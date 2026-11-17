"""Validate generated contracts and classify failures without recording values."""

import hashlib
from datetime import datetime
import json
import math
import re
import uuid

from django.core.exceptions import PermissionDenied, ValidationError

from .capability_catalog import contracts

MAX_ARGUMENT_BYTES = 128 * 1024
MAX_ARGUMENT_DEPTH = 20
MAX_ERRORS = 12


def argument_fingerprint(args):
    try:
        encoded = json.dumps(
            args, ensure_ascii=False, sort_keys=True, allow_nan=False
        ).encode()
    except (ValueError, TypeError, RecursionError):
        encoded = b"invalid-json-arguments"
    return hashlib.sha256(encoded).hexdigest()


class ToolContractError(ValidationError):
    def __init__(self, errors):
        self.field_errors = errors[:MAX_ERRORS]
        super().__init__(
            "工具参数无效："
            + "；".join(
                f"{item['field']} {item['detail']}" for item in self.field_errors
            )
        )


def _json_shape(value, depth=0):
    if depth > MAX_ARGUMENT_DEPTH:
        raise ToolContractError([{"field": "$", "detail": "参数嵌套过深"}])
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ToolContractError([{"field": "$", "detail": "对象键须为文字"}])
        for child in value.values():
            _json_shape(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _json_shape(child, depth + 1)
    elif value is not None and type(value) not in {bool, int, float, str}:
        raise ToolContractError([{"field": "$", "detail": "仅接受JSON值"}])
    elif isinstance(value, float) and not math.isfinite(value):
        raise ToolContractError([{"field": "$", "detail": "数值须为有限值"}])


def _issues(value, schema, path="$", *, depth=0):
    errors = []

    def issue(detail):
        errors.append({"field": path, "detail": detail})

    # These envelopes are checked with the actual algorithm manifest before submission.
    if schema.get("x-business-validation"):
        return []
    expected = schema.get("type")
    types = expected if isinstance(expected, list) else [expected] if expected else []
    matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "number": type(value) in {int, float},
        "boolean": type(value) is bool,
        "null": value is None,
    }
    if types and not any(matches.get(kind, False) for kind in types):
        labels = {
            "integer": "整数",
            "number": "数值",
            "string": "文字",
            "array": "数组",
            "object": "对象",
            "boolean": "布尔值",
            "null": "空值",
        }
        issue(
            schema.get("description", "参数")
            + "；类型须为"
            + "/".join(labels[kind] for kind in types)
        )
        return errors
    if "enum" in schema and value not in schema["enum"]:
        issue("不属于允许的枚举值")
    if "const" in schema and value != schema["const"]:
        issue("与固定值不一致")
    for key, exact in (("oneOf", True), ("anyOf", False)):
        if key in schema:
            count = sum(
                not _issues(value, child, path, depth=depth + 1)
                for child in schema[key]
            )
            if (exact and count != 1) or (not exact and count == 0):
                issue("须符合且仅符合一个参数方案" if exact else "没有符合的参数方案")
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                errors.append({"field": path + "." + name, "detail": "缺少必填参数"})
        if len(value) > schema.get("maxProperties", 100000):
            issue("对象字段数量超过上限")
        for name, child in value.items():
            child_schema = schema.get("properties", {}).get(
                name, schema.get("additionalProperties", True)
            )
            if child_schema is False:
                errors.append({"field": path + "." + name, "detail": "未声明的参数"})
            elif isinstance(child_schema, dict):
                errors.extend(
                    _issues(child, child_schema, path + "." + name, depth=depth + 1)
                )
    if isinstance(value, list):
        if (
            not schema.get("minItems", 0)
            <= len(value)
            <= schema.get("maxItems", 100000)
        ):
            issue("数组数量超出范围")
        if schema.get("uniqueItems") and len(
            {json.dumps(item, sort_keys=True) for item in value}
        ) != len(value):
            issue("不允许重复条目")
        for index, child in enumerate(value):
            errors.extend(
                _issues(
                    child, schema.get("items", {}), f"{path}[{index}]", depth=depth + 1
                )
            )
    if isinstance(value, str):
        if (
            not schema.get("minLength", 0)
            <= len(value)
            <= schema.get("maxLength", 1000000)
        ):
            issue("文字长度超出范围")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            issue("文字格式无效")
        if schema.get("format") == "uuid":
            try:
                uuid.UUID(value)
            except ValueError:
                issue("须为真实UUID格式")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value)
                if "T" not in value or parsed.tzinfo is None:
                    raise ValueError
            except ValueError:
                issue("须为包含时区的日期时间")
    if type(value) in {int, float}:
        if value < schema.get("minimum", -math.inf) or value > schema.get(
            "maximum", math.inf
        ):
            issue("数值超出范围")
    return errors[:MAX_ERRORS]


def validate_arguments(name, args):
    _json_shape(args)
    encoded = json.dumps(
        args, ensure_ascii=False, sort_keys=True, allow_nan=False
    ).encode()
    if len(encoded) > MAX_ARGUMENT_BYTES:
        raise ToolContractError([{"field": "$", "detail": "参数超过128KiB"}])
    errors = _issues(args, contracts()[name]["inputSchema"])
    if errors:
        raise ToolContractError(errors)
    return hashlib.sha256(encoded).hexdigest()


def failure(error, request_id=None):
    from apps.compute.packages import ComputeError
    from django.db import OperationalError

    if isinstance(error, PermissionDenied):
        code, retryable = "PERMISSION_DENIED", False
    elif isinstance(error, (ValidationError, ValueError, TypeError, KeyError)):
        code, retryable = "INVALID_TOOL_ARGUMENTS", False
    elif isinstance(error, OperationalError):
        retryable = any(word in str(error).casefold() for word in ("busy", "locked"))
        code = "SERVICE_BUSY" if retryable else "DATABASE_SCHEMA_ERROR"
    elif isinstance(error, ComputeError):
        code = (
            "OBJECT_NOT_AVAILABLE"
            if error.status == 404
            else "PERMISSION_DENIED"
            if error.status in {401, 403}
            else "REVISION_CONFLICT"
            if error.status == 409
            else "SERVICE_BUSY"
            if error.status in {429, 503}
            else "BUSINESS_VALIDATION_FAILED"
        )
        retryable = error.status in {429, 503}
    else:
        code, retryable = "TOOL_EXECUTION_FAILED", False
    detail = (
        "；".join(error.messages)
        if isinstance(error, ValidationError)
        else str(error)
        if isinstance(error, (PermissionDenied, ComputeError))
        else "工具执行未完成，请依据错误类型处理"
    )
    return {
        "code": code,
        "detail": detail[:1000],
        "retryable": retryable,
        "requestId": str(
            request_id or getattr(error, "tool_request_id", None) or uuid.uuid4()
        ),
        "fieldErrors": getattr(error, "field_errors", []),
    }


def result_refs(result):
    keys = {
        "taskId",
        "workflowId",
        "workspaceId",
        "jobId",
        "resourceId",
        "resourceIds",
        "status",
        "outputId",
        "importId",
    }
    return (
        {key: value for key, value in result.items() if key in keys}
        if isinstance(result, dict)
        else {}
    )
