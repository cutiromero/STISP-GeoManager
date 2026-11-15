"""Native results retain pixels while maps read bounded XYZ windows."""

from unittest.mock import patch
import math
import io
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from PIL import Image
from apps.core.storage import raster_processed_path, raster_source_path
from apps.projects.context import project_scope, ProjectScope
from apps.raster.services.importer import import_raster_file
from apps.raster.services.renderer import (
    register_tile_style,
    render_xyz_tile,
    build_static_xyz_tile_pyramid,
)
from tests.integration.test_compute import setup_compute  # noqa:F401

# ruff:noqa:F811
pytestmark = pytest.mark.django_db


def test_native_large_classification_import_keeps_detail_with_bounded_tiles(
    setup_compute,
):
    env = setup_compute
    with project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    ):
        source = raster_source_path("large-result.tif")
        source.parent.mkdir(parents=True, exist_ok=True)
        data = np.full((128, 9000), 255, dtype="uint8")
        data[32:96, 4468:4532] = 1
        with rasterio.open(
            source,
            "w",
            driver="GTiff",
            width=9000,
            height=128,
            count=1,
            dtype="uint8",
            crs="EPSG:4326",
            nodata=255,
            transform=from_origin(120, 32, 0.001, 0.001),
            tiled=True,
            compress="deflate",
        ) as out:
            out.write_colormap(
                1, {0: (0, 0, 0, 0), 1: (101, 216, 164, 255), 255: (0, 0, 0, 0)}
            )
            out.write(data, 1)
            out.build_overviews([4, 32], rasterio.enums.Resampling.nearest)
        with patch(
            "apps.raster.services.importer.runtime_max_raster_side_pixels",
            return_value=1000,
        ):
            dataset = import_raster_file(
                source,
                name="全域分布",
                raster_kind="categorical",
                native_result=True,
                requested_default_rules={
                    "mode": "unique",
                    "bands": [1],
                    "stretch": {"enabled": False},
                    "alphaBand": "mask",
                    "nodata": {"enabled": True},
                    "uniqueValues": [
                        {"value": 1, "label": "互花米草", "color": "#65d8a4ff"},
                        {"value": 255, "label": "无效", "color": "#00000000"},
                    ],
                },
                uploader_id=env["owner"].pk,
            )
        assert dataset.status == "ready" and dataset.source_gdalinfo["size"] == [
            9000,
            128,
        ]
        assert dataset.processed_gdalinfo["geoManager"]["dynamicTiles"] is True
        with rasterio.open(source) as original:
            np.testing.assert_array_equal(original.read(1), data)
        with rasterio.open(
            raster_processed_path(dataset.processed_relative_path)
        ) as display:
            assert display.width > 8192
            values = display.read(1, out_shape=(16, 1000), masked=True)
            assert set(np.unique(values.compressed())) <= {0, 1}
        style = register_tile_style(dataset, dataset.default_rules)
        assert build_static_xyz_tile_pyramid(dataset, style["styleHash"]) is None
        z = style["maxZoom"]
        lon, lat = 124.5, 31.936
        x = int((lon + 180) / 360 * 2**z)
        y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2**z)
        png = render_xyz_tile(dataset.pk, style["styleHash"], z, x, y)
        pixels = np.array(Image.open(io.BytesIO(png)))
        assert pixels.shape == (256, 256, 4) and (pixels[:, :, 3] > 0).any()
        assert set(map(tuple, pixels[pixels[:, :, 3] > 0, :3])) == {(101, 216, 164)}


def test_native_global_observation_clips_only_mercator_display(setup_compute):
    env = setup_compute
    with project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    ):
        source = raster_source_path("global-observation.tif")
        source.parent.mkdir(parents=True, exist_ok=True)
        data = np.full((180, 360), 5, dtype="float32")
        with rasterio.open(
            source,
            "w",
            driver="GTiff",
            width=360,
            height=180,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            nodata=-9999,
            transform=from_origin(-180, 90, 1, 1),
        ) as out:
            out.write(data, 1)
        dataset = import_raster_file(
            source,
            name="全球观测",
            raster_kind="continuous",
            native_result=True,
            uploader_id=env["owner"].pk,
        )
        assert dataset.status == "ready" and dataset.source_gdalinfo["size"] == [
            360,
            180,
        ]
        assert (
            abs(dataset.bounds_4326[1] + 85.0511288) < 0.001
            and abs(dataset.bounds_4326[3] - 85.0511288) < 0.001
        )
        with rasterio.open(source) as original:
            assert original.bounds.top == 90 and original.bounds.bottom == -90
            np.testing.assert_array_equal(original.read(1), data)
