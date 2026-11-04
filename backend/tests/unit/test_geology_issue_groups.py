import json

import pytest

from apps.agent.geology_issue_groups import expand_groups, group_summaries
from apps.agent.geology_multi_review import assess_edits
from apps.compute.packages import ComputeError


def issues(count=7362):
    return [
        {
            "issue_id": f"i-{index}",
            "feature_id": f"f-{index}",
            "element": "alteration",
            "rule_id": "A-05",
            "rule_version": "trial-1",
            "snapshot_hash": "a" * 64,
            "status": "suggested",
            "suggested_action": "exclude",
            "target_code": "",
            "allowed_actions_json": '["exclude","review"]',
            "measurements_json": json.dumps({"area_m2": index + 1}),
        }
        for index in range(count)
    ]


def decision(group, excluded=(), disposition="suggested"):
    return {
        "group_id": group["group_id"],
        "disposition": disposition,
        "excluded_issue_ids": list(excluded),
        "reason": "实测面积小于规则阈值；排除需裁定例外",
    }


def test_unlimited_groups_expand_every_object_with_individual_validation():
    rows = issues()
    groups = group_summaries(rows)
    assert len(groups) == 1 and groups[0]["count"] == 7362
    assert groups[0]["measurementRanges"] == {"area_m2": [1, 7362]}
    assert len(groups[0]["samples"]) == 3
    accepted, report = assess_edits(
        [decision(groups[0], ["i-5"])], [{"key": "issues", "rows": rows}]
    )
    assert len(accepted) == 7361 and not report["errors"]
    assert all(row["feature_id"] != "f-5" for row in accepted)
    assert all(
        row["snapshot_hash"] == "a" * 64 and row["weight"] == 0 for row in accepted
    )


@pytest.mark.parametrize("status", ["review", "exception"])
def test_review_and_exception_cannot_enter_whole_group(status):
    rows = issues(2)
    rows[1]["status"] = status
    groups = group_summaries(rows)
    protected = next(group for group in groups if group["status"] == status)
    with pytest.raises(ComputeError, match="待裁定或例外"):
        expand_groups([decision(protected)], rows)
    assert expand_groups([decision(protected, disposition="review")], rows) == []


@pytest.mark.parametrize(
    "field,value", [("snapshot_hash", "bad"), ("allowed_actions_json", '["review"]')]
)
def test_expansion_does_not_bypass_object_guards(field, value):
    rows = issues(2)
    rows[1][field] = value
    accepted, report = assess_edits(
        [decision(group) for group in group_summaries(rows)],
        [{"key": "issues", "rows": rows}],
    )
    assert len(accepted) == 1 and report["discardedCount"] == 1


def test_group_snapshot_and_excluded_ids_are_bound_to_actual_check():
    rows = issues(2)
    group = group_summaries(rows)[0]
    with pytest.raises(ComputeError, match="快照"):
        expand_groups([decision(group, ["not-an-object"])], rows)
    rows[0]["snapshot_hash"] = rows[1]["snapshot_hash"] = "b" * 64
    with pytest.raises(ComputeError, match="快照"):
        expand_groups([decision(group)], rows)


def test_overlapping_rules_expand_to_one_actual_operation_in_check_order():
    rows = issues(1)
    rows.append({**rows[0], "issue_id": "secondary", "rule_id": "A-01"})
    expanded = expand_groups([decision(group) for group in group_summaries(rows)], rows)
    assert [item["issue_id"] for item in expanded] == ["i-0"]


def test_group_cannot_receive_conflicting_duplicate_decisions():
    rows = issues(2)
    group = group_summaries(rows)[0]
    with pytest.raises(ComputeError, match="只能给出一次"):
        expand_groups([decision(group), decision(group, disposition="review")], rows)
