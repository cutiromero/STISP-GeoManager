"""Computed provenance stays separate from uploaded data and physical type."""

import importlib
import json

import pytest
from django.apps import apps as django_apps
from django.db import connection

from apps.catalog.importer import ImportDataError, _optional_data_category
from apps.catalog.models import DataResource, DictionaryItem
from apps.catalog.taxonomy import assign_resource_category, TaxonomyError
from apps.compute.data import inspect_output, import_output
from apps.compute.models import ComputeImport, ComputeOutput
from apps.compute.packages import checksum
from apps.compute.worker import process_import, task_scope
from apps.core.storage import app_path
from apps.projects.context import ProjectScope, project_scope
from . import test_compute as shared
from .test_compute_recovery import make_output

setup_compute = shared.setup_compute
pytestmark = pytest.mark.django_db


def make_result(env, kind):
    extension = {
        "vector": "gpkg",
        "raster": "tif",
        "table": "csv",
        "image": "png",
        "report": "pdf",
    }[kind]
    task, path = make_output(env, kind, "result." + extension)
    if kind == "vector":
        import geopandas as gpd
        from shapely.geometry import Point

        gpd.GeoDataFrame({"value": [1]}, geometry=[Point(80, 40)], crs=4326).to_file(
            path, layer="result", driver="GPKG"
        )
    elif kind == "raster":
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin

        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=2,
            height=2,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(80, 40, 0.01, 0.01),
        ) as dst:
            dst.write(np.array([[1, 2], [3, 4]], dtype="float32"), 1)
    elif kind == "image":
        from PIL import Image

        Image.new("RGB", (2, 2), "blue").save(path)
    elif kind == "report":
        from pypdf import PdfWriter

        report = PdfWriter()
        report.add_blank_page(width=200, height=200)
        with path.open("wb") as stream:
            report.write(stream)
    else:
        path.write_text("value\n1\n", encoding="utf-8")
    output = ComputeOutput.objects.create(
        task=task,
        key="result",
        label="结果",
        kind=kind,
        file_name=path.name,
        path=path.relative_to(app_path()).as_posix(),
        size_bytes=path.stat().st_size,
        checksum=checksum(path),
        metadata=inspect_output(path, kind),
    )
    return task, output


@pytest.mark.parametrize("kind", ["raster", "vector", "table", "image", "report"])
def test_all_manual_result_kinds_use_compute_category(setup_compute, kind):
    env = setup_compute
    task, output = make_result(env, kind)
    record = ComputeImport.objects.create(
        output=output, requested_by=env["owner"], name="计算输出"
    )
    with task_scope(task):
        process_import(record)
        record.refresh_from_db()
        assert record.status == "ready", record.error
        resource = record.resource
        assert resource.is_compute_result
        assert resource.category.code == "compute_results"
        assert resource.spatial_class == (
            "spatial" if kind in {"raster", "vector"} else "non_spatial"
        )
        before = (
            resource.project_tag_id,
            resource.storage_path,
            resource.coordinate_system,
        )
        resource.description = "用户补充结果说明"
        resource.save(update_fields=["description"])
        resource.refresh_from_db()
        assert resource.category.code == "compute_results"
        assert (
            resource.project_tag_id,
            resource.storage_path,
            resource.coordinate_system,
        ) == before
        initial = DataResource.objects.count()
        assert import_output(record).id == resource.id
        assert DataResource.objects.count() == initial
    response = env["client"].get(
        "/api/catalog/resources/",
        {"categoryCode": "compute_results"},
        HTTP_X_PROJECT_ID=str(task.project_tag_id),
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [resource.id]
    assert response.json()["items"][0]["categoryPath"][0]["code"] == "compute_results"
    assert not env["resource"].is_compute_result
    assert env["resource"].category.code == "non_spatial"


def test_result_filter_preserves_owner_only_and_project_access(setup_compute):
    env = setup_compute
    task, output = make_result(env, "table")
    with task_scope(task):
        record = ComputeImport.objects.create(
            output=output, requested_by=env["owner"], name="结果"
        )
        process_import(record)
        record.refresh_from_db()
        resource = record.resource
        resource.owner_only = True
        resource.save(update_fields=["owner_only"])
        private = DataResource.objects.create(
            name="他人私有结果",
            code="other-result",
            data_type="table",
            is_compute_result=True,
            owner_only=True,
            maintainer=env["outsider"],
        )
    response = env["client"].get(
        "/api/catalog/resources/",
        {"categoryCode": "compute_results"},
        HTTP_X_PROJECT_ID=str(task.project_tag_id),
    )
    assert [item["id"] for item in response.json()["items"]] == [resource.id]
    other = env["client"].get(
        "/api/catalog/resources/",
        {"categoryCode": "compute_results"},
        HTTP_X_PROJECT_ID="1",
    )
    assert other.json()["items"] == []
    assert private.id != resource.id


def test_upload_cannot_claim_result_category_and_admin_cannot_move_result(
    setup_compute,
):
    env = setup_compute
    with pytest.raises(ImportDataError, match="计算结果"):
        _optional_data_category("compute_results")
    env["client"].force_login(env["admin"])
    task, output = make_result(env, "table")
    with task_scope(task):
        record = ComputeImport.objects.create(
            output=output, requested_by=env["owner"], name="结果"
        )
        process_import(record)
        record.refresh_from_db()
        resource = record.resource
        with pytest.raises(TaxonomyError):
            assign_resource_category(resource, "non_spatial")
    endpoint = f"/api/admin/data/resources/{resource.id}/"
    response = env["client"].post(
        endpoint,
        json.dumps({"action": "updateClassification", "categoryCode": "non_spatial"}),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(task.project_tag_id),
    )
    assert response.status_code == 400
    response = env["client"].post(
        endpoint,
        json.dumps(
            {
                "action": "update",
                "name": "补充后的结果名称",
                "categoryCode": "compute_results",
            }
        ),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(task.project_tag_id),
    )
    assert response.status_code == 200, response.content
    resource.refresh_from_db()
    assert resource.name == "补充后的结果名称"
    assert resource.category.code == "compute_results"


def test_migration_uses_actual_import_links_and_preserves_all_other_fields(
    setup_compute,
):
    env = setup_compute
    task, output = make_result(env, "table")
    with task_scope(task):
        resource = DataResource.objects.create(
            name="已入库结果",
            code="linked",
            data_type="table",
            maintainer=env["owner"],
            owner_only=True,
            storage_path="preserve.csv",
            description="人工补充",
        )
        ComputeImport.objects.create(
            output=output,
            requested_by=env["owner"],
            name=resource.name,
            resource=resource,
            status="ready",
        )
        impostor = DataResource.objects.create(
            name="NDVI计算结果",
            code="upload-named-result",
            data_type="table",
            source="compute-output:invented",
        )
        unrelated = DataResource.objects.create(
            name="未入库数据", code="untouched", data_type="table"
        )
        before = DataResource.objects.values().get(pk=resource.pk)
        mismatch_output = ComputeOutput.objects.create(
            task=task,
            key="mismatch",
            label="错项目关联",
            kind="table",
            file_name="mismatch.csv",
            path="unused.csv",
            size_bytes=0,
            checksum="a" * 64,
        )
    with project_scope(
        ProjectScope(
            (env["other_project"].id,), env["other_project"].id, env["admin"].id, True
        )
    ):
        wrong_project = DataResource.objects.create(
            name="另一项目原始数据", code="mismatched-link", data_type="table"
        )
        ComputeImport.objects.create(
            output=mismatch_output,
            requested_by=env["owner"],
            name="错误历史关联",
            resource=wrong_project,
            status="ready",
        )
    migration = importlib.import_module(
        "apps.catalog.migrations.0019_compute_result_category"
    )
    migration.classify_compute_results(django_apps, None)
    with task_scope(task):
        after = DataResource.objects.values().get(pk=resource.pk)
        assert after["is_compute_result"]
        assert (
            after["category_id"]
            == DictionaryItem.objects.get(
                code="compute_results", dict_type="data_category"
            ).id
        )
        for field in before.keys() - {"is_compute_result", "category_id"}:
            assert after[field] == before[field], field
        for item in (impostor, unrelated, env["resource"]):
            item.refresh_from_db()
            assert not item.is_compute_result
            assert item.category.code == "non_spatial"
        migration.classify_compute_results(django_apps, None)
        assert DataResource.objects.values().get(pk=resource.pk) == after
    wrong_project.refresh_from_db()
    assert not wrong_project.is_compute_result
    assert wrong_project.category.code == "non_spatial"


def test_recovered_import_restores_result_category_without_reimporting(setup_compute):
    env = setup_compute
    task, output = make_result(env, "table")
    with task_scope(task):
        record = ComputeImport.objects.create(
            output=output, requested_by=env["owner"], name="恢复结果"
        )
        process_import(record)
        record.refresh_from_db()
        resource = record.resource
        resource.is_compute_result = False
        resource.save(update_fields=["is_compute_result"])
        record.status = "queued"
        record.resource = None
        record.save(update_fields=["resource", "status"])
        before = DataResource.objects.count()
        process_import(record)
        record.refresh_from_db()
        assert record.status == "ready", record.error
        assert record.resource_id == resource.id
        assert record.resource.is_compute_result
        assert record.resource.category.code == "compute_results"
        assert DataResource.objects.count() == before


def test_old_application_insert_uses_database_default(setup_compute):
    env = setup_compute
    with task_scope(make_result(env, "table")[0]):
        original = DataResource.objects.values().get(pk=env["resource"].pk)
        original.pop("id")
        original.pop("is_compute_result")
        original.update(code="old-application-upload", name="旧版本上传")
        columns = list(original)
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO catalog_dataresource ({', '.join(connection.ops.quote_name(col) for col in columns)}) VALUES ({', '.join('%s' for _ in columns)})",
                [
                    json.dumps(value) if isinstance(value, dict) else value
                    for value in original.values()
                ],
            )
        uploaded = DataResource.objects.get(code="old-application-upload")
        assert not uploaded.is_compute_result
        assert uploaded.category.code == "non_spatial"
