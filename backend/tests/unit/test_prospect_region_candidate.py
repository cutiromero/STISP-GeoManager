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


def test_growing_regions_stay_connected_bounded_and_nonoverlapping():
    sys.path[:0] = [str(CORE), str(CANDIDATE)]
    from region_zones import delineate

    shape = (40, 80)
    score = np.full(shape, 0.75)
    growth = np.ones(shape, dtype=bool)
    growth[:, 39:41] = False
    core = np.zeros(shape, dtype=bool)
    core[18:22, 18:22] = True
    core[18:22, 58:62] = True
    transform = from_origin(300000, 4000000, 50, 50)
    area = box(300000, 3998000, 304000, 4000000)
    base = {
        "transform": transform,
        "dimensions": shape,
        "masks": {"favourable": np.ones(shape, dtype=bool)},
        "evidence": {
            "矿物A": {"presence": np.ones(shape)},
            "矿物B": {"presence": np.ones(shape)},
        },
    }
    fields = {
        "core": core,
        "growth": growth,
        "score": score,
        "structure": score,
        "alteration": score,
        "broad_count": np.full(shape, 2.5),
        "density": np.full(shape, 0.1),
    }
    lith = gpd.GeoDataFrame({"geo_sym": ["C"]}, geometry=[area], crs=32646)
    rules = {
        key: {"version": "source", "knowledge_id": "1", "knowledge_revision": "1"}
        for key in ["P-01", "P-02", "P-03"]
    }
    config = {
        "grid_resolution_m": 50,
        "region_seed_spacing_m": 1000,
        "max_geodesic_reach_m": 2000,
        "core_score_min": 0.6,
        "min_core_area_km2": 0.01,
        "min_zone_area_km2": 0.1,
    }
    profile = {"growth_threshold": 0.5, "max_zone_area_km2": 3, "max_zone_count": 8}
    frame, rows, heat, diagnostics, cores = delineate(
        base, fields, profile, area, lith, rules, {"C": {"name": "基岩"}}, config
    )
    assert len(frame) >= 2 and frame.geometry.is_valid.all()
    assert frame.area_km2.max() <= 3 and (frame.core_area_km2 > 0).all()
    assert frame.geometry.area.sum() == pytest.approx(frame.geometry.union_all().area)
    assert frame.geometry.difference(area).area.sum() == 0
    assert np.all(heat[:, 39:41] == -9999)
    assert frame.core_area_km2.le(frame.area_km2).all()


def test_smoothed_adjacent_regions_have_zero_overlap_and_real_spacing():
    sys.path[:0] = [str(CORE), str(CANDIDATE)]
    from region_boundaries import smooth_nonoverlapping
    from shapely.ops import unary_union

    polygons = [
        box(300000, 4000000, 302000, 4002000),
        box(301990, 4000200, 304000, 4001800),
        box(303990, 4000000, 306000, 4002000),
    ]
    allowed = box(299000, 3999000, 307000, 4003000)
    result, checks = smooth_nonoverlapping(polygons, allowed, 100, 50)
    assert len(result) == 3 and all(geometry.is_valid for geometry in result)
    assert checks["maximum_overlap_m2"] == 0
    assert checks["actual_minimum_distance_m"] >= 50 - 0.01
    assert sum(geometry.area for geometry in result) == pytest.approx(
        unary_union(result).area
    )
    assert all(geometry.difference(allowed).area == 0 for geometry in result)
