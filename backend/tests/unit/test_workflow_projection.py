import copy
import gzip
import hashlib
import json
from types import SimpleNamespace

import pytest

from apps.agent.workflow_projection import page_options, project_workflow


OBJECT_COUNT = 5200


def test_element_pages_keep_global_counts_and_comparison_revision():
    workflow = large_workflow(150)
    for index, item in enumerate(workflow.plan["modificationReview"]["suggestions"]):
        item["element"] = (
            "lithology" if index < 70 else "structure" if index < 90 else "alteration"
        )
        if index >= 90:
            workflow.plan["stages"][0]["results"][0]["rows"][index].update(
                pixel_count=100, area_m2=2500
            )
    first = project_workflow(
        workflow,
        {"planHash": "frozen"},
        "compare",
        "changes",
        0,
        25,
        element="alteration",
    )
    second = project_workflow(
        workflow,
        {"planHash": "frozen"},
        "compare",
        "changes",
        25,
        25,
        element="alteration",
    )
    page = first["plan"]["pagination"]
    assert page["counts"] == {
        "all": 150,
        "lithology": 70,
        "structure": 20,
        "alteration": 60,
    }
    assert page["total"] == 60 and page["alterationPixels"] == 6000
    assert page["alterationAreaM2"] == 150000
    assert second["plan"]["pagination"]["counts"] == page["counts"]
    assert second["plan"]["pagination"]["revision"] == page["revision"]
    assert first["planHash"] == second["planHash"] == "frozen"
    assert all(
        item["element"] == "alteration"
        for item in first["modificationReview"]["suggestions"]
    )
    assert (
        second["plan"]["compareFeatures"]["features"][0]["properties"]["_rowIndex"]
        == 116
    )
    workflow.plan["unrelatedHeartbeat"] = 42
    unchanged = project_workflow(workflow, {}, "compare", "changes", 0, 25)
    assert unchanged["plan"]["pagination"]["revision"] == page["revision"]


def large_workflow(count=OBJECT_COUNT):
    suggestions, rows, edits = [], [], []
    for index in range(count):
        identifier = hashlib.sha256(str(index).encode()).hexdigest()[:24]
        suggestions.append(
            {
                "id": identifier,
                "kind": "multi_element",
                "element": "lithology",
                "featureId": str(index),
                "ruleId": "L-01",
                "action": "remove",
                "status": "suggested",
                "reason": f"对象{index}完整原因",
                "preview": {
                    "type": "Polygon",
                    "coordinates": [
                        [[98, 35], [98.001, 35], [98.001, 35.001], [98, 35]]
                    ],
                },
            }
        )
        edit = {
            "feature_id": str(index),
            "rule_id": "L-01",
            "action": "remove",
            "weight": 1,
            "target_code": "",
        }
        edits.append(edit)
        rows.append(
            {
                **edit,
                "weight": "1.0",
                "actual_changed": "True",
                "new_code": "",
                "issue_id": identifier,
            }
        )
    plan = {
        "phase": "completed",
        "multiElementMap": {
            "before": {"lithology": 674, "faults": 675},
            "after": {"lithology": 680},
            "changes": [688],
        },
        "modificationReview": {
            "proposalHash": "frozen",
            "suggestions": suggestions,
            "approvedSuggestionIds": [item["id"] for item in suggestions],
            "unapprovedSuggestionIds": [],
        },
        "stages": [
            {
                "name": "apply",
                "taskId": "real-task",
                "status": "completed",
                "approvedEdits": edits,
                "modelRequestPayload": "large" * 12000000,
                "results": [
                    {
                        "key": "changes",
                        "taskId": "real-task",
                        "outputId": 1,
                        "checksum": "a" * 64,
                        "scope": "all",
                        "rowCount": count,
                        "rows": rows,
                    }
                ],
            }
        ],
    }
    return SimpleNamespace(
        plan=plan, parameters={}, steps=SimpleNamespace(count=lambda: 0)
    )


def test_compare_first_request_is_bounded_and_pages_use_only_actual_approved_changes():
    workflow = large_workflow()
    metadata = project_workflow(workflow, {}, "compare", "changes", 0, 0)
    assert metadata["plan"]["pagination"]["total"] == OBJECT_COUNT
    assert not metadata["plan"]["compareFeatures"]["features"]
    size = len(json.dumps(metadata).encode())
    zipped = len(gzip.compress(json.dumps(metadata).encode()))
    assert size < 100 * 1024
    assert zipped < 100 * 1024
    page = project_workflow(workflow, {}, "compare", "changes", 25, 25)
    assert len(page["modificationReview"]["suggestions"]) == 25
    assert page["plan"]["stages"][0]["results"][0]["rows"][0]["_rowIndex"] == 26
    assert "modelRequestPayload" not in page["plan"]["stages"][0]
    assert "large" * 100 not in json.dumps(page)
    workflow.plan["stages"][0]["results"][0]["rows"][0]["actual_changed"] = "False"
    workflow.plan["modificationReview"]["approvedSuggestionIds"].pop()
    updated = project_workflow(workflow, {}, "compare", "changes", 0, 25)
    assert updated["plan"]["pagination"]["total"] == OBJECT_COUNT - 2
    print(
        f"compare-summary: {size} bytes / gzip {zipped} bytes; page25 gzip {len(gzip.compress(json.dumps(page).encode()))} bytes"
    )
    inspection = project_workflow(workflow, {}, "inspection", "suggestions", 0, 50)
    inspection_bytes = json.dumps(inspection).encode()
    print(
        f"inspection-50: {len(inspection_bytes)} bytes / gzip {len(gzip.compress(inspection_bytes))} bytes"
    )


def test_inspection_pages_do_not_mutate_frozen_suggestions():
    workflow = large_workflow(60)
    held = workflow.plan["modificationReview"]["suggestions"][-1]
    held.update(
        status="exception", candidateAction="remove", observations={"confidence": 0.9}
    )
    original = copy.deepcopy(workflow.plan["modificationReview"])
    projected = project_workflow(workflow, {}, "inspection", "suggestions", 50, 10)
    index = projected["plan"]["reviewIndex"]
    assert len(index["suggestedIds"]) == 59
    assert index["candidateIds"] == [held["id"]]
    assert index["groups"][-1]["reasons"] == {"置信度≥0.8，规则例外候选": 1}
    assert len(projected["modificationReview"]["suggestions"]) == 10
    assert (
        projected["modificationReview"]["suggestions"][0]["preview"]["coordinates"]
        == []
    )
    assert workflow.plan["modificationReview"] == original


def test_pending_object_can_be_located_without_claiming_approval_or_actual_changes():
    workflow = large_workflow(60)
    workflow.plan["phase"] = "review_modifications"
    workflow.plan["modificationReview"]["approvedSuggestionIds"] = []
    target = workflow.plan["modificationReview"]["suggestions"][-1]
    page = project_workflow(workflow, {}, "compare", "changes", 0, 25, target["id"])
    assert page["plan"]["pagination"]["total"] == 0
    assert page["modificationReview"]["suggestions"][0]["id"] == target["id"]
    assert page["modificationReview"]["approvedSuggestionIds"] == []
    assert page["plan"]["compareFeatures"]["features"] == []


@pytest.mark.parametrize(
    "query", [{"limit": "51"}, {"offset": "-1"}, {"limit": "NaN"}, {"part": "steps"}]
)
def test_invalid_compare_page(query):
    from apps.agent.views import ApiProblem

    with pytest.raises(ApiProblem):
        page_options(query, "compare")
