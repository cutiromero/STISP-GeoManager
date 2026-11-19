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


@pytest.mark.parametrize("subject", ["新桥地区航测成果", "独立工作区 27 号岩性资料"])
def test_report_grounded_in_confirmed_source_not_knowledge_example(subject):
    from apps.agent.report_text import bound_report_scope, check_summary_scope

    old_area = "甲岭北段地质演示案例"
    workflow = SimpleNamespace(
        workflow_type="geology_generic",
        plan={
            "uploadInputs": {"lithology": 512},
            "fieldMappingReview": {
                "roles": [
                    {"role": "lithology", "resourceId": 901, "fileName": subject},
                    {"role": "coverage", "resourceId": 514, "fileName": "工作范围"},
                ]
            },
        },
        evidence=[
            {
                "conditions": [
                    f"仅适用于{old_area}；其他地区需验证",
                    "仅适用于本试验区",
                    "仅适用于覆盖层",
                ]
            },
            {"conditions": f"仅适用于“{old_area}”；需要核实。"},
        ],
    )
    scope = bound_report_scope(workflow)
    assert scope == {
        "sourceResourceId": 512,
        "sourceTitle": subject,
        "otherRuleScopeLabels": [old_area],
    }
    valid = {
        "judgement": "本次资料按规则完成分析。",
        "resultSummary": f"对{subject}完成复查。",
        "uncertainties": [f"规则来源于{old_area}，应用范围需核实。"],
    }
    check_summary_scope(valid, scope)
    with pytest.raises(ComputeError, match="当前分析对象"):
        check_summary_scope(
            {**valid, "resultSummary": f"对{old_area}完成复查。"}, scope
        )
    workflow.plan["fieldMappingReview"]["roles"][0]["fileName"] = old_area + "岩性图"
    check_summary_scope(
        {**valid, "judgement": f"本次所选{old_area}"}, bound_report_scope(workflow)
    )


def test_final_response_requires_revision_when_summary_copies_other_rule_scope():
    ref = {"kind": "resource", "id": "512"}
    workflow = SimpleNamespace(
        evidence=[],
        workflow_type="geology_generic",
        plan={"executionPolicy": "rule_geology_v2", "stages": []},
    )
    value = {
        "decision": {
            "problem": "当前数据核查",
            "findings": ["已读取本次结果"],
            "judgement": "对北岸示范区执行了综合检查。",
            "uncertainties": [],
            "nextAction": "finish",
            "algorithmReason": "采用已登记算子",
            "evidenceRefs": [ref],
            "resultSummary": "本次核查已完成",
        },
        "edits": [],
    }
    with pytest.raises(ComputeError, match="analysisSubject"):
        _validate_response(
            json.dumps(value),
            workflow,
            {"name": "final_analysis", "identifier": "finish"},
            [],
            [ref],
            model_payload={
                "availableEvidence": [ref],
                "analysisSubject": {
                    "sourceResourceId": 512,
                    "sourceTitle": "南岸岩性图",
                    "otherRuleScopeLabels": ["北岸示范区"],
                },
            },
        )


def test_writer_and_reviewer_receive_the_same_confirmed_subject():
    from apps.agent.business_flow_context import protected_evidence
    from apps.agent.rule_dispositions import report_payload
    from apps.business_flows.report_review import report_review_packet

    workflow = SimpleNamespace(
        workflow_type="geology_generic",
        plan={
            "stages": [],
            "uploadInputs": {"lithology": 14},
            "fieldMappingReview": {
                "roles": [{"role": "lithology", "fileName": "本批原始岩性图"}]
            },
        },
        evidence=[
            {
                "id": 3,
                "revision": 1,
                "title": "某区域判读规则",
                "conditions": ["仅适用于岭西旧试点区，区域外需验证。"],
            }
        ],
    )
    writer = report_payload({"actualResults": [], "availableEvidence": []}, workflow)
    reviewer = report_review_packet(workflow, {}, [], "a" * 64)
    expected = {
        "sourceResourceId": 14,
        "sourceTitle": "本批原始岩性图",
        "otherRuleScopeLabels": ["岭西旧试点区"],
    }
    assert writer["analysisSubject"] == reviewer["analysisSubject"] == expected
    assert protected_evidence({"result": {"analysisSubject": expected}})
    assert "本次不重新请求修改" in writer["reportScope"]
