"""Reuse verified ecology calculations when adding observational evidence."""

from __future__ import annotations

import math
from datetime import date
from uuid import UUID

from django.core.exceptions import PermissionDenied

from apps.compute.models import ComputeImport, ComputeOutput
from apps.compute.packages import ComputeError
from .compute_tools import authorized_task
from .demo_results import read_output, read_results, resource_context
from .models import AgentWorkflow
from .workflow_resources import resolve_workflow_resource
from .workflow import _state_hash

FIXED_ROLES = ("early_image", "late_image", "valid_mask", "zones")


def _chain(workflow, user, policy, *, history=False) -> list:
    from .demo_workflow import authorize_demo

    identity = workflow.plan.get("previousWorkflowId")
    chain, seen = [], {workflow.id}
    while identity:
        try:
            identity = UUID(str(identity))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ComputeError("前次分析标识无效") from exc
        if identity in seen or len(chain) >= 8:
            raise ComputeError("前次分析引用循环或更新层数超过8层")
        seen.add(identity)
        previous = AgentWorkflow.objects.filter(
            pk=identity,
            owner_id=user.id,
            project_tag_id=workflow.project_tag_id,
            workflow_type="ecology_investigation",
            status="succeeded",
        ).first()
        if previous is None:
            raise PermissionDenied("前次分析尚未完成或不属于当前用户与项目")
        authorize_demo(previous, user, policy, include_previous=False, history=history)
        chain.append(previous)
        identity = previous.plan.get("previousWorkflowId")
    return chain


def _context(workflow, user, policy) -> dict:
    return next(
        item
        for item in resource_context(workflow, user, policy)
        if item["role"] == "context"
    )


def _evidence_rows(context) -> dict:
    rows = {}
    for raw in context["rows"]:
        row = {
            key: str(value) if value is not None else "" for key, value in raw.items()
        }
        key = (row.get("zone_id", ""), row.get("evidence_id", ""))
        if not all(key) or key in rows:
            raise ComputeError("观测表需唯一且完整的分区与证据编号")
        rows[key] = row
    return rows


def _difference(previous, workflow, user, policy) -> dict:
    old, new = _context(previous, user, policy), _context(workflow, user, policy)
    if old["resourceId"] == new["resourceId"]:
        raise ComputeError("更新分析需选择包含新增证据的新观测资料")
    before, after = _evidence_rows(old), _evidence_rows(new)
    if any(after.get(key) != row for key, row in before.items()):
        raise ComputeError("新增证据资料改动或删除了旧观测，请保留原记录")
    added = [row for key, row in after.items() if key not in before]
    if not added:
        raise ComputeError("新观测资料没有新增证据记录")
    for row in added:
        try:
            confidence = float(row["confidence"])
            observed = date.fromisoformat(row["date"])
            early = date.fromisoformat(workflow.parameters["early_date"])
            late = date.fromisoformat(workflow.parameters["late_date"])
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError
            if not early <= observed <= late or not row.get("source"):
                raise ValueError
        except (ValueError, KeyError, TypeError) as exc:
            raise ComputeError("新增观测需来源、有效置信度及分析时段内的日期") from exc
    return {
        "oldContext": {key: old[key] for key in ("resourceId", "title", "revision")},
        "newContext": {key: new[key] for key in ("resourceId", "title", "revision")},
        "oldContextChecksum": _state_hash(old["rows"]),
        "newContextChecksum": _state_hash(new["rows"]),
        "addedEvidence": added,
    }


def _semantics(previous, workflow, chain) -> None:
    if any(
        previous.plan["inputs"][key] != workflow.plan["inputs"][key]
        for key in FIXED_ROLES
    ):
        raise ComputeError("证据更新须保留同一两期影像、有效掩膜与调查分区")
    for key in ("early_date", "late_date", "red", "nir"):
        if workflow.parameters.get(key) != previous.parameters.get(key):
            raise ComputeError("日期或波段发生变化，请重新运行完整分析")
    origin = chain[-1]
    for stage in origin.plan["stages"]:
        if stage["name"] not in {"early_ndvi", "late_ndvi", "change"}:
            continue
        specs = origin.plan["algorithms"][stage["identifier"]]["manifest"]["parameters"]
        defaults = {spec["key"]: spec.get("default") for spec in specs}
        for key, value in stage["parameters"].items():
            if workflow.parameters.get(key, defaults.get(key)) != value:
                raise ComputeError("影像或变化计算参数发生变化，请重新运行完整分析")


def _change(chain, user, policy) -> dict:
    origin = chain[-1]
    stage = next(
        (item for item in origin.plan["stages"] if item["name"] == "change"), None
    )
    saved = next(
        (item for item in (stage or {}).get("outputs", []) if item["key"] == "change"),
        None,
    )
    if not saved:
        raise ComputeError("前次分析没有已入库的实际变化栅格")
    output = ComputeOutput.objects.filter(
        pk=saved["outputId"], task_id=stage["taskId"], key="change", kind="raster"
    ).first()
    resource = resolve_workflow_resource(user, policy, saved["resourceId"], origin)
    if (
        output is None
        or not ComputeImport.objects.filter(
            output=output, resource=resource, status="ready"
        ).exists()
    ):
        raise PermissionDenied("前次变化资源不再对应已完成的真实输出")
    read_output(origin, user, policy, output)
    if (
        output.checksum != saved["checksum"]
        or resource.updated_at.isoformat() != saved["resourceRevision"]
    ):
        raise PermissionDenied("前次变化栅格来源或内容已变化")
    return {**saved, "taskId": stage["taskId"], "workflowId": str(origin.id)}


def previous_results(workflow, user, policy, chain=None) -> list[dict]:
    chain = chain if chain is not None else _chain(workflow, user, policy)
    results, seen = [], set()
    for previous in reversed(chain):
        for stage in previous.plan["stages"]:
            identity = stage.get("taskId")
            if identity and identity not in seen:
                seen.add(identity)
                results.extend(
                    read_results(
                        previous,
                        user,
                        policy,
                        authorized_task(user, identity, policy, workflow=previous),
                    )
                )
    return results


def prepare_update(workflow, user, policy) -> list:
    if workflow.workflow_type != "ecology_investigation":
        raise ComputeError("新增证据更新仅适用于生态调查")
    chain = _chain(workflow, user, policy)
    previous = chain[0]
    _semantics(previous, workflow, chain)
    change = _change(chain, user, policy)
    decision = previous.plan.get("finalDecision")
    if (
        not decision
        or not previous.steps.filter(
            kind="analysis_decision", action__decision=decision
        ).exists()
    ):
        raise ComputeError("前次分析缺少可核对的已保存判断")
    workflow.plan.update(
        previous_change=change["resourceId"],
        previousChange=change,
        previousAnalysis={
            "workflowId": str(previous.id),
            "oldDecision": decision,
            "previousPlanHash": previous.plan_hash,
            "actualResults": previous_results(workflow, user, policy, chain),
            **_difference(previous, workflow, user, policy),
        },
    )
    return [
        (
            "priority",
            "ecology-priority",
            {"change": "previous_change", "zones": "zones", "context": "context"},
        )
    ]


def authorize_update(workflow, user, policy) -> None:
    chain = _chain(workflow, user, policy)
    previous = chain[0]
    _semantics(previous, workflow, chain)
    analysis = workflow.plan["previousAnalysis"]
    if (
        _change(chain, user, policy) != workflow.plan["previousChange"]
        or previous.plan_hash != analysis["previousPlanHash"]
    ):
        raise PermissionDenied("前次分析或变化结果引用已变化")
    if _difference(previous, workflow, user, policy) != {
        key: analysis[key]
        for key in (
            "oldContext",
            "newContext",
            "oldContextChecksum",
            "newContextChecksum",
            "addedEvidence",
        )
    }:
        raise PermissionDenied("新增或旧观测表内容已变化，请重新生成更新计划")
    previous_results(workflow, user, policy, chain)
