"""Graph orchestration preserves batch progress across an explicit budget review."""

# ruff: noqa: F811

from unittest.mock import patch
import json

import pytest

from apps.agent.decision_budget import budget_review
from apps.agent.demo_workflow import advance_demo, confirm_demo, prepare_demo
from apps.agent.demo_decisions import decide
from apps.agent.policy import default_policy
from apps.agent.workflow_controls import WorkflowPaused
from apps.compute.models import ComputeTask
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_edit_context import model_response
from tests.integration.test_demo_decision_batches import (
    provider_fixture,
    run as run_batches,
    scenario as batch_scenario,
)
from tests.integration.test_demo_decision_retry import retry_model  # noqa: F401
from tests.integration.test_demo_workflow import demo, scenario  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("progress", ["empty", "blocked", "completed"])
def test_batch_budget_review_reserves_one_decision_and_keeps_response_audit(
    demo, progress
):
    completed_batch = progress == "completed"
    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    workflow.max_iterations = 1
    workflow.save(update_fields=["max_iterations"])

    def save_response(stage, on_attempt, on_response):
        child = stage["modelBatches"]["batches"][0]["stage"]
        if not child.get("modelAttempts"):
            attempt = {
                "attempt": 1,
                "batchIndex": 0,
                "status": "requesting",
                "requestSha256": "a" * 64,
                "inputTokens": 100,
                "contentBytes": 100,
                "usage": {},
            }
            child["modelAttempts"] = [attempt]
            on_attempt(attempt)
            attempt["status"] = "response_received"
        else:
            attempt = child["modelAttempts"][0]
        on_response(attempt)
        attempt.update(status="accepted", accepted=True)
        on_attempt(attempt)
        stage["modelBatches"]["cursor"] = 1

    def need_review(workflow, user, policy, stage, results, guard, on_attempt, **hooks):
        stage["modelBatches"] = {
            "sourceSha256": "b" * 64,
            "cursor": 0,
            "batches": [{"stage": {}}],
        }
        if completed_batch:
            save_response(stage, on_attempt, hooks["on_response"])
        elif progress == "blocked":
            stage["modelBatches"]["batches"][0]["stage"]["modelAttempts"] = [
                {"attempt": 1, "status": "budget_blocked", "requested": False}
            ]
        budget_review(stage, {"completeEvidence": True}, "下一批必要证据超出预算")

    with patch("apps.agent.demo_workflow.decide", side_effect=need_review):
        advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval"
    assert workflow.iteration == int(completed_batch)
    assert workflow.plan.get("actualModelCallCount", 0) == int(completed_batch)
    assert not ComputeTask.objects.exists()
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)

    def resume(workflow, user, policy, stage, results, guard, on_attempt, **hooks):
        child = stage["modelBatches"]["batches"][0]["stage"]
        if progress == "blocked":
            child["unrequestedBudgetAttempts"] = child.pop("modelAttempts")
        save_response(stage, on_attempt, hooks["on_response"])
        return model_response(stage["identifier"], [])["decision"], []

    with patch("apps.agent.demo_workflow.decide", side_effect=resume) as decide:
        advance_demo(workflow.id)
        advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert decide.call_count == 1
    assert workflow.status == "waiting_compute", workflow.detail
    assert workflow.iteration == workflow.plan["actualModelCallCount"] == 1
    assert ComputeTask.objects.count() == 1
    stage = workflow.plan["stages"][0]
    assert "modelAttempts" not in stage
    assert stage["modelBatches"]["cursor"] == 1
    attempt = stage["modelBatches"]["batches"][0]["stage"]["modelAttempts"][0]
    audit = workflow.steps.get(kind="analysis_model_attempt")
    assert attempt["accepted"] is True
    assert attempt["auditStepId"] == audit.id
    assert audit.action["batchIndex"] == 0
    assert audit.status == "succeeded"


def test_saved_batch_response_resumes_after_pause_without_resending(retry_model):
    workflow, stage, results = batch_scenario()
    requests, seen = [], []

    def record(attempt):
        if attempt["status"] == "requesting":
            workflow.plan["actualModelCallCount"] += 1
            attempt["requested"] = True

    def pause_after_response(attempt):
        if attempt["batchIndex"] == 2:
            assert attempt["status"] == "response_received"
            assert attempt["response"]
            raise WorkflowPaused()

    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch(
            "apps.agent.context.count_tokens",
            side_effect=lambda model, messages, *args: (
                sum(len(item["content"].encode()) for item in messages) // 4 + 64
            ),
        ),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=provider_fixture(requests, seen),
        ),
        pytest.raises(WorkflowPaused),
    ):
        decide(
            workflow,
            None,
            default_policy(),
            stage,
            results,
            lambda: None,
            record,
            pause_after_response,
        )
    assert len(requests) == workflow.plan["actualModelCallCount"] == 2
    assert stage["modelBatches"]["cursor"] == 1
    assert (
        stage["modelBatches"]["batches"][1]["stage"]["modelAttempts"][-1]["status"]
        == "response_received"
    )
    workflow.plan = json.loads(json.dumps(workflow.plan))
    stage = workflow.plan["stages"][1]
    decision, edits = run_batches(workflow, stage, results, requests, seen)
    assert decision["nextAction"] == "geology-multi-apply"
    assert len(edits) == len(seen) == len(set(seen)) == 257
    assert len(requests) == workflow.plan["actualModelCallCount"]
    assert len(requests) == stage["modelBatches"]["cursor"]
    assert (
        stage["modelBatches"]["batches"][1]["stage"]["recoveredResponseState"]
        == "validated_without_new_request"
    )
