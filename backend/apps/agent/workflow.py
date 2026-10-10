"""Durable preview, confirmed calculation, knowledge check and result import."""

from __future__ import annotations

import hashlib
import json
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.compute.models import AlgorithmVersion, ComputeImport
from apps.compute.services import (
    ComputeError,
    allowed_algorithms,
    agent_algorithm_allowed,
    validate_submission,
    submit as submit_compute,
    request_output_import,
)
from apps.compute.access import require_actor
from apps.projects.context import ProjectScope, project_scope
from .models import AgentCheckpoint, AgentWorkflow, AgentWorkflowStep
from .policy import fresh_user, require_access
from .tools import resources, resolve_resource

try:
    import langgraph  # noqa: F401

    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False


def _scope(workflow):
    return ProjectScope(
        (workflow.project_tag_id,), workflow.project_tag_id, workflow.owner_id
    )


def _state_hash(state):
    return hashlib.sha256(
        json.dumps(
            state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def checkpoint(workflow, node, state):
    AgentCheckpoint.objects.create(
        workflow=workflow, node=node, state=state, state_hash=_state_hash(state)
    )


def step(
    workflow,
    kind,
    *,
    message="",
    status="succeeded",
    action=None,
    input_refs=None,
    output_refs=None,
    metrics=None,
    compute_task_id=None,
    error_code="",
):
    return AgentWorkflowStep.objects.create(
        workflow=workflow,
        sequence=workflow.steps.count() + 1,
        kind=kind,
        status=status,
        message=message[:500],
        action=action or {},
        input_refs=input_refs or {},
        output_refs=output_refs or {},
        metrics=metrics or {},
        compute_task_id=compute_task_id,
        error_code=error_code[:80],
        finished_at=timezone.now(),
    )


def _authorize(workflow):
    user = fresh_user(workflow.owner_id)
    p = require_access(user, "agent", workflow.model)
    if not p.get("workflowEnabled", True):
        raise PermissionDenied("科研工作流功能已关闭")
    for rid in workflow.resource_ids:
        resolve_resource(user, p, rid)
    validate_knowledge(workflow, user)
    return user, p


def validate_knowledge(workflow, user):
    from apps.knowledge.services import visible_entries

    for entry in workflow.evidence:
        if (
            not visible_entries(user)
            .filter(pk=entry.get("id"), revision=entry.get("revision"))
            .exists()
        ):
            raise PermissionDenied("知识依据已变化或无权访问，请重新生成计划")


def _algorithm(workflow):
    versions = list(
        AlgorithmVersion.objects.select_related("algorithm").filter(
            status="published", algorithm__in=allowed_algorithms().filter(enabled=True)
        )
    )
    versions = [v for v in versions if agent_algorithm_allowed(v)]
    if workflow.algorithm_version_id:
        chosen = next(
            (v for v in versions if v.id == workflow.algorithm_version_id), None
        )
        if chosen:
            return chosen
        raise ComputeError("指定算法未发布、已停用或未允许智能体调用")
    goal = workflow.goal.casefold()
    matches = []
    for version in versions:
        algorithm = version.algorithm
        tokens = {algorithm.identifier.casefold(), algorithm.name.casefold()}
        tokens.update(re.findall(r"[a-z][a-z0-9]{2,}", algorithm.name.casefold()))
        score = max(
            (len(token) for token in tokens if token and token in goal), default=0
        )
        if score:
            matches.append((score, version))
    if not matches:
        names = "、".join(sorted({v.algorithm.name for v in versions})[:8])
        raise ComputeError(
            "目标未唯一匹配已发布算法，请在目标中写明算法名称"
            + ("：" + names if names else "；当前没有可调用算法")
        )
    best = max(score for score, _ in matches)
    winners = [version for score, version in matches if score == best]
    if len(winners) != 1:
        raise ComputeError("目标匹配多个算法或版本，请指定一个算法版本")
    return winners[0]


def _body(workflow, plan):
    return {
        "name": f"智能体：{workflow.goal[:120]}",
        "versionId": plan["algorithmVersionId"],
        "inputs": plan["inputs"],
        "parameters": plan["parameters"],
        "idempotencyKey": f"agent-workflow-{workflow.id}-{workflow.iteration}",
        "trial": False,
    }


def _prepare(workflow, user, p):
    from apps.knowledge.services import search_entries

    version = _algorithm(workflow)
    selected = list(
        resources(user, p, workflow.resource_ids)
        .filter(status="active")
        .order_by("id")[:100]
    )
    inputs = dict(workflow.plan.get("inputs", {}))
    for spec in version.manifest.get("inputs", []):
        if spec["key"] in inputs:
            resolve_resource(user, p, inputs[spec["key"]], workflow.resource_ids)
            continue
        candidates = [r for r in selected if r.data_type == spec["kind"]]
        named = [r for r in candidates if r.name.casefold() in workflow.goal.casefold()]
        candidates = named or candidates
        if len(candidates) == 1:
            inputs[spec["key"]] = candidates[0].id
        elif spec.get("required", True):
            raise ComputeError(
                f"请明确选择 {spec['label']} 的一个输入，当前有 {len(candidates)} 个兼容候选"
            )
    plan = {
        "algorithmVersionId": version.id,
        "algorithm": version.algorithm.name,
        "inputs": inputs,
        "parameters": workflow.parameters,
        "goal": workflow.goal,
    }
    validated = validate_submission(user, _body(workflow, plan))
    plan["parameters"] = validated["parameters"]
    if (
        len({resource.id for _, resource, _ in validated["resources"]})
        > p["maxResources"]
    ):
        raise ComputeError("计划使用的数据资源超过当前策略上限")
    plan["inputNames"] = {
        key: resource.name for key, resource, _ in validated["resources"]
    }
    plan["inputRevisions"] = {
        key: resource.updated_at.isoformat()
        for key, resource, _ in validated["resources"]
    }
    plan["algorithmChecksum"] = version.checksum
    knowledge = search_entries(user, workflow.goal[:300], limit=8)
    plan["knowledge"] = knowledge["items"]
    plan["importResults"] = workflow.import_results
    workflow.plan, workflow.plan_hash = plan, _state_hash(plan)
    workflow.resource_ids = sorted(set(inputs.values()))
    workflow.algorithm_version_id, workflow.parameters = version.id, plan["parameters"]
    workflow.evidence = knowledge["items"]
    workflow.status, workflow.current_step = "waiting_approval", "review_plan"
    workflow.detail = (
        "计划和输入已校验，请确认后执行；结果将自动入库"
        if workflow.import_results
        else "计划已校验，请确认后执行"
    )
    workflow.save()
    step(
        workflow,
        "discover_inputs",
        message=f"已匹配 {len(inputs)} 项授权输入",
        output_refs={"resourceIds": workflow.resource_ids},
    )
    step(workflow, "build_plan", message="已按算法输入及参数规范校验计划", action=plan)
    checkpoint(workflow, "review_plan", {"planHash": workflow.plan_hash})


def validate_confirmed_plan(workflow, user, p):
    validate_knowledge(workflow, user)
    if not p.get("operatorEnabled", False):
        raise PermissionDenied("智能体调用算子尚未由管理员开启")
    if not workflow.plan_hash or _state_hash(workflow.plan) != workflow.plan_hash:
        raise ComputeError("执行计划已变化，请重新预览")
    version = _algorithm(workflow)
    if version.checksum != workflow.plan.get("algorithmChecksum"):
        raise ComputeError("算法版本已变化，请重新预览")
    validated = validate_submission(user, _body(workflow, workflow.plan))
    for key, resource, _ in validated["resources"]:
        if resource.updated_at.isoformat() != workflow.plan["inputRevisions"].get(key):
            raise ComputeError("输入数据已变化，请重新预览")
    if workflow.import_results:
        require_actor(user, workflow.project_tag_id, "catalog.add_dataresource")


def run_workflow(workflow_id):
    workflow = AgentWorkflow.objects.get(pk=workflow_id)
    from .demo_workflow import DEMO_TYPES, advance_demo

    if workflow.workflow_type in DEMO_TYPES:
        advance_demo(workflow_id)
        return
    if workflow.status not in {"queued", "running", "interrupted"}:
        return
    with project_scope(_scope(workflow)):
        try:
            user, p = _authorize(workflow)
            if workflow.cancel_requested:
                workflow.status, workflow.detail = "cancelled", "已取消"
            elif not workflow.execute_operators:
                _prepare(workflow, user, p)
                return
            else:
                validate_confirmed_plan(workflow, user, p)
                if workflow.operator_steps >= workflow.max_operator_steps:
                    raise ComputeError("已达到算子步骤上限")
                task = submit_compute(user, _body(workflow, workflow.plan))
                if not workflow.steps.filter(compute_task_id=task.id).exists():
                    step(
                        workflow,
                        "submit_operator",
                        message="已提交计算中心",
                        compute_task_id=task.id,
                        status="waiting",
                    )
                workflow.operator_steps = 1
                workflow.status, workflow.current_step = (
                    "waiting_compute",
                    "wait_operator",
                )
                workflow.detail = "等待计算结果，平台将自动跟踪后续处理"
                checkpoint(workflow, "wait_operator", {"computeTaskId": str(task.id)})
        except PermissionDenied as exc:
            workflow.status, workflow.detail = "interrupted", str(exc)[:300]
        except (ComputeError, ValidationError) as exc:
            workflow.status, workflow.detail = "failed", str(exc)[:300]
        workflow.heartbeat = timezone.now()
        workflow.save()


def _collect(workflow, user, p, task):
    from apps.knowledge.services import check_constraints

    outputs = list(task.outputs.all())
    if not outputs:
        raise ComputeError("计算未提供任何有效输出")
    workflow.result_ids = [output.id for output in outputs]
    existing_check = workflow.steps.filter(kind="check_knowledge").first()
    if not existing_check:
        ids = [entry["id"] for entry in workflow.evidence]
        checks = {"findings": [], "checked": 0}
        for output in outputs:
            supplied = output.metadata.get("knowledgeFacts")
            if supplied is not None and not isinstance(supplied, dict):
                raise ComputeError("计算结果的知识事实格式无效，已停止自动入库")
            result = (
                check_constraints(user, supplied or {}, entry_ids=ids)
                if ids
                else {"findings": [], "checked": 0}
            )
            checks["checked"] += result["checked"]
            checks["findings"].extend(
                {**finding, "outputId": output.id} for finding in result["findings"]
            )
        existing_check = step(
            workflow,
            "check_knowledge",
            message="已检查结果知识约束；缺少适用条件的规则保留待核验状态",
            output_refs=checks,
        )
    if any(
        finding["status"] == "conflict"
        for finding in existing_check.output_refs.get("findings", [])
    ):
        raise ComputeError(
            "结果存在知识冲突，已保留原始输出；请调整参数或选择校正算法后重新计算，尚未自动入库"
        )
    if not workflow.import_results:
        workflow.status, workflow.current_step, workflow.detail = (
            "succeeded",
            "finalize",
            "计算完成，结果已保留",
        )
        return
    require_actor(user, workflow.project_tag_id, "catalog.add_dataresource")
    from apps.compute.quality import require_automatic_quality

    for output in outputs:
        require_automatic_quality(output)
    importable = [output for output in outputs if output.kind != "archive"]
    if not importable:
        raise ComputeError("结果均为压缩包，请下载后按文件类型分别入库")
    records = []
    for output in importable:
        record = ComputeImport.objects.filter(output=output).first()
        records.append(
            record
            or request_output_import(
                user, output, request_source=f"workflow:{workflow.id}"
            )
        )
    if any(record.status == "failed" for record in records):
        raise ComputeError("计算完成但入库失败，请到计算中心重试入库")
    workflow.current_step = "wait_import"
    workflow.detail = "计算完成，等待结果入库"
    if all(record.status == "ready" for record in records):
        workflow.result_resource_ids = [record.resource_id for record in records]
        workflow.status, workflow.current_step = "succeeded", "finalize"
        workflow.detail = f"{len(records)} 项结果已入库" + (
            "；压缩包保留供下载" if len(importable) != len(outputs) else ""
        )
        step(
            workflow,
            "finalize",
            message=workflow.detail,
            output_refs={
                "resourceIds": workflow.result_resource_ids,
                "outputIds": workflow.result_ids,
            },
        )
        checkpoint(workflow, "finalize", {"resourceIds": workflow.result_resource_ids})


def resume_waiting():
    from .compute_tools import authorized_task
    from apps.compute.services import task_action

    count = 0
    for workflow in AgentWorkflow.objects.filter(status="waiting_compute")[:30]:
        from .demo_workflow import DEMO_TYPES, advance_demo

        if workflow.workflow_type in DEMO_TYPES:
            advance_demo(workflow.id)
            count += 1
            continue
        with project_scope(_scope(workflow)):
            try:
                user, p = _authorize(workflow)
                current = (
                    workflow.steps.filter(kind="submit_operator")
                    .order_by("-sequence")
                    .first()
                )
                if not current or not current.compute_task_id:
                    raise ComputeError("缺少计算任务引用")
                task = authorized_task(user, current.compute_task_id, p)
                if workflow.cancel_requested:
                    if task.status in {"queued", "validating", "running"}:
                        task_action(task, user, "cancel")
                    workflow.status, workflow.detail = (
                        "cancelled",
                        "已停止工作流后续处理",
                    )
                elif not p.get("operatorEnabled", False):
                    raise PermissionDenied("自动执行及入库策略已关闭")
                elif task.status in {"queued", "validating", "running", "cancelling"}:
                    workflow.detail = "计算中心：" + task.stage
                elif task.status != "succeeded":
                    raise ComputeError("计算未成功：" + task.status)
                else:
                    _collect(workflow, user, p, task)
            except PermissionDenied as exc:
                workflow.status, workflow.detail = "interrupted", str(exc)[:300]
            except (ComputeError, ValidationError) as exc:
                workflow.status, workflow.detail = "failed", str(exc)[:300]
            workflow.heartbeat = timezone.now()
            workflow.save()
            count += 1
    return count
