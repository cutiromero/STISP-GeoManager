"""Launch/reuse only the identified private WeKnora Lite process on Linux."""

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import urllib.request


class LaunchError(RuntimeError):
    pass


def alive(pid):
    try:
        return pid is not None and bool(Path(f"/proc/{pid}/cmdline").read_bytes())
    except FileNotFoundError:
        return False


def identity(pid, root, home):
    process = Path(f"/proc/{pid}")
    binary = root / "WeKnora-lite"
    try:
        argv = process.joinpath("cmdline").read_bytes().rstrip(b"\0").split(b"\0")
        return (
            argv == [str(binary).encode()]
            and process.joinpath("exe").resolve() == binary
            and process.joinpath("cwd").resolve() == home
        )
    except OSError:
        return False


def port_open(port):
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def owns_listener(pid, port):
    expected = f"0100007F:{port:04X}"
    try:
        inodes = {
            line.split()[9]
            for line in Path("/proc/net/tcp").read_text().splitlines()[1:]
            if line.split()[1] == expected and line.split()[3] == "0A"
        }
        sockets = {f"socket:[{inode}]" for inode in inodes}
        for descriptor in Path(f"/proc/{pid}/fd").iterdir():
            with contextlib.suppress(OSError):
                if os.readlink(descriptor) in sockets:
                    return True
    except OSError:
        return False
    return False


def healthy(port):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            return json.loads(response.read(8193)).get("status") == "ok"
    except (OSError, ValueError, AttributeError):
        return False


def environment(home):
    path = home / "secrets.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise LaunchError("secrets.json must be a private regular file (0600)")
    secret = json.loads(path.read_text())
    if not secret.get("jwt_secret") or not secret.get("aes_key"):
        raise LaunchError("WeKnora secrets are incomplete")
    env = {
        **os.environ,
        "GIN_MODE": "release",
        "LOG_LEVEL": "warn",
        "DB_DRIVER": "sqlite",
        "DB_PATH": str(home / "data/weknora.db"),
        "RETRIEVE_DRIVER": "sqlite",
        "STORAGE_TYPE": "local",
        "LOCAL_STORAGE_BASE_DIR": str(home / "data/files"),
        "STREAM_MANAGER_TYPE": "memory",
        "JWT_SECRET": secret["jwt_secret"],
        "SYSTEM_AES_KEY": secret["aes_key"],
        "NEO4J_ENABLE": "false",
        "ENABLE_GRAPH_RAG": "false",
        "WEKNORA_SANDBOX_MODE": "disabled",
        "CONCURRENCY_POOL_SIZE": "2",
        "SSRF_WHITELIST": "127.0.0.1",
        "WEKNORA_LANGUAGE": "zh-CN",
        "DISABLE_REGISTRATION": "true" if secret.get("api_key") else "false",
    }
    for name in ("REDIS_ADDR", "DOCREADER_ADDR"):
        env.pop(name, None)
    return env


def wait_ready(pid, root, home, port, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not alive(pid) or not identity(pid, root, home):
            raise LaunchError("WeKnora exited or identity differs; inspect service.log")
        if port_open(port):
            if not owns_listener(pid, port):
                raise LaunchError(
                    "Port belongs to another process; no process was stopped"
                )
            if healthy(port):
                return
        time.sleep(0.25)
    raise LaunchError(
        "WeKnora is not ready within timeout; process retained for inspection"
    )


def ensure(root, label, timeout=45, stop=False):
    home = root / label
    port = 19020 if label == "production" else 19021
    pidfile = home / "service.pid"
    pid = None
    if pidfile.exists():
        if pidfile.is_symlink():
            raise LaunchError("PID file must be regular")
        try:
            raw = pidfile.read_text().strip()
            pid = int(raw)
            if pid < 2 or len(raw) > 16:
                raise ValueError
        except ValueError:
            raise LaunchError("Invalid WeKnora PID record") from None
    if alive(pid):
        if not identity(pid, root, home):
            raise LaunchError("Recorded PID is unrelated; no process was changed")
        if port_open(port) and not owns_listener(pid, port):
            raise LaunchError("Port belongs to another process; no process was changed")
        if stop:
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + timeout
            while alive(pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            if alive(pid):
                raise LaunchError("WeKnora has not exited; no force-kill issued")
            pidfile.unlink()
            return {"status": "stopped", "label": label, "pid": pid}
        wait_ready(pid, root, home, port, timeout)
        return {"status": "ready", "started": False, "label": label, "pid": pid}
    if port_open(port):
        raise LaunchError(
            "Port is occupied without a matching PID; no process was changed"
        )
    if stop:
        if pid is not None:
            pidfile.unlink()
        return {"status": "stopped", "label": label, "pid": None}
    binary = root / "WeKnora-lite"
    if not binary.is_file() or not (home / "config/config.yaml").is_file():
        raise LaunchError("WeKnora binary/configuration is missing")
    with (home / "service.log").open("ab") as log:
        process = subprocess.Popen(
            [str(binary)],
            cwd=home,
            env=environment(home),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    temporary = home / f"service.pid.{os.getpid()}.tmp"
    temporary.write_text(str(process.pid))
    temporary.replace(pidfile)
    wait_ready(process.pid, root, home, port, timeout)
    return {"status": "ready", "started": True, "label": label, "pid": process.pid}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument(
        "--label", choices=("production", "candidate"), default="production"
    )
    parser.add_argument("--timeout", type=int, default=45, choices=range(1, 61))
    parser.add_argument("--stop", action="store_true")
    options = parser.parse_args()
    try:
        root = options.root.resolve(strict=True)
        home = root / options.label
        if home.is_symlink():
            raise LaunchError("Service directory must not be a symlink")
        with (home / "startup.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = ensure(root, options.label, options.timeout, options.stop)
        print(json.dumps(result))
        return 0
    except (LaunchError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "detail": str(exc)
                    if isinstance(exc, LaunchError)
                    else "WeKnora configuration or process check failed",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
