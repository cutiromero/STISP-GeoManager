"""Evidence bounded edits on real-shaped map copies, without truth inputs."""

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


def load(name):
    directory = ROOT / name
    old = sys.modules.pop("age_logic", None)
    sys.path.insert(0, str(directory))
    try:
        return runpy.run_path(str(directory / "main.py"))
    finally:
        sys.path.pop(0)
        sys.modules.pop("age_logic", None)
        if old is not None:
            sys.modules["age_logic"] = old


def write(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def fixture(tmp_path):
    frame = gpd.GeoDataFrame(
        {
            "feature_id": ["a", "b", "c"],
            "class": [0, 8, 9],
            "formation": ["八宝山组", "八宝山组", "闹仓坚沟组"],
            "region": ["青海东昆仑南坡"] * 3,
            "geologic_age": ["J3", "T3", "T2"],
            "untouched": [11, 22, 33],
        },
        geometry=[
            box(778000 + i * 100, 3978000, 778100 + i * 100, 3978100) for i in range(3)
        ],
        crs=32646,
    )
    path = tmp_path / "input.gpkg"
    frame.to_file(path, layer="data", driver="GPKG", index=False)
    rule_rows = [
        {
            "rule_id": "cgl-age-a",
            "field": "geologic_age",
            "operation": "set_attribute",
            "formation": "八宝山组",
            "region": "青海东昆仑南坡",
            "expected_age": "T3",
            "evidence_id": "cgl-a",
            "evidence_kind": "dictionary_definition",
            "source": "中国岩石地层名称辞典",
            "source_url": "http://terms.cgl.org.cn/item-a",
            "source_locator": "06-63-0717；时代",
            "conditions": "同名地层在适用地区的时代属性一致性",
            "exceptions": "可靠新测年转人工复核",
            "region_bbox_wgs84": "95,34,100,38",
        }
    ]
    context_rows = [
        {
            "feature_id": str(row.feature_id),
            "evidence_id": "context-" + row.feature_id,
            "evidence_kind": "spatial_context",
            "source": "真实构造及指示层",
            "formation": row.formation,
            "region": row.region,
            "area_m2": row.geometry.area,
            "nearest_structure_m": 100,
            "mineral_positive_pixels": '{"chlorite": 2}',
            "age_evidence": "无独立测年，空间层仅作上下文",
            "limitations": "0为NoData",
        }
        for _, row in frame.iterrows()
    ]
    rules_path, surveys_path = tmp_path / "rules.csv", tmp_path / "context.csv"
    write(rules_path, rule_rows)
    write(surveys_path, context_rows)
    return Context(
        tmp_path / "check",
        {"features": path, "rules": rules_path, "surveys": surveys_path},
    )


def check(context):
    load("geology-age-check")["run"](context)
    quality = json.loads(
        context.output_path("quality.json").read_text(encoding="utf-8")
    )
    validate_report(quality)
    return read(context.output_path("issues.csv")), quality


def edit_context(tmp_path, initial, issues):
    path = tmp_path / "changes.csv"
    fields = load("geology-age-check")["ISSUE_FIELDS"]
    write(
        path,
        [
            {
                key: value
                for key, value in row.items()
                if key in fields and key != "status"
            }
            for row in issues
        ],
    )
    return Context(tmp_path / "edit", {**initial.inputs, "changes": path})


@pytest.mark.parametrize("name", ["geology-age-check", "geology-age-edit"])
def test_manifests_valid_and_common_logic_identical(name):
    spec = validate_manifest(
        yaml.safe_load((ROOT / name / "operator.yaml").read_text(encoding="utf-8"))
    )
    assert spec["qualityReport"] == {"file": "quality.json"}
    assert (ROOT / "geology-age-check/age_logic.py").read_bytes() == (
        ROOT / "geology-age-edit/age_logic.py"
    ).read_bytes()


@pytest.mark.parametrize("normalized", [False, True])
def test_real_check_edit_recheck_retains_geometry_class_other_objects(
    tmp_path, normalized
):
    initial = fixture(tmp_path)
    if normalized:
        frame = gpd.read_file(initial.inputs["features"]).to_crs(4326)
        frame.to_file(
            initial.inputs["features"], layer="data", driver="GPKG", index=False
        )
    original = gpd.read_file(initial.inputs["features"])
    input_bytes = {key: path.read_bytes() for key, path in initial.inputs.items()}
    issues, quality = check(initial)
    assert quality["metrics"]["repairable"] == 1
    assert issues[0]["feature_id"] == "a" and issues[0]["new_value"] == "T3"
    assert "仅作上下文" in issues[0]["reason"]
    edit = edit_context(tmp_path, initial, issues)
    load("geology-age-edit")["run"](edit)
    corrected = gpd.read_file(edit.output_path("corrected.gpkg"))
    assert corrected.geologic_age.tolist() == ["T3", "T3", "T2"]
    assert corrected.geometry.to_wkb().tolist() == original.geometry.to_wkb().tolist()
    assert corrected["class"].tolist() == [0, 8, 9]
    assert corrected.untouched.tolist() == [11, 22, 33]
    assert corrected.check_status.tolist() == ["corrected", "unchanged", "unchanged"]
    assert all(
        path.read_bytes() == input_bytes[key] for key, path in initial.inputs.items()
    )
    report = json.loads(edit.output_path("quality.json").read_text(encoding="utf-8"))
    validate_report(report)
    assert report["metrics"]["area_delta_m2"] == 0
    stored_result = tmp_path / "platform-result.gpkg"
    corrected.to_crs(4326).to_file(
        stored_result, layer="data", driver="GPKG", index=False
    )
    again = Context(
        tmp_path / "recheck",
        {**initial.inputs, "features": stored_result},
    )
    remaining, final = check(again)
    assert remaining == [] and final["metrics"]["issue_count"] == 0
    assert (
        read(edit.output_path("changes.csv"))[0]["output_checksum"]
        == final["metrics"]["input_checksum"]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("new_value", "T2"),
        ("evidence_id", "false"),
        ("input_checksum", "0" * 64),
        ("field", "class"),
        ("old_value", "T1"),
    ],
)
def test_forged_plan_rejected_before_output(tmp_path, field, value):
    initial = fixture(tmp_path)
    issues, _ = check(initial)
    issues[0][field] = value
    edit = edit_context(tmp_path, initial, issues)
    with pytest.raises(ValueError):
        load("geology-age-edit")["run"](edit)
    assert list(edit.directory.iterdir()) == []


@pytest.mark.parametrize(
    "mutation", ["conflicting", "out_of_region", "missing_context", "missing_age"]
)
def test_insufficient_conditions_stay_reviewable(tmp_path, mutation):
    initial = fixture(tmp_path)
    if mutation in {"conflicting", "out_of_region"}:
        rows = read(initial.inputs["rules"])
        if mutation == "conflicting":
            rows.append(
                {
                    **rows[0],
                    "rule_id": "other",
                    "evidence_id": "other-source",
                    "expected_age": "T2",
                }
            )
        else:
            rows[0]["region_bbox_wgs84"] = "110,30,120,40"
        write(initial.inputs["rules"], rows)
    elif mutation == "missing_context":
        rows = read(initial.inputs["surveys"])
        write(initial.inputs["surveys"], rows[1:])
    else:
        frame = gpd.read_file(initial.inputs["features"])
        frame.loc[0, "geologic_age"] = "未赋值"
        frame.to_file(
            initial.inputs["features"], layer="data", driver="GPKG", index=False
        )
    issues, report = check(initial)
    assert report["metrics"]["repairable"] == 0
    assert issues[0]["status"] == "needs_review"


def test_area_alone_and_unrelated_formation_do_not_trigger_changes(tmp_path):
    initial = fixture(tmp_path)
    frame = gpd.read_file(initial.inputs["features"])
    frame.geologic_age = ["T3", "T3", "J3"]
    frame.to_file(initial.inputs["features"], layer="data", driver="GPKG", index=False)
    initial.parameters = {"screen_area_m2": 1000000}
    issues, report = check(initial)
    assert issues == [] and report["metrics"]["repairable"] == 0


def test_actual_sdk_and_trusted_subprocess_runner_with_four_file_packages(tmp_path):
    initial = fixture(tmp_path)
    runner = ROOT.parents[1] / "deploy/compute/runner.py"
    sdk = runpy.run_path(str(runner))["Context"]
    request = {
        "inputs": {
            key: {"path": str(path.resolve())} for key, path in initial.inputs.items()
        },
        "parameters": {
            "working_epsg": 32646,
            "screen_area_m2": 200000,
            "max_changes": 5,
        },
    }
    assert not hasattr(sdk(request, tmp_path, initial.directory), "progress")
    load("geology-age-check")["run"](sdk(request, tmp_path, initial.directory))
    issues = read(initial.output_path("issues.csv"))
    edit = edit_context(tmp_path, initial, issues)
    edit_request = {
        **request,
        "inputs": {
            key: {"path": str(path.resolve())} for key, path in edit.inputs.items()
        },
    }
    load("geology-age-edit")["run"](sdk(edit_request, tmp_path, edit.directory))
    assert gpd.read_file(edit.output_path("corrected.gpkg")).geologic_age.tolist() == [
        "T3",
        "T3",
        "T2",
    ]

    def isolated_run(identifier, payload):
        source = ROOT / identifier
        package, inputs, outputs = (
            tmp_path / identifier / value for value in ("package", "inputs", "outputs")
        )
        for directory in (package, inputs, outputs):
            directory.mkdir(parents=True)
        archive = tmp_path / (identifier + ".zip")
        members = ["main.py", "age_logic.py", "operator.yaml", "README.md"]
        with zipfile.ZipFile(archive, "w") as stream:
            for filename in members:
                stream.write(source / filename, filename)
        with zipfile.ZipFile(archive) as stream:
            assert sorted(stream.namelist()) == sorted(members)
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
            deadline = time.monotonic() + 20
            status = outputs / "__platform_status.json"
            while not status.exists() and time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                time.sleep(0.05)
            assert status.exists(), "真实runner未产生状态文件"
            assert json.loads(status.read_text())["status"] == "succeeded"
            validate_report(
                json.loads((outputs / "quality.json").read_text(encoding="utf-8"))
            )
            return outputs
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    checked = isolated_run("geology-age-check", request)
    assert read(checked / "issues.csv")[0]["new_value"] == "T3"
    edited = isolated_run("geology-age-edit", edit_request)
    assert gpd.read_file(edited / "corrected.gpkg").geologic_age.tolist() == [
        "T3",
        "T3",
        "T2",
    ]
