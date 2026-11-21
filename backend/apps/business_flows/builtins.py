"""Curated starting flows; publication copies these into immutable versions."""

from copy import deepcopy

from .execution_session import default_skill

MINERALS = ("hematite", "chlorite", "hydromica", "calcite", "dolomite")
GEOLOGY_ROLES = {
    "lithology": ("岩性图", "vector"),
    "faults": ("构造线", "vector"),
    "coverage": ("研究区范围", "vector"),
    "units": ("填图单元表", "table"),
    "hematite": ("赤铁矿化", "raster"),
    "chlorite": ("绿泥石化", "raster"),
    "hydromica": ("水云母化", "raster"),
    "calcite": ("方解石化", "raster"),
    "dolomite": ("白云石化", "raster"),
    "alterations": ("蚀变识别资料（不限矿物种类，可多份）", "raster"),
}
# Retain named mineral roles for the legacy upload API and published history.
GEOLOGY_CURRENT_ROLES = tuple(role for role in GEOLOGY_ROLES if role not in MINERALS)
GEOLOGY_NODES = (
    ("inputs", "确认资料与字段", "agent", tuple(GEOLOGY_ROLES)),
    ("check", "综合一致性检查", "operator", tuple(GEOLOGY_ROLES)),
    ("apply", "审核与处置建议", "agent", tuple(GEOLOGY_ROLES)),
    ("recheck", "修正结果复核", "operator", tuple(GEOLOGY_ROLES)),
    ("relations", "构造关系重建", "operator", ("lithology", "faults", "coverage")),
    (
        "prospect",
        "找矿远景推断",
        "operator",
        ("lithology", "faults", *MINERALS, "alterations"),
    ),
    ("finish", "整理报告与成果", "result", ()),
)


def geology_definition(*, legacy_roles=False, main_agent=False):
    input_roles = tuple(GEOLOGY_ROLES) if legacy_roles else GEOLOGY_CURRENT_ROLES
    nodes = []
    for index, (identity, title, kind, roles) in enumerate(GEOLOGY_NODES):
        nodes.append(
            {
                "id": identity,
                "title": title,
                "kind": kind,
                "description": {
                    "inputs": "识别资料用途和字段含义，确认后开始分析。",
                    "check": "调用已登记的地质检查算子，综合岩性、构造与蚀变依据识别问题。",
                    "apply": "核对处置建议与依据，选择本次执行的处置范围。",
                    "recheck": "对已批准的修正结果重新执行质量检查，保留未批准对象。",
                    "relations": "重建修正后的构造交汇关系，使用实际几何证据。",
                    "prospect": "仅依据修正后资料，综合构造、蚀变与岩性生成平滑且不重叠的找矿远景。",
                    "finish": "独立审核结论和证据，整理报告、地图及成果入口。",
                }[identity],
                "dependsOn": [GEOLOGY_NODES[index - 1][0]] if index else [],
                "dataRoles": [role for role in roles if role in input_roles],
                "instruction": {
                    "inputs": "确认各图层、类别与字段在本研究中的含义及覆盖范围，让后续判断可以追溯到实际资料。口径不一致时说明会影响哪项地质判断。",
                    "check": "从空间量测、属性与当地适用规则解释已发现的图面矛盾，区分证据充分的问题、尺度差异与地质解释分歧。",
                    "apply": "逐项说明候选处置会改善哪项地质解释，以及应暂留哪些高不确定对象。按已核验的依据提交人工确认。",
                    "recheck": "比较处置前后相同空间范围和统计口径，核查已处置问题是否解决、哪些位置需要再判读。",
                    "relations": "结合真实交汇位置、几何与交切证据判断可支持的构造关系，标明关系仍待核实的位置。",
                    "prospect": "解释岩性背景、构造位置和蚀变组合各自怎样支持远景判断，区分可定位的优先核查区与低置信区域。",
                    "finish": "按研究目的串联已核验问题、处置效果和找矿线索。给出实际成果引用及外业核查要解决的问题。",
                }[identity],
                "review": {
                    "ai": identity in {"apply", "finish"},
                    "human": identity in {"inputs", "apply"},
                    "maxRevisions": 1 if identity in {"apply", "finish"} else 0,
                },
            }
        )
    return {
        "schemaVersion": 1,
        "adapter": "geology_generic",
        **({"executionMode": "main_agent"} if main_agent else {}),
        "skill": {
            **default_skill("geology_generic"),
            "knowledgeQuestions": [
                "解释岩性、断层与蚀变的空间关系时，哪些地质证据适用于本研究区和填图尺度？",
                "评估成矿远景前，哪些蚀变组合或构造位置支持进一步外业核查？",
            ],
            "nodeInstructions": {
                "inputs": "按真实字段与样本确认资料含义，蚀变类别不受示例矿物列表限制。",
                "apply": "用图斑、关系证据与规则支撑处置建议，说明修改会改善哪项地质解释，并列出值得人工确认的分歧。",
                "finish": "依据完整统计和成果引用，解释已确认的图面问题、处置前后的变化和各要素对远景判断的贡献，指出仍需外业核查的位置与证据缺口。",
            },
        },
        "inputRequirements": [
            {
                "key": key,
                "label": label,
                "description": "资料保留原始内容，处理使用受控工作副本。",
                "dataTypes": [kind],
                "required": key == "lithology",
                "requiredFields": [],
                **(
                    {"multiple": True, "semanticType": "class_mask_stack_v1"}
                    if key == "alterations"
                    else {}
                ),
            }
            for key, (label, kind) in GEOLOGY_ROLES.items()
            if key in input_roles
        ],
        "nodes": nodes,
        "outputRequirements": [
            "处置与复核依据",
            "地质综合推理报告",
            "修正后找矿远景与地图",
        ],
    }


def source_summary_definition(*, main_agent=False):
    return {
        "schemaVersion": 1,
        "adapter": "research_flow",
        **({"executionMode": "main_agent"} if main_agent else {}),
        "skill": {
            "title": "科研资料适用性评估",
            "instructions": "判断哪些项目资料可以回答本次科研问题，为后续选数和研究设计提供依据。核对资料来源、字段口径、时空范围和可见证据，说明结论能推广到哪里，哪些判断需要补充资料。",
            "nodeInstructions": {},
            "knowledgeQuestions": [
                "比较不同来源或时期的项目资料前，需要核对哪些空间尺度、抽样条件或字段口径？",
            ],
        },
        "inputRequirements": [
            {
                "key": "source",
                "label": "待梳理资料",
                "description": "从当前项目选择已授权资料，原始数据只读。",
                "dataTypes": ["table", "document", "vector", "raster", "image", "gene"],
                "required": True,
                "requiredFields": [],
            }
        ],
        "nodes": [
            {
                "id": "summarize",
                "title": "梳理资料与研究线索",
                "description": "定位能支撑研究判断的资料和仍待核查的信息。",
                "kind": "agent",
                "dependsOn": [],
                "dataRoles": ["source"],
                "instruction": "用实际读取的字段和内容说明资料能回答的问题，并注明样本覆盖范围。资料口径冲突时列出各自来源以及对比较结论的影响。",
                "review": {"ai": False, "human": False, "maxRevisions": 0},
            },
            {
                "id": "finish",
                "title": "汇总成果",
                "description": "让后续研究者按结论找到原始依据和待核实项。",
                "kind": "result",
                "dependsOn": ["summarize"],
                "dataRoles": [],
                "instruction": "交付结论与资料的对应关系，并按影响程度列出仍需补充的事实。",
                "review": {"ai": False, "human": False, "maxRevisions": 0},
            },
        ],
        "outputRequirements": ["资料摘要", "引用和适用范围"],
    }


def source_review_definition(*, main_agent=False):
    definition = source_summary_definition(main_agent=main_agent)
    definition["skill"]["knowledgeQuestions"] = [
        "评价本研究的证据强弱前，相关学科标准怎样界定抽样、适用范围和结论可比性？",
    ]
    summary = definition["nodes"][0]
    summary["title"] = "梳理资料并形成审校稿"
    summary["description"] = (
        "梳理资料结构、适用范围和研究解释，审核依据与局限，确认后生成报告。"
    )
    summary["instruction"] = (
        "以已读内容和可定位字段为证据给出审校稿。分别说明事实、解释和待验证假设；资料缺失或抽样覆盖有限时，指出会受影响的结论。"
    )
    summary["review"] = {"ai": True, "human": True, "maxRevisions": 1}
    definition["nodes"][1]["description"] = (
        "仅在独立审校通过且用户明确接受后，整理可追溯报告与引用。"
    )
    definition["outputRequirements"] = [
        "资料结构与适用范围说明",
        "独立审校意见与用户接受记录",
        "只读资料审校报告",
    ]
    return definition


def builtin_flows():
    return deepcopy(
        [
            {
                "code": "geology-logic-reasoning",
                "name": "逻辑推理",
                "description": "综合岩性、构造与蚀变，检查地质一致性，经过独立审核与必要人工批准后完成修正、复核和找矿远景推断。",
                "definition": geology_definition(main_agent=True),
            },
            {
                "code": "research-source-summary",
                "name": "科研资料摘要",
                "description": "梳理项目资料，形成摘要、来源引用与后续研究线索。",
                "definition": source_summary_definition(main_agent=True),
            },
            {
                "code": "research-source-review",
                "name": "科研资料独立审校",
                "description": "梳理资料结构、适用范围与研究解释，经审核和确认后形成报告。",
                "definition": source_review_definition(main_agent=True),
            },
        ]
    )
