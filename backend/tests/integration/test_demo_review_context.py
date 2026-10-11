"""Saved user approval is exposed precisely alongside unchanged quality evidence."""

# ruff: noqa: F811

import copy
import json
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.agent.demo_decisions import decide, decision_payload
from apps.agent.demo_workflow import advance_demo, confirm_demo, prepare_demo
from apps.agent.models import AgentWorkflow
from apps.agent.workflow import resume_waiting, step
from apps.compute.models import ComputeOutput
from apps.compute.packages import ComputeError, checksum
from apps.core.storage import app_path
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import (
    demo,  # noqa: F401
    finish_task,
    mark_imports_ready,
    scenario,
)


@pytest.fixture
def reviewed_geometry(demo):
    workflow = scenario(demo, "geology_correction")
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    advance_demo(workflow.id)
    finish_task(workflow)
    resume_waiting()
    mark_imports_ready(demo)
    resume_waiting()
    advance_demo(workflow.id)
    repaired = finish_task(workflow, review=True)
    task = repaired.task
    for key, kind in (("repair_summary", "table"), ("repair_audit", "archive")):
        path = app_path("outputs", str(task.id), key + ".csv")
        path.write_text(
            "area_before_trustworthy,area_change_pct\nFalse,0\n", encoding="utf-8"
        )
        ComputeOutput.objects.create(
            task=task,
            key=key,
            label=key,
            kind=kind,
            path=str(path.relative_to(app_path())),
            size_bytes=path.stat().st_size,
            file_name=path.name,
            checksum=checksum(path),
            metadata=copy.deepcopy(repaired.metadata),
        )
    resume_waiting()
    workflow.refresh_from_db()
    assert (
        workflow.status == "waiting_approval"
        and workflow.plan["phase"] == "review_results"
    )
    demo["review_workflow"] = workflow
    return demo


def payload(env, workflow=None):
    workflow = workflow or env["review_workflow"]
    results = copy.deepcopy(workflow.plan["stages"][1]["results"])
    return decision_payload(
        workflow,
        {"name": "final_analysis", "identifier": "finish"},
        [],
        results,
    )


def statuses(value):
    return {item["key"]: item for item in value["executionState"]["resultReviews"]}


def test_unapproved_result_scope_and_archive_are_explicit(reviewed_geometry):
    env = reviewed_geometry
    original = copy.deepcopy(env["review_workflow"].plan)
    records = statuses(payload(env))
    assert records["repaired"]["approvalStatus"] == "pending"
    assert records["repair_summary"]["approvalStatus"] == "pending"
    assert records["repair_audit"]["approvalStatus"] == "reference_only"
    assert all(
        item["originalQualityStatus"] == "needs_review" for item in records.values()
    )
    assert all(item["humanReviewStepSequences"] == [] for item in records.values())
    assert env["review_workflow"].plan == original


def test_real_confirmation_keeps_original_quality_and_exact_scope(reviewed_geometry):
    env = reviewed_geometry
    workflow = env["review_workflow"]
    result_before = copy.deepcopy(workflow.plan["stages"][1]["results"])
    confirm_demo(workflow, env["owner"], env["policy"], workflow.plan_hash)
    workflow.refresh_from_db()
    review = workflow.steps.get(kind="human_review")
    records = statuses(payload(env))
    for key in ("repaired", "repair_summary"):
        assert records[key]["approvalStatus"] == "approved"
        assert records[key]["humanReviewStepSequences"] == [review.sequence]
    assert records["repair_audit"]["approvalStatus"] == "reference_only"
    assert records["repair_audit"]["humanReviewStepSequences"] == []
    assert all(
        item["originalQualityStatus"] == "needs_review" for item in records.values()
    )
    assert workflow.plan["stages"][1]["results"] == result_before
    assert payload(env)["actualResults"] == result_before
    assert {item["outputId"] for item in review.action["approvedOutputs"]} == {
        item["outputId"] for key, item in records.items() if key != "repair_audit"
    }


@pytest.mark.parametrize(
    "missing",
    [
        "flag",
        "event",
        "empty_scope",
        "failed_event",
        "wrong_key",
        "wrong_kind",
        "other_workflow",
        "decision_only",
    ],
)
def test_approval_requires_flag_and_exact_successful_event(reviewed_geometry, missing):
    env = reviewed_geometry
    workflow = env["review_workflow"]
    confirm_demo(workflow, env["owner"], env["policy"], workflow.plan_hash)
    review = workflow.steps.get(kind="human_review")
    if missing == "flag":
        workflow.plan["stages"][1].pop("manualApproved")
    elif missing == "decision_only":
        workflow.plan["stages"][1].pop("manualApproved")
        workflow.plan["stages"][1]["decisionApproved"] = True
    elif missing == "event":
        review.delete()
    elif missing == "other_workflow":
        other = AgentWorkflow.objects.create(
            owner=env["owner"],
            model="mock",
            goal="独立审计",
            idempotency_key="separate-review",
            status="succeeded",
        )
        review.workflow = other
        review.save(update_fields=["workflow"])
    elif missing == "failed_event":
        review.status = "failed"
        review.save(update_fields=["status"])
    else:
        if missing == "empty_scope":
            review.action["approvedOutputs"] = []
        else:
            for item in review.action["approvedOutputs"]:
                item["key" if missing == "wrong_key" else "kind"] = "other"
        review.save(update_fields=["action"])
    records = statuses(payload(env))
    assert (
        records["repaired"]["approvalStatus"]
        == records["repair_summary"]["approvalStatus"]
        == "pending"
    )
    assert all(item["humanReviewStepSequences"] == [] for item in records.values())


def test_partial_review_does_not_approve_other_outputs_or_later_task(reviewed_geometry):
    env = reviewed_geometry
    workflow = env["review_workflow"]
    confirm_demo(workflow, env["owner"], env["policy"], workflow.plan_hash)
    review = workflow.steps.get(kind="human_review")
    review.action["approvedOutputs"] = review.action["approvedOutputs"][:1]
    review.save(update_fields=["action"])
    records = statuses(payload(env))
    assert records["repaired"]["approvalStatus"] == "approved"
    assert records["repair_summary"]["approvalStatus"] == "pending"
    results = copy.deepcopy(workflow.plan["stages"][1]["results"])
    later = {**copy.deepcopy(results[0]), "outputId": 987654, "taskId": "later-task"}
    workflow.plan["stages"].append(
        {
            "name": "later_check",
            "identifier": "geology-check",
            "taskId": "later-task",
            "results": [later],
        }
    )
    value = decision_payload(
        workflow,
        {"name": "final_analysis", "identifier": "finish"},
        [],
        results + [later],
    )
    later_state = next(
        item
        for item in value["executionState"]["resultReviews"]
        if item["outputId"] == later["outputId"]
    )
    assert (
        later_state["approvalStatus"] == "pending"
        and later_state["humanReviewStepSequences"] == []
    )
    # A task mismatch must never borrow the same stage's approval.
    results[0]["taskId"] = "unassigned-task"
    value = decision_payload(
        workflow, {"name": "final_analysis", "identifier": "finish"}, [], results
    )
    assert results[0]["outputId"] not in {
        item["outputId"] for item in value["executionState"]["resultReviews"]
    }
    old_results = copy.deepcopy(workflow.plan["stages"][1]["results"])
    workflow.plan["previousAnalysis"] = {"actualResults": old_results}
    old_only = decision_payload(
        workflow, {"name": "final_analysis", "identifier": "finish"}, [], old_results
    )
    assert old_only["executionState"]["resultReviews"] == []


@pytest.mark.parametrize("changed", [False, True])
def test_real_model_context_and_accepted_recovery_include_stable_review_scope(
    reviewed_geometry, settings, changed
):
    env = reviewed_geometry
    workflow = env["review_workflow"]
    confirm_demo(workflow, env["owner"], env["policy"], workflow.plan_hash)
    workflow.refresh_from_db()
    settings.AGENT_MODELS[0] = {**settings.AGENT_MODELS[0], "model_id": "qwen-fixture"}
    stage = {"name": "check", "identifier": "geology-check", "status": "pending"}
    results = copy.deepcopy(workflow.plan["stages"][1]["results"])
    answer = {
        "decision": {
            "problem": "核对已批准结果",
            "findings": ["用户已批准本步候选输出继续处理"],
            "judgement": "继续复核，保留原质量标记",
            "uncertainties": ["无效原面积基准需专业核对"],
            "nextAction": "geology-check",
            "algorithmReason": "实际审核后重新检查",
            "evidenceRefs": [{"kind": "output", "id": str(results[0]["outputId"])}],
            "resultSummary": "用户已审核，继续复核",
        },
        "edits": [],
    }
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=800),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            return_value=iter([json.dumps(answer)]),
        ) as stream,
    ):
        original = decide(
            workflow, env["owner"], env["policy"], stage, results, lambda: None
        )
    messages = stream.call_args.args[1]
    sent = json.loads(messages[-1]["content"])
    assert statuses(sent)["repaired"]["approvalStatus"] == "approved"
    assert (
        "area_change_pct=0" in messages[0]["content"]
        and "不能证明面积保真" in messages[0]["content"]
    )
    assert "不能继续写成等待用户审核" in messages[0]["content"]
    stage_before = copy.deepcopy(stage)
    workflow.iteration = 1
    workflow.plan["actualModelCallCount"] = 1
    workflow.save(update_fields=["plan", "iteration"])
    # New model audit and worker heartbeat cannot change review context/hash.
    step(workflow, "analysis_model_attempt", action={"accepted": True})
    workflow.status, workflow.heartbeat = "running", timezone.now()
    workflow.save(update_fields=["status", "heartbeat"])
    if changed:
        review = workflow.steps.get(kind="human_review")
        review.action["approvedOutputs"] = []
        review.save(update_fields=["action"])
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window") as window,
        patch("apps.agent.context.count_tokens") as tokens,
        patch("apps.agent.demo_decisions.provider.stream") as stream,
    ):
        if changed:
            with pytest.raises(ComputeError, match="本步已有模型请求记录"):
                decide(
                    workflow, env["owner"], env["policy"], stage, results, lambda: None
                )
        else:
            assert (
                decide(
                    workflow, env["owner"], env["policy"], stage, results, lambda: None
                )
                == original
            )
            assert stage["modelAttempts"] == stage_before["modelAttempts"]
        window.assert_not_called()
        tokens.assert_not_called()
        stream.assert_not_called()
