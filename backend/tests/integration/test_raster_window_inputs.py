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
    for port in manifest["inputs"]:
        for key in ("streaming", "months", "sameYear"):
            port["raster"].pop(key, None)
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


def test_streaming_full_extent_stays_readable_after_freeze_and_rejects_source_changes(
    setup_compute, tmp_path
):
    from types import SimpleNamespace
    from unittest.mock import patch
    from datetime import date
    from apps.catalog.models import ResourceObservationMetadata
    from apps.compute.packages import ComputeError

    env = setup_compute
    manifest = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "examples/compute/spartina-rf/operator.yaml"
        ).read_text()
    )
    env["version"].manifest = manifest
    env["version"].save()
    profile = SimpleNamespace(max_band_pixels=2_000_000)
    scope = ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    with (
        project_scope(scope),
        patch("apps.compute.model_runtime.configured", return_value=profile),
    ):
        inputs = {}
        for key, month in [("march", 3), ("august", 8), ("december", 12)]:
            source = raster_source_path(key + ".tif")
            source.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(
                source,
                "w",
                driver="GTiff",
                width=32,
                height=32,
                count=16,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(120, 32, 0.001, 0.001),
            ) as dst:
                dst.write(np.full((16, 32, 32), month, dtype="float32"))
            resource = DataResource.objects.create(
                name=key,
                code=key,
                data_type="raster",
                storage_path=key + ".tif",
                size_bytes=11000000000,
            )
            RasterDataset.objects.create(
                name=key,
                code=key,
                data_resource=resource,
                source_relative_path=key + ".tif",
                status="ready",
                band_count=16,
            )
            ResourceObservationMetadata.objects.create(
                resource=resource,
                starts_at=date(2026, month, 1),
                ends_at=date(2026, month, 1),
                precision="day",
            )
            inputs[key] = resource.pk
        request = {
            "name": "全域流式",
            "versionId": env["version"].pk,
            "idempotencyKey": uuid4().hex,
            "inputs": inputs,
            "parameters": {},
        }
        validated = validate_submission(env["owner"], request)
        assert validated["parameters"] == {
            "west": 120,
            "south": 31.968,
            "east": 120.032,
            "north": 32,
        }
        metadata = validated["resources"][0][2]
        assert metadata["streamingRaster"] and metadata["rasterWindow"] == [
            0,
            0,
            32,
            32,
        ]
        task = ComputeTask.objects.create(
            owner=env["owner"],
            version=env["version"],
            parameters=validated["parameters"],
            status="queued",
            idempotency_key=uuid4().hex,
            request_hash="b" * 64,
        )
        resource = DataResource.objects.get(pk=inputs["march"])
        record = ComputeInput.objects.create(
            task=task,
            key="march",
            resource=resource,
            snapshot={**metadata, "updatedAt": resource.updated_at.isoformat()},
        )
        target = tmp_path / "frozen"
        target.mkdir()
        first = freeze_input(record, target)
        from apps.compute.raster_windows import streaming_output_grid

        output_grid = streaming_output_grid(task, manifest)
        assert output_grid["size"] == [32, 32] and output_grid["bands"] == 16
        assert (
            streaming_output_grid(task, {**manifest, "runtime": "python-geospatial-v1"})
            is None
        )
        # The temporary materialization directory has gone; absolute VRT sources remain valid.
        with rasterio.open(target / "march.tif") as src:
            assert src.driver == "VRT" and src.count == 16
            np.testing.assert_array_equal(src.read(1), np.full((32, 32), 3))
        again = tmp_path / "warm"
        again.mkdir()
        assert freeze_input(record, again)["preparation"]["reused"]
        with rasterio.open(raster_source_path("march.tif"), "r+") as dst:
            dst.write(np.full((32, 32), 42, dtype="float32"), 1)
        changed = tmp_path / "changed"
        changed.mkdir()
        with pytest.raises(ComputeError, match="变化"):
            freeze_input(record, changed)
        # Access is checked again even when a frozen input version already exists.
        DataResource.objects.filter(pk=resource.pk).update(
            owner_only=True, maintainer=env["outsider"]
        )
        denied = tmp_path / "denied"
        denied.mkdir()
        with pytest.raises(ComputeError):
            freeze_input(record, denied)
        DataResource.objects.filter(pk=resource.pk).update(owner_only=False)
        ResourceObservationMetadata.objects.filter(
            resource_id=inputs["december"]
        ).update(starts_at=date(2027, 12, 1))
        with pytest.raises(ComputeError, match="同一观测年"):
            validate_submission(env["owner"], request)
        ResourceObservationMetadata.objects.filter(
            resource_id=inputs["december"]
        ).update(starts_at=date(2026, 11, 1))
        with pytest.raises(ComputeError, match="月份"):
            validate_submission(env["owner"], request)


def test_large_output_is_allowed_only_on_frozen_native_input_grid(
    setup_compute, tmp_path
):
    from apps.compute.data import inspect_output
    from apps.compute.packages import ComputeError
    from rasterio.windows import Window

    path = tmp_path / "huge-classification.tif"
    transform = from_origin(120, 32, 0.0001, 0.0001)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=10001,
        height=10001,
        count=1,
        dtype="uint8",
        nodata=255,
        crs="EPSG:4326",
        transform=transform,
        tiled=True,
        SPARSE_OK="YES",
        compress="deflate",
    ) as output:
        output.write(np.ones((16, 16), dtype="uint8"), 1, window=Window(0, 0, 16, 16))
    grid = {
        "size": [10001, 10001],
        "bands": 16,
        "crs": "EPSG:4326",
        "geoTransform": list(transform.to_gdal()),
    }
    with pytest.raises(ComputeError, match="1亿"):
        inspect_output(path, "raster")
    value = inspect_output(path, "raster", raster_grid=grid)
    assert value["width"] == 10001 and value["height"] == 10001 and value["bands"] == 1
    with pytest.raises(ComputeError, match="冻结"):
        inspect_output(path, "raster", raster_grid={**grid, "size": [10000, 10001]})
    with pytest.raises(ComputeError, match="冻结"):
        inspect_output(path, "raster", raster_grid={**grid, "crs": "EPSG:3857"})
