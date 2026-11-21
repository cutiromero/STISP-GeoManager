"""Project-owned three-season Spartina interpretation."""

from .landcover import definition as base_definition

CODE = "spartina-distribution"


def definition(version_id, *, compact=True):
    value = base_definition(version_id)
    value["skill"] = {
        "title": "互花米草分布判读",
        "knowledgeQuestions": [
            "判读同年三季遥感影像时，互花米草与当地优势植物的物候差异如何支持分类？",
            "安排外业复查时，混生边界、模型低概率和缺测区如何区别对待？",
        ],
        "instructions": "识别互花米草的分布、占地规模和候选复查区。依据三时相物候、目标概率和研究区共同有效覆盖解释结果，说明哪些斑块边缘仍需现场辨认。",
    }
    roles = [
        ("march", "3月影像"),
        ("august", "8月影像"),
        ("december", "12月影像"),
    ]
    value["inputRequirements"] = [
        {
            "key": key,
            "label": label,
            "description": "已登记的同网格WGS84 Float32原始影像，16个固定波段。",
            "dataTypes": ["raster"],
            "required": True,
            "requiredFields": [],
            "multiple": False,
        }
        for key, label in roles
    ]
    instructions = [
        "确认同年3月、8月、12月输入组合；未指定研究区时使用三期共同覆盖全域。三个季节共同形成一次识别。",
        "核对三期16波段顺序、原始WGS84网格和研究区共同有效范围。",
        "以同一格网的三季物候共同判读目标斑块。结合分类、概率和共同有效范围区分稳定斑块、低置信边界和资料缺口。",
        "读取真实研究区面积、共同有效面积、占比及8连通斑块数。",
        "交付本次实际分类图、概率图和统计资源，提供大屏入口；保持本次与历史来源区分。",
        "简洁交付研究区解译结果和同一任务记录。",
    ]
    titles = [
        "确认研究区与资料",
        "核对三时相输入",
        "RF解译与成果准备",
        "核验分布统计",
        "整理大屏成果",
        "完成结果交付",
    ]
    for index, node in enumerate(value["nodes"]):
        node["title"] = titles[index]
        node["description"] = instructions[index]
        node["instruction"] = instructions[index]
        node["dataRoles"] = [key for key, _ in roles] if index < 3 else []
        if node["id"] == "interpret":
            node["parameters"] = {}
            node["contract"].update(
                goal=instructions[index],
                acceptance=[
                    "三期共同输入的研究区实际分类、概率与统计成功，已完成标准入库"
                ],
                requiredOutputs=[
                    {"name": "classification", "semanticType": "raster"},
                    {"name": "probability", "semanticType": "raster"},
                    {"name": "statistics", "semanticType": "table"},
                ],
                importOutputs=[
                    "classification",
                    "probability",
                    "statistics",
                ],
                maxOperatorCalls=2,
                maxModelCalls=32,
                maxSteps=48,
            )
            node["contract"].pop("sourceCoverage", None)
    value["outputRequirements"] = [
        "研究区互花米草分类图与目标概率",
        "WGS84椭球面积统计",
        "本次业务流与智能体记录",
    ]
    if compact:
        by_id = {node["id"]: node for node in value["nodes"]}
        selected = [by_id["sources"], by_id["interpret"], by_id["finish"]]
        labels = ["准备输入资料", "处理并生成成果", "查看与交付成果"]
        for position, node in enumerate(selected):
            node["title"] = labels[position]
            node["dependsOn"] = [selected[position - 1]["id"]] if position else []
        selected[0]["instruction"] = (
            instructions[0]
            + " "
            + instructions[1]
            + " 未给出范围时使用所选资料共同覆盖的全域，无需让用户再次选择研究区。"
        )
        selected[0]["description"] = selected[0]["instruction"]
        selected[2]["instruction"] = " ".join(instructions[3:])
        selected[2]["description"] = selected[2]["instruction"]
        for node in selected:
            if node.get("contract"):
                node["contract"]["goal"] = node["instruction"]
        value["nodes"] = selected
    return value
