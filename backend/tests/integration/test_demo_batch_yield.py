"""A worker tick saves at most one new batch and preserves live controls."""

# ruff: noqa: F811

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.exceptions import PermissionDenied

from apps.agent import demo_workflow
from apps.agent.demo_workflow import advance_demo
from apps.agent.models import AgentWorkflow
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401
from tests.integration.test_demo_decision_retry import retry_model  # noqa: F401
from tests.integration.test_demo_decision_batches import provider_fixture, scenario

pytestmark = pytest.mark.django_db


@pytest.fixture
def batched_workflow(demo, retry_model, monkeypatch):
    def create(count=257, *, limit=10, future_stages=0):
        template, _, results = scenario(count)
        plan = copy.deepcopy(template.plan)
        plan.update(stageIndex=1, phase="decide", inputs={}, actualModelCallCount=1)
        plan["stages"][0].update(status="completed", decision={"checked": True})
        plan["stages"].extend(
            {"name": f"later-{index}", "identifier": f"later-{index}"}
            for index in range(future_stages)
        )
        workflow = AgentWorkflow.objects.create(
            owner=demo["owner"],
            project_tag=demo["project"],
            model=template.model,
            workflow_type=template.workflow_type,
            goal=template.goal,
            evidence=template.evidence,
            plan=plan,
            status="queued",
            iteration=1,
            max_iterations=limit,
            max_operator_steps=12,
            execute_operators=True,
        )
        return workflow, results

    monkeypatch.setattr(
        demo_workflow, "_authorize", lambda workflow: (demo["owner"], demo["policy"])
    )
    monkeypatch.setattr(demo_workflow, "authorize_demo", Mock())
    monkeypatch.setattr(
        demo_workflow,
        "authorized_task",
        lambda *args, **kwargs: SimpleNamespace(status="succeeded"),
    )
    monkeypatch.setattr("apps.agent.demo_decisions.resource_context", lambda *args: [])
    monkeypatch.setattr("apps.agent.demo_results.resource_context", lambda *args: [])
    monkeypatch.setattr(
        "apps.agent.demo_decisions.provider.model_window", lambda *args: 65536
    )
    monkeypatch.setattr("apps.agent.context.count_tokens", lambda *args: 800)

    def freeze(workflow, stage):
        workflow.status = "waiting_approval"
        workflow.plan["phase"] = "review_modifications"
        workflow.plan["modificationReview"] = {
            "suggestions": stage["edits"],
            "approvedSuggestionIds": [],
        }

    monkeypatch.setattr("apps.agent.geology_multi_review.freeze_proposal", freeze)
    return create


def wire_results(monkeypatch, results, requests, seen):
    monkeypatch.setattr(demo_workflow, "read_results", lambda *args: results)
    stream = provider_fixture(requests, seen)
    monkeypatch.setattr("apps.agent.demo_decisions.provider.stream", stream)
    return stream


def test_each_tick_completes_one_batch_with_fresh_deadline_and_exact_durable_counts(
    batched_workflow, monkeypatch
):
    workflow, results = batched_workflow()
    requests, seen, now = [], [], [0.0]
    stream = wire_results(monkeypatch, results, requests, seen)
    monkeypatch.setattr(demo_workflow.time, "monotonic", lambda: now[0])

    def slow_batch(*args, **kwargs):
        response = stream(*args, **kwargs)
        now[0] += 450
        args[3].poll()
        return response

    monkeypatch.setattr("apps.agent.demo_decisions.provider.stream", slow_batch)
    previous_attempts = []
    for tick in range(1, 4):
        advance_demo(workflow.id)
        workflow.refresh_from_db()
        state = workflow.plan["stages"][1]["modelBatches"]
        assert state["cursor"] == tick
        assert len(requests) == tick
        assert workflow.plan["actualModelCallCount"] == 1 + tick
        assert workflow.iteration == 2
        assert workflow.steps.filter(kind="analysis_model_attempt").count() == tick
        assert state["batches"][: tick - 1] == previous_attempts
        previous_attempts = copy.deepcopy(state["batches"])
        assert workflow.status == ("queued" if tick < 3 else "waiting_approval")
        assert ("decision" in workflow.plan["stages"][1]) is (tick == 3)
    assert len(seen) == len(set(seen)) == 257
    assert now[0] == 1350 > 2 * 600
    assert not workflow.plan["modificationReview"]["approvedSuggestionIds"]


@pytest.mark.parametrize("stage_index", [0, 1])
def test_initial_check_and_apply_keep_the_existing_per_tick_time_limit(
    batched_workflow, monkeypatch, stage_index
):
    workflow, results = batched_workflow()
    workflow.plan["stageIndex"] = stage_index
    workflow.plan["stages"][0].pop("decision")
    if stage_index == 0:
        workflow.plan["stages"][0].pop("taskId")
        workflow.plan["actualModelCallCount"] = workflow.iteration = 0
    workflow.save(update_fields=["plan", "iteration"])
    wire_results(monkeypatch, results, [], [])
    now, deadlines = [100.0], []
    monkeypatch.setattr(demo_workflow.time, "monotonic", lambda: now[0])

    def expire(current, user, policy, stage, actual_results, guard, *args, **kwargs):
        assert guard._deadline - now[0] == policy["maxRunSeconds"] == 600
        deadlines.append(guard._deadline)
        now[0] += 601
        guard.poll()
        raise AssertionError("An expired per-tick guard must stop analysis")

    monkeypatch.setattr(demo_workflow, "decide", expire)
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "failed" and "时限" in workflow.detail
    assert deadlines == [700.0]
    assert workflow.plan["actualModelCallCount"] == stage_index


@pytest.mark.parametrize("change", ["source", "response", "accepted_edits"])
def test_next_tick_revalidates_source_and_original_accepted_response_before_sending(
    batched_workflow, monkeypatch, change
):
    workflow, results = batched_workflow()
    requests, seen = [], []
    wire_results(monkeypatch, results, requests, seen)
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    if change == "source":
        results[0]["rows"][-1]["measurements_json"] = '{"area_m2":99999}'
    else:
        child = workflow.plan["stages"][1]["modelBatches"]["batches"][0]["stage"]
        if change == "response":
            child["modelAttempts"][0]["responseArtifact"]["content"] += "forged"
        else:
            child["edits"][0]["target_code"] = "forged"
        workflow.save(update_fields=["plan"])
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "failed"
    assert len(requests) == 1 and workflow.plan["actualModelCallCount"] == 2
    assert workflow.iteration == 2


def test_accepted_response_before_cursor_commit_recovers_without_reissuing_request(
    batched_workflow, monkeypatch
):
    workflow, results = batched_workflow()
    requests, seen = [], []
    wire_results(monkeypatch, results, requests, seen)
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    state = workflow.plan["stages"][1]["modelBatches"]
    state.update(cursor=0, coveredMemberCount=0)
    batch = state["batches"][0]
    batch["status"] = "pending"
    batch["stage"].pop("decision")
    batch["stage"].pop("edits")
    workflow.save(update_fields=["plan"])
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "queued"
    assert workflow.plan["stages"][1]["modelBatches"]["cursor"] == 1
    assert len(requests) == 1 and workflow.plan["actualModelCallCount"] == 2
    assert workflow.iteration == 2
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.plan["stages"][1]["modelBatches"]["cursor"] == 2
    assert len(requests) == 2 and workflow.plan["actualModelCallCount"] == 3
    assert workflow.iteration == 2


@pytest.mark.parametrize("control", ["pause", "cancel", "acl"])
def test_controls_at_durable_cursor_prevent_requeue_or_another_request(
    batched_workflow, monkeypatch, control
):
    workflow, results = batched_workflow()
    requests, seen, fired = [], [], [False]
    wire_results(monkeypatch, results, requests, seen)
    save = demo_workflow._save

    def controlled_save(current, **kwargs):
        save(current, **kwargs)
        state = current.plan["stages"][1].get("modelBatches", {})
        if not fired[0] and state.get("cursor") == 1:
            fired[0] = True
            if control == "acl":

                def revoked(*args):
                    raise PermissionDenied("当前访问权限已撤销")

                monkeypatch.setattr(demo_workflow, "_authorize", revoked)
            else:
                AgentWorkflow.objects.filter(pk=current.pk).update(
                    **{
                        "pause_requested"
                        if control == "pause"
                        else "cancel_requested": True
                    }
                )

    monkeypatch.setattr(demo_workflow, "_save", controlled_save)
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert (
        workflow.status
        == {"pause": "paused", "cancel": "cancelled", "acl": "interrupted"}[control]
    )
    assert workflow.plan["stages"][1]["modelBatches"]["cursor"] == 1
    assert len(requests) == 1 and workflow.plan["actualModelCallCount"] == 2
    advance_demo(workflow.id)
    assert len(requests) == 1
    if control == "pause":
        AgentWorkflow.objects.filter(pk=workflow.pk).update(
            status="queued", pause_requested=False, paused_from=""
        )
        advance_demo(workflow.id)
        workflow.refresh_from_db()
        assert workflow.plan["stages"][1]["modelBatches"]["cursor"] == 2
        assert len(requests) == 2 and workflow.plan["actualModelCallCount"] == 3
        assert workflow.iteration == 2


def test_repair_reserves_remaining_planned_batches_and_future_stages_without_sending(
    batched_workflow, monkeypatch
):
    # Check1 + five apply batches + three later stages + finish1 = limit10;
    # the first rejected response consumes the only slot for its current batch.
    workflow, results = batched_workflow(541, future_stages=3)
    requests, seen = [], []
    stream = wire_results(monkeypatch, results, requests, seen)

    def invalid_first(*args, **kwargs):
        value = json.loads(next(stream(*args, **kwargs)))
        value["edits"][0]["group_id"] = "not-an-actual-group"
        return iter([json.dumps(value)])

    monkeypatch.setattr("apps.agent.demo_decisions.provider.stream", invalid_first)
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert (
        workflow.status == "waiting_approval"
        and workflow.plan["phase"] == "budget_exhausted"
    )
    assert len(requests) == 1 and workflow.plan["actualModelCallCount"] == 2
    summary = workflow.plan["budgetExhausted"]
    assert summary["minimumRemainingRequests"] == 9 and summary["limit"] == 10
    assert summary["usedRequests"] + summary["minimumRemainingRequests"] == 11
    child = workflow.plan["stages"][1]["modelBatches"]["batches"][0]["stage"]
    assert (
        child["modelAttempts"][0]["requested"]
        and child["modelAttempts"][0]["status"] == "rejected"
    )
    assert child["modelAttempts"][1]["requested"] is False
    assert child["modelAttempts"][1]["status"] == "budget_blocked"
    assert len(child["modelAttempts"]) == 2
