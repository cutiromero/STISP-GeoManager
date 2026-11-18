"""One-shot definitions for the three fixed scientific monitoring operators."""

from copy import deepcopy

from . import landcover, spartina, wildfire

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
        title="执行解译并准备成果",
        description="直接执行已发布算子，核验实际图表，按本次任务入库。",
        dependsOn=[],
        inputBindings={row["key"]: {"role": row["key"]} for row in inputs},
    )
    contract = operator["contract"]
    contract.pop("sourceCoverage", None)
    contract["importOutputs"] = [item["name"] for item in contract["requiredOutputs"]]
    finish = deepcopy(next(node for node in source["nodes"] if node["id"] == "finish"))
    finish.update(
        title="查看任务成果",
        dependsOn=[operator["id"]],
        description="图表已按任务归档。可在数据中心检查成果，再明确登记为正式展示成果；未登记不会上大屏。",
    )
    return {
        "schemaVersion": 1,
        "adapter": "research_flow",
        "executionMode": "fixed",
        "inputPreparation": {"allowScripts": False},
        "inputRequirements": inputs,
        "nodes": [operator, finish],
        "outputRequirements": source["outputRequirements"][:2],
    }
