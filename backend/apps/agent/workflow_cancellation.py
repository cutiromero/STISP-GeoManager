"""Stop admission immediately; terminate only this workflow's bound computation."""

from django.db import transaction
from django.utils import timezone

from apps.compute.models import ComputeTask, ComputeImport
from apps.compute.packages import ComputeError
from .models import AgentRun, WORKFLOW_ACTIVE
from .workflow_controls import locked_workflow


@transaction.atomic
def stop_workflow(workflow_id, owner_id):
    workflow = locked_workflow(workflow_id)
    if workflow.owner_id != owner_id:
        raise ComputeError("只能停止本人的任务", 403)
    if workflow.status not in {*WORKFLOW_ACTIVE, "cancelled"}:
        return workflow
    tasks = ComputeTask.objects.filter(
        pk__in=workflow.steps.exclude(compute_task_id=None).values_list(
            "compute_task_id", flat=True
        ),
        owner_id=owner_id,
        project_tag_id=workflow.project_tag_id,
    )
    now = timezone.now()
    tasks.filter(status="queued").update(
        status="cancelled", stage="已取消", finished_at=now, unread=True
    )
    running = tasks.filter(status__in=["validating", "running", "cancelling"])
    releasing = running.exists()
    running.update(status="cancelling", stage="正在停止计算")
    ComputeImport.objects.filter(
        output__task__in=tasks,
        requested_by_id=owner_id,
        request_source=f"workflow:{workflow.id}",
        status="queued",
    ).update(status="failed", error="任务已停止，尚未开始的成果入库已取消")
    AgentRun.objects.filter(
        research_workflow=workflow,
        owner_id=owner_id,
        project_tag_id=workflow.project_tag_id,
        status__in=["queued", "running", "waiting_compute"],
    ).update(cancel_requested=True)
    workflow.cancel_requested = True
    workflow.pause_requested = False
    workflow.status = "cancelled"
    workflow.detail = (
        "已停止后续处理，正在终止已提交计算；已有成果保留"
        if releasing
        else "任务已停止，已有成果保留"
    )
    workflow.save(
        update_fields=[
            "cancel_requested",
            "pause_requested",
            "status",
            "detail",
            "updated_at",
        ]
    )
    return workflow


def check_cancelled(workflow):
    from .models import AgentWorkflow

    state = (
        AgentWorkflow.objects.filter(pk=workflow.pk)
        .values("status", "cancel_requested")
        .first()
    )
    if state is None or state["cancel_requested"] or state["status"] == "cancelled":
        raise ComputeError("任务已停止", 409)
