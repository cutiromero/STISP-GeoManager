import json
from dataclasses import replace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.catalog.models import DataResource, MapLayer, VectorDataset
from apps.projects.models import Project, ProjectMembership
from apps.raster.models import RasterProcessingJob

pytestmark = pytest.mark.django_db
UPLOADS = [
    "/api/catalog/import/commit/",
    "/api/catalog/vector-import/commit/",
    "/api/raster/import/",
    "/api/catalog/results/",
]


@pytest.fixture
def actors(settings, tmp_path):
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=tmp_path / "app",
        research_data_root=tmp_path / "research",
    )
    users = get_user_model()
    admin = users.objects.create_superuser("upload-admin")
    member = users.objects.create_user("upload-member")
    outsider = users.objects.create_user("upload-outsider")
    for user in (member, outsider):
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=[
                    "add_dataresource",
                    "view_dataresource",
                    "browse_data",
                    "query_data",
                    "manage_raster_dataset",
                    "view_resultartifact",
                    "add_resultartifact",
                    "publish_resultartifact",
                    "download_resultartifact",
                ]
            )
        )
    a = Project.objects.create(name="上传项目甲", code="upload-a")
    b = Project.objects.create(name="上传项目乙", code="upload-b")
    ProjectMembership.objects.create(user=member, project=a)
    ProjectMembership.objects.create(user=member, project=b)
    return admin, member, outsider, a, b


@pytest.mark.parametrize("url", UPLOADS)
@pytest.mark.parametrize("header", [None, "", "all", "0", "bad"])
def test_upload_requires_explicit_single_project(client, actors, url, header):
    client.force_login(actors[1])
    headers = {} if header is None else {"HTTP_X_PROJECT_ID": header}
    response = client.post(url, {}, **headers)
    assert response.status_code == 400
    assert "detail" in response.json()
    assert DataResource.objects.count() == 0


@pytest.mark.parametrize("url", UPLOADS)
def test_forged_and_revoked_upload_destinations_fail_before_file_processing(
    client, actors, url
):
    _, member, outsider, a, _ = actors
    client.force_login(outsider)
    assert client.post(url, {}, HTTP_X_PROJECT_ID=str(a.id)).status_code == 404
    client.force_login(member)
    ProjectMembership.objects.filter(user=member, project=a).delete()
    assert client.post(url, {}, HTTP_X_PROJECT_ID=str(a.id)).status_code == 404
    assert DataResource.objects.count() == 0


def table_body(mode="table", name="同名调查数据"):
    return {
        "file": SimpleUploadedFile(
            "survey.csv", b"name,lon,lat\nA,87.600001,43.800001\n"
        ),
        "payload": json.dumps(
            {
                "name": name,
                "domainType": "other",
                "importMode": mode,
                "categoryCode": "spatial" if mode == "geographic" else "non_spatial",
                "tableName": "upload_survey",
                "longitudeColumn": "lon",
                "latitudeColumn": "lat",
                "fieldMetadata": {},
            }
        ),
    }


@pytest.mark.parametrize("mode", ["table", "geographic"])
def test_import_selected_project_drives_storage_inventory_and_access(
    client, actors, settings, mode
):
    admin, member, outsider, a, b = actors
    client.force_login(member)
    imported = []
    for project_id in (1, a.id, b.id):
        header = {"HTTP_X_PROJECT_ID": str(project_id)}
        preview = client.post(
            "/api/catalog/import/preview/", table_body(mode), **header
        )
        assert preview.status_code == 200, preview.content
        # Identical names in different projects do not conflict.
        response = client.post(UPLOADS[0], table_body(mode), **header)
        assert response.status_code == 201, response.content
        resource = DataResource.objects.get(pk=response.json()["resourceId"])
        assert resource.project_tag_id == project_id
        imported.append(resource)
        inventory = client.get("/api/admin/data/resources/", **header)
        assert inventory.status_code == 200, inventory.content
        assert [(r["id"], r["projectTagId"]) for r in inventory.json()["items"]] == [
            (resource.id, project_id)
        ]
        if mode == "geographic":
            assert resource.data_type == "vector"
            prefix = () if project_id == 1 else ("projects", str(project_id))
            assert (
                settings.PROJECT_CONFIG.research_data_root.joinpath(
                    *prefix, "vector", "vector.gpkg"
                )
            ).is_file()
    client.force_login(outsider)
    visible = client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID="1").json()[
        "items"
    ]
    assert [r["id"] for r in visible] == [imported[0].id]
    assert (
        client.get(
            f"/api/catalog/resources/{imported[1].id}/profile/",
            HTTP_X_PROJECT_ID=str(a.id),
        ).status_code
        == 404
    )
    assert (
        client.post(
            UPLOADS[0], table_body(mode, "无权数据"), HTTP_X_PROJECT_ID=str(a.id)
        ).status_code
        == 404
    )
    client.force_login(admin)
    assert (
        client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID="all").status_code
        == 400
    )
    for project_id in (1, a.id, b.id):
        inventory = client.get(
            "/api/admin/data/resources/", HTTP_X_PROJECT_ID=str(project_id)
        )
        assert inventory.status_code == 200, inventory.content
        assert {r["projectTagId"] for r in inventory.json()["items"]} == {project_id}


def test_vector_upload_and_linked_dataset_share_selected_tag(client, actors, settings):
    _, member, _, a, _ = actors
    client.force_login(member)
    geometry = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "A"},
                "geometry": {"type": "Point", "coordinates": [87.6, 43.8]},
            }
        ],
    }
    response = client.post(
        UPLOADS[1],
        {
            "file": SimpleUploadedFile("sample.geojson", json.dumps(geometry).encode()),
            "payload": json.dumps(
                {
                    "name": "标签矢量",
                    "tableName": "tag_vector",
                    "sourceLayerName": "sample",
                    "domainType": "vector",
                    "categoryCode": "spatial",
                }
            ),
        },
        HTTP_X_PROJECT_ID=str(a.id),
    )
    assert response.status_code == 201, response.content
    resource = DataResource.objects.get(pk=response.json()["resourceId"])
    assert resource.project_tag_id == a.id
    assert VectorDataset.objects.get(resource=resource).project_tag_id == a.id
    assert MapLayer.objects.get(data_resource=resource).project_tag_id == a.id
    assert (
        settings.PROJECT_CONFIG.research_data_root
        / "projects"
        / str(a.id)
        / "vector/vector.gpkg"
    ).is_file()


def test_raster_upload_persists_project_for_async_job_and_upload_path(
    client, actors, monkeypatch
):
    _, member, outsider, a, _ = actors
    client.force_login(member)
    monkeypatch.setattr(
        "apps.raster.services.importer.gdalinfo_json",
        lambda *args, **kwargs: {"size": [4, 4]},
    )
    queued = []
    monkeypatch.setattr(
        "apps.raster.services.jobs._HEAVY_TASK_EXECUTOR.submit",
        lambda runner: queued.append(runner) or True,
    )
    response = client.post(
        UPLOADS[2],
        {"file": SimpleUploadedFile("tagged.tif", b"raster fixture")},
        HTTP_X_PROJECT_ID=str(a.id),
    )
    assert response.status_code == 202, response.content
    job = RasterProcessingJob.objects.get(pk=response.json()["id"])
    assert job.project_tag_id == a.id
    assert len(queued) == 1
    from django.conf import settings

    uploaded = list(
        (
            settings.PROJECT_CONFIG.research_data_root
            / "projects"
            / str(a.id)
            / "raster/original/uploaded"
        ).rglob("*.tif")
    )
    assert len(uploaded) == 1
    assert uploaded[0].read_bytes() == b"raster fixture"
    client.force_login(outsider)
    assert (
        client.get(
            f"/api/raster/jobs/{job.id}/", HTTP_X_PROJECT_ID=str(a.id)
        ).status_code
        == 404
    )


def test_superadmin_can_upload_to_any_tag_and_result_file_obeys_membership(
    client, actors
):
    admin, _, outsider, a, _ = actors
    client.force_login(admin)
    response = client.post(
        UPLOADS[3],
        {
            "file": SimpleUploadedFile("result.csv", b"value\n1\n"),
            "payload": json.dumps(
                {
                    "name": "项目成果",
                    "sourceType": "direct_import",
                    "resultType": "table",
                    "categoryCode": "non_spatial",
                    "accessGroupIds": [],
                }
            ),
        },
        HTTP_X_PROJECT_ID=str(a.id),
    )
    assert response.status_code == 201, response.content
    artifact = response.json()
    assert artifact["projectTagId"] == a.id
    file_url = f"/api/catalog/results/{artifact['id']}/file/?variant=artifact"
    client.force_login(outsider)
    assert client.get(file_url, HTTP_X_PROJECT_ID=str(a.id)).status_code == 404
    ProjectMembership.objects.create(user=outsider, project=a)
    downloaded = client.get(file_url, HTTP_X_PROJECT_ID=str(a.id))
    assert downloaded.status_code == 200
    assert b"value" in b"".join(downloaded.streaming_content)
