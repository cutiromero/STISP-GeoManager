"""Large registered originals yield bounded, independently frozen ROI inputs."""

import json
from pathlib import Path
from uuid import uuid4
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from apps.catalog.models import DataResource
from apps.compute.data import freeze_input
from apps.compute.models import ComputeInput, ComputeTask
from apps.compute.services import validate_submission
from apps.core.storage import raster_source_path
from apps.projects.context import project_scope, ProjectScope
from apps.raster.models import RasterDataset
from tests.integration.test_compute import setup_compute  # noqa:F401

# ruff:noqa:F811
pytestmark = pytest.mark.django_db


def test_large_source_is_read_as_window_and_cache_is_bound_to_region(
    setup_compute, tmp_path
):
    env = setup_compute
    manifest = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "examples/compute/spartina-rf/operator.yaml"
        ).read_text()
    )
    manifest["runtime"] = "python-geospatial-v1"
    env["version"].manifest = manifest
    env["version"].save()
    scope = ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    with project_scope(scope):
        source = raster_source_path("large.tif")
        source.parent.mkdir(parents=True, exist_ok=True)
        values = np.tile(
            np.arange(32 * 32, dtype="float32").reshape(32, 32), (16, 1, 1)
        )
        with rasterio.open(
            source,
            "w",
            driver="GTiff",
            width=32,
            height=32,
            count=16,
            dtype="float32",
            nodata=np.nan,
            crs="EPSG:4326",
            transform=from_origin(120, 32, 0.001, 0.001),
        ) as dst:
            dst.write(values)
        resource = DataResource.objects.create(
            name="大陆影像",
            code="large-original",
            data_type="raster",
            storage_path="large.tif",
            coordinate_system="EPSG:3857",
            size_bytes=11000000000,
        )
        RasterDataset.objects.create(
            name="大陆影像",
            code="large-original",
            data_resource=resource,
            source_relative_path="large.tif",
            status="ready",
            band_count=16,
        )
        parameters = {
            "west": 120.004,
            "south": 31.988,
            "east": 120.012,
            "north": 31.996,
        }
        request = {
            "name": "窗口",
            "idempotencyKey": uuid4().hex,
            "versionId": env["version"].pk,
            "inputs": {role: resource.pk for role in ("march", "august", "december")},
            "parameters": parameters,
        }
        validated = validate_submission(env["owner"], request)
        metadata = validated["resources"][0][2]
        assert metadata["rasterWindow"] == [4, 4, 8, 8]
        assert metadata["sizeBytes"] < 100000
        task = ComputeTask.objects.create(
            owner=env["owner"],
            version=env["version"],
            parameters=parameters,
            status="queued",
            idempotency_key=uuid4().hex,
            request_hash="c" * 64,
        )
        item = ComputeInput.objects.create(
            task=task,
            key="march",
            resource=resource,
            snapshot={**metadata, "updatedAt": resource.updated_at.isoformat()},
        )
        directory = tmp_path / "task"
        directory.mkdir()
        result = freeze_input(item, directory)
        assert result["resourceId"] == resource.pk
        with rasterio.open(directory / "march.tif") as src:
            assert (src.width, src.height, src.count) == (8, 8, 16)
            assert src.crs.to_epsg() == 4326
            np.testing.assert_array_equal(src.read(1), values[0, 4:12, 4:12])
        from apps.compute.raster_windows import windowed_metadata

        info = windowed_metadata(
            manifest["inputs"][0],
            {
                **metadata,
                "sizeBytes": resource.size_bytes,
                "rasterMetadata": {
                    **metadata["rasterMetadata"],
                    "size": [32, 32],
                    "geoTransform": [120, 0.001, 0, 32, 0, -0.001],
                },
            },
            {"west": 120.012, "south": 31.988, "east": 120.020, "north": 31.996},
        )
        other = ComputeInput.objects.create(
            task=task,
            key="august",
            resource=resource,
            snapshot={**info, "updatedAt": resource.updated_at.isoformat()},
        )
        second = tmp_path / "second"
        second.mkdir()
        freeze_input(other, second)
        with rasterio.open(second / "august.tif") as src:
            np.testing.assert_array_equal(src.read(1), values[0, 4:12, 12:20])
        assert item.checksum != other.checksum
        assert resource.size_bytes == 11000000000
        assert source.exists()
