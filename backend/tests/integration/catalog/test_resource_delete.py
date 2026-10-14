import json
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import DatabaseError, connection, transaction
from django.test import RequestFactory, TransactionTestCase, override_settings
from shapely.geometry import Point

from apps.agent.models import AgentCheckpoint, AgentWorkflow
from apps.audit.models import OperationLog
from apps.catalog.models import (
    DataCatalog,
    DataResource,
    DictionaryItem,
    MapComposition,
    MapCompositionVersion,
    MapLayer,
    ResultArtifact,
    VectorDataset,
    WorkspaceScene,
)
from apps.compute.models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeImport,
    ComputeInput,
    ComputeOutput,
    ComputeTask,
)
from apps.core.storage import (
    research_path,
    table_data_path,
    vector_geopackage_path,
    vector_original_path,
)
from apps.catalog.resource_management import delete_resource
from apps.catalog.vector_storage import GEOPACKAGE_WRITE_LOCK
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project, ProjectMembership
from apps.raster.models import RasterBand, RasterDataset, RasterStyle
from apps.raster.services.jobs import (
    _JOBS,
    _LOCK,
    _fail_job,
    _finish_job,
    _set_job_running,
    start_export_job,
    start_render_job,
)
from apps.standards.models import ResourceDomain, SourceDataset


class ResourceDeleteFixture(TransactionTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.root = root
        override = override_settings(
            PROJECT_CONFIG=replace(
                settings.PROJECT_CONFIG,
                app_data=root / "app",
                research_data_root=root / "research",
            )
        )
        override.enable()
        self.addCleanup(override.disable)
        self.user = get_user_model().objects.create_user(
            "catalog-delete-user", password="pass12345"
        )
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="catalog",
                codename="delete_dataresource",
            )
        )
        self.client.force_login(self.user)

    def resource(self, code="delete-data", **kwargs):
        return DataResource.objects.create(
            name=f"资源 {code}",
            code=code,
            **{"data_type": "document", "maintainer": self.user, **kwargs},
        )

    def delete(self, ids, **headers):
        return self.client.post(
            "/api/catalog/resources/delete/",
            json.dumps({"resourceIds": ids, "confirmed": True}),
            content_type="application/json",
            HTTP_X_PROJECT_ID="1",
            **headers,
        )

    def write(self, path, content="owned content"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def task(self, resource):
        algorithm = AlgorithmResource.objects.create(
            identifier="delete-check", name="检查", created_by=self.user
        )
        version = AlgorithmVersion.objects.create(
            algorithm=algorithm, version="1", checksum="x", package_path="x"
        )
        task = ComputeTask.objects.create(
            name="已有计算",
            owner=self.user,
            version=version,
            idempotency_key="existing-task",
            request_hash="x",
            status="succeeded",
        )
        ComputeInput.objects.create(task=task, key="image", resource=resource)
        return task


class ResourceDeleteTests(ResourceDeleteFixture):
    def test_requires_login_and_delete_permission(self):
        item = self.resource()
        self.client.logout()
        self.assertEqual(self.delete([item.id]).status_code, 401)
        user = get_user_model().objects.create_user("no-delete", password="pass12345")
        self.client.force_login(user)
        self.assertEqual(self.delete([item.id]).status_code, 403)
        self.assertTrue(DataResource.objects.filter(pk=item.id).exists())

    def test_strict_request_validation_and_confirmation(self):
        invalid = [
            {"resourceIds": [], "confirmed": True},
            {"resourceIds": [True], "confirmed": True},
            {"resourceIds": [0], "confirmed": True},
            {"resourceIds": ["1"], "confirmed": True},
            {"resourceIds": [1] * 101, "confirmed": True},
            {"resourceIds": [1], "confirmed": False},
            {"resourceIds": [1], "confirmed": True, "path": "other"},
            [],
        ]
        for body in invalid:
            with self.subTest(body=body):
                response = self.client.post(
                    "/api/catalog/resources/delete/",
                    json.dumps(body),
                    content_type="application/json",
                    HTTP_X_PROJECT_ID="1",
                )
                self.assertEqual(response.status_code, 400)

    def test_explicit_project_required_before_valid_delete(self):
        item = self.resource()
        response = self.client.post(
            "/api/catalog/resources/delete/",
            json.dumps({"resourceIds": [item.id], "confirmed": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("项目", response.json()["detail"])
        self.assertTrue(DataResource.objects.filter(pk=item.id).exists())

    def test_partial_success_duplicate_and_repeat(self):
        item = self.resource()
        response = self.delete([item.id, item.id, 999999])
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["deletedIds"], [item.id])
        self.assertEqual((payload["deletedCount"], payload["failedCount"]), (1, 1))
        self.assertEqual(payload["items"][0]["name"], item.name)
        self.assertEqual(payload["items"][1]["name"], None)
        self.assertEqual(
            self.delete([item.id]).json()["items"][0]["status"], "not_found"
        )
        self.assertEqual(
            OperationLog.objects.filter(
                target_type="data_resource", target_id=item.id
            ).count(),
            1,
        )

    def test_scanned_file_and_metadata_are_really_deleted(self):
        path = self.write(table_data_path("sample.csv"), "a,b\n1,2")
        item = self.resource(
            data_type="table",
            file_format="CSV",
            storage_path="table/sample.csv",
            source="非地理数据目录扫描",
        )
        catalog = DataCatalog.objects.create(name="目录", code="delete-dir")
        catalog.resources.add(item)
        ResourceDomain.objects.create(resource=item, domain_type="other")
        SourceDataset.objects.create(resource=item, source_file_name="sample.csv")
        result = self.delete([item.id]).json()["items"][0]
        self.assertEqual(result["status"], "deleted")
        self.assertFalse(path.exists())
        self.assertFalse(catalog.resources.exists())
        self.assertFalse(ResourceDomain.objects.filter(resource_id=item.id).exists())
        self.assertFalse(SourceDataset.objects.exists())

    def test_sqlite_table_and_column_metadata_deleted_other_table_preserved(self):
        path = table_data_path("data.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.executescript(
                "CREATE TABLE owned (a TEXT); INSERT INTO owned VALUES ('x'); CREATE TABLE other (a TEXT); CREATE TABLE data_columns (table_name TEXT, column_name TEXT); INSERT INTO data_columns VALUES ('owned','a');"
            )
        item = self.resource(
            data_type="table", file_format="SQLITE", storage_path="owned"
        )
        self.assertEqual(self.delete([item.id]).json()["deletedCount"], 1)
        with sqlite3.connect(path) as db:
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
            self.assertNotIn("owned", names)
            self.assertIn("other", names)
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM data_columns").fetchone()[0], 0
            )

    def test_real_geopackage_layer_rtree_archive_and_derived_records_deleted(self):
        path = vector_geopackage_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        gpd.GeoDataFrame({"kind": ["a"]}, geometry=[Point(1, 2)], crs=4326).to_file(
            path, layer="owned", driver="GPKG"
        )
        gpd.GeoDataFrame({"kind": ["b"]}, geometry=[Point(3, 4)], crs=4326).to_file(
            path, layer="other", driver="GPKG", mode="a"
        )
        item = self.resource(
            data_type="vector", file_format="GPKG", storage_path="owned"
        )
        layer = MapLayer.objects.create(
            name="图层",
            code="owned-layer",
            layer_type="vector",
            data_resource=item,
            source_path="owned",
        )
        archive = self.write(vector_original_path("unique/source.zip"))
        dataset = VectorDataset.objects.create(
            resource=item,
            source_file_name="source.zip",
            source_format="shp",
            source_archive_path="unique/source.zip",
        )
        self.assertEqual(self.delete([item.id]).json()["deletedCount"], 1)
        self.assertFalse(archive.exists())
        self.assertFalse(MapLayer.objects.filter(pk=layer.id).exists())
        self.assertFalse(VectorDataset.objects.filter(pk=dataset.id).exists())
        with sqlite3.connect(path) as db:
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
            self.assertNotIn("owned", names)
            self.assertFalse(any(name.startswith("rtree_owned_") for name in names))
            self.assertEqual(
                db.execute("SELECT table_name FROM gpkg_contents").fetchall(),
                [("other",)],
            )
        self.assertEqual(len(gpd.read_file(path, layer="other")), 1)

    def test_owner_only_and_cross_project_do_not_leak_or_delete(self):
        owner = get_user_model().objects.create_user("private-owner")
        hidden = self.resource("hidden", maintainer=owner, owner_only=True)
        project = Project.objects.create(name="其他项目", code="delete-other")
        foreign = self.resource("foreign", project_tag=project)
        ProjectMembership.objects.create(project=project, user=self.user)
        payload = self.delete([hidden.id, foreign.id]).json()
        self.assertEqual(payload["deletedCount"], 0)
        self.assertTrue(
            all(
                row["status"] == "not_found" and row["name"] is None
                for row in payload["items"]
            )
        )
        self.assertEqual(
            DataResource.objects.filter(pk__in=[hidden.id, foreign.id]).count(), 2
        )

    def test_owner_and_superuser_can_delete_owner_only(self):
        item = self.resource(owner_only=True)
        self.assertEqual(self.delete([item.id]).json()["deletedCount"], 1)
        owner = get_user_model().objects.create_user("another-owner")
        item = self.resource("another-private", maintainer=owner, owner_only=True)
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.assertEqual(self.delete([item.id]).json()["deletedCount"], 1)

    def test_same_relative_name_other_project_does_not_preserve_owned_file(self):
        path = self.write(table_data_path("shared.csv"))
        item = self.resource(storage_path="table/shared.csv")
        project = Project.objects.create(name="共享登记", code="shared-registration")
        other = self.resource(
            "shared-other", storage_path="table/shared.csv", project_tag=project
        )
        result = self.delete([item.id]).json()["items"][0]
        self.assertEqual(result["status"], "deleted")
        self.assertNotIn("共用", result["detail"])
        self.assertFalse(path.exists())
        self.assertTrue(DataResource.objects.filter(pk=other.id).exists())

    def test_external_and_traversal_paths_blocked_without_touching_source(self):
        path = self.write(self.root / "upstream.txt")
        item = self.resource(storage_path=str(path))
        result = self.delete([item.id]).json()["items"][0]
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(path.exists())
        item.storage_path = "../upstream.txt"
        item.save()
        self.assertEqual(self.delete([item.id]).json()["items"][0]["status"], "blocked")

    def test_compute_input_and_registered_result_protected(self):
        item = self.resource()
        task = self.task(item)
        self.assertIn("计算任务", self.delete([item.id]).json()["items"][0]["detail"])
        result = self.resource("registered-result")
        output = ComputeOutput.objects.create(
            task=task,
            key="out",
            label="out",
            kind="table",
            file_name="out.csv",
            path="out.csv",
            size_bytes=1,
            checksum="x",
        )
        ComputeImport.objects.create(
            output=output,
            requested_by=self.user,
            name="入库",
            resource=result,
            status="ready",
        )
        self.assertEqual(
            self.delete([result.id]).json()["items"][0]["status"], "blocked"
        )

    def test_saved_workspace_and_map_version_references_protected(self):
        item = self.resource()
        workspace = WorkspaceScene.objects.create(
            owner=self.user,
            name="研究工程",
            kind="project",
            snapshot={"groups": [{"children": [{"sourceResource": {"id": item.id}}]}]},
        )
        self.assertIn("工程", self.delete([item.id]).json()["items"][0]["detail"])
        workspace.snapshot = {}
        workspace.save()
        composition = MapComposition.objects.create(
            owner=self.user, project=workspace, name="专题图"
        )
        MapCompositionVersion.objects.create(
            composition=composition,
            version_number=1,
            format="png",
            width_px=1,
            height_px=1,
            preview_path="x",
            artifact_path="x",
            resource_manifest=[{"id": item.id}],
        )
        self.assertEqual(self.delete([item.id]).json()["items"][0]["status"], "blocked")

    def test_workflow_and_report_checkpoint_references_protected(self):
        item = self.resource()
        workflow = AgentWorkflow.objects.create(
            owner=self.user,
            goal="检查",
            model="test",
            idempotency_key="delete-wf",
            resource_ids=[item.id],
            status="succeeded",
        )
        self.assertIn("科研工作流", self.delete([item.id]).json()["items"][0]["detail"])
        workflow.resource_ids = []
        workflow.save()
        AgentCheckpoint.objects.create(
            workflow=workflow,
            node="report",
            state={"report": {"resourceId": item.id}},
            state_hash="x",
        )
        self.assertEqual(self.delete([item.id]).json()["items"][0]["status"], "blocked")

    def test_raster_files_package_band_style_cache_deleted(self):
        item = self.resource(data_type="raster", storage_path="uploaded/a/image.tif")
        dataset = RasterDataset.objects.create(
            name="影像",
            code="delete-raster",
            data_resource=item,
            source_relative_path="uploaded/a/image.tif",
            processed_relative_path="uploaded/a/image.tif",
            source_metadata_relative_path="source/image.json",
            processed_metadata_relative_path="processed/image.json",
            source_manifest=[{"name": "image.tif"}, {"name": "image.tif.aux.xml"}],
            status="ready",
        )
        files = [
            self.write(research_path("raster/original", "uploaded/a", name))
            for name in ("image.tif", "image.tif.aux.xml", "manifest.json")
        ]
        files += [
            self.write(research_path("raster/preprocessed", "uploaded/a/image.tif")),
            self.write(research_path("raster/metadata", "source/image.json")),
            self.write(research_path("raster/metadata", "processed/image.json")),
        ]
        cache = self.write(
            settings.PROJECT_CONFIG.app_data
            / "cache/raster-tiles/v1"
            / str(dataset.id)
            / "style.mbtiles"
        )
        RasterBand.objects.create(dataset=dataset, band_index=1)
        RasterStyle.objects.create(dataset=dataset, style_hash="a")
        self.assertEqual(self.delete([item.id]).json()["deletedCount"], 1)
        self.assertFalse(any(path.exists() for path in [*files, cache]))
        self.assertFalse(RasterDataset.objects.filter(pk=dataset.id).exists())
        self.assertFalse(RasterBand.objects.filter(dataset_id=dataset.id).exists())
        self.assertFalse(RasterStyle.objects.filter(dataset_id=dataset.id).exists())

    def test_raster_processing_blocked(self):
        item = self.resource(data_type="raster")
        RasterDataset.objects.create(
            name="处理",
            code="processing-raster",
            source_relative_path="a.tif",
            data_resource=item,
            status="processing",
        )
        self.assertEqual(self.delete([item.id]).json()["items"][0]["status"], "blocked")

    def test_storage_failure_and_protect_race_restore_file_and_metadata(self):
        path = self.write(table_data_path("rollback.md"))
        item = self.resource(storage_path="table/rollback.md")
        with patch(
            "apps.catalog.resource_storage_delete.Path.replace",
            side_effect=OSError("locked"),
        ):
            self.assertEqual(
                self.delete([item.id]).json()["items"][0]["status"], "failed"
            )
        self.assertTrue(path.exists())
        self.task(item)
        with patch(
            "apps.catalog.resource_management.resource_reference_reasons",
            return_value=[],
        ):
            self.assertEqual(
                self.delete([item.id]).json()["items"][0]["status"], "blocked"
            )
        self.assertTrue(path.exists())
        self.assertTrue(DataResource.objects.filter(pk=item.id).exists())

    def test_existing_admin_delete_uses_same_guard(self):
        item = self.resource()
        self.task(item)
        response = self.client.post(
            f"/api/admin/data/resources/{item.id}/",
            json.dumps({"action": "delete", "confirmationName": item.name}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("计算任务", response.json()["detail"])
        self.assertTrue(DataResource.objects.filter(pk=item.id).exists())


class ResourceDeleteAtomicTests(ResourceDeleteFixture):
    def commit_failure_delete(self, item):
        # Bypass unrelated middleware activity writes so the injected failure
        # happens at the resource transaction's actual final commit.
        request = RequestFactory().post("/api/catalog/resources/delete/")
        request.user = self.user
        with project_scope(ProjectScope((1,), 1)):
            with patch.object(
                connection, "commit", side_effect=DatabaseError("commit failed")
            ):
                return delete_resource(request, item.id)

    def test_metadata_commit_failure_rolls_back_attached_sqlite_table(self):
        path = table_data_path("data.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.executescript(
                "CREATE TABLE owned (a TEXT); INSERT INTO owned VALUES ('kept'); CREATE TABLE data_columns (table_name TEXT); INSERT INTO data_columns VALUES ('owned');"
            )
        item = self.resource(
            data_type="table", file_format="SQLITE", storage_path="owned"
        )
        result = self.commit_failure_delete(item)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(DataResource.objects.filter(pk=item.id).exists())
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("SELECT a FROM owned").fetchall(), [("kept",)])
            self.assertEqual(
                db.execute("SELECT table_name FROM data_columns").fetchall(),
                [("owned",)],
            )
        self.assertFalse(
            any(
                row[1].startswith("catalog_delete_")
                for row in connection.cursor()
                .execute("PRAGMA database_list")
                .fetchall()
            )
        )

    def test_metadata_commit_failure_restores_staged_original(self):
        path = self.write(table_data_path("original.md"))
        item = self.resource(storage_path="table/original.md")
        result = self.commit_failure_delete(item)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(encoding="utf-8"), "owned content")
        self.assertFalse(list(path.parent.glob("*.delete-*")))
        self.assertTrue(DataResource.objects.filter(pk=item.id).exists())

    def test_nested_application_transaction_rejected_before_mutation(self):
        path = self.write(table_data_path("nested.md"))
        item = self.resource(storage_path="table/nested.md")
        with transaction.atomic():
            result = self.delete([item.id]).json()["items"][0]
        self.assertEqual(result["status"], "failed")
        self.assertTrue(path.exists())
        self.assertTrue(DataResource.objects.filter(pk=item.id).exists())

    def test_result_reference_blocked_other_selection_still_deleted(self):
        item = self.resource()
        other = self.resource("free-data")
        category = DictionaryItem.objects.create(
            dict_type="data_category", code="result-test", name="成果测试"
        )
        artifact = ResultArtifact.objects.create(
            owner=self.user,
            name="正式成果",
            category=category,
            file_path="a.md",
            file_name="a.md",
        )
        artifact.related_resources.add(item)
        result = self.delete([item.id, other.id]).json()
        self.assertEqual(result["deletedIds"], [other.id])
        self.assertIn("成果展示", result["items"][0]["detail"])
        self.assertTrue(artifact.related_resources.filter(pk=item.id).exists())

    def test_shared_vector_layer_keeps_other_resource_and_table(self):
        path = vector_geopackage_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        gpd.GeoDataFrame({"kind": ["a"]}, geometry=[Point(1, 2)], crs=4326).to_file(
            path, layer="shared", driver="GPKG"
        )
        item = self.resource(data_type="vector", storage_path="shared")
        other = self.resource(
            "shared-vector", data_type="vector", storage_path="shared"
        )
        result = self.delete([item.id]).json()["items"][0]
        self.assertEqual(result["status"], "deleted")
        self.assertIn("共用", result["detail"])
        self.assertTrue(DataResource.objects.filter(pk=other.id).exists())
        self.assertEqual(len(gpd.read_file(path, layer="shared")), 1)

    def test_shared_processed_raster_preserved_exclusive_source_removed(self):
        item = self.resource(data_type="raster", storage_path="shared.tif")
        other = self.resource(
            "other-raster", data_type="raster", storage_path="shared.tif"
        )
        RasterDataset.objects.create(
            name="one",
            code="one",
            data_resource=item,
            source_relative_path="one.tif",
            processed_relative_path="shared.tif",
            status="ready",
        )
        second = RasterDataset.objects.create(
            name="two",
            code="two",
            data_resource=other,
            source_relative_path="two.tif",
            processed_relative_path="shared.tif",
            status="ready",
        )
        source = self.write(research_path("raster/original", "one.tif"))
        other_source = self.write(research_path("raster/original", "two.tif"))
        shared = self.write(research_path("raster/preprocessed", "shared.tif"))
        result = self.delete([item.id]).json()["items"][0]
        self.assertEqual(result["status"], "deleted")
        self.assertFalse(source.exists())
        self.assertTrue(other_source.exists())
        self.assertTrue(shared.exists())
        self.assertTrue(RasterDataset.objects.filter(pk=second.id).exists())

    def test_unified_database_cannot_be_removed_as_document(self):
        path = self.write(table_data_path("data.sqlite"), "database content")
        item = self.resource(storage_path="table/data.sqlite")
        result = self.delete([item.id]).json()["items"][0]
        self.assertEqual(result["status"], "blocked")
        self.assertIn("统一数据库", result["detail"])
        self.assertTrue(path.exists())

    def test_cleanup_failure_reports_retained_isolated_file(self):
        path = self.write(table_data_path("cleanup.md"))
        item = self.resource(storage_path="table/cleanup.md")
        with patch(
            "apps.catalog.resource_storage_delete.Path.unlink",
            side_effect=OSError("locked"),
        ):
            result = self.delete([item.id]).json()["items"][0]
        self.assertEqual(result["status"], "deleted")
        self.assertIn("隔离文件清理失败", result["detail"])
        self.assertFalse(path.exists())
        self.assertEqual(len(list(path.parent.glob("*.delete-*"))), 1)
        self.assertFalse(DataResource.objects.filter(pk=item.id).exists())

    def test_case_variant_shared_sqlite_table_preserved(self):
        path = table_data_path("data.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE owned (a TEXT)")
            db.execute("INSERT INTO owned VALUES ('kept')")
        item = self.resource(
            data_type="table", file_format="SQLITE", storage_path="owned"
        )
        other = self.resource(
            "case-alias", data_type="table", file_format="SQLITE", storage_path="OWNED"
        )
        result = self.delete([item.id]).json()["items"][0]
        self.assertEqual(result["status"], "deleted")
        self.assertIn("共用", result["detail"])
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("SELECT a FROM owned").fetchall(), [("kept",)])
        self.assertTrue(DataResource.objects.filter(pk=other.id).exists())

    def test_case_variant_internal_metadata_table_blocked(self):
        path = table_data_path("data.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE data_columns (table_name TEXT)")
        item = self.resource(
            data_type="table", file_format="SQLITE", storage_path="DATA_COLUMNS"
        )
        self.assertEqual(self.delete([item.id]).json()["items"][0]["status"], "blocked")
        with sqlite3.connect(path) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM data_columns").fetchone()[0], 0
            )

    def test_same_project_shared_file_preserved(self):
        path = self.write(table_data_path("shared.md"))
        item = self.resource(storage_path="table/shared.md")
        self.resource("shared-alias", storage_path="shared.md")
        self.assertIn("共用", self.delete([item.id]).json()["items"][0]["detail"])
        self.assertTrue(path.exists())

    def test_unrelated_bad_raster_path_does_not_block_file_deletion(self):
        self.resource(
            "invalid-raster", data_type="raster", storage_path="../outside.tif"
        )
        path = self.write(table_data_path("valid.md"))
        item = self.resource(storage_path="valid.md")
        self.assertEqual(self.delete([item.id]).json()["deletedCount"], 1)
        self.assertFalse(path.exists())

    def test_failed_file_restore_returns_feedback_and_releases_storage_lock(self):
        path = self.write(table_data_path("restore.md"))
        item = self.resource(storage_path="restore.md")
        original_replace = Path.replace

        def replace_file(source, target):
            if ".delete-" in source.name:
                raise OSError("restore locked")
            return original_replace(source, target)

        with patch("apps.catalog.resource_storage_delete.Path.replace", replace_file):
            result = self.commit_failure_delete(item)
        self.assertEqual(result["status"], "failed")
        self.assertIn("恢复未完成", result["detail"])
        self.assertTrue(DataResource.objects.filter(pk=item.id).exists())
        self.assertEqual(len(list(path.parent.glob("*.delete-*"))), 1)

        def probe_lock():
            acquired = GEOPACKAGE_WRITE_LOCK.acquire(blocking=False)
            if acquired:
                GEOPACKAGE_WRITE_LOCK.release()
            return acquired

        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertTrue(pool.submit(probe_lock).result(timeout=2))

    def test_case_variant_vector_uses_actual_name_to_remove_rtree_and_metadata(self):
        path = vector_geopackage_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = gpd.GeoDataFrame({"kind": ["a"]}, geometry=[Point(1, 2)], crs=4326)
        frame.to_file(path, layer="Owned", driver="GPKG")
        frame.to_file(path, layer="other", driver="GPKG", mode="a")
        item = self.resource(data_type="vector", storage_path="owned")
        self.assertEqual(self.delete([item.id]).json()["deletedCount"], 1)
        with sqlite3.connect(path) as db:
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
            self.assertNotIn("Owned", names)
            self.assertFalse(any(name.startswith("rtree_Owned_") for name in names))
            self.assertEqual(
                db.execute("SELECT table_name FROM gpkg_contents").fetchall(),
                [("other",)],
            )
            self.assertEqual(
                db.execute("SELECT table_name FROM gpkg_geometry_columns").fetchall(),
                [("other",)],
            )
        self.assertEqual(len(gpd.read_file(path, layer="other")), 1)

    def test_archive_path_alias_preserves_shared_file(self):
        path = self.write(vector_original_path("unique/source.zip"))
        item = self.resource(data_type="vector", storage_path="first")
        other = self.resource(
            "archive-alias", data_type="vector", storage_path="second"
        )
        for resource, relative in (
            (item, "unique/source.zip"),
            (other, "unique/./source.zip"),
        ):
            VectorDataset.objects.create(
                resource=resource,
                source_file_name="source.zip",
                source_format="shp",
                source_archive_path=relative,
            )
        result = self.delete([item.id]).json()["items"][0]
        self.assertEqual(result["status"], "deleted")
        self.assertIn("共用", result["detail"])
        self.assertTrue(path.exists())
        self.assertTrue(VectorDataset.objects.filter(resource=other).exists())

    def test_csv_file_name_does_not_alias_a_sqlite_table(self):
        path = table_data_path("data.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE owned (a TEXT)")
        item = self.resource(
            data_type="table", file_format="SQLITE", storage_path="owned"
        )
        self.resource(
            "csv-alias", data_type="table", file_format="CSV", storage_path="owned"
        )
        self.assertEqual(self.delete([item.id]).json()["deletedCount"], 1)
        with sqlite3.connect(path) as db:
            self.assertNotIn(
                "owned",
                {row[0] for row in db.execute("SELECT name FROM sqlite_master")},
            )

    def test_real_render_submission_protects_queued_running_and_releases_ready(self):
        item = self.resource(data_type="raster")
        layer = MapLayer.objects.create(
            name="渲染图层",
            code="render-delete-check",
            layer_type="raster",
            data_resource=item,
        )
        with (
            patch(
                "apps.raster.services.jobs.reconcile_interrupted_jobs",
                return_value=True,
            ),
            patch("apps.raster.services.jobs._submit_job"),
        ):
            job = start_render_job(layer_id=layer.id, dataset_id=None, rules={})
        self.addCleanup(self.remove_job_cache, job.id)
        self.assertEqual(job.result, {"inputRefs": [{"layerId": layer.id}]})
        self.assertIn("处理任务", self.delete([item.id]).json()["items"][0]["detail"])
        _set_job_running(job.id, "生成瓦片", 10)
        self.assertEqual(self.delete([item.id]).json()["items"][0]["status"], "blocked")
        _finish_job(job.id, {"styleHash": "done"}, "ready")
        self.assertEqual(self.delete([item.id]).json()["deletedCount"], 1)

    def test_real_export_submission_protects_dataset_without_saving_geojson(self):
        item = self.resource(data_type="raster")
        dataset = RasterDataset.objects.create(
            name="导出栅格",
            code="export-delete-check",
            data_resource=item,
            source_relative_path="export.tif",
            status="ready",
        )
        with (
            patch(
                "apps.raster.services.jobs.reconcile_interrupted_jobs",
                return_value=True,
            ),
            patch("apps.raster.services.jobs._submit_job"),
        ):
            job = start_export_job(
                items=[
                    {
                        "layerType": "raster",
                        "datasetId": dataset.id,
                        "geojson": {"large": True},
                    }
                ],
                epsg=4326,
                reproject=True,
                clip_geometry=None,
                vector_format="geojson",
            )
        self.addCleanup(self.remove_job_cache, job.id)
        self.assertEqual(job.result, {"inputRefs": [{"datasetId": dataset.id}]})
        self.assertEqual(self.delete([item.id]).json()["items"][0]["status"], "blocked")
        _set_job_running(job.id, "导出中", 10)
        self.assertEqual(self.delete([item.id]).json()["items"][0]["status"], "blocked")
        _fail_job(job.id, "测试导出停止")
        self.assertEqual(self.delete([item.id]).json()["deletedCount"], 1)

    @staticmethod
    def remove_job_cache(job_id):
        with _LOCK:
            _JOBS.pop(job_id, None)
