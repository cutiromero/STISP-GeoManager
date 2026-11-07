"""A candidate region needs a real core and cannot grow outside supported inputs."""

import json
import runpy
import sys

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from apps.compute.packages import validate_manifest
from apps.compute.quality import validate_report
from tests.unit.test_geology_multi_algorithms import Context, CORE, KEYS, fixture

CANDIDATE = CORE.parent / "geology-prospect-regions-candidate"


def candidate(context):
    sys.path[:0] = [str(CORE), str(CANDIDATE)]
    return runpy.run_path(str(CANDIDATE / "main.py"))["run"](context)


def test_package_and_quality_report_require_explicit_review():
    sys.path[:0] = [str(CORE), str(CANDIDATE)]
    build = runpy.run_path(str(CANDIDATE / "build.py"))["build"]
    assert build() == build()
    manifest = validate_manifest(json.loads((CANDIDATE / "operator.yaml").read_text()))
    assert (
        manifest["identifier"] == "geology-prospect-regions-candidate"
        and manifest["agent"]["enabled"] is False
    )
    assert not any(item["key"].startswith("before_") for item in manifest["inputs"])


@pytest.mark.parametrize(
    "mode", ["zero", "nodata", "no_structure", "cover", "downweighted"]
)
def test_unsupported_inputs_produce_real_empty_candidate(tmp_path, mode):
    initial, _ = fixture(tmp_path)
    for index, key in enumerate(KEYS):
        with rasterio.open(initial.inputs[key], "r+") as stream:
            if mode == "nodata":
                stream.nodata = 255
            values = np.full(
                stream.shape,
                255 if mode == "nodata" else (0 if mode == "zero" or index >= 2 else 1),
                dtype="uint8",
            )
            stream.write(values, 1)
        if mode == "downweighted":
            path = tmp_path / (key + "_weight.tif")
            with rasterio.open(initial.inputs[key]) as src:
                profile = {**src.profile, "dtype": "float32", "nodata": None}
            with rasterio.open(path, "w", **profile) as dst:
                dst.write(np.full((100, 100), 0.5, dtype="float32"), 1)
            initial.inputs[key + "_weight"] = path
    if mode == "no_structure":
        faults = gpd.read_file(initial.inputs["faults"])
        faults["state"] = "exclude"
        faults["weight"] = 0
        faults.to_file(initial.inputs["faults"], layer="data", driver="GPKG")
    if mode == "cover":
        from tests.unit.test_geology_multi_algorithms import read, write

        rows = read(initial.inputs["rules"])
        units = json.loads(rows[0]["units_json"])
        for unit in units.values():
            unit["category"] = "cover"
        rows[0]["units_json"] = json.dumps(units)
        write(initial.inputs["rules"], rows)
    context = Context(
        tmp_path / "candidate",
        initial.inputs,
        {
            "grid_resolution_m": 50,
            "min_zone_area_km2": 0.01,
            "min_core_area_km2": 0.001,
        },
    )
    before = {key: path.read_bytes() for key, path in initial.inputs.items()}
    candidate(context)
    assert not context.output_path("after_zones.gpkg").exists()
    report = validate_report(
        json.loads(context.output_path("quality.json").read_text())
    )
    assert report["status"] == "needs_review" and report["metrics"]["zone_count"] == 0
    assert before == {key: path.read_bytes() for key, path in initial.inputs.items()}


def synthetic_regions(gap=False):
    sys.path[:0] = [str(CORE), str(CANDIDATE)]
    from region_zones import delineate

    dimensions = (40, 80)
    score = np.full(dimensions, 0.75)
    margin = np.full(dimensions, 0.25)
    if gap:
        margin[:, 39:41] = -1
    core = np.zeros(dimensions, dtype=bool)
    core[18:22, 18:22] = True
    core[18:22, 58:62] = True
    area = box(300000, 3998000, 304000, 4000000)
    base = {
        "transform": from_origin(300000, 4000000, 50, 50),
        "dimensions": dimensions,
        "masks": {"favourable": np.ones(dimensions, dtype=bool)},
        "evidence": {name: {"presence": np.ones(dimensions)} for name in ["A", "B"]},
    }
    fields = {
        "core": core,
        "margin": margin,
        "score": score,
        "domain": np.ones(dimensions, dtype=bool),
        "structure": score,
        "alteration": score,
        "broad_count": np.full(dimensions, 2.5),
        "density": np.full(dimensions, 0.1),
    }
    lith = gpd.GeoDataFrame({"geo_sym": ["C"]}, geometry=[area], crs=32646)
    rules = {
        key: {"version": "source", "knowledge_id": "1", "knowledge_revision": "1"}
        for key in ["P-01", "P-02", "P-03"]
    }
    config = {
        "grid_resolution_m": 50,
        "core_score_min": 0.6,
        "min_core_area_km2": 0.01,
        "min_zone_area_km2": 0.1,
        "support_smooth_m": 100,
    }
    # An advisory area cannot split the two real cores in one connected belt.
    profile = {"growth_threshold": 0.5, "large_zone_notice_km2": 3, "max_zone_count": 8}
    return delineate(
        base,
        fields,
        profile,
        area,
        lith,
        rules,
        {"C": {"name": "基岩", "category": "stratum"}},
        config,
    ), area


def test_connected_support_belt_with_multiple_cores_is_one_region():
    (frame, rows, heat, checks, cores), area = synthetic_regions()
    assert len(frame) == 1
    assert frame.area_km2.iloc[0] > 3
    assert frame.core_area_km2.iloc[0] == pytest.approx(0.08)
    assert checks["large_zone_count"] == 1
    assert checks["artificial_partition"] is False and checks["artificial_gap_m"] == 0
    assert frame.geometry.difference(area).area.sum() == 0
    assert frame.geometry.is_valid.all()


def test_real_gap_separates_support_islands_without_artificial_spacing():
    (frame, rows, heat, checks, cores), area = synthetic_regions(gap=True)
    assert len(frame) == 2
    assert frame.geometry.area.sum() == pytest.approx(frame.geometry.union_all().area)
    assert checks["maximum_overlap_m2"] == 0
    assert checks["artificial_gap_m"] == 0
    assert np.all(heat[:, 39:41] == -9999)
    assert frame.core_area_km2.le(frame.area_km2).all()
    assert frame.geometry.is_valid.all()


def test_smooth_boundary_is_extracted_from_field_and_retains_missing_data_hole():
    sys.path[:0] = [str(CORE), str(CANDIDATE)]
    from region_boundaries import extract_regions, topology_report

    y, x = np.mgrid[-1000:1001:50, -1000:1001:50]
    margin = 1 - (x**2 + y**2) / 600**2
    transform = from_origin(-1025, 1025, 50, 50)
    allowed = box(-1100, -1100, 1100, 1100).difference(box(-100, -100, 100, 100))
    result = extract_regions(margin, transform, allowed)
    assert len(result) == 1 and len(result[0].interiors) == 1
    coordinates = np.asarray(result[0].exterior.coords)
    assert np.max(np.abs(np.linalg.norm(coordinates, axis=1) - 600)) < 2
    assert result[0].difference(allowed).area == 0
    assert topology_report(result)["maximum_overlap_m2"] == 0


def test_unknown_candidate_parameter_cannot_silently_restore_partitioning():
    sys.path[:0] = [str(CORE), str(CANDIDATE)]
    configuration = runpy.run_path(str(CANDIDATE / "main.py"))["configuration"]
    for key in ["between_zone_gap_m", "region_seed_spacing_m", "max_geodesic_reach_m"]:
        with pytest.raises(ValueError, match="未声明参数"):
            configuration(type("Context", (), {"parameters": {key: 50}})())


def test_touching_and_overlapping_boundaries_are_merged_before_region_ids():
    sys.path[:0] = [str(CORE), str(CANDIDATE)]
    from region_boundaries import merge_connected, topology_report

    connected = [box(0, 0, 2, 2), box(1, 0, 3, 2), box(3, 2, 4, 3)]
    separate = box(10, 0, 11, 1)
    result = merge_connected([*connected, separate])
    assert len(result) == 2
    assert sorted(geometry.area for geometry in result) == [1, 7]
    assert topology_report(result)["maximum_overlap_m2"] == 0
