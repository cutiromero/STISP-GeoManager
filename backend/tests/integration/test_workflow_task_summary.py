from types import SimpleNamespace

import pytest

from apps.agent.workflow_task_summary import task_summary


def stage(name, key, rows):
    return {
        "name": name,
        "identifier": f"geology_{name}",
        "status": "completed",
        "taskId": name,
        "results": [{"key": key, "scope": "all", "rowCount": len(rows), "rows": rows}],
    }


def summary(stages, **extra):
    return task_summary(SimpleNamespace(plan={"stages": stages, **extra}))


def test_complete_actual_counts_and_zero_prospect():
    initial = [
        {
            "feature_id": f"F{i}",
            "rule_id": "R1",
            "status": "review" if i < 36 else "exception" if i < 45 else "suggested",
        }
        for i in range(241)
    ]
    result = summary(
        [
            stage("check", "issues", initial),
            stage(
                "apply",
                "changes",
                [
                    {"feature_id": f"F{i}", "rule_id": "R1", "actual_changed": True}
                    for i in range(45, 241)
                ],
            ),
            stage("recheck", "issues", [{} for _ in range(142)]),
            stage(
                "prospect",
                "statistics",
                [{"grade": grade, "after_count": 0} for grade in ["A", "B"]],
            ),
        ],
        uploadInputs={"lithology": 1, "structure": 2, "alteration": 3},
    )
    assert result == dict(
        sourceCount=3,
        initialIssueCount=241,
        executedDispositionCount=196,
        remainingIssueCount=142,
        retainedIssueCount=45,
        reviewIssueCount=36,
        exceptionIssueCount=9,
        prospectZoneCount=0,
        completedCalculations=4,
        totalCalculations=4,
    )


def test_incomplete_or_absent_results_are_unknown():
    initial = stage("check", "issues", [{"status": "review"}])
    initial["results"][0]["rowCount"] = 241
    result = summary([initial])
    assert result["initialIssueCount"] is None
    assert result["remainingIssueCount"] is None
    assert result["executedDispositionCount"] is None
    assert result["retainedIssueCount"] is None
    assert result["prospectZoneCount"] is None


def test_approval_is_not_execution_and_actual_changes_remove_held_items():
    initial = stage(
        "check", "issues", [{"feature_id": "F1", "rule_id": "R1", "status": "review"}]
    )
    waiting = {
        "name": "apply",
        "identifier": "geology_apply",
        "taskId": "pending",
        "status": "waiting_compute",
        "approvedSuggestionIds": ["F1"],
    }
    assert summary([initial, waiting])["retainedIssueCount"] is None
    actual = stage(
        "apply",
        "changes",
        [{"feature_id": "F1", "rule_id": "R1", "actual_changed": True}],
    )
    assert summary([initial, actual])["retainedIssueCount"] == 0
    actual["results"][0]["rows"][0]["actual_changed"] = False
    result = summary([initial, actual])
    assert result["retainedIssueCount"] == 1
    assert result["executedDispositionCount"] == 0


@pytest.mark.parametrize("invalid", [True, -1, 1.5, "nan", "inf", None, "invalid"])
def test_invalid_counts_never_become_zero(invalid):
    stats = stage(
        "prospect",
        "statistics",
        [{"grade": "A", "after_count": invalid}, {"grade": "B", "after_count": 0}],
    )
    assert summary([stats])["prospectZoneCount"] is None


def test_partial_prospect_rows_are_unknown():
    assert (
        summary([stage("prospect", "statistics", [{"grade": "A", "after_count": 0}])])[
            "prospectZoneCount"
        ]
        is None
    )
