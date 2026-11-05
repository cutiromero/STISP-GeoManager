"""A durable cancellation finishes before a restarted worker claims more work."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.agent.models import AgentWorkflow
from apps.agent.workflow import resume_waiting
from apps.agent.workflow_creation import create_workflow
from apps.agent.workflow_worker import claim, recover
from apps.compute.models import ComputeImport, ComputeTask
from tests.integration.test_workflow_pause import control, prepared

pytestmark = pytest.mark.django_db
pytest_plugins = ["tests.integration.test_demo_workflow"]


@pytest.mark.parametrize("status", ["queued", "running"])
@pytest.mark.parametrize("submitted", [False, True])
def test_cancelled_work_is_recovered_without_resubmission_and_releases_slot(
    demo, status, submitted
):
    workflow = prepared(demo)
    if submitted:
        from apps.agent.demo_workflow import advance_demo

        advance_demo(workflow.id)
    AgentWorkflow.objects.filter(pk=workflow.id).update(
        status=status,
        heartbeat=timezone.now() - timedelta(seconds=100),
        cancel_requested=True,
        pause_requested=True,
    )
    recover()
    resume_waiting()
    workflow.refresh_from_db()
    assert workflow.status == "cancelled"
    assert workflow.cancel_requested and not workflow.pause_requested
    assert not ComputeImport.objects.exists()
    assert ComputeTask.objects.count() == int(submitted)
    if submitted:
        assert ComputeTask.objects.get().status == "cancelled"
    recover()
    fresh = create_workflow(
        demo["owner"],
        demo["project"].id,
        {"goal": "恢复后新任务", "model": "mock", "idempotencyKey": "fresh-run"},
    )
    assert fresh.status == "queued"
    assert claim() == fresh.id


def test_fresh_cancelled_running_work_stays_with_its_inflight_worker(demo):
    workflow = prepared(demo)
    assert claim() == workflow.id
    assert control(demo, workflow, "cancel").status_code == 200
    recover()
    workflow.refresh_from_db()
    assert workflow.status == "running" and workflow.cancel_requested
    assert claim() is None
    assert not ComputeTask.objects.exists()


def test_stale_non_demo_cancellation_reuses_compute_tracking(demo):
    from apps.agent.demo_workflow import advance_demo

    workflow = prepared(demo)
    advance_demo(workflow.id)
    AgentWorkflow.objects.filter(pk=workflow.id).update(
        workflow_type="operator",
        status="running",
        heartbeat=timezone.now() - timedelta(seconds=100),
        cancel_requested=True,
    )
    recover()
    workflow.refresh_from_db()
    assert workflow.status == "waiting_compute"
    assert ComputeTask.objects.get().status == "queued"
    resume_waiting()
    workflow.refresh_from_db()
    assert workflow.status == "cancelled"
    assert ComputeTask.objects.get().status == "cancelled"
    assert not ComputeImport.objects.exists()


def test_stale_cancellation_does_not_cancel_an_unrelated_compute_task(demo):
    from apps.agent.demo_workflow import advance_demo

    workflow = prepared(demo)
    advance_demo(workflow.id)
    original = ComputeTask.objects.get()
    unrelated = ComputeTask.objects.create(
        owner=demo["owner"],
        name="独立计算",
        version=original.version,
        idempotency_key="unrelated-compute",
        request_hash="f" * 64,
    )
    AgentWorkflow.objects.filter(pk=workflow.id).update(
        status="running",
        heartbeat=timezone.now() - timedelta(seconds=100),
        cancel_requested=True,
    )
    recover()
    original.refresh_from_db()
    unrelated.refresh_from_db()
    assert original.status == "cancelled"
    assert unrelated.status == "queued"
    assert ComputeTask.objects.count() == 2
