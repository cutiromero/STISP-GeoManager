"""One-submission monitoring workflows with the shared task-level Agent."""

from copy import deepcopy

from . import landcover, spartina, wildfire

PRESETS = {
    landcover.CODE: (landcover.definition, "landcover-unet-infer"),
    spartina.CODE: (spartina.definition, "spartina-rf-infer"),
    wildfire.CODE: (wildfire.definition, "wildfire-observe"),
}

RESEARCH = {
    landcover.CODE: {
        "title": "地表覆盖格局判读",
        "purpose": "识别研究区六类地表覆盖的空间分布与面积构成，为现状制图和后续地块复核提供基线。结合 2 米 RGB 影像、分类图和有效区统计，判断哪些地类构成主要格局、哪些过渡位置需要进一步核查。",
        "interpret_goal": "把影像中的地表差异转化为可定位、可计量的地类格局。",
        "interpret": "以原始影像为范围，对照已登记 UNet 的六类定义判读。核对波段、投影和有效范围。若统计差异来自无效像元或有效区口径，先核实分母，再解释分类图上的差异。",
        "acceptance": "分类图的格网与原影像对应，六类面积和占比按同一有效区统计，成果就绪并入库。",
        "finish_goal": "形成可用于制图和地块复核的地类现状基线。",
        "finish": "连同分类图给出主要地类面积及其分母，标出地类过渡区或混淆可能最大的区域，说明哪些判断仍需样本验证。",
    },
    spartina.CODE: {
        "title": "互花米草分布与复查优先区",
        "purpose": "判定研究区互花米草的空间分布和占地规模，为入侵监测与外业复查排序。用三期物候差异、模型概率和斑块连通关系一起解释结果，分别说明稳定分布和可能与其他植被混淆的地段。",
        "interpret_goal": "把三期影像中有物候支持的目标斑块与疑似混淆地段区分开。",
        "interpret": "核对三期是否同年且同格网，以共同有效区作为分布统计范围。用分类图定位斑块，以目标概率核对边缘和混生区域。遇到时相或网格偏差，先判断能否建立同一位置的三期对照，再决定适配或补充资料。",
        "acceptance": "分类、概率和面积统计使用同一有效范围，结果能逐项追溯到三期输入并完成入库。",
        "finish_goal": "为外业安排提供可定位的重点复查区域。",
        "finish": "交付分类、目标概率、有效区面积和斑块统计。说明稳定斑块、低置信边界与缺测区域各自对复查排序的影响。",
    },
    wildfire.CODE: {
        "title": "历史野火观测判读",
        "purpose": "查明选定地区在实际观测期哪里记录了火烧或较强的火辐射，以及变化主要出现在哪些时段，为历史事件回顾和现场核查筛选重点。以 SeasFire 原始时标、产品单位及有效掩膜为依据，区分火烧面积与火辐射强度回答的问题。",
        "interpret_goal": "确定所选产品和观测期能支持哪些空间对比与时序判断，并形成可核查的证据。",
        "interpret": "沿用已确认的观测产品、时段和范围，缺省范围取原生立方体全域。按实际时间坐标和有效掩膜区分零观测、缺测与重复记录。出现异常峰值或空图时，先核对时标、有效像元和单位，再判断是资料口径还是实际观测变化。",
        "acceptance": "原值图、分级图、区域统计和序列表均能追溯到同一观测产品、实际时期、范围与有效掩膜，单位一致并完成入库。",
        "finish_goal": "把历史观测转化为可追溯的事件线索与核查重点。",
        "finish": "用原值、分级图和序列指出信号最集中的位置与时段。分别交代产品单位、有效范围及覆盖缺口，给出支撑事件回顾和现场核查的成果引用。",
    },
}

GOALS = {code: research["purpose"] for code, research in RESEARCH.items()}

INPUT_GUIDES = {
    "image": "上传或选择一幅带坐标系的 2 m、Byte、三波段 RGB GeoTIFF（波段顺序红、绿、蓝；米制投影）。每次处理一幅原始影像的全范围，输出六类分类图与面积统计表。",
    "march": "同一地区、同一年 3 月原始 GeoTIFF：WGS84 Float32、16 个规定光谱/指数波段。须与另外两期同网格、同分辨率。",
    "august": "同一地区、同一年 8 月原始 GeoTIFF：WGS84 Float32、16 个规定波段，与 3 月和 12 月严格对齐。",
    "december": "同一地区、同一年 12 月原始 GeoTIFF：WGS84 Float32、16 个规定波段。以三期共同有效范围计算，不需要另画研究区。",
    "cube": "选择已登记的 SeasFire 原生 Zarr 立方体，含时间坐标、经纬网格和有效掩膜。选择 GWIS/GFED/FCCI 火烧面积或 CAMS 火辐射功率密度，并确认观测期。",
}


def definition(code, version_id):
    build, _ = PRESETS[code]
    source = build(version_id)
    research = RESEARCH[code]
    inputs = deepcopy(source["inputRequirements"])
    for row in inputs:
        row.update(multiple=False, description=INPUT_GUIDES[row["key"]])
    operator = deepcopy(
        next(node for node in source["nodes"] if node["id"] == "interpret")
    )
    operator.update(
        title="组织解译与成果核验",
        description=research["interpret_goal"],
        instruction=research["interpret"],
        dependsOn=[],
        inputBindings={row["key"]: {"role": row["key"]} for row in inputs},
    )
    contract = operator["contract"]
    contract.update(
        goal=research["interpret_goal"],
        acceptance=[research["acceptance"]],
        tools=list(dict.fromkeys([*contract["tools"], "prepare_input"])),
        importOutputs=[item["name"] for item in contract["requiredOutputs"]],
    )
    contract.pop("sourceCoverage", None)
    finish = deepcopy(next(node for node in source["nodes"] if node["id"] == "finish"))
    finish.update(
        title="核验交付与说明",
        dependsOn=[operator["id"]],
        description=research["finish_goal"],
        instruction=research["finish"],
    )
    skill = {
        "title": research["title"],
        "instructions": research["purpose"],
        "knowledgeQuestions": source["skill"]["knowledgeQuestions"],
    }
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
