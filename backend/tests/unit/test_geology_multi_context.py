"""Prompt evidence stays bounded without hiding real totals or approval bindings."""

import copy
import csv
import json
import math
import re
from types import SimpleNamespace

import pytest

from apps.agent.geology_multi_results import (
    model_knowledge,
    model_results,
    model_review,
    table_rows,
)
from apps.compute.packages import ComputeError

pytestmark = pytest.mark.unit


def test_raster_model_summary_aggregates_units_without_geometry_or_group_ids():
    rows = [
        {
            "group_id": f"AG-{index}",
            "rule_id": "A-05",
            "rule_version": "raster",
            "knowledge_id": "10",
            "knowledge_revision": "1",
            "mineral": "calcite",
            "unit_code": f"unit-{index}",
            "rock_group": "other",
            "boundary": "false",
            "suggested_action": "downweight",
            "status": "suggested",
            "pixel_count": "2",
            "area_m2": "200",
            "component_count": "1",
            "bbox_json": "[]",
            "representatives_json": "[]",
        }
        for index in range(1000)
    ]
    value = model_results(
        [{"key": "alteration_summary", "rows": rows}], stage_name="apply"
    )[0]
    summary = expand_table(value)
    assert len(summary) == 1
    assert summary[0]["group_count"] == 1000
    assert summary[0]["pixel_count"] == 2000
    assert summary[0]["area_m2"] == 200000
    assert summary[0]["unit_count"] == 1000
    assert len(summary[0]["unit_codes"]) == 20
    assert not {"group_id", "bbox_json", "representatives_json"} & set(summary[0])


def expand_table(table):
    if table.get("rowFormat") != "columns":
        return table["rows"]
    return [dict(zip(table["columns"], row, strict=True)) for row in table["rows"]]


def test_raster_review_summary_uses_frozen_user_action_not_original_recommendation():
    workflow = SimpleNamespace(
        plan={
            "modificationReview": {
                "proposalHash": "frozen",
                "approvedSuggestionIds": ["chosen"],
                "suggestions": [
                    {
                        "id": "chosen",
                        "featureId": "AG-stable",
                        "element": "alteration",
                        "ruleId": "A-01",
                        "action": "exclude",
                        "areaM2": 200,
                        "observations": {
                            "pixel_count": 2,
                            "mineral": "calcite",
                            "rock_group": "carbonate",
                            "boundary": False,
                        },
                    }
                ],
            },
            "stages": [
                {"name": "check", "results": []},
                {
                    "name": "apply",
                    "modificationsApproval": {
                        "alterationActions": {"AG-stable": "downweight"}
                    },
                },
            ],
        }
    )
    summary = model_review(workflow)
    assert summary["groups"][0]["action"] == "downweight"
    assert summary["groups"][0]["approvedCount"] == 1
    assert summary["groups"][0]["pixelCount"] == 2
    assert not summary["suggestions"]["rows"]


def expand_evidence(value, definitions):
    if isinstance(value, list):
        return [expand_evidence(item, definitions) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("rowFormat") == "columns":
        return expand_evidence(expand_table(value), definitions)
    return {
        key[:-3] if key.endswith("Ref") else key: (
            copy.deepcopy(definitions[item])
            if key.endswith("Ref")
            else expand_evidence(item, definitions)
        )
        for key, item in value.items()
        if key not in {"definitions", "referenceNote"}
    }


def write_table(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def evidence_row(index, phase, grade):
    measured = {
        "structure_supported_fraction": index / 200,
        "alteration_supported_fraction": 1,
        "favourable_fraction": 1 if grade == "A" else 0,
        "min_weighted_type_count": 2 + index / 100,
        "min_types_required": 2,
        "rule_expression": "alteration AND structure AND favourable"
        if grade == "A"
        else "alteration AND (structure OR favourable) AND NOT all_three",
    }
    citations = [
        {
            "rule_id": "P-03",
            "rule_version": "trial-1",
            "knowledge_id": 15,
            "knowledge_revision": 2,
        }
    ]
    context = {
        "minerals": ["calcite", "hematite"] if index % 2 else ["hematite", "chlorite"],
        "faults": [{"line_id": "same-fault", "weight": 1}] * 50,
        "intersections": [{"point_id": "same-point", "inferred": True}],
        "lithology_areas_m2": {"Tb": (index + 1) * 1e6},
    }
    return {
        "phase": phase,
        "zone_id": f"{grade}{index:03}",
        "grade": grade,
        "area_km2": index + 1,
        "explanation": "由当次规则计算形成的核查范围",
        "evidence_json": json.dumps(
            {
                "phase": phase,
                "grade_conditions": measured,
                "context": context,
                "knowledge": citations,
            }
        ),
        "conditions_json": json.dumps(measured),
        "faults": json.dumps(context["faults"]),
    }


def test_every_evidence_row_contributes_to_separate_phase_and_grade_totals(tmp_path):
    rows = [
        evidence_row(index, phase, grade)
        for index, (phase, grade) in enumerate(
            [("before", "A")] * 60
            + [("before", "B")] * 30
            + [("after", "A")] * 40
            + [("after", "B")] * 40
        )
    ]
    counts = {}
    for row in rows:
        group = row["phase"], row["grade"]
        counts[group] = counts.get(group, 0) + 1
        row["zone_id"] = f"{row['grade']}{counts[group]:03}"
    path = tmp_path / "evidence.csv"
    write_table(path, rows)
    reading = table_rows(path, "evidence")
    assert reading["rowCount"] == 170
    assert reading["scope"] == "representative_sample"
    assert len(reading["rows"]) == 8
    summary = reading["aggregate"]
    assert summary["scope"] == "all_rows"
    assert summary["rowCount"] == 170 and summary["countUnit"] == "zone"
    for group in summary["byPhaseAndGrade"]:
        actual = [
            row
            for row in rows
            if (row["phase"], row["grade"]) == (group["phase"], group["grade"])
        ]
        assert group["zoneCount"] == len(actual)
        assert group["areaKm2"] == math.fsum(row["area_km2"] for row in actual)
        values = [
            json.loads(row["evidence_json"])["grade_conditions"][
                "structure_supported_fraction"
            ]
            for row in actual
        ]
        assert group["measurementRanges"]["structure_supported_fraction"] == {
            "min": min(values),
            "max": max(values),
        }
    assert sum(group["zoneCount"] for group in summary["evidenceCombinations"]) == 170
    item = {
        "key": "evidence",
        "outputId": 9,
        "taskId": "task",
        "checksum": "a" * 64,
        **reading,
    }
    projected = model_results([item], stage_name="final_analysis")[0]
    definitions = projected["aggregate"]["definitions"]
    assert expand_evidence(projected["aggregate"], definitions) == summary
    assert projected["checksum"] == "a" * 64
    assert len(json.dumps(projected)) < 24000
    for row in expand_evidence(projected["rows"], definitions):
        assert "evidence_json" not in row and "conditions_json" not in row
        assert row["faultAssociations"] == 50
        assert row["inferredIntersectionAssociations"] == 1
    assert "完整对象证据" in projected["samplingNote"]


def test_invalid_row_after_first_forty_cannot_escape_all_row_aggregation(tmp_path):
    rows = [evidence_row(index, "before", "A") for index in range(50)]
    rows[-1]["area_km2"] = "NaN"
    path = tmp_path / "invalid.csv"
    write_table(path, rows)
    with pytest.raises(ComputeError, match="实测条件"):
        table_rows(path, "evidence")


@pytest.mark.parametrize("invalid", ["duplicate", "phase_conflict"])
def test_repeated_zone_or_conflicting_phase_is_rejected_before_aggregation(
    tmp_path, invalid
):
    first = evidence_row(0, "before", "A")
    second = evidence_row(1, "before", "A")
    if invalid == "duplicate":
        second["zone_id"] = first["zone_id"]
    else:
        second["phase"] = "after"
    path = tmp_path / "conflict.csv"
    write_table(path, [first, second])
    with pytest.raises(ComputeError):
        table_rows(path, "evidence")


@pytest.mark.parametrize("key", ["statistics", "changes"])
def test_statistics_and_changes_are_read_completely_past_forty_rows(tmp_path, key):
    path = tmp_path / f"{key}.csv"
    write_table(
        path, [{"field": str(index), "value": index + 1} for index in range(65)]
    )
    reading = table_rows(path, key)
    assert reading["scope"] == "all" and reading["rowCount"] == 65
    assert len(reading["rows"]) == 65
    if key == "changes":
        grouped = model_results([{"key": key, **reading}], stage_name="final_analysis")[
            0
        ]
        assert grouped["scope"] == "all_groups" and grouped["rows"][0]["count"] == 65
        return
    assert (
        expand_table(
            model_results([{"key": key, **reading}], stage_name="final_analysis")[0]
        )
        == reading["rows"]
    )


def test_only_apply_uses_issue_candidate_rows_and_all_other_stages_keep_full_references():
    item = {
        "key": "issues",
        "outputId": 15,
        "taskId": "check-task",
        "checksum": "b" * 64,
        "rowCount": 7357,
        "countsByRule": {"L-03": 3, "A-01": 7354},
        "scope": "representative_sample",
        "rows": [
            {
                "issue_id": "actual-issue",
                "measurements_json": '{"area_m2":5}',
                "geometry_json": "large-geometry",
            }
        ],
    }
    original = copy.deepcopy(item)
    apply = model_results([item], stage_name="apply")[0]
    assert apply["rows"] == []
    assert apply["groups"][0]["count"] == 1
    assert apply["groups"][0]["measurementRanges"] == {"area_m2": [5, 5]}
    assert "geometry_json" not in apply["groups"][0]["samples"][0]
    for name in ("recheck", "relations", "prospect", "final_analysis"):
        actual = model_results([item], stage_name=name)[0]
        assert actual["rows"] == [] and actual["scope"] == "reference_only"
        for key in ("outputId", "taskId", "checksum", "rowCount", "countsByRule"):
            assert actual[key] == item[key]
    assert item == original


def test_public_plan_retains_exact_approval_and_actual_changes_for_map_verification():
    from apps.agent.geology_multi_results import public_plan

    changes = {
        "key": "changes",
        "scope": "all",
        "rows": [{"feature_id": "F1", "action": "exclude"}],
        "rowCount": 1,
    }
    approved = [{"feature_id": "F1", "action": "exclude", "weight": 0}]
    plan = {
        "modificationReview": {"suggestions": []},
        "stages": [
            {
                "name": "apply",
                "approvedEdits": approved,
                "results": [changes],
                "edits": ["internal"],
                "modelRequestPayload": {"internal": "prompt"},
            }
        ],
    }
    saved = copy.deepcopy(plan)
    public = public_plan(plan)
    assert public["stages"][0]["approvedEdits"] == approved
    assert public["stages"][0]["results"][0] == changes
    assert "edits" not in public["stages"][0]
    assert "modelRequestPayload" not in public["stages"][0]
    assert "modificationReview" not in public
    assert plan == saved


@pytest.mark.parametrize("result", [{"rows": "legacy details"}, {"rows": []}])
def test_public_plan_preserves_results_without_a_grouping_key(result):
    from apps.agent.geology_multi_results import public_plan

    plan = {"stages": [{"name": "check", "results": [result]}]}
    saved = copy.deepcopy(plan)

    assert public_plan(plan)["stages"][0]["results"] == [result]
    assert plan == saved


def test_public_plan_groups_legacy_issues_without_grouping_fields():
    from apps.agent.geology_multi_results import public_plan

    rows = [{"issue_id": "legacy-issue", "feature_id": "legacy-feature"}]
    plan = {"stages": [{"name": "check", "results": [{"key": "issues", "rows": rows}]}]}
    saved = copy.deepcopy(plan)

    result = public_plan(plan)["stages"][0]["results"][0]

    assert result["rows"] == []
    assert result["scope"] == "all_groups"
    assert result["groups"][0]["count"] == 1
    assert result["groups"][0]["samples"][0]["issue_id"] == "legacy-issue"
    assert plan == saved


@pytest.mark.parametrize("location", ["stages", "finalStage"])
def test_public_plan_removes_private_batches_without_changing_public_facts(location):
    from apps.agent.geology_multi_results import public_plan

    stage = {
        "name": "apply" if location == "stages" else "final_analysis",
        "status": "completed",
        "decision": {"summary": "保留可见的决策说明"},
        "approvedEdits": [{"feature_id": "F00001", "action": "merge"}],
        "modificationsApproval": {"selectedIssueIds": ["chosen"]},
        "results": [{"key": "changes", "rows": [{"actual_changed": "True"}]}],
    }
    plan = {location: [stage] if location == "stages" else stage}
    baseline = public_plan(plan)
    for size in (1, 100000):
        secret = "private-model-audit" + "x" * size
        stage.update(
            edits=[secret],
            proposedEdits=[secret],
            modelRequestPayload={"members": secret},
            modelRequestInstruction=secret,
            modelAttempts=[{"response": secret}],
            modelBudgetHistory=[{"modelRequestPayload": secret}],
            modelBatches={
                "cursor": size,
                "memberCount": size,
                "batches": [
                    {
                        "scopeSha256": secret,
                        "stage": {
                            "modelRequestPayload": {"members": secret},
                            "modelAttempts": [{"response": secret}],
                            "unrequestedBudgetAttempts": [{"response": secret}],
                        },
                    }
                ],
            },
        )
        saved = copy.deepcopy(plan)
        assert public_plan(plan) == baseline
        assert "private-model-audit" not in json.dumps(public_plan(plan))
        assert plan == saved


def test_model_approval_retains_semantics_and_hashes_without_touching_map_or_saved_plan():
    workflow = SimpleNamespace(
        plan={
            "stages": [
                {
                    "name": "check",
                    "results": [
                        {
                            "key": "issues",
                            "outputId": 4,
                            "taskId": "original-check",
                            "checksum": "c" * 64,
                        }
                    ],
                }
            ],
            "modificationReview": {
                "proposalHash": "d" * 64,
                "approvedSuggestionIds": ["approved"],
                "unapprovedSuggestionIds": ["not-approved"],
                "suggestions": [
                    {
                        "id": name,
                        "featureId": f"object-{name}",
                        "action": "exclude",
                        "reason": "对应本轮规则及实际测量",
                        "observations": {"length_m": 300},
                        "preview": {"coordinates": [1, 2] * 10000},
                        "ruleConditions": ["完整前提在知识中"],
                        "exceptions": ["完整例外在知识中"],
                        "ruleRefs": [
                            {
                                "id": "S-01",
                                "version": "trial-1",
                                "knowledgeId": 25,
                                "revision": 2,
                                "source": "来源原文",
                            }
                        ],
                    }
                    for name in ("approved", "not-approved")
                ],
            },
        }
    )
    saved = copy.deepcopy(workflow.plan)
    review = model_review(workflow)
    assert review["proposalHash"] == "d" * 64
    assert review["approvedSuggestionIds"] == ["approved"]
    assert review["unapprovedSuggestionIds"] == ["not-approved"]
    assert review["sourceOutputs"][0]["checksum"] == "c" * 64
    suggestions = expand_table(review["suggestions"])
    assert all(
        "preview" not in suggestion and "ruleConditions" not in suggestion
        for suggestion in suggestions
    )
    assert suggestions[0]["ruleRefs"] == [
        {"id": "S-01", "version": "trial-1", "knowledgeId": 25, "revision": 2}
    ]
    assert len(json.dumps(review)) < 3000
    assert workflow.plan == saved


def test_repeated_metadata_refs_resolve_to_real_fields_and_preserve_complete_facts():
    quality = {
        "status": "passed",
        "summary": "真实完成检查",
        "metrics": {"before_count": 10, "after_count": 9, "area_m2": 123.456789012345},
    }
    items = [
        {
            "outputId": index,
            "taskId": "actual-task",
            "checksum": str(index) * 64,
            "key": "statistics" if index == 1 else "vector",
            "metadata": {
                "fields": ["field", "value"],
                "qualityCheck": quality,
                "knowledgeFacts": {"geologyMulti": quality["metrics"]},
            },
            "rows": [{"field": "count", "value": "10"}] if index == 1 else [],
            **({"columns": ["field", "value"]} if index == 1 else {}),
        }
        for index in (1, 2, 3)
    ]
    original = copy.deepcopy(items)
    projected = model_results(items, stage_name="final_analysis")
    outputs = {item["outputId"]: item for item in projected}

    def target(reference):
        value = outputs[reference["outputId"]]
        for part in reference["path"].split("."):
            value = value[part]
        return value

    for item in projected:
        metadata = item["metadata"]
        assert target(metadata["fieldsRef"]) == ["field", "value"]
        actual_quality = (
            metadata["qualityCheck"]
            if "qualityCheck" in metadata
            else target(metadata["qualityCheckRef"])
        )
        assert actual_quality == quality
        fact = metadata["knowledgeFactsRef"]
        assert {fact["scope"]: target(fact)} == original[0]["metadata"][
            "knowledgeFacts"
        ]
        assert item["taskId"] == "actual-task" and len(item["checksum"]) == 64
    assert items == original
    assert (
        model_results(
            [{"key": "vector", "metadata": {}, "rows": []}], stage_name="recheck"
        )[0]["metadata"]
        == {}
    )


def test_knowledge_same_as_refs_reconstruct_all_original_conditions_exceptions_and_sources():
    source = {
        "title": "实际知识来源",
        "locator": "原文第12页",
        "excerpt": "必须核对完整的区域和适用前提。" * 20,
    }
    entries = [
        {
            "id": index,
            "revision": index + 1,
            "statement": "图斑位于已核实的完整制图范围且被同一单元包围。" * 10,
            "conditions": [condition, "全部条件必须同时成立。" * 20],
            "exceptions": ["存在未调查区或构造窗时保留并核查。" * 20],
            "sources": [source],
            "ruleConfig": {
                "parameters": {"area": 12.34567890123456},
                "version": f"v{index}",
            },
        }
        for index, condition in enumerate(("地区甲的地层规则", "地区乙的侵入岩规则"), 1)
    ]
    original = copy.deepcopy(entries)
    projected = model_knowledge(entries)

    def expand(value, depth=0):
        assert depth < 30
        if isinstance(value, dict) and set(value) == {"sameAs"}:
            actual = projected
            for part in re.findall(r"\[([0-9]+)\]|\.([^.\[]+)", value["sameAs"]):
                actual = actual[int(part[0])] if part[0] else actual[part[1]]
            return expand(actual, depth + 1)
        if isinstance(value, dict):
            return {key: expand(item, depth + 1) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item, depth + 1) for item in value]
        return value

    assert expand(projected) == original
    assert entries == original
    assert projected[1]["conditions"][0] == "地区乙的侵入岩规则"
    assert len(json.dumps(projected)) < len(json.dumps(entries))
