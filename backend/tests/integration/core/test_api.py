import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import tomlkit
from apps.core.map_thumbnail import ThumbnailTileError
from apps.audit.events import (
    AUTH_GUEST_LOGIN_SUCCESS,
    AUTH_LOGIN_SUCCESS,
)
from apps.audit.models import OperationLog, UserActivityHour
from apps.catalog.models import DataResource, DictionaryItem, MapLayer
from apps.core.config import (
    APP_SUBDIRS,
    ConfigValidationError,
    RESEARCH_SUBDIRS,
    load_project_config,
    metadata_database_path,
    update_runtime_application_config,
)
from apps.core.initialization import (
    DEFAULT_USER_GROUP_NAME,
    GUEST_GROUP_NAME,
    PLATFORM_ADMIN_GROUP_NAME,
    RESEARCH_USER_GROUP_NAME,
    SUPERADMIN_GROUP_NAME,
    ensure_guest_user,
    ensure_superadmin_defaults,
    platform_admin_group_permissions,
    protected_group_permissions,
    research_user_group_permissions,
    superadmin_group_locked_permissions,
)
from apps.core.models import RoleApplication, SystemSetting, UserProfile
from apps.core.runtime_config import runtime_upload_max_mb
from apps.core.storage import (
    StoragePathError,
    app_path,
    gene_data_path,
    raster_metadata_path,
    raster_processed_path,
    raster_source_path,
    research_path,
    table_data_path,
)
from apps.raster.models import RasterDataset
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from geomanager.settings import _default_csrf_trusted_origins


class FrontendSecurityHeadersTests(SimpleTestCase):
    def test_spa_document_blocks_unexpected_media_and_picture_in_picture(self):
        response = self.client.get("/resources/data/import")

        self.assertEqual(response.status_code, 200)
        policy = response["Content-Security-Policy"]
        self.assertIn("media-src 'none'", policy)
        self.assertIn("object-src 'none'", policy)
        self.assertIn(
            "img-src 'self' data: blob: https://api.mapbox.com "
            "https://tiles.openfreemap.org https://*.tile.openstreetmap.org "
            "https://*.tianditu.gov.cn",
            policy,
        )
        self.assertIn(
            "connect-src 'self' https://api.mapbox.com "
            "https://tiles.openfreemap.org https://*.tile.openstreetmap.org "
            "https://*.tianditu.gov.cn",
            policy,
        )
        self.assertEqual(
            response["Permissions-Policy"],
            "autoplay=(), picture-in-picture=()",
        )

    def test_json_api_response_does_not_receive_document_only_headers(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Content-Security-Policy", response)
        self.assertNotIn("Permissions-Policy", response)


class BootstrapApiTests(TestCase):
    def test_bootstrap_returns_public_runtime_settings(self):
        SystemSetting.objects.update_or_create(
            pk=1, defaults={"allow_registration": False}
        )

        response = self.client.get("/api/bootstrap/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("systemName", payload)
        self.assertFalse(payload["allowRegistration"])
        self.assertIn("map", payload)
        self.assertIn("tiandituAccessToken", payload["map"])

    def test_bootstrap_falls_back_to_loaded_upload_limit_after_unsafe_hot_edit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    "upload_max_mb = 512", "upload_max_mb = 1025"
                ),
                encoding="utf-8",
            )

            with override_settings(PROJECT_CONFIG=config):
                response = self.client.get("/api/bootstrap/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["limits"]["uploadMaxMb"], 512)

    def test_bootstrap_returns_configured_tianditu_browser_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research").replace(
                    'mapbox_access_token = ""',
                    'mapbox_access_token = ""\n'
                    'tianditu_access_token = "0123456789abcdef0123456789abcdef"',
                ),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))

            with override_settings(PROJECT_CONFIG=config):
                response = self.client.get("/api/bootstrap/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["map"]["tiandituAccessToken"],
            "0123456789abcdef0123456789abcdef",
        )

    def test_bootstrap_hides_unsafe_credentials_from_hot_edited_toml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research").replace(
                    'mapbox_access_token = ""',
                    'mapbox_access_token = "pk.test-public-token"\n'
                    'tianditu_access_token = "0123456789abcdef0123456789abcdef"',
                ),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'mapbox_access_token = "pk.test-public-token"',
                    'mapbox_access_token = "sk.test-private-token"',
                ),
                encoding="utf-8",
            )

            with override_settings(PROJECT_CONFIG=config):
                response = self.client.get("/api/bootstrap/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["map"]["mapboxAccessToken"], "")
        self.assertEqual(
            response.json()["map"]["tiandituAccessToken"],
            "0123456789abcdef0123456789abcdef",
        )
        self.assertEqual(response.json()["map"]["defaultBasemap"], "osm")

    def test_bootstrap_registration_fallback_uses_latest_toml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    "allow_registration = true", "allow_registration = false"
                ),
                encoding="utf-8",
            )

            with override_settings(PROJECT_CONFIG=config):
                response = self.client.get("/api/bootstrap/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["allowRegistration"])

    def test_bootstrap_upgrades_previous_canonical_platform_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research").replace(
                    'name = "测试系统"',
                    'name = "全球胡杨林生态系统保护数据共享平台"',
                ),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))

            with override_settings(PROJECT_CONFIG=config):
                response = self.client.get("/api/bootstrap/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["systemName"],
            "时空智能服务平台",
        )


class MapThumbnailTileApiTests(TestCase):
    def test_thumbnail_tile_is_served_from_same_origin_and_cached(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(
                    root / "app",
                    root / "research",
                ),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))

            with (
                override_settings(PROJECT_CONFIG=config),
                patch(
                    "apps.core.map_thumbnail.fetch_tile",
                    return_value=(b"png-data", "image/png"),
                ) as fetch_tile,
            ):
                response = self.client.get("/api/map/thumbnail-tiles/3/4/2.png")
                cached_response = self.client.get("/api/map/thumbnail-tiles/3/4/2.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["Cache-Control"], "public, max-age=86400")
        self.assertEqual(response.content, b"png-data")
        self.assertEqual(cached_response.content, b"png-data")
        fetch_tile.assert_called_once()

    def test_thumbnail_tile_preserves_cached_image_content_type(self):
        jpeg_data = b"\xff\xd8\xff\xe0cached-jpeg"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(
                    root / "app",
                    root / "research",
                ),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))

            with (
                override_settings(PROJECT_CONFIG=config),
                patch(
                    "apps.core.map_thumbnail.fetch_tile",
                    return_value=(jpeg_data, "image/jpeg"),
                ) as fetch_tile,
            ):
                response = self.client.get("/api/map/thumbnail-tiles/3/4/2.png")
                cached_response = self.client.get("/api/map/thumbnail-tiles/3/4/2.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(cached_response["Content-Type"], "image/jpeg")
        self.assertEqual(cached_response.content, jpeg_data)
        fetch_tile.assert_called_once()

    def test_thumbnail_tile_returns_generated_image_when_source_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(
                    root / "app",
                    root / "research",
                ),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))

            with (
                override_settings(PROJECT_CONFIG=config),
                patch(
                    "apps.core.map_thumbnail.fetch_tile",
                    side_effect=ThumbnailTileError("unavailable"),
                ),
            ):
                response = self.client.get("/api/map/thumbnail-tiles/3/4/2.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["Cache-Control"], "public, max-age=60")
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_thumbnail_tile_rejects_out_of_range_coordinates(self):
        response = self.client.get("/api/map/thumbnail-tiles/3/99/2.png")

        self.assertEqual(response.status_code, 400)


class LoginOverviewApiTests(TestCase):
    def test_login_overview_returns_public_platform_summary_without_auth(self):
        DataResource.objects.create(
            name="胡杨林分布矢量",
            code="poplar-vector",
            data_type=DataResource.DataType.VECTOR,
            spatial_extent="塔里木河流域",
            storage_path="private/vector.gpkg",
        )
        DataResource.objects.create(
            name="停用数据",
            code="inactive-resource",
            data_type=DataResource.DataType.TABLE,
            status=DataResource.Status.INACTIVE,
        )
        DictionaryItem.objects.create(
            dict_type=DictionaryItem.DictType.REGION,
            code="tarim",
            name="塔里木河流域",
        )
        MapLayer.objects.create(
            name="样方监测点",
            code="monitoring-sites",
            layer_type=MapLayer.LayerType.VECTOR,
            geometry_type=MapLayer.GeometryType.POINT,
            is_active=True,
            source_path="private-layer",
        )
        MapLayer.objects.create(
            name="停用点图层",
            code="inactive-points",
            layer_type=MapLayer.LayerType.VECTOR,
            geometry_type=MapLayer.GeometryType.POINT,
            is_active=False,
        )

        response = self.client.get("/api/login/overview/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["platform"]["chineseName"],
            "时空智能服务平台",
        )
        self.assertEqual(
            payload["platform"]["englishName"],
            "Spatiotemporal Intelligence Service Platform",
        )
        self.assertEqual(payload["platform"]["abbreviation"], "STISP")
        self.assertEqual(
            payload["platform"]["edition"],
            "STISP · Spatiotemporal Services Edition",
        )
        from django.conf import settings
        import tomllib

        with (settings.BASE_DIR / "pyproject.toml").open("rb") as file:
            version = tomllib.load(file)["project"]["version"]
        self.assertEqual(payload["platform"]["version"], f"v{version}")
        metrics = {item["id"]: item for item in payload["metrics"]}
        self.assertEqual(metrics["dataResources"]["value"], 1)
        self.assertEqual(metrics["thematicLayers"]["value"], 1)
        self.assertEqual(metrics["monitoringSites"]["value"], 1)
        self.assertEqual(metrics["coveredBasins"]["value"], 1)
        self.assertEqual(metrics["dataResources"]["displayValue"], "1")
        self.assertEqual(payload["serviceStatus"]["nodeSummary"]["total"], 3)
        self.assertEqual(payload["serviceStatus"]["nodeSummary"]["warning"], 0)
        encoded_payload = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("storage_path", encoded_payload)
        self.assertNotIn("private/vector.gpkg", encoded_payload)
        self.assertNotIn("private-layer", encoded_payload)

    def test_login_overview_system_name_uses_latest_toml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'name = "测试系统"', 'name = "运行期更新系统"'
                ),
                encoding="utf-8",
            )

            with override_settings(PROJECT_CONFIG=config):
                response = self.client.get("/api/login/overview/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["platform"]["chineseName"], "运行期更新系统")

    def test_login_overview_reports_warning_when_catalog_is_empty(self):
        response = self.client.get("/api/login/overview/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        services = {
            service["id"]: service for service in payload["serviceStatus"]["services"]
        }
        self.assertEqual(services["resourceCatalog"]["status"], "warning")
        self.assertEqual(services["layerService"]["status"], "warning")
        self.assertEqual(payload["serviceStatus"]["nodeSummary"]["warning"], 2)

    def test_login_overview_honors_english_accept_language(self):
        response = self.client.get("/api/login/overview/", HTTP_ACCEPT_LANGUAGE="en-US")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["hero"]["badge"], "Ecological Intelligent Monitoring Platform"
        )
        self.assertEqual(payload["metrics"][0]["label"], "Data resources")
        self.assertEqual(payload["serviceStatus"]["title"], "Platform service status")
        self.assertEqual(
            payload["serviceStatus"]["nodeSummary"]["legend"][0]["label"],
            "Normal",
        )


class CsrfSettingsTests(SimpleTestCase):
    def test_debug_defaults_trust_vite_dev_origins_with_wildcard_allowed_hosts(self):
        origins = _default_csrf_trusted_origins(["*"], debug=True)

        self.assertIn("http://127.0.0.1:5173", origins)
        self.assertIn("http://localhost:5173", origins)
        self.assertNotIn("http://*", origins)


class AdminSettingsApiTests(TestCase):
    def test_settings_get_falls_back_after_unsafe_upload_limit_hot_edit(self):
        user = get_user_model().objects.create_user(
            username="settings-limit-hot-edit-admin", password="pass12345"
        )
        grant(user, ("core", "manage_system_settings"))
        self.client.force_login(user)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    "upload_max_mb = 512", "upload_max_mb = 1025"
                ),
                encoding="utf-8",
            )

            with override_settings(PROJECT_CONFIG=config):
                response = self.client.get("/api/admin/settings/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["limits"]["uploadMaxMb"], 512)

    def test_settings_get_hides_unsafe_credentials_from_hot_edited_toml(self):
        user = get_user_model().objects.create_user(
            username="settings-hot-edit-admin", password="pass12345"
        )
        grant(user, ("core", "manage_system_settings"))
        self.client.force_login(user)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research").replace(
                    'mapbox_access_token = ""',
                    'mapbox_access_token = "pk.test-public-token"\n'
                    'tianditu_access_token = "0123456789abcdef0123456789abcdef"',
                ),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'tianditu_access_token = "0123456789abcdef0123456789abcdef"',
                    'tianditu_access_token = "not-a-browser-key"',
                ),
                encoding="utf-8",
            )

            with override_settings(PROJECT_CONFIG=config):
                response = self.client.get("/api/admin/settings/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["map"]["mapboxAccessToken"],
            "pk.test-public-token",
        )
        self.assertEqual(response.json()["map"]["tiandituAccessToken"], "")
        self.assertEqual(response.json()["map"]["defaultBasemap"], "osm")

    def test_tianditu_browser_token_can_be_read_updated_and_cleared(self):
        user = get_user_model().objects.create_user(
            username="settings-tianditu-admin", password="pass12345"
        )
        grant(user, ("core", "manage_system_settings"))
        self.client.force_login(user)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))

            with override_settings(
                PROJECT_CONFIG=config,
                PROGRAM_ROOT=Path("/opt/app"),
            ):
                initial = self.client.get("/api/admin/settings/")
                updated = self.client.post(
                    "/api/admin/settings/",
                    data=json.dumps(
                        {
                            "map": {
                                "tiandituAccessToken": (
                                    "  0123456789abcdef0123456789abcdef  "
                                )
                            }
                        }
                    ),
                    content_type="application/json",
                )
                cleared = self.client.post(
                    "/api/admin/settings/",
                    data=json.dumps({"map": {"tiandituAccessToken": ""}}),
                    content_type="application/json",
                )

            persisted = tomlkit.parse(config_path.read_text(encoding="utf-8"))

        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json()["map"]["tiandituAccessToken"], "")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(
            updated.json()["map"]["tiandituAccessToken"],
            "0123456789abcdef0123456789abcdef",
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["map"]["tiandituAccessToken"], "")
        self.assertEqual(persisted["application"]["map"]["tianditu_access_token"], "")

    def test_map_settings_reject_private_or_malformed_browser_credentials(self):
        user = get_user_model().objects.create_user(
            username="settings-map-credential-admin", password="pass12345"
        )
        grant(user, ("core", "manage_system_settings"))
        self.client.force_login(user)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))

            with override_settings(
                PROJECT_CONFIG=config, PROGRAM_ROOT=Path("/opt/app")
            ):
                private_mapbox = self.client.post(
                    "/api/admin/settings/",
                    data=json.dumps(
                        {"map": {"mapboxAccessToken": "sk.test-private-token"}}
                    ),
                    content_type="application/json",
                )
                malformed_tianditu = self.client.post(
                    "/api/admin/settings/",
                    data=json.dumps(
                        {"map": {"tiandituAccessToken": "not-a-browser-key"}}
                    ),
                    content_type="application/json",
                )

        self.assertEqual(private_mapbox.status_code, 400)
        self.assertIn("pk.*", private_mapbox.json()["detail"])
        self.assertEqual(malformed_tianditu.status_code, 400)
        self.assertIn("32 位浏览器 Key", malformed_tianditu.json()["detail"])

    def test_map_settings_normalize_the_historical_osm_default(self):
        user = get_user_model().objects.create_user(
            username="settings-map-default-admin", password="pass12345"
        )
        grant(user, ("core", "manage_system_settings"))
        self.client.force_login(user)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))

            with override_settings(
                PROJECT_CONFIG=config, PROGRAM_ROOT=Path("/opt/app")
            ):
                response = self.client.post(
                    "/api/admin/settings/",
                    data=json.dumps({"map": {"defaultBasemap": "osm"}}),
                    content_type="application/json",
                )

            persisted = tomlkit.parse(config_path.read_text(encoding="utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["map"]["defaultBasemap"], "satellite")
        self.assertEqual(
            persisted["application"]["map"]["default_basemap"], "satellite"
        )

    def test_map_settings_accept_tianditu_imagery_default(self):
        user = get_user_model().objects.create_user(
            username="settings-tianditu-imagery-admin", password="pass12345"
        )
        grant(user, ("core", "manage_system_settings"))
        self.client.force_login(user)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))

            with override_settings(
                PROJECT_CONFIG=config, PROGRAM_ROOT=Path("/opt/app")
            ):
                response = self.client.post(
                    "/api/admin/settings/",
                    data=json.dumps({"map": {"defaultBasemap": "tianditu-imagery"}}),
                    content_type="application/json",
                )

            persisted = tomlkit.parse(config_path.read_text(encoding="utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["map"]["defaultBasemap"], "tianditu-imagery")
        self.assertEqual(
            persisted["application"]["map"]["default_basemap"],
            "tianditu-imagery",
        )

    def test_update_upgrades_known_legacy_platform_name_before_persisting(self):
        user = get_user_model().objects.create_user(
            username="settings-brand-admin", password="pass12345"
        )
        grant(user, ("core", "manage_system_settings"))
        self.client.force_login(user)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))

            with override_settings(PROJECT_CONFIG=config):
                response = self.client.post(
                    "/api/admin/settings/",
                    data=json.dumps(
                        {"systemName": ("中亚胡杨林生态系统保护数据共享平台")}
                    ),
                    content_type="application/json",
                )

            persisted = config_path.read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["systemName"],
            "时空智能服务平台",
        )
        self.assertIn('name = "时空智能服务平台"', persisted)

    def test_update_refreshes_runtime_upload_limit_without_restart(self):
        user = get_user_model().objects.create_user(
            username="settings-upload-admin", password="pass12345"
        )
        grant(user, ("core", "manage_system_settings"))
        self.client.force_login(user)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research").replace(
                    "upload_max_mb = 512", "upload_max_mb = 64"
                ),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))

            with override_settings(
                PROJECT_CONFIG=config,
                PROGRAM_ROOT=Path("/opt/app"),
                DATA_UPLOAD_MAX_MEMORY_SIZE=64 * 1024 * 1024,
            ):
                response = self.client.post(
                    "/api/admin/settings/",
                    data=json.dumps({"limits": {"uploadMaxMb": 1024}}),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["limits"]["uploadMaxMb"], 1024)
                self.assertEqual(settings.PROJECT_CONFIG.limits.upload_max_mb, 1024)
                self.assertEqual(
                    tomlkit.parse(config_path.read_text(encoding="utf-8"))[
                        "application"
                    ]["limits"]["upload_max_mb"],
                    1024,
                )
                self.assertEqual(settings.DATA_UPLOAD_MAX_MEMORY_SIZE, 10 * 1024 * 1024)
                self.assertEqual(settings.FILE_UPLOAD_MAX_MEMORY_SIZE, 2 * 1024 * 1024)

    def test_rejects_unsafe_admin_limits_without_writing_config(self):
        user = get_user_model().objects.create_user(
            username="settings-limits-admin", password="pass12345"
        )
        grant(user, ("core", "manage_system_settings"))
        self.client.force_login(user)

        rejected_values = (
            (
                {"limits": {"uploadMaxMb": 1025}},
                "uploadMaxMb 必须是 1 到 1024 之间的整数",
            ),
            (
                {"limits": {"queryResultLimit": 10_001}},
                "queryResultLimit 必须是 100 到 10000 之间的整数",
            ),
            (
                {"limits": {"maxRasterSidePixels": 12_001}},
                "maxRasterSidePixels 必须是 1 到 12000 之间的整数",
            ),
            (
                {"raster": {"symbolizerTimeoutSeconds": 601}},
                "symbolizerTimeoutSeconds 必须是 10 到 600 之间的整数",
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))
            before = config_path.read_text(encoding="utf-8")

            with override_settings(PROJECT_CONFIG=config):
                for payload, detail in rejected_values:
                    with self.subTest(payload=payload):
                        response = self.client.post(
                            "/api/admin/settings/",
                            data=json.dumps(payload),
                            content_type="application/json",
                        )
                        self.assertEqual(response.status_code, 400)
                        self.assertEqual(response.json()["detail"], detail)
                        self.assertEqual(
                            config_path.read_text(encoding="utf-8"), before
                        )

    @patch(
        "apps.core.admin_api.update_runtime_application_config",
        side_effect=OSError("Device or resource busy"),
    )
    def test_config_write_failure_returns_json_error(self, _update_config):
        user = get_user_model().objects.create_user(
            username="settings-write-admin", password="pass12345"
        )
        grant(user, ("core", "manage_system_settings"))
        self.client.force_login(user)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))

            with override_settings(PROJECT_CONFIG=config):
                response = self.client.post(
                    "/api/admin/settings/",
                    data=json.dumps({"limits": {"uploadMaxMb": 64}}),
                    content_type="application/json",
                )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"],
            "系统配置写入失败，请检查配置目录是否可写，并将宿主机配置目录挂载到 /config",
        )

    def test_rejects_invalid_map_numbers_without_writing_config(self):
        user = get_user_model().objects.create_user(
            username="settings-admin", password="pass12345"
        )
        grant(user, ("core", "manage_system_settings"))
        self.client.force_login(user)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))
            before = config_path.read_text(encoding="utf-8")

            with override_settings(PROJECT_CONFIG=config):
                center_response = self.client.post(
                    "/api/admin/settings/",
                    data=json.dumps({"map": {"defaultCenter": ["east", 41.5]}}),
                    content_type="application/json",
                )
                zoom_response = self.client.post(
                    "/api/admin/settings/",
                    data=json.dumps({"map": {"defaultZoom": "far"}}),
                    content_type="application/json",
                )

            self.assertEqual(center_response.status_code, 400)
            self.assertEqual(
                center_response.json()["detail"],
                "defaultCenter[0] 必须是有效数字",
            )
            self.assertEqual(zoom_response.status_code, 400)
            self.assertEqual(
                zoom_response.json()["detail"], "defaultZoom 必须是有效数字"
            )
            self.assertEqual(config_path.read_text(encoding="utf-8"), before)

    def test_rejects_non_boolean_registration_flag(self):
        user = get_user_model().objects.create_user(
            username="settings-bool-admin", password="pass12345"
        )
        grant(user, ("core", "manage_system_settings"))
        self.client.force_login(user)

        response = self.client.post(
            "/api/admin/settings/",
            data=json.dumps({"allowRegistration": "false"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "allowRegistration 必须是布尔值")


class ApiJsonErrorTests(TestCase):
    def test_authenticated_api_returns_json_401_instead_of_login_redirect(self):
        response = self.client.get("/api/admin/workspaces/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json()["detail"], "请先登录")

    def test_csrf_failure_returns_standard_json_error(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post("/api/auth/logout/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json()["detail"], "CSRF 验证失败")

    def test_api_errors_honor_english_accept_language(self):
        response = self.client.get(
            "/api/admin/workspaces/", HTTP_ACCEPT_LANGUAGE="en-US"
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Sign in first")


class RegistrationApiTests(TestCase):
    def test_login_writes_dashboard_compatible_audit_log(self):
        user = get_user_model().objects.create_user(
            username="login-user", password="pass12345"
        )

        response = self.client.post(
            "/api/auth/login/",
            data=json.dumps(
                {
                    "username": "login-user",
                    "password": "pass12345",
                    "remember": True,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["user"]
        self.assertTrue(payload["isActive"])
        self.assertEqual(payload["directPermissions"], [])
        self.assertIn("effectivePermissions", payload)
        self.assertTrue(
            OperationLog.objects.filter(
                user=user,
                event_code=AUTH_LOGIN_SUCCESS,
                status="success",
            ).exists()
        )

    def test_auth_me_reports_data_create_and_data_overview_permissions(self):
        user = get_user_model().objects.create_user(
            username="permission-flags-user", password="pass12345"
        )
        grant(user, ("catalog", "add_dataresource"), ("core", "view_data_overview"))
        self.client.force_login(user)

        response = self.client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        permissions = response.json()["user"]["permissions"]
        self.assertTrue(permissions["canUploadData"])
        self.assertTrue(permissions["canCreateDataResources"])
        self.assertTrue(permissions["canViewDataOverview"])
        self.assertTrue(permissions["canViewOwnOperationLogs"])
        self.assertFalse(permissions["canViewOperationLogs"])
        self.assertFalse(permissions["canViewSystemLogs"])
        self.assertFalse(permissions["canManageDataBackup"])

        grant(user, ("core", "view_system_logs"), ("core", "manage_data_backup"))
        response = self.client.get("/api/auth/me/")

        permissions = response.json()["user"]["permissions"]
        self.assertTrue(permissions["canViewSystemLogs"])
        self.assertFalse(permissions["canManageDataBackup"])

        superadmin, _group = ensure_superadmin_defaults()
        self.client.force_login(superadmin)
        response = self.client.get("/api/auth/me/")

        permissions = response.json()["user"]["permissions"]
        self.assertTrue(permissions["canManageDataBackup"])

    def test_registered_user_after_initialization_is_standard_user(self):
        SystemSetting.objects.update_or_create(
            pk=1, defaults={"allow_registration": True}
        )
        ensure_superadmin_defaults()

        response = self.client.post(
            "/api/auth/register/",
            data=json.dumps(
                {
                    "username": "researcher",
                    "email": "researcher@example.local",
                    "password": "123456",
                    "passwordConfirm": "123456",
                    "accountPurpose": "standard",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        user = get_user_model().objects.get(username="researcher")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(
            Group.objects.filter(
                name=SUPERADMIN_GROUP_NAME,
                permissions__codename="manage_auth",
            ).exists()
        )
        self.assertTrue(user.groups.filter(name=DEFAULT_USER_GROUP_NAME).exists())
        self.assertFalse(user.groups.filter(name=GUEST_GROUP_NAME).exists())
        self.assertEqual(user.profile.normalized_email, "researcher@example.local")
        self.assertIsNone(response.json()["roleApplication"])

    def test_registration_requires_valid_unique_normalized_email(self):
        SystemSetting.objects.update_or_create(
            pk=1, defaults={"allow_registration": True}
        )

        missing_response = self.client.post(
            "/api/auth/register/",
            data=json.dumps(
                {
                    "username": "missing-email",
                    "password": "StrongPass12345",
                    "passwordConfirm": "StrongPass12345",
                    "accountPurpose": "standard",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(missing_response.status_code, 400)
        self.assertEqual(missing_response.json()["detail"], "请输入邮箱")

        first_response = self.client.post(
            "/api/auth/register/",
            data=json.dumps(
                {
                    "username": "normalized-email",
                    "email": "  Person@Example.COM  ",
                    "password": "StrongPass12345",
                    "passwordConfirm": "StrongPass12345",
                    "accountPurpose": "standard",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(first_response.status_code, 200)
        user = get_user_model().objects.get(username="normalized-email")
        self.assertEqual(user.email, "person@example.com")
        self.assertEqual(user.profile.normalized_email, "person@example.com")

        self.client.logout()
        duplicate_response = self.client.post(
            "/api/auth/register/",
            data=json.dumps(
                {
                    "username": "duplicate-email",
                    "email": "PERSON@example.com",
                    "password": "StrongPass12345",
                    "passwordConfirm": "StrongPass12345",
                    "accountPurpose": "standard",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(duplicate_response.status_code, 400)
        self.assertEqual(duplicate_response.json()["detail"], "邮箱已被使用")

    def test_research_registration_creates_pending_application_without_elevation(self):
        SystemSetting.objects.update_or_create(
            pk=1, defaults={"allow_registration": True}
        )

        response = self.client.post(
            "/api/auth/register/",
            data=json.dumps(
                {
                    "username": "research-applicant",
                    "email": "Applicant@Example.COM",
                    "password": "StrongPass12345",
                    "passwordConfirm": "StrongPass12345",
                    "accountPurpose": "research",
                    "displayName": "张研究员",
                    "department": "生态监测组",
                    "applicationReason": "需要上传和导出长期监测数据",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        user = get_user_model().objects.get(username="research-applicant")
        application = RoleApplication.objects.get(user=user)
        self.assertEqual(user.first_name, "张研究员")
        self.assertEqual(user.profile.department, "生态监测组")
        self.assertTrue(user.groups.filter(name=DEFAULT_USER_GROUP_NAME).exists())
        self.assertFalse(user.groups.filter(name=RESEARCH_USER_GROUP_NAME).exists())
        self.assertEqual(application.status, RoleApplication.Status.PENDING)
        self.assertEqual(response.json()["roleApplication"]["status"], "pending")

    def test_superadmin_can_approve_research_application_and_replace_base_role(self):
        ensure_superadmin_defaults(create_account=False)
        manager = get_user_model().objects.create_user(
            username="research-reviewer", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"))
        manager.groups.add(Group.objects.get(name=SUPERADMIN_GROUP_NAME))
        applicant = get_user_model().objects.create_user(
            username="research-review-target",
            email="review.target@example.com",
            password="pass12345",
        )
        ordinary_group = Group.objects.get(name=DEFAULT_USER_GROUP_NAME)
        custom_group = Group.objects.create(name="项目协作组")
        applicant.groups.set([ordinary_group, custom_group])
        UserProfile.objects.create(
            user=applicant,
            normalized_email="review.target@example.com",
            department="生态监测组",
        )
        application = RoleApplication.objects.create(
            user=applicant,
            reason="需要科研数据处理权限",
        )
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/admin/role-applications/{application.id}/review/",
            data=json.dumps({"action": "approve", "reviewNote": "申请信息完整"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        applicant.refresh_from_db()
        application.refresh_from_db()
        self.assertFalse(applicant.groups.filter(name=DEFAULT_USER_GROUP_NAME).exists())
        self.assertTrue(applicant.groups.filter(name=RESEARCH_USER_GROUP_NAME).exists())
        self.assertTrue(applicant.groups.filter(name="项目协作组").exists())
        self.assertEqual(application.status, RoleApplication.Status.APPROVED)
        self.assertEqual(application.reviewer, manager)
        self.assertEqual(response.json()["status"], "approved")

        list_response = self.client.get("/api/admin/role-applications/?status=approved")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(
            list_response.json()["items"][0]["user"]["email"],
            "review.target@example.com",
        )

    def test_guest_login_creates_dedicated_guest_user_with_public_read_permissions(
        self,
    ):
        response = self.client.post("/api/auth/guest-login/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()["user"]
        self.assertEqual(payload["username"], "guest")
        self.assertEqual(payload["displayName"], "游客")
        self.assertEqual(payload["roles"], [GUEST_GROUP_NAME])
        permissions = payload["permissions"]
        self.assertTrue(permissions["canBrowseData"])
        self.assertTrue(permissions["canQueryData"])
        self.assertTrue(permissions["canLoadVectorLayer"])
        self.assertTrue(permissions["canLoadRasterLayer"])
        self.assertTrue(permissions["canViewWorkspaces"])
        self.assertFalse(permissions["canUploadData"])
        self.assertFalse(permissions["canExportData"])
        user = get_user_model().objects.get(username="guest")
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.groups.filter(name=GUEST_GROUP_NAME).exists())
        self.assertTrue(
            OperationLog.objects.filter(
                user=user,
                event_code=AUTH_GUEST_LOGIN_SUCCESS,
                status="success",
            ).exists()
        )

    def test_auth_responses_include_required_disabled_permissions(self):
        login_user = get_user_model().objects.create_user(
            username="auth-shape-login-user", password="StrongPass12345"
        )
        grant(login_user, ("core", "browse_data"))
        UserProfile.objects.create(
            user=login_user,
            disabled_permissions=["core.browse_data"],
        )
        login_client = self.client_class()

        login_response = login_client.post(
            "/api/auth/login/",
            data=json.dumps(
                {
                    "username": login_user.username,
                    "password": "StrongPass12345",
                }
            ),
            content_type="application/json",
        )
        me_response = login_client.get("/api/auth/me/")

        guest_client = self.client_class()
        guest_response = guest_client.post("/api/auth/guest-login/")

        SystemSetting.objects.update_or_create(
            pk=1, defaults={"allow_registration": True}
        )
        register_client = self.client_class()
        register_response = register_client.post(
            "/api/auth/register/",
            data=json.dumps(
                {
                    "username": "auth-shape-registered-user",
                    "email": "auth.shape@example.com",
                    "password": "StrongPass12345",
                    "passwordConfirm": "StrongPass12345",
                    "accountPurpose": "standard",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(guest_response.status_code, 200)
        self.assertEqual(register_response.status_code, 200)
        self.assertEqual(
            login_response.json()["user"]["disabledPermissions"],
            ["core.browse_data"],
        )
        self.assertEqual(
            me_response.json()["user"]["disabledPermissions"],
            ["core.browse_data"],
        )
        self.assertEqual(guest_response.json()["user"]["disabledPermissions"], [])
        self.assertEqual(register_response.json()["user"]["disabledPermissions"], [])

    def test_guest_sessions_remain_valid_when_another_visitor_logs_in(self):
        first_visitor = self.client_class()
        second_visitor = self.client_class()

        self.assertEqual(
            first_visitor.post("/api/auth/guest-login/").status_code,
            200,
        )
        self.assertEqual(
            second_visitor.post("/api/auth/guest-login/").status_code,
            200,
        )

        first_me = first_visitor.get("/api/auth/me/")
        first_resources = first_visitor.get("/api/catalog/resources/")

        self.assertEqual(first_me.status_code, 200)
        self.assertEqual(first_me.json()["user"]["username"], "guest")
        self.assertEqual(first_resources.status_code, 200)

    def test_guest_cannot_pollute_shared_account_from_an_independent_session(self):
        first_visitor = self.client_class()
        second_visitor = self.client_class()
        self.assertEqual(first_visitor.post("/api/auth/guest-login/").status_code, 200)
        self.assertEqual(second_visitor.post("/api/auth/guest-login/").status_code, 200)
        guest = get_user_model().objects.get(username="guest")
        guest.refresh_from_db()
        guest.profile.refresh_from_db()
        password_before = guest.password
        profile_before = {
            "avatarUrl": guest.profile.avatar_url,
            "avatarData": guest.profile.avatar_data,
            "department": guest.profile.department,
            "disabledPermissions": list(guest.profile.disabled_permissions),
        }
        second_before = second_visitor.get("/api/auth/me/").json()["user"]
        log_count_before = OperationLog.objects.filter(user=guest).count()

        profile_response = first_visitor.post(
            "/api/admin/profile/update/",
            data=json.dumps(
                {
                    "displayName": "被污染的游客",
                    "email": "polluted@example.com",
                    "avatarUrl": "https://example.com/polluted.png",
                    "department": "污染部门",
                }
            ),
            content_type="application/json",
        )
        avatar_response = first_visitor.post("/api/admin/profile/avatar/", data={})
        permissions_response = first_visitor.post(
            "/api/admin/profile/permissions/",
            data=json.dumps({"disabledPermissions": ["core.browse_data"]}),
            content_type="application/json",
        )
        password_response = first_visitor.post(
            "/api/admin/profile/password/",
            data=json.dumps(
                {
                    "currentPassword": "",
                    "newPassword": "PollutedPass12345",
                    "passwordConfirm": "PollutedPass12345",
                }
            ),
            content_type="application/json",
        )
        logs_response = first_visitor.get("/api/admin/operation-logs/")

        for response in (
            profile_response,
            avatar_response,
            permissions_response,
            password_response,
            logs_response,
        ):
            with self.subTest(path=response.request["PATH_INFO"]):
                self.assertEqual(response.status_code, 403)

        guest.refresh_from_db()
        guest.profile.refresh_from_db()
        second_after = second_visitor.get("/api/auth/me/").json()["user"]
        self.assertEqual(guest.password, password_before)
        self.assertFalse(guest.has_usable_password())
        self.assertEqual(guest.first_name, "游客")
        self.assertEqual(guest.email, "")
        self.assertEqual(guest.profile.avatar_url, profile_before["avatarUrl"])
        self.assertEqual(guest.profile.avatar_data, profile_before["avatarData"])
        self.assertEqual(guest.profile.department, profile_before["department"])
        self.assertEqual(
            guest.profile.disabled_permissions,
            profile_before["disabledPermissions"],
        )
        for key in (
            "displayName",
            "email",
            "avatarUrl",
            "department",
            "disabledPermissions",
        ):
            self.assertEqual(second_after[key], second_before[key])
        self.assertFalse(second_after["permissions"]["canViewOwnOperationLogs"])
        self.assertNotIn(
            "core.view_own_operation_logs", second_after["effectivePermissions"]
        )
        self.assertEqual(
            OperationLog.objects.filter(user=guest).count(), log_count_before
        )

    def test_registration_can_be_closed_by_system_setting(self):
        SystemSetting.objects.update_or_create(
            pk=1, defaults={"allow_registration": False}
        )

        response = self.client.post(
            "/api/auth/register/",
            data=json.dumps(
                {
                    "username": "closed",
                    "password": "StrongPass12345",
                    "passwordConfirm": "StrongPass12345",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)


class FeaturePermissionTests(TestCase):
    def test_legacy_django_admin_route_is_removed(self):
        response = self.client.get("/admin2/")

        self.assertEqual(response.status_code, 404)

    def test_data_only_user_does_not_receive_admin_entry_permission(self):
        user = get_user_model().objects.create_user(
            username="data-only-user", password="pass12345"
        )
        grant(user, ("core", "browse_data"), ("core", "query_data"))
        self.client.force_login(user)

        response = self.client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["user"]["permissions"]["canAccessAdmin"])

    def test_operations_permission_enables_admin_entry(self):
        user = get_user_model().objects.create_user(
            username="operations-user", password="pass12345"
        )
        grant(user, ("core", "view_dashboard_user_card"))
        self.client.force_login(user)

        response = self.client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["user"]["permissions"]["canAccessAdmin"])

    def test_user_can_disable_only_granted_feature_permissions(self):
        user = get_user_model().objects.create_user(
            username="toggle-user", password="pass12345"
        )
        grant(user, ("core", "browse_data"))
        self.client.force_login(user)

        response = self.client.post(
            "/api/admin/profile/permissions/",
            data=json.dumps({"disabledPermissions": ["core.browse_data"]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["user"]["permissions"]["canBrowseData"])

        response = self.client.post(
            "/api/admin/profile/permissions/",
            data=json.dumps({"disabledPermissions": ["core.query_data"]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("不能关闭未授予的权限", response.json()["detail"])

    def test_group_delete_requires_empty_group(self):
        manager = get_user_model().objects.create_user(
            username="group-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "manage_feature_permissions"))
        group = Group.objects.create(name="待删除用户组")
        user = get_user_model().objects.create_user(
            username="group-member", password="pass12345"
        )
        user.groups.add(group)
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/groups/{group.id}/",
            data=json.dumps({"action": "delete"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "角色仍有关联用户，不能删除")

    def test_create_user_permission_can_create_user_when_registration_is_closed(self):
        SystemSetting.objects.update_or_create(
            pk=1, defaults={"allow_registration": False}
        )
        manager = get_user_model().objects.create_user(
            username="user-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "create_user"))
        group = Group.objects.create(name="科研辅助组")
        self.client.force_login(manager)

        response = self.client.post(
            "/api/users/",
            data=json.dumps(
                {
                    "username": "created-by-admin",
                    "password": "StrongPass12345",
                    "displayName": "后台创建用户",
                    "email": "created@example.local",
                    "department": "生态监测组",
                    "groupIds": [group.id],
                    "isActive": True,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        user = get_user_model().objects.get(username="created-by-admin")
        self.assertEqual(user.email, "created@example.local")
        self.assertEqual(user.profile.department, "生态监测组")
        self.assertEqual(user.profile.normalized_email, "created@example.local")
        self.assertTrue(user.groups.filter(id=group.id).exists())

    def test_create_user_requires_email_when_role_is_valid(self):
        manager = get_user_model().objects.create_user(
            username="user-manager-email", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "create_user"))
        group = Group.objects.create(name="邮箱必填测试组")
        self.client.force_login(manager)

        response = self.client.post(
            "/api/users/",
            data=json.dumps(
                {
                    "username": "created-without-email",
                    "groupIds": [group.id],
                    "isActive": True,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "请输入邮箱")

    def test_only_superadmin_can_assign_platform_admin_role(self):
        ensure_superadmin_defaults(create_account=False)
        platform_group = Group.objects.get(name=PLATFORM_ADMIN_GROUP_NAME)
        ordinary_group = Group.objects.get(name=DEFAULT_USER_GROUP_NAME)
        manager = get_user_model().objects.create_user(
            username="platform-role-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "create_user"))
        target = get_user_model().objects.create_user(
            username="platform-role-target", password="pass12345"
        )
        target.groups.add(ordinary_group)
        self.client.force_login(manager)

        create_response = self.client.post(
            "/api/users/",
            data=json.dumps(
                {
                    "username": "blocked-platform-admin",
                    "email": "blocked.platform@example.com",
                    "groupIds": [platform_group.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 400)
        self.assertEqual(
            create_response.json()["detail"],
            "只有超级管理员可以分配平台管理员角色",
        )

        update_response = self.client.post(
            f"/api/users/{target.id}/groups/",
            data=json.dumps({"groupIds": [platform_group.id]}),
            content_type="application/json",
        )
        self.assertEqual(update_response.status_code, 400)
        self.assertEqual(
            update_response.json()["detail"],
            "只有超级管理员可以分配平台管理员角色",
        )

    def test_regular_auth_manager_cannot_mutate_platform_admin_account(self):
        ensure_superadmin_defaults(create_account=False)
        platform_group = Group.objects.get(name=PLATFORM_ADMIN_GROUP_NAME)
        ordinary_group = Group.objects.get(name=DEFAULT_USER_GROUP_NAME)
        manager = get_user_model().objects.create_user(
            username="platform-account-blocked-manager", password="pass12345"
        )
        grant(
            manager,
            ("core", "manage_auth"),
            ("core", "manage_feature_permissions"),
        )
        target = get_user_model().objects.create_user(
            username="protected-platform-admin", password="OldPass12345"
        )
        target.groups.add(platform_group)
        password_before = target.password
        log_count_before = OperationLog.objects.count()
        self.client.force_login(manager)

        responses = (
            self.client.post(f"/api/users/{target.id}/password/reset/"),
            self.client.post(
                f"/api/users/{target.id}/",
                data=json.dumps({"isActive": False}),
                content_type="application/json",
            ),
            self.client.post(
                f"/api/users/{target.id}/",
                data=json.dumps({"action": "delete"}),
                content_type="application/json",
            ),
            self.client.post(
                f"/api/users/{target.id}/groups/",
                data=json.dumps({"groupIds": [ordinary_group.id]}),
                content_type="application/json",
            ),
            self.client.post(
                f"/api/users/{target.id}/permissions/",
                data=json.dumps({"directPermissions": ["core.query_data"]}),
                content_type="application/json",
            ),
        )

        for response in responses:
            with self.subTest(path=response.request["PATH_INFO"]):
                self.assertEqual(response.status_code, 403)
                self.assertEqual(
                    response.json()["detail"],
                    "只有超级管理员可以管理平台管理员账号",
                )
        target.refresh_from_db()
        self.assertTrue(target.is_active)
        self.assertEqual(target.password, password_before)
        self.assertEqual(list(target.groups.all()), [platform_group])
        self.assertEqual(target.user_permissions.count(), 0)
        self.assertEqual(OperationLog.objects.count(), log_count_before)

    def test_superadmin_can_mutate_platform_admin_account(self):
        superadmin, _ = ensure_superadmin_defaults()
        platform_group = Group.objects.get(name=PLATFORM_ADMIN_GROUP_NAME)
        ordinary_group = Group.objects.get(name=DEFAULT_USER_GROUP_NAME)
        target = get_user_model().objects.create_user(
            username="superadmin-managed-platform-admin",
            password="OldPass12345",
        )
        target.groups.add(platform_group)
        self.client.force_login(superadmin)

        reset_response = self.client.post(f"/api/users/{target.id}/password/reset/")
        disable_response = self.client.post(
            f"/api/users/{target.id}/",
            data=json.dumps({"isActive": False}),
            content_type="application/json",
        )
        permissions_response = self.client.post(
            f"/api/users/{target.id}/permissions/",
            data=json.dumps({"directPermissions": ["core.query_data"]}),
            content_type="application/json",
        )
        groups_response = self.client.post(
            f"/api/users/{target.id}/groups/",
            data=json.dumps({"groupIds": [platform_group.id, ordinary_group.id]}),
            content_type="application/json",
        )
        delete_response = self.client.post(
            f"/api/users/{target.id}/",
            data=json.dumps({"action": "delete"}),
            content_type="application/json",
        )

        self.assertEqual(reset_response.status_code, 200)
        self.assertEqual(disable_response.status_code, 200)
        self.assertEqual(permissions_response.status_code, 200)
        self.assertEqual(groups_response.status_code, 200)
        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(pk=target.id).exists())

    def test_guest_group_cannot_be_assigned_to_non_guest_accounts(self):
        ensure_superadmin_defaults(create_account=False)
        guest_group = Group.objects.get(name=GUEST_GROUP_NAME)
        ordinary_group = Group.objects.get(name=DEFAULT_USER_GROUP_NAME)
        manager = get_user_model().objects.create_user(
            username="guest-role-assignment-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "create_user"))
        target = get_user_model().objects.create_user(
            username="guest-role-update-target", password="pass12345"
        )
        target.groups.add(ordinary_group)
        self.client.force_login(manager)

        create_response = self.client.post(
            "/api/users/",
            data=json.dumps(
                {
                    "username": "guest-role-create-target",
                    "email": "guest.role.create@example.com",
                    "groupIds": [guest_group.id],
                }
            ),
            content_type="application/json",
        )
        update_response = self.client.post(
            f"/api/users/{target.id}/groups/",
            data=json.dumps({"groupIds": [guest_group.id]}),
            content_type="application/json",
        )

        for response in (create_response, update_response):
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"], "游客角色只能分配给游客账号")
        self.assertFalse(
            get_user_model()
            .objects.filter(username="guest-role-create-target")
            .exists()
        )
        self.assertEqual(list(target.groups.all()), [ordinary_group])

    def test_profile_email_is_normalized_and_cannot_duplicate_another_user(self):
        user = get_user_model().objects.create_user(
            username="profile-email-user",
            email="old@example.com",
            password="pass12345",
        )
        UserProfile.objects.create(user=user, normalized_email="old@example.com")
        other = get_user_model().objects.create_user(
            username="profile-email-other",
            email="used@example.com",
            password="pass12345",
        )
        UserProfile.objects.create(user=other, normalized_email="used@example.com")
        self.client.force_login(user)

        normalized_response = self.client.post(
            "/api/admin/profile/update/",
            data=json.dumps({"email": "  New.Address@Example.COM  "}),
            content_type="application/json",
        )
        self.assertEqual(normalized_response.status_code, 200)
        user.refresh_from_db()
        user.profile.refresh_from_db()
        self.assertEqual(user.email, "new.address@example.com")
        self.assertEqual(user.profile.normalized_email, "new.address@example.com")

        duplicate_response = self.client.post(
            "/api/admin/profile/update/",
            data=json.dumps({"email": "USED@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(duplicate_response.status_code, 400)
        self.assertEqual(duplicate_response.json()["detail"], "邮箱已被使用")

    def test_create_user_requires_group(self):
        manager = get_user_model().objects.create_user(
            username="user-manager-empty-group", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "create_user"))
        self.client.force_login(manager)

        response = self.client.post(
            "/api/users/",
            data=json.dumps(
                {
                    "username": "created-without-group",
                    "displayName": "无组用户",
                    "groupIds": [],
                    "isActive": True,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "角色为必选项")

    def test_manage_feature_permissions_without_create_user_cannot_create_user(self):
        manager = get_user_model().objects.create_user(
            username="permission-only-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "manage_feature_permissions"))
        self.client.force_login(manager)

        response = self.client.post(
            "/api/users/",
            data=json.dumps(
                {
                    "username": "blocked-create",
                    "password": "StrongPass12345",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "当前用户无新建用户权限")

    def test_create_user_permission_can_list_groups_for_assignment(self):
        manager = get_user_model().objects.create_user(
            username="create-user-lister", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "create_user"))
        self.client.force_login(manager)

        response = self.client.get("/api/groups/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("items", response.json())

    def test_create_user_cannot_assign_superadmin_group(self):
        manager = get_user_model().objects.create_user(
            username="create-user-protected-group", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "create_user"))
        _, protected_group = ensure_superadmin_defaults(create_account=False)
        self.client.force_login(manager)

        response = self.client.post(
            "/api/users/",
            data=json.dumps(
                {
                    "username": "blocked-protected-group",
                    "password": "StrongPass12345",
                    "groupIds": [protected_group.id],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "包含不存在的角色")

    def test_regular_user_cannot_be_assigned_to_superadmin_group(self):
        manager = get_user_model().objects.create_user(
            username="assign-protected-group-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "manage_feature_permissions"))
        target = get_user_model().objects.create_user(
            username="regular-protected-target",
            password="StrongPass12345",
        )
        _, protected_group = ensure_superadmin_defaults(create_account=False)
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/users/{target.id}/groups/",
            data=json.dumps({"groupIds": [protected_group.id]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "包含不存在的角色")

    def test_current_user_cannot_update_own_groups_from_auth_management(self):
        manager = get_user_model().objects.create_user(
            username="self-group-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"))
        group = Group.objects.create(name="科研辅助组")
        manager.groups.add(group)
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/users/{manager.id}/groups/",
            data=json.dumps({"groupIds": [group.id]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "不能修改当前登录用户的角色",
        )

    def test_superadmin_user_groups_cannot_be_updated_from_auth_management(self):
        manager = get_user_model().objects.create_user(
            username="superadmin-group-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"))
        superadmin, protected_group = ensure_superadmin_defaults()
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/users/{superadmin.id}/groups/",
            data=json.dumps({"groupIds": [protected_group.id]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "用户不存在")

    def test_manage_auth_can_toggle_user_status(self):
        manager = get_user_model().objects.create_user(
            username="status-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"))
        target = get_user_model().objects.create_user(
            username="status-target",
            password="StrongPass12345",
        )
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/users/{target.id}/",
            data=json.dumps({"isActive": False}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["isActive"])
        target.refresh_from_db()
        self.assertFalse(target.is_active)

    def test_manage_auth_can_delete_user(self):
        manager = get_user_model().objects.create_user(
            username="delete-user-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"))
        target = get_user_model().objects.create_user(
            username="delete-user-target",
            password="StrongPass12345",
        )
        target_id = target.id
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/users/{target_id}/",
            data=json.dumps({"action": "delete"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(id=target_id).exists())

    def test_manage_auth_can_reset_user_password(self):
        manager = get_user_model().objects.create_user(
            username="reset-password-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"))
        target = get_user_model().objects.create_user(
            username="reset-password-target",
            password="OldPass12345",
        )
        self.client.force_login(manager)

        response = self.client.post(f"/api/users/{target.id}/password/reset/")

        self.assertEqual(response.status_code, 200)
        generated_password = response.json()["generatedPassword"]
        self.assertEqual(len(generated_password), 8)
        target.refresh_from_db()
        self.assertFalse(target.check_password("OldPass12345"))
        self.assertTrue(target.check_password(generated_password))

    def test_current_user_cannot_disable_or_delete_self(self):
        manager = get_user_model().objects.create_user(
            username="self-protect-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"))
        self.client.force_login(manager)

        disable_response = self.client.post(
            f"/api/users/{manager.id}/",
            data=json.dumps({"isActive": False}),
            content_type="application/json",
        )
        delete_response = self.client.post(
            f"/api/users/{manager.id}/",
            data=json.dumps({"action": "delete"}),
            content_type="application/json",
        )

        self.assertEqual(disable_response.status_code, 400)
        self.assertEqual(disable_response.json()["detail"], "不能停用当前登录用户")
        self.assertEqual(delete_response.status_code, 400)
        self.assertEqual(delete_response.json()["detail"], "不能删除当前登录用户")

    def test_current_user_cannot_reset_own_password(self):
        manager = get_user_model().objects.create_user(
            username="self-reset-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"))
        self.client.force_login(manager)

        response = self.client.post(f"/api/users/{manager.id}/password/reset/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "不能重置当前登录用户密码")

    def test_group_list_returns_available_feature_permissions(self):
        manager = get_user_model().objects.create_user(
            username="permission-list-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "manage_feature_permissions"))
        self.client.force_login(manager)

        response = self.client.get("/api/groups/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        permission_ids = {
            permission["id"] for permission in payload["availablePermissions"]
        }
        self.assertNotIn("core.access_admin", permission_ids)
        self.assertIn("core.manage_feature_permissions", permission_ids)
        self.assertIn("core.create_user", permission_ids)
        groups_by_name = {item["name"]: item for item in payload["items"]}
        guest_items = [
            item for item in payload["items"] if item["name"] == GUEST_GROUP_NAME
        ]
        self.assertEqual(guest_items[0]["isProtected"], True)
        self.assertEqual(guest_items[0]["lockedPermissions"], [])
        default_user_items = [
            item for item in payload["items"] if item["name"] == DEFAULT_USER_GROUP_NAME
        ]
        self.assertEqual(default_user_items[0]["isProtected"], True)
        self.assertEqual(default_user_items[0]["lockedPermissions"], [])
        self.assertEqual(groups_by_name[PLATFORM_ADMIN_GROUP_NAME]["isProtected"], True)
        self.assertEqual(
            set(groups_by_name[PLATFORM_ADMIN_GROUP_NAME]["permissions"]),
            platform_admin_group_permissions(),
        )
        self.assertEqual(
            groups_by_name[PLATFORM_ADMIN_GROUP_NAME]["lockedPermissions"], []
        )
        self.assertEqual(groups_by_name[RESEARCH_USER_GROUP_NAME]["isProtected"], True)
        self.assertEqual(
            set(groups_by_name[RESEARCH_USER_GROUP_NAME]["permissions"]),
            research_user_group_permissions(),
        )
        self.assertEqual(
            groups_by_name[RESEARCH_USER_GROUP_NAME]["lockedPermissions"], []
        )
        protected_items = [
            item for item in payload["items"] if item["name"] == SUPERADMIN_GROUP_NAME
        ]
        self.assertEqual(protected_items, [])

    def test_user_list_hides_django_superusers_from_regular_admin(self):
        manager = get_user_model().objects.create_user(
            username="regular-auth-manager", password="pass12345"
        )
        get_user_model().objects.create_superuser(
            username="django-superuser",
            password="StrongPass12345",
        )
        grant(manager, ("core", "manage_auth"))
        self.client.force_login(manager)

        response = self.client.get("/api/users/")

        self.assertEqual(response.status_code, 200)
        usernames = {item["username"] for item in response.json()["items"]}
        self.assertNotIn("django-superuser", usernames)

    def test_django_superuser_without_superadmin_role_cannot_view_superadmin_principals(
        self,
    ):
        protected_user, _ = ensure_superadmin_defaults()
        manager = get_user_model().objects.create_superuser(
            username="plain-django-superuser",
            password="StrongPass12345",
        )
        self.client.force_login(manager)

        users_response = self.client.get("/api/users/")
        groups_response = self.client.get("/api/groups/")

        self.assertEqual(users_response.status_code, 200)
        self.assertEqual(groups_response.status_code, 200)
        usernames = {item["username"] for item in users_response.json()["items"]}
        group_names = {item["name"] for item in groups_response.json()["items"]}
        self.assertNotIn(protected_user.username, usernames)
        self.assertNotIn(SUPERADMIN_GROUP_NAME, group_names)

    def test_group_list_counts_only_visible_users(self):
        manager = get_user_model().objects.create_user(
            username="visible-count-manager", password="pass12345"
        )
        visible_user = get_user_model().objects.create_user(
            username="visible-count-user", password="pass12345"
        )
        superadmin_user, _ = ensure_superadmin_defaults()
        shared_group = Group.objects.create(name="共享角色")
        visible_user.groups.add(shared_group)
        superadmin_user.groups.add(shared_group)
        grant(manager, ("core", "manage_auth"))
        self.client.force_login(manager)

        response = self.client.get("/api/groups/")

        self.assertEqual(response.status_code, 200)
        groups = {item["name"]: item for item in response.json()["items"]}
        self.assertEqual(groups["共享角色"]["userCount"], 1)

    def test_superadmin_group_list_includes_superadmin_role(self):
        manager, _ = ensure_superadmin_defaults()
        self.client.force_login(manager)

        response = self.client.get("/api/groups/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        protected_items = [
            item for item in payload["items"] if item["name"] == SUPERADMIN_GROUP_NAME
        ]
        self.assertEqual(protected_items[0]["isProtected"], True)
        self.assertEqual(
            protected_items[0]["lockedPermissions"],
            sorted(superadmin_group_locked_permissions()),
        )

    def test_guest_group_permissions_can_be_updated(self):
        manager = get_user_model().objects.create_user(
            username="guest-permission-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "manage_feature_permissions"))
        ensure_superadmin_defaults(create_account=False)
        group = Group.objects.get(name=GUEST_GROUP_NAME)
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/groups/{group.id}/",
            data=json.dumps({"permissions": ["core.query_data"]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["permissions"], ["core.query_data"])
        self.assertEqual(response.json()["lockedPermissions"], [])

    def test_manage_auth_cannot_escalate_through_own_group_permissions(self):
        manager = get_user_model().objects.create_user(
            username="group-permission-escalation-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"))
        group = Group.objects.create(name="权限提升防护测试组")
        manager.groups.add(group)
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/groups/{group.id}/",
            data=json.dumps({"permissions": ["core.manage_feature_permissions"]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "当前用户无权限配置角色")
        group.refresh_from_db()
        manager.refresh_from_db()
        self.assertEqual(group.permissions.count(), 0)
        self.assertFalse(manager.has_perm("core.manage_feature_permissions"))

    def test_guest_account_is_protected_from_admin_user_mutations(self):
        manager = get_user_model().objects.create_user(
            username="guest-account-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "manage_feature_permissions"))
        ensure_superadmin_defaults(create_account=False)
        guest = ensure_guest_user()
        normal_group = Group.objects.get(name=DEFAULT_USER_GROUP_NAME)
        self.client.force_login(manager)

        delete_response = self.client.post(
            f"/api/users/{guest.id}/",
            data=json.dumps({"action": "delete"}),
            content_type="application/json",
        )
        disable_response = self.client.post(
            f"/api/users/{guest.id}/",
            data=json.dumps({"isActive": False}),
            content_type="application/json",
        )
        reset_response = self.client.post(
            f"/api/users/{guest.id}/password/reset/",
        )
        groups_response = self.client.post(
            f"/api/users/{guest.id}/groups/",
            data=json.dumps({"groupIds": [normal_group.id]}),
            content_type="application/json",
        )
        permissions_response = self.client.post(
            f"/api/users/{guest.id}/permissions/",
            data=json.dumps({"directPermissions": ["catalog.add_dataresource"]}),
            content_type="application/json",
        )

        self.assertEqual(delete_response.status_code, 400)
        self.assertEqual(disable_response.status_code, 400)
        self.assertEqual(reset_response.status_code, 400)
        self.assertEqual(groups_response.status_code, 400)
        self.assertEqual(permissions_response.status_code, 400)
        guest.refresh_from_db()
        self.assertTrue(guest.is_active)
        self.assertFalse(guest.has_usable_password())
        self.assertEqual(
            list(guest.groups.values_list("name", flat=True)), [GUEST_GROUP_NAME]
        )
        self.assertEqual(guest.user_permissions.count(), 0)

    def test_superadmin_group_cannot_be_deleted_and_keeps_protected_permissions(self):
        manager, group = ensure_superadmin_defaults()
        self.client.force_login(manager)

        delete_response = self.client.post(
            f"/api/groups/{group.id}/",
            data=json.dumps({"action": "delete"}),
            content_type="application/json",
        )
        self.assertEqual(delete_response.status_code, 400)
        self.assertEqual(delete_response.json()["detail"], "系统内置角色不能删除")

        missing_locked_response = self.client.post(
            f"/api/groups/{group.id}/",
            data=json.dumps({"permissions": ["core.browse_data"]}),
            content_type="application/json",
        )
        self.assertEqual(missing_locked_response.status_code, 400)
        self.assertEqual(
            missing_locked_response.json()["detail"],
            "超级管理员角色必须保留系统锁定权限",
        )

        patch_response = self.client.post(
            f"/api/groups/{group.id}/",
            data=json.dumps(
                {"permissions": sorted(superadmin_group_locked_permissions())}
            ),
            content_type="application/json",
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(
            set(patch_response.json()["permissions"]),
            set(protected_group_permissions()),
        )

    def test_default_user_group_cannot_be_deleted_or_renamed_but_permissions_can_change(
        self,
    ):
        manager = get_user_model().objects.create_user(
            username="default-group-guard-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "manage_feature_permissions"))
        ensure_superadmin_defaults(create_account=False)
        group = Group.objects.get(name=DEFAULT_USER_GROUP_NAME)
        self.client.force_login(manager)

        delete_response = self.client.post(
            f"/api/groups/{group.id}/",
            data=json.dumps({"action": "delete"}),
            content_type="application/json",
        )
        self.assertEqual(delete_response.status_code, 400)
        self.assertEqual(delete_response.json()["detail"], "系统内置角色不能删除")

        rename_response = self.client.post(
            f"/api/groups/{group.id}/",
            data=json.dumps({"name": "默认用户"}),
            content_type="application/json",
        )
        self.assertEqual(rename_response.status_code, 400)

        patch_response = self.client.post(
            f"/api/groups/{group.id}/",
            data=json.dumps({"permissions": ["core.query_data"]}),
            content_type="application/json",
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.json()["permissions"], ["core.query_data"])

    def test_non_superadmin_builtin_groups_are_protected_but_permissions_can_change(
        self,
    ):
        manager = get_user_model().objects.create_user(
            username="builtin-group-guard-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "manage_feature_permissions"))
        ensure_superadmin_defaults(create_account=False)
        self.client.force_login(manager)

        for group_name in (PLATFORM_ADMIN_GROUP_NAME, RESEARCH_USER_GROUP_NAME):
            with self.subTest(group_name=group_name):
                group = Group.objects.get(name=group_name)
                delete_response = self.client.post(
                    f"/api/groups/{group.id}/",
                    data=json.dumps({"action": "delete"}),
                    content_type="application/json",
                )
                rename_response = self.client.post(
                    f"/api/groups/{group.id}/",
                    data=json.dumps({"name": f"{group_name}-renamed"}),
                    content_type="application/json",
                )
                patch_response = self.client.post(
                    f"/api/groups/{group.id}/",
                    data=json.dumps({"permissions": ["core.query_data"]}),
                    content_type="application/json",
                )

                self.assertEqual(delete_response.status_code, 400)
                self.assertEqual(rename_response.status_code, 400)
                self.assertEqual(patch_response.status_code, 200)
                self.assertEqual(
                    patch_response.json()["permissions"], ["core.query_data"]
                )
                self.assertEqual(patch_response.json()["lockedPermissions"], [])

    def test_superadmin_user_is_hidden_from_regular_auth_manager(self):
        manager = get_user_model().objects.create_user(
            username="superadmin-user-group-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "manage_feature_permissions"))
        protected_user, _ = ensure_superadmin_defaults()
        normal_group = Group.objects.create(name="普通后台组")
        self.client.force_login(manager)

        list_response = self.client.get("/api/users/")
        response = self.client.post(
            f"/api/users/{protected_user.id}/groups/",
            data=json.dumps({"groupIds": [normal_group.id]}),
            content_type="application/json",
        )

        self.assertEqual(list_response.status_code, 200)
        usernames = {item["username"] for item in list_response.json()["items"]}
        self.assertNotIn(protected_user.username, usernames)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "用户不存在")

    def test_regular_admin_security_surfaces_do_not_serialize_superadmin_principals(
        self,
    ):
        manager = get_user_model().objects.create_user(
            username="security-surface-manager", password="pass12345"
        )
        visible_group = Group.objects.create(name="安全可见角色")
        visible_user = get_user_model().objects.create_user(
            username="visible-security-user",
            first_name="可见用户",
            password="pass12345",
        )
        visible_user.groups.add(visible_group)
        _, superadmin_group = ensure_superadmin_defaults(create_account=False)
        hidden_superadmin = get_user_model().objects.create_user(
            username="hidden-super-principal",
            first_name=SUPERADMIN_GROUP_NAME,
            password="pass12345",
        )
        hidden_superadmin.groups.add(superadmin_group)
        hidden_django_superuser = get_user_model().objects.create_superuser(
            username="hidden-django-superuser",
            password="StrongPass12345",
        )
        grant(
            manager,
            ("core", "manage_auth"),
            ("core", "view_operation_logs"),
            ("core", "view_all_operation_logs"),
            ("core", "view_dashboard_user_card"),
            ("core", "view_dashboard_active_users_card"),
        )
        OperationLog.objects.create(
            user=visible_user,
            module="认证授权",
            action="用户登录",
            status="success",
            message="可见用户登录",
        )
        OperationLog.objects.create(
            user=hidden_superadmin,
            module="认证授权",
            action="用户登录",
            status="success",
            message="隐藏超级管理员登录",
        )
        OperationLog.objects.create(
            user=hidden_django_superuser,
            module="认证授权",
            action="用户登录",
            status="success",
            message="隐藏 Django 超级用户登录",
        )
        self.client.force_login(manager)

        responses = [
            self.client.get("/api/users/"),
            self.client.get("/api/groups/"),
            self.client.get("/api/admin/operation-logs/"),
            self.client.get("/api/admin/dashboard/", {"period": "day"}),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 200)
        encoded_payload = json.dumps(
            [response.json() for response in responses], ensure_ascii=False
        )
        self.assertIn("visible-security-user", encoded_payload)
        self.assertIn("安全可见角色", encoded_payload)
        self.assertIn("可见用户登录", encoded_payload)
        self.assertNotIn("hidden-super-principal", encoded_payload)
        self.assertNotIn("hidden-django-superuser", encoded_payload)
        self.assertNotIn(SUPERADMIN_GROUP_NAME, encoded_payload)
        self.assertNotIn("隐藏超级管理员登录", encoded_payload)
        self.assertNotIn("隐藏 Django 超级用户登录", encoded_payload)

    def test_superadmin_avatar_is_hidden_from_regular_user(self):
        manager = get_user_model().objects.create_user(
            username="superadmin-avatar-manager", password="pass12345"
        )
        protected_user, _ = ensure_superadmin_defaults()
        UserProfile.objects.update_or_create(
            user=protected_user,
            defaults={
                "avatar_data": b"avatar-bytes",
                "avatar_content_type": "image/jpeg",
            },
        )
        self.client.force_login(manager)

        response = self.client.get(f"/api/users/{protected_user.id}/avatar/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "用户不存在")

    def test_regular_user_cannot_be_left_without_group(self):
        manager = get_user_model().objects.create_user(
            username="empty-group-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "manage_feature_permissions"))
        target = get_user_model().objects.create_user(
            username="empty-group-target",
            password="StrongPass12345",
        )
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/users/{target.id}/groups/",
            data=json.dumps({"groupIds": []}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "角色为必选项")

    def test_user_list_returns_direct_and_effective_permissions(self):
        manager = get_user_model().objects.create_user(
            username="user-permission-list-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "manage_feature_permissions"))
        group = Group.objects.create(name="科研辅助组")
        permission = Permission.objects.get(
            content_type__app_label="core", codename="browse_data"
        )
        group.permissions.add(permission)
        target = get_user_model().objects.create_user(
            username="direct-permission-target",
            password="StrongPass12345",
        )
        target.groups.add(group)
        grant(target, ("core", "query_data"))
        self.client.force_login(manager)

        response = self.client.get("/api/users/")

        self.assertEqual(response.status_code, 200)
        target_payload = next(
            item
            for item in response.json()["items"]
            if item["username"] == "direct-permission-target"
        )
        self.assertEqual(target_payload["directPermissions"], ["core.query_data"])
        self.assertEqual(target_payload["groupPermissions"], ["core.browse_data"])
        self.assertEqual(
            set(target_payload["effectivePermissions"]),
            {
                "core.browse_data",
                "core.query_data",
                "core.view_own_operation_logs",
            },
        )

    def test_manage_feature_permissions_can_update_user_direct_permissions(self):
        manager = get_user_model().objects.create_user(
            username="user-permission-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "manage_feature_permissions"))
        target = get_user_model().objects.create_user(
            username="direct-permission-update-target",
            password="StrongPass12345",
        )
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/users/{target.id}/permissions/",
            data=json.dumps({"directPermissions": ["core.query_data"]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["directPermissions"], ["core.query_data"])
        self.assertTrue(target.has_perm("core.query_data"))

    def test_current_user_cannot_update_own_permissions_from_auth_management(self):
        manager = get_user_model().objects.create_user(
            username="own-permission-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"), ("core", "manage_feature_permissions"))
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/users/{manager.id}/permissions/",
            data=json.dumps({"directPermissions": ["core.query_data"]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "请到用户设置中修改自己的权限")

    def test_manage_auth_without_feature_permission_cannot_update_user_permissions(
        self,
    ):
        manager = get_user_model().objects.create_user(
            username="user-permission-blocked-manager", password="pass12345"
        )
        grant(manager, ("core", "manage_auth"))
        target = get_user_model().objects.create_user(
            username="direct-permission-blocked-target",
            password="StrongPass12345",
        )
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/users/{target.id}/permissions/",
            data=json.dumps({"directPermissions": ["core.query_data"]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "当前用户无权限配置用户权限")

    def test_unknown_profile_permission_cannot_be_disabled(self):
        superuser = get_user_model().objects.create_superuser(
            username="protected-profile-superuser",
            password="StrongPass12345",
        )
        ensure_superadmin_defaults(create_account=False)
        self.client.force_login(superuser)

        response = self.client.post(
            "/api/admin/profile/permissions/",
            data=json.dumps({"disabledPermissions": ["core.access_admin"]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "不能关闭未授予的权限：core.access_admin",
        )

    def test_change_password_requires_current_password(self):
        user = get_user_model().objects.create_user(
            username="password-user",
            password="StrongPass12345",
        )
        self.client.force_login(user)

        response = self.client.post(
            "/api/admin/profile/password/",
            data=json.dumps(
                {
                    "currentPassword": "wrong-password",
                    "newPassword": "NewStrong12345",
                    "passwordConfirm": "NewStrong12345",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "当前密码不正确")
        self.assertTrue(
            OperationLog.objects.filter(
                user=user,
                module="认证授权",
                action="修改密码",
                status="failed",
            ).exists()
        )

    def test_change_password_rejects_weak_password(self):
        user = get_user_model().objects.create_user(
            username="weak-password-user",
            password="StrongPass12345",
        )
        self.client.force_login(user)

        response = self.client.post(
            "/api/admin/profile/password/",
            data=json.dumps(
                {
                    "currentPassword": "StrongPass12345",
                    "newPassword": "weak5",
                    "passwordConfirm": "weak5",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("密码长度至少 6 位", response.json()["detail"])

    def test_change_password_updates_password_and_logs_success(self):
        user = get_user_model().objects.create_user(
            username="change-password-user",
            password="StrongPass12345",
        )
        self.client.force_login(user)

        response = self.client.post(
            "/api/admin/profile/password/",
            data=json.dumps(
                {
                    "currentPassword": "StrongPass12345",
                    "newPassword": "NewStrong12345",
                    "passwordConfirm": "NewStrong12345",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.check_password("StrongPass12345"))
        self.assertTrue(user.check_password("NewStrong12345"))
        self.assertTrue(
            OperationLog.objects.filter(
                user=user,
                module="认证授权",
                action="修改密码",
                status="success",
            ).exists()
        )

    def test_admin_operation_logs_query_uses_real_audit_logs(self):
        manager = get_user_model().objects.create_user(
            username="log-manager", password="pass12345"
        )
        grant(
            manager,
            ("core", "view_operation_logs"),
            ("core", "view_all_operation_logs"),
        )
        OperationLog.objects.create(
            user=manager,
            module="系统设置",
            action="保存配置",
            status="success",
            message="写入运行配置",
            target_type="data_resource",
            target_id=123,
            target_code="resource-123",
            target_name="测试数据",
        )
        OperationLog.objects.create(
            user=manager,
            module="认证授权",
            action="创建用户",
            status="failed",
            message="用户名重复",
        )
        superadmin, _ = ensure_superadmin_defaults()
        OperationLog.objects.create(
            user=superadmin,
            module="系统设置",
            action="保存配置",
            status="success",
            message="超级管理员日志",
            target_type="data_resource",
            target_id=123,
        )
        self.client.force_login(manager)

        response = self.client.get(
            "/api/admin/operation-logs/",
            {
                "module": "系统设置",
                "result": "success",
                "targetType": "data_resource",
                "targetId": 123,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["action"], "保存配置")
        self.assertNotEqual(payload["items"][0]["summary"], "超级管理员日志")
        self.assertEqual(payload["items"][0]["targetType"], "data_resource")
        self.assertEqual(payload["items"][0]["targetId"], 123)
        self.assertEqual(payload["items"][0]["targetCode"], "resource-123")
        self.assertEqual(payload["items"][0]["targetName"], "测试数据")

    def test_admin_operation_logs_can_filter_by_user_id(self):
        manager = get_user_model().objects.create_user(
            username="log-user-id-manager", password="pass12345"
        )
        target = get_user_model().objects.create_user(
            username="log-user-id-target", password="pass12345"
        )
        other = get_user_model().objects.create_user(
            username="log-user-id-other", password="pass12345"
        )
        grant(
            manager,
            ("core", "view_operation_logs"),
            ("core", "view_all_operation_logs"),
        )
        OperationLog.objects.create(
            user=target,
            module="认证授权",
            action="重置用户密码",
            status="success",
            message="目标用户日志",
        )
        OperationLog.objects.create(
            user=other,
            module="认证授权",
            action="删除用户",
            status="success",
            message="其他用户日志",
        )
        self.client.force_login(manager)

        response = self.client.get("/api/admin/operation-logs/", {"userId": target.id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["summary"], "目标用户日志")

    def test_admin_operation_logs_user_id_filter_cannot_reveal_superadmin(self):
        manager = get_user_model().objects.create_user(
            username="log-hidden-user-id-manager", password="pass12345"
        )
        superadmin, _ = ensure_superadmin_defaults()
        grant(
            manager,
            ("core", "view_operation_logs"),
            ("core", "view_all_operation_logs"),
        )
        OperationLog.objects.create(
            user=superadmin,
            module="认证授权",
            action="保存权限",
            status="success",
            message="隐藏超级管理员日志",
        )
        self.client.force_login(manager)

        response = self.client.get(
            "/api/admin/operation-logs/", {"userId": superadmin.id}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)

    def test_admin_operation_logs_hide_django_superuser_logs(self):
        manager = get_user_model().objects.create_user(
            username="log-superuser-manager", password="pass12345"
        )
        superuser = get_user_model().objects.create_superuser(
            username="log-django-superuser",
            password="StrongPass12345",
        )
        grant(
            manager,
            ("core", "view_operation_logs"),
            ("core", "view_all_operation_logs"),
        )
        OperationLog.objects.create(
            user=manager,
            module="系统设置",
            action="保存配置",
            status="success",
            message="普通管理员日志",
        )
        OperationLog.objects.create(
            user=superuser,
            module="系统设置",
            action="保存配置",
            status="success",
            message="Django 超级用户日志",
        )
        self.client.force_login(manager)

        response = self.client.get("/api/admin/operation-logs/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["summary"], "普通管理员日志")

    def test_admin_operation_logs_own_scope_only_returns_current_user_logs(self):
        manager = get_user_model().objects.create_user(
            username="own-log-manager", password="pass12345"
        )
        other = get_user_model().objects.create_user(
            username="own-log-other", password="pass12345"
        )
        grant(
            manager,
            ("core", "view_operation_logs"),
            ("core", "view_own_operation_logs"),
        )
        OperationLog.objects.create(
            user=manager,
            module="系统设置",
            action="保存配置",
            status="success",
            message="自己的日志",
        )
        OperationLog.objects.create(
            user=other,
            module="系统设置",
            action="保存配置",
            status="success",
            message="其他用户日志",
        )
        self.client.force_login(manager)

        response = self.client.get("/api/admin/operation-logs/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["summary"], "自己的日志")

        response = self.client.get("/api/admin/operation-logs/", {"userId": other.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)

    def test_admin_operation_logs_always_allows_current_user_own_logs(self):
        user = get_user_model().objects.create_user(
            username="plain-own-log-user", password="pass12345"
        )
        other = get_user_model().objects.create_user(
            username="plain-other-log-user", password="pass12345"
        )
        OperationLog.objects.create(
            user=user,
            module="个人设置",
            action="修改资料",
            status="success",
            message="自己的普通日志",
        )
        OperationLog.objects.create(
            user=other,
            module="个人设置",
            action="修改资料",
            status="success",
            message="其他普通日志",
        )
        self.client.force_login(user)

        response = self.client.get("/api/admin/operation-logs/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["summary"], "自己的普通日志")

    def test_admin_operation_logs_group_scope_uses_configured_groups(self):
        manager = get_user_model().objects.create_user(
            username="group-log-manager", password="pass12345"
        )
        target = get_user_model().objects.create_user(
            username="group-log-target", password="pass12345"
        )
        other = get_user_model().objects.create_user(
            username="group-log-other", password="pass12345"
        )
        target_group = Group.objects.create(name="日志目标组")
        other_group = Group.objects.create(name="其他日志组")
        target.groups.add(target_group)
        other.groups.add(other_group)
        UserProfile.objects.update_or_create(
            user=manager,
            defaults={"operation_log_group_ids": [target_group.id]},
        )
        grant(
            manager,
            ("core", "view_operation_logs"),
            ("core", "view_group_operation_logs"),
        )
        OperationLog.objects.create(
            user=target,
            module="数据管理",
            action="导入数据",
            status="success",
            message="目标组日志",
        )
        OperationLog.objects.create(
            user=other,
            module="数据管理",
            action="导入数据",
            status="success",
            message="其他组日志",
        )
        self.client.force_login(manager)

        response = self.client.get("/api/admin/operation-logs/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["summary"], "目标组日志")

    def test_admin_operation_logs_group_scope_ignores_hidden_superadmin_group(self):
        manager = get_user_model().objects.create_user(
            username="hidden-group-log-manager", password="pass12345"
        )
        target = get_user_model().objects.create_user(
            username="hidden-group-log-target", password="pass12345"
        )
        target_group = Group.objects.create(name="普通日志目标组")
        target.groups.add(target_group)
        superadmin, superadmin_group = ensure_superadmin_defaults()
        UserProfile.objects.update_or_create(
            user=manager,
            defaults={
                "operation_log_group_ids": [target_group.id, superadmin_group.id]
            },
        )
        grant(
            manager,
            ("core", "view_operation_logs"),
            ("core", "view_group_operation_logs"),
        )
        OperationLog.objects.create(
            user=target,
            module="数据管理",
            action="导入数据",
            status="success",
            message="普通角色日志",
        )
        OperationLog.objects.create(
            user=superadmin,
            module="数据管理",
            action="导入数据",
            status="success",
            message="隐藏超级管理员角色日志",
        )
        self.client.force_login(manager)

        response = self.client.get("/api/admin/operation-logs/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["summary"], "普通角色日志")

    def test_admin_system_logs_lists_files_and_returns_tail_content(self):
        manager, _ = ensure_superadmin_defaults()
        log_dir = app_path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "application.log").write_text(
            "第一行\n第二行\n第三行\n第四行\n", encoding="utf-8"
        )
        (log_dir / "django.log").write_text("Django 日志\n", encoding="utf-8")
        self.client.force_login(manager)

        response = self.client.get(
            "/api/admin/system-logs/",
            {"file": "application.log", "lines": 2},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["selectedFile"], "application.log")
        self.assertEqual(payload["lines"], 2)
        self.assertIn("第三行", payload["content"])
        self.assertIn("第四行", payload["content"])
        self.assertNotIn("第一行", payload["content"])
        file_names = [item["name"] for item in payload["files"]]
        self.assertIn("application.log", file_names)
        self.assertIn("django.log", file_names)
        self.assertTrue(all(not Path(name).is_absolute() for name in file_names))

    def test_admin_system_logs_rejects_unknown_or_traversal_file(self):
        manager, _ = ensure_superadmin_defaults()
        log_dir = app_path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "application.log").write_text("可读日志\n", encoding="utf-8")
        self.client.force_login(manager)

        response = self.client.get(
            "/api/admin/system-logs/",
            {"file": "../application.log"},
        )

        self.assertEqual(response.status_code, 404)

    def test_admin_system_logs_requires_system_log_permission(self):
        manager = get_user_model().objects.create_user(
            username="regular-system-log-manager", password="pass12345"
        )
        self.client.force_login(manager)

        response = self.client.get("/api/admin/system-logs/")

        self.assertEqual(response.status_code, 403)

    def test_admin_system_logs_allows_user_with_system_log_permission(self):
        manager = get_user_model().objects.create_user(
            username="delegated-system-log-manager", password="pass12345"
        )
        grant(manager, ("core", "view_system_logs"))
        log_dir = app_path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "application.log").write_text("授权日志\n", encoding="utf-8")
        self.client.force_login(manager)

        response = self.client.get("/api/admin/system-logs/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["selectedFile"], "application.log")

    def test_update_user_permissions_saves_operation_log_groups(self):
        manager = get_user_model().objects.create_user(
            username="log-scope-admin", password="pass12345"
        )
        target = get_user_model().objects.create_user(
            username="log-scope-target", password="pass12345"
        )
        log_group = Group.objects.create(name="可见日志组")
        grant(
            manager,
            ("core", "manage_auth"),
            ("core", "manage_feature_permissions"),
        )
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/users/{target.id}/permissions/",
            data=json.dumps(
                {
                    "directPermissions": ["core.view_group_operation_logs"],
                    "operationLogGroupIds": [log_group.id],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["operationLogGroupIds"], [log_group.id])
        self.assertIn("core.view_group_operation_logs", payload["directPermissions"])

    def test_update_user_permissions_rejects_hidden_superadmin_log_group(self):
        manager = get_user_model().objects.create_user(
            username="hidden-log-scope-admin", password="pass12345"
        )
        target = get_user_model().objects.create_user(
            username="hidden-log-scope-target", password="pass12345"
        )
        _, superadmin_group = ensure_superadmin_defaults(create_account=False)
        grant(
            manager,
            ("core", "manage_auth"),
            ("core", "manage_feature_permissions"),
        )
        self.client.force_login(manager)

        response = self.client.post(
            f"/api/users/{target.id}/permissions/",
            data=json.dumps(
                {
                    "directPermissions": ["core.view_group_operation_logs"],
                    "operationLogGroupIds": [superadmin_group.id],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "包含不存在的日志角色")

    def test_user_list_filters_hidden_superadmin_log_group_ids(self):
        manager = get_user_model().objects.create_user(
            username="hidden-log-group-list-manager", password="pass12345"
        )
        target = get_user_model().objects.create_user(
            username="hidden-log-group-list-target", password="pass12345"
        )
        visible_group = Group.objects.create(name="可见日志角色")
        _, superadmin_group = ensure_superadmin_defaults(create_account=False)
        UserProfile.objects.update_or_create(
            user=target,
            defaults={
                "operation_log_group_ids": [visible_group.id, superadmin_group.id]
            },
        )
        grant(manager, ("core", "manage_auth"))
        self.client.force_login(manager)

        response = self.client.get("/api/users/")

        self.assertEqual(response.status_code, 200)
        users = {item["username"]: item for item in response.json()["items"]}
        self.assertEqual(
            users["hidden-log-group-list-target"]["operationLogGroupIds"],
            [visible_group.id],
        )

    def test_admin_dashboard_counts_data_and_daily_active_users(self):
        manager = get_user_model().objects.create_user(
            username="dashboard-manager", password="pass12345"
        )
        active_user = get_user_model().objects.create_user(
            username="active-user", password="pass12345"
        )
        get_user_model().objects.create_user(
            username="disabled-user", password="pass12345", is_active=False
        )
        grant(
            manager,
            ("core", "view_dashboard_resource_card"),
            ("core", "view_dashboard_layer_card"),
            ("core", "view_dashboard_raster_card"),
            ("core", "view_dashboard_user_card"),
            ("core", "view_dashboard_active_users_card"),
        )
        raster_resource = DataResource.objects.create(
            name="胡杨林分布栅格",
            code="poplar-raster",
            data_type=DataResource.DataType.RASTER,
        )
        DataResource.objects.create(
            name="样地调查点位",
            code="sample-points",
            data_type=DataResource.DataType.VECTOR,
        )
        raster_layer = MapLayer.objects.create(
            name="胡杨林分布栅格",
            code="poplar-raster-layer",
            layer_type=MapLayer.LayerType.RASTER,
            data_resource=raster_resource,
        )
        RasterDataset.objects.create(
            name="胡杨林分布栅格",
            code="poplar-raster-dataset",
            source_relative_path="raster/original/poplar.tif",
            data_resource=raster_resource,
            map_layer=raster_layer,
        )
        OperationLog.objects.create(
            user=active_user,
            module="认证授权",
            action="用户登录",
            event_code=AUTH_LOGIN_SUCCESS,
            status="success",
            message="登录成功",
        )
        OperationLog.objects.create(
            user=active_user,
            module="认证授权",
            action="用户登录",
            event_code=AUTH_LOGIN_SUCCESS,
            status="success",
            message="登录成功",
        )
        UserActivityHour.objects.create(
            user=active_user,
            bucket_start=timezone.localtime().replace(
                minute=0,
                second=0,
                microsecond=0,
            ),
        )
        self.client.force_login(manager)

        response = self.client.get("/api/admin/dashboard/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["cards"]["resources"]["total"], 2)
        self.assertEqual(payload["cards"]["layers"]["total"], 1)
        self.assertEqual(payload["cards"]["rasters"]["resources"], 1)
        self.assertEqual(payload["cards"]["rasters"]["datasets"], 1)
        visible_users = get_user_model().objects.exclude(
            groups__name=SUPERADMIN_GROUP_NAME
        )
        visible_groups = Group.objects.exclude(name=SUPERADMIN_GROUP_NAME)
        self.assertEqual(payload["cards"]["users"]["total"], visible_users.count())
        self.assertEqual(
            payload["cards"]["users"]["active"],
            visible_users.filter(is_active=True).count(),
        )
        self.assertEqual(
            payload["cards"]["users"]["disabled"],
            visible_users.filter(is_active=False).count(),
        )
        self.assertEqual(payload["cards"]["users"]["groups"], visible_groups.count())
        self.assertEqual(payload["cards"]["activeUsers"]["period"], "day")
        self.assertEqual(payload["cards"]["activeUsers"]["count"], 2)
        self.assertEqual(payload["cards"]["activeUsers"]["loginCount"], 2)
        self.assertEqual(
            payload["cards"]["activeUsers"]["ranking"][0]["username"], "active-user"
        )
        self.assertEqual(len(payload["cards"]["activeUsers"]["series"]), 24)

    def test_admin_dashboard_counts_session_activity_without_a_new_login(self):
        manager = get_user_model().objects.create_user(
            username="carried-session-user", password="pass12345"
        )
        grant(manager, ("core", "view_dashboard_active_users_card"))
        self.client.force_login(manager)

        response = self.client.get("/api/admin/dashboard/", {"period": "day"})

        self.assertEqual(response.status_code, 200)
        active_users = response.json()["cards"]["activeUsers"]
        self.assertEqual(active_users["count"], 1)
        self.assertEqual(active_users["loginCount"], 0)
        current_hour = timezone.localtime().hour
        self.assertEqual(active_users["series"][current_hour]["count"], 1)

    def test_admin_dashboard_data_overview_permission_and_superadmin_uploaders(
        self,
    ):
        manager = get_user_model().objects.create_user(
            username="overview-manager", password="pass12345"
        )
        visible_group = Group.objects.create(name="概览可见组")
        manager.groups.add(visible_group)
        uploader = get_user_model().objects.create_user(
            username="overview-uploader",
            first_name="上传人",
            password="pass12345",
        )
        grant(manager, ("core", "view_data_overview"))
        landscape_category = DictionaryItem.objects.get(
            dict_type=DictionaryItem.DictType.DATA_CATEGORY,
            code="thematic_landscape_rs",
        )
        distribution_category = DictionaryItem.objects.get(
            dict_type=DictionaryItem.DictType.DATA_CATEGORY,
            code="distribution_vector",
        )
        DataResource.objects.create(
            name="本人上传",
            code="overview-own",
            data_type=DataResource.DataType.RASTER,
            spatial_extent="80,40,81,41",
            coordinate_system="EPSG:4326",
            size_bytes=30,
            item_count=3,
            maintainer=manager,
            category=landscape_category,
        )
        visible_resource = DataResource.objects.create(
            name="点位",
            code="overview-vector",
            data_type=DataResource.DataType.VECTOR,
            spatial_extent="82,42,83,43",
            coordinate_system="EPSG:4326",
            size_bytes=100,
            item_count=5,
            maintainer=uploader,
            category=distribution_category,
        )
        visible_resource.access_groups.add(visible_group)
        DataResource.objects.create(
            name="表格",
            code="overview-table",
            data_type=DataResource.DataType.TABLE,
            status=DataResource.Status.INACTIVE,
            size_bytes=50,
            item_count=2,
        )
        self.client.force_login(manager)

        response = self.client.get("/api/admin/dashboard/")

        self.assertEqual(response.status_code, 200)
        overview = response.json()["cards"]["dataOverview"]
        self.assertEqual(overview["totalResources"], 3)
        self.assertEqual(overview["activeResources"], 2)
        self.assertEqual(overview["totalSizeBytes"], 180)
        self.assertEqual(overview["totalItemCount"], 10)
        self.assertEqual(overview["ownUploads"]["totalResources"], 1)
        self.assertEqual(overview["ownUploads"]["totalSizeBytes"], 30)
        self.assertEqual(overview["ownUploads"]["totalItemCount"], 3)
        self.assertEqual(
            overview["ownUploads"]["spatialSummary"]["spatialResourceCount"],
            1,
        )
        self.assertEqual(
            overview["ownUploads"]["spatialSummary"]["totalBounds"],
            [80.0, 40.0, 81.0, 41.0],
        )
        own_types = {
            item["dataType"]: item for item in overview["ownUploads"]["typeBreakdown"]
        }
        self.assertEqual(len(own_types), len(DataResource.DataType.choices))
        self.assertEqual(own_types[DataResource.DataType.RASTER]["count"], 1)
        self.assertEqual(own_types[DataResource.DataType.IMAGE]["count"], 0)
        own_categories = {
            item["categoryCode"]: item
            for item in overview["ownUploads"]["categoryBreakdown"]
        }
        self.assertEqual(len(own_categories), 2)
        self.assertEqual(own_categories["spatial"]["count"], 1)
        self.assertEqual(own_categories["spatial"]["children"], [])
        self.assertEqual(overview["ownUploads"]["unclassifiedCount"], 0)
        self.assertEqual(overview["visibleResources"]["totalResources"], 2)
        self.assertEqual(overview["visibleResources"]["totalSizeBytes"], 130)
        self.assertEqual(overview["visibleResources"]["totalItemCount"], 8)
        visible_categories = {
            item["categoryCode"]: item
            for item in overview["visibleResources"]["categoryBreakdown"]
        }
        self.assertEqual(visible_categories["non_spatial"]["count"], 0)
        self.assertEqual(visible_categories["spatial"]["count"], 2)
        visible_spatial = overview["visibleResources"]["spatialSummary"]
        self.assertEqual(visible_spatial["spatialResourceCount"], 2)
        self.assertEqual(visible_spatial["missingSpatialResourceCount"], 0)
        self.assertEqual(visible_spatial["totalBounds"], [80.0, 40.0, 83.0, 43.0])
        self.assertEqual(
            {item["name"] for item in visible_spatial["coverageRanking"]},
            {"本人上传", "点位"},
        )
        self.assertNotIn("uploaders", overview)
        self.assertNotIn("spatialSummary", overview)

        super_group, _ = Group.objects.get_or_create(name=SUPERADMIN_GROUP_NAME)
        superadmin = get_user_model().objects.create_user(
            username="overview-superadmin", password="pass12345"
        )
        superadmin.groups.add(super_group)
        grant(superadmin, ("core", "view_data_overview"))
        self.client.force_login(superadmin)

        response = self.client.get("/api/admin/dashboard/")

        self.assertEqual(response.status_code, 200)
        uploaders = response.json()["cards"]["dataOverview"]["uploaders"]
        uploader_rows = {item["user"]["displayName"]: item for item in uploaders}
        self.assertEqual(uploader_rows["上传人"]["resourceCount"], 1)
        self.assertEqual(uploader_rows["上传人"]["sizeBytes"], 100)
        self.assertEqual(uploader_rows["未记录"]["itemCount"], 2)
        self.assertEqual(
            response.json()["cards"]["dataOverview"]["visibleResources"][
                "totalResources"
            ],
            3,
        )

    def test_admin_dashboard_data_overview_own_uploads_without_permission(self):
        manager = get_user_model().objects.create_user(
            username="own-overview-manager", password="pass12345"
        )
        visible_group = Group.objects.create(name="无权限概览可见组")
        manager.groups.add(visible_group)
        DataResource.objects.create(
            name="本人无需权限上传",
            code="own-overview-upload",
            data_type=DataResource.DataType.TABLE,
            spatial_extent="84,41,85,42",
            size_bytes=64,
            item_count=6,
            maintainer=manager,
        )
        visible_resource = DataResource.objects.create(
            name="可见但需权限统计",
            code="permission-overview-visible",
            data_type=DataResource.DataType.VECTOR,
            size_bytes=128,
            item_count=12,
        )
        visible_resource.access_groups.add(visible_group)
        self.client.force_login(manager)

        response = self.client.get("/api/admin/dashboard/")

        self.assertEqual(response.status_code, 200)
        overview = response.json()["cards"]["dataOverview"]
        self.assertEqual(overview["ownUploads"]["totalResources"], 1)
        self.assertEqual(overview["ownUploads"]["totalSizeBytes"], 64)
        self.assertEqual(overview["ownUploads"]["totalItemCount"], 6)
        self.assertEqual(
            overview["ownUploads"]["spatialSummary"]["totalBounds"],
            [84.0, 41.0, 85.0, 42.0],
        )
        self.assertNotIn("visibleResources", overview)
        self.assertNotIn("totalResources", overview)
        self.assertNotIn("uploaders", overview)

    def test_admin_dashboard_omits_unauthorized_cards(self):
        manager = get_user_model().objects.create_user(
            username="resource-card-manager", password="pass12345"
        )
        grant(
            manager,
            ("core", "view_dashboard_resource_card"),
        )
        DataResource.objects.create(
            name="样地调查点位",
            code="sample-points",
            data_type=DataResource.DataType.VECTOR,
        )
        self.client.force_login(manager)

        response = self.client.get("/api/admin/dashboard/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["cards"]["resources"]["total"], 1)
        self.assertNotIn("layers", payload["cards"])
        self.assertNotIn("activeUsers", payload["cards"])

    def test_admin_dashboard_server_returns_monitor_snapshot(self):
        manager = get_user_model().objects.create_user(
            username="server-manager", password="pass12345"
        )
        grant(
            manager,
            ("core", "view_dashboard_system_card"),
        )
        self.client.force_login(manager)

        response = self.client.get("/api/admin/dashboard/server/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("cpu", payload["cards"])
        self.assertIn("memory", payload["cards"])
        self.assertIn("disks", payload["cards"])
        self.assertIn("usagePercent", payload["cards"]["cpu"])
        self.assertIn("totalBytes", payload["cards"]["memory"])
        self.assertIn("devices", payload["cards"]["disks"])

    def test_admin_dashboard_server_rejects_user_without_system_card_permission(self):
        manager = get_user_model().objects.create_user(
            username="system-card-limited-manager", password="pass12345"
        )
        self.client.force_login(manager)

        response = self.client.get("/api/admin/dashboard/server/")

        self.assertEqual(response.status_code, 403)


class StoragePathTests(SimpleTestCase):
    def test_research_path_rejects_parent_traversal(self):
        with self.assertRaises(StoragePathError):
            research_path("vector", "../secret.gpkg")
        with self.assertRaises(StoragePathError):
            research_path("gene", "../secret.fasta")

    def test_raster_paths_are_under_raster_root(self):
        self.assertEqual(
            raster_source_path("a.tif").parts[-3:],
            ("raster", "original", "a.tif"),
        )
        self.assertEqual(
            raster_processed_path("a.cog.tif").parts[-3:],
            ("raster", "preprocessed", "a.cog.tif"),
        )
        self.assertEqual(
            raster_metadata_path("source/a.tif.gdalinfo.json").parts[-4:],
            ("raster", "metadata", "source", "a.tif.gdalinfo.json"),
        )

    def test_gene_and_table_paths_are_under_fixed_subdirectories(self):
        self.assertEqual(
            gene_data_path("sample.fasta").parts[-2:], ("gene", "sample.fasta")
        )
        self.assertEqual(
            table_data_path("survey.csv").parts[-2:], ("table", "survey.csv")
        )


class ConfigLoaderTests(TestCase):
    def test_django_metadata_database_stays_under_app_data_database(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            business_root = root / "app"
            research_root = root / "research"
            config_path.write_text(
                _minimal_config_text(business_root, research_root),
                encoding="utf-8",
            )

            config = load_project_config(config_path, program_root=Path("/opt/app"))

            self.assertEqual(
                metadata_database_path(config),
                config.app_path("database", "meta.db"),
            )
            self.assertEqual(config.map.tianditu_access_token, "")
            self.assertTrue(
                metadata_database_path(config).is_relative_to(business_root.resolve())
            )
            self.assertFalse(
                metadata_database_path(config).is_relative_to(research_root.resolve())
            )

    def test_loader_rejects_non_boolean_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research").replace(
                    "allow_registration = true",
                    'allow_registration = "false"',
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigValidationError,
                "application.system.allow_registration 必须是布尔值",
            ):
                load_project_config(config_path, program_root=Path("/opt/app"))

    def test_loader_accepts_upload_limit_hard_maximum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research").replace(
                    "upload_max_mb = 512", "upload_max_mb = 1024"
                ),
                encoding="utf-8",
            )

            config = load_project_config(config_path, program_root=Path("/opt/app"))

        self.assertEqual(config.limits.upload_max_mb, 1024)

    def test_loader_rejects_upload_limit_above_hard_maximum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research").replace(
                    "upload_max_mb = 512", "upload_max_mb = 1025"
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigValidationError,
                r"application\.limits\.upload_max_mb 必须是 1 到 1024 之间的整数",
            ):
                load_project_config(config_path, program_root=Path("/opt/app"))

    def test_runtime_reader_falls_back_after_unsafe_upload_limit_hot_edit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    "upload_max_mb = 512", "upload_max_mb = 1025"
                ),
                encoding="utf-8",
            )

            with override_settings(PROJECT_CONFIG=config):
                self.assertEqual(runtime_upload_max_mb(), 512)

    def test_runtime_reader_falls_back_when_hot_edited_config_is_malformed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))
            config_path.write_text("[application\n", encoding="utf-8")

            with override_settings(PROJECT_CONFIG=config):
                self.assertEqual(runtime_upload_max_mb(), 512)

    def test_runtime_reader_falls_back_when_hot_edited_config_is_not_utf8(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))
            config_path.write_bytes(b"\xff\xfe")

            with override_settings(PROJECT_CONFIG=config):
                self.assertEqual(runtime_upload_max_mb(), 512)

    def test_runtime_reader_falls_back_when_hot_edited_limit_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    "upload_max_mb = 512\n", ""
                ),
                encoding="utf-8",
            )

            with override_settings(PROJECT_CONFIG=config):
                self.assertEqual(runtime_upload_max_mb(), 512)

    def test_loader_rejects_invalid_map_numbers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research").replace(
                    "default_center = [80.0, 41.5]",
                    'default_center = ["east", 41.5]',
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigValidationError,
                r"application\.map\.default_center\[0\] 必须是有效数字",
            ):
                load_project_config(config_path, program_root=Path("/opt/app"))

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research").replace(
                    "default_zoom = 4.5",
                    'default_zoom = "far"',
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigValidationError,
                "application.map.default_zoom 必须是有效数字",
            ):
                load_project_config(config_path, program_root=Path("/opt/app"))

    def test_loader_rejects_credentials_that_would_be_exposed_by_bootstrap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research").replace(
                    'mapbox_access_token = ""',
                    'mapbox_access_token = "sk.test-private-token"',
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigValidationError, r"Mapbox pk\.\*"):
                load_project_config(config_path, program_root=Path("/opt/app"))

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                _minimal_config_text(root / "app", root / "research").replace(
                    'mapbox_access_token = ""',
                    'mapbox_access_token = ""\ntianditu_access_token = "invalid"',
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigValidationError, "32 位浏览器 Key"):
                load_project_config(config_path, program_root=Path("/opt/app"))

    def test_loader_creates_fixed_data_subdirectories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
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
mapbox_access_token = "pk.test-token"

[application.limits]
upload_max_mb = 512
query_result_limit = 30000
max_raster_side_pixels = 10000

[application.raster]
symbolizer_timeout_seconds = 120
""",
                encoding="utf-8",
            )

            config = load_project_config(
                config_path, program_root=Path("/opt/data-sharing-platform")
            )

            for subdir in APP_SUBDIRS:
                with self.subTest(root="app", subdir=subdir):
                    self.assertTrue(config.app_path(subdir).is_dir())
            for subdir in RESEARCH_SUBDIRS:
                with self.subTest(root="research", subdir=subdir):
                    self.assertTrue(config.research_path(subdir).is_dir())

    def test_runtime_config_updates_are_written_to_source_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
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

            config = load_project_config(
                config_path, program_root=Path("/opt/data-sharing-platform")
            )
            update_runtime_application_config(
                config,
                {
                    "system": {"name": "更新后的系统"},
                    "map": {"default_center": [82.0, 42.0]},
                },
            )

            # 验证源配置被直接修改
            updated_document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                updated_document["application"]["system"]["name"], "更新后的系统"
            )
            self.assertEqual(
                list(updated_document["application"]["map"]["default_center"]),
                [82.0, 42.0],
            )


def _minimal_config_text(business_root: Path, research_root: Path) -> str:
    return f"""
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
"""


def grant(user, *specs):
    for app_label, codename in specs:
        permission = Permission.objects.get(
            content_type__app_label=app_label, codename=codename
        )
        user.user_permissions.add(permission)
