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
    "\n你是贯穿本次业务流的主执行智能体，executionSession标识同一持续任务。"
    "当前节点是本任务的工作目标；结合ledger延续此前结论、成果与未解决事项。"
    "已完成工作不重复执行；根据真实诊断修复当前问题，成功后继续下一目标。"
    "成果以引用交接，只有实际读取的统计或片段才可作为判断依据，不累积文件正文或完整历史。"
    "配套技能不增加工具、数据访问或人工批准权限；具体动作遵循当前节点允许的工具。"
)
REVIEWER_INSTRUCTION = (
    "\n本次独立审核沿用同一业务流的技能与任务事实；保持独立判断，不继承执行者的思考对话。"
    "台账只提供历史索引，核对结论仍须依据本次真实证据。"
)


def default_skill(adapter):
    return {
        "title": "地质综合推理" if adapter == "geology_generic" else "科研任务执行",
        "instructions": (
            "围绕用户目标完成节点并验证成果。依据真实资料选择登记算子、输入输出绑定和允许调整的参数，"
            "以已验证配置为起点，依据当前数据和任务需要调整并说明原因，不为消除报错放宽科学判据。"
            "先预检再计算。失败先读诊断，区分输入、参数和环境问题，改变有效方案后再预检；"
            "保留已完成工作，不能反复提交相同错误方案。缺少必要含义时明确提问，"
            "格式、引用或审核错误先核对诊断与当前结果，不能用删减必要证据或反复重算消除报错。"
            "自动补救后仍无法继续时，保留当前成果并等待人工补充；收到补充后只处理受影响节点，再校验和审核。"
            "算子核心计算逻辑、原件和用户批准范围保持受保护；参数按实际语义和登记范围判断。"
            "资料与成果按引用读取必要统计和片段，区分已测事实、推断及剩余限制。"
        ),
        "nodeInstructions": {},
    }


def normalize_skill(value, node_ids):
    from .definitions import invalid, keys, text

    keys(value, {"title", "instructions", "nodeInstructions"}, "业务流配套技能")
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
        + "\n业务流配套技能："
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
