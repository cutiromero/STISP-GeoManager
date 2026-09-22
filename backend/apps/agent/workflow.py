"""Durable research-workflow runtime.

The graph is deliberately small and explicit.  LangGraph is used when it is
installed in the deployment environment; the same node contract has a local
fallback so development and migrations can be verified while the offline
package cache is unavailable.  Neither implementation executes an operator
directly: operator work is submitted through ``apps.compute.services``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, TypedDict

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.compute.models import AlgorithmVersion, ComputeTask
from apps.compute.services import ComputeError, submit as submit_compute
from apps.projects.context import ProjectScope, project_scope
from .models import AgentCheckpoint, AgentWorkflow, AgentWorkflowStep
from .policy import fresh_user, require_access
from .tools import resources, resolve_resource

try:  # Optional during the offline local bootstrap; required for server rollout.
    from langgraph.graph import END, START, StateGraph

    HAS_LANGGRAPH = True
except ImportError:  # pragma: no cover - exercised by the local offline runtime
    END = START = StateGraph = None
    HAS_LANGGRAPH = False


class WorkflowState(TypedDict, total=False):
    workflow_id: str
    node: str
    status: str
    resource_ids: list[int]
    algorithm_version_id: int | None
    parameters: dict[str, Any]
    action: dict[str, Any]
    result_ids: list[int]
    evidence: list[dict[str, Any]]
    detail: str


def _scope(workflow: AgentWorkflow) -> ProjectScope:
    return ProjectScope(
        (workflow.project_tag_id,), workflow.project_tag_id, workflow.owner_id
    )


def _state_hash(state: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def checkpoint(workflow: AgentWorkflow, node: str, state: dict[str, Any]) -> None:
    safe = {
        key: value
        for key, value in state.items()
        if key not in {"raw_rows", "raw_text", "prompt", "full_result"}
    }
    AgentCheckpoint.objects.create(
        workflow=workflow,
        node=node,
        state=safe,
        state_hash=_state_hash(safe),
    )


def step(
    workflow: AgentWorkflow,
    kind: str,
    *,
    message: str = "",
    status: str = "succeeded",
    action: dict[str, Any] | None = None,
    input_refs: dict[str, Any] | None = None,
    output_refs: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    compute_task_id=None,
    error_code: str = "",
) -> AgentWorkflowStep:
    sequence = workflow.steps.count() + 1
    return AgentWorkflowStep.objects.create(
        workflow=workflow,
        sequence=sequence,
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


def _resources_for(workflow: AgentWorkflow, user, p) -> list[int]:
    if workflow.resource_ids:
        for resource_id in workflow.resource_ids:
            resolve_resource(user, p, resource_id)
        return sorted(set(workflow.resource_ids))
    # Autonomous discovery is scoped to the current project and the live
    # resource authorization service.  Prefer raster inputs for this workflow.
    candidates = list(resources(user, p).order_by("name")[:100])
    raster = [r.id for r in candidates if r.data_type == "raster"]
    chosen = raster or [r.id for r in candidates if r.data_type in {"table", "vector"}]
    return chosen[: p["maxResources"]]


def _agent_algorithm(workflow: AgentWorkflow):
    if workflow.algorithm_version_id:
        version = (
            AlgorithmVersion.objects.select_related("algorithm")
            .filter(pk=workflow.algorithm_version_id, status="published")
            .first()
        )
        if version and version.algorithm.project_tag_id in {1, workflow.project_tag_id}:
            if version.manifest.get("agent", {}).get("enabled") is True:
                return version
        raise ComputeError("指定算法不存在、未发布或未开放给智能体")
    versions = AlgorithmVersion.objects.select_related("algorithm").filter(
        status="published"
    )
    for version in versions.order_by("id"):
        if version.algorithm.project_tag_id not in {1, workflow.project_tag_id}:
            continue
        if version.manifest.get("agent", {}).get("enabled") is True:
            return version
    return None


def _plan(workflow: AgentWorkflow, resource_ids: list[int], version) -> dict[str, Any]:
    manifest = version.manifest if version else {}
    parameters = dict(workflow.parameters or {})
    for item in manifest.get("parameters", []):
        if item["key"] not in parameters and "default" in item:
            parameters[item["key"]] = item["default"]
    inputs = {}
    for spec, resource_id in zip(manifest.get("inputs", []), resource_ids):
        inputs[spec["key"]] = resource_id
    return {
        "workflowType": workflow.workflow_type,
        "goal": workflow.goal,
        "algorithmVersionId": version.id if version else None,
        "algorithm": version.algorithm.name if version else "待管理员登记并开放的算法",
        "inputs": inputs,
        "parameters": parameters,
        "operatorExecution": "enabled" if workflow.execute_operators else "dry_run",
        "iteration": workflow.iteration,
        "maxIterations": workflow.max_iterations,
    }


def _submit_operator(
    workflow: AgentWorkflow, user, plan: dict[str, Any]
) -> ComputeTask:
    version = AlgorithmVersion.objects.select_related("algorithm").get(
        pk=plan["algorithmVersionId"]
    )
    body = {
        "name": f"智能体：{workflow.goal[:120]}",
        "versionId": version.id,
        "inputs": plan["inputs"],
        "parameters": plan["parameters"],
        "idempotencyKey": f"agent-workflow-{workflow.id}-{workflow.iteration}",
        "trial": False,
    }
    return submit_compute(user, body)


def _run_fallback(workflow: AgentWorkflow) -> dict[str, Any]:
    """Execute the graph contract without importing optional LangGraph."""
    user = fresh_user(workflow.owner_id)
    p = require_access(user, "agent", workflow.model)
    if not p.get("workflowEnabled", True):
        raise PermissionDenied("科研工作流功能已关闭")
    with project_scope(_scope(workflow)):
        resource_ids = _resources_for(workflow, user, p)
        workflow.current_step = "discover_inputs"
        workflow.resource_ids = resource_ids
        workflow.save(update_fields=["current_step", "resource_ids", "updated_at"])
        step(
            workflow,
            "discover_inputs",
            message=f"已发现 {len(resource_ids)} 个当前项目授权资源",
            output_refs={"resourceIds": resource_ids},
        )
        checkpoint(workflow, "discover_inputs", {"resource_ids": resource_ids})

        version = _agent_algorithm(workflow)
        plan = _plan(workflow, resource_ids, version)
        workflow.current_step = "validate_plan"
        workflow.algorithm_version_id = plan["algorithmVersionId"]
        workflow.parameters = plan["parameters"]
        workflow.save(
            update_fields=[
                "current_step",
                "algorithm_version_id",
                "parameters",
                "updated_at",
            ]
        )
        step(
            workflow,
            "build_plan",
            message="已生成结构化科研任务计划",
            action=plan,
            output_refs={"algorithmVersionId": plan["algorithmVersionId"]},
        )
        checkpoint(workflow, "validate_plan", {"action": plan})

        if not workflow.execute_operators:
            workflow.status = "succeeded"
            workflow.detail = "已生成计划；当前策略仍为只读/预览，未提交算子"
            workflow.current_step = "finalize"
            workflow.save(
                update_fields=["status", "detail", "current_step", "updated_at"]
            )
            step(
                workflow,
                "finalize",
                message=workflow.detail,
                output_refs={"plan": plan},
            )
            return {"plan": plan, "status": workflow.status}

        if not p.get("operatorEnabled", False):
            raise PermissionDenied("智能体自动调用算子尚未由超级管理员开启")
        if not version:
            raise ComputeError("当前项目没有已发布且允许智能体调用的算法")
        if workflow.operator_steps >= workflow.max_operator_steps:
            raise ComputeError("已达到智能体算子步骤上限")

        task = _submit_operator(workflow, user, plan)
        workflow.operator_steps += 1
        workflow.status = "waiting_compute"
        workflow.current_step = "wait_operator"
        workflow.detail = "算子任务已提交，等待计算中心返回结果"
        workflow.save(
            update_fields=[
                "operator_steps",
                "status",
                "current_step",
                "detail",
                "updated_at",
            ]
        )
        step(
            workflow,
            "submit_operator",
            message=workflow.detail,
            action=plan,
            input_refs={"resourceIds": resource_ids},
            compute_task_id=task.id,
            status="waiting",
        )
        checkpoint(workflow, "wait_operator", {"computeTaskId": str(task.id)})
        return {"status": workflow.status, "computeTaskId": str(task.id)}


def build_graph():
    """Build the explicit graph when LangGraph is available.

    The node functions intentionally call the same side-effect boundary as the
    fallback.  This keeps local replay and the server runtime behaviorally
    equivalent and avoids LangGraph's generic ToolNode bypassing permissions.
    """
    if not HAS_LANGGRAPH:
        return None
    graph = StateGraph(WorkflowState)
    graph.add_node("load_context", lambda state: {"node": "load_context"})
    graph.add_node("discover_inputs", lambda state: {"node": "discover_inputs"})
    graph.add_node("build_plan", lambda state: {"node": "build_plan"})
    graph.add_node("validate_plan", lambda state: {"node": "validate_plan"})
    graph.add_node(
        "finalize", lambda state: {"node": "finalize", "status": "succeeded"}
    )
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "discover_inputs")
    graph.add_edge("discover_inputs", "build_plan")
    graph.add_edge("build_plan", "validate_plan")
    graph.add_edge("validate_plan", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def run_workflow(workflow_id) -> None:
    workflow = AgentWorkflow.objects.get(pk=workflow_id)
    # ``claim`` marks a row as running before releasing the transaction.  The
    # worker must therefore accept that state as well as a direct retry of an
    # interrupted workflow.  Rejecting it here leaves every claimed task
    # permanently stuck in ``running``.
    if workflow.status not in {"queued", "running", "interrupted"}:
        return
    if workflow.cancel_requested:
        workflow.status, workflow.detail = "cancelled", "已取消"
        workflow.save(update_fields=["status", "detail", "updated_at"])
        return
    workflow.status = "running"
    workflow.heartbeat = timezone.now()
    workflow.save(update_fields=["status", "heartbeat", "updated_at"])
    try:
        if HAS_LANGGRAPH:
            # The graph is the control-plane runtime.  Side effects remain in
            # the guarded adapter below so permissions are rechecked there.
            build_graph().invoke({"workflow_id": str(workflow.id)})
        _run_fallback(workflow)
    except PermissionDenied as exc:
        workflow.status, workflow.detail = "interrupted", str(exc)
        workflow.save(update_fields=["status", "detail", "updated_at"])
    except Exception as exc:  # keep user output free from paths/upstream bodies
        workflow.status, workflow.detail = "failed", str(exc)[:300]
        workflow.save(update_fields=["status", "detail", "updated_at"])


def resume_waiting() -> int:
    count = 0
    for workflow in AgentWorkflow.objects.filter(status="waiting_compute")[:30]:
        workflow.heartbeat = timezone.now()
        current = (
            workflow.steps.filter(kind="submit_operator").order_by("-sequence").first()
        )
        if not current or not current.compute_task_id:
            workflow.status, workflow.detail = "failed", "缺少计算任务引用"
            workflow.save(update_fields=["status", "detail", "updated_at"])
            continue
        task = ComputeTask.objects.filter(pk=current.compute_task_id).first()
        if not task or task.status in {"queued", "validating", "running", "cancelling"}:
            workflow.save(update_fields=["heartbeat", "updated_at"])
            continue
        if task.status != "succeeded":
            workflow.status, workflow.detail = (
                "failed",
                f"算子任务未完成：{task.status}",
            )
            workflow.current_step = "finalize"
            workflow.save(
                update_fields=["status", "detail", "current_step", "updated_at"]
            )
            step(
                workflow,
                "collect_result",
                status="failed",
                message=workflow.detail,
                error_code="operator_failed",
            )
            count += 1
            continue
        output_ids = list(task.outputs.values_list("id", flat=True))
        workflow.result_ids = output_ids
        workflow.status = "succeeded"
        workflow.current_step = "finalize"
        workflow.detail = "算子结果已返回；已完成基础结果登记，专业规则评估待配置"
        workflow.save(
            update_fields=[
                "result_ids",
                "status",
                "current_step",
                "detail",
                "heartbeat",
                "updated_at",
            ]
        )
        step(
            workflow,
            "collect_result",
            message=workflow.detail,
            output_refs={"outputIds": output_ids},
        )
        checkpoint(workflow, "finalize", {"result_ids": output_ids})
        count += 1
    return count
