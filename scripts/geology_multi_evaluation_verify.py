"""Independently verify a real approved same-unit merge after the worker returns."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import set_precision
from shapely.ops import unary_union

from geology_multi_evaluation_data import sha256, write_json
from geology_multi_evaluation_metrics import area_agreement, read_csv


def normalized(geometry: object) -> object:
    return set_precision(geometry, 0.000001).normalize()


def unchanged_geometry(first: object, second: object) -> bool:
    """Accept only storage rounding below 10 micrometres and 0.01 square metre."""
    first, second = normalized(first), normalized(second)
    return first.equals_exact(second, 0.00001, normalize=True) and (
        first.symmetric_difference(second).area <= 0.01
    )


def verify_merge(
    before_path: Path,
    after_path: Path,
    changes_path: Path,
    preparation_path: Path,
    output: Path,
    independent_reference: Path | None = None,
) -> dict:
    if output.exists():
        raise ValueError("Verification evidence must not be overwritten")
    preparation = json.loads(preparation_path.read_text(encoding="utf-8"))
    before = gpd.read_file(before_path).to_crs(32646)
    after = gpd.read_file(after_path).to_crs(32646)
    changes = read_csv(changes_path)
    merges = [
        row for row in changes if row["action"] == "merge" and row["rule_id"] == "L-05"
    ]
    if len(merges) != 1:
        raise AssertionError("Expected one actual project cartographic merge")
    merge = merges[0]
    source, host = str(merge["feature_id"]), str(merge["host_feature_id"])
    if {source, host} != set(preparation["preparedIds"]):
        raise AssertionError("Actual merge differs from prepared cartographic pair")
    old, new = before.set_index("feature_id"), after.set_index("feature_id")
    if source in new.index or host not in new.index or len(after) != len(before) - 1:
        raise AssertionError("Merge did not remove exactly one redundant object")
    shared = old.loc[source].geometry.boundary.intersection(
        old.loc[host].geometry.boundary
    )
    if shared.length <= 1:
        raise AssertionError("Approved polygons did not have a real shared boundary")
    merged_before = unary_union([old.loc[source].geometry, old.loc[host].geometry])
    merge_difference = (
        normalized(merged_before)
        .symmetric_difference(normalized(new.loc[host].geometry))
        .area
    )
    if merge_difference > 0.01:
        raise AssertionError("Merge changed the approved pair outer footprint")
    for field in ("name", "geo_sym", "class", "code", "path", "geo_unit"):
        if field in before:
            if (
                old.loc[source][field] != old.loc[host][field]
                or new.loc[host][field] != old.loc[host][field]
            ):
                raise AssertionError(
                    "Merge changed or mixed classification field: " + field
                )
    footprint_difference = (
        normalized(unary_union(before.geometry))
        .symmetric_difference(normalized(unary_union(after.geometry)))
        .area
    )
    if footprint_difference > 0.01 or not after.geometry.is_valid.all():
        raise AssertionError("Output coverage or geometry is invalid")
    touched = {
        str(row["feature_id"])
        for row in changes
        if str(row.get("actual_changed", "")).lower() in {"true", "1"}
    }
    touched |= {str(row.get("host_feature_id", "")) for row in changes}
    unchanged = 0
    maximum_rounding_distance = 0.0
    maximum_rounding_area = 0.0
    common_fields = (set(before) & set(after)) - {"geometry", "feature_id"}
    for identifier in old.index:
        if identifier in touched:
            continue
        if identifier not in new.index:
            raise AssertionError("An unapproved object disappeared")
        first, second = old.loc[identifier], new.loc[identifier]
        if not unchanged_geometry(first.geometry, second.geometry):
            raise AssertionError("An unapproved geometry changed")
        first_geometry, second_geometry = (
            normalized(first.geometry),
            normalized(second.geometry),
        )
        maximum_rounding_distance = max(
            maximum_rounding_distance,
            first_geometry.hausdorff_distance(second_geometry),
        )
        maximum_rounding_area = max(
            maximum_rounding_area,
            first_geometry.symmetric_difference(second_geometry).area,
        )
        for field in common_fields:
            # None/NaN metadata is equivalent; string and numeric values stay exact.
            first_value, second_value = first[field], second[field]
            if pd.isna(first_value) and pd.isna(second_value):
                continue
            if first_value != second_value:
                raise AssertionError("Unapproved attribute changed: " + field)
        unchanged += 1
    retained_parent = gpd.read_file(
        preparation_path.parent / "retained-parent.gpkg"
    ).to_crs(32646)
    restoration_error = (
        normalized(unary_union(retained_parent.geometry))
        .symmetric_difference(normalized(new.loc[host].geometry))
        .area
    )
    if restoration_error > 0.01:
        raise AssertionError("Merged geometry differs from the private retained parent")
    measurement = json.loads(merge["measurements_json"])
    actual_removed_boundary = float(merge.get("removed_internal_boundary_m") or 0)
    if abs(actual_removed_boundary - shared.length) > 0.01:
        raise AssertionError(
            "Reported removed boundary differs from actual shared line"
        )
    if float(merge.get("class_change_area_m2") or 0) != 0:
        raise AssertionError("Same-unit merge was incorrectly counted as class change")
    if abs(float(merge.get("involved_area_m2") or 0) - merged_before.area) > 0.01:
        raise AssertionError("Reported involved area differs from the approved pair")
    if float(merge.get("geometry_change_area_m2") or 0) != 0:
        raise AssertionError(
            "Removing an internal line incorrectly changed footprint area"
        )
    result = {
        "status": "passed",
        "scope": "真实获批同类图斑融合的独立核验",
        "beforeCount": len(before),
        "afterCount": len(after),
        "unapprovedObjectsUnchanged": unchanged,
        "unchangedGeometryToleranceM": 0.00001,
        "unchangedGeometryAreaToleranceM2": 0.01,
        "maximumUnchangedCoordinateRoundingM": maximum_rounding_distance,
        "maximumUnchangedRoundingAreaM2": maximum_rounding_area,
        "removedInternalBoundaryM": shared.length,
        "involvedObjectAreaM2": merged_before.area,
        "sourceObjectAreaM2": old.loc[source].geometry.area,
        "geometricFootprintChangeAreaM2": merge_difference,
        "classificationChangeAreaM2": 0.0,
        "coverageSymmetricDifferenceM2": footprint_difference,
        "privateParentRestorationDifferenceM2": restoration_error,
        "measuredRuleEvidence": measurement,
        "referenceReadOnlyAfterNormalAlgorithm": True,
        "inputs": {
            "beforeSha256": sha256(before_path),
            "afterSha256": sha256(after_path),
            "changesSha256": sha256(changes_path),
            "preparationSha256": sha256(preparation_path),
        },
    }
    if independent_reference:
        reference = gpd.read_file(independent_reference)
        result["independentAreaLabelComparison"] = {
            "before": area_agreement(before, reference),
            "after": area_agreement(after, reference),
            "scope": "同一示范区模拟输入与独立地质参照的面积标签对照；不是矿产预测准确率。",
        }
    write_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "after", "changes", "preparation", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--independent-reference", type=Path)
    arguments = parser.parse_args()
    result = verify_merge(
        arguments.before,
        arguments.after,
        arguments.changes,
        arguments.preparation,
        arguments.output,
        arguments.independent_reference,
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "beforeCount",
                    "afterCount",
                    "unapprovedObjectsUnchanged",
                    "removedInternalBoundaryM",
                    "involvedObjectAreaM2",
                    "geometricFootprintChangeAreaM2",
                    "classificationChangeAreaM2",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
