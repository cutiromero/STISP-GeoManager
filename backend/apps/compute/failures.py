"""受限运行结果的机器可读分类；不向任务公开主机异常文本。"""

import json
import re

from .manifest_v2 import REMEDIES
from .packages import ComputeError

MAX_ERROR_BYTES = 8192
GENERIC_ERRORS = {
    "PLATFORM_CRASH": ("算子未按协议完成执行", "human_review"),
    "PLATFORM_TIMEOUT": ("执行超过平台或算子时限", "adjust_parameters"),
    "PLATFORM_OOM": ("运行进程内存不足", "replace_data"),
    "PLATFORM_INVALID_ERROR": ("算子结构化错误报告无效", "unrecoverable"),
    "PLATFORM_VALIDATION": ("平台输入、权限或输出检查未通过", "human_review"),
    "PLATFORM_INTERRUPTED": ("工作进程中断，本次执行结果不可用", "human_review"),
}


def generic_failure(code):
    message, remedy = GENERIC_ERRORS[code]
    return {
        "code": code,
        "message": message,
        "inputs": [],
        "parameters": [],
        "remedy": remedy,
        "details": {},
    }


def runtime_failure(code, message=None):
    failure = generic_failure(code)
    return ComputeError(message or failure["message"], failure=failure)


def reported_failure(raw, manifest):
    """严格限制报告字节数、结构、清单错误码与输入/参数引用。"""
    invalid = generic_failure("PLATFORM_INVALID_ERROR")
    try:
        if not isinstance(raw, bytes) or len(raw) > MAX_ERROR_BYTES:
            return invalid
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {
            "code",
            "message",
            "inputs",
            "parameters",
            "remedy",
            "details",
        }:
            return invalid
        if (
            not isinstance(value["code"], str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", value["code"])
            or value["code"].startswith("PLATFORM_")
        ):
            return invalid
        declared = {item["code"]: item for item in manifest.get("errors", [])}
        if manifest.get("schemaVersion") == 2 and (
            value["code"] not in declared
            or value["remedy"] != declared[value["code"]]["remedy"]
        ):
            return invalid
        if (
            not isinstance(value["message"], str)
            or not 1 <= len(value["message"]) <= 1000
            or "\x00" in value["message"]
            or value["remedy"] not in REMEDIES
        ):
            return invalid
        for section in ("inputs", "parameters"):
            allowed = {item["key"] for item in manifest[section]}
            if (
                not isinstance(value[section], list)
                or len(value[section]) > 64
                or any(
                    not isinstance(key, str) or key not in allowed
                    for key in value[section]
                )
            ):
                return invalid
        if not isinstance(value["details"], dict):
            return invalid
        json.dumps(value, allow_nan=False)
        return value
    except (ValueError, TypeError, KeyError, RecursionError):
        return invalid


def status_failure(status, manifest, message):
    raw = status.get("operatorError")
    if raw is not None:
        failure = reported_failure(
            json.dumps(raw, ensure_ascii=False).encode(), manifest
        )
    else:
        failure = generic_failure(
            "PLATFORM_OOM"
            if status.get("error_type") in ("MemoryError", "_ArrayMemoryError")
            or status.get("error_category") == "memory"
            else "PLATFORM_TIMEOUT"
            if status.get("error_category") == "timeout"
            else "PLATFORM_CRASH"
        )
    return ComputeError(
        failure["message"] if raw is not None else message, failure=failure
    )
