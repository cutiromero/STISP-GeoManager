"""Real spatial calculations, approval binding and independent grade expectations."""

import csv
import io
import json
from pathlib import Path
import runpy
import sqlite3
import sys
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, box
from shapely.ops import unary_union
import yaml

from apps.compute.packages import validate_manifest
from apps.compute.quality import validate_report
from apps.catalog.importer import normalize_dataframe

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "examples/compute/geology-multi-core"
X, Y = 300000, 4000000
KEYS = ["hematite", "chlorite", "hydromica", "calcite", "dolomite"]


def test_raster_rule_registration_preserves_other_rules_and_parameters():
    import copy

    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        prepare = runpy.run_path(
            str(ROOT / "scripts/prepare_geology_complete_story.py")
        )
    finally:
        sys.path.pop(0)
    bundle = {
        "rules": [
            {
                "id": key,
                "version": "original",
                "condition": "unchanged",
                "action": "original",
                "params": {"threshold": 2},
                "basis": {"refs": ["original"]},
            }
            for key in (
                "L-01",
                "S-01",
                "P-01",
                "P-02",
                "A-01",
                "A-02",
                "A-03",
                "A-04",
                "A-05",
            )
        ]
    }
    original = copy.deepcopy(bundle)
    prepare["raster_rules"](bundle)
    for before, after in zip(original["rules"], bundle["rules"], strict=True):
        assert before["params"] == after["params"]
        if before["id"] in {"L-01", "S-01", "P-01"}:
            assert before == after
        else:
            assert after["version"] == "2026-11-05-raster-trial"
            assert after["basis"]["refs"] == before["basis"]["refs"]


@pytest.mark.parametrize("confidence,status", [(0.5, "suggested"), (0.9, "review")])
def test_alluvium_shape_candidate_approval_fuses_measured_host(
    tmp_path, confidence, status
):
    initial, original = fixture(tmp_path)
    original.loc[original.feature_id == "G3", "conf"] = confidence
    store(original, initial.inputs["lithology"])
    rows = read(initial.inputs["rules"])
    units = json.loads(rows[0]["units_json"])
    units["O"].update(category="cover", age_ma=0.005)
    units["C"].update(category="cover", age_ma=1.3)
    for row in rows:
        row["units_json"] = json.dumps(units)
    rows.append(
        {
            **rows[0],
            "rule_id": "L-06",
            "rule_version": "trial-shape-v1",
            "params_json": json.dumps(
                {
                    "source_codes": ["O"],
                    "compactness_min": 0.6,
                    "aspect_ratio_max": 1.5,
                    "conf_review_min": 0.88,
                }
            ),
            "rule_json": '{"id":"L-06"}',
        }
    )
    write(initial.inputs["rules"], rows)
    findings, _ = check(initial)
    item = next(
        row
        for row in findings
        if row["rule_id"] == "L-06" and row["feature_id"] == "G3"
    )
    assert item["status"] == status and item["target_code"] == "C"
    assert json.loads(item["measurements_json"])["compactness"] > 0.6
    if status == "review":
        assert (
            item["candidate_action"] == "reclassify"
            and item["candidate_target_code"] == "C"
        )
    edited = approval_context(
        tmp_path, initial, [item], {item["issue_id"]: "reclassify"}
    )
    load("apply")(edited)
    result = gpd.read_file(edited.output_path("lithology.gpkg"))
    assert "G3" not in set(result.feature_id)
    assert unary_union(result.geometry).equals(unary_union(original.geometry))
    changes = read(edited.output_path("changes.csv"))
    assert changes[0]["target_code"] == "C"
    if status == "review":
        assert changes[0]["reason"].startswith("用户裁定（规则为待裁定/例外）")
    approved = read(edited.inputs["approved_changes"])
    approved[0]["target_code"] = "forged"
    write(edited.inputs["approved_changes"], approved)
    with pytest.raises(ValueError, match="候选动作与目标|获批目标"):
        load("apply")(edited)


def test_continuity_trial_only_adds_review_for_isolated_older_unit(tmp_path):
    initial, original = fixture(tmp_path)
    rows = read(initial.inputs["rules"])
    template = rows[0]
    rows = [row for row in rows if row["rule_id"] != "L-01"]
    rows.append(
        {
            **template,
            "rule_id": "L-07",
            "rule_version": "trial-continuity-v1",
            "params_json": "{}",
            "rule_json": '{"id":"L-07"}',
        }
    )
    write(initial.inputs["rules"], rows)
    findings, _ = check(initial)
    item = next(row for row in findings if row["rule_id"] == "L-07")
    assert item["status"] == "review"
    assert (
        item["candidate_action"] == "reclassify"
        and item["candidate_target_code"] == "C"
    )
    assert json.loads(item["measurements_json"])["same_unit_neighbour_count"] == 0


class Context:
    def __init__(self, directory, inputs, parameters=None):
        self.directory, self.inputs = directory, inputs
        self.parameters = parameters or {"grid_resolution_m": 50, "min_zone_area_m2": 0}
        directory.mkdir(parents=True, exist_ok=True)

    def input_path(self, key):
        return self.inputs[key]

    def output_path(self, filename):
        return self.directory / filename


def load(suffix):
    sys.path.insert(0, str(CORE))
    try:
        return runpy.run_path(
            str(ROOT / f"examples/compute/geology-multi-{suffix}/main.py")
        )["run"]
    finally:
        sys.path.pop(0)


def rect(x0, y0, x1, y1):
    return box(X + x0, Y + y0, X + x1, Y + y1)


def store(frame, path):
    path.unlink(missing_ok=True)
    frame.to_file(path, layer="data", driver="GPKG", index=False)


def write(path, rows, fields=None):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def raster_inputs(initial, edited=None):
    result = {"before_" + key: initial.inputs[key] for key in KEYS}
    if edited:
        result.update({key: edited.output_path(key + "_corrected.tif") for key in KEYS})
        result.update(
            {key + "_weight": edited.output_path(key + "_weight.tif") for key in KEYS}
        )
    return result


def fixture(tmp_path):
    island, mismatch = rect(100, 100, 200, 200), rect(800, 800, 900, 900)
    lithology = gpd.GeoDataFrame(
        {
            "feature_id": ["G1", "G2", "G3", "G4"],
            "name": ["carbonate", "carbonate", "old", "carbonate"],
            "geo_sym": ["C", "C", "O", "O"],
            "conf": [0.9, 0.9, 0.5, 0.5],
            "confidence_kind": ["模拟分类置信度"] * 4,
        },
        geometry=[
            rect(0, 0, 500, 1000).difference(island),
            rect(500, 0, 1000, 1000).difference(mismatch),
            island,
            mismatch,
        ],
        crs=32646,
    )
    faults = gpd.GeoDataFrame(
        {"line_id": ["F1", "F2"]},
        geometry=[
            LineString([(X + 400, Y + 300), (X + 900, Y + 300)]),
            LineString([(X + 600, Y + 100), (X + 600, Y + 800)]),
        ],
        crs=32646,
    )
    coverage = gpd.GeoDataFrame(
        {"coverage_id": ["extent"]}, geometry=[rect(0, 0, 1000, 1000)], crs=32646
    )
    units = {
        "C": {
            "name": "carbonate",
            "category": "stratum",
            "age_ma": 200,
            "group": "carbonate",
            "favorable": False,
        },
        "O": {
            "name": "old",
            "category": "stratum",
            "age_ma": 500,
            "group": "clastic",
            "favorable": False,
        },
    }
    params = {
        "L-01": {"enclose_ratio": 0.95, "max_area_km2": 3, "fault_buffer_m": 50},
        "L-03": {},
        "S-01": {"cover_ratio": 0.8, "cover_units": []},
        "S-02": {"boundary_buffer_m": 20, "boundary_ratio": 0.8, "min_sinuosity": 1.15},
        "S-03": {"max_length_m": 100, "isolation_m": 50},
        "S-04": {"turn_angle": 100, "min_turns": 2},
        "S-05": {"snap_dist_m": 100, "max_angle": 45},
        "A-01": {"dominant_ratio": 0.5},
        "A-02": {"dominant_ratio": 0.5},
        "A-03": {"dominant_ratio": 0.5},
        "A-04": {"dominant_ratio": 0.5},
        "A-05": {"min_area_m2": 2600},
        "P-01": {
            "main_fault_min_length_m": 10000,
            "buffer_main_m": 500,
            "buffer_secondary_m": 100,
            "buffer_intersection_main_secondary_m": 100,
            "buffer_intersection_other_m": 100,
        },
        "P-02": {
            "search_m": 100,
            "min_types": 2,
            "alteration_types": [
                "赤铁矿化",
                "绿泥石化",
                "水云母化",
                "方解石化",
                "白云石化",
            ],
        },
        "P-03": {},
    }
    rows = [
        {
            "rule_id": key,
            "rule_version": "0.1-draft",
            "knowledge_id": str(index + 1),
            "knowledge_revision": "1",
            "params_json": json.dumps(value),
            "rule_json": json.dumps(
                {
                    "id": key,
                    "name": key,
                    "condition": "本区适用条件",
                    "status": "草拟",
                    "basis": {"gap": "保留地质例外"},
                }
            ),
            "units_json": json.dumps(units) if index == 0 else "",
            "aliases_json": json.dumps({"carbonate": "C", "old": "O"})
            if index == 0
            else "",
        }
        for index, (key, value) in enumerate(params.items())
    ]
    paths = {
        key: tmp_path / (key + ".gpkg") for key in ("lithology", "faults", "coverage")
    }
    for key, frame in [
        ("lithology", lithology),
        ("faults", faults),
        ("coverage", coverage),
    ]:
        store(frame, paths[key])
    paths["rules"] = tmp_path / "rules.csv"
    write(paths["rules"], rows)
    for key in KEYS:
        paths[key] = tmp_path / (key + ".tif")
        values = np.zeros((100, 100), dtype="uint8")
        if key in {"hematite", "chlorite"}:
            values[35:40, 60:65] = 1
        elif key == "calcite":
            values[30:40, 40:60] = 1
        with rasterio.open(
            paths[key],
            "w",
            driver="GTiff",
            width=100,
            height=100,
            count=1,
            dtype="uint8",
            crs=32646,
            transform=from_origin(X, Y + 1000, 10, 10),
            nodata=0,
        ) as stream:
            stream.write(values, 1)
    return Context(tmp_path / "check", paths), lithology


def check(context):
    load("check")(context)
    report = json.loads(context.output_path("quality.json").read_text(encoding="utf-8"))
    validate_report(report)
    return read(context.output_path("issues.csv")), report


def approval_context(tmp_path, initial, findings, actions=None):
    fields = [
        "issue_id",
        "feature_id",
        "rule_id",
        "rule_version",
        "snapshot_hash",
        "action",
        "target_code",
        "weight",
        "reason",
    ]
    rows = []
    for item in findings:
        action = (actions or {}).get(item["issue_id"], item["suggested_action"])
        rows.append(
            {key: item.get(key, "") for key in fields}
            | {
                "action": action,
                "target_code": item["target_code"]
                if action in {"set_code", "reclassify", "merge"}
                else "",
                "weight": "0.5"
                if action == "downweight"
                else "0"
                if action == "exclude"
                else "1",
                "reason": (
                    "用户裁定（规则为待裁定/例外）："
                    if item["status"] in {"review", "exception"}
                    and action not in {"keep", "review"}
                    else ""
                )
                + "审核当前测量与规则后批准本项操作",
            }
        )
    path = tmp_path / "approved.csv"
    write(path, rows, fields)
    return Context(
        tmp_path / "apply",
        {
            **initial.inputs,
            "issues": initial.output_path("issues.csv"),
            "approved_changes": path,
        },
        initial.parameters,
    )


@pytest.mark.parametrize("suffix", ["check", "apply", "relations", "prospect"])
def test_manifest_reproducible_standalone_packages(suffix):
    builder = runpy.run_path(str(CORE / "build.py"))["build"]
    identifier = "geology-multi-" + suffix
    first = builder(identifier)
    assert first == builder(identifier)
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        spec = validate_manifest(yaml.safe_load(archive.read("operator.yaml")))
        assert spec["identifier"] == identifier
        assert {
            "multi_io.py",
            "multi_checks.py",
            "multi_apply.py",
            "multi_relations.py",
            "multi_prospect.py",
            "main.py",
        } <= set(archive.namelist())


def test_real_name_code_fix_and_reclassification_only_when_approved(tmp_path):
    initial, original = fixture(tmp_path)
    untouched = {key: path.read_bytes() for key, path in initial.inputs.items()}
    findings, report = check(initial)
    code = next(row for row in findings if row["rule_id"] == "L-03")
    island = next(
        row
        for row in findings
        if row["rule_id"] == "L-01" and row["feature_id"] == "G3"
    )
    assert code["feature_id"] == "G4" and code["target_code"] == "C"
    # G3's classification confidence 0.5 is below conf_auto, so reclassifying it to
    # its host is suggested; keeping it under review leaves the map unchanged.
    assert island["suggested_action"] == "reclassify"
    assert island["status"] == "suggested"
    assert json.loads(island["measurements_json"])[
        "shared_boundary_ratio"
    ] == pytest.approx(1)
    assert report["metrics"]["map_modified"] is False
    edited = approval_context(
        tmp_path, initial, [code, island], {island["issue_id"]: "review"}
    )
    load("apply")(edited)
    result = gpd.read_file(edited.output_path("lithology.gpkg")).set_index("feature_id")
    assert "G4" not in result.index and result.at["G3", "geo_sym"] == "O"
    assert "G2" not in result.index
    assert all(
        result.at[row.feature_id, "geometry"].equals_exact(row.geometry, 0)
        for _, row in original.iterrows()
        if row.feature_id not in {"G1", "G2", "G4"}
    )
    assert all(
        path.read_bytes() == untouched[key] for key, path in initial.inputs.items()
    )
    assert (
        json.loads(edited.output_path("quality.json").read_text(encoding="utf-8"))[
            "metrics"
        ]["actual_change_count"]
        == 1
    )


def test_alteration_aggregates_same_class_and_preserves_weight_states(tmp_path):
    initial, _ = fixture(tmp_path)
    findings, _ = check(initial)
    carbonate = next(row for row in findings if row["rule_id"] == "A-01")
    measured = json.loads(carbonate["measurements_json"])
    assert measured["area_m2"] == pytest.approx(20000)
    assert measured["rock_group"] == "carbonate" and measured["unit_code"] == "C"
    # Carbonate background is read as lithology; a reviewer may still downweight.
    assert carbonate["suggested_action"] == "exclude"
    edited = approval_context(
        tmp_path, initial, [carbonate], {carbonate["issue_id"]: "downweight"}
    )
    load("apply")(edited)
    with rasterio.open(edited.output_path("calcite_weight.tif")) as source:
        assert int((source.read(1) == 0.5).sum()) == measured["pixel_count"]
    with rasterio.open(edited.output_path("calcite_corrected.tif")) as source:
        assert int(source.read(1).sum()) == measured["pixel_count"]


def test_reclassification_fuses_host_and_preserves_coverage_and_original_record(
    tmp_path,
):
    initial, original = fixture(tmp_path)
    findings, _ = check(initial)
    island = next(
        row
        for row in findings
        if row["rule_id"] == "L-01" and row["feature_id"] == "G3"
    )
    edited = approval_context(
        tmp_path, initial, [island], {island["issue_id"]: "reclassify"}
    )
    load("apply")(edited)
    result = gpd.read_file(edited.output_path("lithology.gpkg")).set_index("feature_id")
    assert "G3" not in result.index and result.at["G1", "geometry"].equals(
        rect(0, 0, 1000, 1000).difference(rect(800, 800, 900, 900))
    )
    assert result.geometry.is_valid.all()
    assert (
        result.geometry.union_all()
        .symmetric_difference(original.geometry.union_all())
        .area
        < 0.01
    )
    assert result.geometry.area.sum() == pytest.approx(result.geometry.union_all().area)
    assert not {"state", "weight", "rule_id", "modified", "fill_color"} & set(
        result.columns
    )
    faults = gpd.read_file(edited.output_path("final_faults.gpkg"))
    assert len(faults) == 2 and set(faults.columns) == {"line_id", "geometry"}
    for identity in ("G4",):
        assert result.loc[identity].equals(
            original.set_index("feature_id").loc[identity]
        )
    records = gpd.read_file(edited.output_path("changes_lithology_issues.gpkg"))
    assert len(records) == 1
    record = records.iloc[0]
    assert record.action == "reclassify" and record.host_feature_id == "G1"
    assert (record.old_code, record.new_code) == ("O", "C")
    assert set(json.loads(record.absorbed_ids)) == {"G2", "G3"}
    assert record.geometry.equals(original.set_index("feature_id").at["G3", "geometry"])


def test_final_alterations_exclude_approved_items_only(tmp_path):
    initial, _ = fixture(tmp_path)
    findings, _ = check(initial)
    selected = next(row for row in findings if row["rule_id"] == "A-01")
    edited = approval_context(
        tmp_path, initial, [selected], {selected["issue_id"]: "exclude"}
    )
    load("apply")(edited)
    with rasterio.open(edited.output_path("calcite_corrected.tif")) as source:
        assert not source.read(1).any()
    with rasterio.open(edited.output_path("hematite_corrected.tif")) as source:
        assert source.read(1).sum() == 25


def test_absent_faults_are_explicit_empty_optional_outputs(tmp_path):
    initial, _ = fixture(tmp_path)
    faults = gpd.read_file(initial.inputs["faults"])
    store(faults.iloc[:0], initial.inputs["faults"])
    check(initial)
    edited = approval_context(tmp_path, initial, [])
    load("apply")(edited)
    assert not edited.output_path("faults.gpkg").exists()
    assert not edited.output_path("final_faults.gpkg").exists()
    manifest = json.loads(
        (ROOT / "examples/compute/geology-multi-apply/operator.yaml").read_text()
    )
    assert (
        next(row for row in manifest["outputs"] if row["key"] == "faults")["required"]
        is False
    )


def test_operator_packages_are_deterministic_and_declare_clean_outputs():
    builder = runpy.run_path(str(CORE / "build.py"))["build"]
    for suffix in ("check", "apply", "relations", "prospect"):
        identifier = "geology-multi-" + suffix
        package = builder(identifier)
        assert package == builder(identifier)
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            manifest = validate_manifest(yaml.safe_load(archive.read("operator.yaml")))
            assert manifest["version"] == "1.1.1" and manifest["deterministic"]
            assert {"main.py", "multi_apply.py", "multi_io.py", "operator.yaml"} <= set(
                archive.namelist()
            )
            if suffix == "apply":
                assert {
                    "final_faults",
                    "calcite_corrected",
                    "calcite_weight",
                    "calcite_changes",
                } <= {item["key"] for item in manifest["outputs"]}


def test_clean_lithology_strips_processing_fields_without_filtering_coverage(tmp_path):
    load("apply")
    from multi_apply import final_layer

    _, original = fixture(tmp_path)
    original["state"] = "exclude"
    original["weight"] = 0
    original["rule_id"] = "old-rule"
    original["change_flag"] = True
    clean = final_layer(original, "lithology")
    assert len(clean) == len(original)
    assert not {"state", "weight", "rule_id", "change_flag"} & set(clean.columns)
    assert clean.geometry.union_all().equals(original.geometry.union_all())


def test_host_is_longest_shared_boundary_not_point_contact(tmp_path):
    load("apply")
    from multi_apply import apply

    lithology = gpd.GeoDataFrame(
        {
            "feature_id": ["source", "short", "long", "point"],
            "name": ["old", "new", "new", "new"],
            "geo_sym": ["O", "N", "N", "N"],
            "geo_tex": ["旧文字说明", "宿主文字说明", "宿主文字说明", "宿主文字说明"],
        },
        geometry=[
            rect(0, 0, 10, 10),
            rect(-2, 0, 0, 4),
            rect(10, 0, 12, 10),
            rect(10, 10, 12, 12),
        ],
        crs=32646,
    )
    empty_faults = gpd.GeoDataFrame({"line_id": []}, geometry=[], crs=32646)
    empty_alt = gpd.GeoDataFrame({"feature_id": []}, geometry=[], crs=32646)
    operation = {
        "element": "lithology",
        "feature_id": "source",
        "action": "reclassify",
        "target_code": "N",
        "rule_id": "L-01",
    }
    corrected, _, _, records = apply(lithology, empty_faults, empty_alt, [operation])
    assert records[0]["host_feature_id"] == "long"
    assert "source" not in set(corrected.feature_id)
    assert len(corrected) == 1
    assert corrected.iloc[0].geo_tex == "宿主文字说明"
    assert corrected.geometry.union_all().equals(lithology.geometry.union_all())


@pytest.mark.parametrize("reverse", [False, True])
def test_many_sources_same_host_and_chain_are_order_independent(tmp_path, reverse):
    load("apply")
    from multi_apply import apply

    lithology = gpd.GeoDataFrame(
        {
            "feature_id": [
                "host",
                "error-a",
                "host-copy",
                "error-b",
                "point",
                "untouched",
            ],
            "name": ["new", "old", "new", "old", "new", "other"],
            "geo_sym": ["N", "O", "N", "O", "N", "U"],
        },
        geometry=[
            rect(0, 0, 10, 10),
            rect(10, 0, 20, 10),
            rect(20, 0, 30, 10),
            rect(0, 10, 10, 20),
            rect(30, 10, 40, 20),
            rect(100, 100, 110, 110),
        ],
        crs=32646,
    )
    empty_faults = gpd.GeoDataFrame({"line_id": []}, geometry=[], crs=32646)
    empty_alt = gpd.GeoDataFrame({"feature_id": []}, geometry=[], crs=32646)
    operations = [
        {
            "element": "lithology",
            "feature_id": identity,
            "action": "reclassify",
            "target_code": "N",
            "rule_id": "L-01",
        }
        for identity in ("error-a", "error-b")
    ]
    corrected, _, _, records = apply(
        lithology, empty_faults, empty_alt, operations[::-1] if reverse else operations
    )
    assert set(corrected.feature_id) == {"host", "point", "untouched"}
    assert corrected.geometry.union_all().equals(lithology.geometry.union_all())
    assert corrected.geometry.is_valid.all()
    assert corrected.geometry.area.sum() == pytest.approx(
        corrected.geometry.union_all().area
    )
    for identity in ("point", "untouched"):
        assert (
            corrected.set_index("feature_id")
            .at[identity, "geometry"]
            .equals_exact(lithology.set_index("feature_id").at[identity, "geometry"], 0)
        )
    assert sum(
        item["removed_internal_boundary_m"] for item in records
    ) == pytest.approx(30)


def test_host_reclassified_elsewhere_cannot_silently_change_approved_target(tmp_path):
    load("apply")
    from multi_apply import apply

    lithology = gpd.GeoDataFrame(
        {
            "feature_id": ["source", "host", "next"],
            "name": ["old", "middle", "new"],
            "geo_sym": ["O", "M", "N"],
        },
        geometry=[rect(0, 0, 10, 10), rect(10, 0, 20, 10), rect(20, 0, 30, 10)],
        crs=32646,
    )
    empty_faults = gpd.GeoDataFrame({"line_id": []}, geometry=[], crs=32646)
    empty_alt = gpd.GeoDataFrame({"feature_id": []}, geometry=[], crs=32646)
    operations = [
        {
            "element": "lithology",
            "feature_id": identity,
            "action": "reclassify",
            "target_code": target,
            "rule_id": "L-01",
        }
        for identity, target in (("source", "M"), ("host", "N"))
    ]
    corrected, _, _, _ = apply(lithology, empty_faults, empty_alt, operations)
    assert corrected.set_index("feature_id").at["source", "geo_sym"] == "M"
    assert set(corrected.geo_sym) == {"M", "N"}
    assert corrected.geometry.union_all().equals(lithology.geometry.union_all())


@pytest.mark.parametrize(
    "field,value",
    [
        ("snapshot_hash", "0" * 64),
        ("rule_version", "different"),
        ("feature_id", "G1"),
        ("target_code", "O"),
        ("action", "erase"),
        ("weight", "2"),
    ],
)
def test_forged_approvals_fail_before_writing(tmp_path, field, value):
    initial, _ = fixture(tmp_path)
    findings, _ = check(initial)
    code = next(row for row in findings if row["rule_id"] == "L-03")
    edited = approval_context(tmp_path, initial, [code])
    records = read(edited.inputs["approved_changes"])
    records[0][field] = value
    write(edited.inputs["approved_changes"], records)
    with pytest.raises(ValueError):
        load("apply")(edited)
    assert list(edited.directory.iterdir()) == []


def test_rules_change_invalidates_old_plan_and_current_issues(tmp_path):
    initial, _ = fixture(tmp_path)
    findings, _ = check(initial)
    edited = approval_context(
        tmp_path, initial, [next(row for row in findings if row["rule_id"] == "L-03")]
    )
    rows = read(initial.inputs["rules"])
    rows[0]["knowledge_revision"] = "2"
    write(initial.inputs["rules"], rows)
    with pytest.raises(ValueError, match="改变|不符|一致"):
        load("apply")(edited)
    assert list(edited.directory.iterdir()) == []


def test_approval_accepts_catalog_normalized_display_text_only(tmp_path):
    initial, _ = fixture(tmp_path)
    rules = read(initial.inputs["rules"])
    for row in rules:
        rule = json.loads(row["rule_json"])
        rule["condition"] += "\n"
        rule["basis"]["gap"] += "\n"
        row["rule_json"] = json.dumps(rule)
    write(initial.inputs["rules"], rules)
    findings, _ = check(initial)
    code = next(row for row in findings if row["rule_id"] == "L-03")
    edited = approval_context(tmp_path, initial, [code])
    # Exercise the actual catalog normalizer and SQLite/CSV transport used by
    # import_plain_table and freeze_input, without creating platform resources.
    normalized = normalize_dataframe(pd.DataFrame(read(edited.inputs["issues"])))
    with sqlite3.connect(tmp_path / "catalog.sqlite") as connection:
        normalized.to_sql("issues", connection, index=False)
        cursor = connection.execute('SELECT * FROM "issues"')
        with edited.inputs["issues"].open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow([column[0] for column in cursor.description])
            writer.writerows(cursor)
    assert any(row["conditions"].endswith("\n") for row in findings)
    assert all(
        not row["conditions"].endswith("\n") for row in read(edited.inputs["issues"])
    )
    load("apply")(edited)
    result = gpd.read_file(edited.output_path("lithology.gpkg")).set_index("feature_id")
    assert "G4" not in result.index and set(result.geo_sym) == {"C", "O"}


@pytest.mark.parametrize("field", ["conditions", "measurements_json", "geometry_json"])
def test_approval_rejects_substantive_inspection_changes(tmp_path, field):
    initial, _ = fixture(tmp_path)
    findings, _ = check(initial)
    code = next(row for row in findings if row["rule_id"] == "L-03")
    edited = approval_context(tmp_path, initial, [code])
    rows = read(edited.inputs["issues"])
    rows[0][field] += " changed"
    write(edited.inputs["issues"], rows)
    with pytest.raises(ValueError, match="改变"):
        load("apply")(edited)
    assert list(edited.directory.iterdir()) == []


@pytest.mark.parametrize("geographic", [False, True])
def test_relations_and_prospect_have_real_grades_mask_and_matching_evidence(
    tmp_path, geographic
):
    initial, _ = fixture(tmp_path)
    if geographic:
        for key in ("lithology", "faults", "coverage"):
            store(gpd.read_file(initial.inputs[key]).to_crs(4326), initial.inputs[key])
    findings, _ = check(initial)
    edited = approval_context(
        tmp_path, initial, [next(row for row in findings if row["rule_id"] == "L-03")]
    )
    load("apply")(edited)
    relations = Context(
        tmp_path / "relations",
        {**initial.inputs, "faults": edited.output_path("faults.gpkg")},
        initial.parameters,
    )
    load("relations")(relations)
    points = gpd.read_file(relations.output_path("intersections.gpkg"))
    assert len(points.loc[~points.inferred.astype(bool)]) == 1
    prospect = Context(
        tmp_path / "prospect",
        {
            **initial.inputs,
            "before_lithology": initial.inputs["lithology"],
            "before_faults": initial.inputs["faults"],
            "lithology": edited.output_path("lithology.gpkg"),
            "faults": edited.output_path("faults.gpkg"),
            **raster_inputs(initial, edited),
            "intersections": relations.output_path("intersections.gpkg"),
        },
        initial.parameters,
    )
    load("prospect")(prospect)
    zones = gpd.read_file(prospect.output_path("after_zones.gpkg"))
    assert len(zones) > 0 and set(zones.grade) == {"B"}
    assert set(zones.columns) == {"zone_id", "grade", "area_km2", "geometry"}
    assert zones.geometry.difference(rect(0, 0, 1000, 1000)).area.sum() < 0.001
    for row in read(prospect.output_path("evidence.csv")):
        measured = json.loads(row["conditions_json"])
        assert measured["min_weighted_type_count"] >= measured["min_types_required"]
        assert measured["alteration_supported_fraction"] == 1
        assert measured["structure_supported_fraction"] == 1
        assert measured["favourable_fraction"] == 0
    validate_report(
        json.loads(prospect.output_path("quality.json").read_text(encoding="utf-8"))
    )


def test_empty_anomalies_intersections_and_prospects_are_real_empty_layers(tmp_path):
    initial, _ = fixture(tmp_path)
    for key in KEYS:
        with rasterio.open(initial.inputs[key], "r+") as stream:
            stream.write(np.zeros((100, 100), dtype="uint8"), 1)
    initial.parameters["segment"] = "alteration"
    findings, report = check(initial)
    assert findings == [] and report["metrics"]["alteration_count"] == 0
    assert not initial.output_path("alteration_issues.gpkg").exists()
    faults = gpd.read_file(initial.inputs["faults"]).iloc[:1]
    store(faults, initial.inputs["faults"])
    relations = Context(tmp_path / "relations", initial.inputs, initial.parameters)
    load("relations")(relations)
    assert not relations.output_path("intersections.gpkg").exists()
    prospect = Context(
        tmp_path / "prospect",
        {
            **initial.inputs,
            **raster_inputs(initial),
            "before_lithology": initial.inputs["lithology"],
            "before_faults": initial.inputs["faults"],
        },
        initial.parameters,
    )
    load("prospect")(prospect)
    assert not prospect.output_path("before_zones.gpkg").exists()
    assert not prospect.output_path("after_zones.gpkg").exists()
    assert read(prospect.output_path("evidence.csv")) == []


def test_boundary_ratio_measures_line_once_and_ignores_same_class_seams(tmp_path):
    initial, _ = fixture(tmp_path)
    line = gpd.GeoDataFrame(
        {"line_id": ["F-boundary"]},
        geometry=[LineString([(X + 500, Y + 100), (X + 500, Y + 900)])],
        crs=32646,
    )
    store(line, initial.inputs["faults"])
    rows = read(initial.inputs["rules"])
    for row in rows:
        if row["rule_id"] == "S-02":
            row["params_json"] = json.dumps(
                {"boundary_buffer_m": 20, "boundary_ratio": 0.8, "min_sinuosity": 1}
            )
    write(initial.inputs["rules"], rows)
    findings, _ = check(initial)
    assert not any(row["rule_id"] == "S-02" for row in findings)
    lithology = gpd.read_file(initial.inputs["lithology"])
    lithology.loc[lithology.feature_id == "G2", "geo_sym"] = "O"
    lithology.loc[lithology.feature_id == "G2", "name"] = "old"
    store(lithology, initial.inputs["lithology"])
    again = Context(tmp_path / "second", initial.inputs, initial.parameters)
    findings, _ = check(again)
    boundary = next(row for row in findings if row["rule_id"] == "S-02")
    assert json.loads(boundary["measurements_json"])["boundary_ratio"] == pytest.approx(
        1
    )


def test_explicit_empty_approval_copies_input_without_changes(tmp_path):
    initial, original = fixture(tmp_path)
    check(initial)
    edited = approval_context(tmp_path, initial, [])
    load("apply")(edited)
    result = gpd.read_file(edited.output_path("lithology.gpkg"))
    assert result.geo_sym.tolist() == original.geo_sym.tolist()
    assert read(edited.output_path("changes.csv")) == []
    assert not edited.output_path("changes_lithology_issues.gpkg").exists()
    metrics = json.loads(
        edited.output_path("quality.json").read_text(encoding="utf-8")
    )["metrics"]
    assert metrics["approved_count"] == metrics["actual_change_count"] == 0


def test_downweight_really_affects_evidence_without_removing_geometry(tmp_path):
    initial, _ = fixture(tmp_path)
    findings, _ = check(initial)
    selected = [row for row in findings if row["rule_id"] == "A-05"]
    edited = approval_context(
        tmp_path, initial, selected, {row["issue_id"]: "downweight" for row in selected}
    )
    load("apply")(edited)
    with rasterio.open(edited.output_path("hematite_weight.tif")) as source:
        assert int((source.read(1) == 0.5).sum()) == 25
    relations = Context(tmp_path / "relations", initial.inputs, initial.parameters)
    load("relations")(relations)
    prospect = Context(
        tmp_path / "prospect",
        {
            **initial.inputs,
            "before_lithology": initial.inputs["lithology"],
            "before_faults": initial.inputs["faults"],
            **raster_inputs(initial, edited),
            "intersections": relations.output_path("intersections.gpkg"),
        },
        initial.parameters,
    )
    load("prospect")(prospect)
    before = gpd.read_file(prospect.output_path("before_zones.gpkg"))
    assert not prospect.output_path("after_zones.gpkg").exists()
    assert before.geometry.area.sum() > 0
    for row in read(prospect.output_path("evidence.csv")):
        if row["phase"] == "after":
            assert json.loads(row["conditions_json"])["min_weighted_type_count"] >= 2


def test_recheck_keeps_user_review_and_downweight_state(tmp_path):
    initial, _ = fixture(tmp_path)
    findings, _ = check(initial)
    selected = [next(row for row in findings if row["rule_id"] == "A-01")]
    edited = approval_context(
        tmp_path, initial, selected, {selected[0]["issue_id"]: "downweight"}
    )
    load("apply")(edited)
    recheck = Context(
        tmp_path / "recheck",
        {**initial.inputs, **raster_inputs(initial, edited)},
        initial.parameters,
    )
    again, report = check(recheck)
    assert report["metrics"]["snapshot_hash"] != findings[0]["snapshot_hash"]
    with rasterio.open(edited.output_path("calcite_weight.tif")) as source:
        assert int((source.read(1) == 0.5).sum()) == 200
    assert len(again) == len(findings)


def test_approved_exclusion_does_not_reappear_as_unresolved_structure(tmp_path):
    initial, _ = fixture(tmp_path)
    short = gpd.GeoDataFrame(
        {"line_id": ["F-short"]},
        geometry=[LineString([(X + 400, Y + 900), (X + 450, Y + 900)])],
        crs=32646,
    )
    store(short, initial.inputs["faults"])
    findings, _ = check(initial)
    item = next(row for row in findings if row["rule_id"] == "S-03")
    edited = approval_context(tmp_path, initial, [item], {item["issue_id"]: "exclude"})
    load("apply")(edited)
    states = gpd.read_file(edited.output_path("faults.gpkg"))
    assert states.state.tolist() == ["exclude"] and states.weight.tolist() == [0]
    assert not edited.output_path("final_faults.gpkg").exists()
    changes = gpd.read_file(edited.output_path("changes_fault_issues.gpkg"))
    assert changes.action.tolist() == ["exclude"]
    assert changes.reason.iloc[0]
    assert changes.geometry.iloc[0].equals(short.geometry.iloc[0])
    recheck = Context(
        tmp_path / "recheck",
        {**initial.inputs, "faults": edited.output_path("faults.gpkg")},
        initial.parameters,
    )
    remaining, _ = check(recheck)
    assert not any(row["element"] == "structure" for row in remaining)
    relations = Context(
        tmp_path / "relations",
        {**initial.inputs, "faults": edited.output_path("faults.gpkg")},
        initial.parameters,
    )
    load("relations")(relations)
    assert not relations.output_path("intersections.gpkg").exists()


def test_explicit_approved_merge_changes_only_source_and_measured_host(tmp_path):
    initial, original = fixture(tmp_path)
    findings, _ = check(initial)
    island = next(
        row
        for row in findings
        if row["rule_id"] == "L-01" and row["feature_id"] == "G3"
    )
    edited = approval_context(
        tmp_path, initial, [island], {island["issue_id"]: "merge"}
    )
    load("apply")(edited)
    result = gpd.read_file(edited.output_path("lithology.gpkg")).set_index("feature_id")
    assert "G3" not in result.index and result.at["G1", "geometry"].equals(
        rect(0, 0, 1000, 1000).difference(rect(800, 800, 900, 900))
    )
    for identifier in ("G4",):
        assert result.at[identifier, "geometry"].equals_exact(
            original.set_index("feature_id").at[identifier, "geometry"], 0
        )
    rows = read(edited.output_path("statistics.csv"))
    assert float(
        next(row for row in rows if row["geo_sym"] == "C")["delta_area_m2"]
    ) == pytest.approx(10000)


def enable_consolidation(initial):
    rows = read(initial.inputs["rules"])
    rows.append(
        {
            **rows[0],
            "rule_id": "L-05",
            "knowledge_id": "99",
            "rule_json": json.dumps(
                {
                    "id": "L-05",
                    "condition": "同单元粒度整理",
                    "basis": {"gap": "保留有意义内部边界"},
                }
            ),
            "params_json": json.dumps(
                {
                    "unit_level_consolidation": True,
                    "min_shared_boundary_m": 1,
                    "fault_buffer_m": 100,
                }
            ),
            "units_json": "",
            "aliases_json": "",
        }
    )
    write(initial.inputs["rules"], rows)


def test_same_unit_merge_requires_measurement_approval_and_preserves_class_area(
    tmp_path,
):
    initial, original = fixture(tmp_path)
    faults = gpd.read_file(initial.inputs["faults"])
    store(faults.iloc[:0], initial.inputs["faults"])
    enable_consolidation(initial)
    findings, _ = check(initial)
    candidate = next(row for row in findings if row["rule_id"] == "L-05")
    measurement = json.loads(candidate["measurements_json"])
    assert measurement["shared_boundary_m"] == pytest.approx(1000)
    assert measurement["host_feature_id"] == "G2"
    rejected = approval_context(tmp_path, initial, [])
    load("apply")(rejected)
    assert len(gpd.read_file(rejected.output_path("lithology.gpkg"))) == len(original)
    # A new execution directory prevents output from the rejection becoming evidence.
    edited = approval_context(tmp_path, initial, [candidate])
    edited.directory = tmp_path / "accepted"
    edited.directory.mkdir()
    load("apply")(edited)
    result = gpd.read_file(edited.output_path("lithology.gpkg"))
    assert len(result) == len(original) - 1 and "G1" not in set(result.feature_id)
    assert (
        result.geometry.union_all()
        .symmetric_difference(original.geometry.union_all())
        .area
        < 0.01
    )
    for code in set(original.geo_sym):
        assert result.loc[result.geo_sym == code].geometry.area.sum() == pytest.approx(
            original.loc[original.geo_sym == code].geometry.area.sum()
        )
    actual = read(edited.output_path("changes.csv"))[0]
    assert float(actual["involved_area_m2"]) == pytest.approx(980000)
    assert float(actual["geometry_change_area_m2"]) == 0
    assert float(actual["class_change_area_m2"]) == 0
    assert float(actual["removed_internal_boundary_m"]) == pytest.approx(1000)
    highlight = gpd.read_file(edited.output_path("changes_lithology_issues.gpkg"))
    assert highlight.geometry.area.sum() == pytest.approx(490000)
    for identity in ("G3", "G4"):
        assert (
            result.set_index("feature_id")
            .at[identity, "geometry"]
            .equals_exact(original.set_index("feature_id").at[identity, "geometry"], 0)
        )


def test_same_unit_rule_preserves_fault_boundary_and_requires_explicit_scope(tmp_path):
    initial, _ = fixture(tmp_path)
    enable_consolidation(initial)
    findings, _ = check(initial)
    assert not any(row["rule_id"] == "L-05" for row in findings)
    rows = read(initial.inputs["rules"])
    rows[-1]["params_json"] = json.dumps({"unit_level_consolidation": False})
    write(initial.inputs["rules"], rows)
    second = Context(tmp_path / "second", initial.inputs, initial.parameters)
    findings, _ = check(second)
    assert not any(row["rule_id"] == "L-05" for row in findings)


def test_relation_before_after_is_reconstructed_from_actual_active_lines(tmp_path):
    initial, _ = fixture(tmp_path)
    faults = gpd.read_file(initial.inputs["faults"])
    faults["state"], faults["weight"] = ["exclude", "keep"], [0.0, 1.0]
    after = tmp_path / "after_faults.gpkg"
    store(faults, after)
    relations = Context(
        tmp_path / "relations",
        {
            **initial.inputs,
            "before_faults": initial.inputs["faults"],
            "faults": after,
        },
        initial.parameters,
    )
    load("relations")(relations)
    before = gpd.read_file(relations.output_path("before_intersections.gpkg"))
    assert len(before.loc[~before.inferred.astype(bool)]) == 1
    row = next(
        row
        for row in read(relations.output_path("statistics.csv"))
        if row["kind"] == "geometric"
    )
    assert (
        row["before_count"] == "1"
        and row["after_count"] == "0"
        and row["delta_count"] == "-1"
    )
