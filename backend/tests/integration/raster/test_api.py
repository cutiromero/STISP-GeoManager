import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.audit.models import OperationLog
from apps.catalog.models import DataResource, MapLayer
from apps.core.config import load_project_config
from apps.raster.models import RasterDataset
from apps.raster.services import (
    RasterTileOutsideExtent,
    scan_unprocessed_source_files,
    validate_raster_pixel_size,
    validate_raster_upload_size,
)


class RasterPermissionApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="raster-user", password="pass12345"
        )
        self.client.force_login(self.user)

    def test_private_render_async_requires_raster_load_permission(self):
        from apps.projects.models import Project, ProjectMembership

        project = Project.objects.create(name="私有项目", code="private-render")
        ProjectMembership.objects.create(project=project, user=self.user)
        response = self.client.post(
            "/api/raster/render/async/",
            data={"datasetId": 1, "rulesMode": "default"},
            content_type="application/json",
            HTTP_X_PROJECT_ID=str(project.pk),
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("当前角色“未分配角色”无权限", response.json()["detail"])

    def test_default_render_does_not_require_custom_symbolization_permission(self):
        grant(self.user, ("core", "load_raster_layer"))

        response = self.client.post(
            "/api/raster/render/async/",
            data={"datasetId": 1, "rulesMode": "default"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "缺少 layerId 或 datasetId")

    def test_custom_render_requires_custom_symbolization_permission(self):
        grant(self.user, ("core", "load_raster_layer"))

        response = self.client.post(
            "/api/raster/render/async/",
            data={
                "datasetId": 1,
                "rulesMode": "custom",
                "rules": {"mode": "gray"},
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("当前角色“未分配角色”无权限", response.json()["detail"])

    def test_sync_categorical_render_builds_complete_pyramid_before_response(self):
        grant(self.user, ("core", "load_raster_layer"))
        resource = DataResource.objects.create(
            name="LUCC",
            code="sync-lucc-resource",
            data_type=DataResource.DataType.RASTER,
            status=DataResource.Status.ACTIVE,
            maintainer=self.user,
        )
        layer = MapLayer.objects.create(
            name="LUCC",
            code="sync-lucc-layer",
            layer_type=MapLayer.LayerType.RASTER,
            data_resource=resource,
            is_active=True,
            raster_rules={"mode": "unique", "bands": [1]},
        )
        dataset = RasterDataset.objects.create(
            name="LUCC",
            code="sync-lucc-dataset",
            source_relative_path="sync-lucc.tif",
            processed_relative_path="sync-lucc.cog.tif",
            data_resource=resource,
            map_layer=layer,
            raster_kind=RasterDataset.RasterKind.CATEGORICAL,
            resampling="nearest",
            processed_gdalinfo={
                "bands": [{"band": 1, "type": "Byte", "min": 1, "max": 8}]
            },
            default_rules={"mode": "unique", "bands": [1]},
            band_count=1,
            status=RasterDataset.Status.READY,
        )
        render_result = {
            "delivery": "xyz",
            "datasetId": dataset.id,
            "layerId": layer.id,
            "styleHash": "complete-lucc-style",
            "tileUrl": "/api/raster/tiles/1/complete-lucc-style/{z}/{x}/{y}.png",
            "minZoom": 0,
            "maxZoom": 16,
            "tileSampling": "nearest",
            "status": "ready",
            "bounds3857": [],
            "bounds4326": [],
            "imageCoordinates": [],
            "rules": dataset.default_rules,
        }

        with (
            patch("apps.raster.views.register_tile_style", return_value=render_result),
            patch("apps.raster.views.build_static_xyz_tile_pyramid") as build_pyramid,
        ):
            response = self.client.post(
                "/api/raster/render/",
                data={"layerId": layer.id, "rulesMode": "default"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["styleHash"], "complete-lucc-style")
        build_pyramid.assert_called_once_with(dataset, "complete-lucc-style")

    def test_render_async_denies_inactive_default_resource(self):
        grant(self.user, ("core", "load_raster_layer"))
        resource = DataResource.objects.create(
            name="受限栅格资源",
            code="restricted-raster-resource",
            data_type=DataResource.DataType.RASTER,
            status=DataResource.Status.INACTIVE,
        )
        restricted_group = Group.objects.create(name="外部协作组")
        resource.access_groups.add(restricted_group)
        dataset = self._dataset("restricted-dataset", resource)

        response = self.client.post(
            "/api/raster/render/async/",
            data={"datasetId": dataset.id, "rulesMode": "default"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "无权访问该数据资源")

    def test_default_datasets_are_public_regardless_of_legacy_group(self):
        grant(self.user, ("core", "browse_data"))
        public_resource = DataResource.objects.create(
            name="公开栅格资源",
            code="public-raster-resource",
            data_type=DataResource.DataType.RASTER,
            status=DataResource.Status.ACTIVE,
            maintainer=self.user,
        )
        restricted_resource = DataResource.objects.create(
            name="受限栅格资源",
            code="restricted-raster-list-resource",
            data_type=DataResource.DataType.RASTER,
            status=DataResource.Status.ACTIVE,
        )
        restricted_group = Group.objects.create(name="受限组")
        restricted_resource.access_groups.add(restricted_group)
        self._dataset("public-dataset", public_resource)
        self._dataset("hidden-dataset", restricted_resource)

        response = self.client.get("/api/raster/datasets/")

        self.assertEqual(response.status_code, 200)
        names = [item["name"] for item in response.json()["items"]]
        self.assertEqual(set(names), {"hidden-dataset", "public-dataset"})

    def test_superadmin_datasets_include_linked_resources_in_selected_project(self):
        from apps.core.initialization import SUPERADMIN_GROUP_NAME
        from apps.projects.context import ProjectScope, project_scope
        from apps.projects.models import Project

        group, _ = Group.objects.get_or_create(name=SUPERADMIN_GROUP_NAME)
        self.user.groups.add(group)
        project = Project.objects.create(name="栅格项目", code="raster-admin-project")
        other_project = Project.objects.create(
            name="其他项目", code="raster-admin-other"
        )
        with project_scope(ProjectScope((project.pk,), project.pk)):
            visible_ids = set()
            for code, private, status in (
                ("admin-shared", False, DataResource.Status.ACTIVE),
                ("admin-private", True, DataResource.Status.ACTIVE),
                ("admin-inactive", False, DataResource.Status.INACTIVE),
            ):
                resource = DataResource.objects.create(
                    name=code,
                    code=code,
                    data_type=DataResource.DataType.RASTER,
                    owner_only=private,
                    status=status,
                )
                visible_ids.add(self._dataset(code, resource).pk)
            visible_ids.add(self._dataset("admin-unlinked", None).pk)
        with project_scope(ProjectScope((other_project.pk,), other_project.pk)):
            self._dataset("admin-other-project", None)

        for superuser in (False, True):
            with self.subTest(is_superuser=superuser):
                self.user.is_superuser = superuser
                self.user.save(update_fields=["is_superuser"])
                response = self.client.get(
                    "/api/raster/datasets/", HTTP_X_PROJECT_ID=str(project.pk)
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    {item["id"] for item in response.json()["items"]}, visible_ids
                )

    def test_dataset_list_preserves_member_and_platform_admin_privacy(self):
        from apps.core.initialization import PLATFORM_ADMIN_GROUP_NAME
        from apps.projects.context import ProjectScope, project_scope
        from apps.projects.models import Project, ProjectMembership

        grant(self.user, ("core", "browse_data"))
        other_user = get_user_model().objects.create_user(username="raster-owner")
        project = Project.objects.create(name="私有栅格", code="raster-private-list")
        membership = ProjectMembership.objects.create(project=project, user=self.user)
        with project_scope(ProjectScope((project.pk,), project.pk)):
            visible_ids = {self._dataset("member-unlinked", None).pk}
            for code, owner, private, status, visible in (
                ("member-shared", other_user, False, DataResource.Status.ACTIVE, True),
                ("member-own", self.user, True, DataResource.Status.ACTIVE, True),
                ("member-private", other_user, True, DataResource.Status.ACTIVE, False),
                (
                    "member-inactive",
                    other_user,
                    False,
                    DataResource.Status.INACTIVE,
                    False,
                ),
            ):
                resource = DataResource.objects.create(
                    name=code,
                    code=code,
                    data_type=DataResource.DataType.RASTER,
                    maintainer=owner,
                    owner_only=private,
                    status=status,
                )
                dataset = self._dataset(code, resource)
                if visible:
                    visible_ids.add(dataset.pk)

        for role in (None, PLATFORM_ADMIN_GROUP_NAME):
            with self.subTest(role=role):
                if role:
                    group, _ = Group.objects.get_or_create(name=role)
                    self.user.groups.add(group)
                response = self.client.get(
                    "/api/raster/datasets/", HTTP_X_PROJECT_ID=str(project.pk)
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    {item["id"] for item in response.json()["items"]}, visible_ids
                )

        membership.delete()
        response = self.client.get(
            "/api/raster/datasets/", HTTP_X_PROJECT_ID=str(project.pk)
        )
        self.assertEqual(response.status_code, 404)

    def test_scan_endpoint_does_not_write_operation_log(self):
        grant(self.user, ("raster", "manage_raster_dataset"))
        job = SimpleNamespace(
            as_dict=lambda: {
                "id": "scan-job-1",
                "type": "scan",
                "status": "pending",
                "progress": 0,
                "messages": [],
                "result": None,
                "error": "",
            }
        )

        with patch("apps.raster.views.start_scan_job", return_value=job):
            response = self.client.post(
                "/api/raster/scan/", data={}, content_type="application/json"
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["id"], "scan-job-1")
        self.assertFalse(
            OperationLog.objects.filter(
                module="栅格管理", action="发起栅格目录扫描"
            ).exists()
        )

    def test_scan_endpoint_rejects_browse_only_user(self):
        grant(self.user, ("core", "browse_data"))

        response = self.client.post(
            "/api/raster/scan/", data={}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 403)

    def test_import_endpoint_accepts_uploaded_raster_and_starts_job(self):
        grant(self.user, ("raster", "manage_raster_dataset"))
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._config(Path(tmpdir))
            job = SimpleNamespace(
                id="import-job-1",
                as_dict=lambda: {
                    "id": "import-job-1",
                    "kind": "import",
                    "status": "queued",
                    "progressPercent": 0,
                    "messages": [],
                    "result": None,
                    "error": "",
                    "startedAt": 1,
                    "finishedAt": None,
                },
            )
            with override_settings(PROJECT_CONFIG=config):
                with (
                    patch(
                        "apps.raster.services.importer.gdalinfo_json",
                        return_value={"size": [256, 128]},
                    ),
                    patch(
                        "apps.raster.views.start_import_job", return_value=job
                    ) as start_import_job,
                ):
                    response = self.client.post(
                        "/api/raster/import/",
                        data={
                            "name": "NDVI 影像",
                            "file": SimpleUploadedFile(
                                "ndvi.tif",
                                b"fake raster bytes",
                                content_type="image/tiff",
                            ),
                        },
                        HTTP_X_PROJECT_ID="1",
                    )

            self.assertEqual(response.status_code, 202)
            payload = response.json()
            self.assertEqual(payload["id"], "import-job-1")
            saved_path = Path(start_import_job.call_args.args[0])
            self.assertTrue(saved_path.exists())
            self.assertEqual(saved_path.read_bytes(), b"fake raster bytes")
            self.assertEqual(saved_path.suffix, ".tif")
            self.assertIn("raster/original/uploaded", saved_path.as_posix())
            self.assertNotIn("ndvi", saved_path.name)
            self.assertEqual(start_import_job.call_args.kwargs["name"], "NDVI 影像")
            self.assertTrue(
                start_import_job.call_args.kwargs["cleanup_upload_on_failure"]
            )

    def test_import_endpoint_uses_original_upload_stem_when_name_is_empty(self):
        grant(self.user, ("raster", "manage_raster_dataset"))
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._config(Path(tmpdir))
            job = SimpleNamespace(
                id="import-job-2",
                as_dict=lambda: {
                    "id": "import-job-2",
                    "kind": "import",
                    "status": "queued",
                    "progressPercent": 0,
                    "messages": [],
                    "result": None,
                    "error": "",
                    "startedAt": 1,
                    "finishedAt": None,
                },
            )
            with override_settings(PROJECT_CONFIG=config):
                with (
                    patch(
                        "apps.raster.services.importer.gdalinfo_json",
                        return_value={"size": [256, 128]},
                    ),
                    patch(
                        "apps.raster.views.start_import_job", return_value=job
                    ) as start_import_job,
                ):
                    response = self.client.post(
                        "/api/raster/import/",
                        data={
                            "file": SimpleUploadedFile(
                                "Traim.tif",
                                b"fake raster bytes",
                                content_type="image/tiff",
                            ),
                        },
                        HTTP_X_PROJECT_ID="1",
                    )

            self.assertEqual(response.status_code, 202)
            self.assertEqual(start_import_job.call_args.kwargs["name"], "Traim")
            self.assertTrue(
                start_import_job.call_args.kwargs["cleanup_upload_on_failure"]
            )
            saved_path = Path(start_import_job.call_args.args[0])
            self.assertRegex(saved_path.name, r"^[0-9a-f]{32}\.tif$")
            self.assertNotIn("Traim", saved_path.name)

    def test_import_endpoint_rejects_uploaded_raster_over_size_limit(self):
        grant(self.user, ("raster", "manage_raster_dataset"))
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._config(Path(tmpdir), upload_max_mb=1)
            with override_settings(PROJECT_CONFIG=config):
                with patch("apps.raster.views.start_import_job") as start_import_job:
                    response = self.client.post(
                        "/api/raster/import/",
                        data={
                            "file": SimpleUploadedFile(
                                "large.tif",
                                b"x" * (1024 * 1024 + 1),
                                content_type="image/tiff",
                            ),
                        },
                        HTTP_X_PROJECT_ID="1",
                    )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"], "栅格文件大小不能超过 1 MB")
            start_import_job.assert_not_called()

    def test_upload_size_validation_uses_latest_toml_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._config(Path(tmpdir), upload_max_mb=1)
            updated_text = config.config_path.read_text(encoding="utf-8").replace(
                "upload_max_mb = 1", "upload_max_mb = 2"
            )
            config.config_path.write_text(updated_text, encoding="utf-8")
            uploaded_file = SimpleUploadedFile(
                "latest-limit.tif",
                b"x",
                content_type="image/tiff",
            )
            uploaded_file.size = 2 * 1024 * 1024 - 1

            with override_settings(PROJECT_CONFIG=config):
                validate_raster_upload_size(uploaded_file)

    def test_import_endpoint_rejects_uploaded_raster_over_pixel_limit(self):
        grant(self.user, ("raster", "manage_raster_dataset"))
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._config(Path(tmpdir), max_raster_side_pixels=9000)
            with override_settings(PROJECT_CONFIG=config):
                with (
                    patch(
                        "apps.raster.services.importer.gdalinfo_json",
                        return_value={"size": [9001, 9000]},
                    ),
                    patch("apps.raster.views.start_import_job") as start_import_job,
                ):
                    response = self.client.post(
                        "/api/raster/import/",
                        data={
                            "file": SimpleUploadedFile(
                                "wide.tif",
                                b"fake raster bytes",
                                content_type="image/tiff",
                            ),
                        },
                        HTTP_X_PROJECT_ID="1",
                    )

            self.assertEqual(response.status_code, 400)
            self.assertIn("栅格单边长度不能超过 9000 像素", response.json()["detail"])
            start_import_job.assert_not_called()

    def test_pixel_size_validation_uses_latest_toml_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._config(Path(tmpdir), max_raster_side_pixels=1000)
            updated_text = config.config_path.read_text(encoding="utf-8").replace(
                "max_raster_side_pixels = 1000", "max_raster_side_pixels = 2000"
            )
            config.config_path.write_text(updated_text, encoding="utf-8")

            with override_settings(PROJECT_CONFIG=config):
                validate_raster_pixel_size({"size": [1500, 1000]})

    def test_tile_endpoint_cache_identity_includes_renderer_version(self):
        from apps.raster.services.renderer import RASTER_RENDERER_VERSION

        grant(self.user, ("core", "load_raster_layer"))
        resource = DataResource.objects.create(
            name="tile-cache-resource",
            code="tile-cache-resource",
            data_type=DataResource.DataType.RASTER,
            status=DataResource.Status.ACTIVE,
            maintainer=self.user,
        )
        dataset = self._dataset("tile-cache-dataset", resource)

        with patch("apps.raster.views.render_xyz_tile", return_value=b"png"):
            response = self.client.get(
                f"/api/raster/tiles/{dataset.id}/style-hash/7/96/47.png"
                f"?rv={RASTER_RENDERER_VERSION}"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["ETag"],
            f'"style-hash-rv{RASTER_RENDERER_VERSION}-7-96-47"',
        )

    def test_tile_endpoint_returns_no_content_for_tiles_outside_extent(self):
        grant(self.user, ("core", "load_raster_layer"))
        resource = DataResource.objects.create(
            name="栅格资源",
            code="tile-raster-resource",
            data_type=DataResource.DataType.RASTER,
            status=DataResource.Status.ACTIVE,
            maintainer=self.user,
        )
        dataset = self._dataset("tile-dataset", resource)

        with patch(
            "apps.raster.views.render_xyz_tile",
            side_effect=RasterTileOutsideExtent("瓦片不在栅格空间范围内"),
        ):
            response = self.client.get(
                f"/api/raster/tiles/{dataset.id}/style-hash/7/96/47.png"
            )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")

    def _dataset(self, code: str, resource: DataResource | None) -> RasterDataset:
        return RasterDataset.objects.create(
            name=code,
            code=code,
            source_relative_path=f"{code}.tif",
            processed_relative_path=f"{code}.cog.tif",
            data_resource=resource,
            processed_gdalinfo={
                "bands": [{"band": 1, "type": "UInt16", "min": 0, "max": 100}]
            },
            default_rules={"mode": "gray", "bands": [1]},
            band_count=1,
            status=RasterDataset.Status.READY,
        )

    def _config(
        self,
        root: Path,
        *,
        upload_max_mb: int = 512,
        max_raster_side_pixels: int = 10000,
    ):
        config_path = root / "app.toml"
        business_root = root / "app"
        research_root = root / "research"
        config_path.write_text(
            f"""
[runtime]
debug = true
allowed_hosts = ["*"]
csrf_trusted_origins = []
waitress_host = "127.0.0.1"
waitress_port = 8000
waitress_threads = 1
disable_catalog_startup_scan = true
disable_raster_startup_scan = true

[application.system]
name = "test"
allow_registration = true

[application.storage]
app_data = "{business_root.as_posix()}"
research_data_root = "{research_root.as_posix()}"

[application.map]
default_center = [80.0, 41.5]
default_zoom = 4.5
default_basemap = "osm"
mapbox_access_token = ""

[application.limits]
upload_max_mb = {upload_max_mb}
query_result_limit = 30000
max_raster_side_pixels = {max_raster_side_pixels}

[application.raster]
symbolizer_timeout_seconds = 120
""",
            encoding="utf-8",
        )
        return load_project_config(
            config_path, program_root=Path("/opt/data-sharing-platform")
        )


class RasterScanPathTests(TestCase):
    def test_scan_only_checks_raster_original_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self._config(root)
            source_file = config.research_path("raster", "original", "source.tif")
            processed_file = config.research_path(
                "raster", "preprocessed", "processed.tif"
            )
            loose_file = config.research_path("raster", "loose.tif")
            source_file.write_bytes(b"not a real tif")
            processed_file.write_bytes(b"not a source tif")
            loose_file.write_bytes(b"not a source tif")

            with override_settings(PROJECT_CONFIG=config):
                with patch(
                    "apps.raster.services.importer.import_raster_file"
                ) as import_raster_file:
                    import_raster_file.side_effect = lambda path, progress=None: path

                    imported = scan_unprocessed_source_files()

            self.assertEqual(imported, [source_file])
            import_raster_file.assert_called_once()

    def _config(self, root: Path):
        config_path = root / "app.toml"
        business_root = root / "app"
        research_root = root / "research"
        config_path.write_text(
            f"""
[runtime]
debug = true
allowed_hosts = ["*"]
csrf_trusted_origins = []
waitress_host = "127.0.0.1"
waitress_port = 8000
waitress_threads = 1
disable_catalog_startup_scan = true
disable_raster_startup_scan = true

[application.system]
name = "测试系统"
allow_registration = true

[application.storage]
app_data = "{business_root.as_posix()}"
research_data_root = "{research_root.as_posix()}"

[application.map]
default_center = [80.0, 41.5]
default_zoom = 4.5
default_basemap = "osm"
mapbox_access_token = ""

[application.limits]
upload_max_mb = 512
query_result_limit = 30000
max_raster_side_pixels = 10000

[application.raster]
symbolizer_timeout_seconds = 120
""",
            encoding="utf-8",
        )
        return load_project_config(
            config_path, program_root=Path("/opt/data-sharing-platform")
        )


def grant(user, *specs):
    for app_label, codename in specs:
        permission = Permission.objects.get(
            content_type__app_label=app_label, codename=codename
        )
        user.user_permissions.add(permission)
