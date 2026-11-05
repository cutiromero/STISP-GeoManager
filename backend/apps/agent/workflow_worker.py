"""Queue worker for durable research workflows."""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

from django.db import OperationalError, close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

from .models import AgentRuntime, AgentWorkflow
from .workflow import resume_waiting, run_workflow

logger = logging.getLogger(__name__)


def claim():
    with transaction.atomic():
        AgentRuntime.objects.update_or_create(
            name="workflow-queue", defaults={"heartbeat": timezone.now()}
        )
        candidate = (
            AgentWorkflow.objects.select_for_update()
            .filter(status="queued", cancel_requested=False, pause_requested=False)
            .order_by("created_at")
            .first()
        )
        if not candidate:
            return None
        candidate.status = "running"
        candidate.heartbeat = timezone.now()
        candidate.save(update_fields=["status", "heartbeat", "updated_at"])
        return candidate.id


def recover():
    stale = timezone.now() - timedelta(seconds=90)
    # Cancelled queue entries cannot be claimed. A worker may also have died
    # after the API requested cancellation, so finish the existing cancellation
    # path before requeueing stale work or releasing its compute slot.
    cancelled = AgentWorkflow.objects.filter(cancel_requested=True).filter(
        Q(status="queued") | Q(status="running", heartbeat__lt=stale)
    )
    for workflow in cancelled:
        from .demo_workflow import DEMO_TYPES

        workflow.pause_requested = False
        workflow.heartbeat = timezone.now()
        if (
            workflow.workflow_type not in DEMO_TYPES
            and workflow.steps.filter(
                kind="submit_operator", compute_task_id__isnull=False
            ).exists()
        ):
            # resume_waiting owns ordinary-workflow compute cancellation.
            workflow.status = "waiting_compute"
        workflow.save(
            update_fields=["status", "pause_requested", "heartbeat", "updated_at"]
        )
        if workflow.status != "waiting_compute":
            run_workflow(workflow.id)
    # A waiting compute task is durable: the next worker tick can observe its
    # terminal state and resume the workflow.  Marking it interrupted here
    # would restart the graph and could submit the same operator twice.
    AgentWorkflow.objects.filter(
        status="running",
        heartbeat__lt=stale,
        pause_requested=True,
        cancel_requested=False,
    ).update(
        status="paused",
        paused_from="running",
        detail="已暂停，可从已保存步骤继续",
        updated_at=timezone.now(),
    )
    AgentWorkflow.objects.filter(
        status="running",
        heartbeat__lt=stale,
        pause_requested=False,
        cancel_requested=False,
    ).update(status="queued", detail="正在从已保存计划恢复", updated_at=timezone.now())


def serve(stop=None, once=False):
    stop = stop or threading.Event()
    while not stop.is_set():
        try:
            close_old_connections()
            recover()
            AgentRuntime.objects.update_or_create(
                name="workflow-worker", defaults={"heartbeat": timezone.now()}
            )
            resume_waiting()
            workflow_id = claim()
            if workflow_id:
                run_workflow(workflow_id)
            if once:
                break
        except OperationalError as exc:
            logger.warning(
                "workflow queue busy (%s, database code=%s); retrying next heartbeat",
                type(exc).__name__,
                getattr(exc.__cause__, "sqlite_errorname", "unavailable"),
            )
        except Exception:
            logger.exception("workflow worker tick failed")
        stop.wait(1)
    close_old_connections()


def run_once():
    serve(threading.Event(), once=True)
