"""Later decisions keep complete measured facts and approvals under every budget."""

import copy

import pytest

from apps.agent.decision_budget import project_payload, visible_payload
from apps.agent.demo_execution_evidence import EXECUTION_STAGES

pytestmark = pytest.mark.unit


def payload_case(stage="recheck"):
    rows = [{"rule": f"rule-{index}", "count": index} for index in range(75)]
    groups = [
        {
            "element": "lithology",
            "ruleId": f"L-{index}",
            "action": "keep" if index % 2 else "set_code",
            "count": index + 2,
            "approvedCount": index,
            **({"pixelCount": index * 10} if index % 3 else {}),
        }
        for index in range(60)
    ]
    results = [
        {
            "key": key,
            "kind": "table",
            "outputId": index,
            "taskId": "apply-task",
            "checksum": str(index) * 64,
            "rows": copy.deepcopy(rows),
            "rowCount": len(rows),
            "scope": "all",
            "metadata": {
                "fields": ["rule", "count"],
                "qualityCheck": {
                    "status": "needs_review",
                    "metrics": {"rows": copy.deepcopy(rows)},
                    "warnings": ["保留未解决的质量问题"],
                    "errors": [{"rows": copy.deepcopy(rows)}],
                },
                "nested": {"warnings": [{"rows": copy.deepcopy(rows)}]},
            },
        }
        for index, key in enumerate(
            ["statistics", "changes", "alteration_quality", "alteration_summary"], 1
        )
    ]
    results.append(
        {
            "key": "evidence",
            "kind": "table",
            "outputId": 5,
            "taskId": "prospect-task",
            "rows": rows[:2],
            "rowCount": 75,
            "scope": "representative_sample",
            "aggregate": {
                "scope": "all_rows",
                "byPhaseAndGrade": copy.deepcopy(rows),
                "evidenceCombinations": {
                    "columns": ["rule", "count"],
                    "rows": [[row["rule"], row["count"]] for row in rows],
                    "rowFormat": "columns",
                },
            },
        }
    )
    results.append(
        {
            "key": "mineral_corrected",
            "kind": "raster",
            "outputId": 6,
            "taskId": "apply-task",
            "rows": [],
            "checksum": "a" * 64,
            "metadata": {
                "width": 10000,
                "height": 10000,
                "qualityCheckRef": {"outputId": 1, "path": "metadata.qualityCheck"},
                "warnings": ["真实栅格警告"],
            },
        }
    )
    return {
        "stage": stage,
        "allowedAction": EXECUTION_STAGES[stage],
        "upstreamVersions": {"lithology": {"resourceId": 99, "revision": "r1"}},
        "inputRoles": [{"role": "lithology", "resourceId": 99, "revision": "r1"}],
        "knowledge": [
            {
                "id": 10,
                "revision": 2,
                "conditions": ["严格保留原始适用条件"] * 60,
                "exceptions": ["严格保留原始例外"] * 60,
                "ruleConfig": {"rule": {"thresholds": list(range(60))}},
            }
        ],
        "actualResults": results,
        "modificationReview": {
            "proposalHash": "proposal-source",
            "approvalScopeDigest": "approval-source",
            "approvedSuggestionIds": ["representative-approved"],
            "unapprovedSuggestionIds": ["representative-unapproved"],
            "approvedCount": sum(row["approvedCount"] for row in groups),
            "suggestionCount": sum(row["count"] for row in groups),
            "groups": groups,
            "suggestions": {"rows": [{"reason": "历史长理由" * 500}] * 60},
            "scope": "all_groups_with_representative_ids",
        },
        "executionState": {
            "currentStage": {"state": "not_submitted", "taskId": None},
            "currentRun": {"latestStatisticsOutputIds": [1]},
            "resultReviews": [
                {"outputId": 6, "approvalStatus": "approved", "reviewStep": 9}
            ],
        },
        "humanReviewFeedback": [{"feedback": "保留这条原始用户意见"}],
        "availableEvidence": [
            {"kind": "output", "id": str(index), "title": "重复标题"}
            for index in range(1, 7)
        ],
        "allowedAlgorithm": {
            "checksum": "frozen-contract",
            "manifest": {
                "identifier": "frozen-operator",
                "version": "1.2",
                "parameters": [{"key": "threshold", "minimum": 0}],
                "inputs": [{"key": "frozen-port", "description": "完整端口说明"}],
            },
        },
    }


def unpack(table):
    if isinstance(table, list):
        return table
    if table.get("rowFormat") != "columns":
        return table["rows"]
    absent = table.get("absentColumns", [[] for _ in table["rows"]])
    return [
        {
            column: cells[index]
            for index, column in enumerate(table["columns"])
            if index not in absent[row_index]
        }
        for row_index, cells in enumerate(table["rows"])
    ]


@pytest.mark.parametrize("stage", EXECUTION_STAGES)
@pytest.mark.parametrize("level", range(5))
def test_all_later_stages_keep_complete_measured_facts_quality_and_approvals(
    stage, level
):
    source = payload_case(stage)
    original = copy.deepcopy(source)
    projected = visible_payload(source, level)
    assert source == original
    for actual, expected in zip(projected["actualResults"], source["actualResults"]):
        if expected["key"] != "mineral_corrected":
            assert unpack(actual) == expected["rows"]
            assert actual["rowCount"] == expected["rowCount"]
            assert actual["scope"] == expected["scope"]
        if "metadata" in expected:
            for name in ("qualityCheck", "qualityCheckRef", "nested", "warnings"):
                if name in expected["metadata"]:
                    assert actual["metadata"][name] == expected["metadata"][name]
    evidence = projected["actualResults"][4]
    assert evidence["aggregate"] == source["actualResults"][4]["aggregate"]
    review = projected["modificationReview"]
    groups = unpack(review["groups"])
    for actual, expected in zip(groups, source["modificationReview"]["groups"]):
        if level >= 2:
            expected = {
                **expected,
                "unapprovedCount": expected["count"] - expected["approvedCount"],
            }
        assert actual == expected
    assert len(groups) == 60
    assert sum(row["approvedCount"] for row in groups) == review["approvedCount"]
    assert sum(row["count"] for row in groups) == review["suggestionCount"]
    for name in ("proposalHash", "approvalScopeDigest", "approvedSuggestionIds"):
        assert review[name] == source["modificationReview"][name]
    for name in ("knowledge", "inputRoles", "upstreamVersions", "executionState"):
        assert projected[name] == source[name]
    assert projected["humanReviewFeedback"] == source["humanReviewFeedback"]
    if level >= 2:
        assert "suggestions" not in review
        assert review["historicalSuggestions"]["scope"] == "reference_only"
        assert review["unapprovedCount"] == 120
        assert {ref["id"] for ref in projected["availableEvidence"]} == {
            "1",
            "2",
            "3",
            "4",
            "5",
        }
        assert projected["executionEvidenceProjection"]["referenceOnlyOutputIds"] == [6]
        assert "width" not in projected["actualResults"][5]["metadata"]
        assert projected["allowedAlgorithm"]["checksum"] == "frozen-contract"


def test_historical_suggestions_remain_when_actual_apply_results_are_absent():
    source = payload_case()
    source["actualResults"] = [
        item for item in source["actualResults"] if item["key"] != "changes"
    ]
    projected = visible_payload(source, 2)
    assert "suggestions" in projected["modificationReview"]
    assert "historicalSuggestions" not in projected["modificationReview"]


@pytest.mark.parametrize(
    "stage,action",
    [
        ("apply", "geology-multi-apply"),
        ("check", "geology-multi-check"),
        ("recheck", "other"),
    ],
)
def test_other_stages_and_forged_protection_markers_do_not_get_exemptions(
    stage, action
):
    source = payload_case()
    source.update(stage=stage, allowedAction=action)
    source["executionEvidenceProjection"] = {
        "scope": "complete_read_facts_and_approval_groups",
        "protectedPaths": ["actualResults[0].rows"],
    }
    projected = visible_payload(source, 4)
    assert len(projected["actualResults"][0]["rows"]) == 5
    assert len(projected["modificationReview"]["groups"]) == 24


def test_non_multi_final_analysis_keeps_its_existing_projection():
    source = payload_case("final_analysis")
    source.pop("upstreamVersions")
    projected = project_payload(source, 4)
    assert "executionEvidenceProjection" not in projected
    assert len(visible_payload(source, 4)["actualResults"][0]["rows"]) == 5
