"""Small durable scenario graphs over existing compute, imports and checkpoints."""

from __future__ import annotations

import time
from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.compute.models import AlgorithmVersion, ComputeImport
from apps.catalog.nongeo import NonGeoAnalysisError
from apps.compute.quality import require_automatic_quality
from apps.compute.services import (
    ACTIVE,
    allowed_algorithms,
    agent_algorithm_allowed,
    submit,
    request_output_import,
    task_action,
    validate_submission,
)
from apps.compute.access import require_actor
from apps.compute.packages import ComputeError
from apps.knowledge.domains import DOMAINS, validate_domains
from apps.knowledge.services import search_entries, visible_entries
from apps.projects.context import project_scope
from .models import AgentWorkflow
from .geology_reference import is_reference_resource
from .provider import ModelError
from .tools import resolve_resource
from .compute_tools import authorized_task
from .demo_decisions import decide
from .demo_results import create_changes, read_results
from .workflow import _authorize, _scope, _state_hash, checkpoint, step
from .workflow_controls import (
    WorkflowPaused,
    check_pause,
    locked_workflow,
    save_workflow_state,
)

DEMO_TYPES = {
    "ecology_investigation",
    "geology_correction",
    "geology_age_correction",
    "geology_map_review",
}
STAGE_TITLES = {
    "early_ndvi": "前期植被指数",
    "late_ndvi": "后期植被指数",
    "change": "植被变化检测",
    "priority": "调查顺序分析",
    "initial_check": "初始填图检查",
    "geometry": "几何修复",
    "check": "修复后检查",
    "edit": "调查证据属性编辑",
    "recheck": "最终填图复查",
}
ROLES = {
    "geology_map_review": {
        "initial_map": "vector",
        "coverage": "vector",
        "rules": "table",
    },
    "ecology_investigation": {
        "early_image": "raster",
        "late_image": "raster",
        "valid_mask": "raster",
        "zones": "vector",
        "context": "table",
    },
    "geology_correction": {
        "initial_map": "vector",
        "surveys": "table",
        "rules": "table",
    },
    "geology_age_correction": {
        "initial_map": "vector",
        "surveys": "table",
        "rules": "table",
    },
}
GRAPHS = {
    "geology_map_review": [
        (
            "check",
            "geology-map-check",
            {"features": "initial_map", "coverage": "coverage", "rules": "rules"},
        ),
        (
            "edit",
            "geology-map-correct",
            {
                "features": "initial_map",
                "coverage": "coverage",
                "rules": "rules",
                "changes": "model_changes",
            },
        ),
        (
            "recheck",
            "geology-map-check",
            {"features": "edit/corrected", "coverage": "coverage", "rules": "rules"},
        ),
    ],
    "geology_age_correction": [
        (
            "check",
            "geology-age-check",
            {"features": "initial_map", "surveys": "surveys", "rules": "rules"},
        ),
        (
            "edit",
            "geology-age-edit",
            {
                "features": "initial_map",
                "changes": "model_changes",
                "surveys": "surveys",
                "rules": "rules",
            },
        ),
        (
            "recheck",
            "geology-age-check",
            {"features": "edit/corrected", "surveys": "surveys", "rules": "rules"},
        ),
    ],
    "ecology_investigation": [
        ("early_ndvi", "raster-ndvi", {"image": "early_image"}),
        ("late_ndvi", "raster-ndvi", {"image": "late_image"}),
        (
            "change",
            "ndvi-change",
            {
                "early_ndvi": "early_ndvi/ndvi",
                "late_ndvi": "late_ndvi/ndvi",
                "valid_mask": "valid_mask",
            },
        ),
        (
            "priority",
            "ecology-priority",
            {
                "change": "change/change",
                "zones": "zones",
                "context": "context",
            },
        ),
    ],
    "geology_correction": [
        (
            "initial_check",
            "geology-check",
            {"features": "initial_map", "surveys": "surveys", "rules": "rules"},
        ),
        ("geometry", "vector-geometry-repair", {"features": "initial_map"}),
        (
            "check",
            "geology-check",
            {
                "features": "geometry/repaired",
                "surveys": "surveys",
                "rules": "rules",
            },
        ),
        (
            "edit",
            "geology-edit",
            {
                "features": "geometry/repaired",
                "changes": "model_changes",
                "surveys": "surveys",
                "rules": "rules",
            },
        ),
        (
            "recheck",
            "geology-check",
            {
                "features": "edit/corrected",
                "surveys": "surveys",
                "rules": "rules",
            },
        ),
    ],
}


def stage_title(workflow, stage: dict) -> str:
    if workflow.workflow_type == "geology_map_review":
        return {
            "expert_knowledge": "查阅专家知识",
            "check": "检查地图",
            "edit": "修正地图",
            "recheck": "复核地图",
        }.get(stage["name"], "检查报告")
    if workflow.workflow_type == "geology_age_correction":
        return {
            "check": "初始时代属性检查",
            "edit": "地层时代属性纠偏",
            "recheck": "最终时代属性复查",
        }.get(stage["name"], stage["name"])
    return STAGE_TITLES.get(stage["name"], stage["name"])


def _save(workflow, *, acknowledge_pause=False) -> None:
    workflow.plan_hash = _state_hash(workflow.plan)
    save_workflow_state(workflow, acknowledge_pause=acknowledge_pause)


def _domains(workflow) -> list[str]:
    selection = workflow.plan.get("knowledgeSelection", {"mode": "auto", "domains": []})
    mode = selection.get("mode", "auto")
    if mode not in {"auto", "manual", "all", "none"}:
        raise ValidationError("知识调用方式无效")
    domains = validate_domains(selection.get("domains", []))
    if mode == "manual" and not domains:
        raise ValidationError("请选择需要参考的知识分区")
    if mode == "none":
        return []
    if mode == "manual":
        return domains
    if mode == "all":
        return list(DOMAINS)
    return (
        ["remote_sensing", "arid_ecology"]
        if workflow.workflow_type == "ecology_investigation"
        else ["geology"]
    )


def _versions(workflow, graph) -> dict:
    identifiers = {identifier for _, identifier, _ in graph}
    versions = {}
    for identifier in identifiers:
        chat = workflow.plan.get("chatExecution", {})
        permitted_versions = chat.get("algorithmVersionIds")
        options = (
            AlgorithmVersion.objects.select_related("algorithm")
            .filter(
                algorithm__in=allowed_algorithms(),
                algorithm__identifier=identifier,
                algorithm__enabled=True,
                status="published",
            )
            .order_by("-created_at", "-id")
        )
        if permitted_versions is not None:
            options = options.filter(pk__in=permitted_versions)
        version = next((v for v in options if agent_algorithm_allowed(v)), None)
        if version is None:
            raise ComputeError("场景所需算法尚未发布或不可调用：" + identifier)
        snapshot = chat.get("algorithmSnapshots", {}).get(identifier)
        if snapshot is not None and snapshot != {
            "versionId": version.id,
            "checksum": version.checksum,
        }:
            raise PermissionDenied("科研算法在聊天解析后已变化，请重新匹配")
        versions[identifier] = {
            "versionId": version.id,
            "checksum": version.checksum,
            "name": version.algorithm.name,
            "manifest": version.manifest,
        }
    return versions


def prepare_demo(workflow, user, p) -> None:
    roles = ROLES[workflow.workflow_type]
    inputs = workflow.plan.get("inputs", {})
    if not isinstance(inputs, dict) or set(inputs) != set(roles):
        raise ComputeError("请按场景明确选择全部输入角色")
    if len(set(inputs.values())) > p["maxResources"]:
        raise ComputeError("场景输入超过当前资源上限")
    snapshots, names = {}, {}
    for role, kind in roles.items():
        resource = resolve_resource(user, p, inputs[role], workflow.resource_ids)
        if workflow.workflow_type in {
            "geology_age_correction",
            "geology_map_review",
        } and (
            is_reference_resource(resource)
            or (resource.source or "").startswith(
                ("geology-review-reference:", "geology-review-acceptance:")
            )
        ):
            raise ComputeError("此资料仅用于独立验收，请选择待检查地质图与适用资料")
        if resource.status != "active" or resource.data_type != kind:
            raise ComputeError("场景角色的数据类型或状态不匹配：" + role)
        snapshots[role], names[role] = resource.updated_at.isoformat(), resource.name
    if workflow.workflow_type == "ecology_investigation":
        if inputs["early_image"] == inputs["late_image"]:
            raise ComputeError("前期与后期影像须为两份不同资料")
        try:
            early, late = (
                date.fromisoformat(workflow.parameters[key])
                for key in ("early_date", "late_date")
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ComputeError("请提供前后两期的实际日期") from exc
        if early >= late:
            raise ComputeError("后期日期必须晚于前期日期")
    graph = GRAPHS[workflow.workflow_type]
    if workflow.plan.get("previousWorkflowId"):
        from .demo_updates import prepare_update

        graph = prepare_update(workflow, user, p)
    versions = _versions(workflow, graph)
    required_steps = len(graph)
    decisions_required = required_steps + (
        2 if workflow.workflow_type == "geology_map_review" else 1
    )
    if workflow.max_iterations < decisions_required:
        raise ComputeError("请将场景模型决策上限至少设为" + str(decisions_required))
    if workflow.max_operator_steps < required_steps:
        raise ComputeError("请将场景算子步骤上限至少设为" + str(required_steps))
    stages = []
    for name, identifier, bindings in graph:
        manifest = versions[identifier]["manifest"]
        if set(bindings) != {i["key"] for i in manifest["inputs"] if i["required"]}:
            raise ComputeError("场景算法输入清单与角色协议不一致：" + identifier)
        parameters = {
            spec["key"]: workflow.parameters.get(spec["key"], spec.get("default"))
            for spec in manifest["parameters"]
            if spec["key"] in workflow.parameters or "default" in spec
        }
        stages.append(
            {
                "name": name,
                "identifier": identifier,
                "bindings": bindings,
                "parameters": parameters,
                "status": "pending",
                "outputs": [],
            }
        )
    domains = _domains(workflow)
    if workflow.workflow_type == "geology_map_review":
        if not domains:
            raise ComputeError("此演示需要专家知识，请启用地质知识分区")
        stages.insert(
            0,
            {
                "name": "expert_knowledge",
                "identifier": "search_expert_knowledge",
                "bindings": {},
                "parameters": {},
                "status": "pending",
                "outputs": [],
            },
        )
    query = (
        (workflow.goal[:260] + " 地层 时代 辞书 一致性")
        if workflow.workflow_type == "geology_age_correction"
        else "NDVI 植被 物候 有效像元"
        if workflow.workflow_type == "ecology_investigation"
        else "地质 接触 几何 观测"
    )
    knowledge = (
        search_entries(user, query, limit=8, domains=domains)["items"]
        if domains and workflow.workflow_type != "geology_map_review"
        else []
    )
    workflow.plan = {
        **workflow.plan,
        "scenarioVersion": 1,
        "inputSnapshots": snapshots,
        "inputNames": names,
        "algorithms": versions,
        "stages": stages,
        "stageIndex": 0,
        "phase": "review_plan",
        "reviewOutputs": [],
    }
    workflow.resource_ids = sorted(set(inputs.values()))
    workflow.evidence = knowledge
    workflow.status, workflow.current_step = "waiting_approval", "review_plan"
    workflow.detail = "输入角色与算法已匹配，请确认场景计划后执行"
    # A failed automatic confirmation must leave the worker's running state
    # recoverable, rather than publishing a partially prepared waiting plan.
    with transaction.atomic():
        _save(workflow)
        step(workflow, "demo_plan", action=workflow.plan, message=workflow.detail)
        checkpoint(workflow, "review_plan", {"planHash": workflow.plan_hash})
        chat = workflow.plan.get("chatExecution")
        if chat and chat.get("initialPlanAuthorized") and workflow.status != "paused":
            from .models import AgentRun

            current = AgentWorkflow.objects.select_for_update().get(pk=workflow.id)
            source = AgentRun.objects.filter(
                pk=chat.get("requestRunId"),
                owner_id=workflow.owner_id,
                project_tag_id=workflow.project_tag_id,
                research_workflow_id=workflow.id,
            ).first()
            if (
                source is None
                or not source.research_intent.get("_executionAuthorized")
                or source.cancel_requested
                or source.conversation.archived
                or source.status not in {"running", "succeeded"}
                or source.research_intent.get("_initialExecutionAuthorization")
                != {
                    "revision": chat.get("revision"),
                    "originRunId": chat.get("originRunId"),
                    "requestRunId": chat.get("requestRunId"),
                }
                or source.research_intent.get("inputs") != current.plan["inputs"]
                or source.research_intent.get("_inputRevisions")
                != current.plan["inputSnapshots"]
                or current.plan.get("phase") != "review_plan"
            ):
                raise PermissionDenied("聊天执行授权已变化，请在当前任务中重新确认")
            confirm_demo(current, user, p, current.plan_hash)
            step(
                current,
                "chat_execution_authorized",
                action=chat,
                message="根据用户自然语言执行请求确认初始计划；结果质量审核仍由用户确认",
            )
            workflow.refresh_from_db()


def authorize_demo(workflow, user, p, *, include_previous=True) -> None:
    if not p.get("operatorEnabled", False):
        raise PermissionDenied("智能体算子调用已关闭")
    domains = _domains(workflow)
    for item in workflow.evidence:
        if (
            not visible_entries(user, domains=domains)
            .filter(pk=item["id"], revision=item["revision"])
            .exists()
        ):
            raise PermissionDenied("知识依据或分区权限已变化，请重新生成计划")
    for role, identity in workflow.plan["inputs"].items():
        resource = resolve_resource(user, p, identity, workflow.resource_ids)
        if (
            resource.status != "active"
            or resource.updated_at.isoformat() != workflow.plan["inputSnapshots"][role]
        ):
            raise PermissionDenied("原始输入已变化或停用，请重新核对")
    for identifier, fixed in workflow.plan["algorithms"].items():
        chat = workflow.plan.get("chatExecution", {})
        if chat and (
            fixed["versionId"] not in chat.get("algorithmVersionIds", [])
            or (
                chat.get("algorithmSelectionMode") == "manual"
                and fixed["versionId"]
                not in chat.get("selectedAlgorithmVersionIds", [])
            )
        ):
            raise PermissionDenied("科研算法已超出聊天中明确选择的范围")
        version = (
            AlgorithmVersion.objects.select_related("algorithm")
            .filter(
                pk=fixed["versionId"],
                algorithm__in=allowed_algorithms(),
                algorithm__enabled=True,
                status="published",
            )
            .first()
        )
        if (
            version is None
            or version.algorithm.identifier != identifier
            or version.checksum != fixed["checksum"]
            or not agent_algorithm_allowed(version)
        ):
            raise PermissionDenied("已冻结的算法版本已变化或停用")
    for stage in workflow.plan["stages"]:
        for output in stage.get("outputs", []):
            resource = resolve_resource(user, p, output["resourceId"])
            record = ComputeImport.objects.filter(
                output_id=output["outputId"],
                resource=resource,
                status="ready",
                output__checksum=output["checksum"],
                output__task_id=stage["taskId"],
            ).first()
            if (
                record is None
                or resource.status != "active"
                or resource.updated_at.isoformat() != output["resourceRevision"]
            ):
                raise PermissionDenied("下游输入不再对应已核验的实际输出")
    if workflow.import_results:
        require_actor(user, workflow.project_tag_id, "catalog.add_dataresource")
    if include_previous and workflow.plan.get("previousWorkflowId"):
        from .demo_updates import authorize_update

        authorize_update(workflow, user, p)


def confirm_demo(workflow, user, p, plan_hash, selected_suggestion_ids=None) -> None:
    if workflow.status != "waiting_approval" or workflow.cancel_requested:
        raise ComputeError("此场景当前不能确认执行", 409)
    if plan_hash != workflow.plan_hash or _state_hash(workflow.plan) != plan_hash:
        raise ComputeError("场景计划已变化，请刷新后确认", 409)
    authorize_demo(workflow, user, p)
    if workflow.plan["phase"] == "review_modifications":
        from .geology_review import approve_modifications

        if workflow.workflow_type != "geology_map_review":
            raise ComputeError("当前场景不支持此修改审核", 409)
        approve_modifications(workflow, user, p, selected_suggestion_ids, plan_hash)
        workflow.plan["phase"] = "decide"
        workflow.status = "queued"
    elif workflow.plan["phase"] == "review_results":
        stage = workflow.plan["stages"][workflow.plan["stageIndex"]]
        reviewing_output = bool(stage.get("taskId"))
        stage["manualApproved" if reviewing_output else "decisionApproved"] = True
        step(
            workflow,
            "human_review",
            action={"approvedOutputs": workflow.plan["reviewOutputs"]},
            message="用户已确认候选结果，保留原质量记录",
        )
        workflow.plan["reviewOutputs"] = []
        if reviewing_output:
            workflow.import_results = True
            workflow.plan["phase"] = "waiting_compute"
            workflow.status = "waiting_compute"
        else:
            stage["status"] = "pending"
            workflow.plan["phase"] = "decide"
            workflow.status = "queued"
    else:
        workflow.plan["phase"] = "decide"
        workflow.status = "queued"
    workflow.execute_operators = True
    workflow.detail = (
        "已批准选中的建议，等待修正地图"
        if workflow.workflow_type == "geology_map_review"
        and workflow.plan.get("modificationReview", {}).get("approvedSuggestionIds")
        else "已确认场景计划，等待继续处理"
    )
    _save(workflow)


def _inputs(workflow, stage) -> dict:
    values = {}
    for key, binding in stage["bindings"].items():
        if "/" not in binding:
            values[key] = workflow.plan["inputs"].get(binding) or workflow.plan.get(
                binding
            )
        else:
            origin, output_key = binding.split("/", 1)
            previous = next(
                item for item in workflow.plan["stages"] if item["name"] == origin
            )
            output = next(
                (item for item in previous["outputs"] if item["key"] == output_key),
                None,
            )
            values[key] = output.get("resourceId") if output else None
        if type(values[key]) is not int or values[key] < 1:
            raise ComputeError("上一步结果尚未成为可用输入：" + binding)
    return values


def _pause(workflow, stage, reason, outputs=None) -> None:
    workflow.plan.update(
        phase="review_results", reviewOutputs=outputs or [], reviewReason=reason
    )
    workflow.status, workflow.detail = "waiting_approval", reason[:300]
    stage["status"] = "needs_review"
    _save(workflow)
    checkpoint(workflow, "review_results", {"stage": stage["name"], "reason": reason})


def _submit_stage(workflow, user, p, stage) -> None:
    with transaction.atomic():
        current = locked_workflow(workflow.id)
        check_pause(workflow)
        if current.cancel_requested or current.status not in {"queued", "running"}:
            raise ModelError("场景已停止，未提交下一步计算")
        _submit_stage_locked(workflow, user, p, stage)


def _submit_stage_locked(workflow, user, p, stage) -> None:
    edits = stage.get("edits")
    if workflow.workflow_type == "geology_map_review" and stage["name"] == "edit":
        from .geology_review import approved_edits

        edits = approved_edits(workflow, user, p, stage)
    if stage["name"] == "edit" and (
        not workflow.plan.get("model_changes")
        or workflow.workflow_type == "geology_map_review"
    ):
        check = next(
            item for item in workflow.plan["stages"] if item["name"] == "check"
        )
        resource = create_changes(workflow, user, p, edits, check["results"])
        if workflow.workflow_type == "geology_map_review" and workflow.plan.get(
            "model_changes"
        ) not in {None, resource.id}:
            raise ComputeError("已批准的修改表绑定已变化，已停止编辑", 409)
        workflow.plan["model_changes"] = resource.id
    inputs = _inputs(workflow, stage)
    for identity in inputs.values():
        resolve_resource(user, p, identity)
    body = {
        "name": (
            f"地质成果智能检查与修正 · {stage_title(workflow, stage)}"
            if workflow.workflow_type == "geology_map_review"
            else f"{workflow.goal[:90]} · {stage_title(workflow, stage)}"
        ),
        "versionId": workflow.plan["algorithms"][stage["identifier"]]["versionId"],
        "inputs": inputs,
        "parameters": stage["parameters"],
        "idempotencyKey": f"demo-{workflow.id}-{stage['name']}",
        "trial": False,
    }
    validate_submission(user, body)
    with transaction.atomic():
        current = locked_workflow(workflow.id)
        check_pause(workflow)
        if current.cancel_requested or current.status not in {"queued", "running"}:
            raise ModelError("场景已停止，未提交下一步计算")
        AgentWorkflow.objects.filter(pk=workflow.id).update(heartbeat=timezone.now())
        task = submit(user, body)
        stage.update(taskId=str(task.id), inputs=inputs, status="waiting_compute")
        if not workflow.steps.filter(
            kind="submit_operator", compute_task_id=task.id
        ).exists():
            step(
                workflow,
                "submit_operator",
                compute_task_id=task.id,
                status="waiting",
                message="已按本步实际输入提交计算",
                input_refs=inputs,
                output_refs={"taskId": str(task.id), "inputRoles": stage["bindings"]},
            )
        workflow.operator_steps = workflow.steps.filter(kind="submit_operator").count()
        workflow.plan["phase"] = "waiting_compute"
        workflow.status, workflow.detail = (
            "waiting_compute",
            "平台正在跟踪实际计算与结果",
        )
        _save(workflow)


def _collection_cancelled(workflow) -> bool:
    """Call inside a transaction before imports or re-queuing the next stage."""
    current = locked_workflow(workflow.id)
    check_pause(workflow)
    if not current.cancel_requested and current.status != "cancelled":
        return False
    workflow.status, workflow.detail = "cancelled", "已停止场景后续处理"
    workflow.plan["phase"] = "cancelled"
    _save(workflow)
    return True


def _collect_stage(workflow, user, p, stage, task) -> bool:
    with transaction.atomic():
        if _collection_cancelled(workflow):
            return False
        workflow.steps.filter(kind="submit_operator", compute_task_id=task.id).update(
            status="succeeded",
            message="计算已完成",
            finished_at=task.finished_at or timezone.now(),
        )
    if "results" not in stage:
        stage["results"] = read_results(workflow, user, p, task)
        with transaction.atomic():
            step(
                workflow,
                "read_results",
                compute_task_id=task.id,
                message="已读取实际统计与质量报告",
                output_refs={"taskId": str(task.id), "results": stage["results"]},
            )
            _save(workflow)
    outputs = list(task.outputs.exclude(kind="archive").order_by("id"))
    if not stage.get("manualApproved"):
        try:
            for output in outputs:
                require_automatic_quality(output)
        except ComputeError as exc:
            _pause(
                workflow,
                stage,
                str(exc),
                [
                    {"outputId": o.id, "key": o.key, "label": o.label, "kind": o.kind}
                    for o in outputs
                ],
            )
            return False
    if not workflow.import_results:
        _pause(
            workflow,
            stage,
            "下一步需要保存已通过检查的结果，请确认后继续",
            [
                {"outputId": o.id, "key": o.key, "label": o.label, "kind": o.kind}
                for o in outputs
            ],
        )
        return False
    records = []
    for output in outputs:
        with transaction.atomic():
            if _collection_cancelled(workflow):
                return False
            record = ComputeImport.objects.filter(output=output).first()
            if record is None:
                source = (
                    "" if stage.get("manualApproved") else f"workflow:{workflow.id}"
                )
                name = f"{stage_title(workflow, stage)} · {output.label} · {workflow.created_at:%m%d-%H%M%S}"
                record = request_output_import(
                    user, output, name=name, request_source=source
                )
        if record.status == "failed":
            raise ComputeError(
                "结果入库失败，已保留任务与原结果：" + record.error[:200]
            )
        records.append((output, record))
    if any(record.status != "ready" or not record.resource_id for _, record in records):
        workflow.detail = "计算完成，正在等待实际结果入库"
        _save(workflow)
        return False
    stage["outputs"] = []
    for output, record in records:
        resource = resolve_resource(user, p, record.resource_id)
        stage["outputs"].append(
            {
                "outputId": output.id,
                "key": output.key,
                "label": output.label,
                "kind": output.kind,
                "resourceId": resource.id,
                "checksum": output.checksum,
                "resourceRevision": resource.updated_at.isoformat(),
            }
        )
    workflow.result_ids = sorted(set(workflow.result_ids + [o.id for o in outputs]))
    workflow.result_resource_ids = sorted(
        set(workflow.result_resource_ids + [r.resource_id for _, r in records])
    )
    stage["status"] = "completed"
    workflow.plan["stageIndex"] += 1
    workflow.plan["phase"] = "decide"
    workflow.status, workflow.detail = "queued", "已读取本步结果，下一步将据此更新判断"
    with transaction.atomic():
        if _collection_cancelled(workflow):
            return False
        step(
            workflow,
            "collect_results",
            compute_task_id=task.id,
            message="本步真实结果已入库，可作为下一步输入",
            output_refs={
                "taskId": str(task.id),
                "outputs": stage["outputs"],
                "inputRoles": stage["bindings"],
            },
        )
        _save(workflow)
    checkpoint(
        workflow,
        "stage_completed",
        {"stage": stage["name"], "outputs": stage["outputs"]},
    )
    return True


def advance_demo(workflow_id) -> None:
    workflow = AgentWorkflow.objects.get(pk=workflow_id)
    if workflow.status not in {"queued", "running", "waiting_compute", "interrupted"}:
        return
    with project_scope(_scope(workflow)):
        try:
            check_pause(workflow)
            user, p = _authorize(workflow)
            if workflow.cancel_requested:
                for submitted in workflow.steps.filter(kind="submit_operator"):
                    task = authorized_task(user, submitted.compute_task_id, p)
                    if task.status in {"queued", "validating", "running"}:
                        task_action(task, user, "cancel")
                workflow.status, workflow.detail = "cancelled", "已停止场景后续处理"
                _save(workflow)
                return
            if not workflow.execute_operators:
                prepare_demo(workflow, user, p)
                return
            authorize_demo(workflow, user, p)
            index = workflow.plan["stageIndex"]
            stages = workflow.plan["stages"]
            stage = (
                stages[index]
                if index < len(stages)
                else workflow.plan.setdefault(
                    "finalStage", {"name": "final_analysis", "identifier": "finish"}
                )
            )
            workflow.current_step = stage["name"]
            if stage.get("taskId"):
                task = authorized_task(user, stage["taskId"], p)
                if task.status in ACTIVE:
                    workflow.detail = "计算中心：" + task.stage
                    workflow.heartbeat = timezone.now()
                    workflow.save(update_fields=["detail", "heartbeat", "updated_at"])
                    return
                if task.status != "succeeded":
                    raise ComputeError("本步计算未成功：" + task.error[:200])
                _collect_stage(workflow, user, p, stage, task)
                return
            if (
                workflow.operator_steps >= workflow.max_operator_steps
                and stage["identifier"] != "finish"
            ):
                raise ComputeError("已达到场景算子步骤上限")
            if not stage.get("decision"):
                recovering_response = bool(stage.get("modelAttempts"))
                if (
                    not recovering_response
                    and workflow.iteration >= workflow.max_iterations
                ):
                    raise ComputeError("已达到场景模型决策次数上限")
                deadline, heartbeat_at = time.monotonic() + p["maxRunSeconds"], [0.0]

                def guard():
                    check_pause(workflow)
                    current = AgentWorkflow.objects.get(pk=workflow.id)
                    if (
                        current.cancel_requested
                        or current.status not in {"queued", "running"}
                        or time.monotonic() > deadline
                    ):
                        raise ModelError("场景分析已停止或达到本步时限")
                    fresh, policy = _authorize(current)
                    authorize_demo(current, fresh, policy)
                    if time.monotonic() - heartbeat_at[0] > 2:
                        AgentWorkflow.objects.filter(pk=current.id).update(
                            heartbeat=timezone.now()
                        )
                        heartbeat_at[0] = time.monotonic()

                # Reserve the decision count before contacting the configured model.
                if not recovering_response:
                    workflow.iteration += 1
                workflow.status = "running"
                _save(workflow)
                results = []
                if workflow.plan.get("previousWorkflowId"):
                    from .demo_updates import previous_results

                    results = previous_results(workflow, user, p)
                for previous in stages[:index]:
                    if not previous.get("taskId"):
                        continue
                    task = authorized_task(user, previous["taskId"], p)
                    results.extend(read_results(workflow, user, p, task))

                def record_attempt(attempt):
                    # Persist rejection before another network request; the final
                    # stage already belongs to plan.finalStage when not in stages.
                    blocked = False
                    with transaction.atomic():
                        if attempt["status"] == "requesting":
                            calls = workflow.plan.get("actualModelCallCount", 0)
                            if calls >= workflow.max_iterations:
                                blocked = True
                                attempt.update(
                                    status="budget_blocked",
                                    accepted=False,
                                    validationError="已达到场景真实模型请求次数上限",
                                )
                            else:
                                workflow.plan["actualModelCallCount"] = calls + 1
                                attempt["requested"] = True
                        _save(workflow)
                        if attempt["status"] != "requesting":
                            step(
                                workflow,
                                "analysis_model_attempt",
                                status="succeeded" if attempt["accepted"] else "failed",
                                message=attempt.get(
                                    "validationError", "模型响应通过实际证据校验"
                                ),
                                action={
                                    "stage": stage["name"],
                                    "attempt": attempt["attempt"],
                                    "accepted": attempt["accepted"],
                                    "requestSha256": attempt["requestSha256"],
                                },
                                metrics={
                                    "inputTokens": attempt["inputTokens"],
                                    "contentBytes": attempt["contentBytes"],
                                    "usage": attempt["usage"],
                                },
                            )
                    if blocked:
                        raise ComputeError("已达到场景真实模型请求次数上限")

                decision, edits = decide(
                    workflow,
                    user,
                    p,
                    stage,
                    results,
                    guard,
                    record_attempt,
                    on_response=lambda: _save(workflow),
                )
                guard()
                stage.update(decision=decision, edits=edits)
                with transaction.atomic():
                    step(
                        workflow,
                        "analysis_decision",
                        action={"decision": decision},
                        message=decision["judgement"],
                        input_refs=workflow.plan["inputs"],
                        output_refs={"inputRoles": stage.get("bindings", {})},
                    )
                    _save(workflow)
            if stage["decision"]["nextAction"] == "request_review" and not stage.get(
                "decisionApproved"
            ):
                if index >= len(stages):
                    workflow.plan["stages"].append(stage)
                _pause(workflow, stage, stage["decision"]["judgement"])
                return
            if stage["identifier"] == "search_expert_knowledge":
                query = stage["decision"].get("knowledgeQuery")
                if not isinstance(query, str) or not query.strip():
                    raise ComputeError("尚未形成实际知识检索词，请重新发起检查")
                knowledge = search_entries(
                    user, query, limit=8, domains=_domains(workflow)
                )["items"]
                with transaction.atomic():
                    current = locked_workflow(workflow.id)
                    check_pause(workflow)
                    if current.cancel_requested or current.status not in {
                        "queued",
                        "running",
                    }:
                        raise ModelError("检查已停止，已保留知识查询记录")
                    fresh, policy = _authorize(current)
                    authorize_demo(current, fresh, policy)
                    stage["status"] = "completed"
                    workflow.evidence = knowledge
                    workflow.plan["knowledgeSearch"] = {
                        "query": query,
                        "domains": _domains(workflow),
                        "knowledge": [
                            {
                                "id": item["id"],
                                "revision": item["revision"],
                                "title": item["title"],
                            }
                            for item in knowledge
                        ],
                    }
                    workflow.plan["stageIndex"] += 1
                    workflow.status, workflow.detail = (
                        "queued",
                        "已查阅相关专家知识，继续检查地图",
                    )
                    step(
                        workflow,
                        "search_expert_knowledge",
                        message=workflow.detail,
                        action={"query": query, "model": workflow.model},
                        output_refs={"knowledge": knowledge},
                    )
                    _save(workflow)
                    checkpoint(
                        workflow,
                        "expert_knowledge_retrieved",
                        workflow.plan["knowledgeSearch"],
                    )
                return
            if (
                workflow.workflow_type == "geology_map_review"
                and stage["name"] == "edit"
                and not stage.get("modificationsApproval")
            ):
                from .geology_review import freeze_proposal

                with transaction.atomic():
                    current = locked_workflow(workflow.id)
                    check_pause(workflow)
                    if current.cancel_requested or current.status not in {"queued", "running"}:
                        raise ModelError("检查已停止，未生成新的修改建议")
                    fresh, policy = _authorize(current)
                    authorize_demo(current, fresh, policy)
                    freeze_proposal(workflow, stage)
                    step(
                        workflow,
                        "modification_suggestions",
                        message=workflow.detail,
                        output_refs={
                            "modificationReview": workflow.plan["modificationReview"]
                        },
                    )
                    _save(workflow)
                    checkpoint(
                        workflow,
                        "review_modifications",
                        {
                            "planHash": workflow.plan_hash,
                            "proposalHash": workflow.plan["modificationReview"][
                                "proposalHash"
                            ],
                        },
                    )
                return
            if stage["identifier"] == "finish":
                stage["status"] = "completed"
                workflow.plan["phase"] = "completed"
                workflow.plan["finalDecision"] = stage["decision"]
                workflow.status, workflow.current_step = "succeeded", "finalize"
                workflow.detail = (
                    stage["decision"]["resultSummary"] or stage["decision"]["judgement"]
                )
                workflow.detail = workflow.detail[:300]
                _save(workflow)
                checkpoint(
                    workflow, "finalize", {"resourceIds": workflow.result_resource_ids}
                )
                return
            _submit_stage(workflow, user, p, stage)
        except WorkflowPaused:
            _save(workflow, acknowledge_pause=True)
            return
        except PermissionDenied as exc:
            workflow.status, workflow.detail = "interrupted", str(exc)[:300]
            _save(workflow, acknowledge_pause=True)
        except (ComputeError, ValidationError, ModelError, NonGeoAnalysisError) as exc:
            cancelled = AgentWorkflow.objects.filter(
                pk=workflow.id, cancel_requested=True
            ).exists()
            workflow.status = "cancelled" if cancelled else "failed"
            workflow.detail = "已停止场景后续处理" if cancelled else str(exc)[:300]
            _save(workflow, acknowledge_pause=True)
