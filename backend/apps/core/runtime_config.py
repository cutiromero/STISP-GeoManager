from __future__ import annotations

from typing import Any

from django.conf import settings

from apps.core.config import (
    ConfigValidationError,
    UPLOAD_MAX_MB_RANGE,
    load_runtime_config_document,
)
from apps.core.platform_brand import canonicalize_platform_name


def runtime_application() -> dict[str, Any]:
    raw = load_runtime_config_document(settings.PROJECT_CONFIG)
    application = raw.get("application")
    if not isinstance(application, dict):
        raise RuntimeConfigError("运行配置缺少 application 节")
    return application


def runtime_system_name() -> str:
    try:
        return canonicalize_platform_name(runtime_application()["system"]["name"])
    except (KeyError, TypeError) as exc:
        raise RuntimeConfigError("无法读取系统名称配置") from exc


def runtime_allow_registration() -> bool:
    try:
        value = runtime_application()["system"]["allow_registration"]
    except (KeyError, TypeError) as exc:
        raise RuntimeConfigError("无法读取注册开关配置") from exc
    if not isinstance(value, bool):
        raise RuntimeConfigError("注册开关配置必须是布尔值")
    return value


def runtime_upload_max_mb() -> int:
    minimum, maximum = UPLOAD_MAX_MB_RANGE
    try:
        value = runtime_application()["limits"]["upload_max_mb"]
    except (
        ConfigValidationError,
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        RuntimeConfigError,
    ):
        return _loaded_upload_max_mb(minimum, maximum)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        return _loaded_upload_max_mb(minimum, maximum)
    return value


def _loaded_upload_max_mb(minimum: int, maximum: int) -> int:
    try:
        value = settings.PROJECT_CONFIG.limits.upload_max_mb
    except AttributeError as exc:
        raise RuntimeConfigError("无法读取上传大小限制") from exc
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise RuntimeConfigError(
            f"上传大小限制必须是 {minimum} 到 {maximum} 之间的整数"
        )
    return value


def runtime_query_result_limit() -> int:
    return runtime_limit_int("query_result_limit", "查询结果上限")


def runtime_max_raster_side_pixels() -> int:
    return runtime_limit_int("max_raster_side_pixels", "栅格单边像素上限")


def runtime_symbolizer_timeout_seconds() -> int:
    try:
        value = int(runtime_application()["raster"]["symbolizer_timeout_seconds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeConfigError("无法读取栅格任务超时限制") from exc
    if value <= 0:
        raise RuntimeConfigError("栅格任务超时限制必须是正整数")
    return value


def runtime_limit_int(key: str, label: str) -> int:
    try:
        value = int(runtime_application()["limits"][key])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeConfigError(f"无法读取{label}") from exc
    if value <= 0:
        raise RuntimeConfigError(f"{label}必须是正整数")
    return value


class RuntimeConfigError(RuntimeError):
    pass
