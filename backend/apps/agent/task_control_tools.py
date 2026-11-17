"""Own-task controls; lifecycle actions never grant scientific approval."""

import hashlib
import json

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F

from apps.compute.models import ComputeTask
from apps.compute.packages import ComputeError
from apps.compute.services import task_action
from .models import AgentRun, AgentWorkflow, AgentWorkflowStep, AgentToolCall
from .policy import fresh_user, require_access
from .workflow_control_service import control_workflow


def workflow_summary(workflow):
    key = (
        "businessFlowControlEpoch"
        if isinstance(workflow.parameters.get("_businessFlow"), dict)
        else "platformControlEpoch"
    )
    return {
        "workflowId": str(workflow.pk),
        "projectId": workflow.project_tag_id,
        "workflowType": workflow.workflow_type,
        "name": str(
            workflow.parameters.get("_businessFlow", {}).get("name")
            or workflow.workflow_type
        )[:160],
        "createdAt": workflow.created_at.isoformat(),
        "status": workflow.status,
        "currentStep": workflow.current_step,
        "updatedAt": workflow.updated_at.isoformat(),
        "controlEpoch": workflow.policy_snapshot.get(key, 0),
        "pauseRequested": workflow.pause_requested,
        "cancelRequested": workflow.cancel_requested,
    }


def execute_tasks(run, user, policy, name, args, call):
    if name == "cancel_export_task":
        from apps.raster.services.jobs import request_export_cancel

        result = request_export_cancel(args["jobId"], user.pk)
        return result, [(None, result)]
    if name == "list_research_tasks":
        query = AgentWorkflow.objects.filter(
            owner=user, goal__icontains=args.get("query", "")
        ).order_by("created_at", "id")
        offset, limit = args.get("offset", 0), args.get("limit", 10)
        total = query.count()
        return {
            "items": [
                workflow_summary(item) for item in query[offset : offset + limit]
            ],
            "total": total,
            "nextOffset": offset + limit if offset + limit < total else None,
        }, []
    if name == "cancel_compute_task":
        task = ComputeTask.objects.filter(pk=args["taskId"], owner=user).first()
        if task is None:
            raise ComputeError("本人计算任务不存在或无权访问", 404)
        if AgentWorkflowStep.objects.filter(compute_task=task).exists():
            raise ComputeError(
                "该计算由科研任务调度，请停止所属科研任务，不能绕过其状态机"
            )
        task = task_action(task, user, "cancel")
        result = {
            "taskId": str(task.pk),
            "status": task.status,
            "stage": task.stage,
            "progress": task.progress,
            "detail": "取消已按真实任务状态处理；已完成的成果不会被删除",
        }
        return result, [(None, result)]
    workflow = AgentWorkflow.objects.filter(pk=args["workflowId"], owner=user).first()
    if workflow is None:
        raise ComputeError("本人科研任务不存在或无权访问", 404)
    if name == "get_research_task":
        # Summary contains no input IDs, scientific outputs or private trace.
        result = workflow_summary(workflow)
        return result, [(None, result)]
    key = (
        "control-"
        + hashlib.sha256(
            json.dumps(
                [str(workflow.pk), args["action"], args["expectedControlEpoch"]]
            ).encode()
        ).hexdigest()
    )
    with transaction.atomic():
        get_user_model().objects.filter(pk=user.pk, is_active=True).update(
            last_login=F("last_login")
        )
        actor = fresh_user(user.pk)
        require_access(actor, "agent", run.model)
        if not AgentRun.objects.filter(
            pk=run.pk, cancel_requested=False, status="running"
        ).exists():
            raise ComputeError("本轮已停止，未控制其他科研任务", 409)
        prior = AgentToolCall.objects.filter(run=run, idempotency_key=key).first()
        if prior and prior.result_refs.get("workflowId"):
            current = AgentWorkflow.objects.get(pk=workflow.pk, owner=actor)
            result = {**workflow_summary(current), "replayed": True}
            return result, [(None, result)]
        AgentToolCall.objects.filter(pk=call.pk).update(idempotency_key=key)
        workflow = control_workflow(
            actor,
            workflow.pk,
            args["action"],
            actor_kind="agent",
            expected_epoch=args["expectedControlEpoch"],
            request_id=str(call.pk),
        )
        result = workflow_summary(workflow)
        AgentToolCall.objects.filter(pk=call.pk).update(
            result_refs={
                "workflowId": str(workflow.pk),
                "controlEpoch": result["controlEpoch"],
            }
        )
    return result, [(None, result)]
