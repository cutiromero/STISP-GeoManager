"""Postconditions checked by the platform, independent of generated Python."""

from .packages import ComputeError


def read_contract(manifest, parameters):
    import json

    cap = manifest["inputScriptBridge"]
    value = json.loads(parameters[cap["contractParameter"]])
    if not isinstance(value, dict):
        raise ComputeError("脚本目标规范须为对象")
    fields = value.get("requiredFields", [])
    if (
        not isinstance(fields, list)
        or len(fields) > 80
        or any(
            not isinstance(field, str) or not field or len(field) > 160
            for field in fields
        )
    ):
        raise ComputeError("脚本目标字段规范无效")
    semantics = value.get("semanticType", "")
    if not isinstance(semantics, str) or len(semantics) > 100:
        raise ComputeError("脚本目标语义无效")
    if "minBands" in value and (
        type(value["minBands"]) is not int or not 0 <= value["minBands"] <= 1024
    ):
        raise ComputeError("脚本目标波段数无效")
    if "dataTypes" in value and (
        not isinstance(value["dataTypes"], list)
        or any(not isinstance(kind, str) for kind in value["dataTypes"])
    ):
        raise ComputeError("脚本目标类型列表无效")
    if "geometryTypes" in value and (
        not isinstance(value["geometryTypes"], list)
        or any(not isinstance(kind, str) for kind in value["geometryTypes"])
    ):
        raise ComputeError("脚本目标几何列表无效")
    return value


def validate_metadata(metadata, kind, contract):
    if not contract:
        return
    target_types = contract.get("dataTypes", [kind])
    if kind not in target_types:
        raise ComputeError("实际脚本结果类型不符合冻结目标")
    missing = set(contract.get("requiredFields", [])) - set(metadata.get("fields", []))
    if missing:
        raise ComputeError("适配结果缺少目标字段：" + ", ".join(sorted(missing)))
    if contract.get("minBands", 0) > metadata.get("bands", 0):
        raise ComputeError("适配结果未提供目标要求的全部波段")
    if (
        contract.get("geometryTypes")
        and metadata.get("geometryType") not in contract["geometryTypes"]
    ):
        raise ComputeError("适配结果的实际几何类型不符合输入规范")
    if contract.get("semanticType") == "class_mask_stack_v1":
        names = metadata.get("bandNames", [])
        if (
            kind != "raster"
            or metadata.get("inputSemantics") != "class_mask_stack_v1"
            or not names
            or len(names) != len(set(names))
            or any(not name or len(name) > 160 for name in names)
        ):
            raise ComputeError(
                "类别掩膜须保留实际唯一波段名称及class_mask_stack_v1语义标签"
            )
        if metadata.get("nodata") not in {"255", "255.0"}:
            raise ComputeError("类别掩膜须保留NoData=255")
