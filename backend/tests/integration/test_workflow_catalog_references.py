import json
import uuid

import pytest

from apps.agent.models import AgentWorkflow, WorkflowUpload
from apps.agent.workflow_uploads import catalog_profile, store_upload
from apps.catalog.models import DataResource
from tests.integration.test_geology_generic_workflow import geojson

pytestmark = pytest.mark.django_db
pytest_plugins = ["tests.integration.test_geology_generic_workflow"]


def catalog_entry(env):
    env["project"].code = "02"
    env["project"].save(update_fields=["code"])
    attachment = store_upload(
        env["owner"], env["project"].id, geojson(), uuid.uuid4().hex
    )
    resource = attachment.resource
    resource.source = "catalog-demo"
    resource.owner_only = False
    resource.save()
    attachment.delete()
    return resource


def reference(env, resource_ids, batch=None):
    return env["client"].post(
        "/api/agent/workflow-uploads/references/",
        json.dumps({"batchId": batch or env["batch"], "resourceIds": resource_ids}),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


def test_references_are_non_owning_idempotent_and_reusable(generic):
    resource = catalog_entry(generic)
    original = DataResource.objects.filter(pk=resource.pk).values().get()
    first = reference(generic, [resource.id])
    assert first.status_code == 200, first.content
    item = first.json()["items"][0]
    assert item["source"] == "catalog" and item["profile"]["featureCount"] == 4
    assert reference(generic, [resource.id]).json()["items"][0]["id"] == item["id"]
    second = reference(generic, [resource.id], uuid.uuid4().hex)
    assert second.status_code == 200 and second.json()["items"][0]["id"] != item["id"]
    entries = list(WorkflowUpload.objects.filter(resource=resource))
    assert len(entries) == 2
    for index, entry in enumerate(entries):
        workflow = AgentWorkflow.objects.create(
            owner=generic["owner"],
            model="mock",
            goal="目录引用测试",
            workflow_type="geology_generic",
            idempotency_key=f"reference-{index}",
            status="succeeded",
        )
        entry.workflow = workflow
        entry.save(update_fields=["workflow"])
    third = reference(generic, [resource.id], uuid.uuid4().hex).json()["items"][0]
    removed = generic["client"].delete(
        f"/api/agent/workflow-uploads/{third['id']}/",
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert removed.status_code == 204
    assert DataResource.objects.filter(pk=resource.pk).values().get() == original
    assert WorkflowUpload.objects.filter(resource=resource).count() == 2
    listing = generic["client"].get(
        "/api/catalog/resources/", HTTP_X_PROJECT_ID=str(generic["project"].id)
    )
    assert resource.id in [row["id"] for row in listing.json()["items"]]


def test_reference_search_and_permissions_are_project_scoped(generic):
    allowed = catalog_entry(generic)
    hidden = catalog_entry(generic)
    hidden.owner_only, hidden.maintainer = True, generic["outsider"]
    hidden.save()
    cross = catalog_entry(generic)
    DataResource._base_manager.filter(pk=cross.pk).update(
        project_tag_id=generic["other_project"].id
    )
    response = generic["client"].get(
        "/api/agent/workflow-uploads/references/",
        {"q": allowed.name},
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert response.status_code == 200, response.content
    assert [row["id"] for row in response.json()["items"]] == [allowed.id]
    for identity in [hidden.id, cross.id, 99999999]:
        denied = reference(generic, [allowed.id, identity])
        assert denied.status_code == 404, denied.content
        assert not WorkflowUpload.objects.filter(batch_id=generic["batch"]).exists()


def test_references_mix_with_uploads_and_reauthorize_before_roles(generic):
    resource = catalog_entry(generic)
    assert reference(generic, [resource.id]).status_code == 200
    uploaded = store_upload(
        generic["owner"], generic["project"].id, geojson(), generic["batch"]
    )
    items = (
        generic["client"]
        .get(
            "/api/agent/workflow-uploads/",
            {"batchId": generic["batch"]},
            HTTP_X_PROJECT_ID=str(generic["project"].id),
        )
        .json()["items"]
    )
    assert {item["source"] for item in items} == {"catalog", "upload"}
    assert catalog_profile(resource)["crs"]
    resource.owner_only, resource.maintainer = True, generic["outsider"]
    resource.save()
    items = (
        generic["client"]
        .get(
            "/api/agent/workflow-uploads/",
            {"batchId": generic["batch"]},
            HTTP_X_PROJECT_ID=str(generic["project"].id),
        )
        .json()["items"]
    )
    assert [item["resourceId"] for item in items] == [uploaded.resource_id]


@pytest.mark.parametrize("ids", [[], [True], [1, 1], ["1"], list(range(1, 14))])
def test_reference_validation(generic, ids):
    catalog_entry(generic)
    response = reference(generic, ids)
    assert response.status_code == 400, response.content


def test_missing_catalog_layer_returns_structured_error_and_rolls_back_batch(generic):
    good = catalog_entry(generic)
    broken = catalog_entry(generic)
    broken.storage_path = "missing-layer"
    broken.save()
    response = reference(generic, [good.id, broken.id])
    assert response.status_code == 400, response.content
    assert "资料画像" in response.json()["detail"]
    assert not WorkflowUpload.objects.filter(batch_id=generic["batch"]).exists()


def test_table_profile_reads_catalog_sqlite_not_upload_path(generic):
    resource = generic["resource"]
    profile = catalog_profile(resource)
    assert profile["kind"] == "table" and profile["featureCount"] == 3
    assert {field["name"] for field in profile["fields"]} >= {"region", "value"}


def test_raster_profile_uses_real_compute_source_not_display_alpha(generic):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    from apps.core.storage import raster_source_path, raster_processed_path
    from apps.raster.models import RasterDataset

    resource = catalog_entry(generic)
    resource.data_type = "raster"
    resource.save()
    for path, bands, epsg in [
        (raster_source_path("reference.tif"), 1, 32646),
        (raster_processed_path("display.tif"), 2, 3857),
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=2,
            height=2,
            count=bands,
            dtype="uint8",
            crs=f"EPSG:{epsg}",
            transform=from_origin(300000, 4000000, 30, 30),
        ) as output:
            output.write(np.ones((bands, 2, 2), dtype="uint8"))
    RasterDataset.objects.create(
        data_resource=resource,
        name="蚀变",
        code="reference",
        source_relative_path="reference.tif",
        processed_relative_path="display.tif",
        status="ready",
    )
    response = reference(generic, [resource.id])
    assert response.status_code == 200, response.content
    profile = response.json()["items"][0]["profile"]
    assert profile["bandCount"] == 1 and profile["crs"] == "EPSG:32646"
