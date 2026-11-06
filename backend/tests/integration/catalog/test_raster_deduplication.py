from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from django.core.exceptions import PermissionDenied
from apps.catalog.resource_duplicates import raster_signature, verify_duplicate


def source(tmp_path, name, values, **options):
    path = tmp_path / name
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(95, 36, 0.01, 0.01),
        nodata=0,
        **options,
    ) as ds:
        ds.write(np.asarray(values, dtype="uint8"), 1)
    dataset = SimpleNamespace(processed_relative_path=str(path))
    related = SimpleNamespace(
        filter=lambda **kw: SimpleNamespace(first=lambda: dataset)
    )
    return SimpleNamespace(
        pk=1,
        id=1,
        name=name,
        project_tag_id=3,
        data_type="raster",
        is_compute_result=False,
        raster_datasets=related,
    )


def test_raster_signature_compares_pixels_grid_and_masks(tmp_path):
    before = source(tmp_path, "original.tif", [[1, 0], [2, 3]])
    same = source(tmp_path, "different_name.tif", [[1, 0], [2, 3]])
    changed = source(tmp_path, "changed.tif", [[1, 0], [2, 4]])
    with patch(
        "apps.catalog.resource_duplicates.raster_processed_path",
        side_effect=lambda value: value,
    ):
        assert raster_signature(before) == raster_signature(same)
        assert raster_signature(before) != raster_signature(changed)


def test_original_deduplication_requires_admin_and_actual_equivalence(tmp_path):
    before = source(tmp_path, "a.tif", [[1, 0], [2, 3]])
    same = source(tmp_path, "b.tif", [[1, 0], [2, 3]])
    same.id = 2
    with patch("apps.catalog.resource_duplicates.is_superadmin", return_value=False):
        with pytest.raises(PermissionDenied, match="管理员"):
            verify_duplicate(before, 2, None)
    with (
        patch("apps.catalog.resource_duplicates.is_superadmin", return_value=True),
        patch("apps.catalog.resource_duplicates.DataResource") as model,
        patch(
            "apps.catalog.resource_duplicates.raster_processed_path",
            side_effect=lambda value: value,
        ),
    ):
        model.objects.filter.return_value.exclude.return_value.first.return_value = same
        assert verify_duplicate(before, 2, None)["replacementResourceId"] == 2
        model.objects.filter.return_value.exclude.return_value.first.return_value = (
            source(tmp_path, "c.tif", [[9, 0], [2, 3]])
        )
        with pytest.raises(PermissionDenied, match="不同"):
            verify_duplicate(before, 2, None)
