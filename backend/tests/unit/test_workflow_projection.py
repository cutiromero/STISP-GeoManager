import copy
import gzip
import hashlib
import json
from types import SimpleNamespace

import pytest

from apps.agent.workflow_projection import page_options, project_workflow


OBJECT_COUNT = 5200


def test_compare_archive_change_exposes_only_affected_display_symbols():
    workflow = large_workflow(1)
    item = workflow.plan["modificationReview"]["suggestions"][0]
    item.update(
        ruleId="L-08",
        action="reclassify",
        observations={"scope": "anchored_cell_partition"},
    )
    stage = workflow.plan["stages"][0]
    edit = stage["approvedEdits"][0]
    edit.update(rule_id="L-08", action="reclassify", target_code="U005 / U030")
    row = stage["results"][0]["rows"][0]
    row.update(edit, old_code="U009", new_code="U005 / U030", host_feature_id="")
    workflow.plan["unitOverrides"] = {
        "units": {
            "U009": {
                "name": "八宝山组碎屑岩",
                "display_symbol": "Tb",
                "group": "clastic",
            },
            "U005": {"name": "全新世冲积物", "display_symbol": "Qhᵃˡ"},
            "U030": {"name": "贵德群砂砾岩", "display_symbol": "NG₁"},
            "U013": {"name": "另一个单元", "display_symbol": "Chxᵃ"},
        }
    }
    plan = project_workflow(workflow, {}, "compare", "changes", 0, 25)["plan"]
    props = plan["compareFeatures"]["features"][0]["properties"]
    assert props["archive_partition"] is True and props["host_feature_id"] == ""
    assert set(props["lithology_unit_labels"]) == {"U009", "U005", "U030"}
    assert props["lithology_unit_labels"]["U005"]["display_symbol"] == "Qhᵃˡ"
    assert "group" not in props["lithology_unit_labels"]["U009"]
    assert "unitOverrides" not in plan and "archive_partition" not in row


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
    assert index["groups"][-1]["reasons"] == {"置信度≥0.8，规则例外": 1}
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


def test_retained_map_contains_full_automatic_scope_across_manual_pages():
    workflow = large_workflow(241)
    suggestions = workflow.plan["modificationReview"]["suggestions"]
    automatic = [item["id"] for item in suggestions[:196]]
    for item in suggestions[196:]:
        item.update(status="review", candidateAction="remove")
    workflow.plan["retainedReview"] = {
        "automaticSuggestionIds": automatic,
        "retainedSuggestionIds": [item["id"] for item in suggestions[196:]],
    }
    # This is an initial review: there are no actual modifications yet.
    workflow.plan["stages"] = []
    a = project_workflow(workflow, {}, "inspection", "retained", 0, 25)
    b = project_workflow(workflow, {}, "inspection", "retained", 25, 25)
    assert len(a["modificationReview"]["suggestions"]) == 25
    assert len(b["modificationReview"]["suggestions"]) == 20
    positions = a["plan"]["reviewIndex"]["automaticMap"]
    assert positions == b["plan"]["reviewIndex"]["automaticMap"]
    assert positions["total"] == positions["locatedCount"] == 196
    assert sum(point["count"] for point in positions["points"]) == 196
    assert not set(a["plan"]["reviewIndex"]["candidateIds"]) & set(automatic)


def test_large_automatic_map_is_bounded_without_losing_count():
    from apps.agent.review_positions import automatic_positions

    workflow = large_workflow()
    items = workflow.plan["modificationReview"]["suggestions"]
    workflow.plan["retainedReview"] = {
        "automaticSuggestionIds": [item["id"] for item in items]
    }
    result = automatic_positions(workflow.plan)
    assert result["locatedCount"] == OBJECT_COUNT
    assert len(result["points"]) <= 256
    assert sum(point["count"] for point in result["points"]) == OBJECT_COUNT


@pytest.mark.parametrize("apply_in_progress", [True, False])
def test_auto_only_run_can_inspect_authorized_extent_and_nonactionable_findings(
    apply_in_progress,
):
    workflow = large_workflow(1)
    plan = workflow.plan
    auto = plan["modificationReview"]["suggestions"][0]
    apply = plan["stages"][0]
    apply["modificationsApproval"] = {
        "mode": "rule_authorized",
        "selectedSuggestionIds": [auto["id"]],
    }
    if apply_in_progress:
        plan["phase"] = "wait_compute"
        apply.pop("results")

    # These checks never created any executable approval suggestions.
    def issue(issue_id, feature, status):
        return {
            "issue_id": issue_id,
            "feature_id": feature,
            "rule_id": "L-01",
            "status": status,
            "reason": "缺少接触带证据",
            "element": "lithology",
            "geometry_json": json.dumps(auto["preview"]),
        }

    rows = [issue("held", "held-patch", "review"), issue("edited", "0", "exception")]
    plan["stages"].insert(
        0,
        {
            "name": "check",
            "results": [{"key": "issues", "scope": "all", "rowCount": 2, "rows": rows}],
        },
    )
    page = project_workflow(workflow, {}, "inspection", "retained", 0, 25)
    projected = page["modificationReview"]["suggestions"]
    assert projected[0]["featureId"] == "held-patch"
    assert projected[0]["action"] == "keep" and projected[0]["preview"]["coordinates"]
    assert projected[0]["bounds"] == [98, 35, 98.001, 35.001]
    assert projected[0]["knowledgeRefs"] == []
    assert [item["featureId"] for item in projected] == (
        ["held-patch", "0"] if apply_in_progress else ["held-patch"]
    )
    assert all("candidateAction" not in item for item in projected)
    assert page["plan"]["reviewIndex"]["candidateIds"] == []
    assert page["plan"]["reviewIndex"]["automaticMap"]["locatedCount"] == 1
    assert plan["modificationReview"]["suggestions"] == [auto]
