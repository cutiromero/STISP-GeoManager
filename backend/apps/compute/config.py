from dataclasses import dataclass
import sys
import tomllib

from django.conf import settings


@dataclass(frozen=True)
class ComputeConfig:
    mode: str = "docker"
    interpreter: str = ""
    command: tuple[str, ...] = ("docker",)
    image: str = "geomanager-compute:1"
    memory_mb: int = 2048
    timeout_seconds: int = 1800
    input_mb: int = 1024
    output_mb: int = 1024
    retention_days: int = 7
    user_queue: int = 3
    global_queue: int = 20


def config():
    with settings.PROJECT_CONFIG.config_path.open("rb") as stream:
        raw = tomllib.load(stream).get("compute", {})
    mode = str(raw.get("mode", "docker")).strip().lower()
    if mode not in {"docker", "native"}:
        raise ValueError("compute.mode 必须为 docker 或 native")
    interpreter = str(raw.get("interpreter") or sys.executable)
    command = raw.get("command", ["docker"])
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(v, str) and v for v in command)
    ):
        raise ValueError("compute.command 必须为运行时命令参数数组")
    values = {}
    for key, maximum in [
        ("memory_mb", 8192),
        ("timeout_seconds", 7200),
        ("input_mb", 1024),
        ("output_mb", 2048),
        ("retention_days", 90),
        ("user_queue", 10),
        ("global_queue", 100),
    ]:
        values[key] = max(
            1, min(int(raw.get(key, getattr(ComputeConfig, key))), maximum)
        )
    return ComputeConfig(
        mode=mode,
        interpreter=interpreter,
        command=tuple(command),
        image=str(raw.get("image", "geomanager-compute:1")),
        **values,
    )
