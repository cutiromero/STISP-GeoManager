"""Describe the real compute input separately from its map display cache."""
# ruff: noqa: F811 - pytest fixtures are imported by name.

from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied

from apps.agent.models import AgentRun
from apps.agent.tools import execute
from apps.catalog.models import DataResource
from apps.compute.data import candidate
from apps.core.storage import raster_source_path
from apps.raster.models import RasterDataset
from tests.integration.test_agent_compute_intent import env as raster_env  # noqa: F401
from tests.integration.test_compute import setup_compute  # noqa: F401


def run(env):
    return AgentRun.objects.create(
        conversation=env["conversation"],
        owner=env["owner"],
        model="mock",
        prompt="读取影像规格",
        resource_ids=[env["raster"].pk],
        status="running",
        idempotency_key="source-metadata",
    )


def display_cache(env):
    resource = env["raster"]
    resource.coordinate_system = "EPSG:3857"
    resource.save(update_fields=["coordinate_system"])
    RasterDataset.objects.filter(data_resource=resource).update(
        processed_gdalinfo={
            "size": [259, 260],
            "driverShortName": "GTiff",
            "stac": {"proj:epsg": 3857},
            "bands": [{"band": i, "type": "Byte"} for i in range(1, 9)],
        }
    )


def test_source_metadata_is_not_map_display_metadata(raster_env):
    env = raster_env
    display_cache(env)
    result, _ = execute(run(env), "describe_resource", {"resourceId": env["raster"].pk})
    assert result["mapDisplayMetadata"]["size"] == [259, 260]
    assert result["mapDisplayMetadata"]["coordinateSystem"] == 3857
    assert result["rasterMetadata"]["size"] == [4, 4]
    assert result["rasterMetadata"]["coordinateSystem"] == "EPSG:32645"
    assert result["rasterMetadata"]["source"] == "actual_compute_input_file"
    assert result["computeInput"]["available"] is True
    assert result["computeInput"]["bands"] == 8
    assert result["crs"] == "EPSG:32645"
    band = result["rasterMetadata"]["bands"][0]
    assert band["type"] == "uint8" and band["scale"] == 1.0
    assert "未知" in result["rasterMetadata"]["calibrationNote"]
    assert "extent" not in result


def test_candidate_default_contract_remains_compact(raster_env):
    item = candidate(raster_env["raster"])
    assert item["bands"] == 8 and item["crs"] == "EPSG:32645"
    assert "rasterMetadata" not in item


def test_unreadable_source_remains_unknown_with_display_available(raster_env):
    env = raster_env
    display_cache(env)
    raster_source_path("intent.tif").unlink()
    result, _ = execute(run(env), "describe_resource", {"resourceId": env["raster"].pk})
    assert result["computeInput"]["available"] is False
    assert result["crs"] == "" and "rasterMetadata" not in result
    assert result["mapDisplayMetadata"]["size"] == [259, 260]


def test_unauthorized_resource_does_not_open_source(raster_env):
    env = raster_env
    item = run(env)
    DataResource._base_manager.filter(pk=env["raster"].pk).update(
        project_tag=env["other_project"]
    )
    with (
        patch("rasterio.open") as reader,
        pytest.raises(PermissionDenied),
    ):
        execute(item, "describe_resource", {"resourceId": env["raster"].pk})
    reader.assert_not_called()
