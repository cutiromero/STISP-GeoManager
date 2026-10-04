"""Numerical and retention checks for the repository-owned topology operator."""

import csv
import hashlib
import json
from pathlib import Path
import runpy
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import Point, Polygon

ROOT = Path(__file__).resolve().parents[3] / "examples" / "compute"


class RepairContext:
    def __init__(self, directory, source, parameters=None):
        self.directory = directory
        self.source = source
        self.parameters = parameters or {}

    def input_path(self, key):
        assert key == "features"
        return self.source

    def output_path(self, name):
        return self.directory / name


def execute(tmp_path, geometries, *, crs=32644, parameters=None, attributes=None):
    source = tmp_path / "input.gpkg"
    attrs = attributes or {
        "unit_name": [f"岩性单元{n}" for n in range(len(geometries))]
    }
    frame = gpd.GeoDataFrame(attrs, geometry=geometries, crs=crs)
    frame.to_file(source, layer="data", driver="GPKG", index=False)
    before = source.read_bytes()
    run = runpy.run_path(ROOT / "vector-geometry-repair/main.py")["run"]
    run(RepairContext(tmp_path, source, parameters))
    assert source.read_bytes() == before
    quality = json.loads((tmp_path / "quality.json").read_text(encoding="utf-8"))
    with (tmp_path / "repair-log.csv").open(encoding="utf-8-sig", newline="") as stream:
        log = list(csv.DictReader(stream))
    with zipfile.ZipFile(tmp_path / "repair-audit.zip") as archive:
        assert archive.read("original-input.gpkg") == before
        assert "repair-candidates.gpkg" in archive.namelist()
        assert json.loads(archive.read("quality.json")) == quality
    assert (
        quality["knowledgeFacts"]["geometryRepair"]["sourceSha256"]
        == hashlib.sha256(before).hexdigest()
    )
    return frame, quality, log


def test_valid_holes_attributes_crs_and_area_are_preserved(tmp_path):
    face = Polygon(
        [(0, 0), (100, 0), (100, 100), (0, 100)],
        [[(25, 25), (25, 75), (75, 75), (75, 25)]],
    )
    frame, quality, log = execute(
        tmp_path, [face], attributes={"rock": ["花岗岩"], "epoch": [7]}
    )
    result = gpd.read_file(tmp_path / "repaired.gpkg")
    assert result.crs == frame.crs
    assert result["rock"].tolist() == ["花岗岩"]
    assert result["epoch"].tolist() == [7]
    assert result.geometry.iloc[0].equals_exact(face, 0)
    assert quality["status"] == "passed"
    assert quality["metrics"]["needsReview"] == 0
    assert float(log[0]["area_after_m2"]) == pytest.approx(7500)
    assert float(log[0]["area_change_pct"]) == 0
    assert log[0]["status"] == "unchanged"


def test_self_intersection_becomes_complete_valid_multipolygon_for_review(tmp_path):
    bow = Polygon([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)])
    _, quality, log = execute(tmp_path, [bow])
    repaired = gpd.read_file(tmp_path / "repaired.gpkg")
    assert len(repaired) == 1
    assert repaired.is_valid.all()
    assert repaired.geometry.iloc[0].geom_type == "MultiPolygon"
    assert repaired.area.iloc[0] == pytest.approx(50)
    assert log[0]["status"] == "repaired"
    assert log[0]["area_before_trustworthy"] == "False"
    assert log[0]["parts_after"] == "2"
    assert "原面积为零" in log[0]["review_reasons"]
    assert quality["status"] == "needs_review"
    assert quality["metrics"]["validAfter"] == 1


def test_degenerate_face_does_not_publish_partial_vector_and_retains_line(tmp_path):
    valid = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    collapsed = Polygon([(20, 0), (25, 0), (30, 0), (20, 0)])
    _, quality, log = execute(tmp_path, [valid, collapsed])
    assert not (tmp_path / "repaired.gpkg").exists()
    assert quality["status"] == "needs_review"
    assert quality["metrics"] == {
        "totalFeatures": 2,
        "validAfter": 1,
        "needsReview": 1,
        "failed": 1,
        "maxAreaChangePct": 5,
    }
    assert log[1]["status"] == "failed"
    with zipfile.ZipFile(tmp_path / "repair-audit.zip") as archive:
        (tmp_path / "candidates.gpkg").write_bytes(
            archive.read("repair-candidates.gpkg")
        )
    candidates = gpd.read_file(tmp_path / "candidates.gpkg")
    assert len(candidates) == 2
    assert candidates.geometry.iloc[1].geom_type == "MultiLineString"
    assert candidates["unit_name"].tolist() == ["岩性单元0", "岩性单元1"]


def test_lower_dimensional_fragments_are_retained_and_marked_for_review(tmp_path):
    spike = Polygon([(0, 0), (10, 0), (10, 10), (5, 10), (5, 15), (5, 10), (0, 10)])
    _, quality, log = execute(tmp_path, [spike])
    result = gpd.read_file(tmp_path / "repaired.gpkg")
    assert result.is_valid.all()
    assert result.area.iloc[0] == pytest.approx(100)
    assert log[0]["non_polygon_parts"] == "1"
    assert quality["status"] == "needs_review"


def test_missing_geometry_is_reported_and_original_is_retained(tmp_path):
    _, quality, log = execute(tmp_path, [None])
    assert quality["metrics"]["failed"] == 1
    assert "输入几何为空" in log[0]["review_reasons"]
    assert not (tmp_path / "repaired.gpkg").exists()


def test_outside_hole_area_change_triggers_review(tmp_path):
    outside_hole = Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10)], [[(20, 0), (20, 2), (22, 2), (22, 0)]]
    )
    _, quality, log = execute(
        tmp_path, [outside_hole], parameters={"max_area_change_pct": 5}
    )
    assert float(log[0]["area_before_m2"]) == pytest.approx(96)
    assert float(log[0]["area_after_m2"]) == pytest.approx(104)
    assert float(log[0]["area_change_pct"]) == pytest.approx(100 * 8 / 96)
    assert "面积变化超过阈值" in log[0]["review_reasons"]
    assert quality["status"] == "needs_review"


def test_geographic_area_uses_metres(tmp_path):
    square = Polygon([(80, 40), (80.001, 40), (80.001, 40.001), (80, 40.001)])
    frame, quality, log = execute(tmp_path, [square], crs=4326)
    result = gpd.read_file(tmp_path / "repaired.gpkg")
    assert result.crs == frame.crs
    assert quality["status"] == "passed"
    assert 9000 < float(log[0]["area_after_m2"]) < 10000


@pytest.mark.parametrize("case", ["point", "unknown_crs", "reserved", "bad_threshold"])
def test_invalid_inputs_fail_explicitly(tmp_path, case):
    kwargs = {}
    geometry = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    message = ""
    if case == "point":
        geometry = Point(0, 0)
        message = "仅接受面"
    elif case == "unknown_crs":
        kwargs["crs"] = None
        message = "已知坐标系"
    elif case == "reserved":
        kwargs["attributes"] = {"Repair_Row": [99]}
        message = "已有修复记录字段"
    else:
        kwargs["parameters"] = {"max_area_change_pct": float("nan")}
        message = "有限数字"
    with pytest.raises(ValueError, match=message):
        execute(tmp_path, [geometry], **kwargs)


def test_repeated_run_has_identical_geometry_and_diagnostics(tmp_path):
    geometry = Polygon([(0, 0), (10, 10), (0, 10), (10, 0)])
    execute(tmp_path, [geometry])
    original_log = (tmp_path / "repair-log.csv").read_bytes()
    original_quality = (tmp_path / "quality.json").read_bytes()
    output = tmp_path / "again"
    output.mkdir()
    runpy.run_path(ROOT / "vector-geometry-repair/main.py")["run"](
        RepairContext(output, tmp_path / "input.gpkg")
    )
    assert (output / "repair-log.csv").read_bytes() == original_log
    assert (output / "quality.json").read_bytes() == original_quality
    first = gpd.read_file(tmp_path / "repaired.gpkg")
    second = gpd.read_file(output / "repaired.gpkg")
    assert first.geometry.iloc[0].equals_exact(second.geometry.iloc[0], 0)
