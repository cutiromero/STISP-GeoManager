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
                    "inputs": "由执行智能体识别资料角色和字段含义；重要映射由用户明确确认。",
                    "check": "调用已登记的地质检查算子，综合岩性、构造与蚀变依据识别问题。",
                    "apply": "独立审核智能体先核查建议与证据，处置范围仍由用户批准。",
                    "recheck": "对已批准的修正结果重新执行质量检查，保留未批准对象。",
                    "relations": "重建修正后的构造交汇关系，使用实际几何证据。",
                    "prospect": "仅依据修正后资料，综合构造、蚀变与岩性生成平滑且不重叠的找矿远景。",
                    "finish": "独立审核结论和证据，整理报告、地图及成果入口。",
                }[identity],
                "dependsOn": [GEOLOGY_NODES[index - 1][0]] if index else [],
                "dataRoles": [role for role in roles if role in input_roles],
                "instruction": "",
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
            "nodeInstructions": {
                "inputs": "按真实字段与样本确认资料含义，蚀变类别不受示例矿物列表限制。",
                "apply": "核对处置证据，执行范围以用户实际批准记录为准，审核通过不能替代人工批准。",
                "finish": "使用完整实际统计与成果引用撰写结论，明确剩余问题和限制，不能以样本推算全集。",
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
            "title": "只读科研资料梳理",
            "instructions": "围绕用户目标梳理实际可见资料，区分事实、推断和未读内容。引用真实来源，按需读取有界内容，不复制完整文件或累积历史。资料不足时说明具体缺口，遇到错误依据诊断处理。遵循当前节点工具及只读要求，不能编造计算、修改或批准。",
            "nodeInstructions": {},
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
                "description": "读取已授权元信息和可用内容，整理关键字段、事实、局限与后续研究线索。",
                "kind": "agent",
                "dependsOn": [],
                "dataRoles": ["source"],
                "instruction": "请基于本次绑定资料的实际证据，给出简明的资料摘要、可用字段、可信范围和后续研究建议。明确区分事实与推断，不修改原始资料。",
                "review": {"ai": False, "human": False, "maxRevisions": 0},
            },
            {
                "id": "finish",
                "title": "汇总成果",
                "description": "形成可追溯的资料摘要与引用。",
                "kind": "result",
                "dependsOn": ["summarize"],
                "dataRoles": [],
                "instruction": "整理已完成节点的结果与依据。",
                "review": {"ai": False, "human": False, "maxRevisions": 0},
            },
        ],
        "outputRequirements": ["资料摘要", "引用和适用范围"],
    }


def source_review_definition(*, main_agent=False):
    definition = source_summary_definition(main_agent=main_agent)
    summary = definition["nodes"][0]
    summary["title"] = "梳理资料并形成审校稿"
    summary["description"] = (
        "执行智能体整理实际可见的资料结构、适用范围和研究解释，独立审核智能体核对证据与局限，用户明确接受后生成报告；原始资料只读。"
    )
    summary["instruction"] = (
        "请根据本次绑定资料的实际可见证据，整理资料结构、关键字段、适用范围和有依据的研究解释。明确已读内容、抽样或仅元信息的范围，区分事实与推断，说明局限；不修改原始资料。先形成待独立审核和用户接受的审校稿，不能声称用户已经批准。"
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
                "description": "对当前项目已授权资料进行只读梳理，快速形成摘要与研究线索；默认无需AI审核或人工确认。",
                "definition": source_summary_definition(main_agent=True),
            },
            {
                "code": "research-source-review",
                "name": "科研资料独立审校",
                "description": "执行智能体只读梳理资料结构、适用范围与研究解释，独立审核智能体核对后由用户明确接受报告，保留审核与返修依据。",
                "definition": source_review_definition(main_agent=True),
            },
        ]
    )
