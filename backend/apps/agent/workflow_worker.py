"""Queue worker for durable research workflows."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.db import OperationalError, close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

from .models import AgentRuntime, AgentWorkflow
from .workflow import resume_waiting, run_workflow

logger = logging.getLogger(__name__)

# Match the existing chat queue's bounded concurrency; each task keeps its agent.
MAX_ACTIVE_WORKFLOWS = 3


def claim(*, exclude=()):
    with transaction.atomic():
        AgentRuntime.objects.update_or_create(
            name="workflow-queue", defaults={"heartbeat": timezone.now()}
        )
        candidate = (
            AgentWorkflow.objects.select_for_update()
            .filter(status="queued", cancel_requested=False, pause_requested=False)
            .exclude(pk__in=exclude)
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


def _run_task(workflow_id, *, waiting=False):
    close_old_connections()
    try:
        if waiting:
            resume_waiting(workflow_id=workflow_id)
        else:
            run_workflow(workflow_id)
    finally:
        close_old_connections()


def serve(stop=None, once=False):
    stop = stop or threading.Event()
    futures = {}
    capacity = MAX_ACTIVE_WORKFLOWS
    with ThreadPoolExecutor(max_workers=capacity) as pool:
        while not stop.is_set():
            try:
                close_old_connections()
                for workflow_id, future in list(futures.items()):
                    if future.done():
                        del futures[workflow_id]
                        try:
                            future.result()
                        except Exception:
                            logger.exception("workflow task failed")
                # The scheduler remains alive while a task waits for its model.
                AgentWorkflow.objects.filter(pk__in=futures, status="running").update(
                    heartbeat=timezone.now()
                )
                recover()
                AgentRuntime.objects.update_or_create(
                    name="workflow-worker", defaults={"heartbeat": timezone.now()}
                )
                if once:
                    resume_waiting()
                    workflow_id = claim()
                    if workflow_id:
                        run_workflow(workflow_id)
                    break
                for _ in range(capacity - len(futures)):
                    workflow_id = claim(exclude=futures)
                    if not workflow_id:
                        break
                    futures[workflow_id] = pool.submit(_run_task, workflow_id)
                waiting = list(
                    AgentWorkflow.objects.filter(status="waiting_compute")
                    .exclude(pk__in=futures)
                    .order_by("updated_at")
                    .values_list("pk", flat=True)[: capacity - len(futures)]
                )
                for workflow_id in waiting:
                    futures[workflow_id] = pool.submit(
                        _run_task, workflow_id, waiting=True
                    )
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
