"""One admission counter for execution, reviews and preparation model calls."""

from apps.compute.packages import ComputeError

MAX_MODEL_CALLS = 256


class ModelCallBudgetExceeded(ComputeError):
    pass


def admit(workflow, request_id, *, maximum=MAX_MODEL_CALLS):
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
                "业务流已达到本次模型请求额度，已保留当前结果"
            )
        item = state(workflow).get("nodes", {}).get(workflow.current_step, {})
        loop = item.get("toolLoop")
        if loop is not None and request_id not in loop.setdefault("requestIds", []):
            from .state import binding
            from .node_contracts import recovery_contract

            node = next(
                row
                for row in binding(workflow)["definitionSnapshot"]["nodes"]
                if row["id"] == workflow.current_step
            )
            contract = node.get("contract") or recovery_contract(node)
            if loop["modelCalls"] >= contract["maxModelCalls"]:
                raise ModelCallBudgetExceeded("节点模型调用额度已用尽，已保留当前结果")
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
