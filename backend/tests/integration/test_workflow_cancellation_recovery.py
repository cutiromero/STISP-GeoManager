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


def test_fresh_cancelled_running_work_closes_immediately(demo):
    workflow = prepared(demo)
    assert claim() == workflow.id
    assert control(demo, workflow, "cancel").status_code == 200
    recover()
    workflow.refresh_from_db()
    assert workflow.status == "cancelled" and workflow.cancel_requested
    assert claim() is None
    assert not ComputeTask.objects.exists()


def test_stop_immediately_cancels_only_bound_compute_and_rejects_late_plan_save(demo):
    from copy import deepcopy
    from apps.agent.demo_workflow import advance_demo, _save

    workflow = prepared(demo)
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    original = deepcopy(workflow.plan)
    task = ComputeTask.objects.get()
    task.status = "running"
    task.save(update_fields=["status"])
    unrelated = ComputeTask.objects.create(
        owner=demo["owner"],
        name="独立计算",
        version=task.version,
        idempotency_key="independent-stop",
        request_hash="f" * 64,
    )
    response = control(demo, workflow, "cancel")
    assert response.status_code == 200
    assert (
        response.json()["status"] == "cancelled" and response.json()["view"] == "card"
    )
    task.refresh_from_db()
    unrelated.refresh_from_db()
    assert task.status == "cancelling" and unrelated.status == "queued"
    workflow.plan["phase"] = "late-worker-response"
    workflow.status = "running"
    _save(workflow)
    workflow.refresh_from_db()
    assert workflow.status == "cancelled" and workflow.plan == original
    assert control(demo, workflow, "cancel").json()["status"] == "cancelled"


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


def test_stop_skips_pending_workflow_imports_but_keeps_manual_imports(demo):
    from apps.agent.demo_workflow import advance_demo
    from apps.compute.models import ComputeOutput
    from tests.integration.test_demo_workflow import finish_task

    workflow = prepared(demo)
    advance_demo(workflow.id)
    output = finish_task(workflow)
    automatic = ComputeImport.objects.create(
        output=output,
        requested_by=demo["owner"],
        name="自动入库",
        request_source=f"workflow:{workflow.id}",
    )
    second = ComputeOutput.objects.create(
        task=output.task,
        key="manual-output",
        label="手动成果",
        kind=output.kind,
        path=output.path,
        file_name=output.file_name,
        checksum=output.checksum,
        size_bytes=output.size_bytes,
    )
    manual = ComputeImport.objects.create(
        output=second, requested_by=demo["owner"], name="手动入库", request_source=""
    )
    assert control(demo, workflow, "cancel").json()["status"] == "cancelled"
    automatic.refresh_from_db()
    manual.refresh_from_db()
    assert automatic.status == "failed" and "任务已停止" in automatic.error
    assert manual.status == "queued"


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
