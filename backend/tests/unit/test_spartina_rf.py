"""Feature order, missing data, geographic area and window budgets."""

import importlib.util
import json
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from apps.compute.packages import ComputeError, validate_manifest
from apps.compute.raster_windows import windowed_metadata

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "spartina_core", ROOT / "examples/compute/spartina-rf/core.py"
)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


def test_manifest_and_window_use_original_grid_and_bounded_decoded_size():
    manifest = validate_manifest(
        json.loads((ROOT / "examples/compute/spartina-rf/operator.yaml").read_text())
    )
    port = manifest["inputs"][0]
    info = {
        "crs": "EPSG:4326",
        "sizeBytes": 11000000000,
        "rasterMetadata": {
            "size": [100000, 100000],
            "geoTransform": [110, 0.001, 0, 40, 0, -0.001],
            "bands": [{"type": "float32"}] * 16,
        },
    }
    data = windowed_metadata(
        port, info, {"west": 120, "south": 30, "east": 120.01, "north": 30.01}
    )
    assert data["rasterMetadata"]["size"] == [10, 10]
    assert data["rasterWindow"] == [10000, 9990, 10, 10]
    assert data["sizeBytes"] < 100000
    assert info["sizeBytes"] == 11000000000
    for coordinates in (
        {"west": 120, "south": 30, "east": 130, "north": 40},
        {"west": 120, "south": 31, "east": 119, "north": 32},
    ):
        with pytest.raises(ComputeError):
            windowed_metadata(port, info, coordinates)


def test_three_season_order_and_all_band_validity_are_preserved(tmp_path):
    files = {}
    for month, role in enumerate(core.ROLES):
        path = tmp_path / (role + ".tif")
        files[role] = path
        values = np.stack(
            [np.full((3, 4), month * 16 + band, dtype="float32") for band in range(16)]
        )
        if month == 2:
            values[15, 1, 1] = np.nan
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=3,
            width=4,
            count=16,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(120, 32, 0.001, 0.001),
            nodata=np.nan,
        ) as dst:
            dst.write(values)
            for index, name in enumerate(core.BANDS, 1):
                dst.set_band_description(index, name)

    class Model:
        n_features_in_ = 48
        classes_ = np.array([0, 1])

        def predict(self, data):
            np.testing.assert_array_equal(data[0], np.arange(48))
            return np.ones(len(data), dtype="uint8")

        def predict_proba(self, data):
            return np.tile([0.2, 0.8], (len(data), 1))

    result = core.infer(files, Model(), tmp_path / "output")
    assert result["validPixelCount"] == 11 and result["targetPixelCount"] == 11
    assert result["statistics"]["patch_count"] == 1
    assert result["statistics"]["coverage_percent"] == 100
    assert 10 < result["statistics"]["area_ha"] < 12
    with rasterio.open(tmp_path / "output/classification.tif") as src:
        assert src.read(1)[1, 1] == 255 and src.crs.to_epsg() == 4326
    with rasterio.open(tmp_path / "output/probability.tif") as src:
        assert src.read(1)[1, 1] == -9999
        assert src.read(1)[0, 0] == pytest.approx(0.8)
