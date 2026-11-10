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
)
from apps.compute.access import require_actor
from apps.compute.packages import ComputeError, checksum_scope
from apps.knowledge.domains import DOMAINS, validate_domains
from apps.knowledge.services import search_entries, visible_entries
from apps.projects.context import project_scope
from .models import AgentWorkflow
from .model_guard import ModelStreamGuard
from .model_activity import WorkflowModelActivity
from .config import registry
from .geology_reference import is_reference_resource
from .provider import ModelError
from .workflow_resources import resolve_workflow_resource
from .resource_discovery import discovery_scope
from .compute_tools import authorized_task
from .demo_decisions import decide
from .demo_decision_batches import BatchProgressPending
from .demo_results import create_changes, read_results
from .geology_multi import (
    ROLES as MULTI_ROLES,
    SCENARIO as MULTI_TYPE,
    graph as multi_graph,
)
from .workflow import _authorize, _scope, _state_hash, checkpoint, step
from .geology_generic import GENERIC, MULTI_FAMILY
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
    "geology_multi_element_reasoning",
    GENERIC,
}

AUTOMATIC_GEOLOGY_STAGES = {
    "check": "geology-multi-check",
    "recheck": "geology-multi-check",
    "relations": "geology-multi-relations",
    "prospect": "geology-multi-prospect",
}


def _automatic_stage(workflow, stage):
    return (
        workflow.workflow_type in MULTI_FAMILY
        and workflow.plan.get("executionPolicy")
        in {"measured_geology_v1", "rule_geology_v2"}
        and not (workflow.plan.get("modelPlanning") and stage.get("name") == "check")
        and (
            (
                stage.get("name") in AUTOMATIC_GEOLOGY_STAGES
                and AUTOMATIC_GEOLOGY_STAGES.get(stage.get("name"))
                == stage.get("identifier")
            )
            or (
                stage.get("name") == "apply"
                and stage.get("identifier") == "geology-multi-apply"
                and stage.get("modificationsApproval", {}).get("mode") == "unchanged"
            )
        )
    )


def _verified_empty_check(workflow):
    check = next(
        (
            item
            for item in workflow.plan.get("stages", [])
            if item.get("name") == "check"
        ),
        {},
    )
    return bool(check.get("taskId")) and any(
        item.get("key") == "issues"
        and item.get("taskId") == check["taskId"]
        and item.get("scope") == "all"
        and item.get("rowCount") == 0
        and item.get("rows") == []
        for item in check.get("results", [])
    )


class ModelBudgetExhausted(ComputeError):
    """The task's frozen model-request allowance cannot finish the remaining work."""

    def __init__(self, minimum_remaining=1):
        super().__init__("已达到场景真实模型请求次数上限")
        self.minimum_remaining = minimum_remaining


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

ROLES[MULTI_TYPE] = MULTI_ROLES
GRAPHS[MULTI_TYPE] = multi_graph()
ROLES[GENERIC] = MULTI_ROLES
GRAPHS[GENERIC] = multi_graph()


def stage_title(workflow, stage: dict) -> str:
    if (
        stage.get("name") == "apply"
        and stage.get("modificationsApproval", {}).get("mode") == "unchanged"
    ):
        return "保留原始资料"
    if workflow.workflow_type in MULTI_FAMILY:
        from .geology_multi import TITLES

        return TITLES.get(stage["name"], stage["name"])
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
    chat = workflow.plan.get("chatExecution", {})
    frozen = workflow.plan.get("preparedAlgorithmFamily", {})
    options = (
        AlgorithmVersion.objects.select_related("algorithm")
        .filter(
            algorithm__in=allowed_algorithms(),
            algorithm__identifier__in=identifiers,
            algorithm__enabled=True,
            status="published",
        )
        .order_by("algorithm_id", "-created_at", "-id")
    )
    if frozen:
        if not identifiers <= set(frozen):
            raise ComputeError("已冻结算子家族不包含当前执行节点")
        options = options.filter(
            pk__in=[frozen[key]["versionId"] for key in identifiers]
        )
    if chat.get("algorithmVersionIds") is not None:
        options = options.filter(pk__in=chat["algorithmVersionIds"])
    versions = {}
    for version in options:
        identifier = version.algorithm.identifier
        if identifier in versions or not agent_algorithm_allowed(version):
            continue
        snapshot = {"versionId": version.id, "checksum": version.checksum}
        if frozen and frozen[identifier] != snapshot:
            raise PermissionDenied("冻结的科研算法版本已变化")
        snapshots = chat.get("algorithmSnapshots")
        if snapshots is not None and snapshots.get(identifier) != snapshot:
            raise PermissionDenied("科研算法在聊天解析后已变化，请重新匹配")
        versions[identifier] = {
            **snapshot,
            "name": version.algorithm.name,
            "manifest": version.manifest,
        }
    if set(versions) != identifiers:
        raise ComputeError(
            "场景所需算法尚未发布或不可调用："
            + ", ".join(sorted(identifiers - set(versions)))
        )
    return versions


def prepare_demo(workflow, user, p) -> None:
    if workflow.workflow_type == GENERIC:
        from apps.business_flows.input_preparation import advance_inputs

        if not advance_inputs(workflow, user, p):
            return
        from .geology_generic import prepare_generic

        if prepare_generic(workflow, user, p):
            return
    roles = ROLES[workflow.workflow_type]
    inputs = workflow.plan.get("inputs", {})
    if workflow.workflow_type in MULTI_FAMILY and "alteration_stack" in inputs:
        roles = {key: kind for key, kind in roles.items() if kind != "raster"} | {
            "alteration_stack": "raster"
        }
    if not isinstance(inputs, dict) or set(inputs) != set(roles):
        raise ComputeError("请按场景明确选择全部输入角色")
    if p["maxResources"] > 0 and len(set(inputs.values())) > p["maxResources"]:
        raise ComputeError("场景输入超过当前资源上限")
    validated_versions = None
    multi_knowledge = None
    if workflow.workflow_type in MULTI_FAMILY:
        from .geology_multi import prepare

        segment = workflow.parameters.get("segment", "all")
        validated_versions = _versions(workflow, multi_graph(segment))
        workflow.plan["algorithms"] = validated_versions
        multi_knowledge = prepare(workflow, user, p)
        expected_graph = multi_graph(
            segment,
            stack="alteration_stack" in inputs,
            raster=any(
                item.get("key") == "alteration_summary"
                for item in validated_versions["geology-multi-check"]["manifest"].get(
                    "outputs", []
                )
            ),
        )
        if _state_hash(workflow.plan.get("multiGraph")) != _state_hash(expected_graph):
            raise PermissionDenied("场景阶段或输入绑定已超出本次匹配范围，请重新确认")
    if workflow.workflow_type == "geology_map_review":
        from .geology_input_validation import validate_geology_inputs

        validated_versions = _versions(workflow, GRAPHS[workflow.workflow_type])
        validate_geology_inputs(
            user,
            p,
            inputs,
            workflow.parameters,
            workflow.resource_ids,
            versions=validated_versions,
        )
    snapshots, names = {}, {}
    for role, kind in roles.items():
        resource = resolve_workflow_resource(user, p, inputs[role], workflow)
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
    graph = workflow.plan.get("multiGraph") or GRAPHS[workflow.workflow_type]
    if workflow.plan.get("previousWorkflowId"):
        from .demo_updates import prepare_update

        graph = prepare_update(workflow, user, p)
    versions = validated_versions or _versions(workflow, graph)
    required_steps = len(graph)
    if workflow.workflow_type in MULTI_FAMILY:
        workflow.plan["executionPolicy"] = "rule_geology_v2"
        workflow.plan["modelPlanning"] = (
            not registry()[workflow.model].model_id.casefold().startswith("mock")
        )
        decisions_required = 2 if workflow.plan["modelPlanning"] else 1
    else:
        decisions_required = required_steps + (
            2 if workflow.workflow_type == "geology_map_review" else 1
        )
    if workflow.max_iterations < decisions_required:
        raise ComputeError("请将场景模型决策上限至少设为" + str(decisions_required))
    if workflow.max_operator_steps < required_steps:
        raise ComputeError("请将场景算子步骤上限至少设为" + str(required_steps))
    stages = []
    for name, identifier, bindings in graph:
        if (
            workflow.workflow_type == "geology_generic"
            and "faults" in workflow.plan.get("missingRoles", [])
        ):
            bindings = {
                key: "faults" if value == "apply/faults" else value
                for key, value in bindings.items()
            }
        manifest = versions[identifier]["manifest"]
        required = {i["key"] for i in manifest["inputs"] if i["required"]}
        declared = {i["key"] for i in manifest["inputs"]}
        if not required <= set(bindings) <= declared:
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
        multi_knowledge
        if multi_knowledge is not None
        else (
            search_entries(user, query, limit=8, domains=domains)["items"]
            if domains and workflow.workflow_type != "geology_map_review"
            else []
        )
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
        "modelCallBudget": {
            "limit": workflow.max_iterations,
            "minimumStageRequests": decisions_required,
            "batchPlanning": "after_check",
        },
    }
    workflow.resource_ids = sorted(
        set(inputs.values())
        | set(
            workflow.plan.get("uploadInputs", {}).values()
            if workflow.workflow_type == "geology_generic"
            else []
        )
    )
    workflow.evidence = knowledge
    workflow.status, workflow.current_step = "waiting_approval", "review_plan"
    workflow.detail = (
        "资料与算法已准备好，将检查问题、执行确认范围内的处置，并生成复查和对比成果。"
        if workflow.workflow_type in MULTI_FAMILY
        else "资料与算法已匹配，请核对本次执行计划。"
    )
    # A failed automatic confirmation must leave the worker's running state
    # recoverable, rather than publishing a partially prepared waiting plan.
    with transaction.atomic():
        _save(workflow)
        step(workflow, "demo_plan", action=workflow.plan, message=workflow.detail)
        checkpoint(workflow, "review_plan", {"planHash": workflow.plan_hash})
        chat = workflow.plan.get("chatExecution")
        from .input_execution import input_execution_authorized

        if workflow.status != "paused" and input_execution_authorized(
            workflow, user, p
        ):
            current = locked_workflow(workflow.id)
            confirm_demo(current, user, p, current.plan_hash)
            step(
                current,
                "input_execution_authorized",
                message="按已确认资料开始分析，处置建议仍须批准",
            )
            workflow.refresh_from_db()
        elif chat and chat.get("initialPlanAuthorized") and workflow.status != "paused":
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


@discovery_scope()
def authorize_demo(workflow, user, p, *, include_previous=True, history=False) -> None:
    from .deleted_resources import historical_deletion

    if not p.get("operatorEnabled", False):
        raise PermissionDenied("智能体算子调用已关闭")
    domains = _domains(workflow)
    from apps.knowledge.trial_rules import authorize_trial_evidence

    trial_ids = authorize_trial_evidence(workflow, user, history=history)
    if workflow.workflow_type in MULTI_FAMILY and not history:
        from .geology_multi import authorize_frozen

        authorize_frozen(workflow, user, p)
    for item in workflow.evidence:
        if item["id"] in trial_ids:
            continue
        visible = visible_entries(user, domains=domains).filter(pk=item["id"])
        if not history:
            visible = visible.filter(revision=item["revision"])
        if not visible.exists():
            raise PermissionDenied("知识依据或分区权限已变化，请重新生成计划")
    for role, identity in workflow.plan["inputs"].items():
        if history and historical_deletion(workflow, user, p, identity):
            continue
        resource = resolve_workflow_resource(
            user, p, identity, workflow, history=history
        )
        if resource.status != "active" or (
            not history
            and resource.updated_at.isoformat() != workflow.plan["inputSnapshots"][role]
        ):
            raise PermissionDenied("原始输入已变化或停用，请重新核对")
    for identifier, fixed in workflow.plan["algorithms"].items():
        chat = workflow.plan.get("chatExecution", {})
        if chat and (
            fixed["versionId"] not in chat.get("algorithmVersionIds", [])
            or (
                "algorithmSnapshots" in chat
                and chat["algorithmSnapshots"].get(identifier)
                != {"versionId": fixed["versionId"], "checksum": fixed["checksum"]}
            )
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
            if history and historical_deletion(workflow, user, p, output["resourceId"]):
                continue
            resource = resolve_workflow_resource(
                user, p, output["resourceId"], workflow, history=history
            )
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
                or (
                    not history
                    and resource.updated_at.isoformat() != output["resourceRevision"]
                )
            ):
                raise PermissionDenied("下游输入不再对应已核验的实际输出")
    if workflow.import_results and not history:
        require_actor(user, workflow.project_tag_id, "catalog.add_dataresource")
    if include_previous and workflow.plan.get("previousWorkflowId"):
        from .demo_updates import _chain, authorize_update

        if history:
            _chain(workflow, user, p, history=True)
        else:
            authorize_update(workflow, user, p)


@checksum_scope()
@transaction.atomic
def confirm_demo(
    workflow,
    user,
    p,
    plan_hash,
    selected_suggestion_ids=None,
    field_mapping=None,
    alteration_actions=None,
    execute_after_mapping=False,
    apply_rule_suggestions=False,
) -> None:
    from .workflow_slots import require_compute_slot

    require_compute_slot(user, workflow.id)
    if workflow.plan.get("phase") == "review_mapping":
        from .geology_generic import confirm_mapping

        confirm_mapping(
            workflow,
            user,
            p,
            plan_hash,
            field_mapping,
            execute_after_mapping=execute_after_mapping,
            apply_rule_suggestions=apply_rule_suggestions,
        )
        return
    if field_mapping is not None:
        raise ComputeError("当前阶段不接受字段对应", 400)
    if workflow.status != "waiting_approval" or workflow.cancel_requested:
        raise ComputeError("此场景当前不能确认执行", 409)
    if plan_hash != workflow.plan_hash or _state_hash(workflow.plan) != plan_hash:
        raise ComputeError("场景计划已变化，请刷新后确认", 409)
    authorize_demo(workflow, user, p)
    if workflow.plan["phase"] == "review_modifications":
        if workflow.workflow_type in MULTI_FAMILY:
            from .geology_multi_review import approve_modifications
        else:
            from .geology_review import approve_modifications

        if workflow.workflow_type not in {"geology_map_review", *MULTI_FAMILY}:
            raise ComputeError("当前场景不支持此修改审核", 409)
        approve_modifications(
            workflow,
            user,
            p,
            selected_suggestion_ids,
            plan_hash,
            **(
                {"alteration_actions": alteration_actions}
                if workflow.workflow_type in MULTI_FAMILY
                else {}
            ),
        )
        workflow.plan["phase"] = "decide"
        workflow.status = "queued"
    elif workflow.plan["phase"] == "review_results":
        stage = workflow.plan["stages"][workflow.plan["stageIndex"]]
        budget_retry = bool(stage.get("contextBudgetReview"))
        if budget_retry:
            stage.setdefault("modelBudgetHistory", []).append(
                {
                    key: stage.pop(key)
                    for key in (
                        "contextBudgetReview",
                        "modelRequestPayload",
                        "modelRequestInstruction",
                        "modelAttempts",
                    )
                    if key in stage
                }
            )
        reviewing_output = bool(stage.get("taskId"))
        if not budget_retry:
            stage["manualApproved" if reviewing_output else "decisionApproved"] = True
        step(
            workflow,
            "human_review",
            action={"approvedOutputs": workflow.plan["reviewOutputs"]},
            message=(
                "用户请求重新分析输入预算，未批准任何候选结果"
                if budget_retry
                else "用户已确认候选结果，保留原质量记录"
            ),
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
    specs = {
        item["key"]: item
        for item in workflow.plan["algorithms"][stage["identifier"]]["manifest"][
            "inputs"
        ]
    }
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
            if specs.get(key, {}).get("required") is False:
                del values[key]
                continue
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


def _has_model_progress(stage) -> bool:
    batches = stage.get("modelBatches") or {}

    def contacted(attempts):
        # Missing flags in older audits remain conservative; a persisted,
        # explicitly unsent budget rejection does not consume a decision.
        if not isinstance(attempts, list):
            return bool(attempts)
        return any(
            not isinstance(attempt, dict) or attempt.get("requested") is not False
            for attempt in attempts
        )

    return bool(
        contacted(stage.get("modelAttempts", []))
        or batches.get("cursor")
        or any(
            contacted(batch.get("stage", {}).get("modelAttempts", []))
            for batch in batches.get("batches", [])
        )
    )


def _future_model_requests(workflow, stage):
    stages = workflow.plan["stages"][workflow.plan["stageIndex"] + 1 :]
    return sum(
        not item.get("decision")
        and not _automatic_stage(workflow, item)
        and not (
            workflow.plan.get("executionPolicy") == "rule_geology_v2"
            and item.get("name") == "apply"
        )
        for item in stages
    ) + int(
        stage["identifier"] != "finish"
        and not any(item["identifier"] == "finish" for item in stages)
        and not workflow.plan.get("finalStage", {}).get("decision")
    )


def _minimum_model_requests(workflow, stage):
    batches = stage.get("modelBatches") or {}
    planned = batches.get("preflight", {}).get("batches", [])
    current = max(1, len(planned) - batches.get("cursor", 0))
    return current + _future_model_requests(workflow, stage)


def _exhaust_model_budget(workflow, stage, minimum_remaining):
    calls = workflow.plan.get("actualModelCallCount", 0)
    batches = stage.get("modelBatches") or {}
    if batches:
        batches["status"] = "budget_exhausted"
    stage["status"] = "budget_exhausted"
    summary = {
        "usedRequests": calls,
        "usedDecisions": workflow.iteration,
        "limit": workflow.max_iterations,
        "minimumRemainingRequests": minimum_remaining,
        "stage": stage["name"],
        "completedBatches": batches.get("cursor", 0),
        "coveredMembers": batches.get("coveredMemberCount", 0),
        "memberCount": batches.get("memberCount", 0),
        "completedStages": [
            item["name"]
            for item in workflow.plan["stages"]
            if item.get("status") == "completed"
        ],
    }
    workflow.plan.update(phase="budget_exhausted", budgetExhausted=summary)
    workflow.status = "failed"
    workflow.detail = (
        f"模型预算不足：请求已用{calls}/{workflow.max_iterations}次，"
        f"阶段判断{workflow.iteration}/{workflow.max_iterations}次，"
        f"至少还需{minimum_remaining}次；已完成{len(summary['completedStages'])}个阶段、"
        f"{summary['completedBatches']}个批次，结果与审计已保留。"
        "请缩小资料范围，或由管理员提高允许上限后，调整并重新发起任务。"
    )[:300]
    _save(workflow)
    checkpoint(workflow, "budget_exhausted", summary)


def _submit_stage(workflow, user, p, stage) -> None:
    # Reading and verifying large result files can exceed the worker's heartbeat
    # lease. Do that before reserving SQLite's writer so the compute worker can
    # keep its lease fresh. The final transaction rechecks live authorization.
    current = AgentWorkflow.objects.get(pk=workflow.id)
    check_pause(workflow)
    if current.cancel_requested or current.status not in {"queued", "running"}:
        raise ModelError("场景已停止，未提交下一步计算")
    fresh, policy = _authorize(current)
    authorize_demo(current, fresh, policy)
    _prepare_and_submit_stage(workflow, fresh, policy, stage)


def _prepare_and_submit_stage(workflow, user, p, stage) -> None:
    if workflow.workflow_type in MULTI_FAMILY and stage["name"] == "apply":
        from .geology_multi_review import create_approved_changes

        workflow.plan["approved_changes"] = create_approved_changes(
            workflow, user, p, stage
        ).id
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
        resolve_workflow_resource(user, p, identity, workflow)
    body = {
        "name": (
            f"地质成果智能检查与修正 {stage_title(workflow, stage)}"
            if workflow.workflow_type == "geology_map_review"
            else f"地质综合分析 {stage_title(workflow, stage)}"
            if workflow.workflow_type in MULTI_FAMILY
            else f"{workflow.goal[:90]} {stage_title(workflow, stage)}"
        ),
        "versionId": workflow.plan["algorithms"][stage["identifier"]]["versionId"],
        "inputs": inputs,
        "parameters": stage["parameters"],
        "idempotencyKey": f"demo-{workflow.id}-{stage['name']}"
        + (
            f"-review-{len(workflow.plan['retainedReviewHistory'])}"
            if workflow.plan.get("retainedReviewHistory")
            else ""
        ),
        "trial": False,
    }
    with transaction.atomic():
        current = locked_workflow(workflow.id)
        check_pause(workflow)
        if current.cancel_requested or current.status not in {"queued", "running"}:
            raise ModelError("场景已停止，未提交下一步计算")
        if current.plan_hash != workflow.plan_hash:
            raise ComputeError("场景方案已变化，请重新核对后再提交计算", 409)
        user, p = _authorize(current)
        authorize_demo(current, user, p)
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


def result_import_name(workflow, stage, output):
    created = timezone.localtime(workflow.created_at)
    number = len(workflow.plan.get("retainedReviewHistory", []))
    prefix = f"核查第{number}轮 · " if number else ""
    return (
        f"{prefix}{stage_title(workflow, stage)} · {output.label} · {created:%m-%d %H:%M:%S}"
    )[:160]


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
    # Waiting for imports must not hold SQLite's writer while revalidating all
    # inputs. The compute worker needs that writer to publish each ready item.
    with discovery_scope():
        user, p = _authorize(workflow)
        authorize_demo(workflow, user, p)
    workflow.steps.filter(kind="submit_operator", compute_task_id=task.id).exclude(
        status="succeeded"
    ).update(
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
    if workflow.workflow_type in MULTI_FAMILY:
        from .geology_multi import VISIBLE_OUTPUTS

        importable = [
            output
            for output in outputs
            if output.key in VISIBLE_OUTPUTS.get(stage["name"], set())
        ]
    else:
        importable = outputs
    existing = {
        item.output_id: item
        for item in ComputeImport.objects.filter(output__in=importable)
    }
    missing = [output for output in importable if output.id not in existing]
    if missing:
        with transaction.atomic():
            if _collection_cancelled(workflow):
                return False
            with discovery_scope():
                user, p = _authorize(workflow)
                authorize_demo(workflow, user, p)
            source = "" if stage.get("manualApproved") else f"workflow:{workflow.id}"
            for output in missing:
                name = result_import_name(workflow, stage, output)
                existing[output.id] = request_output_import(
                    user, output, name=name, request_source=source
                )
    records = [(output, existing[output.id]) for output in importable]
    for output, record in records:
        if record.status == "failed":
            raise ComputeError(
                "结果入库失败，已保留任务与原结果：" + record.error[:200]
            )
    if any(record.status != "ready" or not record.resource_id for _, record in records):
        ready = sum(
            record.status == "ready" and bool(record.resource_id)
            for _, record in records
        )
        detail = f"正在入库：已完成 {ready}/{len(records)} 项成果"
        if workflow.detail != detail:
            now = timezone.now()
            AgentWorkflow.objects.filter(
                pk=workflow.pk,
                status="waiting_compute",
                pause_requested=False,
                cancel_requested=False,
            ).update(detail=detail, heartbeat=now, updated_at=now)
            workflow.detail = detail
        return False
    stage["outputs"] = []
    internal_resource_ids = set()
    for output, record in records:
        resource = resolve_workflow_resource(user, p, record.resource_id, workflow)
        if (
            workflow.workflow_type in MULTI_FAMILY
            and stage["name"] == "apply"
            and output.key in {"faults", "alterations"}
            and any(
                item["key"] == "final_faults"
                for item in task.version.manifest["outputs"]
            )
        ):
            marker = f"workflow-working:{workflow.id}:calculation"
            if resource.source != marker:
                resource.source = marker
                resource.owner_only = True
                resource.maintainer = user
                resource.save(
                    update_fields=["source", "owner_only", "maintainer", "updated_at"]
                )
            internal_resource_ids.add(resource.id)
        if (
            workflow.workflow_type in MULTI_FAMILY
            and stage["name"] == "apply"
            and output.key == "lithology"
        ):
            from .generic_inputs import style_lithology

            style_lithology(resource)
        if (
            workflow.workflow_type in MULTI_FAMILY
            and stage["name"] == "apply"
            and output.key.startswith("changes_")
        ):
            resource.default_visualization = {
                "symbolization": {
                    "opacity": 65,
                    "renderer": {"type": "single"},
                    "fill": {
                        "fillColor": "#f97316",
                        "fillOpacity": 0.25,
                        "fillOutlineColor": "#f97316",
                    },
                    "line": {"lineColor": "#f97316", "lineWidth": 2},
                }
            }
            resource.save(update_fields=["default_visualization", "updated_at"])
        if workflow.workflow_type in MULTI_FAMILY:
            from .result_colors import style_result

            style_result(workflow, resource, output.key)
            from apps.catalog.display_geometry import prewarm_display_geometry

            prewarm_display_geometry(resource)
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
    if workflow.workflow_type in MULTI_FAMILY:
        from .alteration_result_colors import style_alteration_outputs

        style_alteration_outputs(workflow, outputs)
    workflow.result_ids = sorted(set(workflow.result_ids + [o.id for o in outputs]))
    workflow.result_resource_ids = sorted(
        set(
            workflow.result_resource_ids
            + [
                record.resource_id
                for _, record in records
                if record.resource_id not in internal_resource_ids
            ]
        )
    )
    stage["status"] = "completed"
    if workflow.workflow_type in MULTI_FAMILY:
        from .geology_multi_review import update_map

        update_map(workflow)
    workflow.plan["stageIndex"] += 1
    workflow.plan["phase"] = "decide"
    workflow.status, workflow.detail = "queued", "已读取本步结果，下一步将据此更新判断"
    with transaction.atomic():
        if _collection_cancelled(workflow):
            return False
        user, p = _authorize(workflow)
        authorize_demo(workflow, user, p)
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


@checksum_scope()
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
                    task = authorized_task(
                        user, submitted.compute_task_id, p, workflow=workflow
                    )
                    if task.status in {"queued", "validating", "running"}:
                        task_action(task, user, "cancel")
                workflow.status, workflow.detail = "cancelled", "已停止场景后续处理"
                _save(workflow)
                return
            if not workflow.execute_operators:
                prepare_demo(workflow, user, p)
                return
            authorize_demo(workflow, user, p)
            if workflow.workflow_type == "geology_map_review":
                from .geology_review_outcome import finish_without_edits

                finish_without_edits(workflow, user, p)
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
                task = authorized_task(user, stage["taskId"], p, workflow=workflow)
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
            if (
                workflow.workflow_type in MULTI_FAMILY
                and workflow.plan.get("executionPolicy") == "rule_geology_v2"
                and stage["name"] == "apply"
                and not stage.get("decision")
                and not _has_model_progress(stage)
            ):
                from .rule_dispositions import (
                    build_rule_proposal,
                    authorize_rule_execution,
                )
                from .geology_multi_review import freeze_proposal

                decision, edits, summary = build_rule_proposal(workflow)
                if workflow.parameters.get("_businessFlow"):
                    from apps.business_flows.legacy import review_rule_proposal

                    decision, edits = review_rule_proposal(
                        workflow, user, p, stage, (decision, edits)
                    )
                with transaction.atomic():
                    current = locked_workflow(workflow.id)
                    check_pause(workflow)
                    if current.cancel_requested or current.status not in {
                        "queued",
                        "running",
                    }:
                        raise ModelError("分析已停止，未生成自动处置")
                    fresh, policy = _authorize(current)
                    authorize_demo(current, fresh, policy)
                    stage.update(
                        decision=decision,
                        edits=edits,
                        executionMode="model_reviewed"
                        if workflow.parameters.get("_businessFlow")
                        and stage.get("executionMode") == "model_reviewed"
                        else "rule_verified",
                        ruleDispositionSummary=summary,
                    )
                    step(
                        workflow,
                        "rule_dispositions",
                        message=decision["judgement"],
                        output_refs={"ruleDispositionSummary": summary},
                    )
                    freeze_proposal(workflow, stage)
                    if not stage.get("modificationsApproval") and not (
                        workflow.parameters.get("_businessFlow")
                        and stage.get("executionMode") == "model_reviewed"
                    ):
                        authorize_rule_execution(workflow, fresh, policy, stage)
                    _save(workflow)
                return
            if (
                workflow.workflow_type in MULTI_FAMILY
                and workflow.plan.get("executionPolicy")
                in {"measured_geology_v1", "rule_geology_v2"}
                and stage["name"] == "apply"
                and not stage.get("modificationsApproval")
                and not stage.get("decision")
                and not _has_model_progress(stage)
                and _verified_empty_check(workflow)
            ):
                from .geology_multi_review import freeze_proposal

                stage["edits"] = []
                freeze_proposal(workflow, stage)
                _save(workflow)
                return
            if (
                _automatic_stage(workflow, stage)
                and not stage.get("decision")
                and not _has_model_progress(stage)
                and not stage.get("contextBudgetReview")
            ):
                stage["executionMode"] = "automatic"
                _submit_stage(workflow, user, p, stage)
                step(
                    workflow,
                    "automatic_stage",
                    message=f"按已确认资料与规则执行{stage_title(workflow, stage)}",
                    action={"stage": stage["name"], "identifier": stage["identifier"]},
                    compute_task_id=stage["taskId"],
                )
                return
            if not stage.get("decision"):
                planning = (
                    workflow.plan.get("modelPlanning") and stage.get("name") == "check"
                )
                model_policy = (
                    {
                        **p,
                        "reasoningEffort": "low",
                        "maxOutputTokens": min(p["maxOutputTokens"], 4096),
                        "maxRunSeconds": min(p["maxRunSeconds"], 90),
                    }
                    if planning
                    else {
                        **p,
                        "_thinking": False,
                        "reasoningEffort": "low",
                        "maxOutputTokens": min(p["maxOutputTokens"], 6144),
                        "maxRunSeconds": min(p["maxRunSeconds"], 120),
                    }
                    if workflow.plan.get("executionPolicy") == "rule_geology_v2"
                    and stage["identifier"] == "finish"
                    else p
                )
                recovering_response = _has_model_progress(stage)
                if (
                    not recovering_response
                    and workflow.iteration >= workflow.max_iterations
                ):
                    _exhaust_model_budget(
                        workflow, stage, _minimum_model_requests(workflow, stage)
                    )
                    return
                deadline, heartbeat_at = (
                    time.monotonic() + model_policy["maxRunSeconds"],
                    [0.0],
                )

                def check_stream_authorization():
                    check_pause(workflow)
                    current = AgentWorkflow.objects.get(pk=workflow.id)
                    if current.cancel_requested or current.status not in {
                        "queued",
                        "running",
                    }:
                        raise ModelError("场景分析已停止或达到本步时限")
                    fresh, policy = _authorize(current)
                    authorize_demo(current, fresh, policy)
                    if time.monotonic() - heartbeat_at[0] > 2:
                        AgentWorkflow.objects.filter(pk=current.id).update(
                            heartbeat=timezone.now()
                        )
                        heartbeat_at[0] = time.monotonic()

                guard = ModelStreamGuard(check_stream_authorization, deadline)
                activity = WorkflowModelActivity(
                    workflow,
                    "规划算子执行方案" if planning else stage_title(workflow, stage),
                    registry()[workflow.model],
                    model_policy,
                    guard,
                )

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
                    task = authorized_task(
                        user, previous["taskId"], p, workflow=workflow
                    )
                    results.extend(read_results(workflow, user, p, task))

                def record_attempt(attempt):
                    # Persist rejection before another network request; the final
                    # stage already belongs to plan.finalStage when not in stages.
                    blocked = False
                    with transaction.atomic():
                        if attempt["status"] == "requesting":
                            calls = workflow.plan.get("actualModelCallCount", 0)
                            # A repair still needs this unfinished batch plus all
                            # frozen later batches and graph stages to succeed.
                            reserve = (
                                _minimum_model_requests(workflow, stage)
                                if stage.get("modelBatches", {}).get("preflight")
                                else 1
                            )
                            review_calls = 0
                            if workflow.parameters.get("_businessFlow"):
                                from apps.business_flows.state import (
                                    state as business_state,
                                )

                                review_calls = len(
                                    business_state(workflow).get("requestedIds", [])
                                )
                            if calls + review_calls + reserve > workflow.max_iterations:
                                blocked = True
                                attempt.update(
                                    status="budget_blocked",
                                    requested=False,
                                    accepted=False,
                                    validationError=(
                                        "剩余场景真实模型请求额度不足以完成已规划批次和后续阶段"
                                    ),
                                )
                            else:
                                workflow.plan["actualModelCallCount"] = calls + 1
                                attempt["requested"] = True
                        audit_status = (
                            "running"
                            if attempt["status"] in {"requesting", "response_received"}
                            else "succeeded"
                            if attempt.get("accepted")
                            else "failed"
                        )
                        audit_values = dict(
                            status=audit_status,
                            action={
                                "stage": stage["name"],
                                "attempt": attempt["attempt"],
                                "requestSha256": attempt["requestSha256"],
                                **(
                                    {"batchIndex": attempt["batchIndex"]}
                                    if "batchIndex" in attempt
                                    else {}
                                ),
                                **(
                                    {"accepted": attempt["accepted"]}
                                    if "accepted" in attempt
                                    else {}
                                ),
                            },
                            message=attempt.get(
                                "validationError",
                                "模型响应通过实际证据校验"
                                if audit_status == "succeeded"
                                else "正在读取模型响应",
                            )[:500],
                            output_refs={"modelResponse": attempt["responseArtifact"]}
                            if "responseArtifact" in attempt
                            else {},
                            metrics={
                                "inputTokens": attempt["inputTokens"],
                                "contentBytes": attempt["contentBytes"],
                                "usage": attempt["usage"],
                            },
                        )
                        if attempt.get("auditStepId"):
                            workflow.steps.filter(pk=attempt["auditStepId"]).update(
                                **audit_values,
                                finished_at=timezone.now()
                                if audit_status != "running"
                                else None,
                            )
                        else:
                            audit_step = step(
                                workflow,
                                "analysis_model_attempt",
                                action=audit_values["action"],
                                status=audit_values["status"],
                                message=audit_values["message"],
                                output_refs=audit_values["output_refs"],
                                metrics=audit_values["metrics"],
                            )
                            attempt["auditStepId"] = audit_step.id
                            if audit_status == "running":
                                workflow.steps.filter(pk=audit_step.id).update(
                                    finished_at=None
                                )
                        _save(workflow)
                    if blocked:
                        raise ModelBudgetExhausted(
                            _minimum_model_requests(workflow, stage)
                        )

                from .decision_budget import BudgetReviewRequired

                try:
                    if (
                        workflow.workflow_type in MULTI_FAMILY
                        and stage["identifier"] == "geology-multi-apply"
                        and not registry()[workflow.model]
                        .model_id.casefold()
                        .startswith("mock")
                        and not recovering_response
                    ):
                        from .demo_decision_batches import needs_batches, plan_batches

                        guard.poll()
                        if needs_batches(workflow, stage, results):
                            batches = stage.get("modelBatches") or {}
                            planned = batches.get("preflight")
                            if planned is None:
                                planned = plan_batches(
                                    workflow, user, p, stage, results, guard
                                )
                                if planned["batches"]:
                                    stage["modelBatches"] = {
                                        "sourceSha256": planned["sourceSha256"],
                                        "cursor": 0,
                                        "batches": [],
                                        "memberCount": planned["memberCount"],
                                        "status": "planned",
                                        "preflight": planned,
                                    }
                                    _save(workflow)
                        guard.poll()
                        remaining = _minimum_model_requests(workflow, stage)
                        if (
                            workflow.plan.get("actualModelCallCount", 0) + remaining
                            > workflow.max_iterations
                        ):
                            raise ModelBudgetExhausted(remaining)
                    decision, edits = decide(
                        workflow,
                        user,
                        model_policy,
                        stage,
                        results,
                        guard,
                        record_attempt,
                        on_response=lambda attempt=None: record_attempt(
                            stage["modelAttempts"][-1] if attempt is None else attempt
                        ),
                        on_thinking=activity.thinking,
                        on_progress=activity.progress,
                        batch_limit=1,
                    )
                    if workflow.parameters.get("_businessFlow"):
                        from apps.business_flows.legacy import review_decision

                        decision, edits = review_decision(
                            workflow,
                            user,
                            model_policy,
                            stage,
                            results,
                            (decision, edits),
                            guard,
                            lambda: decide(
                                workflow,
                                user,
                                model_policy,
                                stage,
                                results,
                                guard,
                                record_attempt,
                                on_thinking=activity.thinking,
                                on_progress=activity.progress,
                            ),
                        )
                    guard.poll()
                except BatchProgressPending:
                    # The completed child response and cursor were saved by the
                    # attempt callback. Requeue only under current live controls.
                    guard.poll()
                    with transaction.atomic():
                        current = locked_workflow(workflow.id)
                        check_pause(workflow)
                        if current.cancel_requested or current.status not in {
                            "queued",
                            "running",
                        }:
                            raise ModelError("场景分析已停止，未继续后续批次")
                        batches = stage["modelBatches"]
                        workflow.status = "queued"
                        workflow.detail = (
                            f"已核验并保存{batches['cursor']}个批次，"
                            f"覆盖{batches['coveredMemberCount']}/{batches['memberCount']}个对象；"
                            "下一步继续处理剩余批次"
                        )
                        _save(workflow)
                    return
                except BudgetReviewRequired as exc:
                    activity.fail()
                    guard.poll()
                    if not _has_model_progress(stage) and not recovering_response:
                        workflow.iteration -= 1
                    if stage.get("contextBudgetReview", {}).get("kind") == (
                        "model_call_limit"
                    ):
                        _exhaust_model_budget(
                            workflow, stage, _minimum_model_requests(workflow, stage)
                        )
                        return
                    stage.setdefault(
                        "contextBudgetReview",
                        {"reason": str(exc), "requested": False},
                    )
                    if index >= len(stages):
                        workflow.plan["stages"].append(stage)
                    _pause(workflow, stage, str(exc))
                    return
                except ModelBudgetExhausted as exc:
                    activity.fail()
                    guard.poll()
                    if not _has_model_progress(stage) and not recovering_response:
                        workflow.iteration -= 1
                    _exhaust_model_budget(workflow, stage, exc.minimum_remaining)
                    return
                except Exception:
                    activity.fail()
                    if not _has_model_progress(stage) and not recovering_response:
                        workflow.iteration -= 1
                    raise
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
                    if current.cancel_requested or current.status not in {
                        "queued",
                        "running",
                    }:
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
            if (
                workflow.workflow_type in MULTI_FAMILY
                and stage["name"] == "apply"
                and not stage.get("modificationsApproval")
            ):
                from .geology_multi_review import freeze_proposal

                with transaction.atomic():
                    current = locked_workflow(workflow.id)
                    check_pause(workflow)
                    if current.cancel_requested or current.status not in {
                        "queued",
                        "running",
                    }:
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
                        {"planHash": workflow.plan_hash},
                    )
                return
            if stage["identifier"] == "finish":
                with transaction.atomic():
                    current = locked_workflow(workflow.id)
                    check_pause(workflow)
                    if current.cancel_requested or current.status not in {
                        "queued",
                        "running",
                    }:
                        raise ModelError("检查已停止，未结束场景分析")
                    fresh, policy = _authorize(current)
                    authorize_demo(current, fresh, policy)
                    stage["status"] = "completed"
                    workflow.plan["phase"] = "completed"
                    workflow.plan["finalDecision"] = stage["decision"]
                    workflow.status, workflow.current_step = "succeeded", "finalize"
                    workflow.detail = (
                        stage["decision"]["resultSummary"]
                        or stage["decision"]["judgement"]
                    )
                    workflow.detail = workflow.detail[:300]
                    _save(workflow)
                    checkpoint(
                        workflow,
                        "finalize",
                        {"resourceIds": workflow.result_resource_ids},
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
