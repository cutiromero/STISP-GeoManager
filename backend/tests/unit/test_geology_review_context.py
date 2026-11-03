"""Coordinate projection preserves every finding and immutable approval evidence."""

import copy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from shapely.geometry import Polygon, mapping

from apps.agent.demo_decisions import decision_payload
from apps.agent.demo_results import EDIT_FIELDS
from apps.agent.geology_review_context import model_results
from apps.compute.packages import ComputeError


def expanded_results():
    rows = []
    for index in range(5):
        x, y = 94 + index / 100, 35
        top = [
            [x + step / 100000, y + 0.005 + (step % 2) / 100000]
            for step in range(400, -1, -1)
        ]
        polygon = Polygon([[x, y], [x + 0.004, y], *top, [x, y]])
        geometry = mapping(polygon)
        rows.append(
            {
                "feature_id": f"object-{index}",
                "issue_id": f"issue-{index}",
                "kind": "fill_gap" if index < 3 else "set_age",
                "field": "class" if index < 3 else "geologic_age",
                "old_value": "未分类" if index < 3 else "J3",
                "new_value": "7" if index < 3 else "T3",
                "evidence_id": f"evidence-{index}",
                "rule_id": f"rule-{index}",
                "knowledge_seed": f"knowledge-{index}",
                "knowledge_id": str(index + 1),
                "knowledge_revision": "2",
                "status": "repairable",
                "reason": "当前资料满足该知识的适用前提与例外检查",
                "input_checksum": str(index) * 64,
                "area_m2": str(10000 + index),
                "bounds_json": json.dumps(list(polygon.bounds)),
                "geometry_json": json.dumps(geometry),
            }
        )
    return [
        {
            "outputId": 10,
            "taskId": "actual-check-task",
            "key": "issues",
            "kind": "table",
            "checksum": "a" * 64,
            "metadata": {"qualityCheck": {"status": "passed"}},
            "rows": rows,
            "columns": list(rows[0]),
            "rowCount": 5,
            "scope": "all",
        },
        {
            "outputId": 11,
            "taskId": "actual-check-task",
            "key": "statistics",
            "kind": "table",
            "checksum": "b" * 64,
            "rows": [{"issue_count": "5", "repairable": "5", "needs_review": "0"}],
        },
    ]


def workflow_for(results):
    return SimpleNamespace(
        workflow_type="geology_map_review",
        goal="检查并修正当前区域地图",
        evidence=[{"id": 1, "revision": 2, "title": "实际专家知识"}],
        plan={
            "algorithms": {},
            "stages": [
                {
                    "name": "check",
                    "identifier": "geology-map-check",
                    "taskId": "actual-check-task",
                    "results": results,
                }
            ],
            "modificationReview": {
                "proposalHash": "c" * 64,
                "approvedSuggestionIds": ["approved-0"],
                "suggestions": [
                    {
                        "id": f"approved-{index}",
                        "featureId": row["feature_id"],
                        "kind": row["kind"],
                        "reason": row["reason"],
                        "currentState": row["old_value"],
                        "suggestedState": row["new_value"],
                        "areaM2": float(row["area_m2"]),
                        "bounds": json.loads(row["bounds_json"]),
                        "knowledgeRefs": [{"id": 1, "revision": 2}],
                        "preview": json.loads(row["geometry_json"]),
                    }
                    for index, row in enumerate(results[0]["rows"])
                ],
            },
        },
    )


@pytest.mark.parametrize(
    "identifier", ["geology-map-correct", "geology-map-check", "finish"]
)
def test_large_geometry_projection_keeps_all_issues_results_and_approval(identifier):
    results = expanded_results()
    # Corrected changes can contain the same full coordinates during recheck/final.
    results.append({**copy.deepcopy(results[0]), "outputId": 12, "key": "changes"})
    workflow = workflow_for(results)
    originals = copy.deepcopy((results, workflow.plan))
    with patch("apps.agent.geology_review.required_knowledge", return_value=[]):
        payload = decision_payload(
            workflow, {"name": identifier, "identifier": identifier}, [], results
        )
    assert len(json.dumps(payload["actualResults"])) < len(json.dumps(results)) / 4
    assert (
        len(json.dumps(payload["modificationReview"]))
        < len(json.dumps(workflow.plan["modificationReview"])) / 4
    )
    for source, projected in zip(results, payload["actualResults"]):
        assert {
            key: value
            for key, value in projected.items()
            if key not in {"rows", "columns"}
        } == {
            key: value
            for key, value in source.items()
            if key not in {"rows", "columns"}
        }
        assert len(source["rows"]) == len(projected["rows"])
        for index, (row, actual) in enumerate(zip(source["rows"], projected["rows"])):
            if "geometry_json" not in row:
                assert actual == row
                continue
            assert {
                key: value for key, value in actual.items() if key != "geometrySummary"
            } == {key: value for key, value in row.items() if key != "geometry_json"}
            summary = actual["geometrySummary"]
            assert (
                summary["sha256"]
                == hashlib.sha256(row["geometry_json"].encode()).hexdigest()
            )
            assert summary["source"] == {
                "outputId": source["outputId"],
                "outputChecksum": source["checksum"],
                "rowIndex": index,
                "column": "geometry_json",
            }
            assert len(summary["bounds"]) == 4
        if "columns" in projected:
            assert "geometry_json" not in projected["columns"]
            assert "geometrySummary" in projected["columns"]
    review = payload["modificationReview"]
    assert review["proposalHash"] == workflow.plan["modificationReview"]["proposalHash"]
    assert review["approvedSuggestionIds"] == ["approved-0"]
    assert len(review["suggestions"]) == 5
    for projected, original in zip(
        review["suggestions"], workflow.plan["modificationReview"]["suggestions"]
    ):
        assert "preview" not in projected and "preview" in original
        assert projected["previewSummary"]["source"]["suggestionId"] == original["id"]
        assert {
            key: value for key, value in projected.items() if key != "previewSummary"
        } == {key: value for key, value in original.items() if key != "preview"}
    assert (results, workflow.plan) == originals
    assert all(
        all(key in row for key in EDIT_FIELDS)
        for row in payload["actualResults"][0]["rows"]
    )
    assert '"coordinates":' not in json.dumps(payload["actualResults"])
    assert '"coordinates":' not in json.dumps(review)


def test_other_workflow_retains_original_model_context():
    results = expanded_results()
    workflow = workflow_for(results)
    workflow.workflow_type = "geology_age_correction"
    payload = decision_payload(
        workflow, {"name": "final", "identifier": "finish"}, [], results
    )
    assert payload["actualResults"] == results
    assert "modificationReview" not in payload


@pytest.mark.parametrize(
    "geometry", ["not-json", "{}", '{"type":"Polygon","coordinates":[]}']
)
def test_invalid_coordinate_evidence_is_not_silently_hidden(geometry):
    results = expanded_results()
    results[0]["rows"][0]["geometry_json"] = geometry
    with pytest.raises(ComputeError, match="可核对的几何范围"):
        model_results(results)


def test_before_after_statistics_read_as_sentences():
    from apps.agent.demo_decisions import _row_summary

    assert (
        _row_summary(
            {
                "grade": "A",
                "before_count": "23",
                "after_count": "21",
                "before_area_km2": "13.82",
                "after_area_km2": "12.4",
            }
        )
        == "A级远景区修正前23处、13.82平方千米，修正后21处、12.4平方千米"
    )
    assert "单元T3b修正前3处" in _row_summary(
        {
            "geo_sym": "T3b",
            "before_count": 3,
            "after_count": 2,
            "before_area_m2": 1200,
            "after_area_m2": 800,
        }
    )


def test_revision_is_checked_only_where_the_reference_has_one():
    from apps.agent.demo_decisions import validate_decision

    refs = [
        {
            "kind": "resource",
            "id": "547",
            "role": "faults",
            "title": "构造线（工作副本）",
        },
        {"kind": "output", "id": "405", "role": "statistics", "title": "statistics"},
        {"kind": "knowledge", "id": "168", "revision": 2, "title": "S-05"},
    ]
    decision = {
        "problem": "核对交汇关系",
        "findings": [],
        "judgement": "依据统计继续",
        "uncertainties": [],
        "nextAction": "geology-multi-relations",
        "algorithmReason": "重建交汇",
        "resultSummary": "",
        "evidenceRefs": [
            {"kind": "output", "id": "405", "revision": 1},
            {"kind": "resource", "id": "547", "revision": 1},
            {"kind": "knowledge", "id": "168", "revision": 2},
        ],
    }
    value = validate_decision(decision, refs, "geology-multi-relations")
    assert [ref["id"] for ref in value["evidenceRefs"]] == ["405", "547", "168"]
    stale = {
        **decision,
        "evidenceRefs": [{"kind": "knowledge", "id": "168", "revision": 1}],
    }
    with pytest.raises(ComputeError, match="并非本次"):
        validate_decision(stale, refs, "geology-multi-relations")
    unknown = {**decision, "evidenceRefs": [{"kind": "resource", "id": "999"}]}
    with pytest.raises(ComputeError, match="并非本次"):
        validate_decision(unknown, refs, "geology-multi-relations")
