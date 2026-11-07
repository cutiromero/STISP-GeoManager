"""Independent expectations for bounded, corrected-only prospect targets."""

import json
import sys

import geopandas as gpd
import numpy as np
import pytest
import rasterio

from apps.agent.geology_multi_results import table_rows, model_results
from tests.unit.test_geology_multi_algorithms import (
    CORE,
    KEYS,
    Context,
    fixture,
    load,
    read,
    write,
)


def setup_prospect(
    tmp_path, *, separated=False, downweight=False, no_structure=False, cover=False
):
    initial, _ = fixture(tmp_path)
    for key in KEYS:
        with rasterio.open(initial.inputs[key], "r+") as stream:
            values = np.zeros(stream.shape, dtype="uint8")
            if key == "hematite":
                values[25, 58] = values[75, 58] = 1
            if key == "chlorite":
                values[25, 60] = values[75, 60] = 1
                if separated:
                    values[:] = 0
                    values[0, 0] = 1
            stream.write(values, 1)
        if downweight:
            path = tmp_path / (key + "_weight.tif")
            with rasterio.open(initial.inputs[key]) as src:
                profile = {**src.profile, "dtype": "float32"}
            with rasterio.open(path, "w", **profile) as dst:
                dst.write(np.full((100, 100), 0.5, dtype="float32"), 1)
            initial.inputs[key + "_weight"] = path
    if no_structure:
        frame = gpd.read_file(initial.inputs["faults"])
        frame["state"] = "exclude"
        frame["weight"] = 0
        frame.to_file(initial.inputs["faults"], layer="data", driver="GPKG")
    if cover:
        rows = read(initial.inputs["rules"])
        units = json.loads(rows[0]["units_json"])
        for unit in units.values():
            unit["category"] = "cover"
        rows[0]["units_json"] = json.dumps(units)
        write(initial.inputs["rules"], rows)
    relations = Context(tmp_path / "relations", initial.inputs, initial.parameters)
    load("relations")(relations)
    inputs = dict(initial.inputs)
    path = relations.output_path("intersections.gpkg")
    if path.exists():
        inputs["intersections"] = path
    return Context(tmp_path / "prospect", inputs, initial.parameters)


def test_sparse_separate_pixels_form_neighbourhood_evidence_without_before_inputs(
    tmp_path,
):
    context = setup_prospect(tmp_path)
    assert not any(key.startswith("before_") for key in context.inputs)
    load("prospect")(context)
    frame = gpd.read_file(context.output_path("after_zones.gpkg"))
    assert len(frame) == 2 and set(frame.zone_id) == {"P001", "P002"}
    assert "grade" not in frame
    assert not context.output_path("before_zones.gpkg").exists()
    evidence = read(context.output_path("evidence.csv"))
    for row in evidence:
        assert row["phase"] == "after" and row["schema_version"] == "2"
        conditions = json.loads(row["conditions_json"])
        assert (
            conditions["structure_supported_fraction"]
            == conditions["bedrock_supported_fraction"]
            == 1
        )
        assert conditions["min_weighted_type_count"] == 2
        assert conditions["favourable_fraction"] == 0
    summary = table_rows(context.output_path("evidence.csv"), "evidence")
    assert summary["aggregate"]["byPhase"][0]["zoneCount"] == 2
    assert "byPhaseAndGrade" not in summary["aggregate"]
    assert model_results([{"key": "evidence", **summary}], stage_name="prospect")
    with rasterio.open(context.output_path("prospect_support.tif")) as stream:
        support = stream.read(1, masked=True)
        assert support.count() and support.min() >= 0 and support.max() <= 1
        assert np.ma.getmaskarray(support).any()


@pytest.mark.parametrize(
    "options",
    [
        {"separated": True},
        {"downweight": True},
        {"no_structure": True},
        {"cover": True},
    ],
)
def test_insufficient_or_disallowed_evidence_stays_empty(tmp_path, options):
    context = setup_prospect(tmp_path, **options)
    load("prospect")(context)
    assert not context.output_path("after_zones.gpkg").exists()
    assert read(context.output_path("statistics.csv"))[0]["zone_count"] == "0"
    assert read(context.output_path("evidence.csv")) == []
    with rasterio.open(context.output_path("prospect_support.tif")) as stream:
        assert stream.read(1, masked=True).count() == 0


def test_count_and_area_caps_do_not_create_or_cut_targets(tmp_path):
    context = setup_prospect(tmp_path)
    context.parameters["max_zone_count"] = 1
    load("prospect")(context)
    assert read(context.output_path("statistics.csv"))[0]["zone_count"] == "1"
    metrics = json.loads(context.output_path("quality.json").read_text())["metrics"]
    assert (
        metrics["eligible_component_count"] == 2
        and metrics["not_selected_by_count_limit"] == 1
    )
    context.parameters["max_zone_area_m2"] = 1000
    load("prospect")(Context(tmp_path / "limited", context.inputs, context.parameters))
    assert not (tmp_path / "limited/after_zones.gpkg").exists()


def test_old_rule_semantics_are_rejected_explicitly(tmp_path):
    context = setup_prospect(tmp_path)
    rows = read(context.inputs["rules"])
    for row in rows:
        if row["rule_id"] == "P-02":
            params = json.loads(row["params_json"])
            params.pop("evidence_method")
            row["params_json"] = json.dumps(params)
    write(context.inputs["rules"], rows)
    with pytest.raises(ValueError, match="显式绑定邻域"):
        load("prospect")(context)
    assert not list(context.directory.iterdir())


@pytest.mark.parametrize("distance", [0, 1, 1.5, 3, 100])
def test_circular_neighbourhood_matches_brute_force(distance):
    sys.path.insert(0, str(CORE))
    from multi_prospect_raster import circular_maximum

    values = np.random.default_rng(42).random((4, 6))
    expected = np.zeros_like(values)
    for row in range(4):
        for col in range(6):
            expected[row, col] = max(
                values[y, x]
                for y in range(4)
                for x in range(6)
                if (row - y) ** 2 + (col - x) ** 2 <= distance**2
            )
    np.testing.assert_allclose(circular_maximum(values, distance, 1), expected)
