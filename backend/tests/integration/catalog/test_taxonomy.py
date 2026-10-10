import importlib

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from apps.catalog.models import (
    DataResource,
    DictionaryItem,
    MapComposition,
    MapCompositionVersion,
    WorkspaceScene,
)
from apps.catalog.taxonomy import TaxonomyError, resolve_data_category, taxonomy_tree


class DataTaxonomyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="taxonomy-user", password="pass12345"
        )
        grant(self.user, ("core", "browse_data"), ("catalog", "change_dataresource"))
        self.client.force_login(self.user)

    def test_coordinate_categories_and_automatic_compute_results(self):
        tree = taxonomy_tree()
        self.assertEqual(
            [node["code"] for node in tree],
            ["spatial", "non_spatial", "compute_results"],
        )
        self.assertTrue(
            all(node["selectable"] and not node["children"] for node in tree[:2])
        )
        self.assertFalse(tree[2]["selectable"])
        self.assertIsNone(tree[2]["spatialClass"])
        with self.assertRaises(TaxonomyError):
            resolve_data_category("compute_results")

    def test_retired_categories_are_not_assignable(self):
        with self.assertRaises(TaxonomyError):
            resolve_data_category("habitat_soil")

    def test_root_category_filter_uses_actual_coordinates(self):
        spatial = DataResource.objects.create(
            name="矢量",
            code="vector",
            data_type="vector",
            coordinate_system="EPSG:4326",
        )
        table = DataResource.objects.create(
            name="表格", code="table", data_type="table"
        )
        for code, resource in [("spatial", spatial), ("non_spatial", table)]:
            response = self.client.get(
                "/api/catalog/resources/", {"categoryCode": code}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                [item["id"] for item in response.json()["items"]], [resource.id]
            )
            self.assertEqual(
                response.json()["items"][0]["categoryPath"][0]["code"], code
            )

    def test_data_migration_preserves_project_and_file_path(self):
        resource = DataResource.objects.create(
            name="已有数据",
            code="preserved",
            data_type="vector",
            coordinate_system="EPSG:4326",
            storage_path="keep_me",
        )
        old = DictionaryItem.objects.get(dict_type="data_category", code="habitat_soil")
        DataResource.objects.filter(pk=resource.pk).update(category=old)
        migration = importlib.import_module(
            "apps.catalog.migrations.0017_coordinate_data_categories"
        )
        migration.regroup(django_apps, None)
        resource.refresh_from_db()
        self.assertEqual(resource.category.code, "spatial")
        self.assertEqual(resource.storage_path, "keep_me")
        self.assertEqual(resource.project_tag_id, 1)
        self.assertTrue(
            DictionaryItem.objects.filter(pk=old.pk, is_active=False).exists()
        )


class ArchivedMapCompositionMigrationTests(TestCase):
    def test_archived_composition_is_completed_without_losing_version_artifacts(self):
        user = get_user_model().objects.create_user(
            username="archived-map-owner", password="pass12345"
        )
        project = WorkspaceScene.objects.create(
            owner=user,
            kind=WorkspaceScene.Kind.PROJECT,
            name="归档专题来源工程",
        )
        composition = MapComposition.objects.create(
            owner=user,
            project=project,
            name="历史归档专题",
            status="archived",
            source_workspace_snapshot={"layers": [1]},
        )
        version = MapCompositionVersion.objects.create(
            composition=composition,
            version_number=1,
            format=MapCompositionVersion.Format.PNG,
            width_px=1200,
            height_px=800,
            preview_path="map-compositions/preview-v1.png",
            artifact_path="map-compositions/artifact-v1.png",
            workspace_snapshot={"layers": [1]},
            resource_manifest=[{"resourceId": 1}],
        )
        before_counts = (
            MapComposition.objects.count(),
            MapCompositionVersion.objects.count(),
        )
        migration = importlib.import_module(
            "apps.catalog.migrations.0009_remove_map_composition_archived_status"
        )

        migration.preserve_archived_map_compositions(django_apps, None)

        composition.refresh_from_db()
        version.refresh_from_db()
        self.assertEqual(composition.status, MapComposition.Status.COMPLETED)
        self.assertEqual(
            (
                MapComposition.objects.count(),
                MapCompositionVersion.objects.count(),
            ),
            before_counts,
        )
        self.assertEqual(version.preview_path, "map-compositions/preview-v1.png")
        self.assertEqual(version.artifact_path, "map-compositions/artifact-v1.png")
        self.assertEqual(version.resource_manifest, [{"resourceId": 1}])


def grant(user, *specs):
    for app_label, codename in specs:
        permission = Permission.objects.get(
            content_type__app_label=app_label, codename=codename
        )
        user.user_permissions.add(permission)
