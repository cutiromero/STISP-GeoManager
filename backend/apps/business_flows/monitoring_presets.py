"""One-submission monitoring workflows with the shared task-level Agent."""

from copy import deepcopy

from . import landcover, spartina, wildfire
from .execution_session import default_skill

PRESETS = {
    landcover.CODE: (landcover.definition, "landcover-unet-infer"),
    spartina.CODE: (spartina.definition, "spartina-rf-infer"),
    wildfire.CODE: (wildfire.definition, "wildfire-observe"),
}

GOALS = {
    landcover.CODE: "按已登记 2 米 RGB 原始影像的全域，生成六类地表覆盖分类图与面积统计表。",
    spartina.CODE: "按同年三季节影像的共同有效全域，生成互花米草分类、目标概率和面积统计。",
    wildfire.CODE: "从原始 SeasFire 选择实际观测期，生成观测原值、物理量分级和统计序列，不做未来野火预报。",
}

INPUT_GUIDES = {
    "image": "上传或选择一幅带坐标系的 2 m、Byte、三波段 RGB GeoTIFF（波段顺序红、绿、蓝；米制投影）。每次处理一幅原始影像的全范围，输出六类分类图与面积统计表。",
    "march": "同一地区、同一年 3 月原始 GeoTIFF：WGS84 Float32、16 个规定光谱/指数波段。须与另外两期同网格、同分辨率。",
    "august": "同一地区、同一年 8 月原始 GeoTIFF：WGS84 Float32、16 个规定波段，与 3 月和 12 月严格对齐。",
    "december": "同一地区、同一年 12 月原始 GeoTIFF：WGS84 Float32、16 个规定波段。以三期共同有效范围计算，不需要另画研究区。",
    "cube": "选择当前项目已登记的 SeasFire 原生 Zarr 时空立方体（含实际时间、经纬度及有效掩膜），不是普通 TIFF 或模型权重。确认 GWIS/GFED/FCCI 火烧面积或 CAMS 火辐射功率密度及观测期；按资料全域输出原值图、物理量分级图、统计表和观测序列表，不产出风险预报。",
}


INTERPRET = {
    landcover.CODE: "核对本次绑定的image与已登记UNet版本；按原始影像全域、classes=all处理。只有预检通过才启动。同一任务不重复计算，实际分类及面积统计通过后交付。",
    spartina.CODE: "核对同年3、8、12月对应端口与共同网格。预检三期共同有效全域，不要求再画框。实际分类、概率与面积统计通过后交付。",
    wildfire.CODE: "使用已确认的product、time_index和history及实际cube。未设置四界就按数据全域；不猜测索引，不改变量与时段。核对实际面积或FRP的单位，交付原值、分级、统计和序列表，不称预警。",
}


def definition(code, version_id):
    build, _ = PRESETS[code]
    source = build(version_id)
    inputs = deepcopy(source["inputRequirements"])
    for row in inputs:
        row.update(multiple=False, description=INPUT_GUIDES[row["key"]])
    operator = deepcopy(
        next(node for node in source["nodes"] if node["id"] == "interpret")
    )
    operator.update(
        title="组织解译与成果核验",
        description="主 Agent 核对资料、调用适配工具、预检并运行已发布科学算子，检查实际图表。",
        instruction=INTERPRET[code],
        dependsOn=[],
        inputBindings={row["key"]: {"role": row["key"]} for row in inputs},
    )
    contract = operator["contract"]
    contract.update(
        goal=INTERPRET[code],
        tools=list(dict.fromkeys([*contract["tools"], "prepare_input"])),
        importOutputs=[item["name"] for item in contract["requiredOutputs"]],
    )
    contract.pop("sourceCoverage", None)
    finish = deepcopy(next(node for node in source["nodes"] if node["id"] == "finish"))
    finish.update(
        title="核验交付与说明",
        dependsOn=[operator["id"]],
        description="核对实际成果、范围和观测单位，整理图表、实际方法与局限。",
        instruction="依据本次已核验的算子输出说明成果、统计口径及局限，提示用户在数据中心明确登记主地图。不要冒充用户登记，不要求再次选择研究区。",
    )
    skill = default_skill("research_flow")
    skill.update(
        title="遥感监测解译组织",
        nodeInstructions={
            "interpret": "查nodeDefaults的versionId；用visibleInputs里的整数ID做预检（不是role对象或outputId）。成功后按返回的runAction调用run_operator，只传usePreflight=true，不重抄绑定。预检确有差距时用已发布适配能力或受控prepare_input，结果就绪后重新预检。保留原件、核心算法和已确认的时空范围；只有无法可靠判断含义时提问。",
            "finish": "通过实际图表、日期、单位与输入来源交付。任务入库不等于正式发布，不调用大屏或替用户登记。",
        },
    )
    return {
        "schemaVersion": 1,
        "adapter": "research_flow",
        "executionMode": "main_agent",
        "inputPreparation": {"allowScripts": True, "reviewScripts": True},
        "skill": skill,
        "inputRequirements": inputs,
        "nodes": [operator, finish],
        "outputRequirements": source["outputRequirements"][:2],
    }
