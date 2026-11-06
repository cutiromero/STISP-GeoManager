"""Execution never reuses a successful stream poll as authorization to submit."""

# ruff: noqa: F811

from unittest.mock import patch
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor

from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection
from django.utils import timezone
import pytest

from apps.agent.demo_workflow import (
    _submit_stage,
    authorize_demo,
    confirm_demo,
    prepare_demo,
)
from apps.agent.model_guard import ModelStreamGuard
from apps.agent.workflow import _authorize
from apps.compute.models import ComputeTask, RuntimeLease
from apps.compute.worker import pulse
from apps.knowledge.models import KnowledgeEntry
from apps.knowledge.services import serialize
from apps.projects.models import ProjectMembership
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo, scenario  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("change", ["knowledge", "membership"])
def test_submission_rechecks_live_permissions_even_with_a_cached_stream_poll(
    demo, change
):
    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    entry = KnowledgeEntry.objects.create(
        title="执行前需核对的专家知识",
        category="遥感",
        statement="核对实际输入",
        domain="remote_sensing",
        status="published",
    )
    workflow.evidence = [serialize(entry)]
    workflow.plan["knowledgeSelection"] = {
        "mode": "manual",
        "domains": ["remote_sensing"],
    }
    workflow.save(update_fields=["evidence", "plan"])

    def full_authorization():
        user, policy = _authorize(workflow)
        authorize_demo(workflow, user, policy)

    guard = ModelStreamGuard(full_authorization, 10, clock=lambda: 0)
    guard()
    if change == "knowledge":
        KnowledgeEntry.objects.filter(pk=entry.id).update(revision=entry.revision + 1)
    else:
        ProjectMembership.objects.filter(
            project=demo["project"], user=demo["owner"]
        ).delete()
    # The next tiny SSE frame may share its preceding successful check.
    guard()
    with (
        patch("apps.agent.demo_workflow.submit") as submit,
        pytest.raises(PermissionDenied),
    ):
        _submit_stage(
            workflow, demo["owner"], demo["policy"], workflow.plan["stages"][0]
        )
    submit.assert_not_called()
    assert not ComputeTask.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_slow_submission_preparation_keeps_the_compute_worker_lease_alive(demo):
    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    clock = [timezone.now()]
    calls = []

    def heartbeat():
        close_old_connections()
        try:
            pulse()
        finally:
            close_old_connections()

    def slow_preflight(*args, **kwargs):
        if not calls:
            calls.append(True)
            assert not connection.in_atomic_block
            # Production-sized result verification exceeds the 30-second lease.
            clock[0] += timedelta(seconds=45)
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(heartbeat).result(timeout=5)
            assert RuntimeLease.objects.get(pk="worker").heartbeat == clock[0]
        return authorize_demo(*args, **kwargs)

    with (
        patch("django.utils.timezone.now", side_effect=lambda: clock[0]),
        patch("apps.agent.demo_workflow.authorize_demo", side_effect=slow_preflight),
    ):
        _submit_stage(
            workflow, demo["owner"], demo["policy"], workflow.plan["stages"][0]
        )
    assert workflow.status == "waiting_compute"
    assert ComputeTask.objects.count() == 1
    assert workflow.steps.filter(kind="submit_operator").count() == 1


@pytest.mark.parametrize("change", ["membership", "cancel", "plan"])
def test_submission_rechecks_changes_after_preparation(demo, change):
    from apps.agent import demo_workflow
    from apps.agent.models import AgentWorkflow
    from apps.agent.provider import ModelError
    from apps.compute.packages import ComputeError

    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    resolve = demo_workflow.resolve_workflow_resource
    changed = []

    def change_after_preparation(*args, **kwargs):
        result = resolve(*args, **kwargs)
        if not changed:
            changed.append(True)
            if change == "membership":
                ProjectMembership.objects.filter(
                    project=demo["project"], user=demo["owner"]
                ).delete()
            elif change == "cancel":
                AgentWorkflow.objects.filter(pk=workflow.pk).update(
                    cancel_requested=True
                )
            else:
                AgentWorkflow.objects.filter(pk=workflow.pk).update(plan_hash="changed")
        return result

    with (
        patch(
            "apps.agent.demo_workflow.resolve_workflow_resource",
            side_effect=change_after_preparation,
        ),
        pytest.raises((PermissionDenied, ModelError, ComputeError)),
    ):
        _submit_stage(
            workflow, demo["owner"], demo["policy"], workflow.plan["stages"][0]
        )
    assert not ComputeTask.objects.exists()
