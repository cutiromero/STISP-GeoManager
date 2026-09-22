import io
import importlib
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.audit.models import OperationLog
from apps.catalog.models import MapComposition, MapCompositionVersion, WorkspaceScene
from apps.core.initialization import (
    DEFAULT_USER_GROUP_NAME,
    GUEST_GROUP_NAME,
    ensure_default_user_group,
)


class MapCompositionApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="map-composer", password="pass12345"
        )
        grant(
            self.user,
            "add_mapcomposition",
            "view_mapcomposition",
            "change_mapcomposition",
            "delete_mapcomposition",
            "export_mapcomposition",
            "publish_mapcomposition",
            "restore_mapcomposition",
            "add_workspacescene",
        )
        self.client.force_login(self.user)
        self.project = WorkspaceScene.objects.create(
            owner=self.user,
            kind=WorkspaceScene.Kind.PROJECT,
            name="测试制图工程",
            snapshot={"groups": [], "mapView": None},
        )
        self.audience_group = Group.objects.create(name="专题成果访问组")
        self.workspace_snapshot = {
            "version": 2,
            "groups": [],
            "selectedLayerId": None,
            "mapView": None,
        }
        self.layout = {
            "version": 1,
            "page": {
                "preset": "A4",
                "orientation": "landscape",
                "widthMm": 297,
                "heightMm": 210,
                "dpi": 300,
            },
            "mapFrame": {
                "xMm": 14,
                "yMm": 28,
                "widthMm": 210,
                "heightMm": 150,
                "bounds": [87.4, 43.6, 87.8, 44.0],
            },
        }

    def test_create_update_version_publish_preview_and_delete(self):
        response = self.client.post(
            "/api/catalog/map-compositions/",
            data=json.dumps(
                {
                    "projectId": self.project.id,
                    "name": "胡杨样地专题图",
                    "description": "A4 横版",
                    "layout": self.layout,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        composition_id = response.json()["id"]
        self.assertEqual(response.json()["status"], "draft")
        self.assertEqual(response.json()["projectName"], self.project.name)

        update_response = self.client.post(
            f"/api/catalog/map-compositions/{composition_id}/",
            data=json.dumps(
                {
                    "action": "update",
                    "description": "包含区位副图和经纬网",
                    "layout": {**self.layout, "grid": {"enabled": True}},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(update_response.status_code, 200)
        self.assertTrue(update_response.json()["layout"]["grid"]["enabled"])

        with tempfile.TemporaryDirectory() as tmpdir:
            config = replace(
                settings.PROJECT_CONFIG,
                app_data=Path(tmpdir) / "app",
                research_data_root=Path(tmpdir) / "research",
            )
            with override_settings(PROJECT_CONFIG=config):
                version_response = self.client.post(
                    f"/api/catalog/map-compositions/{composition_id}/versions/",
                    data={
                        "image": png_file(320, 240),
                        "payload": json.dumps(
                            {
                                "format": "pdf",
                                "dpi": 300,
                                "widthPx": 320,
                                "heightPx": 240,
                                "note": "第一版",
                                "workspaceSnapshot": self.workspace_snapshot,
                            }
                        ),
                    },
                )

                self.assertEqual(version_response.status_code, 201)
                version = version_response.json()
                self.assertEqual(version["versionNumber"], 1)
                self.assertEqual(version["format"], "pdf")
                self.assertEqual(version["snapshotSchemaVersion"], 2)
                self.assertEqual(len(version["snapshotChecksum"]), 64)
                self.assertTrue(
                    config.app_path(
                        "exports",
                        "map-compositions",
                        str(composition_id),
                        "v1",
                        "artifact.pdf",
                    ).is_file()
                )

                preview_response = self.client.get(
                    version["previewUrl"],
                )
                self.assertEqual(preview_response.status_code, 200)
                self.assertEqual(preview_response.headers["Content-Type"], "image/png")
                b"".join(preview_response.streaming_content)
                preview_response.close()

                download_response = self.client.get(version["downloadUrl"])
                self.assertEqual(download_response.status_code, 200)
                self.assertEqual(
                    download_response.headers["Content-Type"], "application/pdf"
                )
                self.assertIn(".pdf", download_response.headers["Content-Disposition"])
                pdf_content = b"".join(download_response.streaming_content)
                self.assertTrue(pdf_content.startswith(b"%PDF-"))
                self.assertGreater(len(pdf_content), 100)
                download_response.close()

        publish_response = self.client.post(
            f"/api/catalog/map-compositions/{composition_id}/publish/",
            data=json.dumps(
                {
                    "versionNumber": 1,
                    "audienceGroupIds": [self.audience_group.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(publish_response.status_code, 200)
        self.assertEqual(publish_response.json()["status"], "published")
        self.assertEqual(
            publish_response.json()["publishedVersion"]["versionNumber"], 1
        )

        restore_response = self.client.post(
            f"/api/catalog/map-compositions/{composition_id}/restore-project/",
            data=json.dumps(
                {
                    "versionNumber": 1,
                    "name": "胡杨样地专题图恢复工程",
                    "accessGroupIds": [],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(restore_response.status_code, 201)
        self.assertEqual(restore_response.json()["project"]["kind"], "project")
        restored = WorkspaceScene.objects.get(
            pk=restore_response.json()["project"]["id"]
        )
        self.assertEqual(restored.snapshot, self.workspace_snapshot)

        delete_response = self.client.post(
            f"/api/catalog/map-compositions/{composition_id}/",
            data=json.dumps({"action": "delete"}),
            content_type="application/json",
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(
            delete_response.json(),
            {"deleted": True, "id": composition_id, "detail": "出图稿已删除"},
        )
        self.assertFalse(MapComposition.objects.filter(pk=composition_id).exists())
        self.assertFalse(
            MapCompositionVersion.objects.filter(composition_id=composition_id).exists()
        )
        self.assertTrue(
            OperationLog.objects.filter(
                target_type="map_composition",
                target_id=composition_id,
                target_code="deleted",
            ).exists()
        )

    def test_delete_removes_files_and_allows_same_name_to_be_created_again(self):
        composition = MapComposition.objects.create(
            owner=self.user,
            project=self.project,
            name="可重复生成的专题图",
            layout=self.layout,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config = replace(
                settings.PROJECT_CONFIG,
                app_data=Path(tmpdir) / "app",
                research_data_root=Path(tmpdir) / "research",
            )
            with override_settings(PROJECT_CONFIG=config):
                version_response = self.client.post(
                    f"/api/catalog/map-compositions/{composition.id}/versions/",
                    data={
                        "image": png_file(200, 100),
                        "payload": json.dumps(
                            {
                                "format": "pdf",
                                "dpi": 150,
                                "widthPx": 200,
                                "heightPx": 100,
                                "workspaceSnapshot": self.workspace_snapshot,
                            }
                        ),
                    },
                )
                self.assertEqual(version_response.status_code, 201)
                version = MapCompositionVersion.objects.get(composition=composition)
                preview_path = config.app_path(*version.preview_path.split("/"))
                artifact_path = config.app_path(*version.artifact_path.split("/"))
                self.assertTrue(preview_path.is_file())
                self.assertTrue(artifact_path.is_file())

                publish_response = self.client.post(
                    f"/api/catalog/map-compositions/{composition.id}/publish/",
                    data=json.dumps(
                        {
                            "versionNumber": 1,
                            "audienceGroupIds": [self.audience_group.id],
                        }
                    ),
                    content_type="application/json",
                )
                self.assertEqual(publish_response.status_code, 200)

                delete_response = self.client.post(
                    f"/api/catalog/map-compositions/{composition.id}/",
                    data=json.dumps({"action": "delete"}),
                    content_type="application/json",
                )
                self.assertEqual(delete_response.status_code, 200)
                self.assertFalse(preview_path.exists())
                self.assertFalse(artifact_path.exists())

                recreate_response = self.client.post(
                    "/api/catalog/map-compositions/",
                    data=json.dumps(
                        {
                            "projectId": self.project.id,
                            "name": "可重复生成的专题图",
                            "layout": self.layout,
                        }
                    ),
                    content_type="application/json",
                )
                self.assertEqual(recreate_response.status_code, 201)

    def test_rejects_embedded_image_and_publish_without_version(self):
        invalid = self.client.post(
            "/api/catalog/map-compositions/",
            data=json.dumps(
                {
                    "projectId": self.project.id,
                    "name": "非法版式",
                    "layout": {"logo": "data:image/png;base64,AAAA"},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(invalid.status_code, 400)

        composition = MapComposition.objects.create(
            owner=self.user,
            project=self.project,
            name="尚未导出的专题图",
            layout=self.layout,
        )
        publish = self.client.post(
            f"/api/catalog/map-compositions/{composition.id}/publish/",
            data=json.dumps(
                {
                    "versionNumber": 1,
                    "audienceGroupIds": [self.audience_group.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(publish.status_code, 404)
        self.assertEqual(publish.json()["detail"], "专题成果版本不存在")

    def test_version_dimensions_must_match_uploaded_png(self):
        composition = MapComposition.objects.create(
            owner=self.user,
            project=self.project,
            name="尺寸校验专题图",
            layout=self.layout,
        )
        response = self.client.post(
            f"/api/catalog/map-compositions/{composition.id}/versions/",
            data={
                "image": png_file(200, 100),
                "payload": json.dumps(
                    {
                        "format": "png",
                        "dpi": 150,
                        "widthPx": 201,
                        "heightPx": 100,
                        "workspaceSnapshot": self.workspace_snapshot,
                    }
                ),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "上传图片尺寸与成果参数不一致")
        self.assertFalse(MapCompositionVersion.objects.exists())

    def test_version_rejects_image_above_independent_byte_limit(self):
        composition = MapComposition.objects.create(
            owner=self.user,
            project=self.project,
            name="文件大小校验专题图",
            layout=self.layout,
        )
        with patch("apps.catalog.map_compositions.MAP_COMPOSITION_IMAGE_MAX_BYTES", 1):
            response = self.client.post(
                f"/api/catalog/map-compositions/{composition.id}/versions/",
                data={
                    "image": png_file(2, 2),
                    "payload": json.dumps(
                        {
                            "format": "png",
                            "dpi": 150,
                            "widthPx": 2,
                            "heightPx": 2,
                            "workspaceSnapshot": self.workspace_snapshot,
                        }
                    ),
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "出图母图不能超过 128 MB")
        self.assertFalse(MapCompositionVersion.objects.exists())

    def test_unpublished_is_private_and_published_audience_gets_limited_access(self):
        viewer = get_user_model().objects.create_user(
            username="published-topic-viewer", password="pass12345"
        )
        viewer.groups.add(self.audience_group)
        grant(
            viewer,
            "view_mapcomposition",
            "export_mapcomposition",
            "restore_mapcomposition",
            "add_workspacescene",
        )
        private_composition = MapComposition.objects.create(
            owner=self.user,
            project=self.project,
            name="未发布专题",
            layout=self.layout,
            source_workspace_snapshot=self.workspace_snapshot,
        )
        published_composition = MapComposition.objects.create(
            owner=self.user,
            project=self.project,
            name="已发布专题",
            layout=self.layout,
            source_workspace_snapshot=self.workspace_snapshot,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config = replace(
                settings.PROJECT_CONFIG,
                app_data=Path(tmpdir) / "app",
                research_data_root=Path(tmpdir) / "research",
            )
            with override_settings(PROJECT_CONFIG=config):
                version_response = self.client.post(
                    f"/api/catalog/map-compositions/{published_composition.id}/versions/",
                    data={
                        "image": png_file(160, 120),
                        "payload": json.dumps(
                            {
                                "format": "png",
                                "dpi": 150,
                                "widthPx": 160,
                                "heightPx": 120,
                                "workspaceSnapshot": self.workspace_snapshot,
                            }
                        ),
                    },
                )
                self.assertEqual(version_response.status_code, 201)
                publish_response = self.client.post(
                    f"/api/catalog/map-compositions/{published_composition.id}/publish/",
                    data=json.dumps(
                        {
                            "versionNumber": 1,
                            "audienceGroupIds": [self.audience_group.id],
                        }
                    ),
                    content_type="application/json",
                )
                self.assertEqual(publish_response.status_code, 200)

                self.client.force_login(viewer)
                list_response = self.client.get("/api/catalog/map-compositions/")
                self.assertEqual(list_response.status_code, 200)
                self.assertEqual(
                    [item["name"] for item in list_response.json()["items"]],
                    ["已发布专题"],
                )
                shared = list_response.json()["items"][0]
                self.assertFalse(shared["canEditLayout"])
                self.assertFalse(shared["canPublish"])
                self.assertTrue(shared["canDownload"])
                self.assertTrue(shared["canRestoreProject"])
                self.assertEqual(len(shared["versions"]), 1)
                self.assertEqual(shared["status"], "published")
                self.assertEqual(shared["publishedVersion"]["versionNumber"], 1)
                self.assertEqual(shared["publishedVersion"]["format"], "png")

                results_list_response = self.client.get(
                    "/api/catalog/map-compositions/?status=published"
                )
                self.assertEqual(results_list_response.status_code, 200)
                self.assertEqual(
                    [item["name"] for item in results_list_response.json()["items"]],
                    ["已发布专题"],
                )
                results_item = results_list_response.json()["items"][0]
                self.assertEqual(
                    results_item["publishedVersion"], shared["publishedVersion"]
                )

                published_preview_response = self.client.get(
                    results_item["publishedVersion"]["previewUrl"]
                )
                self.assertEqual(published_preview_response.status_code, 200)
                self.assertEqual(
                    published_preview_response.headers["Content-Type"], "image/png"
                )
                preview_content = b"".join(published_preview_response.streaming_content)
                self.assertTrue(preview_content.startswith(b"\x89PNG\r\n\x1a\n"))
                published_preview_response.close()

                private_response = self.client.get(
                    f"/api/catalog/map-compositions/{private_composition.id}/"
                )
                self.assertEqual(private_response.status_code, 404)
                update_response = self.client.post(
                    f"/api/catalog/map-compositions/{published_composition.id}/",
                    data=json.dumps({"description": "越权修改"}),
                    content_type="application/json",
                )
                self.assertEqual(update_response.status_code, 404)
                delete_response = self.client.post(
                    f"/api/catalog/map-compositions/{published_composition.id}/",
                    data=json.dumps({"action": "delete"}),
                    content_type="application/json",
                )
                self.assertEqual(delete_response.status_code, 404)
                download_response = self.client.get(
                    results_item["publishedVersion"]["downloadUrl"]
                )
                self.assertEqual(download_response.status_code, 200)
                b"".join(download_response.streaming_content)
                download_response.close()

    def test_default_user_can_see_composition_published_to_guest_audience(self):
        default_group = Group.objects.get(name=DEFAULT_USER_GROUP_NAME)
        default_group.permissions.remove(
            Permission.objects.get(
                content_type__app_label="catalog",
                codename="view_mapcomposition",
            )
        )
        ensure_default_user_group()
        self.assertTrue(
            default_group.permissions.filter(
                content_type__app_label="catalog",
                codename="view_mapcomposition",
            ).exists()
        )
        viewer = get_user_model().objects.create_user(
            username="ordinary-public-topic-viewer", password="pass12345"
        )
        viewer.groups.add(default_group)
        guest_group = Group.objects.get(name=GUEST_GROUP_NAME)
        composition = MapComposition.objects.create(
            owner=self.user,
            project=self.project,
            name="游客开放专题图",
            status=MapComposition.Status.PUBLISHED,
            layout=self.layout,
            source_workspace_snapshot=self.workspace_snapshot,
        )
        version = MapCompositionVersion.objects.create(
            composition=composition,
            version_number=1,
            format=MapCompositionVersion.Format.PNG,
            dpi=150,
            width_px=160,
            height_px=120,
            preview_path="exports/map-compositions/public/v1/preview.png",
            artifact_path="exports/map-compositions/public/v1/artifact.png",
            layout_snapshot=self.layout,
            workspace_snapshot=self.workspace_snapshot,
            created_by=self.user,
        )
        composition.published_version = version
        composition.save(update_fields=["published_version"])
        composition.audience_groups.add(guest_group)

        self.client.force_login(viewer)
        response = self.client.get("/api/catalog/map-compositions/?status=published")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["name"] for item in response.json()["items"]],
            ["游客开放专题图"],
        )
        self.assertEqual(
            response.json()["items"][0]["publishedVersion"]["versionNumber"],
            1,
        )
        self.assertFalse(response.json()["items"][0]["canEditLayout"])

    def test_platform_admin_can_manage_every_users_draft(self):
        platform_group = Group.objects.get(name="平台管理员")
        platform_admin = get_user_model().objects.create_user(
            username="topic-platform-admin", password="pass12345"
        )
        platform_admin.groups.add(platform_group)
        grant(platform_admin, "view_mapcomposition", "change_mapcomposition")
        composition = MapComposition.objects.create(
            owner=self.user,
            project=self.project,
            name="他人专题草稿",
            layout=self.layout,
            source_workspace_snapshot=self.workspace_snapshot,
        )
        self.client.force_login(platform_admin)

        list_response = self.client.get("/api/catalog/map-compositions/")
        update_response = self.client.post(
            f"/api/catalog/map-compositions/{composition.id}/",
            data=json.dumps({"description": "平台管理员维护"}),
            content_type="application/json",
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertIn(
            composition.id, {item["id"] for item in list_response.json()["items"]}
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["description"], "平台管理员维护")

    def test_cleanup_migration_removes_legacy_topics_and_backfills_snapshots(self):
        legacy_topic = WorkspaceScene.objects.create(
            owner=self.user,
            kind="topic",
            name="待清理旧专题",
            snapshot={"groups": []},
        )
        composition = MapComposition.objects.create(
            owner=self.user,
            project=self.project,
            name="待回填专题",
            layout=self.layout,
        )
        version = MapCompositionVersion.objects.create(
            composition=composition,
            version_number=1,
            format="png",
            dpi=150,
            width_px=100,
            height_px=100,
            preview_path="preview.png",
            artifact_path="artifact.png",
            layout_snapshot=self.layout,
            created_by=self.user,
        )
        migration = importlib.import_module(
            "apps.catalog.migrations.0008_map_composition_publication_and_project_only"
        )

        migration.remove_legacy_topics_and_backfill_snapshots(apps, None)

        self.assertFalse(WorkspaceScene.objects.filter(pk=legacy_topic.id).exists())
        composition.refresh_from_db()
        version.refresh_from_db()
        self.assertEqual(composition.source_workspace_snapshot, self.project.snapshot)
        self.assertEqual(version.workspace_snapshot, self.project.snapshot)
        self.assertEqual(len(version.snapshot_checksum), 64)

    def test_archived_composition_migration_preserves_topic_and_version(self):
        archived = MapComposition.objects.create(
            owner=self.user,
            project=self.project,
            name="历史归档专题",
            status="archived",
            layout=self.layout,
        )
        archived_version = MapCompositionVersion.objects.create(
            composition=archived,
            version_number=1,
            format="png",
            dpi=150,
            width_px=100,
            height_px=100,
            preview_path="preview.png",
            artifact_path="artifact.png",
            layout_snapshot=self.layout,
            created_by=self.user,
        )
        archived.published_version = archived_version
        archived.save(update_fields=["published_version"])
        migration = importlib.import_module(
            "apps.catalog.migrations.0009_remove_map_composition_archived_status"
        )

        migration.preserve_archived_map_compositions(apps, None)

        archived.refresh_from_db()
        archived_version.refresh_from_db()
        self.assertEqual(archived.status, MapComposition.Status.COMPLETED)
        self.assertEqual(archived.published_version_id, archived_version.id)
        self.assertEqual(archived_version.preview_path, "preview.png")
        self.assertEqual(archived_version.artifact_path, "artifact.png")


def png_file(width: int, height: int) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, "PNG")
    return SimpleUploadedFile("composition.png", buffer.getvalue(), "image/png")


def grant(user, *codenames: str) -> None:
    for codename in codenames:
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label="catalog", codename=codename)
        )
