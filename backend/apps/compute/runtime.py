"""Compute execution backends.

Docker remains available for deployments that can provide it.  AutoDL's
container does not expose the kernel capabilities Docker needs, so production
can use the explicit ``native`` backend: the same trusted runner protocol is
started in a short-lived child process using the configured Python runtime.
"""

import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tarfile
import threading
import time
from functools import lru_cache

from django.conf import settings
from .config import config
from .packages import ComputeError

NATIVE_PACKAGES = (
    "numpy",
    "pandas",
    "rasterio",
    "geopandas",
    "pyogrio",
    "shapely",
    "pyproj",
    "Pillow",
)


def _failure_message(status, *, scripted=False):
    if scripted:
        details = status.get("scriptDiagnostics")
        if isinstance(details, dict) and set(details) == {
            "errorType",
            "message",
            "line",
        }:
            kind, message, line = (
                details[key] for key in ("errorType", "message", "line")
            )
            if (
                isinstance(kind, str)
                and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,63}", kind)
                and isinstance(message, str)
                and len(message) <= 600
                and "\x00" not in message
                and (line is None or type(line) is int and 1 <= line <= 16000)
            ):
                return "适配脚本执行失败：" + json.dumps(details, ensure_ascii=False)
    generic = "算法运行失败，请检查输入条件、参数和算法实现；可在修正后重试"
    error_type = status.get("error_type", "")
    detail = status.get("error_detail", "")
    if not isinstance(error_type, str) or not re.fullmatch(
        r"[A-Za-z_][A-Za-z_0-9]{0,63}", error_type
    ):
        return generic
    if not isinstance(detail, str) or not re.fullmatch(
        r"内存不足(?:：无法分配 \d{1,12}(?:\.\d{1,12})? (?:[KMGT]i?B|bytes))?"
        r"|输入或参数校验失败|缺少输入或依赖|文件读写失败|计算数值异常|算法主动退出|算法执行异常",
        detail,
    ):
        return generic
    return f"算法运行失败：{detail}（{error_type}）"


def command(*args, timeout=15, check=True):
    try:
        result = subprocess.run(
            [*config().command, *args],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ComputeError(
            "Linux容器运行环境未就绪，请联系管理员完成环境部署", 503
        ) from exc
    if check and result.returncode:
        raise ComputeError("容器操作失败，请管理员检查运行环境和镜像", 503)
    return result


def _native_environment():
    cfg = config()
    interpreter = Path(cfg.interpreter).expanduser()
    runner = settings.PROGRAM_ROOT / "deploy" / "compute" / "runner.py"
    if not interpreter.is_file():
        raise ComputeError("本机进程计算环境缺少配置的 Python 解释器", 503)
    if not runner.is_file():
        raise ComputeError("本机进程计算环境缺少算法运行器", 503)
    versions = {}
    for package in NATIVE_PACKAGES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ComputeError(f"本机进程计算环境缺少依赖：{package}", 503) from exc
    identity = {
        "mode": "native",
        "interpreter": str(interpreter.resolve()),
        "python": sys.version,
        "packages": versions,
    }
    digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
    )
    return digest, identity


def _native_state():
    digest, identity = _native_environment()
    return {
        "ready": True,
        "id": "python-geospatial-native-v1",
        "name": "Python 地理计算环境 v1（本机进程）",
        "imageDigest": digest,
        "detail": "本机进程计算环境就绪",
        "packages": identity["packages"],
        "scriptIsolation": script_isolation_status(),
    }


@lru_cache(maxsize=4)
def _script_probe(path, identity):
    spec = importlib.util.spec_from_file_location("platform_script_sandbox_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.probe()


def script_isolation_status():
    if config().mode != "native":
        return {
            "available": False,
            "reason": "当前部署未启用受限脚本解释器",
            "policyVersion": 1,
        }
    path = settings.PROGRAM_ROOT / "deploy/compute/script_sandbox.py"
    if not path.is_file():
        return {
            "available": False,
            "reason": "受限脚本解释器尚未部署",
            "policyVersion": 1,
        }
    stat = path.stat()
    try:
        return dict(
            _script_probe(str(path), (stat.st_ino, stat.st_size, stat.st_mtime_ns))
        )
    except (ImportError, OSError, RuntimeError):
        return {"available": False, "reason": "受限脚本隔离未就绪", "policyVersion": 1}


def inspect_runtime():
    if config().mode == "native":
        try:
            return _native_state()
        except (ComputeError, OSError, ValueError):
            return {
                "ready": False,
                "id": "python-geospatial-native-v1",
                "name": "Python 地理计算环境 v1（本机进程）",
                "imageDigest": "",
                "detail": "本机进程计算环境尚未就绪，请检查 Python 解释器和地理计算依赖",
            }
    try:
        server = (
            command("info", "--format", "{{.OSType}}", timeout=8)
            .stdout.decode()
            .strip()
        )
        if server != "linux":
            raise ComputeError("计算环境必须为Linux容器", 503)
        result = json.loads(
            command("image", "inspect", config().image, timeout=8).stdout
        )[0]
        digest = result["Id"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ComputeError("镜像没有有效的不可变摘要", 503)
        return {
            "ready": True,
            "id": "python-geospatial-v1",
            "name": "Python 地理计算环境 v1",
            "imageDigest": digest,
            "detail": "容器环境就绪",
        }
    except (ComputeError, ValueError, KeyError, IndexError):
        return {
            "ready": False,
            "id": "python-geospatial-v1",
            "name": "Python 地理计算环境 v1",
            "imageDigest": "",
            "detail": "Linux容器环境尚未就绪，请完成WSL2/Docker及计算镜像部署",
        }


def _terminate_process(process):
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def stop_native(root):
    """Stop a native runner left behind by a worker restart."""
    pid_file = Path(root) / ".runner.pid"
    try:
        pid = int(pid_file.read_text(encoding="ascii").strip())
    except (FileNotFoundError, OSError, ValueError):
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
            )
        else:
            os.killpg(pid, signal.SIGTERM)
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        pid_file.unlink()
    except OSError:
        pass


def mount_path(path):
    path = Path(path).resolve()
    if os.name == "nt" and any(
        Path(p).name.lower() in {"wsl", "wsl.exe"} for p in config().command
    ):
        return (
            "/mnt/"
            + path.drive[0].lower()
            + "/"
            + path.as_posix().split(":", 1)[1].lstrip("/")
        )
    return str(path)


def stop_container(name):
    if not re.fullmatch(r"gm-compute-[0-9a-f]{32}", name):
        raise ComputeError("容器标识无效")
    command("rm", "-f", name, check=False)


def _native_preexec(timeout_seconds, memory_mb):
    if os.name == "nt":
        return None

    def apply_limits():
        try:
            import resource

            cpu = max(1, int(timeout_seconds) + 5)
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
            memory = max(256, int(memory_mb)) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
        except (ImportError, OSError, ValueError):
            pass

    return apply_limits


def _native_env(cfg, package, inputs, destination):
    keys = (
        "PATH",
        "PROJ_DATA",
        "GDAL_DATA",
        "GDAL_DRIVER_PATH",
        "PROJ_LIB",
    )
    env = {key: os.environ[key] for key in keys if os.environ.get(key)}
    env.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": str(destination),
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "GEOMANAGER_ALGORITHM_DIR": str(package.resolve()),
            "GEOMANAGER_INPUT_DIR": str(inputs.resolve()),
            "GEOMANAGER_OUTPUT_DIR": str(destination.resolve()),
        }
    )
    return env


def _execute_native(attempt, package, inputs, destination, manifest, heartbeat):
    cfg = config()
    runtime = inspect_runtime()
    if not runtime["ready"]:
        raise ComputeError(runtime["detail"], 503)
    scripted = manifest["runtime"] == "python-data-script-v1"
    runner = (
        settings.PROGRAM_ROOT
        / "deploy/compute"
        / ("script_runner.py" if scripted else "runner.py")
    )
    if scripted:
        isolation = script_isolation_status()
        if not isolation["available"] or not runner.is_file():
            raise ComputeError(isolation.get("reason") or "受限脚本运行器尚未就绪", 503)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", attempt.runtime_digest):
        raise ComputeError("算法版本尚未绑定本机进程运行环境", 503)
    status_path = destination / "__platform_status.json"
    temporary_status = destination / "__platform_status.tmp"
    for path in (status_path, temporary_status):
        path.unlink(missing_ok=True)
    pid_file = package.parent / ".runner.pid"
    command = [
        cfg.interpreter,
        "-I",
        str(runner),
        "--algorithm-dir",
        str(package.resolve()),
        "--input-dir",
        str(inputs.resolve()),
        "--output-dir",
        str(destination.resolve()),
    ]
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=str(package),
        env=_native_env(cfg, package, inputs, destination),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
        creationflags=flags,
        preexec_fn=_native_preexec(
            min(cfg.timeout_seconds, manifest["timeoutSeconds"]), cfg.memory_mb
        ),
    )
    pid_file.write_text(str(process.pid), encoding="ascii")
    started = time.monotonic()
    timeout = min(cfg.timeout_seconds, manifest["timeoutSeconds"])
    try:
        while True:
            heartbeat()
            if time.monotonic() - started > timeout:
                raise ComputeError(f"计算超过{timeout}秒时限，请减少数据规模或调整算法")
            if status_path.is_file():
                raw = status_path.read_bytes()
                if len(raw) > 4096:
                    raise ComputeError("算法返回的状态信息不合法")
                try:
                    status = json.loads(raw)
                except ValueError as exc:
                    raise ComputeError("算法返回的状态信息不合法") from exc
                if status.get("status") != "succeeded":
                    raise ComputeError(_failure_message(status, scripted=scripted))
                break
            if process.poll() is not None:
                raise ComputeError("计算进程提前退出，可能超出内存限制或算法异常")
            time.sleep(0.5)
        heartbeat()
    finally:
        _terminate_process(process)
        pid_file.unlink(missing_ok=True)
        status_path.unlink(missing_ok=True)
        temporary_status.unlink(missing_ok=True)


def execute(attempt, package, inputs, destination, manifest, heartbeat):
    cfg = config()
    if cfg.mode == "native":
        return _execute_native(
            attempt, package, inputs, destination, manifest, heartbeat
        )
    if manifest["runtime"] == "python-data-script-v1":
        raise ComputeError("当前运行环境未配置受限数据脚本；未降级为普通算法执行", 503)
    runtime = inspect_runtime()
    if not runtime["ready"]:
        raise ComputeError(runtime["detail"], 503)
    # A version is pinned to an image by content ID. Retained old images remain runnable.
    digest = attempt.runtime_digest
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ComputeError("算法版本尚未绑定运行镜像", 503)
    name = attempt.container_name
    args = [
        "create",
        "--name",
        name,
        "--label",
        "geomanager.compute=true",
        "--network",
        "none",
        "--read-only",
        "--user",
        "10001:10001",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "64",
        "--cpus",
        "1",
        "--memory",
        f"{cfg.memory_mb}m",
        "--memory-swap",
        f"{cfg.memory_mb}m",
        "--ulimit",
        "nofile=256:256",
        "--log-driver",
        "none",
        "--ipc",
        "none",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=128m,mode=1777",
        "--tmpfs",
        f"/output:rw,noexec,nosuid,size={cfg.output_mb}m,mode=1777",
    ]
    for host, container in [
        (package, "/algorithm"),
        (inputs, "/inputs"),
        (settings.PROGRAM_ROOT / "deploy/compute/runner.py", "/runner.py"),
    ]:
        value = mount_path(host)
        if "," in value:
            raise ComputeError("运行目录不能包含逗号")
        args += ["--mount", f"type=bind,src={value},dst={container},readonly"]
    args += [
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "HOME=/tmp",
        "--env",
        "OPENBLAS_NUM_THREADS=1",
        "--env",
        "OMP_NUM_THREADS=1",
        digest,
        "python",
        "-I",
        "/runner.py",
        "--algorithm-dir",
        "/algorithm",
        "--input-dir",
        "/inputs",
        "--output-dir",
        "/output",
    ]
    created = False
    try:
        command(*args, timeout=30)
        created = True
        command("start", name)
        started = time.monotonic()
        timeout = min(cfg.timeout_seconds, manifest["timeoutSeconds"])
        while True:
            heartbeat()
            if time.monotonic() - started > timeout:
                raise ComputeError(f"计算超过{timeout}秒时限，请减少数据规模或调整算法")
            probe = command(
                "exec",
                name,
                "head",
                "-c",
                "4097",
                "/output/__platform_status.json",
                check=False,
            )
            if probe.returncode == 0:
                if len(probe.stdout) > 4096:
                    raise ComputeError("算法返回的状态信息不合法")
                try:
                    status = json.loads(probe.stdout)
                except ValueError as exc:
                    raise ComputeError("算法返回的状态信息不合法") from exc
                if status.get("status") != "succeeded":
                    raise ComputeError(_failure_message(status))
                break
            running = command(
                "inspect", "--format", "{{.State.Running}}", name
            ).stdout.strip()
            if running != b"true":
                raise ComputeError("计算进程提前退出，可能超出内存限制或算法异常")
            time.sleep(2)
        heartbeat()
        # Read the live mount through the fixed container tar binary: Docker's
        # archive/cp endpoint can omit tmpfs contents. Never dereference links.
        expected = {o["file"] for o in manifest["outputs"]}
        if manifest.get("qualityReport"):
            expected.add(manifest["qualityReport"]["file"])
        proc = subprocess.Popen(
            [
                *cfg.command,
                "exec",
                name,
                "/bin/tar",
                "--format=ustar",
                "--numeric-owner",
                "-C",
                "/output",
                "-cf",
                "-",
                ".",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        total = 0
        seen = set()
        watchdog = threading.Timer(
            120, lambda: proc.kill() if proc.poll() is None else None
        )
        watchdog.daemon = True
        watchdog.start()
        try:
            with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
                for number, member in enumerate(archive):
                    if number > 5000:
                        raise ComputeError("输出文件数量超限")
                    total += member.size
                    if total > cfg.output_mb * 1024**2:
                        raise ComputeError("输出总大小超限")
                    name_in = member.name.removeprefix("./")
                    if name_in not in expected:
                        continue
                    if not member.isfile() or name_in in seen:
                        raise ComputeError("输出须为不重复的普通文件，不允许链接")
                    seen.add(name_in)
                    source = archive.extractfile(member)
                    with (destination / name_in).open("xb") as stream:
                        while chunk := source.read(1024 * 1024):
                            stream.write(chunk)
                            heartbeat()
                    heartbeat()
            if proc.wait(timeout=15):
                raise ComputeError("无法读取计算结果")
        finally:
            watchdog.cancel()
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            if proc.stdout:
                proc.stdout.close()
    finally:
        if created:
            stop_container(attempt.container_name)
