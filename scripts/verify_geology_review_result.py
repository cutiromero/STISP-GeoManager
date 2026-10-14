"""Independent acceptance: never import this module or its reference into runtime."""

import argparse
import csv
import json
from pathlib import Path

import geopandas as gpd


def verify(
    initial, reference, corrected, changes, statistics, differences, workflow, output
):
    before = gpd.read_file(initial).to_crs(32646).set_index("feature_id")
    truth = gpd.read_file(reference).to_crs(32646).set_index("feature_id")
    after = gpd.read_file(corrected).to_crs(32646).set_index("feature_id")
    diff = gpd.read_file(differences).to_crs(32646)
    with changes.open(encoding="utf-8-sig", newline="") as stream:
        logs = list(csv.DictReader(stream))
    with statistics.open(encoding="utf-8-sig", newline="") as stream:
        stats = list(csv.DictReader(stream))
    assert logs and set(before.index) == set(truth.index) == set(after.index)
    assert len(diff) == len(logs)
    assert after.geometry.is_valid.all()
    accepted = {(row["feature_id"], row["kind"]): row for row in logs}
    assert len(accepted) == len(logs)
    flow = json.loads(workflow.read_text(encoding="utf-8-sig"))
    assert (
        flow["status"] == "succeeded" and flow["workflowType"] == "geology_map_review"
    )
    review = flow["modificationReview"]
    approved_ids = review["approvedSuggestionIds"]
    proposals = [item for item in review["suggestions"] if item["id"] in approved_ids]
    assert approved_ids and len(proposals) == len(approved_ids)
    assert {(item["featureId"], item["kind"]) for item in proposals} == set(accepted)
    edit_stage = next(
        item
        for item in flow["plan"]["stages"]
        if item["identifier"] == "geology-map-correct"
    )
    approval = edit_stage["modificationsApproval"]
    assert approval["selectedSuggestionIds"] == approved_ids
    assert approval["proposalHash"] == review["proposalHash"]
    assert any(
        step["kind"] == "modifications_approved"
        and step["status"] == "succeeded"
        and step["action"] == approval
        for step in flow["steps"]
    )
    expected_logs = {row["issue_id"]: row for row in edit_stage["approvedEdits"]}
    assert {row["issue_id"] for row in logs} == set(expected_logs)
    for row in logs:
        expected = expected_logs[row["issue_id"]]
        for key in (
            "feature_id",
            "kind",
            "field",
            "old_value",
            "new_value",
            "rule_id",
            "evidence_id",
            "input_checksum",
        ):
            assert row[key] == str(expected[key]), (row["issue_id"], key)
    unchanged, restored, areas = [], [], {}
    for identity in before.index:
        old, new, expected = (
            before.loc[identity],
            after.loc[identity],
            truth.loc[identity],
        )
        for key in ("class", "name", "code", "path", "formation", "region"):
            assert str(old[key]) == str(new[key]), (identity, key)
        fill = accepted.get((identity, "fill_gap"))
        age = accepted.get((identity, "set_age"))
        expected_geometry = expected.geometry if fill else old.geometry
        geometry_error = expected_geometry.symmetric_difference(new.geometry).area
        assert geometry_error < 0.02, (identity, geometry_error)
        expected_age = str(expected.geologic_age if age else old.geologic_age)
        assert str(new.geologic_age) == expected_age
        if not fill and not age:
            unchanged.append(identity)
        else:
            restored.append(identity)
        if fill:
            real_change = old.geometry.symmetric_difference(new.geometry)
            missing = expected.geometry.difference(old.geometry)
            assert real_change.symmetric_difference(missing).area < 0.02
            assert abs(real_change.area - float(fill["area_m2"])) < 0.02
            areas[identity] = real_change.area
    for _, row in diff.iterrows():
        key = str(row.feature_id), str(row.kind)
        assert key in accepted
        original = before.loc[key[0]].geometry
        result = after.loc[key[0]].geometry
        expected_diff = (
            original.symmetric_difference(result) if key[1] == "fill_gap" else original
        )
        assert row.geometry.symmetric_difference(expected_diff).area < 0.02
    grouped = before.groupby("class").geometry.apply(lambda series: series.area.sum())
    grouped_after = after.groupby("class").geometry.apply(
        lambda series: series.area.sum()
    )
    assert {int(row["class"]) for row in stats} == set(grouped.index)
    for row in stats:
        key = int(row["class"])
        assert abs(float(row["before_area_m2"]) - grouped[key]) < 0.02
        assert abs(float(row["after_area_m2"]) - grouped_after[key]) < 0.02
    receipt = {
        "passed": True,
        "modifiedFeatures": restored,
        "unchangedFeatures": unchanged,
        "actualFilledAreaM2": sum(areas.values()),
        "operationCount": len(logs),
        "stableClasses": sorted(int(value) for value in grouped.index),
        "scope": "依据真实批准记录独立检验选中操作、获批问题恢复、未获批对象保持、差异图层与按class重算统计一致",
        "referenceUsedByRuntime": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for key in (
        "initial",
        "reference",
        "corrected",
        "changes",
        "statistics",
        "differences",
        "workflow",
        "output",
    ):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    verify(**vars(args))
