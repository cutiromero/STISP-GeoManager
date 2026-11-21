"""Native historical fire observations with explicit physical units and periods."""

from .spartina import definition as base_definition

CODE = "wildfire-history-observation"


def definition(version_id):
    value = base_definition(version_id, compact=False)
    value["skill"] = {
        "title": "历史野火观测判读",
        "knowledgeQuestions": [
            "比较历史野火序列前，SeasFire 中 GWIS、GFED、FCCI 火烧面积与 CAMS 火辐射功率密度各表示什么，单位和时间尺度有何差异？",
            "判断空图或异常时，FCCI 月尺度重复记录、有效掩膜和零值应怎样区分？",
        ],
        "instructions": "查明选定地区实际观测中哪里记录了火烧或较强火辐射，以及信号何时集中，为历史事件回顾和实地核查提供线索。根据实际时标、单位和有效范围解释两类物理量。",
    }
    value["inputRequirements"] = [
        {
            "key": "cube",
            "label": "原始SeasFire立方体",
            "description": "已登记的原生Zarr时空观测容器，时间和有效掩膜保留。",
            "dataTypes": ["raster"],
            "required": True,
            "requiredFields": [],
            "multiple": False,
        }
    ]
    titles = [
        "确认产品、时期与研究区",
        "核对观测期和单位",
        "提取观测并生成图表",
        "核对区域观测统计",
        "整理大屏观测成果",
        "交付观测与处理记录",
    ]
    instructions = [
        "从任务目标读取已选观测产品、时期、研究区与序列长度，结合已绑定原生立方体确认资料，随后继续。产品为gwis_ba、gfed_ba、fcci_ba或cams_frpfire。",
        "GWIS/GFED按原始周期，FCCI按月平均重复记录，三者单位ha；CAMS FRP单位W m-2、按原始周期。按原始有效掩膜核对任务目标中已选时期。",
        "以所选产品的实际时标和有效格网提取观测。遇到空图、零值或异常峰值，核对时标、掩膜和单位后解释，并通过原值、分级和序列对照验证。",
        "读取实际火烧面积或FRP值、有效格网和真实日期序列；火烧面积已经是ha，不乘显示像元面积。",
        "交付同任务入库的观测原值、物理量分级、区域统计和历史序列，提供大屏入口。",
        "简洁交付所选历史观测、实际时期、区域和处理记录。",
    ]
    for index, node in enumerate(value["nodes"]):
        node.update(
            title=titles[index],
            description=instructions[index],
            instruction=instructions[index],
            dataRoles=["cube"] if index < 3 else [],
        )
        if node["id"] == "interpret":
            node["parameters"] = {"history": 1}
            node["contract"].update(
                goal=instructions[index],
                acceptance=["真实观测时段、单位、格网与数据一致，图表完成标准入库"],
                requiredOutputs=[
                    {"name": key, "semanticType": kind}
                    for key, kind in [
                        ("observation", "raster"),
                        ("classification", "raster"),
                        ("statistics", "table"),
                        ("series", "table"),
                    ]
                ],
                importOutputs=["observation", "classification", "statistics", "series"],
            )
    value["outputRequirements"] = [
        "真实观测原值与物理量分级图",
        "实际时期的区域统计与序列",
        "同一业务流与智能体记录",
    ]
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
        + " 未给出范围时使用资料全域，无需让用户再次选择研究区。"
    )
    selected[0]["description"] = selected[0]["instruction"]
    selected[2]["instruction"] = " ".join(instructions[3:])
    selected[2]["description"] = selected[2]["instruction"]
    for node in selected:
        if node.get("contract"):
            node["contract"]["goal"] = node["instruction"]
    value["nodes"] = selected
    return value
