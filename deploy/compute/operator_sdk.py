"""算子侧轻量协议；只读输入绑定，在输出目录报告有界错误。"""

import json
from pathlib import Path
import re
from functools import wraps
from contextlib import contextmanager
from tempfile import TemporaryDirectory

ERROR_FILE = "__operator_error.json"
MAX_ERROR_BYTES = 8192
REMEDIES = {
    "adjust_parameters",
    "convert_input",
    "complete_mapping",
    "replace_data",
    "human_review",
    "unrecoverable",
}


class OperatorFailure(ValueError):
    pass


def fail(
    context,
    code,
    message,
    *,
    remedy="human_review",
    inputs=(),
    parameters=(),
    details=None,
):
    """写入错误后终止当前算子；不能用于记录警告或成功状态。"""
    if (
        not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", code)
        or code.startswith("PLATFORM_")
        or remedy not in REMEDIES
    ):
        raise ValueError("错误码或补救类别无效")
    value = {
        "code": code,
        "message": message,
        "inputs": list(inputs),
        "parameters": list(parameters),
        "remedy": remedy,
        "details": details or {},
    }
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if (
        len(encoded) > MAX_ERROR_BYTES
        or not isinstance(message, str)
        or not 1 <= len(message) <= 1000
    ):
        raise ValueError("结构化错误过大或说明无效")
    target = context.output_path(ERROR_FILE)
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(target)
    raise OperatorFailure(message)


def field_mapping(context, key):
    """返回语义角色到实际字段名/波段号的绑定，不猜测字段名。"""
    return dict(getattr(context, "field_mappings", {}).get(key, {}))


def repeated_inputs(context, key):
    """返回包含key、label、path和fieldMappings的同类输入列表。"""
    records = getattr(context, "input_collections", {}).get(key, [])
    return [
        {
            **record,
            "path": context.input_path(record["key"]),
            "fieldMappings": field_mapping(context, record["key"]),
        }
        for record in records
    ]


def diagnosed(code="INPUT_INVALID", remedy="replace_data"):
    """为已有校验异常补充协议报告，保留科学计算主体及成功结果。"""

    def decorate(run):
        @wraps(run)
        def wrapped(context):
            try:
                return run(context)
            except OperatorFailure:
                raise
            except (ValueError, TypeError, KeyError) as error:
                fail(
                    context,
                    code,
                    str(error)[:1000] or "输入未通过算子检查",
                    remedy=remedy,
                )

        return wrapped

    return decorate


@contextmanager
def bound_context(context, manifest):
    """仅为迁移清单显式legacyName创建字段别名视图，不修改原件。"""

    class BoundContext:
        def __init__(self, original):
            self.original, self.paths = original, {}

        def __getattr__(self, name):
            return getattr(self.original, name)

        def input_path(self, key):
            return (
                self.paths[key] if key in self.paths else self.original.input_path(key)
            )

        def input_evidence(self, key):
            return None if key in self.paths else self.original.input_evidence(key)

    with TemporaryDirectory(prefix="operator-fields-") as temporary:
        bound = BoundContext(context)
        for spec in manifest.get("inputs", []):
            mapping = field_mapping(context, spec["key"])
            aliases = {
                mapping[field["role"]]: field["legacyName"]
                for field in spec.get("fields", [])
                if field.get("legacyName")
                and field["role"] in mapping
                and mapping[field["role"]] != field["legacyName"]
            }
            if not aliases:
                continue
            source = context.input_path(spec["key"])
            if spec["kind"] == "vector":
                import geopandas as gpd

                frame = gpd.read_file(source)
            elif spec["kind"] == "table":
                import pandas as pd

                frame = pd.read_csv(
                    source, dtype=str, keep_default_na=False, encoding="utf-8-sig"
                )
            else:
                raise ValueError("legacyName仅用于矢量与表格字段迁移")
            if len(set(aliases.values())) != len(aliases) or any(
                target in frame.columns and target not in aliases
                for target in aliases.values()
            ):
                raise ValueError("字段映射产生重名，请先通过输入适配器整理字段")
            frame = frame.rename(columns=aliases)
            target = Path(temporary) / (
                spec["key"] + (".gpkg" if spec["kind"] == "vector" else ".csv")
            )
            if spec["kind"] == "vector":
                frame.to_file(target, layer="data", driver="GPKG", index=False)
            else:
                frame.to_csv(target, index=False, encoding="utf-8-sig")
            bound.paths[spec["key"]] = target
        yield bound
