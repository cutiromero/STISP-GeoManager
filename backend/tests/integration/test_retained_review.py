from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from apps.agent.retained_review import (
    held_suggestions,
    open_initial_review,
    merge_selection,
    reopen,
)
from apps.compute.packages import ComputeError
from apps.agent.workflow import _state_hash


def fake():
    suggestions = [
        {
            "id": "auto",
            "status": "suggested",
            "featureId": "A",
            "ruleId": "L-01",
            "action": "set_code",
        },
        {
            "id": "held",
            "status": "review",
            "featureId": "H",
            "ruleId": "L-06",
            "candidateAction": "reclassify",
            "action": "reclassify",
        },
        {
            "id": "exception",
            "status": "exception",
            "featureId": "E",
            "ruleId": "S-04",
            "candidateAction": "exclude",
            "action": "exclude",
        },
    ]
    apply = {
        "name": "apply",
        "identifier": "geology-multi-apply",
        "status": "completed",
        "taskId": "old-apply",
        "bindings": {},
        "parameters": {},
        "decision": {},
        "edits": [],
        "proposedEdits": [],
        "modificationsApproval": {"mode": "rule_authorized"},
        "results": [
            {
                "key": "changes",
                "scope": "all",
                "rowCount": 1,
                "rows": [
                    {
                        "feature_id": "A",
                        "rule_id": "L-01",
                        "action": "set_code",
                        "actual_changed": True,
                    }
                ],
            }
        ],
    }
    plan = {
        "stages": [
            {"name": "check", "taskId": "check", "status": "completed"},
            apply,
            {"name": "recheck", "taskId": "old-recheck", "status": "completed"},
        ],
        "modificationReview": {
            "suggestions": suggestions,
            "proposalHash": "proposal",
            "approvedSuggestionIds": ["auto"],
        },
        "finalDecision": {"summary": "old"},
        "model_changes": 9,
    }
    return SimpleNamespace(
        id="workflow",
        owner_id=1,
        workflow_type="geology_generic",
        status="succeeded",
        plan=plan,
        plan_hash=_state_hash(plan),
        operator_steps=3,
        max_operator_steps=12,
        result_resource_ids=[3, 4],
        result_ids=[5],
    )


def test_actual_execution_filters_retained_not_approval():
    workflow = fake()
    workflow.plan["modificationReview"]["approvedSuggestionIds"].append("held")
    assert [s["id"] for s in held_suggestions(workflow.plan)] == ["held", "exception"]
    result = workflow.plan["stages"][1]["results"][0]
    result["rows"].append(
        {"feature_id": "H", "rule_id": "L-06", "actual_changed": True}
    )
    result["rowCount"] = 2
    assert [s["id"] for s in held_suggestions(workflow.plan)] == ["exception"]


def test_partial_changes_do_not_masquerade_as_remaining_scope():
    workflow = fake()
    workflow.plan["stages"][1]["results"][0]["rowCount"] = 10
    with pytest.raises(ComputeError, match="不完整"):
        held_suggestions(workflow.plan)


def test_automatic_flow_waits_only_for_held_items_and_defaults_to_none():
    workflow = fake()
    stage = workflow.plan["stages"][1]
    stage.pop("taskId")
    assert open_initial_review(workflow, stage, ["auto"])
    assert workflow.status == "waiting_approval"
    assert workflow.plan["retainedReview"]["candidateIds"] == ["held", "exception"]
    with patch("apps.agent.rule_dispositions.automatic_authorized", return_value=True):
        selected, proof = merge_selection(workflow, None, None, [])
        assert selected == ["auto"] and proof["manualSuggestionIds"] == []
        selected, proof = merge_selection(workflow, None, None, ["held"])
        assert selected == ["auto", "held"] and proof["manualSuggestionIds"] == ["held"]
        with pytest.raises(ComputeError, match="只能选择"):
            merge_selection(workflow, None, None, ["auto"])


def test_reopen_preserves_prior_round_and_only_resets_downstream():
    workflow = fake()
    old = deepcopy(workflow.plan)
    expected = workflow.plan_hash
    with (
        patch("apps.agent.workflow._authorize", return_value=(None, {})),
        patch("apps.agent.demo_workflow.authorize_demo"),
        patch(
            "apps.agent.geology_multi_review._fresh",
            return_value=(old["modificationReview"], []),
        ),
        patch("apps.agent.demo_workflow._save"),
        patch("apps.agent.workflow.step"),
        patch("apps.agent.workflow.checkpoint"),
    ):
        reopen(workflow, SimpleNamespace(id=1), {}, expected)
    assert workflow.plan["retainedReviewHistory"][0]["stages"] == old["stages"]
    assert workflow.plan["stages"][0] == old["stages"][0]
    assert "taskId" not in workflow.plan["stages"][1]
    assert workflow.plan["retainedReview"]["automaticSuggestionIds"] == ["auto"]
    assert workflow.result_resource_ids == [3, 4]
    assert workflow.status == "waiting_approval"
    assert "model_changes" not in workflow.plan
    assert workflow.max_operator_steps == 12


def test_completed_scope_cannot_be_reopened_with_stale_plan():
    with pytest.raises(ComputeError, match="变化"):
        reopen(fake(), SimpleNamespace(id=1), {}, "stale")
