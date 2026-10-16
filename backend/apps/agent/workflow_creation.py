"""Shared workflow creation; browser and chat use identical validation/locking."""

from django.db import connection, transaction
from django.db.models import F

from apps.compute.packages import ComputeError
from .models import AgentPolicy, AgentWorkflow, WORKFLOW_ACTIVE
from .policy import require_access


def create_workflow(user, project_id, value, *, chat_execution=None):
    p = require_access(user, "agent", value.get("model"))
    if not p.get("workflowEnabled", True):
        raise ComputeError("科研工作流功能已关闭", 403)
    goal = value.get("goal")
    model = value.get("model")
    workflow_type = value.get("workflowType", "hyperspectral_interpretation")
    key = value.get("idempotencyKey")
    resources_selected = value.get("resourceIds", [])
    parameters = value.get("parameters", {})
    execute_operators = value.get("executeOperators", False)
    algorithm_id = value.get("algorithmVersionId")
    inputs = value.get("inputs", {})
    import_results = value.get("importResults", True)
    previous_workflow = value.get("previousWorkflowId")
    if previous_workflow is not None:
        from uuid import UUID

        try:
            UUID(previous_workflow)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ComputeError("原分析记录无效") from exc
        if workflow_type != "ecology_investigation":
            raise ComputeError("补充证据更新目前适用于生态分析")
    from .selections import normalize

    knowledge_selection = normalize(value, resources_selected)["knowledge_selection"]
    if (
        not isinstance(goal, str)
        or not 1 <= len(goal.strip()) <= 12000
        or not isinstance(workflow_type, str)
        or not 1 <= len(workflow_type) <= 40
        or not isinstance(model, str)
        or not isinstance(key, str)
        or not 8 <= len(key) <= 80
        or not isinstance(resources_selected, list)
        or (p["maxResources"] > 0 and len(resources_selected) > p["maxResources"])
        or any(type(i) is not int or i < 1 for i in resources_selected)
        or not isinstance(parameters, dict)
        or len(parameters) > 60
        or type(execute_operators) is not bool
        or (algorithm_id is not None and type(algorithm_id) is not int)
        or not isinstance(inputs, dict)
        or len(inputs) > 30
        or any(
            not isinstance(k, str) or type(v) is not int or v < 1
            for k, v in inputs.items()
        )
        or type(import_results) is not bool
    ):
        raise ComputeError("科研工作流参数无效")
    if execute_operators and not p.get("operatorEnabled", False):
        raise ComputeError("智能体自动调用算子尚未由超级管理员开启", 403)
    if execute_operators:
        raise ComputeError("请先生成计划，再使用确认执行入口")
    resources_selected = sorted(set(resources_selected))
    with transaction.atomic():
        if connection.vendor == "sqlite":
            # Reserve the writer before any reads establish a WAL snapshot.
            # An empty/no-op UPDATE also reserves it without altering state.
            AgentWorkflow._base_manager.filter(
                owner=user,
                project_tag_id=project_id,
                idempotency_key=key,
            ).update(idempotency_key=F("idempotency_key"))
        existing = AgentWorkflow._base_manager.filter(
            owner=user,
            project_tag_id=project_id,
            idempotency_key=key,
        ).first()
        if existing:
            if (
                existing.goal != goal.strip()
                or existing.model != model
                or existing.policy_snapshot.get("request") != value
            ):
                raise ComputeError("幂等键已用于不同科研工作流", 409)
            return existing
        if AgentWorkflow._base_manager.filter(
            owner=user, status__in=WORKFLOW_ACTIVE
        ).exists():
            raise ComputeError("您已有活动科研工作流，请等待完成", 409)
        workflow = AgentWorkflow.objects.create(
            owner=user,
            workflow_type=workflow_type,
            goal=goal.strip(),
            model=model,
            max_iterations=p["maxIterations"],
            max_operator_steps=p["maxOperatorSteps"],
            execute_operators=execute_operators,
            resource_ids=resources_selected,
            algorithm_version_id=algorithm_id,
            parameters=parameters,
            plan={
                "inputs": inputs,
                "knowledgeSelection": knowledge_selection,
                **({"chatExecution": chat_execution} if chat_execution else {}),
                **(
                    {"previousWorkflowId": value["previousWorkflowId"]}
                    if value.get("previousWorkflowId")
                    else {}
                ),
            },
            import_results=import_results,
            idempotency_key=key,
            policy_snapshot={
                "request": value,
                "revision": AgentPolicy.objects.filter(pk=1)
                .values_list("updated_at", flat=True)
                .first()
                .isoformat()
                if AgentPolicy.objects.filter(pk=1).exists()
                else "",
                "maxIterations": p["maxIterations"],
                "maxOperatorSteps": p["maxOperatorSteps"],
                "operatorEnabled": p.get("operatorEnabled", False),
            },
        )
    return workflow
