"""User controls are independent of the model's mutable workflow plan."""

from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from .models import AgentWorkflow


class WorkflowPaused(Exception):
    """A safe checkpoint has acknowledged a user's durable pause request."""


def locked_workflow(workflow_id):
    # SQLite ignores select_for_update; reserve its writer before reading state.
    if connection.vendor == "sqlite":
        AgentWorkflow.objects.filter(pk=workflow_id).update(
            idempotency_key=F("idempotency_key")
        )
    return AgentWorkflow.objects.select_for_update().get(pk=workflow_id)


def apply_control_state(workflow, current, *, acknowledge_pause=False):
    workflow.cancel_requested = current.cancel_requested
    workflow.pause_requested = current.pause_requested
    workflow.paused_from = current.paused_from
    if current.cancel_requested or current.status == "cancelled":
        for name in (
            "plan",
            "plan_hash",
            "resource_ids",
            "evidence",
            "current_step",
            "execute_operators",
            "operator_steps",
            "iteration",
            "result_ids",
            "result_resource_ids",
            "algorithm_version_id",
            "parameters",
        ):
            setattr(workflow, name, getattr(current, name))
        workflow.status, workflow.detail = "cancelled", "已停止工作流后续处理"
        workflow.pause_requested = False
        return
    if current.pause_requested or current.status == "paused":
        continuation = workflow.status
        if current.status == "paused" and current.paused_from == "waiting_approval":
            # No in-flight model save can replace an already visible approval
            # gate, its candidate outputs, or its immutable confirmation hash.
            for name in (
                "plan",
                "plan_hash",
                "resource_ids",
                "evidence",
                "current_step",
                "execute_operators",
                "import_results",
                "operator_steps",
                "iteration",
                "result_ids",
                "result_resource_ids",
                "algorithm_version_id",
                "parameters",
            ):
                setattr(workflow, name, getattr(current, name))
            continuation = "waiting_approval"
        if continuation == "succeeded":
            continuation = "queued"
        elif continuation not in {
            "queued",
            "running",
            "waiting_compute",
            "waiting_approval",
        }:
            continuation = current.paused_from or "queued"
        # An in-flight result save can reach the next stage or an approval gate.
        workflow.paused_from = continuation
        workflow.pause_requested = True
        if (
            current.status == "running"
            and continuation == "running"
            and not acknowledge_pause
        ):
            workflow.status = "running"
            workflow.detail = "正在暂停；当前步骤到达保存点后停止后续处理"
            return
        workflow.status, workflow.detail = (
            "paused",
            "已暂停；已提交的计算继续完成，恢复后接着处理",
        )


def save_workflow_state(workflow, update_fields=None, *, acknowledge_pause=False):
    fields = update_fields or [
        "plan",
        "plan_hash",
        "resource_ids",
        "evidence",
        "status",
        "current_step",
        "detail",
        "execute_operators",
        "import_results",
        "operator_steps",
        "iteration",
        "result_ids",
        "result_resource_ids",
        "algorithm_version_id",
        "parameters",
    ]
    with transaction.atomic():
        current = locked_workflow(workflow.id)
        apply_control_state(workflow, current, acknowledge_pause=acknowledge_pause)
        workflow.heartbeat = timezone.now()
        workflow.save(
            update_fields=list(
                dict.fromkeys(
                    [
                        *fields,
                        "status",
                        "detail",
                        "pause_requested",
                        "paused_from",
                        "heartbeat",
                        "updated_at",
                    ]
                )
            )
        )


def check_pause(workflow):
    state = (
        AgentWorkflow.objects.filter(pk=workflow.id)
        .values("pause_requested", "status")
        .get()
    )
    if not state["pause_requested"] and state["status"] != "paused":
        return
    with transaction.atomic():
        current = locked_workflow(workflow.id)
        if not current.pause_requested and current.status != "paused":
            return
        apply_control_state(workflow, current, acknowledge_pause=True)
        # Publish paused in the caller's final save after unwinding its model
        # and transaction stack; resume cannot race the old worker's save.
    raise WorkflowPaused()
