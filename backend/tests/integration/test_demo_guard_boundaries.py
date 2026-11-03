"""Execution never reuses a successful stream poll as authorization to submit."""

# ruff: noqa: F811

from unittest.mock import patch

from django.core.exceptions import PermissionDenied
import pytest

from apps.agent.demo_workflow import (
    _submit_stage,
    authorize_demo,
    confirm_demo,
    prepare_demo,
)
from apps.agent.model_guard import ModelStreamGuard
from apps.agent.workflow import _authorize
from apps.compute.models import ComputeTask
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
