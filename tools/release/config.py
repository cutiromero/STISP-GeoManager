"""严格加载不含口令的发布配置。"""

from pathlib import Path, PurePosixPath
import os
import re
import stat
import tomllib

if __package__:
    from .server import RUNTIME_INVARIANTS
else:
    from server import RUNTIME_INVARIANTS

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config/release.local.toml"
TIMEOUT_MINIMUMS = {
    "drainSeconds": 900,
    "stopSeconds": 40,
    "healthSeconds": 120,
    "pollSeconds": 2,
    "backupSeconds": 180,
    "managementSeconds": 300,
    "minimumFreeBytes": 536870912,
    "staticPreparationAllowanceBytes": 134217728,
}
SERVER_PATHS = (
    "launcher",
    "productionConfig",
    "python",
    "waitress",
    "appData",
    "researchData",
    "logDir",
    "deployLock",
    "publishLock",
    "releaseParent",
    "opsParent",
    "projData",
    "gdalData",
)
REQUIRED = {
    "ssh": {"host": str, "port": int, "user": str, "options": list},
    "local": {
        "branch": str,
        "pnpm": list,
        "buildResources": list,
        "buildSeconds": int,
        "commandSeconds": int,
        "statusPollSeconds": int,
    },
    "server": {
        **dict.fromkeys(SERVER_PATHS, str),
        "baseUrl": str,
        "healthPath": str,
        **dict.fromkeys(TIMEOUT_MINIMUMS, int),
        "maxArchiveBytes": int,
        "maxExpandedBytes": int,
        **{name: type(value) for name, value in RUNTIME_INVARIANTS.items()},
    },
    "candidate": {"port": int, "commandSeconds": int, "hookSeconds": int},
}
SSH_OPTIONS = (
    "IdentityFile=",
    "UserKnownHostsFile=",
    "ConnectTimeout=",
    "ServerAliveInterval=",
    "ServerAliveCountMax=",
    "IdentitiesOnly=yes",
    "ControlMaster=auto",
    "ControlPersist=60",
    "ControlPath=",
)


class ConfigError(ValueError):
    pass


def load(path=CONFIG_PATH, *, executing=False):
    try:
        value = tomllib.loads(Path(path).read_text())
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"无法读取发布配置 {path}：{type(error).__name__}") from None
    if set(value) != set(REQUIRED):
        raise ConfigError("配置必须且只能包含 ssh、local、server、candidate 四个节")
    for section, fields in REQUIRED.items():
        raw = value[section]
        if not isinstance(raw, dict) or set(raw) != set(fields):
            missing = sorted(set(fields) - set(raw)) if isinstance(raw, dict) else []
            extra = sorted(set(raw) - set(fields)) if isinstance(raw, dict) else []
            raise ConfigError(
                f"配置 {section} 缺项 {missing} 或未知项 {extra}；不接受口令参数"
            )
        for name, kind in fields.items():
            if type(raw[name]) is not kind or (kind is str and not raw[name].strip()):
                raise ConfigError(f"配置 {section}.{name} 类型错误或为空")
            if kind is int and raw[name] <= 0:
                raise ConfigError(f"配置 {section}.{name} 必须为正整数")
    local = value["local"]
    if not local["pnpm"] or any(
        not isinstance(part, str) or not part.strip() or re.search(r"[\r\n\0]", part)
        for part in local["pnpm"]
    ):
        raise ConfigError("local.pnpm 必须为非空命令参数列表")
    for name in local["buildResources"]:
        if (
            not isinstance(name, str)
            or not name
            or PurePosixPath(name).is_absolute()
            or any(part in ("", ".", "..") for part in name.split("/"))
            or re.search(r"[\\:\r\n\0]", name)
        ):
            raise ConfigError("local.buildResources 必须为仓库相对文件路径列表")
    if len(set(local["buildResources"])) != len(local["buildResources"]):
        raise ConfigError("local.buildResources 不可重复")
    ssh = value["ssh"]
    if not re.fullmatch(
        r"[A-Za-z0-9_][A-Za-z0-9_.:-]*", ssh["host"]
    ) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", ssh["user"]):
        raise ConfigError("SSH 主机或用户格式错误")
    if ssh["port"] > 65535 or not value["local"]["branch"].startswith("codex/"):
        raise ConfigError("SSH 端口错误或不是固定个人分支")
    for option in ssh["options"]:
        if (
            not isinstance(option, str)
            or not option.startswith(SSH_OPTIONS)
            or any(char in option for char in "\n\r\0")
        ):
            raise ConfigError("SSH options 仅接受密钥、known_hosts、连接与保活选项")
    controls = [option for option in ssh["options"] if option.startswith("Control")]
    if controls:
        paths = [
            option.removeprefix("ControlPath=")
            for option in controls
            if option.startswith("ControlPath=")
        ]
        if (
            len(controls) != 3
            or "ControlMaster=auto" not in controls
            or "ControlPersist=60" not in controls
            or len(paths) != 1
        ):
            raise ConfigError(
                "SSH 连接复用须同时指定 ControlMaster=auto、ControlPersist=60 和唯一 ControlPath"
            )
        socket = Path(paths[0])
        if (
            not socket.is_absolute()
            or ".." in socket.parts
            or re.search(r"[\s%]", str(socket))
        ):
            raise ConfigError("ControlPath 必须为不含空白、替换符或上跳的绝对路径")
        if executing and (
            not socket.parent.is_dir()
            or socket.parent.is_symlink()
            or socket.is_symlink()
            or stat.S_IMODE(socket.parent.stat().st_mode) & 0o077
            or socket.parent.stat().st_uid != os.getuid()
        ):
            raise ConfigError("ControlPath 的父目录必须由当前用户独占并设为 0700")
    remote = value["server"]
    if any(remote[name] != expected for name, expected in RUNTIME_INVARIANTS.items()):
        raise ConfigError("HTTP、心跳、进程和监听参数须保持样例中的历史精确门禁")
    for name in SERVER_PATHS:
        path_value = PurePosixPath(remote[name])
        if (
            not path_value.is_absolute()
            or ".." in path_value.parts
            or re.search(r"\s", remote[name])
        ):
            raise ConfigError(f"server.{name} 必须为不含空白及上跳的绝对路径")
        if executing and "REPLACE_" in remote[name]:
            raise ConfigError(f"先核实并填写 server.{name} 的占位值")
    for name, minimum in TIMEOUT_MINIMUMS.items():
        if remote[name] < minimum:
            raise ConfigError(f"server.{name} 不得低于历史门禁 {minimum}")
    if (
        remote["maxArchiveBytes"] > 1073741824
        or remote["maxExpandedBytes"] > 4294967296
    ):
        raise ConfigError("归档大小上限不得高于历史门禁")
    if remote["deployLock"] == remote["publishLock"]:
        raise ConfigError("两把发布锁必须不同")
    if (
        remote["baseUrl"] != "http://127.0.0.1:6007"
        or remote["healthPath"] != "/api/health/"
    ):
        raise ConfigError("正式健康检查必须使用已核实的本机 6007 入口")
    candidate = value["candidate"]
    if candidate["port"] in (6007, 19000, 19010, 19020) or candidate["port"] > 65535:
        raise ConfigError("候选端口与正式或受保护服务冲突")
    if candidate["commandSeconds"] != 600 or candidate["hookSeconds"] < 600:
        raise ConfigError("通用候选命令须保持历史 600 秒；自定义钩子不得短于 600 秒")
    return value
