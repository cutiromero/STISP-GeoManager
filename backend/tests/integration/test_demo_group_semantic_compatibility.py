"""Redundant group fields may describe, but cannot alter, explicit model choices."""

import copy
import itertools

import pytest

from apps.agent.demo_decision_batches import model_issue_groups
from apps.agent.geology_multi_review import _expand_review_group, assess_edits
from apps.compute.packages import ComputeError
from tests.integration.test_demo_decision_batches import scenario


def group_case(*, action="downweight", targets=("", ""), status="suggested"):
    _, _, results = scenario(len(targets))
    rows = results[0]["rows"]
    for row, target in zip(rows, targets):
        row.update(
            suggested_action=action,
            target_code=target,
            status=status,
            allowed_actions_json='["downweight","exclude","reclassify","merge","set_code","keep","review"]',
        )
    identity, _ = model_issue_groups(rows)[0]
    return (
        results,
        rows,
        {
            "group_id": identity,
            "disposition": "suggested" if status == "suggested" else "review",
            "excluded_issue_ids": [],
            "reason": "共同测量满足试用条件，保留具体地质例外并等待批准",
        },
    )


@pytest.mark.parametrize(
    "fields",
    [
        fields
        for length in (1, 2, 3)
        for fields in itertools.combinations(
            ("action", "target_code", "weight"), length
        )
    ],
)
def test_redundant_field_subsets_preserve_exact_expansion_and_raw_response(fields):
    _, rows, raw = group_case()
    expected = _expand_review_group(raw, rows)
    described = {"action": "downweight", "target_code": "", "weight": 0.5}
    raw.update({key: described[key] for key in fields})
    before = copy.deepcopy(raw)
    assert _expand_review_group(raw, rows) == expected
    assert raw == before


@pytest.mark.parametrize(
    "action,target,weight",
    [
        ("exclude", "", 0),
        ("downweight", "", 0.5),
        ("reclassify", "T3", 1.0),
        ("set_code", "T3", 1),
        ("merge", "T3", 1),
    ],
)
def test_redundant_values_only_confirm_the_selected_source_action(
    action, target, weight
):
    results, rows, raw = group_case(action=action, targets=(target, target))
    payload = {
        "actualResults": [
            {
                "key": "issues",
                "groups": [
                    {"group_id": raw["group_id"], "count": len(rows), "samples": rows}
                ],
            }
        ]
    }
    expected = assess_edits([raw], results, model_payload=payload)
    raw.update(action=action, target_code=target, weight=weight)
    actual = assess_edits([raw], results, model_payload=payload)
    assert actual == expected and not actual[1]["errors"]
    assert len(actual[0]) == 2 and all(edit["action"] == action for edit in actual[0])


@pytest.mark.parametrize(
    "key", ["group_id", "disposition", "excluded_issue_ids", "reason"]
)
def test_redundant_fields_do_not_replace_any_required_group_key(key):
    _, rows, raw = group_case()
    raw.update(action="downweight", target_code="", weight=0.5)
    raw.pop(key)
    with pytest.raises(ComputeError, match="须含"):
        _expand_review_group(raw, rows)


@pytest.mark.parametrize(
    "extra",
    [
        {"confidence": 0.9},
        {"issue_id": "object-0"},
        {"action": "exclude"},
        {"action": ["downweight"]},
        {"target_code": "T3"},
        {"target_code": None},
        {"weight": 0.6},
        {"weight": True},
        {"weight": False},
        {"weight": "0.5"},
        {"weight": None},
        {"weight": float("nan")},
        {"weight": float("inf")},
        {"weight": -float("inf")},
    ],
)
def test_conflicting_unknown_or_ill_typed_fields_cannot_be_silently_dropped(extra):
    _, rows, raw = group_case()
    raw.update(extra)
    with pytest.raises(ComputeError):
        _expand_review_group(raw, rows)


def test_per_member_targets_remain_independent_and_exclusions_limit_equivalence_check():
    _, rows, raw = group_case(action="reclassify", targets=("T3", "P1"))
    raw.update(action="reclassify", weight=1)
    expanded = _expand_review_group(raw, rows)
    assert {edit["issue_id"]: edit["target_code"] for edit in expanded} == {
        row["issue_id"]: row["target_code"] for row in rows
    }
    raw["target_code"] = "T3"
    with pytest.raises(ComputeError, match="不一致"):
        _expand_review_group(raw, rows)
    raw["excluded_issue_ids"] = [rows[1]["issue_id"]]
    assert _expand_review_group(raw, rows) == [
        edit for edit in expanded if edit["issue_id"] == rows[0]["issue_id"]
    ]
    raw["excluded_issue_ids"] = [rows[0]["issue_id"]]
    with pytest.raises(ComputeError, match="不一致"):
        _expand_review_group(raw, rows)


@pytest.mark.parametrize("disposition", ["keep", "review"])
def test_keep_and_review_do_not_adopt_redundant_source_candidate(disposition):
    _, rows, raw = group_case(action="reclassify", targets=("T3", "P1"))
    raw.update(disposition=disposition, action=disposition, target_code="", weight=1.0)
    expanded = _expand_review_group(raw, rows)
    if disposition == "keep":
        assert len(expanded) == 2
        assert all(
            edit["action"] == "keep"
            and edit["target_code"] == ""
            and edit["weight"] == 1
            for edit in expanded
        )
    else:
        assert expanded == []
    raw.update(action="reclassify", target_code="T3", weight=1)
    with pytest.raises(ComputeError, match="不一致"):
        _expand_review_group(raw, rows)


@pytest.mark.parametrize("status", ["review", "exception"])
def test_held_review_stays_empty_and_redundancy_never_promotes_it(status):
    _, rows, raw = group_case(status=status)
    raw.update(action="review", target_code="", weight=1)
    assert _expand_review_group(raw, rows) == []
    raw.update(disposition="suggested", action="downweight", weight=0.5)
    with pytest.raises(ComputeError, match="待裁定或例外"):
        _expand_review_group(raw, rows)


@pytest.mark.parametrize(
    "extra", [{"action": "reject"}, {"target_code": ""}, {"weight": 1}]
)
def test_reject_has_no_execution_fields_that_can_be_inferred(extra):
    _, rows, raw = group_case()
    raw["disposition"] = "reject"
    assert _expand_review_group(raw, rows) == []
    raw.update(extra)
    with pytest.raises(ComputeError, match="拒绝候选不产生动作"):
        _expand_review_group(raw, rows)


def test_empty_or_invalid_excluded_scope_cannot_vacuously_validate_redundancy():
    _, rows, raw = group_case()
    raw["excluded_issue_ids"] = [row["issue_id"] for row in rows]
    assert _expand_review_group(raw, rows) == []
    raw["weight"] = 0.5
    with pytest.raises(ComputeError, match="空处置范围"):
        _expand_review_group(raw, rows)
    raw["excluded_issue_ids"] = ["outside-this-group"]
    with pytest.raises(ComputeError, match="不属于本次检查快照"):
        _expand_review_group(raw, rows)
