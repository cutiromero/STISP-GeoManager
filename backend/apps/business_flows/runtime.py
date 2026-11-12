"""Public start/decision/control boundaries for versioned scientific flows."""

from copy import deepcopy
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.agent.models import AgentRun, AgentWorkflow, Conversation
from apps.agent.policy import require_access
from apps.agent.resource_discovery import (
    resolve_discoverable_resource,
)
from apps.agent.run_concurrency import (
    lock_run_queue,
    require_run_capacity,
    retry_run_admission,
)
from apps.agent.workflow_controls import locked_workflow
from apps.agent.workflow_slots import require_compute_slot
from apps.compute.packages import ComputeError
from apps.projects.context import selected_project_id
from .models import BusinessFlowVersion
from .model_requests import request_limit
from .state import (
    binding,
    digest,
    emit,
    initial_state,
    state,
    TERMINAL,
)


def authorize(user, workflow, *, history=False):
    if workflow.owner_id != user.pk or workflow.project_tag_id != selected_project_id():
        raise PermissionDenied("业务流不属于当前账号或项目")
    bind = binding(workflow)
    version = (
        BusinessFlowVersion.objects.select_related("flow")
        .filter(
            pk=bind.get("versionId"),
            flow_id=bind.get("flowId"),
            flow__project_tag_id=workflow.project_tag_id,
        )
        .first()
    )
    if (
        not version
        or version.definition_hash != bind.get("definitionHash")
        or version.definition != bind["definitionSnapshot"]
    ):
        raise PermissionDenied("冻结的业务流版本无法核实")
    if not history and not version.flow.is_active:
        raise PermissionDenied("业务流已停用，不能继续新的执行步骤")
    policy = require_access(user, "agent", workflow.model)
    if not policy.get("workflowEnabled", True):
        raise PermissionDenied("业务流执行权限已关闭")
    if workflow.workflow_type == "geology_generic":
        from apps.agent.workflow import _authorize, authorize_workflow_history

        if history:
            _, policy = authorize_workflow_history(workflow)
        else:
            _, policy = _authorize(workflow)
            if workflow.plan.get("scenarioVersion"):
                from apps.agent.demo_workflow import authorize_demo

                authorize_demo(workflow, user, policy)
    if not history or workflow.workflow_type == "business_flow":
        authorize_inputs(user, policy, bind.get("inputVersions", {}), history=history)
    return policy


def authorize_inputs(user, policy, versions, *, history=False):
    from apps.agent.resource_discovery import acl_resources

    identities = {item["id"] for item in versions.values()}
    if not identities:
        return
    visible = (
        acl_resources(user, policy, identities, active=not history)
        .only("id", "updated_at")
        .in_bulk()
    )
    if set(visible) != identities:
        raise PermissionDenied("业务流输入资料不存在、停用或已被撤权")
    if not history and any(
        visible[item["id"]].updated_at.isoformat() != item["updatedAt"]
        for item in versions.values()
    ):
        raise PermissionDenied("输入资料版本已变化，请重新发起业务流")


def canonical_current_node(workflow):
    if workflow.workflow_type != "business_flow" and workflow.parameters.get(
        "_businessFlow"
    ):
        if (
            workflow.current_step
            in {
                "review_mapping",
                "review_plan",
                "build_inputs",
                "inputs_ready",
                "prepare",
            }
            or not workflow.current_step
        ):
            return "inputs"
        if workflow.current_step == "human_review":
            plan = workflow.__dict__.get("plan", {})
            stages = plan.get("stages", [])
            index = plan.get("stageIndex", 0)
            return stages[index]["name"] if index < len(stages) else "finish"
        if workflow.current_step == "review_modifications":
            return "apply"
        if workflow.current_step in {"final_analysis", "finalize"}:
            return "finish"
    return workflow.current_step


def serialize_run(user, workflow, *, control_only=False):
    from .script_preparation import public_item

    if control_only:
        if (
            workflow.owner_id != user.pk
            or workflow.project_tag_id != selected_project_id()
        ):
            raise PermissionDenied("业务流归属不一致")
    else:
        authorize(user, workflow, history=workflow.status in TERMINAL)
    bind = binding(workflow)
    if workflow.workflow_type != "business_flow":
        from .legacy import projected_state

        value = projected_state(workflow)
    else:
        value = state(workflow)
    projected = []
    for node in bind["definitionSnapshot"]["nodes"]:
        item = deepcopy(value["nodes"][node["id"]])
        item.pop("executionContextId", None)
        item.pop("contextPreviousExecutor", None)
        item.pop("reviewContextBudget", None)
        for actor in ("executor", "reviewer"):
            item.get(actor, {}).get("audit", {}).pop("responsePreview", None)
        for attempt in item.get("attempts", []):
            attempt.pop("responsePreview", None)
        loop = item.pop("toolLoop", None)
        if loop:
            item["toolProgress"] = {
                key: deepcopy(loop.get(key))
                for key in (
                    "steps",
                    "modelCalls",
                    "operatorCalls",
                    "recoveries",
                    "history",
                )
            }
        # The legacy executor keeps its full structured decision privately.
        # Public actor.decision is reserved for the review decision string.
        if isinstance(item.get("executor", {}).get("decision"), dict):
            item["executor"].pop("decision")
        if (
            workflow.workflow_type == "geology_generic"
            and workflow.status == "waiting_approval"
            and not item.get("contextRecovery")
            and not item.get("recovery")
            and node["id"] == canonical_current_node(workflow)
        ):
            item["human"].update(
                required=True, status="pending", reason=workflow.detail
            )
            item["status"] = "waiting_human"
        item["outputs"] = {
            "evidence": [
                {key: row.get(key) for key in ("id", "kind", "title")}
                for row in item.get("outputs", {}).get("evidence", [])
            ],
            **{
                key: item.get("outputs", {}).get(key)
                for key in ("taskId",)
                if key in item.get("outputs", {})
            },
        }
        if workflow.status in {"paused", "cancelled"} and item["status"] not in {
            "succeeded",
            "skipped",
            "pending",
        }:
            item["status"] = workflow.status
        if control_only:
            item = {
                "nodeId": item["nodeId"],
                "status": item["status"],
                "attempt": item["attempt"],
                "executor": {"status": "unavailable"},
                "reviewer": {"status": "unavailable"},
                "outputs": {},
                "human": {
                    "required": item["human"]["required"],
                    "status": item["human"]["status"],
                    "reason": "",
                },
            }
        projected.append(item)
    return {
        "id": str(workflow.pk),
        "flowId": bind["flowId"],
        "versionId": bind["versionId"],
        "projectId": workflow.project_tag_id,
        "conversationId": bind["conversationId"],
        "runId": bind["runId"],
        "name": bind["name"],
        "goal": workflow.goal,
        "status": workflow.status,
        "currentNode": canonical_current_node(workflow),
        "definitionSnapshot": bind["definitionSnapshot"],
        "nodes": projected,
        "events": [] if control_only else value.get("events", []),
        "revision": value.get("revision", 0),
        "resultResourceIds": [] if control_only else workflow.result_resource_ids,
        "resultOutputIds": [] if control_only else workflow.result_ids,
        "createdAt": workflow.created_at.isoformat(),
        "updatedAt": workflow.updated_at.isoformat(),
        **(
            {
                "inputPreparation": {
                    "ready": all(
                        row["status"] in {"direct", "ready"}
                        for row in workflow.plan.get("inputAdaptations", [])
                    ),
                    "items": [
                        public_item(item)
                        for item in workflow.plan.get("inputAdaptations", [])
                    ],
                }
            }
            if not control_only
            else {}
        ),
    }


def _inputs(
    user, definition, value, policy, *, preview=False, allowed_adapter_ids=None
):
    from .input_adapters import logical_role, plan_inputs
    from apps.compute.data import list_candidate
    from .input_policy import for_definition
    from .script_bridges import versions as bridge_catalog

    supplied = value.get("inputs", {})
    specs = {item["key"]: item for item in definition["inputRequirements"]}
    if (
        not isinstance(supplied, dict)
        or len(supplied) > 30
        or any(
            type(identity) is not int or identity < 1 for identity in supplied.values()
        )
    ):
        raise ValidationError("资料角色必须使用业务流声明的角色和真实资源编号")
    logical = {key: logical_role(key, specs) for key in supplied}
    if not preview and any(
        item["required"] and key not in logical.values() for key, item in specs.items()
    ):
        raise ValidationError("请补齐业务流必需的输入资料")
    versions, sources, cached = {}, {}, {}
    batch_id = value.get("parameters", {}).get("uploadBatchId") or value.get(
        "uploadBatchId"
    )
    if definition["adapter"] == "geology_generic" and batch_id:
        from apps.agent.models import WorkflowUpload

        cached = {
            row.resource_id: {**row.profile, "bands": row.profile.get("bandCount", 0)}
            for row in WorkflowUpload.objects.filter(
                owner=user, batch_id=batch_id, resource_id__in=list(supplied.values())
            ).only("resource_id", "profile")
        }
    for role, identity in supplied.items():
        if definition["adapter"] == "geology_generic":
            from apps.agent.workflow_resources import resolve_upload_resource

            resource = (
                resolve_upload_resource(user, policy, identity, batch_id)
                if batch_id
                else resolve_discoverable_resource(user, policy, identity)
            )
        else:
            resource = resolve_discoverable_resource(user, policy, identity)
        if resource.pk not in cached:
            metadata = list_candidate(resource)
            if resource.data_type == "raster" and specs[logical[role]].get(
                "semanticType"
            ):
                from apps.raster.models import RasterDataset

                dataset = (
                    RasterDataset.objects.filter(data_resource=resource, status="ready")
                    .only("source_gdalinfo")
                    .first()
                )
                metadata["semanticType"] = (
                    (
                        (dataset.source_gdalinfo or {})
                        .get("metadata", {})
                        .get("", {})
                        .get("stisp_input_semantics", "")
                    )
                    if dataset
                    else ""
                )
            cached[resource.pk] = metadata
        sources[role] = resource, cached[resource.pk]
        versions[role] = {
            "id": identity,
            "name": resource.name,
            "dataType": resource.data_type,
            "updatedAt": resource.updated_at.isoformat(),
        }
    available = None
    if allowed_adapter_ids is not None:
        from .input_adapters import capabilities

        available = [
            row
            for row in capabilities(user, pinned=allowed_adapter_ids)
            if row.pk in allowed_adapter_ids
        ]
    planned = plan_inputs(
        user,
        definition["inputRequirements"],
        sources,
        value.get("inputAdapters"),
        available=available,
        script_policy=for_definition(definition)
        if policy.get("operatorEnabled", False)
        else None,
        bridge_versions=bridge_catalog(permitted=allowed_adapter_ids)
        if allowed_adapter_ids is not None
        else None,
    )
    if not preview and not planned["ready"]:
        raise ValidationError("输入仍需配置转换能力或参数，请先查看输入适配方案")
    return dict(supplied), versions, planned


@retry_run_admission
def start_flow(user, version, value, *, source_run=None):
    if (
        version.flow.project_tag_id != selected_project_id()
        or not version.flow.is_active
        or version.status != "published"
    ):
        raise PermissionDenied("业务流版本不可执行")
    model, key = value.get("model"), value.get("idempotencyKey")
    if not isinstance(model, str) or not model:
        raise ValidationError("请选择已登记的执行模型")
    policy = require_access(user, "agent", model)
    from apps.agent.config import registry
    from apps.agent.workflow_model_policy import REASONING_EFFORTS

    effort = value.get("reasoningEffort", "medium")
    if not isinstance(effort, str) or effort not in REASONING_EFFORTS:
        raise ValidationError("思考强度必须为low、medium或xhigh")
    thinking = bool(policy.get("thinkingEnabled", True) and registry()[model].qwen)
    if "reasoningEffort" in value and not thinking:
        raise PermissionDenied("当前模型或策略不支持深度思考，不能应用所选强度")
    if (
        source_run
        and "reasoningEffort" in value
        and (
            source_run.thinking_mode != "deep" or source_run.reasoning_effort != effort
        )
    ):
        raise ValidationError("业务流思考设置必须与发起运行一致")
    if not policy.get("workflowEnabled", True):
        raise PermissionDenied("业务流执行权限已关闭")
    goal = value.get("goal", version.flow.description or version.flow.name)
    parameters = deepcopy(value.get("parameters", {}))
    if (
        not isinstance(model, str)
        or not isinstance(key, str)
        or not 8 <= len(key) <= 80
        or not isinstance(goal, str)
        or not 1 <= len(goal.strip()) <= 12000
    ):
        raise ValidationError("目标、模型或幂等键无效")
    if (
        not isinstance(parameters, dict)
        or len(parameters) > 50
        or any(str(name).startswith("_") for name in parameters)
    ):
        raise ValidationError("参数包含未声明的内部控制字段")
    try:
        if len(json.dumps(parameters, allow_nan=False).encode()) > 128 * 1024:
            raise ValidationError("启动参数超过128KiB边界")
    except (ValueError, TypeError, RecursionError) as error:
        raise ValidationError("启动参数必须是有限数值的有界JSON") from error
    definition = deepcopy(version.definition)
    if type(value.get("agentEnabled", True)) is not bool:
        raise ValidationError("agentEnabled必须为布尔值")
    if any(node["kind"] == "operator" for node in definition["nodes"]):
        if not policy.get("operatorEnabled", False):
            raise PermissionDenied("当前策略未允许业务流调用算子")
        from apps.compute.access import require_actor

        require_actor(user, selected_project_id(), "submit_task")
    if any(
        "nodeId" in source
        for node in definition["nodes"]
        for source in node.get("inputBindings", {}).values()
    ):
        from apps.compute.access import require_actor

        require_actor(user, selected_project_id(), "catalog.add_dataresource")
    if definition["adapter"] == "research_flow":
        if set(parameters) - {"nodeParameters"} or not isinstance(
            parameters.get("nodeParameters", {}), dict
        ):
            raise ValidationError("通用业务流参数须按nodeParameters绑定已声明算子节点")
        operators = {
            node["id"]: node
            for node in definition["nodes"]
            if node["kind"] == "operator"
        }
        supplied = parameters.get("nodeParameters", {})
        if set(supplied) - set(operators) or any(
            not isinstance(item, dict) or len(item) > 50 for item in supplied.values()
        ):
            raise ValidationError("参数包含未知算子节点或无效参数对象")
        from apps.compute.models import AlgorithmVersion

        versions_by_id = AlgorithmVersion.objects.filter(
            pk__in={node["algorithmVersionId"] for node in operators.values()}
        ).in_bulk()
        for identity, values in supplied.items():
            algorithm = versions_by_id.get(operators[identity]["algorithmVersionId"])
            if algorithm is None or set(values) - {
                item["key"] for item in algorithm.manifest["parameters"]
            }:
                raise ValidationError("启动参数包含算子清单未声明字段")
    reviewer = value.get("reviewerModel") or model
    for alias in {
        node["review"].get("model") or reviewer
        for node in definition["nodes"]
        if node["review"]["ai"]
    }:
        require_access(user, "agent", alias)
        if (
            source_run.thinking_mode == "deep" if source_run else thinking
        ) and not registry()[alias].qwen:
            raise PermissionDenied(
                "审核模型不支持本次深度思考设置，请选择支持思考的模型"
            )
    request_hash = digest(
        {
            "versionId": version.pk,
            "model": model,
            "reviewerModel": reviewer,
            "agentEnabled": value.get("agentEnabled", True),
            "goal": goal,
            "inputs": value.get("inputs", {}),
            "parameters": parameters,
            **(
                {"inputAdapters": value["inputAdapters"]}
                if value.get("inputAdapters")
                else {}
            ),
            "conversationId": value.get("conversationId"),
            "sourceRunId": source_run.pk if source_run else None,
            "reasoningEffort": source_run.reasoning_effort if source_run else effort,
            "thinkingMode": source_run.thinking_mode
            if source_run
            else ("deep" if thinking else "fast"),
        }
    )
    previous = AgentWorkflow._base_manager.filter(
        owner=user, project_tag_id=selected_project_id(), idempotency_key=key
    ).first()
    if previous:
        if binding(previous).get("requestHash") != request_hash:
            raise ComputeError("幂等键已用于另一份业务流请求", 409)
        return previous
    inputs, revisions, input_plan = _inputs(
        user,
        definition,
        value,
        policy,
        allowed_adapter_ids=set(source_run.algorithm_version_ids)
        if source_run and source_run.algorithm_selection_mode == "manual"
        else None,
    )
    if any(
        item["status"] in {"convert", "needs_script"} for item in input_plan["items"]
    ):
        from apps.compute.access import require_actor

        if not policy.get("operatorEnabled", False):
            raise PermissionDenied("当前策略未允许输入适配调用算子")
        require_actor(user, selected_project_id(), "submit_task")
        require_actor(user, selected_project_id(), "catalog.add_dataresource")
    if (
        definition["adapter"] == "research_flow"
        and policy["maxResources"] > 0
        and len(set(inputs.values())) > policy["maxResources"]
    ):
        raise ComputeError("本次输入超过当前策略允许的资料数量")
    with transaction.atomic():
        lock_run_queue()
        if not source_run:
            from apps.agent.policy import daily_quota

            quota = daily_quota(user, policy)
            if (
                quota > 0
                and AgentRun._base_manager.filter(
                    owner=user, created_at__date=timezone.localdate()
                ).count()
                >= quota
            ):
                raise ComputeError("今日智能体任务额度已用完，业务流尚未开始", 429)
        existing = AgentWorkflow._base_manager.filter(
            owner=user, project_tag_id=selected_project_id(), idempotency_key=key
        ).first()
        if existing:
            if binding(existing).get("requestHash") != request_hash:
                raise ComputeError("幂等键已用于另一份业务流请求", 409)
            return existing
        if source_run:
            conversation = Conversation.objects.get(
                pk=source_run.conversation_id, owner=user, mode="agent", archived=False
            )
        elif value.get("conversationId") is not None:
            conversation = Conversation.objects.get(
                pk=value["conversationId"], owner=user, mode="agent", archived=False
            )
            require_run_capacity(user.pk, conversation.pk)
        else:
            conversation = Conversation.objects.create(
                owner=user, mode="agent", title=version.flow.name[:120]
            )
            require_run_capacity(user.pk, conversation.pk)
        require_compute_slot(user)
        if definition["adapter"] == "geology_generic":
            from apps.agent.workflow_creation import create_workflow

            original = {
                "workflowType": "geology_generic",
                "model": model,
                "goal": goal.strip(),
                "idempotencyKey": key,
                "inputs": inputs,
                "resourceIds": list(inputs.values()),
                "uploadBatchId": parameters.pop("uploadBatchId", None),
                "parameters": parameters,
            }
            workflow = create_workflow(
                user,
                selected_project_id(),
                original,
                input_plan=[
                    {
                        key: item
                        for key, item in row.items()
                        if key not in {"fields", "candidates"}
                    }
                    for row in input_plan["items"]
                ],
            )
        else:
            workflow = AgentWorkflow.objects.create(
                owner=user,
                workflow_type="business_flow",
                model=model,
                goal=goal.strip(),
                idempotency_key=key,
                resource_ids=sorted(set(inputs.values())),
                parameters=parameters,
                import_results=True,
                max_iterations=request_limit(policy),
                max_operator_steps=policy["maxOperatorSteps"],
                plan={
                    "inputs": inputs,
                    "knowledgeSelection": {"mode": "none", "domains": []},
                },
                policy_snapshot={
                    "operatorEnabled": policy.get("operatorEnabled", False)
                },
            )
        run = source_run or AgentRun.objects.create(
            owner=user,
            conversation=conversation,
            model=model,
            prompt=goal.strip(),
            status="waiting_compute",
            idempotency_key="business-flow-" + key[:60],
            resource_ids=sorted(set(inputs.values())),
            knowledge_selection={"mode": "none", "domains": [], "_contextRunIds": []},
            thinking_mode="deep" if thinking else "fast",
            reasoning_effort=effort if thinking else "",
        )
        if run.owner_id != user.pk or run.project_tag_id != workflow.project_tag_id:
            raise PermissionDenied("业务流与发起对话归属不一致")
        run.research_workflow = workflow
        run.execution_state = {"phase": "business_flow", "workflowId": str(workflow.pk)}
        if not source_run:
            run.resource_ids = sorted(set(inputs.values()))
        run.detail = "已按发布版本启动业务流"
        if not source_run:
            run.status = "waiting_compute"
        run.save(
            update_fields=[
                "research_workflow",
                "execution_state",
                "resource_ids",
                "detail",
                "status",
                "updated_at",
            ]
        )
        workflow.parameters["_businessFlow"] = {
            "flowId": version.flow_id,
            "versionId": version.pk,
            "name": version.flow.name,
            "definitionSnapshot": definition,
            "definitionHash": version.definition_hash,
            "inputVersions": revisions,
            "conversationId": conversation.pk,
            "runId": run.pk,
            "reviewerModel": reviewer,
            "revision": 0,
            "requestHash": request_hash,
            "agentEnabled": value.get("agentEnabled", True),
        }
        if workflow.workflow_type == "geology_generic" and value.get(
            "agentEnabled", True
        ):
            from .logic_nodes import EXECUTION_MODE

            workflow.parameters["_businessFlow"]["nodeExecution"] = EXECUTION_MODE
            workflow.max_iterations = request_limit(policy)
        workflow.plan["inputAdaptations"] = [
            {
                key: item
                for key, item in row.items()
                if key not in {"fields", "candidates"}
            }
            for row in input_plan["items"]
        ]
        from .input_policy import for_definition

        workflow.plan["inputPreparationPolicy"] = {
            **for_definition(definition),
            "algorithmVersionIds": sorted(source_run.algorithm_version_ids)
            if source_run and source_run.algorithm_selection_mode == "manual"
            else None,
        }
        if workflow.workflow_type == "business_flow":
            workflow.plan["businessFlow"] = initial_state(definition)
        else:
            workflow.parameters["_businessFlow"]["state"] = initial_state(definition)
        workflow.save(
            update_fields=["parameters", "plan", "max_iterations", "updated_at"]
        )
        emit(workflow, "system", "", "started", "业务流已启动，将按发布版本逐节点处理")
        # An ordinary tool caller hands ownership to the workflow queue after returning.
        if source_run:
            AgentRun.objects.filter(pk=run.pk).update(status="running")
        return workflow


def decide_flow(user, workflow, value):
    if value.get("decision") in {"retry_recovery", "skip_node"}:
        from .node_recovery import decide_recovery

        return decide_recovery(user, workflow, value)
    authorize(user, workflow)
    if workflow.workflow_type != "business_flow":
        if value.get("decision") == "retry_context":
            from .legacy import retry_context

            return retry_context(user, workflow, value)
        raise ComputeError("专业流程的重要决定请在原审核卡中确认", 409)
    node_id, decision = value.get("nodeId"), value.get("decision")
    if any(key in value for key in ("recoveryInputs", "recoveryParameters")):
        raise ValidationError("恢复资料与参数只能用于retry_recovery决定")
    feedback = value.get("feedback", "")
    key = value.get("idempotencyKey")
    if (
        decision not in {"approve", "request_changes", "retry_context"}
        or not isinstance(feedback, str)
        or len(feedback) > 4000
        or not isinstance(key, str)
        or not 8 <= len(key) <= 80
    ):
        raise ValidationError("人工决定、反馈或幂等键无效")
    if decision != "retry_context" and any(
        key in value for key in ("skipEvidenceIds", "contextScope")
    ):
        raise ValidationError("证据范围只允许用于上下文重试，不能改变科研人工批准")
    with transaction.atomic():
        current = locked_workflow(workflow.pk)
        authorize(user, current)
        value_state = state(current)
        receipts = value_state.setdefault("decisions", {})
        fingerprint = digest(
            {
                k: value.get(k)
                for k in (
                    "nodeId",
                    "decision",
                    "feedback",
                    "revision",
                    "skipEvidenceIds",
                    "contextScope",
                )
            }
        )
        if key in receipts:
            if receipts[key] != fingerprint:
                raise ComputeError("决定幂等键冲突", 409)
            return current
        if (
            current.status != "waiting_approval"
            or str(value.get("revision")) != str(value_state["revision"])
            or node_id != current.current_step
        ):
            raise ComputeError("审核对象或版本已变化，请刷新后查看当前节点", 409)
        item = value_state["nodes"].get(node_id)
        if item and item.get("contextRecovery"):
            if decision != "retry_context":
                raise ComputeError(
                    "上下文等待不能批准科研节点，请选择缩小范围、跳过非必需证据后重试，或停止任务",
                    409,
                )
            from .context_recovery import retry_node

            retry_node(current, item, value)
            require_compute_slot(user, current.pk)
            receipts[key] = fingerprint
            current.status, current.detail = (
                "queued",
                "上下文范围已更新，将重试当前节点；未批准科研结果",
            )
            current.policy_snapshot["businessFlowControlEpoch"] = (
                current.policy_snapshot.get("businessFlowControlEpoch", 0) + 1
            )
            current.save(
                update_fields=[
                    "plan",
                    "parameters",
                    "status",
                    "detail",
                    "policy_snapshot",
                    "updated_at",
                ]
            )
            emit(current, "human", node_id, "context_retry", current.detail)
            return current
        if decision == "retry_context":
            raise ComputeError("该节点没有等待处理的上下文", 409)
        if (
            not item
            or not item["human"]["required"]
            or item["human"]["status"] != "pending"
        ):
            raise ComputeError("该节点没有待处理的人工决定", 409)
        node = next(
            n
            for n in binding(current)["definitionSnapshot"]["nodes"]
            if n["id"] == node_id
        )
        if decision == "request_changes":
            if not feedback.strip():
                raise ValidationError("退回时请说明需要修改的内容")
            if item["attempt"] >= node["review"]["maxRevisions"] + 1:
                raise ComputeError(
                    "本节点已达到返修上限，请保留当前结果并重新发起调整后的流程", 409
                )
            item.update(
                status="pending",
                feedback={"reason": feedback[:2000], "repairInstructions": feedback},
                executor={"status": "pending"},
                reviewer={
                    "status": "pending" if node["review"]["ai"] else "not_required"
                },
            )
            item["human"].update(status="pending", reason=feedback)
            item["revisionEvidence"] = deepcopy(
                item.get("outputs", {}).get("evidence", [])
            )
            if item.get("toolLoop") is not None:
                item["toolLoop"]["invalidOutputIds"] = list(
                    dict.fromkeys(
                        [
                            *item["toolLoop"].get("invalidOutputIds", []),
                            *[row["id"] for row in item["revisionEvidence"]],
                        ]
                    )
                )
            item["outputs"] = {}
            item.pop("computeTaskId", None)
        else:
            item["human"].update(
                status="approved",
                reason=feedback,
                userId=user.pk,
                approvedOutputDigest=digest(item["executor"]),
            )
            item["status"] = "succeeded"
            from .ledger import complete_node

            complete_node(current, node)
        require_compute_slot(user, current.pk)
        receipts[key] = fingerprint
        current.status, current.detail = "queued", "人工决定已保存，继续业务流"
        current.policy_snapshot["businessFlowControlEpoch"] = (
            current.policy_snapshot.get("businessFlowControlEpoch", 0) + 1
        )
        current.save(
            update_fields=[
                "plan",
                "parameters",
                "status",
                "detail",
                "policy_snapshot",
                "updated_at",
            ]
        )
        emit(
            current, "human", node_id, decision, feedback or "已确认当前节点的实际结果"
        )
        return current


def control_flow(user, workflow, action):
    if action == "cancel":
        if (
            workflow.owner_id != user.pk
            or workflow.project_tag_id != selected_project_id()
        ):
            raise PermissionDenied("只能停止当前项目中自己的业务流")
        binding(workflow)
    else:
        authorize(user, workflow, history=workflow.status in TERMINAL)
    if action not in {"pause", "resume", "cancel"}:
        raise ValidationError("未知业务流操作")
    if workflow.workflow_type != "business_flow":
        from .legacy import legacy_control

        return legacy_control(user, workflow, action)
    with transaction.atomic():
        current = locked_workflow(workflow.pk)
        if (
            current.status in TERMINAL
            or action == "pause"
            and current.status == "paused"
        ):
            return current
        if action == "cancel":
            current.cancel_requested = True
            current.pause_requested = False
            current.status, current.detail = (
                "cancelled",
                "已停止业务流，后续审核和计算不再启动",
            )
        elif action == "pause":
            current.paused_from = current.status
            current.pause_requested = True
            current.status, current.detail = "paused", "业务流已暂停，保留当前节点结果"
        else:
            if current.status != "paused":
                raise ComputeError("只有已暂停业务流可以恢复", 409)
            require_compute_slot(user, current.pk)
            current.status = (
                "waiting_approval"
                if current.paused_from == "waiting_approval"
                else "queued"
            )
            current.pause_requested = False
            current.paused_from = ""
            current.detail = "业务流已恢复"
        from .state import interrupt_actor_audits

        interrupt_actor_audits(current, action)
        current.policy_snapshot["businessFlowControlEpoch"] = (
            current.policy_snapshot.get("businessFlowControlEpoch", 0) + 1
        )
        current.save(
            update_fields=[
                "status",
                "detail",
                "cancel_requested",
                "pause_requested",
                "paused_from",
                "policy_snapshot",
                "plan",
                "parameters",
                "updated_at",
            ]
        )
        emit(current, "human", current.current_step, action, current.detail)
    if action == "cancel":
        from .engine import cancel_tasks

        cancel_tasks(user, current)
    return current
