from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any

import tomlkit
from tomlkit.exceptions import TOMLKitError

APP_SUBDIRS = (
    "database",
    "media",
    "uploads",
    "exports",
    "logs",
    "static",
    "config",
    "backups",
)
RESEARCH_SUBDIRS = (
    "vector",
    "raster",
    "raster/original",
    "raster/preprocessed",
    "raster/metadata/source",
    "raster/metadata/preprocessed",
    "gene",
    "table",
)
CONFIG_ARG_NAMES = ("--config", "--app-config")
CONFIG_POINTER = Path(".runtime/config-path")
DEFAULT_CONFIG_CANDIDATES = (
    Path("config/app.test.toml"),
    Path("config/app.example.toml"),
)
INTERNAL_DEFAULT_SYMBOLIZER_SCRIPT = "scripts/raster_symbolizers/basic_gradient.py"
UPLOAD_MAX_MB_RANGE = (1, 1024)

_CONFIG_LOCKS_GUARD = threading.Lock()
_CONFIG_LOCKS: dict[Path, threading.RLock] = {}


class ConfigValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeConfig:
    debug: bool
    allowed_hosts: tuple[str, ...]
    csrf_trusted_origins: tuple[str, ...]
    waitress_host: str
    waitress_port: int
    waitress_threads: int
    disable_catalog_startup_scan: bool
    disable_raster_startup_scan: bool


@dataclass(frozen=True)
class MapConfig:
    default_center: tuple[float, float]
    default_zoom: float
    default_basemap: str
    mapbox_access_token: str
    tianditu_access_token: str


@dataclass(frozen=True)
class LimitConfig:
    upload_max_mb: int
    query_result_limit: int
    max_raster_side_pixels: int


@dataclass(frozen=True)
class RasterConfig:
    symbolizer_timeout_seconds: int
    symbolizer_script: str = INTERNAL_DEFAULT_SYMBOLIZER_SCRIPT


@dataclass(frozen=True)
class ProjectConfig:
    config_path: Path
    runtime: RuntimeConfig
    system_name: str
    allow_registration: bool
    app_data: Path
    research_data_root: Path
    map: MapConfig
    limits: LimitConfig
    raster: RasterConfig

    def app_path(self, *parts: str) -> Path:
        return self.app_data.joinpath(*parts)

    def research_path(self, *parts: str) -> Path:
        return self.research_data_root.joinpath(*parts)


def metadata_database_path(config: ProjectConfig) -> Path:
    return config.app_path("database", "meta.db")


def persist_config_argument(argv: list[str], program_root: Path) -> Path | None:
    config_path: str | None = None
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg in CONFIG_ARG_NAMES:
            if index + 1 >= len(argv):
                raise ConfigValidationError(f"{arg} 缺少配置文件路径")
            config_path = argv[index + 1]
            del argv[index : index + 2]
            continue
        matched_name = next(
            (name for name in CONFIG_ARG_NAMES if arg.startswith(f"{name}=")), None
        )
        if matched_name:
            config_path = arg.split("=", 1)[1]
            del argv[index]
            continue
        index += 1

    if not config_path:
        return None

    path = _resolve_user_path(config_path)
    pointer_path = program_root.joinpath(CONFIG_POINTER)
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(str(path), encoding="utf-8")
    return path


def resolve_config_path(program_root: Path) -> Path:
    program_root = program_root.expanduser().resolve()
    pointer_path = program_root.joinpath(CONFIG_POINTER)
    if pointer_path.exists():
        configured_path = pointer_path.read_text(encoding="utf-8").strip()
        if configured_path:
            return _resolve_user_path(configured_path)

    for candidate in DEFAULT_CONFIG_CANDIDATES:
        path = program_root / candidate
        if path.exists():
            return path.resolve()

    raise ConfigValidationError(
        "未提供 TOML 配置文件。请通过 --config /path/to/app.toml 指定配置文件。"
    )


def load_project_config(config_path: Path, program_root: Path) -> ProjectConfig:
    source_path = config_path.expanduser().resolve()
    program_root = program_root.expanduser().resolve()
    raw = _load_toml_document(source_path)

    runtime = _runtime_config(_table(raw, "runtime"))
    application = _table(raw, "application")
    system = _table(application, "system")
    storage = _table(application, "storage")
    map_config = _table(application, "map")
    limits = _table(application, "limits")
    raster = _table(application, "raster")

    app_root = _absolute_path(storage.get("app_data"), "application.storage.app_data")
    research_root = _absolute_path(
        storage.get("research_data_root"),
        "application.storage.research_data_root",
    )
    _validate_separate_roots(program_root, app_root, research_root)

    project_config = ProjectConfig(
        config_path=source_path,
        runtime=runtime,
        system_name=_string(system.get("name"), "application.system.name"),
        allow_registration=_bool(
            system.get("allow_registration", False),
            "application.system.allow_registration",
        ),
        app_data=app_root,
        research_data_root=research_root,
        map=MapConfig(
            default_center=_center(map_config.get("default_center")),
            default_zoom=_finite_float(
                map_config.get("default_zoom", 4.5),
                "application.map.default_zoom",
            ),
            default_basemap=_string(
                map_config.get("default_basemap"),
                "application.map.default_basemap",
            ),
            mapbox_access_token=validate_mapbox_browser_token(
                map_config.get("mapbox_access_token", ""),
                "application.map.mapbox_access_token",
            ),
            tianditu_access_token=validate_tianditu_browser_key(
                map_config.get("tianditu_access_token", ""),
                "application.map.tianditu_access_token",
            ),
        ),
        limits=LimitConfig(
            upload_max_mb=_bounded_int(
                limits.get("upload_max_mb"),
                "application.limits.upload_max_mb",
                *UPLOAD_MAX_MB_RANGE,
            ),
            query_result_limit=_positive_int(
                limits.get("query_result_limit"),
                "application.limits.query_result_limit",
            ),
            max_raster_side_pixels=_positive_int(
                limits.get("max_raster_side_pixels"),
                "application.limits.max_raster_side_pixels",
            ),
        ),
        raster=RasterConfig(
            symbolizer_timeout_seconds=_positive_int(
                raster.get("symbolizer_timeout_seconds"),
                "application.raster.symbolizer_timeout_seconds",
            ),
        ),
    )
    _prepare_fixed_directories(project_config)
    return project_config


def load_runtime_config_document(config: ProjectConfig) -> dict[str, Any]:
    """直接读取源配置,不再使用运行时副本。"""
    return _load_toml_document(config.config_path)


def write_runtime_config_document(config: ProjectConfig, raw: dict[str, Any]) -> None:
    """原子写入源配置，避免并发或中断写入损坏 TOML。"""
    with _config_file_lock(config.config_path):
        _write_runtime_config_document_atomic(config.config_path, raw)


def update_runtime_application_config(
    config: ProjectConfig,
    patch: dict[str, Any],
) -> dict[str, Any]:
    with _config_file_lock(config.config_path):
        raw = load_runtime_config_document(config)
        application = _table(raw, "application")
        _deep_update(application, patch)
        write_runtime_config_document(config, raw)
        return raw


def _config_file_lock(path: Path) -> threading.RLock:
    resolved_path = path.expanduser().resolve()
    with _CONFIG_LOCKS_GUARD:
        lock = _CONFIG_LOCKS.get(resolved_path)
        if lock is None:
            lock = threading.RLock()
            _CONFIG_LOCKS[resolved_path] = lock
        return lock


def _write_runtime_config_document_atomic(
    path: Path,
    raw: dict[str, Any],
) -> None:
    serialized = tomlkit.dumps(raw)
    target_path = path.expanduser().resolve()
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            dir=target_path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        _load_toml_document(temporary_path)
        os.replace(temporary_path, target_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _load_toml_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigValidationError(f"TOML 配置文件不存在：{path}")

    try:
        raw = tomlkit.parse(path.read_text(encoding="utf-8"))
    except TOMLKitError as exc:
        raise ConfigValidationError(f"TOML 配置格式错误：{exc}") from exc

    if not _is_toml_table(raw):
        raise ConfigValidationError("TOML 配置文件根节点必须是对象")
    return raw


def _runtime_config(raw: dict[str, Any]) -> RuntimeConfig:
    return RuntimeConfig(
        debug=_bool(raw.get("debug", False), "runtime.debug"),
        allowed_hosts=_string_tuple(
            raw.get("allowed_hosts", ["*"]), "runtime.allowed_hosts"
        ),
        csrf_trusted_origins=_string_tuple(
            raw.get("csrf_trusted_origins", []),
            "runtime.csrf_trusted_origins",
        ),
        waitress_host=_string(
            raw.get("waitress_host", "0.0.0.0"),
            "runtime.waitress_host",
        ),
        waitress_port=_positive_int(
            raw.get("waitress_port", 8000),
            "runtime.waitress_port",
        ),
        waitress_threads=_positive_int(
            raw.get("waitress_threads", 4),
            "runtime.waitress_threads",
        ),
        disable_catalog_startup_scan=_bool(
            raw.get("disable_catalog_startup_scan", False),
            "runtime.disable_catalog_startup_scan",
        ),
        disable_raster_startup_scan=_bool(
            raw.get("disable_raster_startup_scan", False),
            "runtime.disable_raster_startup_scan",
        ),
    )


def _table(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not _is_toml_table(value):
        raise ConfigValidationError(f"缺少 TOML 配置段：{key}")
    return value


def _string(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigValidationError(f"配置项 {key} 必须是非空字符串")
    return value.strip()


def _optional_string(value: Any, key: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigValidationError(f"配置项 {key} 必须是字符串")
    return value.strip()


def validate_mapbox_browser_token(value: Any, key: str) -> str:
    token = _optional_string(value, key)
    if token and not token.startswith("pk."):
        raise ConfigValidationError(
            f"配置项 {key} 只允许 Mapbox pk.* 浏览器公开 Token，"
            "不得填写 sk.* 私密 Token"
        )
    return token


def validate_tianditu_browser_key(value: Any, key: str) -> str:
    token = _optional_string(value, key)
    if token and not re.fullmatch(r"[A-Za-z0-9]{32}", token):
        raise ConfigValidationError(
            f"配置项 {key} 必须是天地图控制台签发的 32 位浏览器 Key"
        )
    return token


def sanitized_public_map_credentials(map_config: dict[str, Any]) -> tuple[str, str]:
    """Return only browser credentials that are safe for public serialization."""
    try:
        mapbox_token = validate_mapbox_browser_token(
            map_config.get("mapbox_access_token", ""),
            "application.map.mapbox_access_token",
        )
    except ConfigValidationError:
        mapbox_token = ""

    try:
        tianditu_key = validate_tianditu_browser_key(
            map_config.get("tianditu_access_token", ""),
            "application.map.tianditu_access_token",
        )
    except ConfigValidationError:
        tianditu_key = ""

    return mapbox_token, tianditu_key


def _string_tuple(value: Any, key: str) -> tuple[str, ...]:
    if not _is_toml_array(value):
        raise ConfigValidationError(f"配置项 {key} 必须是字符串数组")
    return tuple(_string(item, f"{key}[]") for item in value)


def _positive_int(value: Any, key: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ConfigValidationError(f"配置项 {key} 必须是正整数")
    return value


def _bounded_int(value: Any, key: str, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise ConfigValidationError(
            f"配置项 {key} 必须是 {minimum} 到 {maximum} 之间的整数"
        )
    return value


def _bool(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigValidationError(f"配置项 {key} 必须是布尔值")
    return value


def _finite_float(value: Any, key: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(f"配置项 {key} 必须是有效数字") from exc
    if not math.isfinite(number):
        raise ConfigValidationError(f"配置项 {key} 必须是有效数字")
    return number


def _absolute_path(value: Any, key: str) -> Path:
    path_text = _string(value, key)
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        raise ConfigValidationError(f"配置项 {key} 必须是绝对路径")
    return path.resolve()


def _center(value: Any) -> tuple[float, float]:
    if not _is_toml_array(value) or len(value) != 2:
        raise ConfigValidationError(
            "配置项 application.map.default_center 必须是 [经度, 纬度]"
        )
    lon = _finite_float(value[0], "application.map.default_center[0]")
    lat = _finite_float(value[1], "application.map.default_center[1]")
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ConfigValidationError(
            "配置项 application.map.default_center 超出经纬度范围"
        )
    return lon, lat


def _validate_separate_roots(
    program_root: Path, app_root: Path, research_root: Path
) -> None:
    roots = {
        "业务数据总目录": app_root,
        "科研数据总目录": research_root,
    }
    seen: dict[Path, str] = {}
    for label, root in roots.items():
        if root in seen:
            raise ConfigValidationError(f"{seen[root]}和{label}不能相同")
        seen[root] = label
        if _is_relative_to(root, program_root):
            raise ConfigValidationError(f"{label}不能位于程序目录内")
    root_items = list(roots.items())
    for index, (label, root) in enumerate(root_items):
        for other_label, other_root in root_items[index + 1 :]:
            if _is_relative_to(root, other_root) or _is_relative_to(other_root, root):
                raise ConfigValidationError(f"{label}和{other_label}不能互为上下级目录")


def _prepare_fixed_directories(config: ProjectConfig) -> None:
    required_paths = [
        *(config.app_path(subdir) for subdir in APP_SUBDIRS),
        *(config.research_path(subdir) for subdir in RESEARCH_SUBDIRS),
    ]
    for directory in required_paths:
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.exists() or not directory.is_dir():
            raise ConfigValidationError(f"固定子目录不存在：{directory}")


def _resolve_user_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _deep_update(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and _is_toml_table(target.get(key)):
            _deep_update(target[key], value)
        else:
            target[key] = value


def _is_toml_table(value: Any) -> bool:
    return (
        hasattr(value, "get")
        and hasattr(value, "items")
        and hasattr(value, "__setitem__")
        and not isinstance(value, (str, bytes, list, tuple))
    )


def _is_toml_array(value: Any) -> bool:
    return (
        hasattr(value, "__iter__")
        and hasattr(value, "__len__")
        and not _is_toml_table(value)
        and not isinstance(value, (str, bytes))
    )
