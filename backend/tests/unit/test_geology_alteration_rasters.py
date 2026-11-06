import json

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from tests.unit.test_geology_multi_algorithms import (
    X,
    Y,
    KEYS,
    approval_context,
    check,
    fixture,
    load,
    read,
    rect,
    store,
    write,
)


def pixels(path):
    with rasterio.open(path) as source:
        return source.read(1)


def scene(tmp_path, size=20):
    tmp_path.mkdir(parents=True, exist_ok=True)
    context, _ = fixture(tmp_path)
    lithology = gpd.GeoDataFrame(
        {
            "feature_id": ["G1", "G2"],
            "name": ["carbonate", "old"],
            "geo_sym": ["C", "O"],
        },
        geometry=[rect(0, 0, 500, 1000), rect(500, 0, 1000, 1000)],
        crs=32646,
    )
    store(lithology, context.inputs["lithology"])
    for key in KEYS:
        with rasterio.open(
            context.inputs[key],
            "w",
            driver="GTiff",
            height=size,
            width=size,
            count=1,
            dtype="uint8",
            crs=32646,
            transform=from_origin(X, Y + 1000, 1000 / size, 1000 / size),
        ) as target:
            target.write(
                np.ones((size, size), dtype="uint8")
                if key == "calcite"
                else np.zeros((size, size), dtype="uint8"),
                1,
            )
    context.parameters["segment"] = "alteration"
    return context


def test_cross_unit_connected_alteration_is_only_partly_excluded(tmp_path):
    context = scene(tmp_path)
    findings, _ = check(context)
    selected = [row for row in findings if row["rule_id"] == "A-01"]
    assert len(selected) == 1
    measurement = json.loads(selected[0]["measurements_json"])
    assert measurement["pixel_count"] == 200
    assert measurement["component_count"] == 1
    assert measurement["boundary"] is False
    edited = approval_context(tmp_path, context, selected)
    load("apply")(edited)
    corrected = pixels(edited.output_path("calcite_corrected.tif"))
    changed = pixels(edited.output_path("calcite_changes.tif"))
    assert not corrected[:, :10].any() and corrected[:, 10:].all()
    assert (changed[:, :10] == 1).all() and not changed[:, 10:].any()
    assert not pixels(edited.output_path("calcite_weight.tif"))[:, :10].any()
    quality = next(
        row
        for row in read(context.output_path("alteration_quality.csv"))
        if row["mineral"] == "calcite"
    )
    assert int(quality["hydrothermal_pixels"]) == 200
    assert float(quality["hydrothermal_area_m2"]) == 500000
    assert len(read(edited.output_path("changes.csv"))) == 1
    with rasterio.open(edited.output_path("calcite_corrected.tif")) as source:
        assert source.tags(ns="IMAGE_STRUCTURE")["LAYOUT"] == "COG"


def test_shared_lithology_preparation_preserves_different_mineral_grids(tmp_path):
    context = scene(tmp_path)
    with rasterio.open(
        context.inputs["dolomite"],
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype="uint8",
        crs=32646,
        transform=from_origin(X, Y + 1000, 100, 100),
    ) as target:
        target.write(np.ones((10, 10), dtype="uint8"), 1)
    findings, _ = check(context)
    selected = [row for row in findings if row["rule_id"] == "A-01"]
    sizes = {
        json.loads(row["measurements_json"])["mineral"]: json.loads(
            row["measurements_json"]
        )["pixel_count"]
        for row in selected
    }
    assert sorted(sizes.values()) == [50, 200]
    edited = approval_context(tmp_path, context, selected)
    load("apply")(edited)
    fine = pixels(edited.output_path("calcite_corrected.tif"))
    coarse = pixels(edited.output_path("dolomite_corrected.tif"))
    assert fine.shape == (20, 20) and coarse.shape == (10, 10)
    assert not fine[:, :10].any() and fine[:, 10:].all()
    assert not coarse[:, :5].any() and coarse[:, 5:].all()


def test_small_components_are_per_mineral_and_unit_and_default_to_downweight(tmp_path):
    context = scene(tmp_path)
    rows = read(context.inputs["rules"])
    for row in rows:
        if row["rule_id"] == "A-05":
            row["params_json"] = '{"min_area_m2":6000}'
    write(context.inputs["rules"], rows)
    for key in ("hematite", "chlorite"):
        with rasterio.open(context.inputs[key], "r+") as target:
            values = target.read(1)
            values[5, 9:11] = 1
            values[6, 8] = 1
            target.write(values, 1)
    findings, _ = check(context)
    small = [row for row in findings if row["rule_id"] == "A-05"]
    assert len(small) == 4
    assert all(row["suggested_action"] == "downweight" for row in small)
    assert sorted(
        json.loads(row["measurements_json"])["pixel_count"] for row in small
    ) == [1, 1, 2, 2]
    edited = approval_context(tmp_path, context, small)
    load("apply")(edited)
    for key in ("hematite", "chlorite"):
        raw = pixels(context.inputs[key])
        assert np.array_equal(raw, pixels(edited.output_path(key + "_corrected.tif")))
        assert (pixels(edited.output_path(key + "_weight.tif"))[raw == 1] == 0.5).all()
        assert (pixels(edited.output_path(key + "_changes.tif"))[raw == 1] == 5).all()


def test_summary_cardinality_is_bounded_by_groups_not_pixels(tmp_path):
    first = scene(tmp_path / "coarse", 20)
    second = scene(tmp_path / "fine", 40)
    check(first)
    check(second)
    coarse = read(first.output_path("alteration_summary.csv"))
    fine = read(second.output_path("alteration_summary.csv"))
    assert len(coarse) == len(fine) == 1
    assert coarse[0]["group_id"] == fine[0]["group_id"]
    assert int(fine[0]["pixel_count"]) == 4 * int(coarse[0]["pixel_count"])
    assert float(fine[0]["area_m2"]) == float(coarse[0]["area_m2"])
    assert "geometry_json" not in fine[0]
    assert len(json.loads(fine[0]["representatives_json"])) <= 3


def test_unaligned_lithology_boundary_is_reported_separately(tmp_path):
    context = scene(tmp_path)
    frame = gpd.read_file(context.inputs["lithology"])
    frame.geometry = [rect(0, 0, 526, 1000), rect(526, 0, 1000, 1000)]
    store(frame, context.inputs["lithology"])
    findings, _ = check(context)
    boundary = [
        json.loads(row["measurements_json"])
        for row in findings
        if json.loads(row["measurements_json"])["boundary"]
    ]
    assert len(boundary) == 1 and boundary[0]["pixel_count"] == 20


def test_weighted_prospect_aggregation_uses_pixel_fraction(tmp_path):
    context = scene(tmp_path)
    with rasterio.open(context.inputs["calcite"]) as source:
        profile = {**source.profile, "dtype": "float32"}
        weights = np.full(source.shape, 0.5, dtype="float32")
    context.inputs["calcite_weight"] = tmp_path / "calcite_weight.tif"
    with rasterio.open(context.inputs["calcite_weight"], "w", **profile) as target:
        target.write(weights, 1)
    load("check")
    from multi_raster import RasterAlterations
    from multi_io import inputs, settings

    config = settings(context)
    lithology, _, area, rules, units, _, snapshot = inputs(context, config)
    raster = RasterAlterations(context, config, area)
    raster.inspect(lithology, rules, units, snapshot)
    aggregate = raster.aggregate(
        from_origin(X, Y + 1000, 100, 100), (10, 10), 32646, ["方解石化"]
    )
    assert np.allclose(aggregate, 0.5)


def test_freeze_rejects_changed_pixels_before_producing_corrected_output(tmp_path):
    context = scene(tmp_path)
    findings, _ = check(context)
    edited = approval_context(tmp_path, context, findings)
    with rasterio.open(context.inputs["calcite"], "r+") as target:
        values = target.read(1)
        values[0, 0] = 0
        target.write(values, 1)
    with pytest.raises(ValueError, match="改变|不符|不一致"):
        load("apply")(edited)
    assert not edited.output_path("calcite_corrected.tif").exists()
