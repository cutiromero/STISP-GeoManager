import io
import pytest
from PIL import Image
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.projects.models import Project, ProjectMembership
from apps.projects.context import ProjectScope, project_scope
from apps.catalog.models import DataResource, MapLayer
from apps.content.models import Article

pytestmark = pytest.mark.django_db


@pytest.fixture
def actors():
    User = get_user_model()
    admin = User.objects.create_superuser("scope-root", password="test-pass")
    alice = User.objects.create_user("scope-alice", password="test-pass")
    bob = User.objects.create_user("scope-bob", password="test-pass")
    p = Project.objects.create(name="A", code="scope-a")
    q = Project.objects.create(name="B", code="scope-b")
    ProjectMembership.objects.create(project=p, user=alice)
    ProjectMembership.objects.create(project=q, user=bob)
    return admin, alice, bob, p, q


def test_default_is_public_and_private_tags_are_hidden(client, actors):
    _, alice, _, p, q = actors
    response = client.get("/api/projects/")
    assert response.status_code == 200
    assert [x["id"] for x in response.json()["items"]] == [1]
    assert (
        client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID=str(p.id)).status_code
        == 404
    )
    client.force_login(alice)
    assert {x["id"] for x in client.get("/api/projects/").json()["items"]} == {1, p.id}
    assert (
        client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID=str(q.id)).status_code
        == 404
    )


def test_scope_filters_all_resource_paths(client, actors):
    admin, alice, _, p, q = actors
    a = DataResource.objects.create(
        name="A数据", code="same", data_type="table", project_tag=p
    )
    b = DataResource.objects.create(
        name="B数据", code="same", data_type="table", project_tag=q
    )
    DataResource.objects.create(name="公共数据", code="same", data_type="table")
    assert [
        i["name"] for i in client.get("/api/catalog/resources/").json()["items"]
    ] == ["公共数据"]
    client.force_login(admin)
    response = client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID=str(p.id))
    assert [i["id"] for i in response.json()["items"]] == [a.pk]
    assert (
        client.get(
            f"/api/catalog/resources/{b.pk}/profile/", HTTP_X_PROJECT_ID=str(p.id)
        ).status_code
        == 404
    )
    assert (
        client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID="all").status_code
        == 400
    )


def test_cross_project_relations_and_write_scope(actors):
    _, alice, _, p, q = actors
    b = DataResource.objects.create(
        name="B", code="b", data_type="vector", project_tag=q
    )
    with project_scope(ProjectScope((p.id,), p.id, alice.id)):
        a = DataResource.objects.create(name="A", code="a", data_type="vector")
        assert a.project_tag_id == p.id
        with pytest.raises(ValidationError):
            MapLayer.objects.create(
                name="bad", code="bad", layer_type="vector", data_resource=b
            )
        with pytest.raises(ValidationError):
            DataResource.objects.filter(pk=a.pk).update(project_tag_id=q.id)


def test_assignments_only_admin_and_revocation(client, actors):
    admin, alice, _, p, q = actors
    alice.user_permissions.add(
        Permission.objects.get(content_type__app_label="core", codename="browse_data")
    )
    client.force_login(alice)
    url = f"/api/projects/assignments/{alice.pk}/"
    assert (
        client.post(
            url,
            {"userId": alice.pk, "projectIds": [q.pk]},
            content_type="application/json",
        ).status_code
        == 403
    )
    client.force_login(admin)
    assert (
        client.post(
            url,
            {"userId": alice.pk, "projectIds": [p.pk, q.pk]},
            content_type="application/json",
        ).status_code
        == 200
    )
    client.force_login(alice)
    assert (
        client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID=str(q.id)).status_code
        == 200
    )
    ProjectMembership.objects.filter(user=alice, project=q).delete()
    assert (
        client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID=str(q.id)).status_code
        == 404
    )


def test_default_cannot_be_disabled(client, actors):
    client.force_login(actors[0])
    assert (
        client.post(
            "/api/projects/1/",
            {"name": "公开", "isActive": False},
            content_type="application/json",
        ).status_code
        == 400
    )
    assert Project.objects.get(pk=1).is_active


def test_article_media_publish_archive_and_revision(client, actors):
    client.force_login(actors[0])
    response = client.post(
        "/api/content/articles/",
        {
            "kind": "news",
            "title": "学术会议",
            "category": "学术会议",
            "body": "会议内容",
            "status": "draft",
        },
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    article = response.json()
    blob = io.BytesIO()
    Image.new("RGB", (20, 20)).save(blob, "PNG")
    upload = client.post(
        f"/api/content/articles/{article['id']}/assets/",
        {
            "file": SimpleUploadedFile(
                "photo.png", blob.getvalue(), content_type="image/png"
            )
        },
    )
    assert upload.status_code == 201
    url = upload.json()["url"]
    client.logout()
    assert client.get(url).status_code == 404
    assert client.get("/api/content/articles/").json()["total"] == 0
    client.force_login(actors[0])
    patch = {
        "revision": article["revision"],
        "status": "published",
        "commitAssetIds": [upload.json()["id"]],
    }
    detail = f"/api/content/articles/{article['id']}/"
    assert (
        client.post(detail, patch, content_type="application/json").status_code == 200
    )
    assert (
        client.post(detail, patch, content_type="application/json").status_code == 409
    )
    client.logout()
    assert client.get(detail).status_code == 200
    assert client.get(url).status_code == 200
    Article.objects.filter(pk=article["id"]).update(status="archived")
    assert client.get(url).status_code == 404


def test_header_query_conflict_and_aggregate_write(client, actors):
    client.force_login(actors[0])
    assert (
        client.get(
            "/api/catalog/resources/?projectTagId=1",
            HTTP_X_PROJECT_ID=str(actors[3].pk),
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/catalog/import/commit/",
            {},
            content_type="application/json",
            HTTP_X_PROJECT_ID="all",
        ).status_code
        == 400
    )


def test_anonymous_public_module_reads(client):
    for url in (
        "/api/catalog/resources/",
        "/api/catalog/directories/",
        "/api/layers/",
        "/api/catalog/workspaces/",
        "/api/catalog/map-compositions/",
        "/api/catalog/results/",
        "/api/raster/datasets/",
        "/api/data-schema/summary/",
        "/api/content/articles/",
    ):
        response = client.get(url)
        assert response.status_code == 200, (url, response.content)


def test_private_jobs_and_snapshot_cannot_cross_projects(actors):
    from apps.catalog.models import WorkspaceScene
    from apps.raster.models import RasterProcessingJob
    from apps.raster.services.jobs import get_job
    from apps.raster.services.exceptions import RasterJobError
    from apps.projects.context import require_live_membership
    from django.core.exceptions import PermissionDenied

    _, alice, _, p, q = actors
    foreign = DataResource.objects.create(
        name="foreign", code="foreign", data_type="vector", project_tag=q
    )
    RasterProcessingJob.objects.create(id="foreign-job", kind="render", project_tag=q)
    with project_scope(ProjectScope((p.id,), p.id, alice.id)):
        with pytest.raises(RasterJobError):
            get_job("foreign-job")
        with pytest.raises(ValidationError):
            WorkspaceScene.objects.create(
                name="forged",
                owner=alice,
                snapshot={
                    "groups": [{"children": [{"sourceResource": {"id": foreign.id}}]}]
                },
            )
        require_live_membership()
        ProjectMembership.objects.filter(user=alice, project=p).delete()
        with pytest.raises(PermissionDenied):
            require_live_membership()


def test_composition_optimistic_lock(client, actors):
    from apps.catalog.models import WorkspaceScene, MapComposition

    admin, _, _, p, _ = actors
    scene = WorkspaceScene.objects.create(project_tag=p, owner=admin, name="layout")
    composition = MapComposition.objects.create(
        project_tag=p, owner=admin, project=scene, name="layout", layout={"version": 1}
    )
    client.force_login(admin)
    payload = {
        "action": "update",
        "layout": {"version": 1, "title": {"text": "saved"}},
        "expectedUpdatedAt": composition.updated_at.isoformat(),
    }
    url = f"/api/catalog/map-compositions/{composition.pk}/"
    assert (
        client.post(
            url, payload, content_type="application/json", HTTP_X_PROJECT_ID=str(p.id)
        ).status_code
        == 200
    )
    assert (
        client.post(
            url, payload, content_type="application/json", HTTP_X_PROJECT_ID=str(p.id)
        ).status_code
        == 409
    )


def test_assignment_admin_does_not_gain_private_data_access(client, actors):
    _, alice, _, p, q = actors
    alice.user_permissions.add(
        Permission.objects.get(content_type__app_label="core", codename="manage_auth")
    )
    client.force_login(alice)
    result = client.get("/api/projects/").json()
    assert {x["id"] for x in result["items"]} == {1, p.id}
    assert result["assignableItems"] == []
    assert result["canAssign"] is False
    assert (
        client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID=str(q.id)).status_code
        == 404
    )
    assert (
        client.get("/api/content/articles/", HTTP_X_PROJECT_ID=str(q.id)).status_code
        == 200
    )


def test_asset_changes_are_atomic_and_clear_removed_cover(client, actors):
    from apps.content.models import Asset
    from apps.content.views import store_asset

    admin = actors[0]
    article = Article.objects.create(kind="news", title="资料", category="学术会议")
    other = Article.objects.create(kind="news", title="其他", category="学术会议")
    blob = io.BytesIO()
    Image.new("RGB", (20, 20)).save(blob, "PNG")
    photo = store_asset(article, "photo.png", blob.getvalue())
    foreign = store_asset(other, "photo.png", blob.getvalue())
    article.cover_asset = photo
    article.save()
    client.force_login(admin)
    url = f"/api/content/articles/{article.pk}/"
    bad = client.post(
        url,
        {"revision": 1, "title": "不应写入", "removeAssetIds": [foreign.id]},
        content_type="application/json",
    )
    assert bad.status_code == 400
    article.refresh_from_db()
    assert article.title == "资料" and article.revision == 1
    caption = client.post(
        url,
        {"revision": 1, "assetCaptions": [{"id": photo.id, "caption": "报告示意"}]},
        content_type="application/json",
    )
    assert caption.status_code == 200
    assert caption.json()["assets"][0]["caption"] == "报告示意"
    removed = client.post(
        url,
        {"revision": 2, "removeAssetIds": [photo.id]},
        content_type="application/json",
    )
    assert removed.status_code == 200
    assert removed.json()["coverUrl"] == "" and removed.json()["assets"] == []
    article.refresh_from_db()
    assert article.cover_asset_id is None
    assert Asset.objects.filter(pk=foreign.id).exists()


def test_anonymous_raster_render_only_exposes_own_public_jobs(client, monkeypatch):
    from apps.raster.services.jobs import RasterJob
    from apps.raster import views
    from django.contrib.auth.models import Group

    resource = DataResource.objects.create(
        name="公开栅格", code="pub-raster", data_type="raster"
    )
    layer = MapLayer.objects.create(
        name="公开图层", code="pub-layer", layer_type="raster", data_resource=resource
    )
    layer.access_groups.add(Group.objects.create(name="旧分组不覆盖默认公开规则"))
    job = RasterJob(id="own-public-render", kind="render")
    monkeypatch.setattr(views, "start_render_job", lambda **kwargs: job)
    monkeypatch.setattr(views, "get_job", lambda job_id: job)
    assert client.get("/api/raster/jobs/own-public-render/").status_code == 403
    response = client.post(
        "/api/raster/render/async/",
        {"layerId": layer.id, "rulesMode": "default"},
        content_type="application/json",
    )
    assert response.status_code == 202, response.content
    assert client.get("/api/raster/jobs/own-public-render/").status_code == 200
    assert (
        client.post(
            "/api/raster/render/async/",
            {"layerId": layer.id, "rulesMode": "custom"},
            content_type="application/json",
        ).status_code
        == 403
    )
    job.kind = "import"
    assert client.get("/api/raster/jobs/own-public-render/").status_code == 403


def test_scan_coalescing_and_startup_discovery_are_project_scoped(actors, monkeypatch):
    from apps.raster.services import jobs
    from apps.catalog import services
    from apps.projects.context import current_scope

    _, alice, bob, p, q = actors
    monkeypatch.setattr(jobs, "_submit_job", lambda *args, **kwargs: None)
    with project_scope(ProjectScope((p.id,), p.id, alice.id)):
        first = jobs.start_scan_job(created_by_id=alice.id)
        assert jobs.start_scan_job(created_by_id=alice.id).id == first.id
    with project_scope(ProjectScope((q.id,), q.id, bob.id)):
        second = jobs.start_scan_job(created_by_id=bob.id)
        assert second.id != first.id
        assert second.project_tag_id == q.id
    seen = []
    monkeypatch.setattr(
        services,
        "scan_vector_geopackage_layers",
        lambda: seen.append(current_scope.get().selected) or [],
    )
    monkeypatch.setattr(services, "scan_nongeographic_files", lambda: [])
    services.scan_catalog_sources()
    assert seen == [1]
    with jobs._LOCK:
        jobs._JOBS.pop(first.id, None)
        jobs._JOBS.pop(second.id, None)


def test_restart_recovery_includes_stale_jobs_in_other_projects(actors, monkeypatch):
    from apps.raster.models import RasterProcessingJob
    from apps.raster.services import jobs

    _, alice, _, p, q = actors
    RasterProcessingJob.objects.create(
        id="restart-a", kind="render", status="running", project_tag=p
    )
    RasterProcessingJob.objects.create(
        id="restart-b", kind="render", status="queued", project_tag=q
    )
    monkeypatch.setattr(jobs, "_RESTART_RECONCILED", False)
    with project_scope(ProjectScope((p.id,), p.id, alice.id)):
        assert jobs.reconcile_interrupted_jobs()
    assert set(
        RasterProcessingJob.objects.filter(
            id__in=["restart-a", "restart-b"]
        ).values_list("status", flat=True)
    ) == {"failed"}
