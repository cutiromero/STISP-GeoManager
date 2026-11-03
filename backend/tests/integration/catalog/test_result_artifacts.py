import json
import tempfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.catalog.models import DataResource, DictionaryItem, ResultArtifact
from apps.core.initialization import GUEST_GROUP_NAME, ensure_guest_user


class ResultArtifactApiTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="result-owner", password="pass12345"
        )
        grant(
            self.owner,
            ("catalog", "view_resultartifact"),
            ("catalog", "add_resultartifact"),
            ("catalog", "download_resultartifact"),
            ("catalog", "publish_resultartifact"),
            ("catalog", "delete_resultartifact"),
        )
        self.viewer = get_user_model().objects.create_user(
            username="result-viewer", password="pass12345"
        )
        grant(
            self.viewer,
            ("catalog", "view_resultartifact"),
            ("catalog", "download_resultartifact"),
        )
        self.audience = Group.objects.create(name="成果访问角色")
        self.viewer.groups.add(self.audience)
        self.category = DictionaryItem.objects.get(code="spatial")
        self.client.force_login(self.owner)

    def test_import_rejects_draft_mode(self):
        with self.result_storage():
            response = self.create_result(
                file=uploaded("analysis.png", b"fake-png", "image/png"),
                publish=False,
                source_type="analysis",
                result_type="image",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "成果导入必须直接发布")
        self.assertFalse(ResultArtifact.objects.exists())

    def test_related_resources_follow_privacy_and_publish_preserves_links(self):
        grant(self.owner, ("catalog", "view_dataresource"))
        grant(self.viewer, ("catalog", "view_dataresource"))
        resource = DataResource.objects.create(
            name="真实图件",
            code="real-related",
            data_type="vector",
            maintainer=self.owner,
            owner_only=True,
            status="active",
        )
        with self.result_storage():
            response = self.create_result(
                file=uploaded("real.png", valid_png(), "image/png"),
                resource_ids=[resource.id],
            )
            self.assertEqual(response.status_code, 201)
            artifact_id = response.json()["id"]
            self.assertEqual(
                response.json()["relatedResources"],
                [{"id": resource.id, "name": "真实图件", "dataType": "vector"}],
            )
            self.client.force_login(self.viewer)
            hidden = self.client.get(f"/api/catalog/results/{artifact_id}/")
            self.assertEqual(hidden.json()["relatedResources"], [])
            self.client.force_login(self.owner)
            preserved = self.client.post(
                f"/api/catalog/results/{artifact_id}/",
                data=json.dumps({"action": "publish"}),
                content_type="application/json",
            )
            self.assertEqual(preserved.status_code, 200)
            self.assertEqual(len(preserved.json()["relatedResources"]), 1)
            cleared = self.client.post(
                f"/api/catalog/results/{artifact_id}/",
                data=json.dumps({"action": "publish", "resourceIds": []}),
                content_type="application/json",
            )
            self.assertEqual(cleared.status_code, 200)
            self.assertEqual(cleared.json()["relatedResources"], [])

    def test_related_resources_reject_cross_project_private_and_invalid_ids(self):
        from apps.projects.models import Project

        other = Project.objects.create(name="其他项目", code="other-result-project")
        resource = DataResource.objects.create(
            name="其他项目图件",
            code="cross-related",
            data_type="vector",
            project_tag=other,
            maintainer=self.owner,
        )
        private = DataResource.objects.create(
            name="其他人私有图件",
            code="private-related",
            data_type="vector",
            maintainer=self.viewer,
            owner_only=True,
        )
        with self.result_storage():
            for ids in ([resource.id], [private.id], [True], [999999], "wrong"):
                with self.subTest(ids=ids):
                    response = self.create_result(
                        file=uploaded("rejected.png", valid_png(), "image/png"),
                        resource_ids=ids,
                    )
                    self.assertEqual(response.status_code, 400)
            self.assertFalse(ResultArtifact.objects.exists())

    def test_published_default_result_is_public(self):
        outsider = get_user_model().objects.create_user(
            username="result-outsider", password="pass12345"
        )
        grant(outsider, ("catalog", "view_resultartifact"))
        with self.result_storage():
            response = self.create_result(
                file=uploaded("report.pdf", valid_pdf(), "application/pdf"),
                result_type="report",
            )

            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["status"], "published")
            self.assertEqual(
                response.json()["accessGroups"],
                [
                    {
                        "id": self.audience.id,
                        "name": self.audience.name,
                        "isGuest": False,
                        "isSuperadmin": False,
                    }
                ],
            )

            self.client.force_login(self.viewer)
            visible = self.client.get("/api/catalog/results/")
            self.assertEqual(visible.status_code, 200)
            self.assertEqual(
                [item["name"] for item in visible.json()["items"]], ["测试成果"]
            )

            self.client.force_login(outsider)
            hidden = self.client.get("/api/catalog/results/")
            self.assertEqual(hidden.status_code, 200)
            self.assertEqual(
                [item["name"] for item in hidden.json()["items"]], ["测试成果"]
            )

    def test_guest_shared_result_is_public_and_previewable(self):
        guest = ensure_guest_user()
        self.audience = Group.objects.get(name=GUEST_GROUP_NAME)
        registered_user = get_user_model().objects.create_user(
            username="public-result-reader", password="pass12345"
        )
        grant(
            registered_user,
            ("catalog", "view_resultartifact"),
            ("catalog", "download_resultartifact"),
        )

        with self.result_storage():
            response = self.create_result(
                file=uploaded("public.png", valid_png(), "image/png"),
                result_type="image",
            )
            self.assertEqual(response.status_code, 201)
            payload = response.json()

            for viewer in (guest, registered_user):
                with self.subTest(username=viewer.username):
                    self.client.force_login(viewer)
                    visible = self.client.get("/api/catalog/results/")
                    self.assertEqual(visible.status_code, 200)
                    self.assertEqual(
                        [item["id"] for item in visible.json()["items"]],
                        [payload["id"]],
                    )

                    preview = self.client.get(payload["previewUrl"])
                    self.assertEqual(preview.status_code, 200)
                    self.assertEqual(b"".join(preview.streaming_content), valid_png())
                    self.assertEqual(preview["Content-Type"], "image/png")
                    self.assertEqual(preview["X-Content-Type-Options"], "nosniff")
                    self.assertIn("sandbox", preview["Content-Security-Policy"])
                    preview.close()

    def test_image_card_thumbnail_is_bounded_cached_and_pdf_has_none(self):
        large = BytesIO()
        Image.new("RGB", (2000, 1000), color=(20, 120, 80)).save(large, format="PNG")
        with self.result_storage():
            image = self.create_result(
                file=uploaded("large.png", large.getvalue(), "image/png"),
                result_type="image",
            ).json()
            document = self.create_result(
                file=uploaded("report.pdf", valid_pdf(), "application/pdf"),
                result_type="report",
            ).json()
            self.assertIsNone(document["thumbnailUrl"])
            self.assertEqual(
                self.client.get(
                    document["previewUrl"].replace("preview", "thumbnail")
                ).status_code,
                400,
            )
            bodies = []
            for _ in range(2):
                response = self.client.get(image["thumbnailUrl"])
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "image/webp")
                # Signed-in responses stay no-store so revoked access applies at once.
                self.assertIn("no-store", response["Cache-Control"])
                bodies.append(b"".join(response.streaming_content))
                response.close()
            self.assertEqual(bodies[0], bodies[1])
            with Image.open(BytesIO(bodies[0])) as thumbnail:
                self.assertEqual(thumbnail.size, (640, 320))

    def test_rejects_disguised_or_corrupt_preview_files(self):
        with self.result_storage():
            disguised_pdf = self.create_result(
                file=uploaded(
                    "evil.pdf",
                    b"<html><script>parent.document.body.innerHTML='owned'</script></html>",
                    "text/html",
                ),
                result_type="report",
            )
            corrupt_image = self.create_result(
                file=uploaded("broken.png", b"not-an-image", "image/png"),
                result_type="image",
            )
            mismatched_image = self.create_result(
                file=uploaded("wrong.jpg", valid_png(), "image/png"),
                result_type="image",
            )

        self.assertEqual(disguised_pdf.status_code, 400)
        self.assertEqual(corrupt_image.status_code, 400)
        self.assertEqual(mismatched_image.status_code, 400)
        self.assertFalse(ResultArtifact.objects.exists())

    def test_uses_server_verified_mime_instead_of_client_content_type(self):
        with self.result_storage():
            response = self.create_result(
                file=uploaded("report.pdf", valid_pdf(), "text/html"),
                result_type="report",
            )
            self.assertEqual(response.status_code, 201)
            artifact = ResultArtifact.objects.get(pk=response.json()["id"])
            self.assertEqual(artifact.mime_type, "application/pdf")

            preview = self.client.get(response.json()["previewUrl"])
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview["Content-Type"], "application/pdf")
            self.assertEqual(preview["X-Content-Type-Options"], "nosniff")
            self.assertEqual(preview["X-Frame-Options"], "SAMEORIGIN")
            self.assertIn("sandbox", preview["Content-Security-Policy"])
            preview.close()

            download = self.client.get(response.json()["downloadUrl"])
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download["X-Frame-Options"], "DENY")
            download.close()

    def test_direct_publish_requires_publish_permission(self):
        uploader = get_user_model().objects.create_user(
            username="result-uploader", password="pass12345"
        )
        grant(
            uploader,
            ("catalog", "view_resultartifact"),
            ("catalog", "add_resultartifact"),
        )
        self.client.force_login(uploader)
        with self.result_storage():
            response = self.create_result(
                file=uploaded("result.csv", b"a,b\n1,2", "text/csv"),
                result_type="table",
            )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ResultArtifact.objects.exists())

    def test_direct_publish_requires_view_permission(self):
        uploader = get_user_model().objects.create_user(
            username="result-uploader-without-view", password="pass12345"
        )
        grant(
            uploader,
            ("catalog", "add_resultartifact"),
            ("catalog", "publish_resultartifact"),
        )
        self.client.force_login(uploader)
        with self.result_storage():
            response = self.create_result(
                file=uploaded("result.csv", b"a,b\n1,2", "text/csv"),
                result_type="table",
            )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ResultArtifact.objects.exists())

    def test_table_can_be_downloaded_but_not_previewed(self):
        with self.result_storage():
            response = self.create_result(
                file=uploaded("result.csv", b"a,b\n1,2", "text/csv"),
                result_type="table",
            )
            self.assertEqual(response.status_code, 201)
            payload = response.json()

            self.client.force_login(self.viewer)
            preview = self.client.get(payload["previewUrl"])
            self.assertEqual(preview.status_code, 400)
            download = self.client.get(payload["downloadUrl"])
            self.assertEqual(download.status_code, 200)
            self.assertEqual(b"".join(download.streaming_content), b"a,b\n1,2")
            download.close()

    def test_rejects_invalid_category_extension_and_oversized_file(self):
        with self.result_storage():
            invalid_category = self.create_result(
                file=uploaded("result.pdf", b"%PDF-1.4", "application/pdf"),
                category_code="thematic",
            )
            invalid_extension = self.create_result(
                file=uploaded("result.exe", b"MZ", "application/octet-stream")
            )
            with patch("apps.catalog.results.runtime_upload_max_mb", return_value=1):
                oversized = self.create_result(
                    file=uploaded(
                        "large.pdf",
                        b"0" * (1024 * 1024 + 1),
                        "application/pdf",
                    )
                )

        self.assertEqual(invalid_category.status_code, 400)
        self.assertEqual(invalid_extension.status_code, 400)
        self.assertEqual(oversized.status_code, 400)
        self.assertFalse(ResultArtifact.objects.exists())

    def test_historical_draft_can_be_published_unpublished_and_deleted(self):
        with self.result_storage() as config:
            relative_path = "exports/results/legacy/legacy-report.pdf"
            path = config.app_path(*relative_path.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"%PDF-1.4 legacy")
            artifact = ResultArtifact.objects.create(
                owner=self.owner,
                name="历史成果草稿",
                description="历史导入草稿",
                source_type=ResultArtifact.SourceType.DIRECT_IMPORT,
                result_type=ResultArtifact.ResultType.REPORT,
                status=ResultArtifact.Status.DRAFT,
                category=self.category,
                provider="测试单位",
                file_path=relative_path,
                file_name="legacy-report.pdf",
                mime_type="application/pdf",
                size_bytes=15,
            )

            published = self.client.post(
                f"/api/catalog/results/{artifact.id}/",
                data=json.dumps(
                    {
                        "action": "publish",
                        "accessGroupIds": [self.audience.id],
                    }
                ),
                content_type="application/json",
            )
            self.assertEqual(published.status_code, 200)
            self.assertEqual(published.json()["status"], "published")
            self.assertTrue(published.json()["canUnpublish"])

            unpublished = self.client.post(
                f"/api/catalog/results/{artifact.id}/",
                data=json.dumps({"action": "unpublish"}),
                content_type="application/json",
            )
            self.assertEqual(unpublished.status_code, 200)
            self.assertEqual(unpublished.json()["status"], "draft")

            deleted = self.client.post(
                f"/api/catalog/results/{artifact.id}/",
                data=json.dumps({"action": "delete"}),
                content_type="application/json",
            )
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(deleted.json()["deleted"], True)
            self.assertFalse(ResultArtifact.objects.filter(pk=artifact.id).exists())
            self.assertFalse(path.exists())

    def create_result(
        self,
        *,
        file: SimpleUploadedFile,
        publish: bool | None = None,
        source_type: str = "direct_import",
        result_type: str = "other",
        category_code: str | None = None,
        resource_ids=None,
    ):
        return self.client.post(
            "/api/catalog/results/",
            data={
                "file": file,
                "payload": json.dumps(
                    {
                        "name": "测试成果",
                        "description": "成果接口集成测试",
                        "sourceType": source_type,
                        "resultType": result_type,
                        "categoryCode": category_code or self.category.code,
                        "provider": "测试单位",
                        "accessGroupIds": [self.audience.id],
                        **(
                            {"resourceIds": resource_ids}
                            if resource_ids is not None
                            else {}
                        ),
                        **({"publish": publish} if publish is not None else {}),
                    },
                    ensure_ascii=False,
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

    def result_storage(self):
        temporary = tempfile.TemporaryDirectory()
        config = replace(
            settings.PROJECT_CONFIG,
            app_data=Path(temporary.name) / "app",
            research_data_root=Path(temporary.name) / "research",
        )
        override = override_settings(PROJECT_CONFIG=config)

        class ResultStorageContext:
            def __enter__(self):
                temporary.__enter__()
                override.__enter__()
                return config

            def __exit__(self, exc_type, exc_value, traceback):
                try:
                    return override.__exit__(exc_type, exc_value, traceback)
                finally:
                    temporary.__exit__(exc_type, exc_value, traceback)

        return ResultStorageContext()


def uploaded(name: str, content: bytes, content_type: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type)


def valid_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1, 1), color=(20, 120, 80)).save(buffer, format="PNG")
    return buffer.getvalue()


def valid_pdf() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def grant(user, *specs: tuple[str, str]) -> None:
    for app_label, codename in specs:
        permission = Permission.objects.get(
            content_type__app_label=app_label,
            codename=codename,
        )
        user.user_permissions.add(permission)
