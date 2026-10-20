"""Actual map checks/approved edits, with independent geometry expectations."""

import csv
import json
from pathlib import Path
import runpy
import subprocess
import sys
import time
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import box
import yaml

from apps.compute.packages import validate_manifest
from apps.compute.quality import validate_report

ROOT = Path(__file__).resolve().parents[3] / "examples/compute"
BASE_X, BASE_Y = 778000, 3978000


class Context:
    def __init__(self, directory, inputs, parameters=None):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.inputs = inputs
        self.parameters = parameters or {}

    def input_path(self, key):
        return self.inputs[key]

    def output_path(self, name):
        return self.directory / name


def load(identifier):
    directory = ROOT / identifier
    prior = sys.modules.pop("review_logic", None)
    sys.path.insert(0, str(directory))
    try:
        return runpy.run_path(str(directory / "main.py"))
    finally:
        sys.path.pop(0)
        sys.modules.pop("review_logic", None)
        if prior is not None:
            sys.modules["review_logic"] = prior


def write(path, rows, fields=None):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def geom(x1, y1, x2, y2):
    return box(BASE_X + x1, BASE_Y + y1, BASE_X + x2, BASE_Y + y2)


def store(frame, path):
    frame.to_file(path, layer="data", driver="GPKG", index=False)


def fixture(tmp_path, gap_bounds=(20, 20, 40, 40)):
    gap = geom(*gap_bounds)
    frame = gpd.GeoDataFrame(
        {
            "feature_id": ["map-a", "map-b", "map-c"],
            "class": [0, 8, 9],
            "name": ["八宝山组", "八宝山组", "其他单元"],
            "code": ["T3b", "T3b2", "T2n"],
            "path": ["三叠系/八宝山组A", "三叠系/八宝山组B", "三叠系/其他"],
            "formation": ["八宝山组", "八宝山组", "闹仓坚沟组"],
            "region": ["青海东昆仑南坡"] * 3,
            "geologic_age": ["T3", "J3", "T2"],
            "retained": [11, 22, 33],
        },
        geometry=[
            geom(0, 0, 100, 100).difference(gap),
            geom(100, 0, 200, 100),
            geom(200, 0, 300, 100),
        ],
        crs=32646,
    )
    coverage = gpd.GeoDataFrame(
        {
            "coverage_id": ["area-a"],
            "role": ["coverage"],
            "complete_coverage": [True],
            "no_water": [True],
            "no_uninvestigated": [True],
            "region": ["青海东昆仑南坡"],
            "source": ["本项目制图覆盖资料"],
            "source_locator": ["范围与例外记录1"],
        },
        geometry=[geom(0, 0, 300, 100)],
        crs=32646,
    )
    rules = [
        {
            "rule_id": "complete-map",
            "kind": "fill_gap",
            "name": "完整范围内部漏填检查",
            "scope": "本项目明确完整覆盖区",
            "conditions": "完整覆盖、无水体或未调查区，单一图斑完整包围",
            "exceptions": "水体、未调查区、多个图斑和边界空白需复核",
            "evidence_id": "project-coverage-rule",
            "evidence_kind": "project_rule",
            "source": "项目整理的制图一致性规则",
            "source_locator": "规则1",
            "region": "青海东昆仑南坡",
            "region_bbox_wgs84": "95,34,100,38",
            "formation": "",
            "expected_age": "",
            "knowledge_seed": "coverage-entry",
            "knowledge_id": "123",
            "knowledge_revision": "2",
        },
        {
            "rule_id": "formation-age",
            "kind": "set_age",
            "name": "八宝山组时代定义",
            "scope": "本条目适用地层和地区",
            "conditions": "地层标识与适用地区一致，无相反定年证据",
            "exceptions": "新的可靠定年证据需专家复核",
            "evidence_id": "dictionary-babao",
            "evidence_kind": "dictionary_definition",
            "source": "中国岩石地层名称辞典",
            "source_locator": "06-63-0717；时代",
            "region": "青海东昆仑南坡",
            "region_bbox_wgs84": "95,34,100,38",
            "formation": "八宝山组",
            "expected_age": "T3",
            "knowledge_seed": "age-entry",
            "knowledge_id": "124",
            "knowledge_revision": "1",
        },
    ]
    inputs = {
        "features": tmp_path / "input.gpkg",
        "coverage": tmp_path / "coverage.gpkg",
        "rules": tmp_path / "rules.csv",
    }
    store(frame, inputs["features"])
    store(coverage, inputs["coverage"])
    write(inputs["rules"], rules)
    return Context(tmp_path / "check", inputs), frame, gap


def check(context):
    load("geology-map-check")["run"](context)
    quality = json.loads(
        context.output_path("quality.json").read_text(encoding="utf-8")
    )
    validate_report(quality)
    return read(context.output_path("issues.csv")), quality


def edit_context(tmp_path, initial, issues):
    changes = tmp_path / "approved.csv"
    fields = load("geology-map-check")["ISSUE_FIELDS"]
    write(changes, issues, fields)
    return Context(
        tmp_path / "edit", {**initial.inputs, "changes": changes}, initial.parameters
    )


@pytest.mark.parametrize("name", ["geology-map-check", "geology-map-correct"])
def test_manifests_and_standalone_package_logic(name):
    spec = validate_manifest(
        yaml.safe_load((ROOT / name / "operator.yaml").read_text(encoding="utf-8"))
    )
    assert spec["version"] == "1.0.1" and spec["qualityReport"] == {
        "file": "quality.json"
    }
    assert (ROOT / "geology-map-check/review_logic.py").read_bytes() == (
        ROOT / "geology-map-correct/review_logic.py"
    ).read_bytes()


@pytest.mark.parametrize("wgs84", [False, True])
def test_check_correct_recheck_actual_scope_area_and_classes(tmp_path, wgs84):
    initial, original, gap = fixture(tmp_path)
    if wgs84:
        for key in ("features", "coverage"):
            store(gpd.read_file(initial.inputs[key]).to_crs(4326), initial.inputs[key])
    input_bytes = {key: value.read_bytes() for key, value in initial.inputs.items()}
    issues, report = check(initial)
    assert report["metrics"]["repairable"] == 2
    assert {row["kind"] for row in issues} == {"fill_gap", "set_age"}
    hole = next(row for row in issues if row["kind"] == "fill_gap")
    assert (
        hole["feature_id"] == "map-a"
        and hole["old_value"] == "未分类"
        and hole["new_value"] == "0"
    )
    assert hole["knowledge_seed"] == "coverage-entry" and hole["knowledge_id"] == "123"
    assert float(hole["area_m2"]) == pytest.approx(400, abs=1e-5)
    actual = gpd.read_file(initial.output_path("issues.gpkg")).to_crs(32646)
    assert (
        actual.loc[actual.kind == "fill_gap"]
        .geometry.iloc[0]
        .symmetric_difference(gap)
        .area
        < 1e-5
    )
    edit = edit_context(tmp_path, initial, issues)
    load("geology-map-correct")["run"](edit)
    corrected = gpd.read_file(edit.output_path("corrected.gpkg")).to_crs(32646)
    assert corrected.feature_id.tolist() == original.feature_id.tolist()
    assert corrected["class"].tolist() == [0, 8, 9]
    assert corrected.retained.tolist() == [11, 22, 33]
    assert corrected.geologic_age.tolist() == ["T3", "T3", "T2"]
    assert (
        corrected.geometry.iloc[0].symmetric_difference(geom(0, 0, 100, 100)).area
        < 1e-5
    )
    assert all(
        corrected.geometry.iloc[index]
        .symmetric_difference(original.geometry.iloc[index])
        .area
        < 1e-5
        for index in [1, 2]
    )
    differences = gpd.read_file(edit.output_path("changes.gpkg")).to_crs(32646)
    assert (
        differences.loc[differences.kind == "fill_gap"]
        .geometry.iloc[0]
        .symmetric_difference(gap)
        .area
        < 1e-5
    )
    stats = read(edit.output_path("statistics.csv"))
    assert {row["class"] for row in stats} == {"0", "8", "9"}
    assert float(
        next(row for row in stats if row["class"] == "0")["delta_area_m2"]
    ) == pytest.approx(400, abs=1e-5)
    final_context = Context(
        tmp_path / "recheck",
        {**initial.inputs, "features": edit.output_path("corrected.gpkg")},
    )
    remaining, final = check(final_context)
    edited_report = json.loads(
        edit.output_path("quality.json").read_text(encoding="utf-8")
    )
    validate_report(edited_report)
    assert remaining == [] and final["metrics"]["issue_count"] == 0
    assert (
        edited_report["metrics"]["output_checksum"]
        == final["metrics"]["input_checksum"]
    )
    assert edited_report["metrics"]["area_delta_m2"] == pytest.approx(400, abs=1e-5)
    assert all(
        path.read_bytes() == input_bytes[key] for key, path in initial.inputs.items()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("new_value", "9"),
        ("feature_id", "map-c"),
        ("input_checksum", "0" * 64),
        ("evidence_id", "invented"),
        ("rule_id", "invented"),
        ("old_value", "0"),
        ("kind", "set_age"),
        ("issue_id", "invented"),
        ("geometry_json", '{"type":"Polygon","coordinates":[]}'),
    ],
)
def test_forged_or_unbound_plan_rejected_before_output(tmp_path, field, value):
    initial, _, _ = fixture(tmp_path)
    issues, _ = check(initial)
    issues[0][field] = value
    edit = edit_context(tmp_path, initial, issues)
    with pytest.raises(ValueError):
        load("geology-map-correct")["run"](edit)
    assert list(edit.directory.iterdir()) == []


@pytest.mark.parametrize(
    "precondition", ["complete_coverage", "no_water", "no_uninvestigated"]
)
def test_missing_explicit_coverage_condition_stays_reviewable(tmp_path, precondition):
    initial, _, _ = fixture(tmp_path)
    area = gpd.read_file(initial.inputs["coverage"])
    area[precondition] = False
    store(area, initial.inputs["coverage"])
    issues, report = check(initial)
    hole = next(row for row in issues if row["kind"] == "fill_gap")
    assert hole["status"] == "needs_review" and hole["new_value"] == ""
    assert report["status"] == "passed" and report["metrics"]["needs_review"] == 1
    edit = edit_context(tmp_path, initial, [hole])
    with pytest.raises(ValueError):
        load("geology-map-correct")["run"](edit)
    assert list(edit.directory.iterdir()) == []


def test_excluded_area_and_open_boundary_cannot_be_filled(tmp_path):
    initial, _, gap = fixture(tmp_path)
    area = gpd.read_file(initial.inputs["coverage"])
    excluded = area.copy()
    excluded.coverage_id = "water-exception"
    excluded.role = "exclusion"
    excluded.geometry = [gap]
    store(
        gpd.GeoDataFrame(
            __import__("pandas").concat([area, excluded], ignore_index=True),
            crs=area.crs,
        ),
        initial.inputs["coverage"],
    )
    issues, _ = check(initial)
    assert (
        next(row for row in issues if row["kind"] == "fill_gap")["status"]
        == "needs_review"
    )
    alternate = tmp_path / "boundary"
    alternate.mkdir()
    opened, _, _ = fixture(alternate, (0, 20, 20, 40))
    issues, _ = check(opened)
    assert (
        next(row for row in issues if row["kind"] == "fill_gap")["status"]
        == "needs_review"
    )


@pytest.mark.parametrize("same_class", [False, True])
def test_multiple_surrounding_hosts_never_inferred_from_area(tmp_path, same_class):
    initial, _, gap = fixture(tmp_path, (80, 20, 120, 40))
    frame = gpd.read_file(initial.inputs["features"])
    frame.at[1, "geometry"] = frame.at[1, "geometry"].difference(gap)
    if same_class:
        for key in ("class", "name", "code", "path"):
            frame.at[1, key] = frame.at[0, key]
    store(frame, initial.inputs["features"])
    issues, _ = check(initial)
    hole = next(row for row in issues if row["kind"] == "fill_gap")
    assert hole["status"] == "needs_review" and "唯一图斑" in hole["reason"]


@pytest.mark.parametrize("target", ["features", "coverage", "rules"])
def test_plan_checksum_binds_every_input(tmp_path, target):
    initial, _, _ = fixture(tmp_path)
    issues, _ = check(initial)
    if target == "rules":
        rows = read(initial.inputs[target])
        rows[0]["source_locator"] = "修订2"
        write(initial.inputs[target], rows)
    else:
        frame = gpd.read_file(initial.inputs[target])
        frame["audit_note"] = "revision-2"
        store(frame, initial.inputs[target])
    edit = edit_context(tmp_path, initial, issues)
    with pytest.raises(ValueError):
        load("geology-map-correct")["run"](edit)
    assert list(edit.directory.iterdir()) == []


@pytest.mark.parametrize("approved_kind", ["fill_gap", "set_age"])
def test_only_selected_operations_change_the_map(tmp_path, approved_kind):
    initial, original, gap = fixture(tmp_path)
    issues, _ = check(initial)
    edit = edit_context(
        tmp_path, initial, [row for row in issues if row["kind"] == approved_kind]
    )
    load("geology-map-correct")["run"](edit)
    result = gpd.read_file(edit.output_path("corrected.gpkg")).to_crs(32646)
    assert result.geologic_age.tolist() == (
        ["T3", "J3", "T2"] if approved_kind == "fill_gap" else ["T3", "T3", "T2"]
    )
    expected = (
        geom(0, 0, 100, 100)
        if approved_kind == "fill_gap"
        else original.geometry.iloc[0]
    )
    assert result.geometry.iloc[0].symmetric_difference(expected).area < 1e-5
    quality = json.loads(edit.output_path("quality.json").read_text(encoding="utf-8"))
    assert (
        quality["metrics"]["remaining_issue_count"] == 1
        and quality["status"] == "passed"
    )


def test_moved_gap_is_discovered_from_actual_geometry(tmp_path):
    first, _, _ = fixture(tmp_path)
    issues, _ = check(first)
    alternate = tmp_path / "moved"
    alternate.mkdir()
    second, _, gap = fixture(alternate, (55, 55, 75, 75))
    moved, _ = check(second)
    old_hole = next(row for row in issues if row["kind"] == "fill_gap")
    new_hole = next(row for row in moved if row["kind"] == "fill_gap")
    assert old_hole["issue_id"] != new_hole["issue_id"]
    assert old_hole["geometry_json"] != new_hole["geometry_json"]
    edit = edit_context(alternate, second, moved)
    load("geology-map-correct")["run"](edit)
    differences = gpd.read_file(edit.output_path("changes.gpkg")).to_crs(32646)
    assert (
        differences.loc[differences.kind == "fill_gap"]
        .geometry.iloc[0]
        .symmetric_difference(gap)
        .area
        < 1e-5
    )


@pytest.mark.parametrize("offset", [(0, 0), (20, -10)])
def test_native_grid_island_is_found_corrected_and_rechecked(tmp_path, offset):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    initial, original, _ = fixture(tmp_path)
    reference = tmp_path / "native-grid.tif"
    with rasterio.open(
        reference,
        "w",
        driver="GTiff",
        width=150,
        height=150,
        count=1,
        dtype="uint8",
        crs=32646,
        transform=from_origin(BASE_X - 100, BASE_Y + 200, 2, 2),
    ) as dst:
        dst.write(np.zeros((150, 150), dtype="uint8"), 1)
    module = runpy.run_path(str(ROOT.parents[1] / "scripts/geology_review_data.py"))
    gap, _ = module["natural_gap"](
        (BASE_X + 50 + offset[0], BASE_Y + 50 + offset[1]), reference
    )
    frame = original.copy()
    frame.at[0, "geometry"] = geom(0, 0, 100, 100).difference(gap)
    store(frame, initial.inputs["features"])
    issues, report = check(initial)
    assert report["metrics"]["issue_count"] == 2
    hole = next(row for row in issues if row["kind"] == "fill_gap")
    assert hole["status"] == "repairable"
    assert float(hole["area_m2"]) == pytest.approx(gap.area, abs=1e-5)
    edit = edit_context(tmp_path, initial, issues)
    load("geology-map-correct")["run"](edit)
    corrected = gpd.read_file(edit.output_path("corrected.gpkg")).to_crs(32646)
    assert (
        corrected.geometry.iloc[0].symmetric_difference(geom(0, 0, 100, 100)).area
        < 1e-5
    )
    assert all(
        corrected.geometry.iloc[i].symmetric_difference(original.geometry.iloc[i]).area
        < 1e-5
        for i in [1, 2]
    )
    recheck = Context(
        tmp_path / "recheck",
        {**initial.inputs, "features": edit.output_path("corrected.gpkg")},
    )
    remaining, final = check(recheck)
    assert remaining == [] and final["metrics"]["issue_count"] == 0


def test_empty_approval_and_contradictory_knowledge_stop_edits(tmp_path):
    initial, _, _ = fixture(tmp_path)
    edit = edit_context(tmp_path, initial, [])
    with pytest.raises(ValueError):
        load("geology-map-correct")["run"](edit)
    rows = read(initial.inputs["rules"])
    rows.append({**rows[1], "rule_id": "other-age", "expected_age": "T2"})
    write(initial.inputs["rules"], rows)
    issues, _ = check(initial)
    assert all(
        row["status"] == "needs_review" for row in issues if row["kind"] == "set_age"
    )


def test_real_sdk_and_standalone_trusted_runner(tmp_path):
    initial, _, _ = fixture(tmp_path)
    runner = ROOT.parents[1] / "deploy/compute/runner.py"
    sdk = runpy.run_path(str(runner))["Context"]
    request = {
        "inputs": {
            key: {"path": str(value.resolve())} for key, value in initial.inputs.items()
        },
        "parameters": {},
    }
    load("geology-map-check")["run"](sdk(request, tmp_path, initial.directory))
    issues = read(initial.output_path("issues.csv"))
    edit = edit_context(tmp_path, initial, issues)
    edit_request = {
        "inputs": {
            key: {"path": str(value.resolve())} for key, value in edit.inputs.items()
        },
        "parameters": {},
    }
    for identifier, payload in [
        ("geology-map-check", request),
        ("geology-map-correct", edit_request),
    ]:
        package, inputs, outputs = (
            tmp_path / identifier / part for part in ("package", "inputs", "outputs")
        )
        for path in (package, inputs, outputs):
            path.mkdir(parents=True)
        archive = tmp_path / (identifier + ".zip")
        members = ["main.py", "review_logic.py", "operator.yaml", "README.md"]
        with zipfile.ZipFile(archive, "w") as stream:
            for member in members:
                stream.write(ROOT / identifier / member, member)
        with zipfile.ZipFile(archive) as stream:
            stream.extractall(package)
        (inputs / "context.json").write_text(json.dumps(payload), encoding="utf-8")
        process = subprocess.Popen(
            [
                sys.executable,
                str(runner),
                "--algorithm-dir",
                str(package),
                "--input-dir",
                str(inputs),
                "--output-dir",
                str(outputs),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            status = outputs / "__platform_status.json"
            deadline = time.monotonic() + 20
            while (
                not status.exists()
                and time.monotonic() < deadline
                and process.poll() is None
            ):
                time.sleep(0.05)
            assert (
                status.exists()
                and json.loads(status.read_text())["status"] == "succeeded"
            )
            validate_report(
                json.loads((outputs / "quality.json").read_text(encoding="utf-8"))
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
