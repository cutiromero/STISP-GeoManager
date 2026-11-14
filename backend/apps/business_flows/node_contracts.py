"""节点内执行合同和平台硬上限。"""

from .definitions import invalid, keys, strings, text

TOOLS = {
    "read_evidence",
    "read_task_record",
    "operator_catalog",
    "preflight_operator",
    "run_operator",
    "prepare_input",
    "ask_user",
    "finish_node",
}
LIMITS = {
    "maxSteps": (1, 128, 32),
    "maxModelCalls": (1, 128, 32),
    "maxOperatorCalls": (0, 32, 6),
    "maxRecoveries": (0, 8, 4),
    "maxSeconds": (1, 14400, 3600),
}
MAX_TOOL_BYTES = 8192
MAX_FRAGMENT_BYTES = 4096
MAX_EVIDENCE_BYTES = 96 * 1024


def normalize_contract(value):
    keys(
        value,
        {
            "goal",
            "acceptance",
            "requiredOutputs",
            "tools",
            "sourceCoverage",
            "importOutputs",
            *LIMITS,
        },
        "节点合同",
    )
    result = dict(value)
    if "sourceCoverage" in result:
        coverage = result["sourceCoverage"]
        keys(coverage, {"inputRole", "outputKey"}, "来源覆盖合同")
        for key in ("inputRole", "outputKey"):
            coverage[key] = text(coverage.get(key), "来源覆盖" + key, 64)
    if "importOutputs" in result:
        result["importOutputs"] = strings(result["importOutputs"], "自动入库输出", 30)
    result["goal"] = text(result.get("goal"), "节点目标", 2000)
    result["acceptance"] = strings(result.get("acceptance"), "验收条件", 8)
    if not result["acceptance"]:
        invalid("节点合同须提供验收条件")
    result["tools"] = strings(result.get("tools"), "允许工具", len(TOOLS))
    if set(result["tools"]) - TOOLS or "finish_node" not in result["tools"]:
        invalid("节点合同工具无效或缺少finish_node")
    outputs = result.get("requiredOutputs")
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= 8:
        invalid("节点合同须声明1至8项必需输出")
    names = set()
    for output in outputs:
        keys(output, {"name", "semanticType"}, "合同输出")
        for key in ("name", "semanticType"):
            output[key] = text(output.get(key), "合同输出" + key, 100)
        if output["name"] in names:
            invalid("合同输出名称不得重复")
        names.add(output["name"])
    for key, (lower, upper, default) in LIMITS.items():
        result.setdefault(key, default)
        if type(result[key]) is not int or not lower <= result[key] <= upper:
            invalid(f"{key}须为{lower}至{upper}")
    return result


def recovery_contract(node):
    return normalize_contract(
        {
            "goal": "恢复当前算子节点：" + node["title"],
            "acceptance": ["必须取得真实算子结果；不得代替人工批准"],
            "requiredOutputs": [{"name": "result", "semanticType": "operator_result"}],
            "tools": sorted(TOOLS),
        }
    )
