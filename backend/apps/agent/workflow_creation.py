"""Shared workflow creation; browser and chat use identical validation/locking."""

from django.db import connection, transaction
from django.db.models import F

from apps.compute.packages import ComputeError
from .models import AgentPolicy, AgentWorkflow
from .policy import require_access


def create_workflow(user, project_id, value, *, chat_execution=None, input_plan=None):
    p = require_access(user, "agent", value.get("model"))
    if not p.get("workflowEnabled", True):
        raise ComputeError("MH-workflow功能已关闭", 403)
    goal = value.get("goal")
    model = value.get("model")
    workflow_type = value.get("workflowType", "hyperspectral_interpretation")
    key = value.get("idempotencyKey")
    resources_selected = value.get("resourceIds", [])
    parameters = value.get("parameters", {})
    if isinstance(parameters, dict) and "_businessFlow" in parameters:
        raise ComputeError("业务流绑定只能由已发布业务流启动入口创建")
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
        raise ComputeError("MH-workflow参数无效")
    if execute_operators and not p.get("operatorEnabled", False):
        raise ComputeError("智能体自动调用算子尚未由超级管理员开启", 403)
    if execute_operators:
        raise ComputeError("请先生成计划，再使用确认执行入口")
    resources_selected = sorted(set(resources_selected))
    if workflow_type == "geology_multi_element_reasoning":
        from .geology_multi import validate_inputs

        validate_inputs(user, p, inputs, parameters, resources_selected)
    if workflow_type == "geology_map_review":
        from .geology_input_validation import validate_geology_inputs

        validate_geology_inputs(user, p, inputs, parameters, resources_selected)
    generic_plan = {}
    if workflow_type == "geology_generic":
        from .geology_generic import validate_creation

        batch_id = value.get("uploadBatchId")
        if input_plan is None:
            from apps.business_flows.builtins import geology_definition
            from apps.business_flows.input_adapters import plan_inputs
            from .workflow_uploads import batch_uploads

            uploads = {row.resource_id: row for row in batch_uploads(user, batch_id)}
            if set(inputs.values()) - set(uploads):
                raise ComputeError("资料角色只能选择本次任务上传的资料或已授权目录引用")
            planned = plan_inputs(
                user,
                geology_definition()["inputRequirements"],
                {
                    role: (
                        uploads[identity].resource,
                        {
                            **uploads[identity].profile,
                            "bands": uploads[identity].profile.get("bandCount", 0),
                        },
                    )
                    for role, identity in inputs.items()
                },
            )
            if not planned["ready"]:
                raise ComputeError("请先在业务流资料准备中选择输入适配工具与参数")
            input_plan = [
                {
                    key: value
                    for key, value in row.items()
                    if key not in {"fields", "candidates"}
                }
                for row in planned["items"]
            ]
        rules_id = validate_creation(
            user, p, inputs, parameters, batch_id, key, adaptations=input_plan
        )
        resources_selected = sorted(set(inputs.values()) | {rules_id})
        generic_plan = {
            "uploadInputs": inputs,
            "uploadBatchId": batch_id,
            "rulesResourceId": rules_id,
            **({"inputAdaptations": input_plan} if input_plan else {}),
        }
        inputs = {}
    elif value.get("uploadBatchId") is not None:
        raise ComputeError("只有通用地质推理使用上传批次")
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
                raise ComputeError("幂等键已用于不同MH-workflow", 409)
            return existing
        from .workflow_slots import require_compute_slot

        require_compute_slot(user)
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
                **generic_plan,
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
        if generic_plan:
            from .workflow_uploads import bind_batch

            bind_batch(
                workflow,
                user,
                generic_plan["uploadBatchId"],
                generic_plan["uploadInputs"],
            )
    return workflow
