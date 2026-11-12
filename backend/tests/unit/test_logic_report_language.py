import json
from types import SimpleNamespace

import pytest

from apps.agent.demo_decisions import _validate_response
from apps.compute.packages import ComputeError


@pytest.mark.parametrize(
    "text,reason",
    [
        ("采用试用或草稿规则", "正式发布"),
        ("由大模型调度全部算子", "没有模型执行规划记录"),
    ],
)
def test_report_rejects_internal_labels_or_unrecorded_model_claims(text, reason):
    ref = {"kind": "resource", "id": "1"}
    workflow = SimpleNamespace(
        evidence=[],
        workflow_type="geology_generic",
        plan={"executionPolicy": "rule_geology_v2", "stages": []},
    )
    value = {
        "decision": {
            "problem": "地质核查",
            "findings": [],
            "judgement": text,
            "uncertainties": [],
            "nextAction": "finish",
            "algorithmReason": "依据实际结果",
            "evidenceRefs": [ref],
            "resultSummary": "初检241条",
        },
        "edits": [],
    }
    with pytest.raises(ComputeError, match=reason):
        _validate_response(
            json.dumps(value),
            workflow,
            {"name": "final_analysis", "identifier": "finish"},
            [],
            [ref],
            model_payload={
                "availableEvidence": [ref],
                "ruleRegistration": [{"id": 10, "status": "published"}],
                "modelDispatchRecorded": False,
            },
        )


@pytest.mark.parametrize("text", ["本轮以确定性规则完成处置", "非模型逐项审阅"])
def test_style_guidance_does_not_reject_valid_report(text):
    ref = {"kind": "resource", "id": "1"}
    workflow = SimpleNamespace(
        evidence=[],
        workflow_type="geology_generic",
        plan={"executionPolicy": "rule_geology_v2", "stages": []},
    )
    decision, edits = _validate_response(
        json.dumps(
            {
                "decision": {
                    "problem": "核查",
                    "findings": [],
                    "judgement": text,
                    "uncertainties": [],
                    "nextAction": "finish",
                    "algorithmReason": "依据实际结果",
                    "evidenceRefs": [ref],
                    "resultSummary": "已完成核查",
                },
                "edits": [],
            }
        ),
        workflow,
        {"name": "final_analysis", "identifier": "finish"},
        [],
        [ref],
        model_payload={"availableEvidence": [ref]},
    )
    assert decision["judgement"] == text and edits == []
