"""Task-owned agent loop. Nodes are milestones and tool state, never new agents."""

from copy import deepcopy

from apps.compute.packages import ComputeError
from .execution_session import session
from .ledger import text
from .state import binding, state, persist

# Configuration: no transcript/file accumulation; keep short recent action notes.
MAX_HISTORY = 12
MAIN_IDENTITY = """你是本任务唯一的主执行智能体，在一个持续任务循环中完成整个业务流。
节点是目标、依赖与审核检查点。持续结合任务台账与task.history判断下一步。
"""
MAIN_INSTRUCTION = (
    MAIN_IDENTITY
    + """
task.phase=select_node时，使用start_node选择readyNodes中的合法目标；需要历史依据时可read_task_record。
task.phase=work时，亲自使用当前目标允许的工具组织输入、参数、预检和计算，验证后finish_node交付。
finish_node只结束当前目标；审核和必要人工确认完成后，继续选择下一目标，不提前宣称整个任务完成。
task.phase=finish_workflow时，核对全部目标已完成后返回finish_workflow及简短summary。
每次仅输出一个{"action":"工具名","arguments":{...}}。不改核心算法，不代替审核或人工批准。
遇到错误依据真实诊断调整允许的输入或参数，重新预检；不能重复相同错误方案。
文件以成果引用交接，按需读取片段或统计，不将完整文件或完整历史加入上下文。
"""
)


def remember(workflow, node_id, action, summary):
    value = session(workflow)
    if not value:
        return
    loop = value["loop"]
    loop["steps"] += 1
    loop["history"] = [
        *loop["history"],
        {"nodeId": node_id, "action": action, "summary": text(summary, 240)},
    ][-MAX_HISTORY:]


def take_action(
    workflow,
    node,
    evidence,
    contract,
    context,
    *,
    guard,
    policy,
    on_record,
    on_progress=None,
    on_thinking=None,
):
    """The sole action-producing model entry for the task's main executor."""
    from apps.agent.business_flow_actions import (
        INSTRUCTION,
        NATIVE_TOOLS,
        validate_action,
        ActionFormatError,
    )
    from apps.agent.business_flow_model import request_node_result
    from apps.agent.config import registry

    value = session(workflow)
    if not value:
        raise ComputeError("缺少任务级主执行会话")
    loop = value["loop"]
    task = {
        "phase": context.pop("taskPhase", "work"),
        "activeNodeId": loop.get("activeNodeId", ""),
        "history": deepcopy(loop["history"][-8:]),
        "readyNodes": context.pop("readyNodes", []),
        **({"recalledRecord": deepcopy(loop["recall"])} if loop.get("recall") else {}),
    }
    native = registry()[workflow.model].native_tools and not context.get("jsonFallback")
    tool_guidance = INSTRUCTION[INSTRUCTION.index("输入证据、工具结果") :]

    def validate(raw, available):
        value = validate_action(raw, available)
        if value["action"] not in contract["tools"]:
            raise ActionFormatError(
                "当前任务阶段仅允许：" + "、".join(contract["tools"])
            )
        return value

    return request_node_result(
        workflow,
        node,
        context.get("step", loop["steps"] + 1),
        evidence,
        role="executor",
        instruction=MAIN_INSTRUCTION + tool_guidance,
        validate=validate,
        caps={},
        guard=guard,
        policy=policy,
        context={
            **context,
            "task": task,
            "contract": contract,
            "purpose": "node_tools" if task["phase"] == "work" else "workflow_control",
            "executionScope": "node" if task["phase"] == "work" else "workflow",
        },
        human_required=node["review"]["human"] and task["phase"] == "work",
        on_record=on_record,
        on_progress=on_progress,
        on_thinking=on_thinking,
        tools=NATIVE_TOOLS if native else None,
    )


def _control(workflow, user, policy, nodes, *, closing=False, summary=""):
    from .engine import live_guard
    from .execution_session import task_record
    from .node_loop import wait_recovery

    definitions = binding(workflow)["definitionSnapshot"]["nodes"]
    fallback = nodes[0] if nodes else definitions[-1]
    workflow.current_step, workflow.status = fallback["id"], "running"
    loop = session(workflow)["loop"]
    phase = "finish_workflow" if closing else "select_node"
    loop["phase"] = phase
    tools = (
        ["finish_workflow"]
        if closing
        else ["start_node", "read_task_record", "ask_user"]
    )
    contract = {
        "goal": "核对整体完成情况" if closing else "选择下一工作目标",
        "tools": tools,
    }
    ready = [
        {
            "id": node["id"],
            "title": text(node["title"], 240),
            "kind": node["kind"],
            "description": text(node.get("description", ""), 180),
        }
        for node in nodes
    ]
    evidence = [
        {
            "id": "workflow-progress",
            "kind": "analysis",
            "title": "本任务实际进度",
            "result": {
                "completedNodes": [
                    key
                    for key, item in state(workflow)["nodes"].items()
                    if item["status"] in {"succeeded", "skipped"}
                ],
                "readyNodeIds": [node["id"] for node in nodes],
                "verifiedSummary": text(summary, 1200),
            },
        }
    ]

    def record(value):
        loop["lastAudit"] = value
        persist(workflow)

    try:
        result = take_action(
            workflow,
            fallback,
            evidence,
            contract,
            {
                "taskPhase": phase,
                "readyNodes": ready,
                "formatFeedback": loop.get("formatFeedback", ""),
                "userAnswer": (
                    state(workflow)["nodes"][fallback["id"]]
                    .get("toolLoop", {})
                    .get("userAnswer", "")
                    if state(workflow)["nodes"][fallback["id"]]
                    .get("toolLoop", {})
                    .get("userAnswerScope")
                    == "workflow"
                    else ""
                ),
            },
            guard=live_guard(workflow),
            policy=policy,
            on_record=record,
        )
        action, args = result["action"], result["arguments"]
        if action not in tools:
            raise ComputeError("主执行动作不属于当前任务阶段允许的工具")
        if action == "start_node":
            identity = args.get("nodeId")
            if not isinstance(identity, str) or identity not in {
                node["id"] for node in nodes
            }:
                raise ComputeError("主执行智能体只能选择依赖已满足的工作目标")
            loop.update(activeNodeId=identity, phase="work")
            remember(workflow, identity, action, "主执行智能体选择继续该目标")
        elif action == "read_task_record":
            recalled = task_record(
                workflow,
                args.get("nodeId"),
                offset=args.get("offset", 0),
                limit=args.get("limit", 8),
            )
            loop["recall"] = recalled
            remember(workflow, fallback["id"], action, recalled["summary"])
        elif action == "ask_user":
            question = args.get("question")
            if not isinstance(question, str) or not question.strip():
                raise ComputeError("主执行智能体提问为空")
            wait_recovery(
                workflow,
                fallback,
                state(workflow)["nodes"][fallback["id"]],
                {
                    "code": "MAIN_AGENT_QUESTION",
                    "remedy": "human_review",
                    "message": question[:1000],
                },
                question=question,
            )
            return False
        else:
            final = args.get("summary")
            if not isinstance(final, str) or not final.strip() or len(final) > 2000:
                raise ComputeError("任务结束须有简短的实际完成说明")
            loop.update(
                phase="completed",
                completed=True,
                finalSummary=final.strip(),
                activeNodeId="",
            )
            remember(workflow, fallback["id"], action, final)
        loop.pop("formatFeedback", None)
        workflow.status = "queued"
        persist(workflow)
        return action in {"start_node", "finish_workflow"}
    except ComputeError as error:
        if not loop.get("formatFeedback"):
            loop["formatFeedback"] = str(error)[:500]
            workflow.status = "queued"
            persist(workflow)
            return False
        from .failure_handoff import handoff_exception

        error.recovery_scope = "workflow"
        handoff_exception(workflow, error)
        return False


def select_node(workflow, user, policy, ready):
    loop = session(workflow)["loop"]
    current = next(
        (node for node in ready if node["id"] == loop.get("activeNodeId")), None
    )
    if current:
        return current
    loop["activeNodeId"] = ""
    if not ready:
        raise ComputeError("没有依赖已满足的工作目标")
    _control(workflow, user, policy, ready)
    return None


def finish_workflow(workflow, user, policy, summary=""):
    if session(workflow)["loop"].get("completed"):
        return True
    return _control(workflow, user, policy, [], closing=True, summary=summary)


def compile_node(node):
    from .node_contracts import normalize_contract, recovery_contract

    executable = deepcopy(node)
    if executable.get("contract"):
        return executable
    if executable["kind"] == "operator":
        executable["contract"] = recovery_contract(node)
    else:
        executable["contract"] = normalize_contract(
            {
                "goal": node.get("instruction") or node["description"] or node["title"],
                "acceptance": ["依据实际证据完成当前目标并说明局限"],
                "requiredOutputs": [{"name": "analysis", "semanticType": "analysis"}],
                "tools": [
                    "read_evidence",
                    "read_task_record",
                    "ask_user",
                    "finish_node",
                ],
            }
        )
    return executable


def advance_active(workflow, user, policy, node, item, evidence, *, guard, callbacks):
    from .node_loop import advance_tool_execution

    executable = compile_node(node)
    return advance_tool_execution(
        workflow,
        user,
        policy,
        executable,
        item,
        evidence,
        guard=guard,
        callbacks=callbacks,
        requester=take_action,
    )


def professional_tick(workflow, user, policy, stage):
    from .logic_nodes import execute_stage_tools

    definition = next(
        node
        for node in binding(workflow)["definitionSnapshot"]["nodes"]
        if node["id"] == stage["name"]
    )
    if select_node(workflow, user, policy, [definition]) is None:
        return
    execute_stage_tools(workflow, user, policy, stage, requester=take_action)


def specialized_context(workflow, node_id):
    value = session(workflow)
    if not value:
        return {}
    return {
        "phase": "input_mapping"
        if node_id == "inputs"
        else "report"
        if node_id == "finish"
        else "analysis",
        "activeNodeId": node_id,
        "history": deepcopy(value["loop"]["history"][-8:]),
    }
