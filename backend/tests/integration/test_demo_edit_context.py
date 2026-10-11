"""Real provider receives current edit obligations without fabricated proposals."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.agent.demo_decisions import decide, decision_payload
from apps.agent.demo_results import EDIT_FIELDS, validate_edits
from apps.agent.policy import default_policy


def issue(feature="arbitrary-object", **changes):
    return {
        "feature_id": feature,
        "field": "contact_type",
        "old_value": "整合",
        "new_value": "断层",
        "evidence_id": "actual-survey",
        "rule_id": "actual-consistency-rule",
        "reason": "实测编号、位置、允许值和可信度均匹配",
        "status": "repairable",
        "input_checksum": "a" * 64,
        **changes,
    }


def geology():
    stage = {
        "name": "edit",
        "identifier": "geology-edit",
        "status": "pending",
        "bindings": {"features": "geometry/repaired", "changes": "model_changes"},
    }
    workflow = SimpleNamespace(
        model="online-fixture",
        goal="依据实际检查和调查规则提出属性修正",
        evidence=[],
        plan={
            "stages": [
                {"identifier": "geology-check", "taskId": "initial-check"},
                {"identifier": "vector-geometry-repair", "taskId": "geometry-task"},
                {"identifier": "geology-check", "taskId": "latest-check"},
                stage,
                {"identifier": "geology-check", "status": "pending"},
            ],
            "algorithms": {"geology-edit": {"versionId": 55}},
        },
    )
    results = [
        {
            "outputId": 101,
            "taskId": "latest-check",
            "key": "issues",
            "rows": [
                issue("unresolved", status="needs_review"),
                issue(),
                issue("geometry-object", field="geometry"),
            ],
        },
        {
            "outputId": 102,
            "taskId": "latest-check",
            "key": "statistics",
            "rows": [{"issue_count": "3", "repairable": "2"}],
        },
        # Result order alone is insufficient: this stale row must not be proposed.
        {
            "outputId": 999,
            "taskId": "initial-check",
            "key": "issues",
            "rows": [issue("stale-object")],
        },
    ]
    return workflow, stage, results


def test_edit_context_points_to_latest_actual_rows_and_required_fields():
    workflow, stage, results = geology()
    original_results, original_plan = (
        copy.deepcopy(results),
        copy.deepcopy(workflow.plan),
    )
    payload = decision_payload(workflow, stage, [], results)
    assert payload["editTask"] == {
        "changesInputState": "requires_model_proposal",
        "latestCheckTaskId": "latest-check",
        "issuesOutputIds": [101],
        "repairableAttributeRows": [{"outputId": 101, "rowIndex": 1}],
        "requiredFields": [*EDIT_FIELDS, "reason"],
        "inputChecksumSource": "executor_binds_actual_issue",
    }
    assert "edits" not in payload["editTask"]
    assert payload["actualResults"] == original_results
    assert results == original_results and workflow.plan == original_plan


@pytest.mark.parametrize("identifier", ["geology-check", "finish", "ecology-priority"])
def test_other_stages_have_no_edit_task(identifier):
    workflow, stage, results = geology()
    stage["identifier"] = identifier
    assert decision_payload(workflow, stage, [], results)["editTask"] is None


def model_response(action, edits):
    return {
        "decision": {
            "problem": "依据实际清单处理属性问题",
            "findings": ["当前检查给出了明确属性修正与待核实事项"],
            "judgement": "提交明确修改" if edits else "核对本步依据",
            "uncertainties": ["待核实的对象继续保留"],
            "nextAction": action,
            "algorithmReason": "按实际调查与规则进行受约束编辑",
            "evidenceRefs": [
                {"kind": "output", "id": "101"},
                {"kind": "output", "id": "102"},
            ],
            "resultSummary": "明确修改后重新检查",
        },
        "edits": edits,
    }


@pytest.mark.parametrize("kind", ["proposal", "review"])
def test_real_provider_keeps_model_proposal_and_genuine_review_without_autofill(
    kind, settings
):
    settings.AGENT_MODELS = [
        {
            "alias": "online-fixture",
            "name": "真实provider接口测试",
            "model_id": "qwen-fixture",
            "base_url": "http://127.0.0.1:19100/v1",
            "agent": True,
        }
    ]
    workflow, stage, results = geology()
    actual_issue = results[0]["rows"][1]
    edits = (
        [{key: actual_issue[key] for key in (*EDIT_FIELDS, "reason")}]
        if kind == "proposal"
        else []
    )
    action = "request_review" if kind == "review" else "geology-edit"
    response = model_response(action, edits)
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=800),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            return_value=iter([json.dumps(response, ensure_ascii=False)]),
        ) as stream,
    ):
        decision, proposed = decide(
            workflow, None, default_policy(), stage, results, lambda: None
        )
    assert decision["nextAction"] == action
    assert decision["modelMode"] == "real"
    assert proposed == edits
    messages = stream.call_args.args[1]
    payload = json.loads(messages[-1]["content"])
    assert payload["editTask"]["repairableAttributeRows"] == [
        {"outputId": 101, "rowIndex": 1}
    ]
    instruction = messages[0]["content"]
    assert "model_changes是绑定名称，不是已有修改表" in instruction
    assert "edits不能留空或只在正文描述修改" in instruction
    assert "无法提出有据修改时选择request_review" in instruction
    assert "input_checksum由执行器从该真实问题行绑定" in instruction
    assert "调查排序改变不等于原因被证实" in instruction
    if kind == "proposal":
        accepted = validate_edits(proposed, [results[0]])
        assert accepted[0]["input_checksum"] == actual_issue["input_checksum"]
