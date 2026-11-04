"""Only approved objects expand; actual operation records control completion claims."""

from types import SimpleNamespace

import pytest

from apps.agent.geology_multi_report import render_report
from apps.compute.packages import ComputeError


def report_fixture(monkeypatch):
    suggestions = [
        {
            "id": f"s-{index}",
            "featureId": f"G-{index}",
            "ruleId": "L-03" if index == 0 else "A-01",
            "action": "set_code" if index == 0 else "review",
            "title": f"第{index}项待核查",
            "currentState": "当前代号",
            "suggestedState": "对应地层代号",
            "reason": "名称和冻结映射不一致，依据实测属性修正代号"
            if index == 0
            else f"未批准细节-{index}",
            "observations": {"observed_code": "old", "expected_code": "T3"},
        }
        for index in range(26)
    ]
    output = SimpleNamespace(id=30, label="完整变化CSV")
    task = SimpleNamespace(
        id="task-apply",
        name="获批修正",
        parameters={"segment": "all"},
        version=SimpleNamespace(
            version="1.0.1", algorithm=SimpleNamespace(name="真实编辑算法")
        ),
        outputs=SimpleNamespace(order_by=lambda *args: [output]),
    )
    workflow = SimpleNamespace(
        project_tag=SimpleNamespace(name="逻辑推理"),
        project_tag_id=4,
        goal="检查地图并修正",
        evidence=[
            {
                "trialBinding": {"ruleId": "L-03", "ruleVersion": "0.1-draft"},
                "revision": 2,
                "conditions": ["名称及地层映射已核对"],
                "exceptions": ["新名称先保留"],
                "sources": [{"title": "冻结的名称代号表", "locator": "L-03条目"}],
            }
        ],
        plan={
            "stages": [
                {
                    "name": "apply",
                    "taskId": "task-apply",
                    "decision": {"modelMode": "mock"},
                    "approvedEdits": [
                        {
                            "feature_id": "G-0",
                            "rule_id": "L-03",
                            "target_code": "T3",
                            "weight": 1,
                        }
                    ],
                }
            ],
            "modificationReview": {
                "suggestions": suggestions,
                "approvedSuggestionIds": ["s-0"],
            },
            "finalDecision": {"resultSummary": "实际修改代号"},
            "frozen_rules": 22,
        },
    )
    rows = [
        {
            "feature_id": "G-0",
            "rule_id": "L-03",
            "action": "set_code",
            "actual_changed": "True",
            "target_code": "T3",
            "new_code": "T3",
            "weight": "1.0",
        }
    ]
    monkeypatch.setattr(
        "apps.agent.geology_review_report.actual_table", lambda *args: rows
    )
    return workflow, task, rows


def test_compact_report_groups_unapproved_and_links_complete_evidence(monkeypatch):
    workflow, task, _ = report_fixture(monkeypatch)
    text = render_report(workflow, [task]).decode()
    assert "用户批准1项，其余25项保持原样" in text
    assert text.count("### 1.") == 1
    assert "未批准细节" not in text
    assert "A-01 | 保留待核查 | 25 | 保留原数据" in text
    assert "实际结果：已执行" in text
    assert "修订 2" in text and "冻结的名称代号表 L-03条目" in text
    assert "/api/compute/outputs/30/file/?projectTagId=4" in text
    assert "/api/catalog/resources/22/profile/?projectTagId=4" in text
    assert "真实编辑算法 1.0.1" in text and "真实模型判断尚未验证" in text


def test_clean_report_links_deliverable_layers_not_calculation_states(monkeypatch):
    workflow, task, _ = report_fixture(monkeypatch)
    task.version.manifest = {
        "version": "1.0.5",
        "outputs": [{"key": "final_faults"}, {"key": "final_alterations"}],
    }
    task.outputs = SimpleNamespace(
        order_by=lambda *args: [
            SimpleNamespace(id=30, label="计算构造状态", key="faults"),
            SimpleNamespace(id=31, label="计算蚀变状态", key="alterations"),
            SimpleNamespace(id=32, label="修正后构造图", key="final_faults"),
            SimpleNamespace(id=33, label="有效蚀变", key="final_alterations"),
        ]
    )
    text = render_report(workflow, [task]).decode()
    assert "计算构造状态" not in text and "计算蚀变状态" not in text
    assert "[修正后构造图]" in text and "[有效蚀变]" in text


@pytest.mark.parametrize(
    "change", ["wrong_object", "wrong_action", "extra", "wrong_code", "wrong_weight"]
)
def test_report_rejects_changes_that_do_not_match_approval(monkeypatch, change):
    workflow, task, rows = report_fixture(monkeypatch)
    if change == "wrong_object":
        rows[0]["feature_id"] = "G-unapproved"
    elif change == "wrong_action":
        rows[0]["action"] = "exclude"
    elif change == "extra":
        rows.append({**rows[0], "feature_id": "G-extra"})
    elif change == "wrong_code":
        rows[0]["new_code"] = "Unapproved"
    else:
        rows[0]["weight"] = "0.5"
    with pytest.raises(ComputeError, match="批准|获批"):
        render_report(workflow, [task])
