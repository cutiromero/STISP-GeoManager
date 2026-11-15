"""Native historical fire observations with explicit physical units and periods."""

from .spartina import definition as base_definition

CODE = "wildfire-history-observation"


def definition(version_id):
    value = base_definition(version_id)
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
        "以cube端口绑定真实原生立方体资源，沿用所选产品、时间、序列长度和边界参数，依次查询、预检并执行冻结观测算子一次。观测图、分级图、统计及序列表实际成功并完成入库后结束目标。",
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
            node["parameters"] = {
                "product": "gwis_ba",
                "time_index": 873,
                "history": 12,
                "west": 112,
                "south": -44,
                "east": 154,
                "north": -10,
            }
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
    return value
