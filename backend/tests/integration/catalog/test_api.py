from apps.projects.models import Project
import csv
import io
import json
import sqlite3
import tempfile
import zipfile
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from shapely.geometry import Point

from apps.audit.models import OperationLog
from apps.catalog.models import (
    DataCatalog,
    DataResource,
    DataResourceGroup,
    DictionaryItem,
    MapComposition,
    MapLayer,
    VectorDataset,
    WorkspaceScene,
)
from apps.catalog.services import scan_catalog_sources, stable_catalog_code
from apps.core.initialization import (
    GUEST_GROUP_NAME,
    PLATFORM_ADMIN_GROUP_NAME,
    SUPERADMIN_GROUP_NAME,
    ensure_guest_user,
    ensure_superadmin_defaults,
)
from apps.core.storage import (
    gene_data_path,
    table_data_path,
    vector_geopackage_path,
    vector_original_path,
)
from apps.raster.models import RasterDataset
from apps.standards.models import DataDomainType, ResourceDomain, SourceDataset


class IsolatedCatalogStorageMixin:
    def isolate_catalog_storage(self):
        storage_tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(storage_tempdir.name)
        config = replace(
            settings.PROJECT_CONFIG,
            app_data=root / "app",
            research_data_root=root / "research",
        )
        storage_override = override_settings(PROJECT_CONFIG=config)
        storage_override.enable()
        self.addCleanup(storage_tempdir.cleanup)
        self.addCleanup(storage_override.disable)


class LayerApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tester", password="pass12345"
        )
        grant(self.user, ("core", "browse_data"))
        self.client.force_login(self.user)

    def test_layers_endpoint_returns_public_layers(self):
        MapLayer.objects.create(
            name="公开图层",
            code="public-layer",
            layer_type=MapLayer.LayerType.RASTER,
            is_active=True,
        )

        response = self.client.get("/api/layers/")

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        raster_items = [item for item in items if item.get("layerType") == "raster"]
        self.assertEqual(raster_items[0]["code"], "public-layer")

    def test_default_layers_are_public(self):
        layer = MapLayer.objects.create(
            name="受限图层",
            code="restricted-layer",
            layer_type=MapLayer.LayerType.RASTER,
            is_active=True,
        )
        restricted_group, _ = Group.objects.get_or_create(name="科研用户")
        layer.access_groups.add(restricted_group)

        response = self.client.get("/api/layers/")

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        raster_items = [item for item in items if item.get("layerType") == "raster"]
        self.assertEqual([item["code"] for item in raster_items], ["restricted-layer"])

    def test_default_resource_layers_are_public(self):
        restricted_group = Group.objects.create(name="保密资源组")
        resource = DataResource.objects.create(
            name="受限资源",
            code="restricted-layer-resource",
            data_type=DataResource.DataType.VECTOR,
            status=DataResource.Status.ACTIVE,
        )
        resource.access_groups.add(restricted_group)
        MapLayer.objects.create(
            name="资源受限图层",
            code="resource-restricted-layer",
            layer_type=MapLayer.LayerType.VECTOR,
            data_resource=resource,
            is_active=True,
        )

        response = self.client.get("/api/layers/")

        self.assertEqual(response.status_code, 200)
        layer_codes = {item["code"] for item in response.json()["items"]}
        self.assertIn("resource-restricted-layer", layer_codes)


class ResourceListDomainTypeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="domain-filter", password="pass12345"
        )
        grant(self.user, ("core", "browse_data"))
        self.client.force_login(self.user)

    def test_resources_endpoint_filters_by_domain_type(self):
        DataResource.objects.create(
            name="种质样品",
            code="domain-germplasm",
            data_type=DataResource.DataType.VECTOR,
            domain_type="germplasm",
            maintainer=self.user,
            status=DataResource.Status.ACTIVE,
        )
        DataResource.objects.create(
            name="分子实验",
            code="domain-molecular",
            data_type=DataResource.DataType.TABLE,
            domain_type="molecular",
            maintainer=self.user,
            status=DataResource.Status.ACTIVE,
        )
        DataResource.objects.create(
            name="临时资料",
            code="domain-other",
            data_type=DataResource.DataType.TABLE,
            domain_type="other",
            maintainer=self.user,
            status=DataResource.Status.ACTIVE,
        )
        DataResource.objects.create(
            name="行政区边界",
            code="domain-vector",
            data_type=DataResource.DataType.VECTOR,
            domain_type="vector",
            maintainer=self.user,
            status=DataResource.Status.ACTIVE,
        )

        response = self.client.get(
            "/api/catalog/resources/", {"domainType": "germplasm"}
        )

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual([item["code"] for item in items], ["domain-germplasm"])
        self.assertEqual(items[0]["domainType"], "germplasm")

        response = self.client.get("/api/catalog/resources/", {"domainType": "other"})

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual([item["code"] for item in items], ["domain-other"])
        self.assertEqual(items[0]["domainType"], "other")

        response = self.client.get("/api/catalog/resources/", {"domainType": "vector"})

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual([item["code"] for item in items], ["domain-vector"])
        self.assertEqual(items[0]["domainType"], "vector")

    def test_resources_endpoint_rejects_invalid_domain_type(self):
        response = self.client.get("/api/catalog/resources/", {"domainType": "unknown"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "无效的数据业务类型"})

    def test_resources_endpoint_separates_spatial_and_non_spatial_resources(self):
        spatial = DataResource.objects.create(
            name="样地点位",
            code="spatial-resource-filter",
            data_type=DataResource.DataType.VECTOR,
            coordinate_system="EPSG:4326",
            domain_type="field_survey",
            maintainer=self.user,
            status=DataResource.Status.ACTIVE,
        )
        non_spatial = DataResource.objects.create(
            name="样地基础元数据",
            code="non-spatial-resource-filter",
            data_type=DataResource.DataType.TABLE,
            domain_type="field_survey",
            maintainer=self.user,
            status=DataResource.Status.ACTIVE,
        )

        spatial_response = self.client.get(
            "/api/catalog/resources/", {"spatialClass": "spatial"}
        )
        non_spatial_response = self.client.get(
            "/api/catalog/resources/", {"spatialClass": "non_spatial"}
        )

        self.assertEqual(spatial_response.status_code, 200)
        self.assertEqual(non_spatial_response.status_code, 200)
        spatial_items = spatial_response.json()["items"]
        non_spatial_items = non_spatial_response.json()["items"]
        self.assertEqual([item["id"] for item in spatial_items], [spatial.id])
        self.assertEqual(spatial_items[0]["spatialClass"], "spatial")
        self.assertEqual([item["id"] for item in non_spatial_items], [non_spatial.id])
        self.assertEqual(non_spatial_items[0]["spatialClass"], "non_spatial")

    def test_resources_endpoint_rejects_invalid_spatial_class(self):
        response = self.client.get("/api/catalog/resources/", {"spatialClass": "mixed"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "无效的空间数据分类"})


class GuestPublicDataAccessTests(TestCase):
    def test_default_project_resources_are_public_regardless_of_legacy_group(self):
        guest = ensure_guest_user()
        guest_group = Group.objects.get(name=GUEST_GROUP_NAME)
        private_group = Group.objects.create(name="内部科研数据组")
        owner = get_user_model().objects.create_user(
            username="guest-public-data-owner", password="pass12345"
        )
        public_resource = DataResource.objects.create(
            name="公开胡杨样地",
            code="guest-public-resource",
            data_type=DataResource.DataType.VECTOR,
            maintainer=owner,
            status=DataResource.Status.ACTIVE,
        )
        private_resource = DataResource.objects.create(
            name="内部胡杨样地",
            code="guest-private-resource",
            data_type=DataResource.DataType.VECTOR,
            maintainer=owner,
            status=DataResource.Status.ACTIVE,
        )
        public_resource.access_groups.add(guest_group)
        private_resource.access_groups.add(private_group)
        self.client.force_login(guest)

        response = self.client.get("/api/catalog/resources/")

        self.assertEqual(response.status_code, 200)
        resource_ids = {item["id"] for item in response.json()["items"]}
        self.assertIn(public_resource.id, resource_ids)
        self.assertIn(private_resource.id, resource_ids)

        registered_user = get_user_model().objects.create_user(
            username="registered-public-data-reader", password="pass12345"
        )
        grant(registered_user, ("core", "browse_data"))
        self.client.force_login(registered_user)

        registered_response = self.client.get("/api/catalog/resources/")

        self.assertEqual(registered_response.status_code, 200)
        registered_resource_ids = {
            item["id"] for item in registered_response.json()["items"]
        }
        self.assertIn(public_resource.id, registered_resource_ids)
        self.assertIn(private_resource.id, registered_resource_ids)


class ResourceQueryApiTests(IsolatedCatalogStorageMixin, TestCase):
    def setUp(self):
        self.isolate_catalog_storage()
        self.user = get_user_model().objects.create_user(
            username="resource-tester", password="pass12345"
        )
        grant(
            self.user,
            ("core", "browse_data"),
            ("core", "query_data"),
            ("core", "load_vector_layer"),
        )
        self.client.force_login(self.user)
        self.layer_name = "test_query_points"
        self.path = vector_geopackage_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.unlink(missing_ok=True)
        gene_data_path("populus.fasta").unlink(missing_ok=True)
        table_data_path("survey.csv").unlink(missing_ok=True)

        import geopandas as gpd

        gdf = gpd.GeoDataFrame(
            [
                {
                    "name": "样点一",
                    "height": 4.2,
                    "phase": "2025",
                    "geometry": Point(87.6, 43.8),
                },
                {
                    "name": "样点二",
                    "height": 8.5,
                    "phase": "2026",
                    "geometry": Point(87.7, 43.9),
                },
            ],
            geometry="geometry",
            crs="EPSG:4326",
        )
        gdf.to_file(self.path, layer=self.layer_name, driver="GPKG")
        self.resource = DataResource.objects.create(
            name="测试查询点",
            code="test-query-points",
            data_type=DataResource.DataType.VECTOR,
            storage_path=self.layer_name,
            status=DataResource.Status.ACTIVE,
            maintainer=self.user,
        )

    def test_resource_profile_returns_fields_and_metadata(self):
        response = self.client.get(
            f"/api/catalog/resources/{self.resource.id}/profile/"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["featureCount"], 2)
        self.assertEqual(payload["geometryType"], "Point")
        self.assertIn("height", [field["name"] for field in payload["fields"]])

    def test_resource_query_filters_by_attribute(self):
        response = self.client.post(
            f"/api/catalog/resources/{self.resource.id}/query/",
            data={
                "attributeFilters": [
                    {"field": "height", "operator": "gte", "value": "8"}
                ],
                "limit": 10,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["totalCount"], 1)
        self.assertEqual(
            payload["geojson"]["features"][0]["properties"]["name"], "样点二"
        )
        self.assertIn("warnings", payload)

    def test_resource_query_is_gzip_compressed_when_accepted(self):
        import gzip
        import json as jsonlib

        response = self.client.post(
            f"/api/catalog/resources/{self.resource.id}/query/",
            data={"attributeFilters": [], "limit": 10},
            content_type="application/json",
            HTTP_ACCEPT_ENCODING="gzip",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Encoding"], "gzip")
        payload = jsonlib.loads(gzip.decompress(response.content))
        self.assertEqual(payload["resourceId"], self.resource.id)

    def test_resource_query_filters_by_spatial_polygon(self):
        response = self.client.post(
            f"/api/catalog/resources/{self.resource.id}/query/",
            data=json.dumps(
                {
                    "spatialFilter": {
                        "mode": "polygon",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [87.55, 43.75],
                                    [87.65, 43.75],
                                    [87.65, 43.85],
                                    [87.55, 43.85],
                                    [87.55, 43.75],
                                ]
                            ],
                        },
                    },
                    "limit": 10,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["totalCount"], 1)
        self.assertEqual(
            payload["geojson"]["features"][0]["properties"]["name"], "样点一"
        )

    def test_resource_query_rejects_unknown_attribute_operator(self):
        response = self.client.post(
            f"/api/catalog/resources/{self.resource.id}/query/",
            data=json.dumps(
                {
                    "attributeFilters": [
                        {
                            "field": "height",
                            "operator": "startsWith",
                            "value": "8",
                        }
                    ]
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("不支持的属性操作符", response.json()["detail"])

    def test_resource_query_rejects_invalid_json_body(self):
        response = self.client.post(
            f"/api/catalog/resources/{self.resource.id}/query/",
            data="{",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "请求体不是有效 JSON")

    def test_resource_query_rejects_oversized_json_before_querying(self):
        with (
            patch("apps.catalog.views.RESOURCE_QUERY_MAX_BODY_BYTES", 64),
            patch("apps.catalog.views.query_data_resource") as query,
        ):
            response = self.client.post(
                f"/api/catalog/resources/{self.resource.id}/query/",
                data=json.dumps({"padding": "x" * 128}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 413)
        query.assert_not_called()

    def test_resource_query_returns_retryable_busy_response(self):
        gate = MagicMock()
        gate.acquire.return_value = False
        with (
            patch("apps.catalog.views._RESOURCE_QUERY_GATE", gate),
            patch("apps.catalog.views.query_data_resource") as query,
        ):
            response = self.client.post(
                f"/api/catalog/resources/{self.resource.id}/query/",
                data=json.dumps({"limit": 10}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "2")
        query.assert_not_called()
        gate.release.assert_not_called()

    def test_warm_display_query_does_not_use_busy_execution_slot(self):
        url = f"/api/catalog/resources/{self.resource.id}/query/"
        payload = json.dumps({"displayGeometry": True, "limit": 10})
        first = self.client.post(url, data=payload, content_type="application/json")
        self.assertEqual(first.status_code, 200)
        gate = MagicMock()
        gate.acquire.return_value = False
        with patch("apps.catalog.views._DISPLAY_QUERY_GATE", gate):
            cached = self.client.post(
                url, data=payload, content_type="application/json"
            )
        self.assertEqual(cached.status_code, 200)
        self.assertEqual(cached.json()["geojson"], first.json()["geojson"])
        gate.acquire.assert_not_called()

    def test_default_project_query_is_public(self):
        resource = DataResource.objects.create(
            name="受限矢量资源",
            code="restricted-query-resource",
            data_type=DataResource.DataType.VECTOR,
            storage_path=self.layer_name,
            status=DataResource.Status.ACTIVE,
        )
        restricted_group = Group.objects.create(name="外部协作组")
        resource.access_groups.add(restricted_group)

        response = self.client.post(
            f"/api/catalog/resources/{resource.id}/query/",
            data=json.dumps({"limit": 10}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)


class CatalogBusinessScenarioTests(IsolatedCatalogStorageMixin, TestCase):
    def setUp(self):
        self.isolate_catalog_storage()
        suffix = uuid4().hex[:8]
        self.research_group = Group.objects.create(name=f"科研用户-{suffix}")
        self.researcher = get_user_model().objects.create_user(
            username=f"tarim-researcher-{suffix}", password="pass12345"
        )
        self.researcher.groups.add(self.research_group)
        grant(
            self.researcher,
            ("core", "browse_data"),
            ("core", "query_data"),
            ("core", "load_vector_layer"),
        )
        self.other_user = get_user_model().objects.create_user(
            username=f"external-user-{suffix}", password="pass12345"
        )
        grant(
            self.other_user,
            ("core", "browse_data"),
            ("core", "query_data"),
            ("core", "load_vector_layer"),
        )
        self.layer_name = f"tarim_poplar_monitoring_2026_{suffix}"
        self.path = vector_geopackage_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

        import geopandas as gpd

        gdf = gpd.GeoDataFrame(
            [
                {
                    "sample_id": "TP-2026-001",
                    "health": "良好",
                    "dbh_cm": 32.5,
                    "canopy_m": 7.8,
                    "geometry": Point(87.60000, 43.80000),
                },
                {
                    "sample_id": "TP-2026-002",
                    "health": "一般",
                    "dbh_cm": 28.1,
                    "canopy_m": 6.4,
                    "geometry": Point(87.61532, 43.81245),
                },
                {
                    "sample_id": "TP-2026-003",
                    "health": "良好",
                    "dbh_cm": 35.7,
                    "canopy_m": 8.1,
                    "geometry": Point(87.64280, 43.79510),
                },
            ],
            geometry="geometry",
            crs="EPSG:4326",
        )
        gdf.to_file(self.path, layer=self.layer_name, driver="GPKG")
        self.resource = DataResource.objects.create(
            name="塔里木河胡杨样地监测点",
            code=f"tarim-poplar-monitoring-2026-{suffix}",
            data_type=DataResource.DataType.VECTOR,
            source="2026 塔里木河野外调查",
            provider="生态监测组",
            spatial_extent="87.600000,43.795100,87.642800,43.812450",
            coordinate_system="EPSG:4326",
            file_format="GeoPackage",
            storage_path=self.layer_name,
            item_count=3,
            status=DataResource.Status.ACTIVE,
            maintainer=self.researcher,
        )
        self.resource.access_groups.add(self.research_group)
        MapLayer.objects.create(
            name="塔里木河胡杨样地监测点",
            code=f"tarim-poplar-monitoring-layer-{suffix}",
            layer_type=MapLayer.LayerType.VECTOR,
            geometry_type=MapLayer.GeometryType.POINT,
            data_resource=self.resource,
            source_path=self.layer_name,
            is_active=True,
            bounds=[87.6, 43.7951, 87.6428, 43.81245],
        ).access_groups.add(self.research_group)

    def test_authorized_researcher_can_filter_query_and_audit_resource_flow(self):
        self.client.force_login(self.researcher)

        list_response = self.client.get(
            "/api/catalog/resources/?q=塔里木河&dataType=vector"
        )
        profile_response = self.client.get(
            f"/api/catalog/resources/{self.resource.id}/profile/"
        )
        query_response = self.client.post(
            f"/api/catalog/resources/{self.resource.id}/query/",
            data=json.dumps(
                {
                    "attributeFilters": [
                        {"field": "dbh_cm", "operator": "gte", "value": "32"}
                    ],
                    "spatialFilter": {
                        "mode": "rectangle",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [87.59, 43.79],
                                    [87.65, 43.79],
                                    [87.65, 43.82],
                                    [87.59, 43.82],
                                    [87.59, 43.79],
                                ]
                            ],
                        },
                    },
                    "limit": 10,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(list_response.status_code, 200)
        listed_ids = [item["id"] for item in list_response.json()["items"]]
        self.assertEqual(listed_ids, [self.resource.id])

        self.assertEqual(profile_response.status_code, 200)
        profile = profile_response.json()
        self.assertEqual(profile["featureCount"], 3)
        self.assertEqual(profile["bounds"], [87.6, 43.7951, 87.6428, 43.81245])
        self.assertIn("dbh_cm", [field["name"] for field in profile["fields"]])

        self.assertEqual(query_response.status_code, 200)
        payload = query_response.json()
        self.assertEqual(payload["totalCount"], 2)
        self.assertEqual(payload["returnedCount"], 2)
        sample_ids = {
            feature["properties"]["sample_id"]
            for feature in payload["geojson"]["features"]
        }
        self.assertEqual(sample_ids, {"TP-2026-001", "TP-2026-003"})
        self.assertTrue(
            OperationLog.objects.filter(
                user=self.researcher,
                module="数据查询",
                action="查询数据资源",
                status=OperationLog.Status.SUCCESS,
                message__contains="返回 2 条",
                target_type="data_resource",
                target_id=self.resource.id,
                target_code=self.resource.code,
                target_name=self.resource.name,
            ).exists()
        )
        self.assertTrue(
            OperationLog.objects.filter(
                user=self.researcher,
                module="数据查询",
                action="查看数据资源",
                status=OperationLog.Status.SUCCESS,
                target_type="data_resource",
                target_id=self.resource.id,
                target_code=self.resource.code,
                target_name=self.resource.name,
            ).exists()
        )

    def test_visualization_summary_returns_vector_aggregates(self):
        self.client.force_login(self.researcher)

        response = self.client.get(
            f"/api/catalog/resources/{self.resource.id}/visualization-summary/",
            {"topN": "5", "histogramBins": "4"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resource"]["id"], self.resource.id)
        self.assertEqual(payload["source"], "backend_aggregate")
        self.assertEqual(payload["profile"]["featureCount"], 3)
        self.assertEqual(payload["spatialSummary"]["validGeometryCount"], 3)
        self.assertEqual(payload["spatialSummary"]["coordinateCoverageRatio"], 1)

        category_fields = {item["field"] for item in payload["categoryStats"]}
        numeric_fields = {item["field"] for item in payload["numericStats"]}
        self.assertIn("health", category_fields)
        self.assertIn("dbh_cm", numeric_fields)

        dbh_stat = next(
            item for item in payload["numericStats"] if item["field"] == "dbh_cm"
        )
        self.assertEqual(dbh_stat["count"], 3)
        self.assertGreaterEqual(len(dbh_stat["histogram"]), 1)
        self.assertTrue(payload["recommendedCharts"])
        self.assertEqual(payload["monitorPreview"]["status"], "planned")
        self.assertTrue(
            OperationLog.objects.filter(
                user=self.researcher,
                action="查看数据可视化摘要",
                target_type="data_resource",
                target_id=self.resource.id,
            ).exists()
        )

    def test_visualization_summary_rejects_invalid_query_params(self):
        self.client.force_login(self.researcher)

        response = self.client.get(
            f"/api/catalog/resources/{self.resource.id}/visualization-summary/",
            {"topN": "99"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("topN", response.json()["detail"])

    def test_default_project_resource_reads_ignore_legacy_group_restriction(self):
        self.client.force_login(self.other_user)

        list_response = self.client.get("/api/catalog/resources/?dataType=vector")
        layer_response = self.client.get("/api/layers/")
        profile_response = self.client.get(
            f"/api/catalog/resources/{self.resource.id}/profile/"
        )
        summary_response = self.client.get(
            f"/api/catalog/resources/{self.resource.id}/visualization-summary/"
        )
        query_response = self.client.post(
            f"/api/catalog/resources/{self.resource.id}/query/",
            data=json.dumps({"limit": 10}),
            content_type="application/json",
        )

        self.assertEqual(list_response.status_code, 200)
        listed_ids = {
            item["id"]
            for item in list_response.json()["items"]
            if isinstance(item["id"], int)
        }
        self.assertIn(self.resource.id, listed_ids)
        layer_ids = {item["dataResourceId"] for item in layer_response.json()["items"]}
        self.assertIn(self.resource.id, layer_ids)
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(query_response.status_code, 200)

    def test_default_project_directory_includes_active_resources(self):
        public_resource = DataResource.objects.create(
            name="公开目录资源",
            code="public-catalog-resource",
            data_type=DataResource.DataType.TABLE,
            status=DataResource.Status.ACTIVE,
            maintainer=self.other_user,
        )
        catalog = DataCatalog.objects.create(name="监测目录", code="monitoring")
        catalog.resources.add(public_resource, self.resource)
        self.client.force_login(self.other_user)

        response = self.client.get("/api/catalog/directories/")

        self.assertEqual(response.status_code, 200)
        resources = response.json()["items"][0]["resources"]
        resource_ids = {item["id"] for item in resources}
        self.assertIn(public_resource.id, resource_ids)
        self.assertIn(self.resource.id, resource_ids)


class CatalogScanTests(IsolatedCatalogStorageMixin, TestCase):
    def setUp(self):
        self.isolate_catalog_storage()
        self.user = get_user_model().objects.create_user(
            username="catalog-scanner", password="pass12345"
        )
        grant(
            self.user,
            ("core", "browse_data"),
            ("catalog", "add_dataresource"),
        )
        self.client.force_login(self.user)
        self.layer_name = "scan_test_points"
        self.path = vector_geopackage_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.unlink(missing_ok=True)

        import geopandas as gpd

        gdf = gpd.GeoDataFrame(
            [{"name": "扫描点", "geometry": Point(87.6, 43.8)}],
            geometry="geometry",
            crs="EPSG:4326",
        )
        gdf.to_file(self.path, layer=self.layer_name, driver="GPKG")

    def test_scan_endpoint_requires_data_creation_permission(self):
        self.user.user_permissions.clear()
        grant(self.user, ("core", "browse_data"))

        response = self.client.post(
            "/api/catalog/scan/", data={}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 403)

    def test_scan_endpoint_registers_vector_geopackage_layers(self):
        with patch("geopandas.read_file") as read_file:
            read_file.side_effect = AssertionError(
                "目录扫描应通过 SQLite 读取 GeoPackage 元数据"
            )
            response = self.client.post(
                "/api/catalog/scan/", data={}, content_type="application/json"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(len(payload["items"]), 1)
        resource = DataResource.objects.get(storage_path=self.layer_name)
        self.assertEqual(resource.name, self.layer_name)
        self.assertEqual(resource.data_type, DataResource.DataType.VECTOR)
        self.assertEqual(resource.source, "矢量数据目录扫描")
        self.assertEqual(resource.item_count, 1)
        self.assertIsNone(resource.maintainer)
        self.assertEqual(
            set(resource.access_groups.values_list("name", flat=True)),
            {SUPERADMIN_GROUP_NAME},
        )
        layer = MapLayer.objects.get(source_path=self.layer_name)
        self.assertEqual(layer.data_resource, resource)
        self.assertEqual(layer.geometry_type, MapLayer.GeometryType.POINT)
        self.assertEqual(layer.bounds, [87.6, 43.8, 87.6, 43.8])
        self.assertEqual(
            set(layer.access_groups.values_list("name", flat=True)),
            {SUPERADMIN_GROUP_NAME},
        )
        self.assertFalse(
            OperationLog.objects.filter(
                module="数据管理", action="扫描数据目录"
            ).exists()
        )

    def test_scan_preserves_user_uploaded_vector_resource_visibility(self):
        _, superadmin_group = ensure_superadmin_defaults(create_account=False)
        resource = DataResource.objects.create(
            name="User uploaded points",
            code=stable_catalog_code("vector", self.layer_name),
            data_type=DataResource.DataType.VECTOR,
            source="User import",
            storage_path=self.layer_name,
            maintainer=self.user,
            size_bytes=123,
            item_count=1,
            status=DataResource.Status.ACTIVE,
        )
        resource.access_groups.add(superadmin_group)
        layer = MapLayer.objects.create(
            name="Custom upload layer",
            code=stable_catalog_code("vector", self.layer_name),
            layer_type=MapLayer.LayerType.VECTOR,
            data_resource=resource,
            source_path=self.layer_name,
            default_visible=True,
            default_opacity=42,
            symbolization={"pointColor": "#2f7d62"},
            is_active=True,
        )
        layer.access_groups.add(superadmin_group)

        response = self.client.post(
            "/api/catalog/scan/", data={}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["id"], resource.id)
        self.assertEqual(payload["items"][0]["name"], "User uploaded points")
        resource.refresh_from_db()
        self.assertEqual(resource.name, "User uploaded points")
        self.assertEqual(resource.source, "User import")
        self.assertEqual(resource.maintainer, self.user)
        self.assertEqual(resource.size_bytes, 123)
        self.assertEqual(resource.item_count, 1)
        self.assertEqual(
            set(resource.access_groups.values_list("name", flat=True)),
            {SUPERADMIN_GROUP_NAME},
        )
        layer.refresh_from_db()
        self.assertEqual(layer.name, "Custom upload layer")
        self.assertTrue(layer.default_visible)
        self.assertEqual(layer.default_opacity, 42)
        self.assertEqual(layer.symbolization, {"pointColor": "#2f7d62"})
        self.assertEqual(layer.data_resource, resource)

        resources_response = self.client.get("/api/catalog/resources/?dataType=vector")
        self.assertEqual(resources_response.status_code, 200)
        resource_ids = {item["id"] for item in resources_response.json()["items"]}
        self.assertIn(resource.id, resource_ids)

        layers_response = self.client.get("/api/layers/")
        self.assertEqual(layers_response.status_code, 200)
        layer_resource_ids = {
            item["dataResourceId"] for item in layers_response.json()["items"]
        }
        self.assertIn(resource.id, layer_resource_ids)

        dashboard_response = self.client.get("/api/admin/dashboard/")
        self.assertEqual(dashboard_response.status_code, 200)
        own_uploads = dashboard_response.json()["cards"]["dataOverview"]["ownUploads"]
        self.assertEqual(own_uploads["totalResources"], 1)
        self.assertEqual(own_uploads["totalSizeBytes"], 123)
        self.assertEqual(own_uploads["totalItemCount"], 1)

    def test_resources_endpoint_ignores_unreadable_realtime_geopackage(self):
        self.path.write_text("not a geopackage", encoding="utf-8")
        DataResource.objects.create(
            name="已登记样点",
            code="registered-points",
            data_type=DataResource.DataType.VECTOR,
            storage_path="registered_points",
            status=DataResource.Status.ACTIVE,
            maintainer=self.user,
        )

        response = self.client.get("/api/catalog/resources/?dataType=vector")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["name"] for item in payload["items"]], ["已登记样点"])

    def test_scan_endpoint_ignores_unreadable_geopackage(self):
        self.path.write_text("not a geopackage", encoding="utf-8")

        response = self.client.post(
            "/api/catalog/scan/", data={}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": [], "count": 0})

    def test_scan_catalog_sources_registers_nongeographic_files(self):
        gene_file = gene_data_path("populus.fasta")
        table_file = table_data_path("survey.csv")
        gene_file.parent.mkdir(parents=True, exist_ok=True)
        table_file.parent.mkdir(parents=True, exist_ok=True)
        gene_file.write_text(">sample\nATCG\n", encoding="utf-8")
        table_file.write_text("id,value\n1,42\n", encoding="utf-8")
        self.addCleanup(gene_file.unlink, missing_ok=True)
        self.addCleanup(table_file.unlink, missing_ok=True)

        nongeographic_resources = scan_catalog_sources()

        resource_types = {
            resource.storage_path: resource.data_type
            for resource in nongeographic_resources
        }
        for resource in nongeographic_resources:
            self.assertIsNone(resource.maintainer)
            self.assertEqual(
                set(resource.access_groups.values_list("name", flat=True)),
                {SUPERADMIN_GROUP_NAME},
            )
        self.assertEqual(
            resource_types["gene/populus.fasta"], DataResource.DataType.GENE
        )
        self.assertEqual(
            resource_types["table/survey.csv"], DataResource.DataType.TABLE
        )


class WorkspaceSceneApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="workspace-owner", password="pass12345"
        )
        grant(
            self.user,
            ("catalog", "add_workspacescene"),
            ("catalog", "view_workspacescene"),
            ("catalog", "change_workspacescene"),
            ("catalog", "delete_workspacescene"),
        )
        self.client.force_login(self.user)

    def test_create_list_load_update_and_delete_workspace_scene(self):
        shared_group = Group.objects.create(name="工程协作组")
        _, superadmin_group = ensure_superadmin_defaults(create_account=False)
        snapshot = {
            "layerGroups": [
                {
                    "id": "group-1",
                    "name": "胡杨样地",
                    "visible": True,
                    "layers": [],
                }
            ],
            "activePanel": "layers",
        }

        create_response = self.client.post(
            "/api/catalog/workspaces/",
            data=json.dumps(
                {
                    "kind": "project",
                    "name": "现场判读工程",
                    "description": "用于恢复当前图层顺序和符号化",
                    "snapshot": snapshot,
                    "accessGroupIds": [shared_group.id],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()
        self.assertEqual(created["kind"], "project")
        self.assertEqual(created["name"], "现场判读工程")
        self.assertEqual(created["snapshot"], snapshot)
        self.assertEqual(created["owner"]["username"], self.user.username)
        self.assertTrue(created["isOwner"])
        self.assertTrue(created["canEdit"])
        self.assertTrue(created["canDelete"])
        self.assertEqual(
            [group["id"] for group in created["accessGroups"]],
            [shared_group.id],
        )
        scene = WorkspaceScene.objects.get(pk=created["id"])
        self.assertEqual(
            set(scene.access_groups.values_list("id", flat=True)),
            {shared_group.id, superadmin_group.id},
        )
        self.assertTrue(
            OperationLog.objects.filter(
                user=self.user,
                module="工作台",
                action="保存工程",
                status=OperationLog.Status.SUCCESS,
                message="现场判读工程",
                target_type="workspace_scene",
                target_id=created["id"],
                target_code="project",
                target_name="现场判读工程",
            ).exists()
        )

        list_response = self.client.get("/api/catalog/workspaces/?kind=project")

        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.json()
        items = list_payload["items"]
        self.assertEqual([item["name"] for item in items], ["现场判读工程"])
        self.assertNotIn(
            superadmin_group.id,
            [group["id"] for group in list_payload["availableAccessGroups"]],
        )

        detail_response = self.client.get(f"/api/catalog/workspaces/{created['id']}/")

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["snapshot"], snapshot)

        updated_snapshot = {"layerGroups": [], "activePanel": "topics"}
        update_response = self.client.post(
            f"/api/catalog/workspaces/{created['id']}/",
            data=json.dumps(
                {
                    "name": "更新后的工程",
                    "expectedUpdatedAt": created["updatedAt"],
                    "description": "更新说明",
                    "snapshot": updated_snapshot,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["name"], "更新后的工程")
        self.assertEqual(update_response.json()["snapshot"], updated_snapshot)
        self.assertTrue(
            OperationLog.objects.filter(
                user=self.user,
                module="工作台",
                action="更新工程",
                status=OperationLog.Status.SUCCESS,
                message="更新后的工程",
                target_type="workspace_scene",
                target_id=created["id"],
                target_code="project",
                target_name="更新后的工程",
            ).exists()
        )

        delete_response = self.client.post(
            f"/api/catalog/workspaces/{created['id']}/",
            data=json.dumps({"action": "delete"}),
            content_type="application/json",
        )

        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(WorkspaceScene.objects.filter(pk=created["id"]).exists())
        self.assertTrue(
            OperationLog.objects.filter(
                user=self.user,
                module="工作台",
                action="删除工程",
                status=OperationLog.Status.SUCCESS,
                message="更新后的工程",
                target_type="workspace_scene",
                target_id=created["id"],
                target_code="project",
                target_name="更新后的工程",
            ).exists()
        )

    def test_workspace_scene_hides_items_without_owner_or_group_access(self):
        other = get_user_model().objects.create_user(
            username="other-workspace-owner", password="pass12345"
        )
        scene = WorkspaceScene.objects.create(
            project_tag=Project.objects.create(
                name="私有工程", code="hidden-workspace"
            ),
            owner=other,
            kind=WorkspaceScene.Kind.PROJECT,
            name="他人的工程",
            snapshot={"layerGroups": []},
        )

        response = self.client.get(f"/api/catalog/workspaces/{scene.id}/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "工程不存在")

    def test_legacy_group_sharing_does_not_expose_another_users_workspace(self):
        owner = get_user_model().objects.create_user(
            username="shared-workspace-owner", password="pass12345"
        )
        shared_group = Group.objects.create(name="共享工程组")
        self.user.groups.add(shared_group)
        scene = WorkspaceScene.objects.create(
            owner=owner,
            kind=WorkspaceScene.Kind.PROJECT,
            name="共享退化工程",
            snapshot={"groups": []},
        )
        scene.access_groups.add(shared_group)

        list_response = self.client.get("/api/catalog/workspaces/?kind=project")
        detail_response = self.client.get(f"/api/catalog/workspaces/{scene.id}/")
        update_response = self.client.post(
            f"/api/catalog/workspaces/{scene.id}/",
            data=json.dumps({"name": "越权修改"}),
            content_type="application/json",
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["items"], [])
        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(update_response.status_code, 404)
        scene.refresh_from_db()
        self.assertEqual(scene.name, "共享退化工程")

    def test_owner_can_update_access_scope_without_general_change_permission(self):
        change_permission = Permission.objects.get(
            content_type__app_label="catalog",
            codename="change_workspacescene",
        )
        self.user.user_permissions.remove(change_permission)
        shared_group = Group.objects.create(name="仅共享配置组")
        _, superadmin_group = ensure_superadmin_defaults(create_account=False)
        scene = WorkspaceScene.objects.create(
            owner=self.user,
            kind=WorkspaceScene.Kind.PROJECT,
            name="仅权限维护工程",
            snapshot={"groups": []},
        )

        access_response = self.client.post(
            f"/api/catalog/workspaces/{scene.id}/",
            data=json.dumps(
                {
                    "accessGroupIds": [shared_group.id],
                    "expectedUpdatedAt": scene.updated_at.isoformat(),
                }
            ),
            content_type="application/json",
        )
        edit_response = self.client.post(
            f"/api/catalog/workspaces/{scene.id}/",
            data=json.dumps({"name": "不允许修改名称"}),
            content_type="application/json",
        )

        self.assertEqual(access_response.status_code, 200)
        self.assertEqual(edit_response.status_code, 403)
        scene.refresh_from_db()
        self.assertEqual(scene.name, "仅权限维护工程")
        self.assertEqual(
            set(scene.access_groups.values_list("id", flat=True)),
            {shared_group.id, superadmin_group.id},
        )

    def test_superuser_lists_and_loads_every_active_workspace(self):
        other = get_user_model().objects.create_user(
            username="workspace-uploader", password="pass12345"
        )
        scene = WorkspaceScene.objects.create(
            owner=other,
            kind=WorkspaceScene.Kind.PROJECT,
            name="上传用户工程",
            snapshot={"groups": []},
        )
        superuser = get_user_model().objects.create_superuser(
            username="workspace-superuser",
            password="pass12345",
            email="workspace-superuser@example.com",
        )
        self.client.force_login(superuser)

        list_response = self.client.get("/api/catalog/workspaces/?kind=project")
        detail_response = self.client.get(f"/api/catalog/workspaces/{scene.id}/")

        self.assertEqual(list_response.status_code, 200)
        self.assertIn(
            "上传用户工程",
            [item["name"] for item in list_response.json()["items"]],
        )
        self.assertEqual(detail_response.status_code, 200)

    def test_platform_admin_cannot_list_or_maintain_other_users_workspaces(self):
        superadmin, _ = ensure_superadmin_defaults()
        platform_group = Group.objects.get(name=PLATFORM_ADMIN_GROUP_NAME)
        platform_admin = get_user_model().objects.create_user(
            username="workspace-platform-admin", password="pass12345"
        )
        platform_admin.groups.add(platform_group)
        other = get_user_model().objects.create_user(
            username="workspace-platform-owner", password="pass12345"
        )
        scene = WorkspaceScene.objects.create(
            owner=other,
            kind=WorkspaceScene.Kind.PROJECT,
            name="平台维护工程",
            snapshot={"groups": []},
        )
        hidden_owner_scene = WorkspaceScene.objects.create(
            owner=superadmin,
            kind=WorkspaceScene.Kind.PROJECT,
            name="系统维护工程",
            snapshot={"groups": []},
        )
        self.client.force_login(platform_admin)

        list_response = self.client.get("/api/catalog/workspaces/?kind=project")
        admin_list_response = self.client.get("/api/admin/workspaces/?kind=project")
        update_response = self.client.post(
            f"/api/admin/workspaces/{scene.id}/",
            data=json.dumps(
                {
                    "action": "setStatus",
                    "status": "inactive",
                    "expectedUpdatedAt": WorkspaceScene.objects.get(
                        pk=scene.id
                    ).updated_at.isoformat(),
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(list_response.status_code, 200)
        visible = {item["id"] for item in list_response.json()["items"]}
        self.assertNotIn(scene.id, visible)
        self.assertNotIn(hidden_owner_scene.id, visible)
        self.assertEqual(admin_list_response.status_code, 200)
        self.assertNotIn(
            scene.id,
            {item["id"] for item in admin_list_response.json()["items"]},
        )
        self.assertEqual(update_response.status_code, 404)
        scene.refresh_from_db()
        self.assertEqual(scene.status, WorkspaceScene.Status.ACTIVE)

    def test_workspace_scene_rejects_duplicate_name_per_owner_and_kind(self):
        WorkspaceScene.objects.create(
            owner=self.user,
            kind=WorkspaceScene.Kind.PROJECT,
            name="重复工程",
            snapshot={"layerGroups": []},
        )

        response = self.client.post(
            "/api/catalog/workspaces/",
            data=json.dumps(
                {
                    "kind": "project",
                    "name": "重复工程",
                    "snapshot": {"layerGroups": []},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "同名工程已存在")

    def test_workspace_scene_rejects_legacy_topic_kind(self):
        response = self.client.post(
            "/api/catalog/workspaces/",
            data=json.dumps(
                {
                    "kind": "topic",
                    "name": "旧专题入口",
                    "snapshot": {"groups": []},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "kind 仅支持 project")

    def test_workspace_scene_rejects_embedded_geojson_data(self):
        response = self.client.post(
            "/api/catalog/workspaces/",
            data=json.dumps(
                {
                    "kind": "project",
                    "name": "错误工程",
                    "snapshot": {
                        "groups": [
                            {
                                "id": "group-1",
                                "children": [
                                    {
                                        "id": "layer-1",
                                        "geojson": {
                                            "type": "FeatureCollection",
                                            "features": [],
                                        },
                                    }
                                ],
                            }
                        ]
                    },
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "工程快照只能保存查询、范围、资源引用和图层结构，不能包含原始数据",
        )

    def test_workspace_scene_rejects_oversized_payload_with_json_error(self):
        response = self.client.post(
            "/api/catalog/workspaces/",
            data=json.dumps(
                {
                    "kind": "project",
                    "name": "超大工程",
                    "snapshot": {"padding": "x" * (1025 * 1024)},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"], "请求体过大")

    def test_admin_workspace_management_updates_status_access_and_delete(self):
        group = Group.objects.create(name="工程协作组")
        _, superadmin_group = ensure_superadmin_defaults(create_account=False)
        scene = WorkspaceScene.objects.create(
            owner=self.user,
            kind=WorkspaceScene.Kind.PROJECT,
            name="退化监测工程",
            description="后台管理测试",
            snapshot={"layerGroups": []},
        )

        list_response = self.client.get("/api/admin/workspaces/?kind=project")

        self.assertEqual(list_response.status_code, 200)
        payload = list_response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["name"], "退化监测工程")
        self.assertEqual(payload["items"][0]["status"], "active")
        self.assertTrue(payload["items"][0]["canManageAccess"])

        access_response = self.client.post(
            f"/api/admin/workspaces/{scene.id}/",
            data=json.dumps(
                {
                    "action": "updateAccess",
                    "accessGroupIds": [group.id],
                    "expectedUpdatedAt": scene.updated_at.isoformat(),
                }
            ),
            content_type="application/json",
        )
        status_response = self.client.post(
            f"/api/admin/workspaces/{scene.id}/",
            data=json.dumps(
                {
                    "action": "setStatus",
                    "status": "inactive",
                    "expectedUpdatedAt": WorkspaceScene.objects.get(
                        pk=scene.id
                    ).updated_at.isoformat(),
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(access_response.status_code, 200)
        self.assertEqual(status_response.status_code, 200)
        scene.refresh_from_db()
        self.assertEqual(scene.status, WorkspaceScene.Status.INACTIVE)
        self.assertEqual(
            set(scene.access_groups.values_list("id", flat=True)),
            {group.id, superadmin_group.id},
        )
        regular_response = self.client.get(f"/api/catalog/workspaces/{scene.id}/")
        self.assertEqual(regular_response.status_code, 404)

        bad_delete_response = self.client.post(
            f"/api/admin/workspaces/{scene.id}/",
            data=json.dumps({"action": "delete", "confirmationName": "错误名称"}),
            content_type="application/json",
        )
        delete_response = self.client.post(
            f"/api/admin/workspaces/{scene.id}/",
            data=json.dumps({"action": "delete", "confirmationName": "退化监测工程"}),
            content_type="application/json",
        )

        self.assertEqual(bad_delete_response.status_code, 400)
        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(WorkspaceScene.objects.filter(pk=scene.id).exists())
        self.assertTrue(
            OperationLog.objects.filter(
                module="数据管理",
                action="删除工程",
                target_type="workspace_scene",
                target_id=scene.id,
                target_code=WorkspaceScene.Kind.PROJECT,
                target_name="退化监测工程",
            ).exists()
        )

    def test_admin_workspace_delete_hides_project_referenced_by_map_composition(self):
        scene = WorkspaceScene.objects.create(
            owner=self.user,
            kind=WorkspaceScene.Kind.PROJECT,
            name="referenced-project",
            snapshot={"layerGroups": []},
        )
        composition = MapComposition.objects.create(
            owner=self.user,
            project=scene,
            name="composition-1",
            layout={},
        )

        response = self.client.post(
            f"/api/admin/workspaces/{scene.id}/",
            data=json.dumps(
                {"action": "delete", "confirmationName": "referenced-project"}
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        scene.refresh_from_db()
        self.assertEqual(scene.status, WorkspaceScene.Status.INACTIVE)
        self.assertTrue(MapComposition.objects.filter(pk=composition.id).exists())
        regular_response = self.client.get(f"/api/catalog/workspaces/{scene.id}/")
        self.assertEqual(regular_response.status_code, 404)

    def test_admin_workspace_management_hides_inaccessible_project_and_topic(self):
        other = get_user_model().objects.create_user(
            username="other-managed-workspace-owner", password="pass12345"
        )
        restricted_group = Group.objects.create(name="工程专题保密组")
        project = WorkspaceScene.objects.create(
            project_tag=Project.objects.create(
                name="私有工程", code="hidden-workspace"
            ),
            owner=other,
            kind=WorkspaceScene.Kind.PROJECT,
            name="不可见工程",
            snapshot={"groups": []},
        )
        project.access_groups.add(restricted_group)

        list_response = self.client.get("/api/admin/workspaces/")
        update_response = self.client.post(
            f"/api/admin/workspaces/{project.id}/",
            data=json.dumps(
                {
                    "action": "setStatus",
                    "status": "inactive",
                    "expectedUpdatedAt": WorkspaceScene.objects.get(
                        pk=project.id
                    ).updated_at.isoformat(),
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(list_response.status_code, 200)
        names = {item["name"] for item in list_response.json()["items"]}
        self.assertNotIn("不可见工程", names)
        self.assertEqual(update_response.status_code, 404)
        project.refresh_from_db()
        self.assertEqual(project.status, WorkspaceScene.Status.ACTIVE)

    def test_admin_superuser_sees_all_workspaces_without_selectable_superadmin_scope(
        self,
    ):
        other = get_user_model().objects.create_user(
            username="other-superadmin-workspace-owner", password="pass12345"
        )
        WorkspaceScene.objects.create(
            owner=other,
            kind=WorkspaceScene.Kind.PROJECT,
            name="超级管理员全量可见工程",
            snapshot={"groups": []},
        )
        _, superadmin_group = ensure_superadmin_defaults(create_account=False)
        superuser = get_user_model().objects.create_superuser(
            username="workspace-admin-superuser",
            password="pass12345",
            email="workspace-admin-superuser@example.com",
        )
        self.client.force_login(superuser)

        response = self.client.get("/api/admin/workspaces/?kind=project")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(
            "超级管理员全量可见工程",
            [item["name"] for item in payload["items"]],
        )
        self.assertNotIn(
            superadmin_group.id,
            [group["id"] for group in payload["availableAccessGroups"]],
        )


class DataImportApiTests(IsolatedCatalogStorageMixin, TestCase):
    def setUp(self):
        self.isolate_catalog_storage()
        self.user = get_user_model().objects.create_user(
            username="importer", password="pass12345"
        )
        grant(self.user, ("catalog", "add_dataresource"))
        self.client.force_login(self.user)
        self.vector_path = vector_geopackage_path()
        self.table_path = table_data_path("data.sqlite")
        self.vector_path.parent.mkdir(parents=True, exist_ok=True)
        self.table_path.parent.mkdir(parents=True, exist_ok=True)
        self.vector_path.unlink(missing_ok=True)
        self.table_path.unlink(missing_ok=True)

    def test_import_preview_detects_coordinate_columns_and_quantization_error(self):
        response = self.client.post(
            "/api/catalog/import/preview/",
            data={
                "file": self._csv_file(
                    "sample.csv", "name,longitude,latitude\nA,87.600,43.80\n"
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["detected"]["isGeographic"])
        self.assertEqual(payload["detected"]["longitudeColumn"], "longitude")
        self.assertEqual(payload["detected"]["latitudeColumn"], "latitude")
        self.assertIsNone(payload["detected"]["coordinateStats"])
        self.assertEqual(payload["detected"]["validationIssues"], [])

    def test_all_table_import_stages_reject_oversized_files_before_parsing(self):
        oversized_content = b"name\n" + b"x" * (1024 * 1024)
        requests = (
            ("/api/catalog/import/preview/", {}),
            (
                "/api/catalog/import/validate/",
                {"payload": json.dumps({"importMode": "table"})},
            ),
            (
                "/api/catalog/import/commit/",
                {"payload": json.dumps({"importMode": "table"})},
            ),
        )

        with (
            patch("apps.catalog.importer.runtime_upload_max_mb", return_value=1),
            patch("apps.catalog.importer.pd.read_csv") as read_csv,
        ):
            for endpoint, extra in requests:
                with self.subTest(endpoint=endpoint):
                    response = self.client.post(
                        endpoint,
                        data={
                            "file": SimpleUploadedFile(
                                "oversized.csv",
                                oversized_content,
                                content_type="text/csv",
                            ),
                            **extra,
                        },
                        HTTP_X_PROJECT_ID="1",
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(
                        response.json()["detail"],
                        "上传表格超过平台上传大小限制",
                    )

        read_csv.assert_not_called()

    def test_import_preview_does_not_run_coordinate_validation(self):
        response = self.client.post(
            "/api/catalog/import/preview/",
            data={
                "file": self._csv_file(
                    "sample.csv", "name,longitude,latitude\nA,87.600,\n"
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["detected"]["coordinateStats"])
        self.assertEqual(payload["detected"]["validationIssues"], [])

    def test_import_validate_returns_coordinate_issues(self):
        response = self.client.post(
            "/api/catalog/import/validate/",
            data={
                "file": self._csv_file(
                    "points.csv", "name,lon,lat\nA,181.000,43.800\n"
                ),
                "payload": json.dumps(
                    {
                        "importMode": "geographic",
                        "longitudeColumn": "lon",
                        "latitudeColumn": "lat",
                    }
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["coordinateStats"]["totalRows"], 1)
        self.assertEqual(payload["validationIssues"][0]["code"], "invalid_longitude")

    def test_import_validate_returns_duplicate_display_name_target(self):
        DataResource.objects.create(
            name="已有调查表",
            code="existing-display-name",
            data_type=DataResource.DataType.TABLE,
            storage_path="existing_table",
            status=DataResource.Status.ACTIVE,
        )

        response = self.client.post(
            "/api/catalog/import/validate/",
            data={
                "file": self._csv_file("survey.csv", "name\nA\n"),
                "payload": json.dumps(
                    {
                        "name": "已有调查表",
                        "importMode": "table",
                        "tableName": "new_unique_table",
                    }
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        duplicate_target = response.json()["duplicateTarget"]
        self.assertEqual(duplicate_target["targetType"], "data_resource_name")
        self.assertEqual(duplicate_target["targetName"], "已有调查表")

    def test_import_geographic_table_writes_gpkg_metadata(self):
        self.assertFalse(self.vector_path.exists())
        uploaded_file = self._csv_file("points.csv", "name,lon,lat\nA,87.600,43.800\n")

        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": uploaded_file,
                "payload": json.dumps(
                    {
                        "name": "导入点位",
                        "domainType": "field_survey",
                        "categoryCode": "spatial",
                        "tableName": "import_points",
                        "importMode": "geographic",
                        "longitudeColumn": "lon",
                        "latitudeColumn": "lat",
                        "duplicateConfirmed": False,
                        "fieldMetadata": {
                            "name": "样点名称",
                            "lon": "经度",
                            "lat": "纬度",
                        },
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["mode"], "geographic")
        self.assertEqual(payload["importedRows"], 1)
        self.assertEqual(payload["layerName"], "import_points")
        self.assertEqual(payload["tableName"], "import_points")
        self.assertEqual(payload["resourceName"], "导入点位")
        self.assertTrue(self.vector_path.is_file())

        import geopandas as gpd

        gdf = gpd.read_file(self.vector_path, layer="import_points")
        self.assertEqual(len(gdf), 1)

        resource = DataResource.objects.get(storage_path="import_points")
        self.assertEqual(resource.name, "导入点位")
        self.assertEqual(resource.id, payload["resourceId"])
        self.assertEqual(resource.data_type, DataResource.DataType.VECTOR)
        self.assertEqual(resource.domain_type, "field_survey")
        self.assertEqual(resource.category.code, "spatial")
        self.assertEqual(resource.maintainer, self.user)
        self.assertEqual(resource.size_bytes, uploaded_file.size)
        self.assertEqual(resource.item_count, 1)

        with sqlite3.connect(self.vector_path) as connection:
            description = connection.execute(
                "SELECT description FROM gpkg_data_columns WHERE table_name = ? AND column_name = ?",
                ("import_points", "name"),
            ).fetchone()[0]
        self.assertEqual(description, "样点名称")

    def test_imported_geographic_table_resource_list_uses_display_name(self):
        grant(self.user, ("core", "browse_data"))
        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file("points.csv", "name,lon,lat\nA,87.600,43.800\n"),
                "payload": json.dumps(
                    {
                        "name": "样地调查点",
                        "domainType": "field_survey",
                        "tableName": "survey_points_2026",
                        "importMode": "geographic",
                        "longitudeColumn": "lon",
                        "latitudeColumn": "lat",
                        "duplicateConfirmed": False,
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )
        self.assertEqual(response.status_code, 201)

        resources_response = self.client.get("/api/catalog/resources/?dataType=vector")

        self.assertEqual(resources_response.status_code, 200)
        names = [item["name"] for item in resources_response.json()["items"]]
        self.assertIn("样地调查点", names)
        self.assertNotIn("survey_points_2026", names)

    def test_import_geographic_table_respects_included_columns(self):
        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file(
                    "points.csv",
                    "name,lon,lat,drop_me\nA,87.600,43.800,hidden\n",
                ),
                "payload": json.dumps(
                    {
                        "name": "导入点位",
                        "domainType": "field_survey",
                        "tableName": "included_points",
                        "importMode": "geographic",
                        "longitudeColumn": "lon",
                        "latitudeColumn": "lat",
                        "duplicateConfirmed": False,
                        "includedColumns": ["name", "lon", "lat"],
                        "fieldMetadata": {
                            "name": "样点名称",
                            "lon": "经度",
                            "lat": "纬度",
                            "drop_me": "不应入库",
                        },
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 201)
        import geopandas as gpd

        gdf = gpd.read_file(self.vector_path, layer="included_points")
        self.assertNotIn("drop_me", gdf.columns)
        with sqlite3.connect(self.vector_path) as connection:
            hidden_metadata = connection.execute(
                "SELECT description FROM gpkg_data_columns WHERE table_name = ? AND column_name = ?",
                ("included_points", "drop_me"),
            ).fetchone()
        self.assertIsNone(hidden_metadata)

    def test_import_geographic_table_rejects_missing_coordinates(self):
        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file("points.csv", "name,lon,lat\nA,87.600,\n"),
                "payload": json.dumps(
                    {
                        "name": "导入点位",
                        "domainType": "field_survey",
                        "tableName": "missing_points",
                        "importMode": "geographic",
                        "longitudeColumn": "lon",
                        "latitudeColumn": "lat",
                        "duplicateConfirmed": False,
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["detail"], "数据校验未通过")
        self.assertEqual(payload["issues"][0]["code"], "missing_geometry")

    def test_import_geographic_table_accepts_integer_decimal_degrees(self):
        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file("points.csv", "name,lon,lat\nA,87,43.800\n"),
                "payload": json.dumps(
                    {
                        "name": "导入点位",
                        "domainType": "field_survey",
                        "tableName": "integer_coordinate_points",
                        "importMode": "geographic",
                        "longitudeColumn": "lon",
                        "latitudeColumn": "lat",
                        "duplicateConfirmed": False,
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 201)

    def test_import_geographic_table_rejects_out_of_range_coordinates(self):
        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file(
                    "points.csv", "name,lon,lat\nA,181.000,43.800\nB,87.600,91.000\n"
                ),
                "payload": json.dumps(
                    {
                        "name": "导入点位",
                        "domainType": "field_survey",
                        "tableName": "out_of_range_points",
                        "importMode": "geographic",
                        "longitudeColumn": "lon",
                        "latitudeColumn": "lat",
                        "duplicateConfirmed": False,
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 400)
        issue_codes = [issue["code"] for issue in response.json()["issues"]]
        self.assertIn("invalid_longitude", issue_codes)
        self.assertIn("invalid_latitude", issue_codes)

    def test_import_geographic_table_requires_uncertainty_confirmation(self):
        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file(
                    "points.csv",
                    "name,lon,lat\nA,87.6,43.8\nB,87.600001,43.800001\n",
                ),
                "payload": json.dumps(
                    {
                        "name": "导入点位",
                        "domainType": "field_survey",
                        "tableName": "uncertain_points",
                        "importMode": "geographic",
                        "longitudeColumn": "lon",
                        "latitudeColumn": "lat",
                        "duplicateConfirmed": False,
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["issues"][0]["code"], "coordinate_uncertainty")

    def test_import_geographic_table_can_ignore_uncertainty(self):
        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file(
                    "points.csv",
                    "name,lon,lat\nA,87.6,43.8\nB,87.600001,43.800001\n",
                ),
                "payload": json.dumps(
                    {
                        "name": "导入点位",
                        "domainType": "field_survey",
                        "tableName": "confirmed_uncertain_points",
                        "importMode": "geographic",
                        "longitudeColumn": "lon",
                        "latitudeColumn": "lat",
                        "ignoreCoordinateUncertainty": True,
                        "duplicateConfirmed": False,
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["importedRows"], 2)

    def test_add_dataresource_permission_can_import(self):
        self.user.user_permissions.clear()
        grant(self.user, ("catalog", "add_dataresource"))

        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file("survey.csv", "name,value\nA,42\n"),
                "payload": json.dumps(
                    {
                        "name": "普通用户上传表",
                        "domainType": "field_survey",
                        "tableName": "upload_permission_table",
                        "importMode": "table",
                        "duplicateConfirmed": False,
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 201)
        resource = DataResource.objects.get(storage_path="upload_permission_table")
        self.assertEqual(resource.maintainer, self.user)

    def test_import_commit_sets_visibility_scope(self):
        ensure_guest_user()
        guest_group = Group.objects.get(name=GUEST_GROUP_NAME)

        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file("survey.csv", "name,value\nA,42\n"),
                "payload": json.dumps(
                    {
                        "name": "游客共享表",
                        "domainType": "field_survey",
                        "tableName": "guest_visible_table",
                        "importMode": "table",
                        "duplicateConfirmed": False,
                        "accessGroupIds": [guest_group.id],
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 201)
        resource = DataResource.objects.get(storage_path="guest_visible_table")
        group_names = set(resource.access_groups.values_list("name", flat=True))
        self.assertEqual(resource.maintainer, self.user)
        self.assertIn(SUPERADMIN_GROUP_NAME, group_names)
        self.assertIn(GUEST_GROUP_NAME, group_names)

    def test_import_commit_rejects_hidden_superadmin_access_group(self):
        _, superadmin_group = ensure_superadmin_defaults(create_account=False)

        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file("survey.csv", "name,value\nA,42\n"),
                "payload": json.dumps(
                    {
                        "name": "隐藏角色表",
                        "domainType": "field_survey",
                        "tableName": "hidden_group_table",
                        "importMode": "table",
                        "duplicateConfirmed": False,
                        "accessGroupIds": [superadmin_group.id],
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "包含不存在或不可选择的角色")
        self.assertFalse(
            DataResource.objects.filter(storage_path="hidden_group_table").exists()
        )

    def test_import_commit_rejects_superadmin_access_group_from_superadmin_user(self):
        superadmin_user, superadmin_group = ensure_superadmin_defaults()
        grant(superadmin_user, ("catalog", "add_dataresource"))
        self.client.force_login(superadmin_user)

        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file("survey.csv", "name,value\nA,42\n"),
                "payload": json.dumps(
                    {
                        "name": "超级管理员手动角色表",
                        "domainType": "field_survey",
                        "tableName": "superadmin_selected_group_table",
                        "importMode": "table",
                        "duplicateConfirmed": False,
                        "accessGroupIds": [superadmin_group.id],
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "包含不存在或不可选择的角色")
        self.assertFalse(
            DataResource.objects.filter(
                storage_path="superadmin_selected_group_table"
            ).exists()
        )

    def test_import_plain_table_writes_sqlite_data_and_metadata(self):
        self.assertFalse(self.table_path.exists())
        uploaded_file = self._csv_file("survey.csv", "name,value\nA,42\n")

        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": uploaded_file,
                "payload": json.dumps(
                    {
                        "name": "调查表",
                        "domainType": "field_survey",
                        "tableName": "survey_table",
                        "importMode": "table",
                        "duplicateConfirmed": False,
                        "fieldMetadata": {"name": "名称", "value": "数值"},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["mode"], "table")
        self.assertEqual(payload["resourceName"], "调查表")
        resource = DataResource.objects.get(storage_path="survey_table")
        self.assertEqual(resource.data_type, DataResource.DataType.TABLE)
        self.assertEqual(resource.domain_type, "field_survey")
        self.assertEqual(resource.maintainer, self.user)
        self.assertEqual(resource.size_bytes, uploaded_file.size)
        self.assertEqual(resource.item_count, 1)
        self.assertTrue(self.table_path.is_file())
        with sqlite3.connect(self.table_path) as connection:
            row = connection.execute("SELECT name, value FROM survey_table").fetchone()
            description = connection.execute(
                "SELECT description FROM data_columns WHERE table_name = ? AND column_name = ?",
                ("survey_table", "value"),
            ).fetchone()[0]
        self.assertEqual(row, ("A", "42"))
        self.assertEqual(description, "数值")

    def test_import_plain_table_rejects_duplicate_name_without_duplicate_confirmation_and_allows_duplicate_confirmation(
        self,
    ):
        DataResource.objects.create(
            name="重复表",
            code="duplicate-display-name",
            data_type=DataResource.DataType.TABLE,
            storage_path="existing_table",
            status=DataResource.Status.ACTIVE,
        )

        reject_response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file("survey.csv", "name\n新值\n"),
                "payload": json.dumps(
                    {
                        "name": "重复表",
                        "domainType": "field_survey",
                        "tableName": "existing_table",
                        "importMode": "table",
                        "duplicateConfirmed": False,
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(reject_response.status_code, 400)
        reject_payload = reject_response.json()
        self.assertEqual(reject_payload["detail"], "数据名称已存在")
        self.assertEqual(reject_payload["issues"][0]["code"], "duplicate_target")
        self.assertEqual(
            reject_payload["issues"][0]["targetType"], "data_resource_name"
        )

        confirmed_response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file("survey.csv", "name\n新值\n"),
                "payload": json.dumps(
                    {
                        "name": "重复表",
                        "domainType": "field_survey",
                        "tableName": "existing_table",
                        "importMode": "table",
                        "duplicateConfirmed": True,
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(confirmed_response.status_code, 201)
        confirmed_payload = confirmed_response.json()
        self.assertEqual(confirmed_payload["resourceName"], "重复表")
        self.assertNotEqual(confirmed_payload["tableName"], "existing_table")
        self.assertTrue(confirmed_payload["tableName"].startswith("existing_table_"))
        with sqlite3.connect(self.table_path) as connection:
            rows = connection.execute(
                f'SELECT name FROM "{confirmed_payload["tableName"]}"'
            ).fetchall()
        self.assertEqual(rows, [("新值",)])

    def test_import_plain_table_generates_unique_storage_id_for_each_upload(self):
        first_response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file("survey.csv", "name\nA\n"),
                "payload": json.dumps(
                    {
                        "name": "第一次调查表",
                        "domainType": "field_survey",
                        "tableName": "same_backend_id",
                        "importMode": "table",
                        "duplicateConfirmed": False,
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )
        second_response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file("survey.csv", "name\nB\n"),
                "payload": json.dumps(
                    {
                        "name": "第二次调查表",
                        "domainType": "field_survey",
                        "tableName": "same_backend_id",
                        "importMode": "table",
                        "duplicateConfirmed": False,
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 201)
        first_table = first_response.json()["tableName"]
        second_table = second_response.json()["tableName"]
        self.assertEqual(first_table, "same_backend_id")
        self.assertNotEqual(second_table, first_table)
        self.assertTrue(second_table.startswith("same_backend_id_"))
        self.assertEqual(
            DataResource.objects.filter(name__endswith="调查表").count(), 2
        )

    def test_import_plain_table_respects_included_columns(self):
        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file("survey.csv", "name,value,drop_me\nA,42,x\n"),
                "payload": json.dumps(
                    {
                        "name": "调查表",
                        "domainType": "field_survey",
                        "categoryCode": "non_spatial",
                        "tableName": "included_table",
                        "importMode": "table",
                        "duplicateConfirmed": False,
                        "includedColumns": ["name", "value"],
                        "fieldMetadata": {
                            "name": "名称",
                            "value": "数值",
                            "drop_me": "不应入库",
                        },
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 201)
        resource = DataResource.objects.get(storage_path="included_table")
        self.assertEqual(resource.category.code, "non_spatial")
        with sqlite3.connect(self.table_path) as connection:
            columns = [
                row[1]
                for row in connection.execute("PRAGMA table_info(included_table)")
            ]
            hidden_metadata = connection.execute(
                "SELECT description FROM data_columns WHERE table_name = ? AND column_name = ?",
                ("included_table", "drop_me"),
            ).fetchone()
        self.assertEqual(columns, ["name", "value"])
        self.assertIsNone(hidden_metadata)

    def test_vector_import_preview_reads_geojson_metadata(self):
        response = self.client.post(
            "/api/catalog/vector-import/preview/",
            data={"file": self._geojson_file("xinjiang_boundary.geojson")},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["sourceFormat"], "GEOJSON")
        self.assertEqual(len(payload["layers"]), 1)
        layer = payload["layers"][0]
        self.assertEqual(layer["sourceLayerName"], "xinjiang_boundary")
        self.assertEqual(layer["geometryType"], "Polygon")
        self.assertEqual(layer["featureCount"], 1)
        self.assertEqual(layer["quality"]["invalidCount"], 0)
        self.assertIn("name", [field["name"] for field in layer["fields"]])

    def test_vector_import_preview_rejects_standalone_shapefile(self):
        response = self.client.post(
            "/api/catalog/vector-import/preview/",
            data={
                "file": SimpleUploadedFile("boundary.shp", b"not-a-complete-shapefile")
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("打包为 ZIP", response.json()["detail"])

    def test_vector_import_preview_rejects_incomplete_shapefile_zip(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("boundary.shp", b"shape")
        response = self.client.post(
            "/api/catalog/vector-import/preview/",
            data={
                "file": SimpleUploadedFile(
                    "boundary.zip",
                    archive.getvalue(),
                    content_type="application/zip",
                )
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("缺少必要组件", response.json()["detail"])

    def test_vector_import_commit_creates_resource_dataset_layer_and_domain(self):
        response = self.client.post(
            "/api/catalog/vector-import/commit/",
            data={
                "file": self._geojson_file("xinjiang_boundary.geojson"),
                "payload": json.dumps(
                    {
                        "name": "新疆自治区边界",
                        "domainType": "vector",
                        "categoryCode": "spatial",
                        "sourceLayerName": "xinjiang_boundary",
                        "tableName": "xinjiang_boundary",
                        "duplicateConfirmed": False,
                        "repairInvalidGeometries": False,
                        "skipInvalidGeometries": False,
                        "accessGroupIds": [],
                        "fieldMetadata": {"name": "行政区名称"},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(payload["mode"], "vector")
        self.assertEqual(payload["importedFeatures"], 1)
        self.assertEqual(payload["geometryType"], "Polygon")
        resource = DataResource.objects.get(pk=payload["resourceId"])
        self.assertEqual(resource.data_type, DataResource.DataType.VECTOR)
        self.assertEqual(resource.domain_type, DataDomainType.VECTOR)
        self.assertEqual(resource.category.code, "spatial")
        self.assertEqual(resource.coordinate_system, "EPSG:4326")
        dataset = VectorDataset.objects.get(resource=resource)
        self.assertEqual(dataset.source_format, VectorDataset.SourceFormat.GEOJSON)
        self.assertEqual(dataset.feature_count, 1)
        self.assertEqual(dataset.normalized_epsg, 4326)
        layer = MapLayer.objects.get(data_resource=resource)
        self.assertEqual(layer.geometry_type, MapLayer.GeometryType.POLYGON)
        self.assertEqual(layer.name, "新疆自治区边界")
        domain = ResourceDomain.objects.get(resource=resource)
        self.assertEqual(domain.domain_type, DataDomainType.VECTOR)
        self.assertTrue(SourceDataset.objects.filter(resource=resource).exists())
        vector_original_path(dataset.source_archive_path).unlink(missing_ok=True)

    def test_vector_import_validate_requires_crs_when_source_has_none(self):
        content = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "A"},
                    "geometry": {"type": "Point", "coordinates": [87.6, 43.8]},
                }
            ],
        }
        with patch("apps.catalog.vector_importer.read_vector_layer") as reader:
            import geopandas as gpd

            reader.return_value = (
                gpd.GeoDataFrame(
                    [{"name": "A", "geometry": Point(87.6, 43.8)}], crs=None
                ),
                None,
            )
            response = self.client.post(
                "/api/catalog/vector-import/validate/",
                data={
                    "file": SimpleUploadedFile(
                        "point.geojson",
                        json.dumps(content).encode("utf-8"),
                        content_type="application/geo+json",
                    ),
                    "payload": json.dumps(
                        {
                            "name": "无坐标系点",
                            "sourceLayerName": "point",
                            "tableName": "point_without_crs",
                        }
                    ),
                },
            )

        self.assertEqual(response.status_code, 200)
        issues = response.json()["validationIssues"]
        self.assertTrue(any(issue["code"] == "missing_crs" for issue in issues))

    def _geojson_file(self, name: str) -> SimpleUploadedFile:
        content = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "新疆自治区"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [73.5, 34.3],
                                [96.3, 34.3],
                                [96.3, 49.1],
                                [73.5, 49.1],
                                [73.5, 34.3],
                            ]
                        ],
                    },
                }
            ],
        }
        return SimpleUploadedFile(
            name,
            json.dumps(content, ensure_ascii=False).encode("utf-8"),
            content_type="application/geo+json",
        )

    def _csv_file(self, name: str, content: str) -> SimpleUploadedFile:
        return SimpleUploadedFile(
            name, content.encode("utf-8"), content_type="text/csv"
        )


class ImportCommitDomainTypeApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="import-domain-validator", password="pass12345"
        )
        grant(self.user, ("catalog", "add_dataresource"))
        self.client.force_login(self.user)

    def test_import_commit_rejects_missing_domain_type(self):
        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file("survey.csv", "name,value\nA,42\n"),
                "payload": json.dumps(
                    {
                        "name": "缺少业务类型表",
                        "tableName": "missing_domain_type_table",
                        "importMode": "table",
                        "duplicateConfirmed": False,
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "请选择业务数据类型")
        self.assertFalse(
            DataResource.objects.filter(
                storage_path="missing_domain_type_table"
            ).exists()
        )

    def test_import_commit_rejects_invalid_domain_type(self):
        response = self.client.post(
            "/api/catalog/import/commit/",
            data={
                "file": self._csv_file("survey.csv", "name,value\nA,42\n"),
                "payload": json.dumps(
                    {
                        "name": "无效业务类型表",
                        "domainType": "unknown",
                        "tableName": "invalid_domain_type_table",
                        "importMode": "table",
                        "duplicateConfirmed": False,
                        "fieldMetadata": {},
                    }
                ),
            },
            HTTP_X_PROJECT_ID="1",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "无效的数据业务类型")
        self.assertFalse(
            DataResource.objects.filter(
                storage_path="invalid_domain_type_table"
            ).exists()
        )

    def test_import_commit_accepts_other_domain_type(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.__exit__.return_value = False
        with (
            patch(
                "apps.catalog.importer.unique_import_table_name",
                return_value="other_domain_type_table",
            ),
            patch("apps.catalog.importer._ensure_table_can_be_written"),
            patch("apps.catalog.importer.sqlite3.connect", return_value=connection),
            patch("apps.catalog.importer.pd.DataFrame.to_sql"),
            patch("apps.catalog.importer.write_sqlite_field_metadata"),
        ):
            response = self.client.post(
                "/api/catalog/import/commit/",
                data={
                    "file": self._csv_file("notes.csv", "name,value\nA,42\n"),
                    "payload": json.dumps(
                        {
                            "name": "其他类型资料表",
                            "domainType": "other",
                            "tableName": "other_domain_type_table",
                            "importMode": "table",
                            "duplicateConfirmed": False,
                            "fieldMetadata": {"name": "名称", "value": "数值"},
                        }
                    ),
                },
                HTTP_X_PROJECT_ID="1",
            )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["mode"], "table")
        resource = DataResource.objects.get(storage_path="other_domain_type_table")
        self.assertEqual(resource.domain_type, "other")
        self.assertEqual(resource.name, "其他类型资料表")

    def _csv_file(self, name: str, content: str) -> SimpleUploadedFile:
        return SimpleUploadedFile(
            name, content.encode("utf-8"), content_type="text/csv"
        )


class ExportApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="exporter", password="pass12345"
        )
        grant(self.user, ("core", "browse_data"))
        self.client.force_login(self.user)
        self.resource = DataResource.objects.create(
            name="导出测试数据",
            code="export-test-data",
            data_type=DataResource.DataType.VECTOR,
            status=DataResource.Status.ACTIVE,
            maintainer=self.user,
        )
        self.geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "空间查询结果"},
                    "geometry": {"type": "Point", "coordinates": [87.6, 43.8]},
                }
            ],
        }

    def test_export_requires_export_permission(self):
        response = self.client.post(
            "/api/catalog/export/",
            data={"epsg": 4326, "items": [self._vector_item()]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("当前角色“未分配角色”无权限", response.json()["detail"])

    def test_export_vector_geojson_zip(self):
        grant(self.user, ("catalog", "export_dataresource"))

        response = self.client.post(
            "/api/catalog/export/",
            data={"epsg": 4326, "items": [self._vector_item()]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        archive_content = b"".join(response.streaming_content)
        response.close()
        with zipfile.ZipFile(io.BytesIO(archive_content)) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), 2)
            geojson_name = next(name for name in names if name.endswith(".geojson"))
            attributes_name = next(
                name for name in names if name.endswith("-attributes.csv")
            )
            exported = json.loads(archive.read(geojson_name).decode("utf-8"))
            expected_name = exported["features"][0]["properties"]["name"]
            self.assertEqual(
                exported["features"][0]["properties"]["name"], "空间查询结果"
            )

            rows = list(
                csv.DictReader(
                    io.StringIO(archive.read(attributes_name).decode("utf-8-sig"))
                )
            )
            self.assertEqual(rows[0]["name"], expected_name)

    def test_export_rejects_oversized_json_before_starting_work(self):
        grant(self.user, ("catalog", "export_dataresource"))

        with (
            patch("apps.catalog.views.EXPORT_REQUEST_MAX_BODY_BYTES", 64),
            patch("apps.catalog.views.export_layers_zip_to_path") as export,
        ):
            response = self.client.post(
                "/api/catalog/export/",
                data=json.dumps({"padding": "x" * 128}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 413)
        export.assert_not_called()

    def test_raster_export_without_resource_id_checks_real_resource_access(self):
        grant(self.user, ("catalog", "export_dataresource"))
        restricted_resource = self._restricted_raster_resource(
            "restricted-raster-omitted"
        )
        dataset = self._raster_dataset("restricted-raster-omitted", restricted_resource)

        self._assert_raster_export_rejected(
            {
                "layerType": "raster",
                "name": "受限栅格",
                "datasetId": dataset.id,
            },
            expected_status=404,
            expected_detail="栅格数据集不存在",
        )

    def test_raster_export_rejects_forged_resource_id(self):
        grant(self.user, ("catalog", "export_dataresource"))
        raster_resource = self._accessible_raster_resource("owned-raster-mismatch")
        dataset = self._raster_dataset("owned-raster-mismatch", raster_resource)

        self._assert_raster_export_rejected(
            {
                "layerType": "raster",
                "name": "资源不匹配栅格",
                "datasetId": dataset.id,
                "resourceId": self.resource.id,
            },
            expected_status=400,
            expected_detail="resourceId 与栅格数据集不匹配",
        )

    def test_raster_export_rejects_matching_but_restricted_resource(self):
        grant(self.user, ("catalog", "export_dataresource"))
        restricted_resource = self._restricted_raster_resource(
            "restricted-raster-matching"
        )
        dataset = self._raster_dataset(
            "restricted-raster-matching", restricted_resource
        )

        self._assert_raster_export_rejected(
            {
                "layerType": "raster",
                "name": "受限栅格",
                "datasetId": dataset.id,
                "resourceId": restricted_resource.id,
            },
            expected_status=404,
            expected_detail="栅格数据集不存在",
        )

    def test_raster_export_rejects_dataset_without_data_resource(self):
        grant(self.user, ("catalog", "export_dataresource"))
        dataset = self._raster_dataset("orphan-raster", None)

        self._assert_raster_export_rejected(
            {
                "layerType": "raster",
                "name": "孤立栅格",
                "datasetId": dataset.id,
            },
            expected_status=400,
            expected_detail="栅格数据集未关联数据资源",
        )

    def test_raster_export_accepts_matching_accessible_resource(self):
        grant(self.user, ("catalog", "export_dataresource"))
        raster_resource = self._accessible_raster_resource("owned-raster-valid")
        dataset = self._raster_dataset("owned-raster-valid", raster_resource)
        item = {
            "layerType": "raster",
            "name": "可访问栅格",
            "datasetId": dataset.id,
            "resourceId": raster_resource.id,
        }

        def write_test_archive(*args, output_path, **kwargs):
            output_path.write_bytes(b"test-archive")
            return output_path

        with patch(
            "apps.catalog.views.export_layers_zip_to_path",
            side_effect=write_test_archive,
        ) as sync_export:
            sync_response = self.client.post(
                "/api/catalog/export/",
                data=json.dumps({"epsg": 4326, "items": [item]}),
                content_type="application/json",
            )
        self.assertEqual(sync_response.status_code, 200)
        sync_export.assert_called_once()
        b"".join(sync_response.streaming_content)
        sync_response.close()

        job = MagicMock()
        job.id = "authorized-raster-export"
        job.as_dict.return_value = {
            "id": "authorized-raster-export",
            "status": "queued",
        }
        with patch(
            "apps.catalog.views.start_export_job", return_value=job
        ) as async_export:
            async_response = self.client.post(
                "/api/catalog/export/async/",
                data=json.dumps({"epsg": 4326, "items": [item]}),
                content_type="application/json",
            )
        self.assertEqual(async_response.status_code, 202)
        async_export.assert_called_once()

    def _vector_item(self):
        return {
            "layerType": "vector",
            "name": "查询结果",
            "resourceId": self.resource.id,
            "geojson": self.geojson,
        }

    def _assert_raster_export_rejected(
        self,
        item,
        *,
        expected_status: int,
        expected_detail: str,
    ):
        endpoint_services = (
            (
                "/api/catalog/export/",
                "apps.catalog.views.export_layers_zip_to_path",
            ),
            (
                "/api/catalog/export/async/",
                "apps.catalog.views.start_export_job",
            ),
        )
        for endpoint, service_path in endpoint_services:
            with self.subTest(endpoint=endpoint), patch(service_path) as service:
                response = self.client.post(
                    endpoint,
                    data=json.dumps({"epsg": 4326, "items": [item]}),
                    content_type="application/json",
                )

                self.assertEqual(
                    response.status_code, expected_status, response.content
                )
                self.assertEqual(response.json()["detail"], expected_detail)
                service.assert_not_called()

    def _accessible_raster_resource(self, code: str) -> DataResource:
        return DataResource.objects.create(
            name=code,
            code=code,
            data_type=DataResource.DataType.RASTER,
            status=DataResource.Status.ACTIVE,
            maintainer=self.user,
        )

    def _restricted_raster_resource(self, code: str) -> DataResource:
        owner = get_user_model().objects.create_user(
            username=f"{code}-owner", password="pass12345"
        )
        resource = DataResource.objects.create(
            project_tag=Project.objects.create(name=code, code=code),
            name=code,
            code=code,
            data_type=DataResource.DataType.RASTER,
            status=DataResource.Status.ACTIVE,
            maintainer=owner,
        )
        restricted_group = Group.objects.create(name=f"{code}-access")
        resource.access_groups.add(restricted_group)
        return resource

    def _raster_dataset(
        self, code: str, resource: DataResource | None
    ) -> RasterDataset:
        return RasterDataset.objects.create(
            project_tag_id=resource.project_tag_id if resource else 1,
            name=code,
            code=code,
            source_relative_path=f"{code}.tif",
            data_resource=resource,
            status=RasterDataset.Status.READY,
        )


class AdminDataResourceApiTests(IsolatedCatalogStorageMixin, TestCase):
    def setUp(self):
        self.isolate_catalog_storage()
        self.user = get_user_model().objects.create_user(
            username="data-admin", password="pass12345"
        )
        grant(
            self.user,
            ("catalog", "view_dataresource"),
            ("catalog", "change_dataresource"),
            ("catalog", "delete_dataresource"),
            ("catalog", "export_dataresource"),
            ("core", "browse_data"),
        )
        self.client.force_login(self.user)
        self.group, _ = Group.objects.get_or_create(name="科研用户")
        self.distribution_category = DictionaryItem.objects.get(
            dict_type=DictionaryItem.DictType.DATA_CATEGORY,
            code="spatial",
        )
        self.remote_sensing_category = DictionaryItem.objects.get(
            dict_type=DictionaryItem.DictType.DATA_CATEGORY,
            code="spatial",
        )
        self.resource = DataResource.objects.create(
            name="存量样地数据",
            code="inventory-plots",
            data_type=DataResource.DataType.VECTOR,
            domain_type="field_survey",
            category=self.distribution_category,
            source="用户导入",
            provider="平台组",
            file_format="GPKG",
            storage_path="inventory_plots",
            status=DataResource.Status.ACTIVE,
            maintainer=self.user,
        )

    def test_admin_data_resource_list_includes_active_and_inactive_resources(self):
        self.resource.status = DataResource.Status.INACTIVE
        self.resource.save(update_fields=["status"])

        response = self.client.get("/api/admin/data/resources/?status=inactive")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["name"], "存量样地数据")
        self.assertEqual(payload["items"][0]["status"], "inactive")
        self.assertEqual(payload["items"][0]["domainType"], "field_survey")

    def test_admin_data_resource_list_summaries_ignore_pagination(self):
        inventory_group = DataResourceGroup.objects.create(name="重点监测")
        self.resource.inventory_group = inventory_group
        self.resource.size_bytes = 100
        self.resource.item_count = 10
        self.resource.save(
            update_fields=["inventory_group", "size_bytes", "item_count"]
        )
        self.resource.access_groups.add(self.group)
        for index in range(10):
            DataResource.objects.create(
                name=f"野外调查 {index}",
                code=f"inventory-field-{index}",
                data_type=DataResource.DataType.TABLE,
                domain_type="field_survey",
                category=self.distribution_category,
                size_bytes=10,
                item_count=1,
                status=DataResource.Status.ACTIVE,
                maintainer=self.user,
            )
        DataResource.objects.create(
            name="遥感禁用数据",
            code="inventory-raster-inactive",
            data_type=DataResource.DataType.RASTER,
            domain_type="remote_sensing",
            category=self.remote_sensing_category,
            size_bytes=200,
            item_count=2,
            status=DataResource.Status.INACTIVE,
            maintainer=self.user,
        )

        response = self.client.get(
            "/api/admin/data/resources/", {"current": 1, "pageSize": 10}
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["items"]), 10)
        self.assertEqual(payload["total"], 12)
        self.assertEqual(
            payload["summary"],
            {
                "total": 12,
                "activeCount": 11,
                "inactiveCount": 1,
                "restrictedCount": 0,
                "sizeBytes": 400,
                "itemCount": 22,
            },
        )
        summaries = {item["key"]: item for item in payload["groupSummaries"]}
        self.assertEqual(summaries["__all__"]["resourceCount"], 12)
        self.assertEqual(summaries["__category__:non_spatial"]["resourceCount"], 12)
        self.assertEqual(summaries["__category__:non_spatial"]["sizeBytes"], 400)
        self.assertEqual(summaries["__category__:non_spatial"]["inactiveCount"], 1)
        self.assertEqual(summaries["__unclassified__"]["resourceCount"], 0)
        self.assertEqual(
            summaries[f"__custom__:{inventory_group.id}"]["resourceCount"], 1
        )

    def test_admin_data_resource_summary_groups_pending_data_as_unclassified(self):
        self.resource.category = None
        DataResource.objects.filter(pk=self.resource.pk).update(category=None)

        response = self.client.get("/api/admin/data/resources/")

        self.assertEqual(response.status_code, 200)
        summaries = {item["key"]: item for item in response.json()["groupSummaries"]}
        self.assertEqual(summaries["__unclassified__"]["resourceCount"], 1)
        self.assertEqual(summaries["__category__:non_spatial"]["resourceCount"], 0)

    def test_admin_data_resource_groups_persist_and_clear_on_delete(self):
        create_response = self.client.post(
            "/api/admin/data/resource-groups/",
            data=json.dumps({"name": "植被调查"}),
            content_type="application/json",
        )

        self.assertEqual(create_response.status_code, 201)
        group_id = create_response.json()["id"]
        move_response = self.client.post(
            f"/api/admin/data/resources/{self.resource.id}/",
            data=json.dumps(
                {"action": "updateInventoryGroup", "inventoryGroupId": group_id}
            ),
            content_type="application/json",
        )
        list_response = self.client.get("/api/admin/data/resources/")

        self.assertEqual(move_response.status_code, 200)
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.inventory_group_id, group_id)
        payload = list_response.json()
        self.assertIn(
            {"id": group_id, "name": "植被调查"},
            [
                {"id": item["id"], "name": item["name"]}
                for item in payload["inventoryGroups"]
            ],
        )
        self.assertEqual(payload["items"][0]["inventoryGroupId"], group_id)

        rename_response = self.client.post(
            f"/api/admin/data/resource-groups/{group_id}/",
            data=json.dumps({"action": "update", "name": "样地调查"}),
            content_type="application/json",
        )
        delete_response = self.client.post(
            f"/api/admin/data/resource-groups/{group_id}/",
            data=json.dumps({"action": "delete"}),
            content_type="application/json",
        )

        self.assertEqual(rename_response.status_code, 200)
        self.assertEqual(rename_response.json()["name"], "样地调查")
        self.assertEqual(delete_response.status_code, 200)
        self.resource.refresh_from_db()
        self.assertIsNone(self.resource.inventory_group_id)
        self.assertFalse(DataResourceGroup.objects.filter(pk=group_id).exists())

    def test_status_toggle_hides_resource_from_regular_catalog(self):
        response = self.client.post(
            f"/api/admin/data/resources/{self.resource.id}/",
            data=json.dumps({"action": "setStatus", "status": "inactive"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.status, DataResource.Status.INACTIVE)
        regular_response = self.client.get("/api/catalog/resources/")
        self.assertEqual(regular_response.status_code, 200)
        regular_ids = {
            item["id"]
            for item in regular_response.json()["items"]
            if isinstance(item["id"], int)
        }
        self.assertNotIn(self.resource.id, regular_ids)
        self.assertTrue(
            OperationLog.objects.filter(
                module="数据管理",
                action="切换数据状态",
                target_type="data_resource",
                target_id=self.resource.id,
                target_code=self.resource.code,
                target_name=self.resource.name,
            ).exists()
        )

    def test_update_access_groups_and_default_visualization(self):
        response = self.client.post(
            f"/api/admin/data/resources/{self.resource.id}/",
            data=json.dumps(
                {
                    "action": "update",
                    "accessGroupIds": [self.group.id],
                    "visualization": {
                        "layerName": "默认样地点",
                        "defaultVisible": True,
                        "defaultOpacity": 72,
                        "symbolization": {"pointColor": "#2f7d62"},
                    },
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.resource.refresh_from_db()
        self.assertEqual(
            set(self.resource.access_groups.values_list("name", flat=True)),
            {SUPERADMIN_GROUP_NAME, self.group.name},
        )
        self.assertEqual(self.resource.default_visualization["defaultOpacity"], 72)
        layer = MapLayer.objects.get(data_resource=self.resource)
        self.assertEqual(layer.name, "默认样地点")
        self.assertEqual(layer.default_opacity, 72)
        self.assertEqual(layer.symbolization["pointColor"], "#2f7d62")
        self.assertEqual(
            set(layer.access_groups.values_list("name", flat=True)),
            {SUPERADMIN_GROUP_NAME, self.group.name},
        )

    def test_update_access_rejects_hidden_superadmin_group(self):
        _, superadmin_group = ensure_superadmin_defaults(create_account=False)

        response = self.client.post(
            f"/api/admin/data/resources/{self.resource.id}/",
            data=json.dumps(
                {"action": "updateAccess", "accessGroupIds": [superadmin_group.id]}
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "包含不存在或不可选择的角色")
        self.resource.refresh_from_db()
        self.assertEqual(list(self.resource.access_groups.all()), [])

    def test_data_resource_update_renames_display_name_only(self):
        layer = MapLayer.objects.create(
            name="原始默认图层",
            code="inventory-plots-layer",
            layer_type=MapLayer.LayerType.VECTOR,
            data_resource=self.resource,
        )
        original_code = self.resource.code
        original_storage_path = self.resource.storage_path

        response = self.client.post(
            f"/api/admin/data/resources/{self.resource.id}/",
            data=json.dumps({"action": "update", "name": "  重命名后数据  "}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "重命名后数据")
        self.resource.refresh_from_db()
        layer.refresh_from_db()
        self.assertEqual(self.resource.name, "重命名后数据")
        self.assertEqual(self.resource.code, original_code)
        self.assertEqual(self.resource.storage_path, original_storage_path)
        self.assertEqual(layer.name, "原始默认图层")
        self.assertTrue(
            OperationLog.objects.filter(
                module="数据管理",
                action="更新存量数据名称",
                target_type="data_resource",
                target_id=self.resource.id,
                target_code=original_code,
                target_name="重命名后数据",
            ).exists()
        )

    def test_data_resource_update_validates_rename(self):
        before_count = OperationLog.objects.count()

        empty_response = self.client.post(
            f"/api/admin/data/resources/{self.resource.id}/",
            data=json.dumps({"action": "update", "name": "   "}),
            content_type="application/json",
        )
        long_response = self.client.post(
            f"/api/admin/data/resources/{self.resource.id}/",
            data=json.dumps({"action": "update", "name": "数" * 161}),
            content_type="application/json",
        )

        self.assertEqual(empty_response.status_code, 400)
        self.assertEqual(empty_response.json()["detail"], "数据资源名称不能为空")
        self.assertEqual(long_response.status_code, 400)
        self.assertEqual(
            long_response.json()["detail"], "数据资源名称不能超过 160 个字符"
        )
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.name, "存量样地数据")
        self.assertEqual(OperationLog.objects.count(), before_count)

    def test_delete_requires_matching_confirmation_name(self):
        response = self.client.post(
            f"/api/admin/data/resources/{self.resource.id}/",
            data=json.dumps({"action": "delete", "confirmationName": "错误名称"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(DataResource.objects.filter(pk=self.resource.id).exists())

    def test_delete_removes_resource_and_logs_operation(self):
        response = self.client.post(
            f"/api/admin/data/resources/{self.resource.id}/",
            data=json.dumps(
                {"action": "delete", "confirmationName": self.resource.name}
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(DataResource.objects.filter(pk=self.resource.id).exists())
        self.assertTrue(
            OperationLog.objects.filter(
                module="数据管理",
                action="删除存量数据",
                target_type="data_resource",
                target_id=self.resource.id,
                target_code=self.resource.code,
                target_name=self.resource.name,
            ).exists()
        )

    def test_admin_data_export_supports_csv_and_xlsx(self):
        data_category = DictionaryItem.objects.create(
            dict_type="data_category",
            code="field-survey",
            name="野外调查",
        )
        inventory_group = DataResourceGroup.objects.create(name="DNA 样品")
        self.resource.domain_type = "germplasm"
        self.resource.category = data_category
        self.resource.inventory_group = inventory_group
        self.resource.data_date = date(2026, 7, 1)
        self.resource.spatial_extent = "87.600000,43.795100,87.642800,43.812450"
        self.resource.coordinate_system = "EPSG:4326"
        self.resource.description = "胡杨 DNA 样品清单"
        self.resource.quality_note = "经纬度已统一"
        self.resource.size_bytes = 232103
        self.resource.item_count = 663
        self.resource.save()
        self.resource.access_groups.add(self.group)
        MapLayer.objects.create(
            name="DNA 样品点",
            code="dna-sample-points",
            layer_type=MapLayer.LayerType.VECTOR,
            geometry_type=MapLayer.GeometryType.POINT,
            data_resource=self.resource,
        )

        csv_response = self.client.get("/api/admin/data/resources/export/?format=csv")
        xlsx_response = self.client.get("/api/admin/data/resources/export/?format=xlsx")

        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("text/csv", csv_response["Content-Type"])
        csv_text = csv_response.content.decode("utf-8-sig")
        self.assertIn("存量数据组别", csv_text)
        self.assertIn("业务数据类型", csv_text)
        self.assertIn("空间范围", csv_text)
        self.assertIn("DNA 样品", csv_text)
        self.assertIn("种质数据", csv_text)
        self.assertIn("经纬度已统一", csv_text)
        self.assertEqual(xlsx_response.status_code, 200)
        self.assertIn("spreadsheetml", xlsx_response["Content-Type"])
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(xlsx_response.content), data_only=True)
        sheet = workbook.active
        headers = [cell.value for cell in sheet[1]]
        values = dict(zip(headers, [cell.value for cell in sheet[2]], strict=True))
        self.assertEqual(values["存量数据组别"], "DNA 样品")
        self.assertEqual(values["数据类型"], "矢量空间数据")
        self.assertEqual(values["业务数据类型"], "种质数据")
        self.assertEqual(values["状态"], "启用")
        self.assertEqual(values["分类"], "地理数据")
        self.assertEqual(values["空间范围"], "87.600000,43.795100,87.642800,43.812450")
        self.assertEqual(values["默认图层"], "DNA 样品点")
        self.assertEqual(values["数据大小(B)"], 232103)
        self.assertEqual(values["数据条目数"], 663)
        self.assertEqual(sheet.freeze_panes, "A2")

    def test_admin_data_resource_list_hides_inaccessible_resources(self):
        restricted_group = Group.objects.create(name="保密数据组")
        other_user = get_user_model().objects.create_user(
            username="restricted-owner", password="pass12345"
        )
        restricted_resource = DataResource.objects.create(
            project_tag=Project.objects.create(name="私有数据", code="hidden-resource"),
            name="不可见样地数据",
            code="restricted-inventory-plots",
            data_type=DataResource.DataType.VECTOR,
            storage_path="restricted_inventory_plots",
            maintainer=other_user,
        )
        restricted_resource.access_groups.add(restricted_group)

        response = self.client.get("/api/admin/data/resources/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        item_ids = {item["id"] for item in payload["items"]}
        self.assertIn(self.resource.id, item_ids)
        self.assertNotIn(restricted_resource.id, item_ids)

    def test_platform_admin_can_list_and_maintain_all_data_resources(self):
        ensure_superadmin_defaults(create_account=False)
        platform_group = Group.objects.get(name=PLATFORM_ADMIN_GROUP_NAME)
        platform_admin = get_user_model().objects.create_user(
            username="inventory-platform-admin", password="pass12345"
        )
        platform_admin.groups.add(platform_group)
        restricted_group = Group.objects.create(name="平台管理员全局数据测试组")
        other_user = get_user_model().objects.create_user(
            username="platform-admin-data-owner", password="pass12345"
        )
        restricted_resource = DataResource.objects.create(
            name="平台管理员维护数据",
            code="platform-admin-maintained-resource",
            data_type=DataResource.DataType.TABLE,
            storage_path="platform_admin_maintained_resource",
            maintainer=other_user,
        )
        restricted_resource.access_groups.add(restricted_group)
        self.client.force_login(platform_admin)

        list_response = self.client.get("/api/admin/data/resources/")
        update_response = self.client.post(
            f"/api/admin/data/resources/{restricted_resource.id}/",
            data=json.dumps({"action": "setStatus", "status": "inactive"}),
            content_type="application/json",
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertIn(
            restricted_resource.id,
            {item["id"] for item in list_response.json()["items"]},
        )
        self.assertEqual(update_response.status_code, 200)
        restricted_resource.refresh_from_db()
        self.assertEqual(restricted_resource.status, DataResource.Status.INACTIVE)

    def test_admin_data_resource_list_hides_superadmin_uploader_identity(self):
        superadmin_user, superadmin_group = ensure_superadmin_defaults()
        self.user.groups.add(self.group)
        protected_resource = DataResource.objects.create(
            name="超级管理员维护数据",
            code="superadmin-maintained-resource",
            data_type=DataResource.DataType.TABLE,
            storage_path="superadmin_table",
            maintainer=superadmin_user,
        )
        protected_resource.access_groups.add(self.group, superadmin_group)

        response = self.client.get("/api/admin/data/resources/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        resource_item = next(
            item for item in payload["items"] if item["id"] == protected_resource.id
        )
        self.assertEqual(resource_item["maintainer"], "")
        self.assertIsNone(resource_item["uploader"])
        self.assertNotIn(
            SUPERADMIN_GROUP_NAME,
            {group["name"] for group in resource_item["accessGroups"]},
        )
        self.assertNotIn(
            SUPERADMIN_GROUP_NAME,
            {group["name"] for group in payload["availableAccessGroups"]},
        )

    def test_import_access_group_options_hide_superadmin_from_django_superuser(self):
        _, superadmin_group = ensure_superadmin_defaults(create_account=False)
        django_superuser = get_user_model().objects.create_superuser(
            username="import-options-django-superuser",
            password="pass12345",
        )
        visible_group = Group.objects.create(name="导入可选角色")
        self.client.force_login(django_superuser)

        response = self.client.get("/api/admin/data/resources/?current=1&pageSize=1")

        self.assertEqual(response.status_code, 200)
        option_names = {
            item["name"] for item in response.json()["availableAccessGroups"]
        }
        self.assertIn(visible_group.name, option_names)
        self.assertNotIn(SUPERADMIN_GROUP_NAME, option_names)
        self.assertNotIn(
            superadmin_group.id,
            {item["id"] for item in response.json()["availableAccessGroups"]},
        )

    def test_import_access_group_options_hide_superadmin_from_superadmin_user(self):
        superadmin_user, superadmin_group = ensure_superadmin_defaults()
        grant(superadmin_user, ("catalog", "view_dataresource"))
        visible_group = Group.objects.create(name="超级管理员导入可选角色")
        self.resource.access_groups.add(superadmin_group, visible_group)
        self.client.force_login(superadmin_user)

        response = self.client.get("/api/admin/data/resources/?current=1&pageSize=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        option_names = {item["name"] for item in payload["availableAccessGroups"]}
        self.assertIn(visible_group.name, option_names)
        self.assertNotIn(SUPERADMIN_GROUP_NAME, option_names)
        self.assertNotIn(
            superadmin_group.id,
            {item["id"] for item in payload["availableAccessGroups"]},
        )
        resource_item = next(
            item for item in payload["items"] if item["id"] == self.resource.id
        )
        self.assertEqual(
            {item["id"] for item in resource_item["accessGroups"]},
            {visible_group.id},
        )

    def test_admin_data_export_hides_inaccessible_resources(self):
        restricted_group = Group.objects.create(name="导出保密数据组")
        other_user = get_user_model().objects.create_user(
            username="restricted-export-owner", password="pass12345"
        )
        restricted_resource = DataResource.objects.create(
            project_tag=Project.objects.create(name="私有数据", code="hidden-resource"),
            name="导出不可见样地数据",
            code="restricted-export-inventory-plots",
            data_type=DataResource.DataType.VECTOR,
            storage_path="restricted_export_inventory_plots",
            maintainer=other_user,
        )
        restricted_resource.access_groups.add(restricted_group)

        response = self.client.get("/api/admin/data/resources/export/?format=csv")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8-sig")
        self.assertIn("存量样地数据", body)
        self.assertNotIn("导出不可见样地数据", body)

    def test_admin_data_resource_update_hides_inaccessible_resource(self):
        restricted_group = Group.objects.create(name="修改保密数据组")
        other_user = get_user_model().objects.create_user(
            username="restricted-change-owner", password="pass12345"
        )
        restricted_resource = DataResource.objects.create(
            project_tag=Project.objects.create(name="私有数据", code="hidden-resource"),
            name="修改不可见样地数据",
            code="restricted-change-inventory-plots",
            data_type=DataResource.DataType.VECTOR,
            storage_path="restricted_change_inventory_plots",
            maintainer=other_user,
        )
        restricted_resource.access_groups.add(restricted_group)

        response = self.client.post(
            f"/api/admin/data/resources/{restricted_resource.id}/",
            data=json.dumps({"action": "setStatus", "status": "inactive"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        restricted_resource.refresh_from_db()
        self.assertEqual(restricted_resource.status, DataResource.Status.ACTIVE)

    def test_uploader_can_list_own_resources_and_update_access_only(self):
        uploader = get_user_model().objects.create_user(
            username="resource-uploader", password="pass12345"
        )
        other = get_user_model().objects.create_user(
            username="other-uploader", password="pass12345"
        )
        grant(uploader, ("catalog", "add_dataresource"))
        ensure_guest_user()
        _, superadmin_group = ensure_superadmin_defaults(create_account=False)
        guest_group = Group.objects.get(name=GUEST_GROUP_NAME)
        own_resource = DataResource.objects.create(
            name="上传者自己的数据",
            code="uploader-own-resource",
            data_type=DataResource.DataType.TABLE,
            storage_path="uploader_table",
            maintainer=uploader,
        )
        DataResource.objects.create(
            name="他人上传数据",
            code="other-uploaded-resource",
            data_type=DataResource.DataType.TABLE,
            storage_path="other_table",
            maintainer=other,
        )
        self.client.force_login(uploader)

        list_response = self.client.get("/api/admin/data/resources/")

        self.assertEqual(list_response.status_code, 200)
        payload = list_response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["id"], own_resource.id)
        self.assertTrue(payload["items"][0]["canManageAccess"])
        self.assertNotIn(
            SUPERADMIN_GROUP_NAME,
            {item["name"] for item in payload["availableAccessGroups"]},
        )

        access_response = self.client.post(
            f"/api/admin/data/resources/{own_resource.id}/",
            data=json.dumps(
                {"action": "updateAccess", "accessGroupIds": [guest_group.id]}
            ),
            content_type="application/json",
        )
        status_response = self.client.post(
            f"/api/admin/data/resources/{own_resource.id}/",
            data=json.dumps({"action": "setStatus", "status": "inactive"}),
            content_type="application/json",
        )

        self.assertEqual(access_response.status_code, 200)
        own_resource.refresh_from_db()
        self.assertEqual(
            set(own_resource.access_groups.values_list("id", flat=True)),
            {guest_group.id, superadmin_group.id},
        )
        self.assertEqual(status_response.status_code, 403)

    def test_data_resource_update_requires_change_permission(self):
        user = get_user_model().objects.create_user(
            username="no-data-change", password="pass12345"
        )
        user.groups.add(self.group)
        self.resource.access_groups.add(self.group)
        self.client.force_login(user)

        response = self.client.post(
            f"/api/admin/data/resources/{self.resource.id}/",
            data=json.dumps({"action": "update"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            OperationLog.objects.filter(
                user=user,
                module="数据管理",
                action="更新存量数据",
                target_id=self.resource.id,
            ).exists()
        )

    def test_data_resource_update_rejects_empty_change(self):
        before_count = OperationLog.objects.count()

        response = self.client.post(
            f"/api/admin/data/resources/{self.resource.id}/",
            data=json.dumps({"action": "update"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "没有可更新的数据资源字段")
        self.assertEqual(OperationLog.objects.count(), before_count)


def grant(user, *specs):
    for app_label, codename in specs:
        permission = Permission.objects.get(
            content_type__app_label=app_label, codename=codename
        )
        user.user_permissions.add(permission)
