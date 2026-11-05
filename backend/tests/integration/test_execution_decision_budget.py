"""Later full-fact decisions use the configured window, while edits stay bounded."""

# ruff: noqa: F811

import copy
import json
from unittest.mock import patch

import pytest

from apps.agent.decision_budget import BudgetReviewRequired
from apps.agent.demo_decisions import decide
from apps.agent.policy import default_policy
from apps.compute.packages import ComputeError
from tests.integration.test_decision_input_budget import expand
from tests.integration.test_demo_decision_retry import (
    ordinary_stage,
    responses,
    retry_model,  # noqa: F401
)
from tests.integration.test_demo_edit_context import model_response


STAGES = [
    ("recheck", "geology-multi-check"),
    ("relations", "geology-multi-relations"),
    ("prospect", "geology-multi-prospect"),
    ("final_analysis", "finish"),
]


def context_for_stage(name, action):
    workflow, stage, _ = ordinary_stage()
    workflow.workflow_type = "geology_generic"
    workflow.plan["algorithms"] = {
        "geology-multi-check": {
            "manifest": {"outputs": [{"key": "alteration_summary"}]}
        }
    }
    stage.update(name=name, identifier=action)
    payload = {
        "stage": name,
        "allowedAction": action,
        "upstreamVersions": {},
        "knowledge": [],
        "actualResults": [
            {
                "key": "statistics",
                "outputId": 101,
                "taskId": "actual-task",
                "rows": [{"rule_id": f"R-{i}", "count": i} for i in range(80)],
                "rowCount": 80,
                "scope": "all",
                "metadata": {"warnings": ["需保留"]},
            }
        ],
        "executionState": {
            "currentStage": {"state": "not_submitted"},
            "currentRun": {"latestStatisticsOutputIds": [101]},
        },
        "editTask": None,
        "availableEvidence": [{"kind": "output", "id": "101"}],
    }
    return workflow, stage, payload


@pytest.mark.parametrize("name,action", STAGES)
def test_later_stage_projects_full_facts_before_using_selected_window(
    name, action, retry_model
):
    workflow, stage, payload = context_for_stage(name, action)
    original = copy.deepcopy(payload)
    answer = model_response(action, [])
    requests = []
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.decision_payload", return_value=payload),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=229120),
        patch("apps.agent.context.count_tokens", return_value=31000),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=responses([answer], requests),
        ),
        patch(
            "apps.agent.demo_decisions._validate_response",
            return_value=(answer["decision"], []),
        ),
    ):
        decide(workflow, None, default_policy(), stage, [], lambda: None)
    attempt = stage["modelAttempts"][0]
    assert attempt["inputTokens"] == 31000
    assert attempt["inputLimit"] == default_policy()["maxContextTokens"] == 49152
    assert attempt["budgetLevel"] >= 3
    sent = json.loads(requests[0][1]["content"])
    sent = expand(sent, sent["contextDefinitions"])
    assert (
        sent["executionEvidenceProjection"]["scope"]
        == "complete_read_facts_and_approval_groups"
    )
    table = sent["actualResults"][0]
    assert table["rows"] == [[f"R-{i}", i] for i in range(80)]
    assert table["metadata"]["warnings"] == ["需保留"]
    assert sent["executionState"]["currentStage"]["state"] == "not_submitted"
    assert payload == original


@pytest.mark.parametrize(
    "context_limit,window,output,bytes_limit",
    [
        (15000, 229120, 32768, 384000),
        (49152, 64000, 32768, 384000),
        (49152, 229120, 32768, 256),
    ],
)
def test_later_stage_never_exceeds_selected_tokens_real_window_or_bytes(
    context_limit,
    window,
    output,
    bytes_limit,
    retry_model,
):
    workflow, stage, payload = context_for_stage(*STAGES[0])
    policy = {
        **default_policy(),
        "maxContextTokens": context_limit,
        "maxOutputTokens": output,
        "maxContextBytes": bytes_limit,
    }
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.decision_payload", return_value=payload),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=window),
        patch("apps.agent.context.count_tokens", return_value=31000),
        patch("apps.agent.demo_decisions.provider.stream") as stream,
        pytest.raises(BudgetReviewRequired),
    ):
        decide(workflow, None, policy, stage, [], lambda: None)
    stream.assert_not_called()
    assert not stage.get("modelAttempts")


def test_later_stage_repairs_and_recovers_large_accepted_response_without_resending(
    retry_model,
):
    workflow, stage, payload = context_for_stage(*STAGES[1])
    answer = model_response(STAGES[1][1], [])
    requests = []

    def validate(raw, *args, **kwargs):
        if raw == "invalid-json":
            raise ComputeError("本次模型JSON无效")
        return answer["decision"], []

    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.decision_payload", return_value=payload),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=229120),
        patch("apps.agent.context.count_tokens", return_value=31000),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=responses(["invalid-json", answer], requests),
        ) as stream,
        patch("apps.agent.demo_decisions._validate_response", side_effect=validate),
    ):
        expected = decide(workflow, None, default_policy(), stage, [], lambda: None)
        assert stream.call_count == 2
        workflow.max_iterations = 20
        workflow.iteration = 3
        workflow.plan["actualModelCallCount"] = 2
        assert (
            decide(workflow, None, default_policy(), stage, [], lambda: None)
            == expected
        )
        assert stream.call_count == 2
        tampered = copy.deepcopy(stage)
        tampered["modelAttempts"][0]["budgetLevel"] = 0
        with pytest.raises(ComputeError, match="保留审计"):
            decide(workflow, None, default_policy(), tampered, [], lambda: None)
        assert stream.call_count == 2
    assert len(stage["modelAttempts"]) == 2
    assert all(a["inputLimit"] == 49152 for a in stage["modelAttempts"])


@pytest.mark.parametrize(
    "variant", ["initial", "other_family", "missing_scope", "member_batch"]
)
def test_initial_edits_and_unrecognized_context_keep_the_raster_ceiling(
    variant, retry_model
):
    workflow, stage, payload = context_for_stage(*STAGES[0])
    if variant == "initial":
        stage["name"] = payload["stage"] = "check"
    elif variant == "other_family":
        workflow.workflow_type = "ecology"
    elif variant == "missing_scope":
        payload.pop("upstreamVersions")
    else:
        payload["modelBatch"] = {"completeMembers": True}
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.decision_payload", return_value=payload),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=229120),
        patch("apps.agent.context.count_tokens", return_value=16000),
        patch("apps.agent.demo_decisions.provider.stream") as stream,
        pytest.raises(BudgetReviewRequired),
    ):
        decide(workflow, None, default_policy(), stage, [], lambda: None)
    stream.assert_not_called()
    assert "可用 15000" in stage["contextBudgetReview"]["reason"]
