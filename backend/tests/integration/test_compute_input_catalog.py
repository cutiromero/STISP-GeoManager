"""Selectors read schemas cheaply; actual submission keeps file validation."""

# ruff: noqa: F811

import io
import sqlite3
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from django.core.files.uploadedfile import UploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rasterio.transform import from_origin
from shapely.geometry import Point

from apps.catalog.models import DataResource
from apps.compute.data import candidate, list_candidate
from apps.compute.models import AlgorithmResource, ComputeTask
from apps.compute.templates import build_package
from apps.compute.views import store_version
from apps.core.storage import (
    raster_source_path,
    table_data_path,
    vector_geopackage_path,
)
from apps.projects.context import ProjectScope, project_scope
from apps.raster.models import RasterDataset
from tests.integration.test_compute import post, setup_compute  # noqa: F401


def scope(env, project=None):
    project_id = project or env["project"].id
    return project_scope(ProjectScope((project_id,), project_id, env["owner"].id))


def raster(env, index=0):
    path = raster_source_path(f"input-{index}.tif")
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=2,
        dtype="uint8",
        crs="EPSG:32645",
        transform=from_origin(615864, 4444548, 1, 1),
    ) as target:
        target.write(np.ones((2, 4, 4), dtype="uint8"))
    resource = DataResource.objects.create(
        name=f"影像{index}",
        code=f"image-{index}",
        data_type="raster",
        coordinate_system="EPSG:3857",
        file_format="COG",
        maintainer=env["owner"],
    )
    dataset = RasterDataset.objects.create(
        name=resource.name,
        code=resource.code,
        status="ready",
        data_resource=resource,
        source_relative_path=path.name,
        band_count=3,
        source_gdalinfo={
            "bands": [{"band": 1}, {"band": 2}],
            "coordinateSystem": {"wkt": rasterio.crs.CRS.from_epsg(32645).to_wkt()},
        },
    )
    return resource, dataset, path


def response(env, query=""):
    return env["client"].get(
        "/api/compute/inputs/?" + query,
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


@pytest.mark.parametrize(
    "suffix,encoding", [("csv", "utf-8-sig"), ("tsv", "gb18030"), ("xlsx", None)]
)
def test_file_table_selector_reads_only_headers(setup_compute, suffix, encoding):
    env = setup_compute
    with scope(env):
        path = table_data_path(f"input.{suffix}")
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame({"区域": ["一", "二"], "value": [1, 2]})
        if suffix == "xlsx":
            frame.to_excel(path, index=False)
        else:
            frame.to_csv(
                path,
                index=False,
                sep="\t" if suffix == "tsv" else ",",
                encoding=encoding,
            )
        resource = DataResource.objects.create(
            name="文件表格",
            code="file-table",
            data_type="table",
            file_format=suffix.upper(),
            storage_path=f"table/input.{suffix}",
            maintainer=env["owner"],
        )
        expected = candidate(resource)
    reader = "read_excel" if suffix == "xlsx" else "read_csv"
    with (
        patch("pandas." + reader, wraps=getattr(pd, reader)) as read,
        patch(
            "apps.catalog.nongeo._resource_dataframe",
            side_effect=AssertionError("full dataframe read"),
        ),
    ):
        result = response(env, f"resourceId={resource.id}")
    assert result.status_code == 200, result.content
    assert result.json()["items"] == [expected]
    assert read.call_count >= 1
    assert all(call.kwargs["nrows"] == 0 for call in read.call_args_list)


def test_sqlite_selector_reads_schema_without_counting_or_loading_rows(setup_compute):
    env = setup_compute
    statements = []
    connect = sqlite3.connect

    def traced(*args, **kwargs):
        database = connect(*args, **kwargs)
        database.set_trace_callback(statements.append)
        return database

    with (
        scope(env),
        patch("sqlite3.connect", side_effect=traced),
        patch(
            "apps.catalog.nongeo._resource_dataframe",
            side_effect=AssertionError("full table read"),
        ),
    ):
        result = list_candidate(env["resource"])
    assert result["fields"] == ["region", "value"]
    assert len(statements) == 1
    assert statements[0].startswith("PRAGMA table_info")


def test_vector_selector_matches_actual_schema_without_gdal_or_feature_scan(
    setup_compute,
):
    env = setup_compute
    with scope(env):
        path = vector_geopackage_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        gpd.GeoDataFrame(
            {"class": [1], "label": ["地质图"]}, geometry=[Point(80, 40)], crs=4326
        ).to_file(path, layer="input_polygon", driver="GPKG")
        resource = DataResource.objects.create(
            name="矢量",
            code="input-vector",
            data_type="vector",
            file_format="GPKG",
            storage_path="input_polygon",
            coordinate_system="EPSG:4326",
            maintainer=env["owner"],
        )
        expected = candidate(resource)
        with (
            patch("pyogrio.read_info", side_effect=AssertionError("GDAL dataset open")),
            patch(
                "geopandas.read_file", side_effect=AssertionError("feature data read")
            ),
        ):
            result = list_candidate(resource)
    assert result == expected


def test_raster_selector_uses_original_metadata_and_one_batch_query(setup_compute):
    env = setup_compute
    with scope(env):
        resources = [raster(env, index)[0] for index in range(4)]
        expected = {resource.id: candidate(resource) for resource in resources}
    with (
        CaptureQueriesContext(connection) as captured,
        patch("rasterio.open", side_effect=AssertionError("source raster reopened")),
    ):
        result = response(env, "kind=raster&pageSize=50")
    assert result.status_code == 200, result.content
    assert {item["id"]: item for item in result.json()["items"]} == expected
    raster_queries = [
        query
        for query in captured.captured_queries
        if 'FROM "raster_rasterdataset"' in query["sql"]
    ]
    assert len(raster_queries) == 1
    assert all(
        item["bands"] == 2 and item["crs"] == "EPSG:32645"
        for item in result.json()["items"]
    )


def test_old_raster_without_saved_source_metadata_still_inspects_actual_file(
    setup_compute,
):
    env = setup_compute
    with scope(env):
        resource, dataset, _ = raster(env)
        dataset.source_gdalinfo = {}
        dataset.save(update_fields=["source_gdalinfo"])
        assert list_candidate(resource) == candidate(resource)


def test_private_and_cross_project_sources_are_filtered_before_file_inspection(
    setup_compute,
):
    env = setup_compute
    with scope(env):
        DataResource.objects.create(
            name="其他用户私有影像",
            code="private-image",
            data_type="raster",
            owner_only=True,
            maintainer=env["outsider"],
        )
    with scope(env, env["other_project"].id):
        DataResource.objects.create(
            name="其他项目影像", code="other-image", data_type="raster"
        )
    with patch(
        "apps.compute.data.candidate",
        side_effect=AssertionError("inaccessible file inspection"),
    ):
        result = response(env)
    assert result.status_code == 200, result.content
    assert [item["id"] for item in result.json()["items"]] == [env["resource"].id]
    env["client"].logout()
    assert env["client"].get("/api/compute/inputs/").status_code == 401


def test_missing_source_has_readable_error_and_read_only_sqlite_is_not_created(
    setup_compute,
):
    env = setup_compute
    with scope(env):
        resource, _, path = raster(env)
        path.unlink()
    result = response(env, f"resourceId={resource.id}")
    assert result.status_code == 400
    assert "源文件不存在" in result.json()["detail"]
    with scope(env):
        path = table_data_path("missing.sqlite")
    with patch("apps.compute.data.table_data_path", return_value=path):
        result = response(env, f"resourceId={env['resource'].id}")
    assert result.status_code == 400
    assert "源文件" in result.json()["detail"]
    assert not path.exists()


def test_submission_rechecks_real_bands_after_advisory_metadata_becomes_stale(
    setup_compute,
):
    env = setup_compute
    with scope(env):
        resource, dataset, _ = raster(env)
        dataset.source_gdalinfo = {
            **dataset.source_gdalinfo,
            "bands": [{"band": i} for i in range(1, 9)],
        }
        dataset.save(update_fields=["source_gdalinfo"])
        package, identifier = build_package(4)
        algorithm = AlgorithmResource.objects.create(
            identifier=identifier, name="NDVI", created_by=env["owner"]
        )
        version = store_version(
            algorithm,
            UploadedFile(io.BytesIO(package), name="operator.zip", size=len(package)),
        )
        version.status = "published"
        version.save()
    assert response(env, f"resourceId={resource.id}").json()["items"][0]["bands"] == 8
    result = post(
        env,
        "preflight/",
        {
            "name": "验证实际波段",
            "versionId": version.id,
            "inputs": {"image": resource.id},
            "parameters": {"red": 3, "nir": 8},
            "idempotencyKey": "real-band-preflight",
        },
    )
    assert result.status_code == 400, result.content
    assert (
        "波段" in result.json()["detail"]
        or "不属于选中的数据" in result.json()["detail"]
    )
    assert ComputeTask.objects.count() == 0
