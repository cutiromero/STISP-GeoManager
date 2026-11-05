"""Production batch planning reserves the frozen allowance before generation."""

import copy
import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied

from apps.agent.demo_workflow import advance_demo, confirm_demo
from apps.agent.models import AgentWorkflow
from apps.compute.models import ComputeTask
from apps.compute.packages import ComputeError
from tests.integration.test_demo_decision_batches import provider_fixture, scenario
from tests.integration.test_workflow_pause import control, prepared

pytestmark = pytest.mark.django_db
pytest_plugins = ["tests.integration.test_demo_workflow"]


def workflow_case(env, *, count=600, used=2, segment="all"):
    source, _, results = scenario(count)
    stages = source.plan["stages"]
    identity = str(uuid.uuid4())
    stages[0].update(taskId=identity, status="completed", results=results)
    for item in results:
        item["taskId"] = identity
    for name, identifier in [
        ("recheck", "geology-multi-check"),
        *(
            [
                ("relations", "geology-multi-relations"),
                ("prospect", "geology-multi-prospect"),
            ]
            if segment == "all"
            else []
        ),
    ]:
        stages.append({"name": name, "identifier": identifier})
    source.plan.update(
        inputs={}, stageIndex=1, actualModelCallCount=used, phase="decide"
    )
    workflow = AgentWorkflow.objects.create(
        owner=env["owner"],
        model="mock",
        workflow_type=source.workflow_type,
        goal=source.goal,
        evidence=source.evidence,
        max_iterations=10,
        max_operator_steps=16,
        iteration=1,
        execute_operators=True,
        plan=source.plan,
        idempotency_key="budget-preflight",
    )
    return workflow, results


@pytest.fixture
def planning(demo, settings):
    settings.AGENT_MODELS[0] = {**settings.AGENT_MODELS[0], "model_id": "qwen-fixture"}
    with (
        patch(
            "apps.agent.demo_workflow._authorize",
            return_value=(demo["owner"], demo["policy"]),
        ),
        patch(
            "apps.agent.workflow._authorize",
            return_value=(demo["owner"], demo["policy"]),
        ),
        patch("apps.agent.demo_workflow.authorize_demo"),
        patch(
            "apps.agent.demo_workflow.authorized_task",
            return_value=SimpleNamespace(id=uuid.uuid4()),
        ),
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_results.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch(
            "apps.agent.context.count_tokens",
            side_effect=lambda model, messages, *args: (
                sum(len(item["content"].encode()) for item in messages) // 4 + 64
            ),
        ),
    ):
        yield demo


def test_full_preflight_stops_before_first_batch_and_rejects_old_confirmation(planning):
    workflow, results = workflow_case(planning)
    with (
        patch("apps.agent.demo_workflow.read_results", return_value=results),
        patch("apps.agent.demo_decisions.provider.stream") as stream,
    ):
        advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "failed", workflow.detail
    assert workflow.plan["phase"] == "budget_exhausted"
    summary = workflow.plan["budgetExhausted"]
    stage = workflow.plan["stages"][1]
    preflight = stage["modelBatches"]["preflight"]
    assert len(preflight["batches"]) == 5
    assert summary["minimumRemainingRequests"] == 9  # five batches + four stages
    assert summary["usedRequests"] == 2 and summary["limit"] == 10
    assert workflow.iteration == 1
    assert stage["modelBatches"]["batches"] == []
    assert stage["modelBatches"]["cursor"] == 0
    assert not workflow.steps.filter(kind="analysis_model_attempt").exists()
    assert "调整并重新发起" in workflow.detail
    with pytest.raises(ComputeError, match="当前不能确认") as error:
        confirm_demo(
            workflow, planning["owner"], planning["policy"], workflow.plan_hash
        )
    assert error.value.status == 409
    advance_demo(workflow.id)
    assert not stream.called and not ComputeTask.objects.exists()


@pytest.mark.parametrize("segment,used,reserved", [("all", 1, 4), ("lithology", 3, 2)])
def test_exact_allowance_executes_the_frozen_ranges(planning, segment, used, reserved):
    workflow, results = workflow_case(planning, used=used, segment=segment)
    requests, seen = [], []

    def freeze(workflow, stage):
        workflow.status = "waiting_approval"
        workflow.plan.update(phase="review_modifications", modificationReview={})

    with (
        patch("apps.agent.demo_workflow.read_results", return_value=results),
        patch("apps.agent.geology_multi_review.freeze_proposal", side_effect=freeze),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=provider_fixture(requests, seen),
        ),
    ):
        advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval", workflow.detail
    stage = workflow.plan["stages"][1]
    state = stage["modelBatches"]
    assert len(requests) == len(state["preflight"]["batches"]) == 5
    assert len(seen) == len(set(seen)) == 600
    assert workflow.plan["actualModelCallCount"] == used + 5 == 10 - reserved
    assert [(item["start"], item["end"]) for item in state["batches"]] == [
        (item["start"], item["end"]) for item in state["preflight"]["batches"]
    ]
    assert all(item["inputTokens"] <= 15000 for item in state["preflight"]["batches"])
    assert all(item["outputLimit"] == 2000 for item in state["preflight"]["batches"])


@pytest.mark.parametrize("action", ["pause", "cancel", "revoke"])
def test_preflight_live_guard_stops_before_any_generation(planning, action):
    workflow, results = workflow_case(planning, used=0)
    before = copy.deepcopy(workflow.plan)
    changed = [False]

    def tokens(model, messages, *args):
        if not changed[0]:
            changed[0] = True
            if action == "revoke":
                return 800
            assert control(planning, workflow, action).status_code == 200
        return 800

    def authorize(*args, **options):
        if changed[0] and action == "revoke":
            raise PermissionDenied("资料授权已撤销")
        return planning["owner"], planning["policy"]

    # Force each loop poll to read durable state, independently of wall-clock speed.
    from apps.agent.model_guard import ModelStreamGuard

    class EagerGuard(ModelStreamGuard):
        __call__ = ModelStreamGuard.poll

    with (
        patch("apps.agent.demo_workflow.read_results", return_value=results),
        patch("apps.agent.demo_workflow._authorize", side_effect=authorize),
        patch("apps.agent.demo_workflow.ModelStreamGuard", EagerGuard),
        patch("apps.agent.context.count_tokens", side_effect=tokens),
        patch("apps.agent.demo_decisions.provider.stream") as stream,
    ):
        advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert (
        workflow.status
        == {
            "pause": "paused",
            "cancel": "cancelled",
            "revoke": "interrupted",
        }[action]
    ), workflow.detail
    assert workflow.plan["actualModelCallCount"] == before["actualModelCallCount"]
    assert workflow.iteration == 1
    assert not workflow.steps.filter(kind="analysis_model_attempt").exists()
    assert not stream.called and not ComputeTask.objects.exists()


def test_request_cap_failure_preserves_unsent_attempt_without_confirmation_loop(
    demo, settings
):
    workflow = prepared(demo)
    settings.AGENT_MODELS[0] = {**settings.AGENT_MODELS[0], "model_id": "qwen-fixture"}
    workflow.plan["actualModelCallCount"] = workflow.max_iterations
    workflow.save(update_fields=["plan"])
    with (
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=800),
        patch("apps.agent.demo_decisions.provider.stream") as stream,
    ):
        advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "failed" and workflow.plan["phase"] == "budget_exhausted"
    assert workflow.iteration == 0
    assert workflow.plan["actualModelCallCount"] == workflow.max_iterations
    attempt = workflow.plan["stages"][0]["modelAttempts"][-1]
    assert attempt["requested"] is False and attempt["status"] == "budget_blocked"
    assert workflow.steps.get(kind="analysis_model_attempt").status == "failed"
    assert not stream.called and not ComputeTask.objects.exists()
    assert json.loads(json.dumps(workflow.plan)) == workflow.plan
