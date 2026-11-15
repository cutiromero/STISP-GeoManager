"""Project-owned three-season Spartina interpretation."""

from .landcover import definition as base_definition

CODE = "spartina-distribution"


def definition(version_id):
    value = base_definition(version_id)
    roles = [
        ("march", "第一期16波段影像"),
        ("august", "第二期16波段影像"),
        ("december", "第三期16波段影像"),
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
        "确认三时相输入组合和用户研究区。三个季节共同形成一次识别。",
        "核对三期16波段顺序、原始WGS84网格和研究区共同有效范围。",
        "对三时相作为一个组合执行一次冻结RF版本，march、august、december端口各绑定一个真实资源ID；使用已配置研究区参数。依次查询算子、预检、执行；分类、概率和统计完成入库后结束节点。",
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
                    "original",
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
    return value
