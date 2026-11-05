"""Exact connected components and frozen pre-streaming operator results."""

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from scipy import ndimage

from tests.unit.test_geology_multi_algorithms import (
    CORE,
    KEYS,
    Context,
    X,
    Y,
    approval_context,
    check,
    fixture,
    load,
    raster_inputs,
    read,
    write,
)

EXPECTED = Path(__file__).parents[1] / "fixtures" / "raster_streaming_expected.json"


@pytest.fixture
def streaming(monkeypatch):
    monkeypatch.syspath_prepend(str(CORE))
    import multi_windows

    monkeypatch.setattr(multi_windows, "FULL_RASTER_PIXELS", 1)
    monkeypatch.setattr(multi_windows, "WINDOW_SIZE", 17)
    return multi_windows


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_components_merge_edges_corners_and_row_major_ties(tmp_path, streaming, seed):
    values = np.random.default_rng(seed).random((53, 61)) < 0.15
    values[16:19, 16:19] = np.eye(3, dtype=bool)
    values[32:36, 33] = True
    path = tmp_path / "source.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=61,
        height=53,
        count=1,
        dtype="uint8",
        transform=from_origin(X, Y, 10, 10),
        crs=32646,
    ) as target:
        target.write(values.astype("uint8"), 1)
    labels, count = ndimage.label(values, structure=np.ones((3, 3)))
    identities, sizes = np.unique(labels, return_counts=True)
    sizes = dict(zip(identities.tolist(), sizes.tolist()))
    objects = ndimage.find_objects(labels)
    top = sorted(
        range(1, count + 1), key=lambda identity: (-sizes[identity], identity)
    )[:3]
    with (
        rasterio.open(path) as source,
        streaming.Components(
            tmp_path / "labels.tif",
            source,
            lambda window: source.read(1, window=window) > 0,
        ) as components,
    ):
        actual_count, pixels, bounds, actual_top = components.summary()
        assert actual_count == count
        assert pixels == int(values.sum())
        rows, columns = np.where(values)
        assert bounds == (rows.min(), columns.min(), rows.max() + 1, columns.max() + 1)
        assert actual_top == [
            (
                sizes[identity],
                objects[identity - 1][0].start,
                objects[identity - 1][1].start,
                objects[identity - 1][0].stop,
                objects[identity - 1][1].stop,
            )
            for identity in top
        ]
        for threshold in (1, 3, 6, 25):
            expected = values & (
                np.array([sizes.get(identity, 0) for identity in range(count + 1)])[
                    labels
                ]
                < threshold
            )
            for window in streaming.windows(source.profile):
                row, column = int(window.row_off), int(window.col_off)
                np.testing.assert_array_equal(
                    components.small(window, threshold),
                    expected[
                        row : row + int(window.height),
                        column : column + int(window.width),
                    ],
                )


def comparison_fixture(directory, case):
    initial, _ = fixture(directory)
    rows = read(initial.inputs["rules"])
    units = json.loads(rows[0]["units_json"])
    units["C"]["group"] = "carbonate" if case == 0 else "carbonate_interbed"
    units["O"]["group"] = "red_clastic" if case == 0 else "loose"
    rows[0]["units_json"] = json.dumps(units)
    for row in rows:
        if row["rule_id"] == "P-02":
            params = json.loads(row["params_json"])
            params["min_types"] = 0.3
            row["params_json"] = json.dumps(params)
    write(initial.inputs["rules"], rows)
    for index, key in enumerate(KEYS):
        generator = np.random.default_rng(31 + index)
        values = (generator.random((87, 103)) < 0.08).astype("int16")
        values[30:50, 40:60] = 1
        values[0, :7] = -9
        with rasterio.open(
            initial.inputs[key],
            "w",
            driver="GTiff",
            width=103,
            height=87,
            count=1,
            dtype="int16",
            nodata=-9,
            crs=32646,
            transform=from_origin(X - 3, Y + 1007, 11, 12),
        ) as target:
            target.write(values, 1)
        path = directory / (key + "_weight.tif")
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=103,
            height=87,
            count=1,
            dtype="float64",
            crs=32646,
            transform=from_origin(X - 3, Y + 1007, 11, 12),
        ) as target:
            target.write(
                generator.choice([0.25, 0.5, 0.999999999, 1], size=values.shape), 1
            )
        initial.inputs[key + "_weight"] = path
    return initial


def fingerprints(directory):
    result = {}
    for path in sorted(directory.iterdir()):
        if path.suffix == ".tif":
            with rasterio.open(path) as source:
                result[path.name] = {
                    "pixels": hashlib.sha256(source.read(1).tobytes()).hexdigest(),
                    "dtype": source.dtypes[0],
                    "shape": list(source.shape),
                    "crs": source.crs.to_epsg(),
                    "transform": list(source.transform),
                }
        elif path.suffix == ".gpkg":
            frame = gpd.read_file(path)
            result[path.name] = json.loads(frame.to_json(drop_id=True))
        elif path.suffix in {".csv", ".json"}:
            result[path.name] = (
                read(path) if path.suffix == ".csv" else json.loads(path.read_text())
            )
    return result


def run_comparison(directory, case, before_prospect=None):
    initial = comparison_fixture(directory, case)
    findings, _ = check(initial)
    approved = [row for row in findings if row["element"] == "alteration"]
    edited = approval_context(directory, initial, approved)
    load("apply")(edited)
    relations = Context(
        directory / "relations",
        {**initial.inputs, "faults": edited.output_path("faults.gpkg")},
        initial.parameters,
    )
    load("relations")(relations)
    prospect = Context(
        directory / "prospect",
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
    if before_prospect:
        before_prospect()
    load("prospect")(prospect)
    return {
        stage: fingerprints(directory / stage)
        for stage in ("check", "apply", "prospect")
    }


@pytest.mark.parametrize("case", [0, 1])
def test_all_outputs_equal_pre_streaming_baseline(
    tmp_path, streaming, case, monkeypatch
):
    expected = json.loads(EXPECTED.read_text())[str(case)]
    import multi_raster

    def forbid_inspect():
        monkeypatch.setattr(
            multi_raster.RasterAlterations,
            "inspect",
            lambda *args: pytest.fail("prospect must not inspect alteration rules"),
        )

    assert run_comparison(tmp_path, case, forbid_inspect) == expected
    assert not list(tmp_path.rglob(".raster-*"))
