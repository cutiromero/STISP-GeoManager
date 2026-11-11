"""Stacked and legacy mineral ports preserve the same computed observation domain."""

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from apps.core.data_adapters import combine_masks, binary_raster_masks

from tests.unit.test_geology_multi_algorithms import (
    Context,
    KEYS,
    approval_context,
    check,
    fixture,
    load,
    read,
)

LABELS = ["赤铁矿化", "绿泥石化", "水云母化", "方解石化", "白云石化"]


@pytest.mark.parametrize("nodata,external_mask", [(0, False), (255, False), (0, True)])
def test_binary_mask_normalization_keeps_observed_zero_and_real_missing(
    tmp_path, nodata, external_mask
):
    path = tmp_path / "source.tif"
    values = np.array([[0 if nodata == 0 else 255, 1], [0, 0]], dtype="uint8")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="uint8",
        crs=32646,
        transform=from_origin(300000, 4000000, 29, 29),
        nodata=nodata,
    ) as source:
        source.write(values, 1)
        if external_mask:
            source.write_mask(np.array([[0, 255], [255, 255]], dtype="uint8"))
    result = tmp_path / "normalized.tif"
    binary_raster_masks(path, result, label="检测类别")
    with rasterio.open(result) as normalized:
        expected = np.array(
            [[255 if nodata == 255 or external_mask else 0, 1], [0, 0]], dtype="uint8"
        )
        np.testing.assert_array_equal(normalized.read(1), expected)
        np.testing.assert_array_equal(
            normalized.read_masks(1), (expected != 255).astype("uint8") * 255
        )
    combined = tmp_path / "combined.tif"
    with rasterio.open(path) as source:
        combine_masks(
            [{"path": path, "label": "检测类别"}],
            combined,
            bounds=source.bounds,
            crs=source.crs,
            resolution=29,
        )
    with rasterio.open(combined) as normalized:
        np.testing.assert_array_equal(normalized.read(1), expected)
        np.testing.assert_array_equal(
            normalized.read_masks(1), (expected != 255).astype("uint8") * 255
        )


def test_apply_stack_keeps_computed_masks_including_valid_zero_pixels(tmp_path):
    initial, _ = fixture(tmp_path)
    findings, _ = check(initial)
    native_dir = tmp_path / "native"
    native_dir.mkdir()
    native = approval_context(
        native_dir, initial, findings, {row["issue_id"]: "keep" for row in findings}
    )
    load("apply")(native)
    stack_path = tmp_path / "mineral-stack.tif"
    with rasterio.open(initial.inputs[KEYS[0]]) as source:
        bounds, crs, resolution = source.bounds, source.crs, source.transform.a
    combine_masks(
        [
            {"path": initial.inputs[key], "label": label}
            for key, label in zip(KEYS, LABELS)
        ],
        stack_path,
        bounds=bounds,
        crs=crs,
        resolution=resolution,
    )
    stacked = Context(
        tmp_path / "stack-check",
        {
            **{key: value for key, value in initial.inputs.items() if key not in KEYS},
            "alteration_stack": stack_path,
        },
        initial.parameters,
    )
    load("check")(stacked)
    stack_findings = read(stacked.output_path("issues.csv"))
    stack_dir = tmp_path / "stacked"
    stack_dir.mkdir()
    edited = approval_context(
        stack_dir,
        stacked,
        stack_findings,
        {row["issue_id"]: "keep" for row in stack_findings},
    )
    load("apply")(edited)
    for suffix in ("corrected", "weight"):
        with rasterio.open(
            edited.output_path("alteration_stack_" + suffix + ".tif")
        ) as combined:
            for key, label in zip(KEYS, LABELS):
                band = combined.descriptions.index(label) + 1
                with rasterio.open(
                    native.output_path(key + "_" + suffix + ".tif")
                ) as legacy:
                    np.testing.assert_array_equal(
                        combined.read(band, masked=True).filled(0),
                        legacy.read(1, masked=True).filled(0),
                    )
                    np.testing.assert_array_equal(
                        combined.read_masks(band), legacy.read_masks(1)
                    )
