"""One durable executor identity and a small, version-bound workflow skill."""

from copy import deepcopy
import hashlib
import json
from uuid import uuid4

# Configuration: only core guidance and the current node's note enter a request.
MODE = "main_agent_v1"
MAX_CORE_CHARACTERS = 600
MAX_NODE_CHARACTERS = 300
MAX_SKILL_BYTES = 16 * 1024
EXECUTOR_INSTRUCTION = (
    "\n你负责从研究问题到成果交付的同一项任务。结合本次目标、流程目的和已验证证据，"
    "判断当前节点需要解决什么问题，并在允许的动作范围内选择做法。遇到意外先判断"
    "它影响哪项科研结论，再决定补充证据、调整处理方案或请用户确认。"
)
REVIEWER_INSTRUCTION = (
    "\n按本次科研目的、节点验收条件和实际证据独立判断。指出哪些结论成立，"
    "哪些还需要补充证据，以及缺口会影响什么判断。"
)


def default_skill(adapter):
    return {
        "title": "地质综合推理" if adapter == "geology_generic" else "本次科研任务",
        "instructions": (
            "用岩性、构造和蚀变的空间关系检查地质图中值得复核的矛盾，解释已确认修正对成矿远景判断的影响。"
            "按实际空间尺度、地质规则和数据分辨率逐项核对证据，区分可确认的问题、解释分歧和需要外业复查的线索。"
            if adapter == "geology_generic"
            else "根据用户本次提出的科研问题和所选资料，找出能支撑结论的证据。资料的时间、范围或语义有疑问时，先明确这些差异会影响哪个判断。"
        ),
        "nodeInstructions": {},
    }


def normalize_skill(value, node_ids):
    from .definitions import invalid, keys, strings, text

    keys(
        value,
        {"title", "instructions", "nodeInstructions", "knowledgeQuestions"},
        "业务流配套技能",
    )
    result = {
        "title": text(value.get("title"), "技能名称", 80),
        "instructions": text(
            value.get("instructions"), "技能核心指导", MAX_CORE_CHARACTERS
        ),
        "nodeInstructions": deepcopy(value.get("nodeInstructions", {})),
    }
    notes = result["nodeInstructions"]
    if not isinstance(notes, dict) or set(notes) - set(node_ids):
        invalid("技能专项指导只能引用当前流程节点")
    for identity, note in notes.items():
        notes[identity] = text(note, "节点技能指导", MAX_NODE_CHARACTERS)
    if "knowledgeQuestions" in value:
        result["knowledgeQuestions"] = strings(
            value["knowledgeQuestions"], "待查证的知识问题", 3
        )
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_SKILL_BYTES:
        invalid("技能说明过长，请保留短核心指导及当前节点必要说明")
    return result


def session(workflow):
    return (
        (getattr(workflow, "parameters", {}) or {})
        .get("_businessFlow", {})
        .get("executorSession", {})
    )


def initialize(workflow):
    bind = workflow.parameters["_businessFlow"]
    if not bind.get("agentEnabled", True):
        return
    definition = bind["definitionSnapshot"]
    if definition.get("executionMode") != "main_agent":
        return
    skill = normalize_skill(
        definition.get("skill") or default_skill(definition["adapter"]),
        [node["id"] for node in definition["nodes"]],
    )
    encoded = json.dumps(
        skill, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    bind["executorSession"] = {
        "id": uuid4().hex,
        "mode": MODE,
        "skill": skill,
        "skillHash": hashlib.sha256(encoded.encode()).hexdigest(),
        "flowVersionId": bind["versionId"],
        "loop": {"phase": "select_node", "activeNodeId": "", "history": [], "steps": 0},
    }


def guidance(workflow, node_id, role="executor"):
    value = session(workflow)
    if not value:
        return ""
    skill = value["skill"]
    note = skill.get("nodeInstructions", {}).get(node_id, "")
    return (
        (EXECUTOR_INSTRUCTION if role == "executor" else REVIEWER_INSTRUCTION)
        + "\n流程科研目的与判断依据："
        + skill["title"]
        + "\n"
        + skill["instructions"]
        + ("\n本节点专项指导：" + note if note else "")
    )


def request_context(workflow, node_id, role="executor"):
    value = session(workflow)
    if not value:
        return {}
    return {
        "id": value["id"],
        "actor": "main_executor" if role == "executor" else "independent_reviewer",
        "nodeId": node_id,
        "flowVersionId": value["flowVersionId"],
        "skillHash": value["skillHash"],
    }


def public_session(workflow):
    value = session(workflow)
    if not value:
        return None
    return {
        "id": value["id"],
        "mode": value["mode"],
        "skillTitle": value["skill"]["title"],
        "skillHash": value["skillHash"],
        "flowVersionId": value["flowVersionId"],
    }


def task_record(workflow, node_id, *, offset=0, limit=8):
    """Recall a completed milestone's note and references, never its file bodies."""
    from apps.compute.packages import ComputeError
    from .state import binding, state
    from .ledger import text

    if not session(workflow):
        raise ComputeError("本任务未启用持续执行会话")
    if (
        type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= 12
    ):
        raise ComputeError("任务记录的引用分页无效")
    nodes = {row["id"]: row for row in binding(workflow)["definitionSnapshot"]["nodes"]}
    if not isinstance(node_id, str) or node_id not in nodes:
        raise ComputeError("只能读取本任务已完成的节点记录")
    item = state(workflow)["nodes"][node_id]
    stage = next(
        (row for row in workflow.plan.get("stages", []) if row["name"] == node_id), {}
    )
    if item.get("status") != "succeeded" and stage.get("status") != "completed":
        raise ComputeError("该节点尚未完成，不能把进行中记录当成历史成果")
    actor = item.get("executor", {})
    results = (
        stage.get("results", [])
        if stage
        else item.get("outputs", {}).get("evidence", [])
    )
    refs = []
    for row in results[offset : offset + limit]:
        metadata = {
            **row,
            **(row.get("result") if isinstance(row.get("result"), dict) else {}),
        }
        refs.append(
            {
                key: metadata[key]
                for key in (
                    "id",
                    "outputId",
                    "taskId",
                    "key",
                    "kind",
                    "label",
                    "title",
                    "checksum",
                )
                if key in metadata
            }
        )
    return {
        "nodeId": node_id,
        "title": nodes[node_id]["title"],
        "summary": text(
            actor.get("summary") or stage.get("decision", {}).get("resultSummary"), 900
        ),
        "limitations": [text(value, 180) for value in actor.get("limitations", [])[:3]],
        "inputs": deepcopy(stage.get("inputs", {})),
        "parameters": deepcopy(
            stage.get("actualParameters", stage.get("parameters", {}))
        ),
        "outputs": refs,
        "outputCount": len(results),
        "nextOffset": offset + limit if offset + limit < len(results) else None,
        "scope": "仅为本任务已完成节点的摘要及成果引用，未读取文件正文。",
    }
