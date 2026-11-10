"""Pure contract for the platform-owned, confined data-script interpreter."""

from copy import deepcopy

RUNTIME = "python-data-script-v1"
DATA_TYPES = {"vector", "raster", "table", "gene", "document", "image"}
MAX_CODE_CHARACTERS = 16000
POLICY_VERSION = 1


def validate_bridge(manifest):
    value = manifest.get("inputScriptBridge")
    if manifest.get("runtime") != RUNTIME:
        if value is not None:
            raise ValueError("脚本衔接能力只能绑定专用受限解释器")
        return None
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "inputPorts",
            "outputPorts",
            "codeParameter",
            "targetParameter",
            "contractParameter",
            "policyVersion",
        }
        or type(value["policyVersion"]) is not int
        or value["policyVersion"] != POLICY_VERSION
    ):
        raise ValueError("受限脚本衔接声明无效")
    inputs = {item["key"]: item for item in manifest["inputs"]}
    outputs = {item["key"]: item for item in manifest["outputs"]}
    ports = value["inputPorts"]
    if not isinstance(ports, dict) or not ports or set(ports) - DATA_TYPES:
        raise ValueError("脚本输入必须使用平台已登记的资料类型")
    used = set()
    for kind, names in ports.items():
        if not isinstance(names, list) or not 1 <= len(names) <= 5:
            raise ValueError("每种来源须声明1至5个实际端口")
        for name in names:
            if not isinstance(name, str) or name in used or name not in inputs:
                raise ValueError("脚本输入端口缺失或重复")
            if inputs[name]["kind"] != kind or inputs[name].get("required", True):
                raise ValueError("脚本输入端口须为对应类型的可选来源")
            used.add(name)
    if used != set(inputs):
        raise ValueError("脚本解释器不能声明未受控的其他输入")
    targets = value["outputPorts"]
    if not isinstance(targets, dict) or not targets or set(targets) - DATA_TYPES:
        raise ValueError("脚本目标须为可登记的资料类型")
    if len(set(targets.values())) != len(targets):
        raise ValueError("脚本目标输出端口不得重复")
    for kind, key in targets.items():
        if (
            key not in outputs
            or outputs[key]["kind"] != kind
            or outputs[key].get("required", True)
        ):
            raise ValueError("脚本目标须绑定真实可选输出")
    if set(targets.values()) != set(outputs):
        raise ValueError("脚本解释器不能额外输出未声明类型")
    parameters = {item["key"]: item for item in manifest["parameters"]}
    if set(parameters) != {
        value["codeParameter"],
        value["targetParameter"],
        value["contractParameter"],
    }:
        raise ValueError("脚本解释器参数必须明确且独立")
    code, target, contract = (
        parameters[value[key]]
        for key in ("codeParameter", "targetParameter", "contractParameter")
    )
    if (
        code["type"] != "string"
        or not code.get("required", True)
        or not 1 <= code.get("maxLength", 2000) <= MAX_CODE_CHARACTERS
    ):
        raise ValueError("脚本代码参数类型或长度无效")
    if target["type"] != "enum" or set(target["choices"]) != set(targets):
        raise ValueError("脚本目标枚举必须与输出对应")
    if contract["type"] != "string" or not manifest.get("qualityReport"):
        raise ValueError("脚本需要目标规范与真实质量报告")
    return deepcopy(value)
