"""Independent-evaluation boundaries and stable scoring semantics."""

import json
from pathlib import Path
import sys

import pytest
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geology_multi_evaluation import OperatorContext, threshold_rules
from geology_multi_evaluation_data import (
    GENERATOR_CONSTANTS,
    GENERATOR_FUNCTIONS,
    pure_generators,
    sha256,
    source_fingerprints,
)
from geology_multi_evaluation_metrics import (
    calibrate,
    counts,
    read_csv,
    score_relations,
    selected,
    structure_overall,
    write_csv,
)
from geology_multi_evaluation_prepare import candidate_split
from geology_multi_evaluation_relations import (
    contact_comparison,
    contact_edges,
    line_relation,
)
from geology_multi_evaluation_publish import publish_dto, scalar
from geology_multi_evaluation_verify import unchanged_geometry, verify_merge
import geopandas as gpd
from shapely.geometry import LineString


def finding(identifier, rule, confidence=0.7, status="review"):
    return {
        "feature_id": identifier,
        "rule_id": rule,
        "status": status,
        "measurements_json": json.dumps({"simulation_confidence": confidence}),
    }


def test_source_module_top_level_is_never_executed(tmp_path):
    source = tmp_path / "source.py"
    nodes = [f"{name} = {{}}" for name in GENERATOR_CONSTANTS]
    nodes.extend(
        f"def {name}():\n    return 'selected'" for name in GENERATOR_FUNCTIONS
    )
    marker = tmp_path / "should-not-exist"
    nodes.extend(
        [
            f"open({str(marker)!r}, 'w').write('bad')",
            "raise RuntimeError('top-level executed')",
        ]
    )
    source.write_text("\n".join(nodes), encoding="utf-8")
    loaded = pure_generators(source)
    assert loaded.simulate_lithology() == "selected"
    assert not marker.exists()


def test_generator_constant_cannot_execute_call(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("LITHO_INJECTION = print('unsafe')", encoding="utf-8")
    with pytest.raises(ValueError):
        pure_generators(source)


def test_operator_context_rejects_private_reference(tmp_path):
    with pytest.raises(ValueError, match="reference"):
        OperatorContext(
            tmp_path / "task", {"lithology": tmp_path / "private/reference.gpkg"}
        )


def test_operator_output_cannot_escape_task(tmp_path):
    context = OperatorContext(tmp_path / "task", {})
    with pytest.raises(ValueError, match="task-local"):
        context.output_path("../elsewhere")


def test_source_checksums_detect_change_without_rewriting(tmp_path):
    source = tmp_path / "original"
    source.mkdir()
    item = source / "source.txt"
    item.write_text("original", encoding="utf-8")
    (source / "SHA256SUMS.txt").write_text(
        f"{sha256(item)}  source.txt\n", encoding="utf-8"
    )
    assert len(source_fingerprints(source)) == 1
    item.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        source_fingerprints(source)


def test_l03_is_attribute_check_not_geological_contact():
    labels = {"lithology": {"a": "L-01", "b": "L-03"}, "structure": {}}
    result = score_relations([finding("a", "L-01"), finding("b", "L-03")], labels)
    contact = next(row for row in result if row["relation"] == "地层接触")
    attributes = next(row for row in result if row["relation"] == "属性一致性")
    assert contact["expected"] == contact["tp"] == 1
    assert attributes["expected"] == attributes["tp"] == 1
    assert "L-03" not in contact["rules"]
    assert not contact["complete_geological_relation_validation"]


def test_missing_predictions_are_undefined_precision_not_perfect():
    result = counts({"a"}, set())
    assert result["recall"] == 0
    assert result["precision"] is None
    assert result["fn"] == 1


def test_structure_overall_retains_uncovered_abnormal_lines():
    labels = {"lithology": {}, "structure": {"a": "S-01", "b": "S-UNSUPPORTED"}}
    all_lines, covered = structure_overall([finding("a", "S-01")], labels)
    assert all_lines["recall"] == 0.5
    assert covered["recall"] == 1.0


def test_threshold_changes_candidate_reporting_not_actual_edits():
    findings = [
        finding("a", "L-02", 0.82, "exception"),
        finding("b", "L-02", 0.95, "exception"),
    ]
    assert [row["feature_id"] for row in selected(findings, 0.84)] == ["a"]
    assert len(selected(findings, 1.01)) == 2


def test_calibration_uses_spatial_rules_and_explicit_unmet_targets():
    labels = {"lithology": {"a": "L-01", "b": "L-02", "c": "L-04"}, "structure": {}}
    threshold, scan, objective = calibrate([finding("a", "L-01", 0.7)], labels)
    assert 0.5 <= threshold <= 0.98
    assert scan
    assert objective["allTargetsMet"] is False
    assert objective["selectionReadTestLabels"] is False


def test_threshold_changes_only_confidence_parameters(tmp_path):
    source, target = tmp_path / "rules.csv", tmp_path / "frozen.csv"
    write_csv(
        source,
        [
            {
                "rule_id": "L-02",
                "params_json": '{"report_conf_max": 0.8, "max_area_km2": 3}',
                "rule_version": "v1",
            },
            {
                "rule_id": "S-01",
                "params_json": '{"cover_ratio": 0.8}',
                "rule_version": "v1",
            },
        ],
    )
    threshold_rules(source, target, 0.84)
    changed = read_csv(target)
    assert json.loads(changed[0]["params_json"]) == {
        "report_conf_max": 0.84,
        "max_area_km2": 3,
    }
    assert changed[1] == read_csv(source)[1]
    assert changed[0]["rule_version"] == "v1"


@pytest.mark.parametrize("vertical", [True, False])
def test_cartographic_split_preserves_classifiable_footprint(vertical):
    original = box(300000, 4000000, 302000, 4001500)
    first, second, shared = candidate_split(original, vertical)
    assert first.union(second).symmetric_difference(original).area < 1e-7
    assert first.intersection(second).area == 0
    assert shared.length > 100
    assert min(first.area, second.area) >= original.area * 0.25


def test_contact_graph_does_not_count_corner_touch():
    frame = gpd.GeoDataFrame(
        {"geo_sym": ["A", "B"]},
        geometry=[box(0, 0, 100, 100), box(100, 100, 200, 200)],
        crs=32646,
    )
    assert not contact_edges(frame)


def test_shared_line_metrics_compare_actual_geometry_and_unit_pairs(tmp_path):
    reference = gpd.GeoDataFrame(
        {"geo_sym": ["A", "B"]},
        geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100)],
        crs=32646,
    )
    actual = reference.copy()
    actual.loc[actual.geo_sym == "B", "geo_sym"] = "C"
    result = contact_comparison(actual, reference, {}, tmp_path / "contacts.csv")
    assert result["contactPairMetrics"]["tp"] == 0
    assert result["contactPairMetrics"]["fp"] == 1
    assert result["contactPairMetrics"]["fn"] == 1
    assert result["referenceContactLengthM"] == 100
    assert result["lengthPrecision"] == 0


def test_along_boundary_is_not_cross_cutting():
    first, second = box(0, 0, 100, 100), box(100, 0, 200, 100)
    along = line_relation(LineString([(100, 10), (100, 90)]), first, second)
    crossing = line_relation(LineString([(50, 50), (150, 50)]), first, second)
    assert along["alongBoundaryM"] == 80
    assert not along["crossesBothInteriors"]
    assert crossing["crossesBothInteriors"]


def test_real_merge_verifier_keeps_area_categories_and_normal_object(tmp_path):
    before = gpd.GeoDataFrame(
        {
            "feature_id": ["G1", "G2", "G3"],
            "name": ["same", "same", "normal"],
            "geo_sym": ["S", "S", "N"],
        },
        geometry=[
            box(0, 0, 500, 1000),
            box(500, 0, 1000, 1000),
            box(1000, 0, 2000, 1000),
        ],
        crs=32646,
    )
    after = before.iloc[[1, 2]].copy()
    after.loc[after.feature_id == "G2", "geometry"] = box(0, 0, 1000, 1000)
    before_path, after_path = tmp_path / "before.gpkg", tmp_path / "after.gpkg"
    before.to_file(before_path, layer="data", index=False)
    after.to_file(after_path, layer="data", index=False)
    private = tmp_path / "private"
    private.mkdir()
    gpd.GeoDataFrame(
        {"id": ["parent"]}, geometry=[box(0, 0, 1000, 1000)], crs=32646
    ).to_file(private / "retained-parent.gpkg", layer="data", index=False)
    preparation = private / "preparation.json"
    preparation.write_text(json.dumps({"preparedIds": ["G1", "G2"]}), encoding="utf-8")
    changes = tmp_path / "changes.csv"
    write_csv(
        changes,
        [
            {
                "action": "merge",
                "rule_id": "L-05",
                "feature_id": "G1",
                "host_feature_id": "G2",
                "actual_changed": "True",
                "measurements_json": "{}",
                "removed_internal_boundary_m": 1000,
                "involved_area_m2": 1000000,
                "class_change_area_m2": 0,
                "geometry_change_area_m2": 0,
            }
        ],
    )
    result = verify_merge(
        before_path, after_path, changes, preparation, tmp_path / "verification.json"
    )
    assert result["status"] == "passed"
    assert result["unapprovedObjectsUnchanged"] == 1
    assert result["geometricFootprintChangeAreaM2"] == 0
    assert result["classificationChangeAreaM2"] == 0


def test_storage_rounding_is_distinct_from_unapproved_geometry_edit():
    original = box(300000, 4000000, 301000, 4001000)
    rounding = box(300000.0000009, 4000000, 301000, 4001000)
    actual_edit = box(300000.001, 4000000, 301000, 4001000)
    assert unchanged_geometry(original, rounding)
    assert not unchanged_geometry(original, actual_edit)


def test_publish_scalar_preserves_only_json_scalar_values():
    assert scalar("") is None
    assert scalar("False") is False
    assert scalar("12") == 12
    assert scalar("0.34") == 0.34
    assert scalar("L-03") == "L-03"


def test_publish_dto_uses_actual_counts_versions_and_scalar_rows(tmp_path):
    result = {
        "executionStatus": "passed",
        "calibration": {
            "calibrationSeed": 72,
            "threshold": 0.73,
            "allTargetsMet": False,
        },
        "measuredSpatialRelations": {
            "contactGraph": {"contactPairMetrics": {"expected": 9, "reported": 8}},
            "independentControls": {
                "scope": "small controls",
                "checks": {"pointContactIsNotLineContact": True},
            },
        },
        "structureMetrics": [
            {"tp": 3, "expected": 5},
            {"tp": 3, "expected": 4},
        ],
    }
    (tmp_path / "evaluation-summary.json").write_text(
        json.dumps(result), encoding="utf-8"
    )
    snapshot = tmp_path / "operator-snapshot"
    snapshot.mkdir()
    (snapshot / "check-operator.yaml").write_text(
        '{"version": "9.8.7"}', encoding="utf-8"
    )
    for filename in (
        "metrics-by-rule.csv",
        "metrics-by-relation.csv",
        "confidence-calibration.csv",
        "structure-all-vs-covered.csv",
        "measured-contact-pairs.csv",
        "structure-measured-items.csv",
    ):
        write_csv(tmp_path / filename, [{"stage": "first", "recall": 0.5, "tp": 2}])
    dto = publish_dto(tmp_path)
    assert set(dto) == {"scope", "summary", "sections"}
    assert "9.8.7" in dto["summary"]
    assert "3/5" in dto["summary"] and "3/4" in dto["summary"]
    assert "0.73" in dto["summary"] and "未全部满足" in dto["summary"]
    assert len(dto["sections"]) == 7
    for section in dto["sections"]:
        assert set(section) == {"key", "title", "summary", "columns", "rows"}
        keys = {column["key"] for column in section["columns"]}
        for row in section["rows"]:
            assert set(row) == keys
            assert all(
                isinstance(value, (str, int, float, bool, type(None)))
                for value in row.values()
            )
    assert dto["sections"][0]["rows"][0]["recall"] == "50.00%"
    result["measuredSpatialRelations"]["independentControls"]["checks"][
        "pointContactIsNotLineContact"
    ] = False
    (tmp_path / "evaluation-summary.json").write_text(
        json.dumps(result), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="successfully"):
        publish_dto(tmp_path)
