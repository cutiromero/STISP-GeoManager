"""One admission counter for execution, reviews and preparation model calls."""

from apps.compute.packages import ComputeError

MAX_MODEL_CALLS = 256


def request_limit(policy, definition=None):
    """A zero tool-step setting means unlimited; the platform ceiling still applies."""
    steps = policy["maxSteps"]
    if steps == 0:
        return MAX_MODEL_CALLS
    routing = (
        len(definition["nodes"]) + 1
        if definition and definition.get("executionMode") == "main_agent"
        else 0
    )
    # Main-agent routing is mandatory framework overhead. Without this reserve
    # a valid 32-goal flow cannot even finish its shortest path under defaults.
    return min(MAX_MODEL_CALLS, max(4, steps * 2) + routing)


def check_start_budget(policy, definition, input_plan, *, agent_enabled=True):
    """Check the known minimum of the complete normal path before creating work."""
    from .input_policy import for_definition

    nodes = definition["nodes"]
    preparation = for_definition(definition)
    rows = input_plan.get("items", [])
    conversions = {
        (row.get("sourceId"), row.get("versionId"))
        for row in rows
        if row["status"] in {"convert", "needs_script"}
    }
    scripts = {
        (row.get("sourceId"), row.get("versionId"))
        for row in rows
        if row["status"] == "needs_script"
    }
    scientific = definition["adapter"] == "geology_generic"

    def calculation(node):
        return node["kind"] == "operator" or any(
            row["semanticType"] != "analysis"
            for row in node.get("contract", {}).get("requiredOutputs", [])
        )

    calculations = 5 if scientific else sum(calculation(node) for node in nodes)
    operators = calculations + len(conversions)
    reviews = sum(node["review"]["ai"] for node in nodes)
    if agent_enabled and definition.get("executionMode") == "main_agent":
        # Scientific mapping may be reused; its five calculations and final
        # analysis still require the task's own actions, routing and review.
        models = (
            calculations * 4 + calculations + 1 + 1 + reviews
            if scientific
            else (
                len(nodes)
                + 1
                + sum(4 if calculation(node) else 1 for node in nodes)
                + reviews
            )
        )
    else:
        models = reviews + (
            0 if scientific else sum(node["kind"] == "agent" for node in nodes)
        )
    models += len(scripts) * (1 + int(preparation["reviewScripts"]))
    if models > request_limit(policy, definition):
        raise ComputeError(
            f"流程完整正常路径至少需要{models}次模型请求，当前额度{request_limit(policy, definition)}次；"
            "请管理员提高调用次数额度或调整流程，任务尚未创建",
            409,
        )
    if operators > policy["maxOperatorSteps"]:
        raise ComputeError(
            f"流程及输入准备至少需要{operators}次算子调用，当前额度{policy['maxOperatorSteps']}次；"
            "请管理员提高算子调用额度或调整输入，任务尚未创建",
            409,
        )


class ModelCallBudgetExceeded(ComputeError):
    def __init__(self, message, *, scope="task", used=None, limit=None):
        super().__init__(message)
        self.scope, self.used, self.limit = scope, used, limit


def operator_budget_wait(node_id, used, limit, *, scope="task", preparation_role=None):
    from apps.agent.business_flow_context import ContextReviewRequired

    return ContextReviewRequired(
        {
            "nodeId": node_id,
            "level": 0,
            "kind": "operator_call_limit",
            "budgetScope": scope,
            "usedOperatorCalls": used,
            "limit": limit,
            "evidence": [],
            "reason": f"算子调用额度已用{used}/{limit}次，当前成果保留；请提高允许额度后继续。",
            **({"preparationRole": preparation_role} if preparation_role else {}),
        }
    )


def renew_operator_budget(workflow, policy, recovery):
    if recovery.get("kind") != "operator_call_limit":
        return
    if recovery.get("budgetScope") == "node":
        raise ComputeError("节点算子调用上限已用尽，不能通过重试重置额度", 409)
    allowance = policy["maxOperatorSteps"]
    if allowance <= workflow.max_operator_steps or allowance <= workflow.operator_steps:
        raise ComputeError(
            "当前算子允许额度尚未增加，请管理员提高后重试；已用计数保留", 409
        )
    from .state import state

    state(workflow).setdefault("budgetAdjustments", []).append(
        {
            "kind": "operator",
            "previousLimit": workflow.max_operator_steps,
            "limit": allowance,
            "usedOperatorCalls": workflow.operator_steps,
        }
    )
    workflow.max_operator_steps = allowance


def renew_task_budget(workflow, policy, recovery):
    """An explicit retry may adopt a larger live allowance; never reset usage."""
    if recovery.get("kind") != "model_call_limit":
        return
    if recovery.get("budgetScope") == "node":
        raise ComputeError(
            "节点合同额度已用尽；须发布额度更高的流程版本，重试不会重置计数", 409
        )
    from .state import binding, state

    allowance = request_limit(policy, binding(workflow)["definitionSnapshot"])
    values = state(workflow)
    spent = len(values.get("requestedIds", [])) + (
        workflow.plan.get("actualModelCallCount", 0)
        if workflow.workflow_type != "business_flow"
        else 0
    )
    minimum = max(1, recovery.get("minimumRemainingRequests", 1))
    if allowance <= workflow.max_iterations or allowance < spent + minimum:
        raise ComputeError(
            f"当前允许额度尚未增加到可继续的范围：已用{spent}次，至少还需{minimum}次。请由管理员提高允许额度后重试；计数保留",
            409,
        )
    values.setdefault("budgetAdjustments", []).append(
        {
            "previousLimit": workflow.max_iterations,
            "limit": allowance,
            "usedRequests": spent,
        }
    )
    workflow.max_iterations = allowance


def admit(workflow, request_id, *, maximum=MAX_MODEL_CALLS, node_scoped=True):
    if not isinstance(request_id, str) or not request_id:
        raise ComputeError("模型请求缺少实际编号")
    if workflow.parameters.get("_businessFlow"):
        from .state import state

        calls = state(workflow).setdefault("requestedIds", [])
        spent = (
            workflow.plan.get("actualModelCallCount", 0)
            if workflow.workflow_type != "business_flow"
            else 0
        )
        if request_id in calls:
            return
        if len(calls) + spent >= min(maximum, workflow.max_iterations):
            raise ModelCallBudgetExceeded(
                "业务流已达到本次模型请求额度，已保留当前结果",
                used=len(calls) + spent,
                limit=min(maximum, workflow.max_iterations),
            )
        item = state(workflow).get("nodes", {}).get(workflow.current_step, {})
        loop = item.get("toolLoop")
        if (
            node_scoped
            and loop is not None
            and request_id not in loop.setdefault("requestIds", [])
        ):
            from .state import binding
            from .node_contracts import recovery_contract

            node = next(
                row
                for row in binding(workflow)["definitionSnapshot"]["nodes"]
                if row["id"] == workflow.current_step
            )
            from . import logic_nodes

            if (
                logic_nodes.enabled(workflow)
                and workflow.current_step != "final_analysis"
            ):
                node = logic_nodes.node_definition(
                    workflow, logic_nodes.current_stage(workflow, node["id"])
                )
            contract = node.get("contract") or recovery_contract(node)
            if loop["modelCalls"] >= contract["maxModelCalls"]:
                raise ModelCallBudgetExceeded(
                    "节点模型调用额度已用尽，已保留当前结果",
                    scope="node",
                    used=loop["modelCalls"],
                    limit=contract["maxModelCalls"],
                )
            loop["requestIds"].append(request_id)
            loop["modelCalls"] += 1
        calls.append(request_id)
    else:
        calls = workflow.plan.setdefault("inputScriptRequestIds", [])
        if request_id in calls:
            return
        spent = workflow.plan.get("actualModelCallCount", 0)
        if spent >= min(maximum, workflow.max_iterations):
            raise ModelCallBudgetExceeded("任务已达到本次模型请求额度，已保留当前结果")
        calls.append(request_id)
        workflow.plan["actualModelCallCount"] = spent + 1
