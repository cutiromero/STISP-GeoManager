"""Queue worker for durable research workflows."""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

from django.db import OperationalError, close_old_connections, transaction
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
            .filter(status="queued", cancel_requested=False)
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
    # A waiting compute task is durable: the next worker tick can observe its
    # terminal state and resume the workflow.  Marking it interrupted here
    # would restart the graph and could submit the same operator twice.
    AgentWorkflow.objects.filter(status="running", heartbeat__lt=stale).update(
        status="queued", detail="正在从已保存计划恢复", updated_at=timezone.now()
    )


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
