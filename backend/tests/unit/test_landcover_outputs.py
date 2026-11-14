"""Classification precedence, original grid and categorical import evidence."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from apps.compute import data
from apps.compute.packages import ComputeError
from apps.compute.raster_outputs import rendering_rules

ROOT = Path(__file__).resolve().parents[3]


def test_final_codes_keep_delivered_priority_and_transparent_invalid(tmp_path):
    path = ROOT / "examples/compute/landcover-unet/core/raster_workflow.py"
    spec = importlib.util.spec_from_file_location("landcover_composition", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    profile = {
        "driver": "GTiff",
        "height": 4,
        "width": 4,
        "count": 3,
        "dtype": "uint8",
        "crs": "EPSG:3857",
        "transform": from_origin(10, 20, 2, 2),
        "nodata": 0,
    }
    rgb = np.full((3, 4, 4), 100, dtype=np.uint8)
    rgb[:, 3, 3] = 0
    image = tmp_path / "rgb.tif"
    with rasterio.open(image, "w", **profile) as dst:
        dst.write(rgb)
    masks = {}
    for name in module.CODES:
        values = np.zeros((4, 4), dtype=np.uint8)
        values[0, 0] = 1
        if name in {"road", "forest"}:
            values[0, 1] = 1
        if name == "road":
            values[0, 2] = 1
        mask = tmp_path / (name + ".tif")
        with rasterio.open(mask, "w", **{**profile, "count": 1, "nodata": 255}) as dst:
            dst.write(values, 1)
        masks[name] = mask
    result = module.compose(image, masks, tmp_path / "result.tif")
    with rasterio.open(tmp_path / "result.tif") as src:
        values = src.read(1)
        assert values[0, :3].tolist() == [6, 4, 8]
        assert values[1, 1] == 1 and values[3, 3] == 255
        assert src.transform == profile["transform"]
    assert sum(result["counts"].values()) == 16


def classification(tmp_path, monkeypatch, unknown=False):
    monkeypatch.setattr(data, "config", lambda: SimpleNamespace(output_mb=10))
    path = tmp_path / "result.tif"
    values = np.full((16, 16), 6, dtype=np.uint8)
    values[0, 0] = 255
    if unknown:
        values[1, 1] = 3
    legend = [
        {"code": 6, "name": "建筑", "rgba": [255, 185, 185, 255]},
        {"code": 255, "name": "无效区", "rgba": [0, 0, 0, 0]},
    ]
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=16,
        width=16,
        count=1,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(0, 40, 2, 2),
        nodata=255,
    ) as dst:
        dst.write(values, 1)
        dst.write_colormap(1, {6: (255, 185, 185, 255), 255: (0, 0, 0, 0)})
        dst.update_tags(
            stisp_categorical=json.dumps(
                {"schemaVersion": 1, "legend": legend, "transparentValues": [255]}
            )
        )
    return path


def test_categorical_metadata_preserves_non_contiguous_codes_and_labels(
    tmp_path, monkeypatch
):
    metadata = data.inspect_output(classification(tmp_path, monkeypatch), "raster")
    assert metadata["rasterKind"] == "categorical"
    rules = rendering_rules(metadata)
    assert rules["mode"] == "unique" and rules["stretch"]["enabled"] is False
    assert rules["uniqueValues"][0] == {
        "value": 6,
        "label": "建筑",
        "color": "#ffb9b9ff",
    }


def test_undeclared_pixel_cannot_pass_categorical_contract(tmp_path, monkeypatch):
    with pytest.raises(ComputeError, match="未声明"):
        data.inspect_output(classification(tmp_path, monkeypatch, True), "raster")
