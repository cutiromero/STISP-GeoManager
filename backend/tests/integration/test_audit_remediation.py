import io
import json
from datetime import timedelta
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.catalog.models import WorkspaceScene
from apps.content.models import Article, Asset
from apps.content.views import cleanup_pending_assets
from apps.core.backup_service import (
    _backup_sources,
    _build_backup_archive,
    BackupServiceError,
)
from apps.core.config import load_project_config
from apps.core.map_thumbnail import configured_tile_url, ThumbnailTileError
from apps.projects.context import ProjectScope, project_scope
from .core.test_backup import minimal_config_text


@pytest.fixture
def environment(settings, tmp_path, client):
    config = tmp_path / "app.toml"
    config.write_text(
        minimal_config_text(tmp_path / "app", tmp_path / "research"), encoding="utf-8"
    )
    settings.PROJECT_CONFIG = load_project_config(
        config, program_root=tmp_path / "program"
    )
    user = get_user_model().objects.create_superuser(
        "audit-admin", password="test-pass"
    )
    client.force_login(user)
    return settings.PROJECT_CONFIG, user


def test_full_backup_restore_and_invalid_database_never_deletes_source(
    environment, tmp_path
):
    config, _ = environment
    for name in [
        "projects/1/content/a.png",
        "projects/2/content/a.pdf",
        "exports/map-compositions/1/map.png",
    ]:
        path = config.app_data / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"persistent")
    for name in ["vector/a.txt", "projects/2/table/a.csv", "projects/3/raster/a.tif"]:
        path = config.research_data_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"research")
    with project_scope(ProjectScope((2,), 2)):
        for plan in ["platform", "research"]:
            sources = _backup_sources(plan, include_logs=False)
            archive, manifest = _build_backup_archive(
                plan, plan, include_logs=False, progress=lambda *args: None
            )
            with ZipFile(archive) as zipped:
                for entry in manifest["files"]:
                    target = tmp_path / "restored" / entry["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zipped.read(entry["path"]))
                for source in sources:
                    assert (
                        tmp_path / "restored" / source.archive_name
                    ).read_bytes() == source.path.read_bytes()
    broken = config.research_data_root / "vector/broken.gpkg"
    broken.write_bytes(b"invalid geopackage")
    with pytest.raises(BackupServiceError):
        _build_backup_archive(
            "research", "bad", include_logs=False, progress=lambda *args: None
        )
    assert broken.read_bytes() == b"invalid geopackage"


def test_workspace_paged_summaries_and_conflicting_saves(environment, client):
    _, user = environment
    WorkspaceScene.objects.bulk_create(
        [
            WorkspaceScene(
                owner=user,
                name=f"scene-{i:03d}",
                snapshot={"groups": [], "note": "x" * 12000},
            )
            for i in range(105)
        ]
    )
    result = client.get("/api/catalog/workspaces/?limit=24&offset=24").json()
    assert result["total"] == 105 and len(result["items"]) == 24
    assert all("snapshot" not in item for item in result["items"])
    assert len(json.dumps(result)) < 24000
    item = result["items"][0]
    detail = client.get(f"/api/catalog/workspaces/{item['id']}/").json()
    assert len(detail["snapshot"]["note"]) == 12000
    for url in [
        f"/api/catalog/workspaces/{item['id']}/",
        f"/api/admin/workspaces/{item['id']}/",
    ]:
        data = {
            "name": "saved",
            "expectedUpdatedAt": detail["updatedAt"],
            **({"action": "update"} if "admin" in url else {}),
        }
        assert (
            client.post(
                url, {"name": "missing version"}, content_type="application/json"
            ).status_code
            == 400
        )
        response = client.post(url, data, content_type="application/json")
        assert response.status_code == 200
        assert (
            client.post(
                url,
                {**data, "name": "stale overwrite"},
                content_type="application/json",
            ).status_code
            == 409
        )
        assert WorkspaceScene.objects.get(pk=item["id"]).name == "saved"
        detail = response.json()
    assert client.get("/api/catalog/workspaces/?q=scene-099").json()["total"] == 1


def test_pending_assets_save_cancel_expiry_and_editor_isolation(environment, client):
    config, admin = environment
    article = Article.objects.create(
        kind="news", title="Published", category="学术会议", status="published"
    )
    detail = f"/api/content/articles/{article.pk}/"

    def upload(color):
        buf = io.BytesIO()
        Image.new("RGB", (5, 5), color).save(buf, "PNG")
        response = client.post(
            detail + "assets/",
            {
                "file": SimpleUploadedFile(
                    "a.png", buf.getvalue(), content_type="image/png"
                )
            },
        )
        assert response.status_code == 201
        return response.json()

    staged = upload("red")
    assert staged["pending"]
    assert client.get(detail).json()["assets"] == []
    preview = client.get(staged["url"])
    assert preview.status_code == 200
    preview.close()
    client.logout()
    assert client.get(staged["url"]).status_code == 404
    other = get_user_model().objects.create_superuser(
        "other-editor", password="test-pass"
    )
    client.force_login(other)
    assert client.get(staged["url"]).status_code == 404
    bad = client.post(
        detail,
        {
            "revision": 1,
            "title": "unauthorized commit",
            "commitAssetIds": [staged["id"]],
        },
        content_type="application/json",
    )
    assert bad.status_code == 400
    article.refresh_from_db()
    assert article.revision == 1 and article.title == "Published"
    client.force_login(admin)
    saved = client.post(
        detail,
        {
            "revision": 1,
            "commitAssetIds": [staged["id"]],
            "coverAssetId": staged["id"],
            "assetCaptions": [{"id": staged["id"], "caption": "committed"}],
        },
        content_type="application/json",
    )
    assert saved.status_code == 200
    assert not saved.json()["assets"][0]["pending"]
    client.logout()
    response = client.get(staged["url"])
    assert response.status_code == 200
    response.close()
    client.force_login(admin)
    cancelled = upload("blue")
    target = config.app_data / Asset.objects.get(pk=cancelled["id"]).path
    assert client.delete(cancelled["url"]).status_code == 200
    assert not target.exists()
    expired = upload("green")
    Asset.objects.filter(pk=expired["id"]).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert client.get(expired["url"]).status_code == 404
    assert cleanup_pending_assets() == 1
    assert not Asset.objects.filter(pk=expired["id"]).exists()


@pytest.mark.parametrize(
    "body", [b"[]", b"null", b"42", b"\xff", b'{"username":[]}', b'{"remember":"yes"}']
)
def test_auth_invalid_input_is_json_400(client, environment, body):
    client.logout()
    for url in ["/api/auth/login/", "/api/auth/register/"]:
        response = client.post(url, body, content_type="application/json")
        assert response.status_code == 400
        assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize("value", ["2026-02-30", "no-date", [], 12])
def test_bad_date_never_writes(environment, client, value):
    article = Article.objects.create(
        kind="news", title="unchanged", category="学术会议"
    )
    response = client.post(
        f"/api/content/articles/{article.pk}/",
        {"revision": 1, "title": "bad", "eventDate": value},
        content_type="application/json",
    )
    assert response.status_code == 400
    article.refresh_from_db()
    assert article.title == "unchanged" and article.revision == 1


def test_each_basemap_uses_selected_provider_style_and_zoom(environment):
    document = {
        "application": {
            "map": {
                "mapbox_access_token": "test",
                "tianditu_access_token": "test",
                "default_basemap": "mapbox",
            }
        }
    }
    with patch(
        "apps.core.map_thumbnail.load_runtime_config_document", return_value=document
    ):
        assert (
            "streets-v12" in configured_tile_url(20, 1, 1, basemap="mapbox-streets")[0]
        )
        assert (
            "satellite-streets"
            in configured_tile_url(20, 1, 1, basemap="mapbox-satellite")[0]
        )
        assert "openstreetmap.org" in configured_tile_url(19, 1, 1, basemap="osm")[0]
        assert "vec_w" in configured_tile_url(18, 1, 1, basemap="tianditu-vector")[0]
        assert (
            "cia_w"
            in configured_tile_url(18, 1, 1, basemap="tianditu-imagery", labels=True)[0]
        )
        assert (
            configured_tile_url(5, 1, 1, basemap="tianditu-imagery")[1]
            != configured_tile_url(5, 1, 1, basemap="tianditu-imagery", labels=True)[1]
        )
        with pytest.raises(ValueError):
            configured_tile_url(20, 1, 1, basemap="osm")
        with pytest.raises(ValueError):
            configured_tile_url(2, 1, 1, basemap="https://arbitrary-source")
        document["application"]["map"]["mapbox_access_token"] = ""
        with pytest.raises(ThumbnailTileError):
            configured_tile_url(2, 1, 1, basemap="mapbox-streets")
