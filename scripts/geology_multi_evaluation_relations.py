"""Measured contact graphs and independent geometric controls, not field claims."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from geology_multi_evaluation_metrics import counts, write_csv


def contact_edges(frame: gpd.GeoDataFrame, minimum_length: float = 1.0) -> dict:
    """Shared line contacts by normalized unit pair; a point contact is excluded."""
    dissolved = gpd.GeoDataFrame(
        [
            {"code": str(code), "geometry": unary_union(group.geometry)}
            for code, group in frame.groupby("geo_sym")
        ],
        geometry="geometry",
        crs=frame.crs,
    ).reset_index(drop=True)
    result = {}
    for first, row in dissolved.iterrows():
        for second in dissolved.sindex.query(row.geometry, predicate="intersects"):
            if first >= second:
                continue
            other = dissolved.iloc[second]
            shared = row.geometry.boundary.intersection(other.geometry.boundary)
            if shared.length > minimum_length:
                pair = tuple(sorted((row.code, other.code)))
                result[pair] = shared
    return result


def contact_comparison(
    actual: gpd.GeoDataFrame,
    reference: gpd.GeoDataFrame,
    units: dict,
    output: Path,
    tolerance: float = 0.5,
) -> dict:
    actual_edges, reference_edges = contact_edges(actual), contact_edges(reference)
    rows = []
    reference_length = predicted_length = matched_reference = matched_predicted = 0.0
    for pair in sorted(set(actual_edges) | set(reference_edges)):
        predicted, expected = actual_edges.get(pair), reference_edges.get(pair)
        observed_length = float(predicted.length) if predicted is not None else 0.0
        expected_length = float(expected.length) if expected is not None else 0.0
        covered_prediction = (
            float(predicted.intersection(expected.buffer(tolerance)).length)
            if predicted is not None and expected is not None
            else 0.0
        )
        covered_reference = (
            float(expected.intersection(predicted.buffer(tolerance)).length)
            if predicted is not None and expected is not None
            else 0.0
        )
        first_category = units.get(pair[0], {}).get("category", "unknown")
        second_category = units.get(pair[1], {}).get("category", "unknown")
        rows.append(
            {
                "first_code": pair[0],
                "second_code": pair[1],
                "first_category": first_category,
                "second_category": second_category,
                "reference_shared_line_m": expected_length,
                "observed_shared_line_m": observed_length,
                "same_pair_reference_covered_m": covered_reference,
                "same_pair_observed_supported_m": covered_prediction,
            }
        )
        reference_length += expected_length
        predicted_length += observed_length
        matched_reference += covered_reference
        matched_predicted += covered_prediction
    write_csv(output, rows)
    pair_scores = counts(set(reference_edges), set(actual_edges))
    category_scores = []
    categories = {
        "地层与地层的线接触": lambda pair: all(
            units.get(code, {}).get("category") == "stratum" for code in pair
        ),
        "侵入岩与地层的线接触": lambda pair: (
            {units.get(code, {}).get("category") for code in pair}
            == {"stratum", "intrusive"}
        ),
        "侵入岩与侵入岩的线接触": lambda pair: all(
            units.get(code, {}).get("category") == "intrusive" for code in pair
        ),
    }
    for title, predicate in categories.items():
        category_scores.append(
            {
                "test_item": title,
                **counts(
                    {pair for pair in reference_edges if predicate(pair)},
                    {pair for pair in actual_edges if predicate(pair)},
                ),
            }
        )
    return {
        "testItem": "不同地质单元的实际共享线接触图与独立参照对照",
        "minimumSharedLineM": 1.0,
        "matchingToleranceM": tolerance,
        "contactPairMetrics": pair_scores,
        "categoryMetrics": category_scores,
        "referenceContactLengthM": reference_length,
        "observedContactLengthM": predicted_length,
        "lengthRecall": matched_reference / reference_length
        if reference_length
        else None,
        "lengthPrecision": matched_predicted / predicted_length
        if predicted_length
        else None,
        "reference": "原始地质图，仅在正常检查结束后用于独立几何与标签对照。",
        "scope": "评价共享线位置及单元标签对是否一致；不判定接触性质、真实年代关系或岩体演化。",
        "file": output.name,
    }


def line_relation(line: LineString, first: object, second: object) -> dict:
    shared = first.boundary.intersection(second.boundary)
    along = line.intersection(shared).length
    first_interior = line.intersection(first.buffer(-0.001)).length
    second_interior = line.intersection(second.buffer(-0.001)).length
    return {
        "alongBoundaryM": float(along),
        "firstInteriorM": float(first_interior),
        "secondInteriorM": float(second_interior),
        "crossesBothInteriors": first_interior > 1
        and second_interior > 1
        and along < 0.01,
    }


def independent_controls(lithology_checker: object, rule: dict) -> dict:
    first, second, corner = (
        box(0, 0, 1000, 1000),
        box(1000, 0, 2000, 1000),
        box(1000, 1000, 2000, 2000),
    )
    normal_contact = gpd.GeoDataFrame(
        {"geo_sym": ["A", "B"]}, geometry=[first, second], crs=32646
    )
    point_contact = gpd.GeoDataFrame(
        {"geo_sym": ["A", "B"]}, geometry=[first, corner], crs=32646
    )
    along = line_relation(LineString([(1000, 100), (1000, 900)]), first, second)
    crossing = line_relation(LineString([(500, 500), (1500, 500)]), first, second)
    island = box(300, 300, 600, 600)
    lithology = gpd.GeoDataFrame(
        {
            "feature_id": ["C-001", "C-002"],
            "name": ["metamorphic", "volcanic"],
            "geo_sym": ["M", "V"],
            "conf": [0.95, 0.98],
            "confidence_kind": ["模拟分类置信度"] * 2,
        },
        geometry=[first.difference(island), island],
        crs=32646,
    )
    faults = gpd.GeoDataFrame({"line_id": []}, geometry=[], crs=32646)
    units = {
        "M": {"group": "metamorphic_high", "category": "stratum", "age_ma": 2000},
        "V": {"group": "volcanic", "category": "stratum", "age_ma": 200},
    }
    rule = deepcopy(rule)
    rule["params"]["report_conf_max"] = 0.86
    findings = lithology_checker(
        lithology,
        faults,
        first,
        {"L-04": rule},
        units,
        {"metamorphic": "M", "volcanic": "V"},
        "independent-control",
        {"working_epsg": 32646},
    )
    high_confidence = [row for row in findings if row["feature_id"] == "C-002"]
    checks = {
        "pointContactIsNotLineContact": not contact_edges(point_contact),
        "sharedLineDetected": abs(
            contact_edges(normal_contact)[("A", "B")].length - 1000
        )
        < 1e-8,
        "alongBoundaryIsNotCrossCut": not along["crossesBothInteriors"]
        and along["alongBoundaryM"] == 800,
        "crossingHasTwoInteriors": crossing["crossesBothInteriors"],
        "coexistenceExceptionRetained": len(high_confidence) == 1
        and high_confidence[0]["status"] == "exception"
        and high_confidence[0]["suggested_action"] == "review",
    }
    if not all(checks.values()):
        raise AssertionError(
            "Independent geometric control failed: " + json.dumps(checks)
        )
    return {
        "status": "passed",
        "checks": checks,
        "alongBoundary": along,
        "crossing": crossing,
        "scope": "小型独立合成几何，仅验证点/线接触、沿界/穿越区分和高置信度例外保留，不表示完整专业关系判断。",
    }


def structure_measurement_rows(findings: list[dict], labels: dict) -> list[dict]:
    measured = {}
    for row in findings:
        if row["element"] != "structure":
            continue
        identifier = row["feature_id"]
        item = measured.setdefault(identifier, {"rules": [], "measurements": {}})
        item["rules"].append(row["rule_id"])
        item["measurements"].update(json.loads(row["measurements_json"]))
    rows = []
    for identifier in sorted(set(labels["structure"]) | set(measured)):
        item = measured.get(identifier, {"rules": [], "measurements": {}})
        values = item["measurements"]
        rows.append(
            {
                "line_id": identifier,
                "independent_simulation_type": labels["structure"].get(
                    identifier, "参照正常线"
                ),
                "actual_reported_rules": ",".join(sorted(item["rules"])),
                **{
                    key: values.get(key, "")
                    for key in (
                        "length_m",
                        "cover_ratio",
                        "endpoints_in_cover",
                        "boundary_ratio",
                        "sinuosity",
                        "neighbour_count",
                        "turn_count",
                    )
                },
            }
        )
    return rows
