"""Execute declared nodes, independently review, then honor human gates."""

from copy import deepcopy
import json
import time

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.agent.models import AgentWorkflow, AgentWorkflowStep
from apps.agent.policy import fresh_user
from apps.agent.provider import ModelError
from apps.agent.workflow import _scope
from apps.agent.workflow_controls import WorkflowPaused, check_pause, locked_workflow
from apps.compute.packages import ComputeError
from apps.projects.context import project_scope
from .state import binding, emit, parent_run, persist, state
from .runtime import authorize
from .state import WorkflowControlChanged

# Configuration: no token-by-token full state writes or scientific file rereads.
PROGRESS_SECONDS = 0.6
MAX_EVIDENCE_BYTES = 96 * 1024
MAX_MODEL_CALLS = 256


def cancel_tasks(user, workflow):
    from apps.compute.services import task_action

    for identity in (
        workflow.steps.exclude(compute_task_id=None)
        .values_list("compute_task_id", flat=True)
        .distinct()
    ):
        from apps.compute.models import ComputeTask
        from apps.compute.access import task_access

        task = ComputeTask.objects.get(
            pk=identity, owner=user, project_tag_id=workflow.project_tag_id
        )
        task_access(task, user)
        if task.status in {"queued", "validating", "running"}:
            task_action(task, user, "cancel")


def live_guard(workflow):
    touched = [0.0]
    frozen = deepcopy(binding(workflow))
    epoch = workflow.policy_snapshot.get("businessFlowControlEpoch", 0)

    def guard():
        current = AgentWorkflow.objects.only(
            "id",
            "owner_id",
            "project_tag_id",
            "status",
            "cancel_requested",
            "pause_requested",
            "policy_snapshot",
        ).get(pk=workflow.pk)
        if current.policy_snapshot.get("businessFlowControlEpoch", 0) != epoch:
            raise WorkflowControlChanged("业务流有更新的用户控制决定")
        if current.cancel_requested or current.status == "cancelled":
            raise ModelError("业务流已停止")
        check_pause(current)
        if current.status not in {"queued", "running", "waiting_compute"}:
            raise ModelError("业务流状态已变化，当前模型请求已停止")
        from apps.agent.policy import require_access
        from .models import BusinessFlowDefinition

        user = fresh_user(current.owner_id)
        policy = require_access(user, "agent", workflow.model)
        if (
            not policy.get("workflowEnabled", True)
            or not BusinessFlowDefinition._base_manager.filter(
                pk=frozen["flowId"],
                project_tag_id=current.project_tag_id,
                is_active=True,
            ).exists()
        ):
            raise PermissionDenied("业务流已停用或执行权限已收窄")
        from .runtime import authorize_inputs

        authorize_inputs(user, policy, frozen.get("inputVersions", {}))
        if time.monotonic() - touched[0] >= 2:
            AgentWorkflow.objects.filter(pk=current.pk).update(heartbeat=timezone.now())
            touched[0] = time.monotonic()

    return guard


def stash_evidence(workflow, rows):
    store = state(workflow).setdefault("evidenceStore", {})
    for row in rows:
        store[row["id"]] = deepcopy(row)
    return [{key: row[key] for key in ("id", "kind", "title")} for row in rows]


def resolve_evidence(workflow, rows):
    store = state(workflow).setdefault("evidenceStore", {})
    return [deepcopy(store.get(row["id"], row)) for row in rows]


def input_evidence(workflow, user, policy, node):
    from apps.catalog.data_query import get_resource_profile

    values = state(workflow)
    cached = values.setdefault("inputEvidence", {})
    specs = {
        item["key"]: item
        for item in binding(workflow)["definitionSnapshot"]["inputRequirements"]
    }
    result = []
    declared_roles = list(
        dict.fromkeys(
            [
                *node["dataRoles"],
                *[
                    item["role"]
                    for item in node.get("inputBindings", {}).values()
                    if "role" in item
                ],
            ]
        )
    )
    from .input_adapters import logical_role

    roles = [
        key
        for key in workflow.plan["inputs"]
        if logical_role(key, specs) in declared_roles
    ]
    schemas = values.setdefault("inputSchemas", {})
    for role in roles:
        identity = workflow.plan["inputs"].get(role)
        if identity is None:
            continue
        from apps.agent.workflow_resources import resolve_workflow_resource

        resource = resolve_workflow_resource(user, policy, identity, workflow)
        cache_key = f"{identity}:{resource.updated_at.isoformat()}"
        if cache_key not in cached:
            metadata = {
                "id": identity,
                "name": resource.name,
                "dataType": resource.data_type,
                "fileFormat": resource.file_format,
                "description": resource.description[:2000],
                "itemCount": resource.item_count,
                "coordinateSystem": resource.coordinate_system,
                "updatedAt": resource.updated_at.isoformat(),
                "contentScope": "metadata",
                "contentRead": False,
            }
            if resource.data_type in {"vector", "raster", "table", "gene"}:
                profile = get_resource_profile(resource)
                fields = profile.fields
                metadata.update(
                    fields=fields[:80],
                    featureCount=profile.feature_count,
                    geometryType=profile.geometry_type,
                    bounds=profile.bounds,
                    fieldListComplete=len(fields) <= 80,
                )
                if resource.data_type == "table":
                    if resource.file_format.upper() == "SQLITE":
                        from apps.catalog.nongeo import _sqlite_dataframe

                        sample, total, descriptions = _sqlite_dataframe(
                            resource,
                            limit=10,
                            offset=0,
                            sort_field=None,
                            sort_direction="asc",
                        )
                        metadata.update(
                            fields=[
                                {
                                    "name": str(name),
                                    "type": str(sample[name].dtype),
                                    "description": descriptions.get(str(name), ""),
                                }
                                for name in sample.columns
                            ],
                            sample=sample.astype(object)
                            .where(sample.notna(), None)
                            .to_dict(orient="records"),
                            totalRows=total,
                            contentScope="first_10_rows",
                        )
                        fields = metadata["fields"]
                    elif resource.file_format.upper() == "CSV":
                        from apps.catalog.nongeo import _resource_file_path
                        from apps.compute.result_reads import table_page

                        with table_page(_resource_file_path(resource), 0, 10) as page:
                            metadata.update(
                                fields=[
                                    {"name": name, "type": "text"}
                                    for name in page["columns"]
                                ],
                                sample=list(page["rows"]),
                                totalRows=page["total"],
                                contentScope="first_10_rows",
                            )
                            fields = metadata["fields"]
                if "sample" in metadata:
                    metadata["contentRead"] = True
                metadata.setdefault("contentScope", "metadata")
                schemas[cache_key] = [field["name"] for field in fields]
            if resource.data_type == "document" and resource.file_format.upper() in {
                "TXT",
                "MD",
            }:
                from apps.agent.tools import execute

                document, _ = execute(
                    parent_run(workflow), "read_document", {"resourceId": identity}
                )
                metadata.update(
                    text=document.get("text", ""),
                    contentScope="first_6000_characters",
                    contentRead=True,
                    truncated=document.get("truncated", False),
                )
            from apps.agent.tools import clean

            metadata = clean(metadata)
            cached[cache_key] = {
                "id": f"resource-{identity}",
                "kind": "resource",
                "title": resource.name,
                "result": metadata,
            }
        if set(specs[logical_role(role, specs)].get("requiredFields", [])) - set(
            schemas.get(cache_key, [])
        ):
            raise ComputeError(
                specs[logical_role(role, specs)]["label"]
                + "缺少业务流要求的字段，不能因复用资料跳过角色规范"
            )
        result.append(deepcopy(cached[cache_key]))
    for dependency in node["dependsOn"]:
        previous = values["nodes"][dependency]
        result.extend(
            resolve_evidence(workflow, previous.get("outputs", {}).get("evidence", []))
        )
        if previous.get("executor", {}).get("summary"):
            result.append(
                {
                    "id": "node-" + dependency,
                    "kind": "analysis",
                    "title": dependency,
                    "result": {
                        key: previous["executor"].get(key)
                        for key in ("summary", "findings", "limitations", "evidenceIds")
                    },
                }
            )
    result = list({item["id"]: item for item in result}.values())
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_EVIDENCE_BYTES:
        raise ComputeError("节点实际证据超过上下文边界，请将流程拆分为更小节点")
    if not result:
        result = [
            {
                "id": "frozen-plan",
                "kind": "plan",
                "title": "已发布的流程与执行请求",
                "result": {
                    "definitionHash": binding(workflow)["definitionHash"],
                    "goal": workflow.goal,
                    "nodeId": node["id"],
                    "note": "本证据只描述计划，尚无数据分析或计算结果。",
                },
            }
        ]
    return result


def _callbacks(workflow, node, actor):
    entry = state(workflow)["nodes"][node["id"]]
    updated = [0.0]

    def record(value):
        calls = state(workflow).setdefault("requestedIds", [])
        request_id = value.get("requestId")
        if value.get("status") == "requesting" and request_id not in calls:
            limit = min(MAX_MODEL_CALLS, workflow.max_iterations)
            spent = (
                workflow.plan.get("actualModelCallCount", 0)
                if workflow.workflow_type != "business_flow"
                else 0
            )
            if len(calls) + spent >= limit:
                raise ComputeError("业务流已达到本次模型请求额度，已保留当前结果")
            calls.append(request_id)
        entry.setdefault("attempts", [])
        previous = next(
            (item for item in entry["attempts"] if item.get("requestId") == request_id),
            None,
        )
        if previous is None:
            entry["attempts"].append(deepcopy(value))
        else:
            previous.update(deepcopy(value))
        entry[actor].update(
            status=value.get("status", "running"),
            model=value.get("modelAlias", workflow.model),
            audit=deepcopy(value),
        )
        emit(
            workflow,
            actor,
            node["id"],
            value.get("status", "progress"),
            ("执行智能体正在处理" if actor == "executor" else "独立审核智能体正在核对")
            if value.get("status") == "requesting"
            else "本次模型请求状态已保存",
        )

    def progress(value):
        if time.monotonic() - updated[0] < PROGRESS_SECONDS:
            return
        updated[0] = time.monotonic()
        entry[actor]["progress"] = deepcopy(value)
        persist(workflow)

    def thinking(text):
        entry[actor]["thinking"] = (entry[actor].get("thinking", "") + text)[-24000:]
        if time.monotonic() - updated[0] >= PROGRESS_SECONDS:
            updated[0] = time.monotonic()
            persist(workflow)

    return {"on_record": record, "on_progress": progress, "on_thinking": thinking}


def _operator(workflow, user, policy, node, item, evidence):
    from apps.compute.models import AlgorithmVersion
    from apps.compute.services import (
        allowed_algorithms,
        agent_algorithm_allowed,
        submit,
    )
    from apps.agent.compute_tools import authorized_task
    from apps.agent.compute_result_tools import read_output

    if not policy.get("operatorEnabled", False):
        raise PermissionDenied("当前策略未允许业务流调用算子")
    task_id = item.get("computeTaskId")
    if not task_id:
        if workflow.operator_steps >= workflow.max_operator_steps:
            raise ComputeError("业务流已达到算子执行上限")
        version = AlgorithmVersion.objects.select_related("algorithm").get(
            pk=node["algorithmVersionId"],
            status="published",
            algorithm__in=allowed_algorithms().filter(enabled=True),
        )
        if not agent_algorithm_allowed(version):
            raise PermissionDenied("该版本未允许智能体调用")
        from apps.agent.demo_decisions import EDIT_CHECKS

        if version.algorithm.identifier in EDIT_CHECKS:
            raise PermissionDenied("此修改算子须使用原专业业务流逐项批准")
        available = {
            role: workflow.plan["inputs"][role]
            for role in node["dataRoles"]
            if role in workflow.plan["inputs"]
        }
        from .data_bindings import prepare_inputs

        inputs = prepare_inputs(workflow, user, policy, node, version, available)
        if inputs is None:
            return None
        parameters = {
            **node.get("parameters", {}),
            **workflow.parameters.get("nodeParameters", {}).get(node["id"], {}),
        }
        if item["attempt"] > 1 and item.get("feedback"):
            from apps.agent.business_flow_operator_repair import propose_parameters

            planned = propose_parameters(
                workflow,
                node,
                item["attempt"],
                list(
                    {
                        row["id"]: row
                        for row in [
                            *evidence,
                            *resolve_evidence(
                                workflow, item.get("revisionEvidence", [])
                            ),
                        ]
                    }.values()
                ),
                version.manifest,
                item.get("actualParameters", item.get("revisedParameters", parameters)),
                item["feedback"],
                guard=live_guard(workflow),
                policy=policy,
                **_callbacks(workflow, node, "executor"),
            )
            if not planned["canRepair"]:
                raise ComputeError(
                    "执行智能体无法在当前算子参数范围内完成返修：" + planned["reason"]
                )
            parameters = planned["parameters"]
            item["revisedParameters"] = parameters
        with transaction.atomic():
            current = locked_workflow(workflow.pk)
            if (
                current.cancel_requested
                or current.pause_requested
                or current.status not in {"queued", "running", "waiting_compute"}
                or current.policy_snapshot.get("businessFlowControlEpoch", 0)
                != workflow.policy_snapshot.get("businessFlowControlEpoch", 0)
            ):
                raise WorkflowControlChanged("新的控制决定已阻止提交算子")
            task = submit(
                user,
                {
                    "versionId": version.pk,
                    "name": binding(workflow)["name"] + " · " + node["title"],
                    "inputs": inputs,
                    "parameters": parameters,
                    "trial": False,
                    "idempotencyKey": f"business-{workflow.pk}-{node['id']}-{item['attempt']}",
                },
            )
            AgentWorkflowStep.objects.get_or_create(
                workflow=workflow,
                compute_task_id=task.id,
                defaults={
                    "sequence": workflow.steps.count() + 1,
                    "kind": "submit_operator",
                    "status": "waiting",
                    "message": node["title"],
                },
            )
            workflow.operator_steps += 1
            item["computeTaskId"] = str(task.id)
            item["actualParameters"] = deepcopy(task.parameters)
            workflow.status, workflow.detail = (
                "waiting_compute",
                "算子正在计算，完成后继续节点审核",
            )
            emit(
                workflow, "executor", node["id"], "operator_submitted", workflow.detail
            )
            return None
    task = authorized_task(user, task_id, policy, workflow=workflow)
    if task.status in {"queued", "validating", "running", "cancelling"}:
        return None
    if task.status != "succeeded":
        raise ComputeError("节点算子未完成：" + (task.error or task.status))
    actual = []
    for output in task.outputs.all():
        if output.kind == "archive":
            continue
        value, _ = read_output(
            parent_run(workflow),
            user,
            policy,
            {"outputId": output.pk, "limit": 20},
            workflow=workflow,
        )
        actual.append(
            {
                "id": f"output-{output.pk}",
                "kind": "output",
                "title": output.label or output.file_name,
                "result": value,
            }
        )
    if not actual:
        raise ComputeError("算子未提供可读取的真实结果")
    item["outputs"] = {
        "evidence": stash_evidence(workflow, actual),
        "taskId": str(task.id),
    }
    return {
        "summary": f"{node['title']}已完成，已读取{len(actual)}项实际结果。",
        "findings": [],
        "limitations": [],
        "evidenceIds": [row["id"] for row in actual],
        "status": "succeeded",
    }


def advance(workflow_id):
    workflow = AgentWorkflow.objects.get(pk=workflow_id)
    if workflow.status not in {"queued", "running", "waiting_compute"}:
        return
    with project_scope(_scope(workflow)):
        try:
            user = fresh_user(workflow.owner_id)
            policy = authorize(user, workflow)
            check_pause(workflow)
            if workflow.cancel_requested:
                workflow.status, workflow.detail = "cancelled", "已停止业务流"
                persist(workflow)
                return
            from .input_preparation import advance_inputs

            if not advance_inputs(workflow, user, policy):
                return
            definition = binding(workflow)["definitionSnapshot"]
            value = state(workflow)
            remaining = [
                node
                for node in definition["nodes"]
                if value["nodes"][node["id"]]["status"] != "succeeded"
            ]
            if not remaining:
                _finish(workflow, user, policy)
                return
            node = next(
                (
                    node
                    for node in remaining
                    if all(
                        value["nodes"][key]["status"] == "succeeded"
                        for key in node["dependsOn"]
                    )
                ),
                None,
            )
            if node is None:
                raise ComputeError("业务流没有可执行的依赖节点")
            item = value["nodes"][node["id"]]
            workflow.current_step, workflow.status = node["id"], "running"
            guard = live_guard(workflow)
            if item.get("reviewer", {}).get("decision") == "request_changes":
                if item["attempt"] > node["review"]["maxRevisions"]:
                    raise ComputeError("节点已达到独立审核返修上限")
                feedback = deepcopy(item["reviewer"])
                item["revisionEvidence"] = deepcopy(
                    item.get("outputs", {}).get("evidence", [])
                )
                item.update(
                    status="pending",
                    feedback=feedback,
                    executor={"status": "pending"},
                    reviewer={"status": "pending"},
                    outputs={},
                )
                item.pop("computeTaskId", None)
            if item["status"] == "pending":
                item["attempt"] += 1
                item.update(
                    status="executing",
                    executor={
                        "status": "running",
                        **(
                            {"model": workflow.model} if node["kind"] == "agent" else {}
                        ),
                    },
                    reviewer={
                        "status": "pending" if node["review"]["ai"] else "not_required"
                    },
                )
                workflow.detail = "执行智能体 · " + node["title"]
                emit(workflow, "executor", node["id"], "node_started", workflow.detail)
            evidence = input_evidence(workflow, user, policy, node)
            if not item["executor"].get("summary"):
                if node["kind"] == "operator":
                    result = _operator(workflow, user, policy, node, item, evidence)
                    if result is None:
                        return
                elif (
                    node["kind"] == "agent"
                    or item.get("feedback")
                    and node["kind"] in {"human", "result"}
                ):
                    from apps.agent.business_flow_execution import execute_node

                    executable = {
                        **node,
                        "instruction": node.get("instruction")
                        or node["description"]
                        or "依据实际上游结果与返修反馈，整理当前节点的说明和局限，不修改上游数据、流程或人工状态。",
                    }
                    result = execute_node(
                        workflow,
                        executable,
                        item["attempt"],
                        evidence,
                        guard=guard,
                        feedback=item.get("feedback"),
                        policy=policy,
                        **_callbacks(workflow, node, "executor"),
                    )
                else:
                    summaries = [
                        value["nodes"][key]["executor"].get("summary", "")
                        for key in node["dependsOn"]
                    ]
                    result = {
                        "summary": "\n\n".join(filter(None, summaries))
                        or node["description"],
                        "findings": [],
                        "limitations": [],
                        "evidenceIds": [row["id"] for row in evidence],
                        "status": "succeeded",
                    }
                guard()
                item["executor"].update(
                    result, status="succeeded", answer=result["summary"]
                )
                if not item["outputs"].get("evidence"):
                    item["outputs"] = {"evidence": stash_evidence(workflow, evidence)}
                item["status"] = "reviewing" if node["review"]["ai"] else "executed"
                emit(
                    workflow, "executor", node["id"], "node_executed", result["summary"]
                )
            if node["review"]["ai"] and item["reviewer"].get("decision") != "accept":
                from apps.agent.business_flow_review import review_node

                review_evidence = [
                    *resolve_evidence(workflow, item["outputs"]["evidence"]),
                    {
                        "id": "execution-result",
                        "kind": "analysis",
                        "title": node["title"] + "执行结果",
                        "result": {
                            key: item["executor"].get(key)
                            for key in (
                                "summary",
                                "findings",
                                "limitations",
                                "evidenceIds",
                            )
                        },
                    },
                ]
                workflow.detail = "独立审核智能体 · " + node["title"]
                item["status"] = "reviewing"
                emit(
                    workflow, "reviewer", node["id"], "review_started", workflow.detail
                )
                alias = (
                    node["review"].get("model") or binding(workflow)["reviewerModel"]
                )
                review = review_node(
                    workflow,
                    node,
                    item["attempt"],
                    review_evidence,
                    guard=guard,
                    model_alias=alias,
                    policy=policy,
                    **_callbacks(workflow, node, "reviewer"),
                )
                guard()
                item["reviewer"].update(
                    review,
                    status="passed" if review["decision"] == "accept" else "rejected",
                    model=alias,
                    feedback=review.get("repairInstructions", ""),
                )
                emit(
                    workflow,
                    "reviewer",
                    node["id"],
                    "review_accepted"
                    if review["decision"] == "accept"
                    else "review_rejected",
                    review["reason"],
                )
                if review["decision"] != "accept":
                    if item["attempt"] > node["review"]["maxRevisions"]:
                        raise ComputeError(
                            "节点审核未通过且已达到返修上限：" + review["reason"]
                        )
                    item["revisionEvidence"] = deepcopy(
                        item.get("outputs", {}).get("evidence", [])
                    )
                    item.update(
                        status="pending",
                        feedback=review,
                        executor={"status": "pending"},
                        reviewer={"status": "pending"},
                        outputs={},
                    )
                    item.pop("computeTaskId", None)
                    workflow.status, workflow.detail = (
                        "queued",
                        "执行智能体将按独立审核意见返修",
                    )
                    emit(
                        workflow,
                        "executor",
                        node["id"],
                        "revision_requested",
                        review["repairInstructions"],
                    )
                    return
            if item["human"]["required"] and item["human"]["status"] != "approved":
                item["status"] = "waiting_human"
                item["human"]["reason"] = (
                    node["description"]
                    or "此节点需要您作决定，独立审核不能代替人工批准。"
                )
                workflow.status, workflow.detail = (
                    "waiting_approval",
                    "等待您的决定 · " + node["title"],
                )
                emit(
                    workflow,
                    "human",
                    node["id"],
                    "human_required",
                    item["human"]["reason"],
                )
                return
            item["status"] = "succeeded"
            workflow.status, workflow.detail = (
                "queued",
                node["title"] + "已完成，继续下一节点",
            )
            emit(workflow, "system", node["id"], "node_completed", workflow.detail)
        except WorkflowControlChanged:
            return
        except WorkflowPaused:
            try:
                persist(workflow)
            except WorkflowControlChanged:
                return
        except Exception as error:
            current = AgentWorkflow.objects.only(
                "cancel_requested", "status", "policy_snapshot"
            ).get(pk=workflow.pk)
            if current.policy_snapshot.get(
                "businessFlowControlEpoch", 0
            ) != workflow.policy_snapshot.get("businessFlowControlEpoch", 0):
                return
            workflow.status = (
                "cancelled"
                if current.cancel_requested
                else "interrupted"
                if isinstance(error, PermissionDenied)
                else "failed"
            )
            workflow.detail = (
                str(error)[:300]
                if isinstance(
                    error, (ComputeError, ModelError, PermissionDenied, ValidationError)
                )
                else "业务流节点未能完成，已保留此前结果"
            )
            if workflow.current_step in state(workflow)["nodes"]:
                state(workflow)["nodes"][workflow.current_step]["status"] = "failed"
            emit(workflow, "system", workflow.current_step, "stopped", workflow.detail)


def _finish(workflow, user, policy):
    value = state(workflow)
    nodes = binding(workflow)["definitionSnapshot"]["nodes"]
    has_successors = {identity for node in nodes for identity in node["dependsOn"]}
    sinks = [node for node in nodes if node["id"] not in has_successors]
    answer = (
        "\n\n".join(
            value["nodes"][node["id"]]["executor"].get("summary", "") for node in sinks
        )
        or "业务流已完成"
    )
    value["answer"] = answer
    workflow.plan["finalDecision"] = {
        "judgement": answer,
        "resultSummary": answer,
        "findings": [],
        "uncertainties": [],
        "evidenceRefs": [],
    }
    from apps.agent.workflow_reports import generate_report, report_json

    with transaction.atomic():
        current = locked_workflow(workflow.pk)
        if (
            current.cancel_requested
            or current.pause_requested
            or current.policy_snapshot.get("businessFlowControlEpoch", 0)
            != workflow.policy_snapshot.get("businessFlowControlEpoch", 0)
        ):
            raise WorkflowControlChanged("新的用户控制决定阻止了终态发布")
        workflow.result_ids = sorted(
            {
                int(row["id"].removeprefix("output-"))
                for node in value["nodes"].values()
                for row in node.get("outputs", {}).get("evidence", [])
                if str(row.get("id", "")).startswith("output-")
                and str(row["id"])[7:].isdigit()
            }
        )
        workflow.result_ids = [
            identity
            for identity in workflow.result_ids
            if identity not in set(value.get("consumedOutputs", []))
        ]
        from apps.compute.models import ComputeImport

        workflow.result_resource_ids = list(
            ComputeImport.objects.filter(
                output_id__in=workflow.result_ids, status="ready"
            )
            .exclude(resource_id=None)
            .values_list("resource_id", flat=True)
        )
        workflow.status, workflow.detail = (
            "succeeded",
            "业务流已完成，节点审核和人工决定均已保存",
        )
        workflow.save(
            update_fields=[
                "status",
                "detail",
                "plan",
                "result_ids",
                "result_resource_ids",
                "updated_at",
            ]
        )
        data = generate_report(workflow, user, policy)
        value["report"] = report_json(workflow, user, data)
        emit(workflow, "system", "", "completed", workflow.detail)
