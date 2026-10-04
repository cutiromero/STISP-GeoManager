"""Idempotent Linux launcher for the private BGE-M3 embedding process."""

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request

HOST = "127.0.0.1"
PORT = 19010
MODEL = "BAAI/bge-m3"
GPU = "4"
ARGS = [
    "-m",
    "uvicorn",
    "embedding_server:app",
    "--host",
    HOST,
    "--port",
    str(PORT),
    "--workers",
    "1",
]


class LaunchError(RuntimeError):
    pass


def read_environment(root):
    path = root / "embedding.env"
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise LaunchError("embedding.env 必须为仅服务账号可读写的普通文件（600）")
    if path.stat().st_size > 16384:
        raise LaunchError("embedding.env 大小无效")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise LaunchError("embedding.env 格式无效")
        key, value = line.split("=", 1)
        key = key.strip()
        if key in values or not key or "\x00" in value:
            raise LaunchError("embedding.env 存在重复或无效配置")
        values[key] = value
    if not values.get("KNOWLEDGE_EMBEDDING_API_KEY"):
        raise LaunchError("embedding.env 缺少服务密钥")
    model_path = Path(values.get("KNOWLEDGE_EMBEDDING_MODEL_PATH", ""))
    if not model_path.is_absolute() or not (model_path / "config.json").is_file():
        raise LaunchError("embedding.env 中的模型目录未就绪")
    if values.get("CUDA_VISIBLE_DEVICES") != GPU:
        raise LaunchError("向量服务仅使用已指定的 GPU 4，请检查配置")
    return values


def read_pid(root):
    path = root / "embedding.pid"
    if not path.exists():
        return None
    if path.is_symlink():
        raise LaunchError("PID 文件不能为链接")
    try:
        raw = path.read_text(encoding="ascii").strip()
        if len(raw) > 16:
            raise ValueError
        pid = int(raw)
        if pid < 2:
            raise ValueError
        return pid
    except (OSError, ValueError):
        raise LaunchError("PID 文件无效，请核对服务记录") from None


def alive(pid):
    if pid is None:
        return False
    try:
        return bool((Path("/proc") / str(pid) / "cmdline").read_bytes())
    except FileNotFoundError:
        return False


def matches_identity(pid, root, interpreter, config):
    process = Path("/proc") / str(pid)
    try:
        command = (
            process.joinpath("cmdline").read_bytes().rstrip(b"\x00").split(b"\x00")
        )
        if not command:
            return False
        command = [value.decode() for value in command]
        if command[1:] != ARGS or Path(command[0]).resolve() != interpreter:
            return False
        if (
            process.joinpath("exe").resolve() != interpreter
            or process.joinpath("cwd").resolve() != root
        ):
            return False
        environment = dict(
            value.split(b"=", 1)
            for value in process.joinpath("environ").read_bytes().split(b"\x00")
            if b"=" in value
        )
        return (
            environment.get(b"CUDA_VISIBLE_DEVICES") == GPU.encode()
            and environment.get(b"KNOWLEDGE_EMBEDDING_MODEL_PATH")
            == config["KNOWLEDGE_EMBEDDING_MODEL_PATH"].encode()
            and secrets.compare_digest(
                environment.get(b"KNOWLEDGE_EMBEDDING_API_KEY", b""),
                config["KNOWLEDGE_EMBEDDING_API_KEY"].encode(),
            )
        )
    except (OSError, ValueError, UnicodeError):
        return False


def port_open():
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((HOST, PORT)) == 0


def owns_listener(pid):
    """Require the actual listening socket, not just a matching health response."""
    expected = f"0100007F:{PORT:04X}"
    inodes = set()
    try:
        for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
            fields = line.split()
            if fields[1] == expected and fields[3] == "0A":
                inodes.add(fields[9])
        for descriptor in (Path("/proc") / str(pid) / "fd").iterdir():
            with contextlib.suppress(OSError):
                if os.readlink(descriptor) in {f"socket:[{inode}]" for inode in inodes}:
                    return True
    except OSError:
        return False
    return False


def healthy(config):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://{HOST}:{PORT}/health", timeout=2) as response:
            data = json.loads(response.read(8193))
        if (
            data.get("status") != "ok"
            or data.get("ready") is not True
            or data.get("model") != MODEL
        ):
            return False
        request = urllib.request.Request(
            f"http://{HOST}:{PORT}/v1/models",
            headers={
                "Authorization": "Bearer " + config["KNOWLEDGE_EMBEDDING_API_KEY"]
            },
        )
        with opener.open(request, timeout=2) as response:
            models = json.loads(response.read(8193))
        return any(item.get("id") == MODEL for item in models.get("data", []))
    except (OSError, ValueError, TypeError, AttributeError, urllib.error.URLError):
        return False


def wait_ready(pid, root, interpreter, config, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not alive(pid) or not matches_identity(pid, root, interpreter, config):
            raise LaunchError("向量进程已退出或身份不符，请查看受控运行日志")
        if port_open():
            if not owns_listener(pid):
                raise LaunchError("19010 端口由其他进程占用，未停止或替换该进程")
            if healthy(config):
                return
        time.sleep(0.5)
    raise LaunchError("模型尚未在时限内就绪，保留原进程供检查；可稍后再次调用")


def ensure(root, interpreter, timeout=45, stop=False):
    config = read_environment(root)
    pid = read_pid(root)
    if alive(pid):
        if not matches_identity(pid, root, interpreter, config):
            raise LaunchError("记录的 PID 不属于此向量服务，未停止或替换任何进程")
        if port_open() and not owns_listener(pid):
            raise LaunchError("19010 端口由其他进程占用，未停止或替换该进程")
        if stop:
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + timeout
            while alive(pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            if alive(pid):
                raise LaunchError("向量服务尚未退出，保留 PID；未发送强制终止信号")
            (root / "embedding.pid").unlink()
            return {"status": "stopped", "pid": pid, "model": MODEL}
        wait_ready(pid, root, interpreter, config, timeout)
        return {
            "status": "ready",
            "started": False,
            "pid": pid,
            "model": MODEL,
            "port": PORT,
            "gpu": GPU,
        }
    if port_open():
        raise LaunchError("19010 端口已被其他身份占用，未创建或停止任何进程")
    if stop:
        if pid is not None:
            (root / "embedding.pid").unlink()
        return {"status": "stopped", "pid": None, "model": MODEL}
    if not (root / "embedding_server.py").is_file() or not interpreter.is_file():
        raise LaunchError("向量服务代码或指定 Python 未就绪")
    env = {
        **os.environ,
        **config,
        "PYTHONNOUSERSITE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_OFFLINE": "1",
    }
    with (root / "embedding.log").open("ab") as log:
        process = subprocess.Popen(
            [str(interpreter), *ARGS],
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    pid = process.pid
    temporary = root / f"embedding.pid.{os.getpid()}.tmp"
    temporary.write_text(str(pid), encoding="ascii")
    temporary.replace(root / "embedding.pid")
    wait_ready(pid, root, interpreter, config, timeout)
    return {
        "status": "ready",
        "started": True,
        "pid": pid,
        "model": MODEL,
        "port": PORT,
        "gpu": GPU,
    }


def main():
    parser = argparse.ArgumentParser(description="启动或复用本地 BGE-M3 向量服务")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True, dest="interpreter")
    parser.add_argument(
        "--timeout", type=int, default=45, choices=range(1, 61), metavar="1..60"
    )
    parser.add_argument(
        "--stop", action="store_true", help="仅停止身份完全匹配的此向量服务"
    )
    options = parser.parse_args()
    try:
        root = options.root.resolve(strict=True)
        interpreter = options.interpreter.resolve(strict=True)
        with (root / "embedding-start.lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            result = ensure(root, interpreter, options.timeout, options.stop)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (LaunchError, OSError) as exc:
        detail = (
            str(exc)
            if isinstance(exc, LaunchError)
            else "向量服务运行目录或进程检查失败，请检查本机权限与配置"
        )
        print(json.dumps({"status": "error", "detail": detail}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
