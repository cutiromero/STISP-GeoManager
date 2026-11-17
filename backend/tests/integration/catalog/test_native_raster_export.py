"""Native downloads preserve scientific TIFFs; reprojection and sidecars still warp."""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from apps.catalog.export import export_raster_tif
from apps.core.storage import raster_source_path
from apps.projects.context import ProjectScope, project_scope
from apps.raster.models import RasterDataset
from tests.integration.test_compute import setup_compute  # noqa:F401

# ruff:noqa:F811
pytestmark = pytest.mark.django_db


def source_dataset(external=False):
    source = raster_source_path("export-native.tif")
    source.parent.mkdir(parents=True, exist_ok=True)
    values = np.ones((32, 32), dtype="uint8")
    mask = np.full((32, 32), 255, dtype="uint8")
    mask[:4, :4] = 0
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=not external):
        with rasterio.open(
            source,
            "w",
            driver="GTiff",
            width=32,
            height=32,
            count=1,
            dtype="uint8",
            crs="EPSG:4326",
            transform=from_origin(120, 32, 0.01, 0.01),
            nodata=255,
            tiled=True,
            compress="deflate",
        ) as out:
            out.write_colormap(
                1, {0: (0, 0, 0, 0), 1: (101, 216, 164, 255), 255: (0, 0, 0, 0)}
            )
            out.write(values, 1)
            out.write_mask(mask)
            out.set_band_description(1, "目标类别")
            out.update_tags(observed_period="2025-03/2025-12")
    dataset = RasterDataset.objects.create(
        name="原生分类成果",
        code="export-native",
        source_relative_path="export-native.tif",
        source_format="GTiff",
        status="ready",
    )
    return source, dataset, mask


def test_native_download_preserves_full_tiff_bytes_grid_masks_and_metadata(
    setup_compute, tmp_path
):
    env = setup_compute
    with project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    ):
        source, dataset, mask = source_dataset()
        target = tmp_path / "native-download.tif"
        with patch(
            "apps.catalog.export.run_gdal_command",
            side_effect=AssertionError("Unnecessary full-scene warp"),
        ):
            export_raster_tif(dataset.pk, None, target)
        assert source.read_bytes() == target.read_bytes()
        with rasterio.open(target) as result:
            assert result.crs.to_epsg() == 4326 and result.transform == from_origin(
                120, 32, 0.01, 0.01
            )
            assert (
                result.descriptions == ("目标类别",)
                and result.tags()["observed_period"] == "2025-03/2025-12"
            )
            assert result.colormap(1)[1][:3] == (101, 216, 164)
            np.testing.assert_array_equal(result.dataset_mask(), mask)


def test_external_masks_are_materialized_instead_of_exporting_an_incomplete_tiff(
    setup_compute, tmp_path
):
    env = setup_compute
    with project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    ):
        source, dataset, mask = source_dataset(external=True)
        assert Path(str(source) + ".msk").exists()
        target = tmp_path / "materialized-mask.tif"
        export_raster_tif(dataset.pk, None, target)
        with rasterio.open(target) as result:
            np.testing.assert_array_equal(result.dataset_mask(), mask)
            assert result.width == 32 and result.height == 32


def test_explicit_existing_crs_preserves_native_bytes_without_full_scene_warp(
    setup_compute, tmp_path
):
    env = setup_compute
    with project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    ):
        source, dataset, _ = source_dataset()
        target = tmp_path / "same-crs.tif"
        with patch(
            "apps.catalog.export.run_gdal_command",
            side_effect=AssertionError("Same CRS must not resample scientific pixels"),
        ):
            export_raster_tif(dataset.pk, 4326, target)
        assert target.read_bytes() == source.read_bytes()


def test_requested_reprojection_is_still_performed(setup_compute, tmp_path):
    env = setup_compute
    with project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    ):
        _, dataset, _ = source_dataset()
        target = tmp_path / "projected.tif"
        export_raster_tif(dataset.pk, 3857, target)
        with rasterio.open(target) as result:
            assert result.crs.to_epsg() == 3857
