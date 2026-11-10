"""Pure validation for registered, portable input conversion capabilities."""

from copy import deepcopy


def validate_capability(manifest):
    """The annotation grants no extra files, tools, authority or executable code."""
    value = manifest.get("inputAdapter")
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {
        "inputKey",
        "outputKey",
        "sourceKind",
        "targetKind",
        "targetSemantics",
        "fieldHints",
        "fieldTargets",
        "outputFields",
        "description",
        "metadataParameters",
    }:
        raise ValueError("inputAdapter能力声明无效")
    inputs = {item["key"]: item for item in manifest["inputs"]}
    outputs = {item["key"]: item for item in manifest["outputs"]}
    source, target = (
        inputs.get(value.get("inputKey")),
        outputs.get(value.get("outputKey")),
    )
    if (
        not source
        or not target
        or value.get("sourceKind") != source["kind"]
        or value.get("targetKind") != target["kind"]
    ):
        raise ValueError("适配能力必须对应本算子的真实输入与输出")
    if any(
        item.get("required", True) and item["key"] != source["key"]
        for item in inputs.values()
    ):
        raise ValueError("自动输入适配器只能有一个必需来源，其他输入须可选")
    semantics = value.get("targetSemantics", "")
    if not isinstance(semantics, str) or len(semantics) > 100:
        raise ValueError("适配目标语义无效")
    parameters = {item["key"]: item for item in manifest["parameters"]}
    if not isinstance(value.get("fieldHints", {}), dict):
        raise ValueError("字段适配提示必须为对象")
    if not isinstance(value.get("metadataParameters", {}), dict) or any(
        key not in parameters or source not in {"sourceName", "sourceType", "crs"}
        for key, source in value.get("metadataParameters", {}).items()
    ):
        raise ValueError("元信息参数仅可引用有界的来源名称、类型与坐标系")
    for key, hints in value.get("fieldHints", {}).items():
        if (
            key not in parameters
            or parameters[key]["type"] != "field"
            or not isinstance(hints, list)
            or len(hints) > 30
            or any(
                not isinstance(hint, str) or not 1 <= len(hint) <= 80 for hint in hints
            )
        ):
            raise ValueError("字段适配提示必须绑定已声明的field参数")
    if not isinstance(value.get("fieldTargets", {}), dict) or any(
        key not in parameters or not isinstance(target, str) or len(target) > 80
        for key, target in value.get("fieldTargets", {}).items()
    ):
        raise ValueError("适配字段映射声明无效")
    if not isinstance(value.get("outputFields", []), list) or any(
        not isinstance(field, str) or len(field) > 160
        for field in value.get("outputFields", [])
    ):
        raise ValueError("适配输出字段声明无效")
    return deepcopy(value)
