"""Catalog copy updates preserve customized metadata and published packages."""

from dataclasses import replace
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.compute.management.commands.seed_compute import NDVI_DESCRIPTION
from apps.compute.models import AlgorithmResource, AlgorithmVersion, ComputeTask
from apps.core.storage import app_path
from apps.projects.models import Project


migration = import_module("apps.compute.migrations.0005_ndvi_description")


@pytest.fixture
def ndvi_catalog(settings, tmp_path):
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=tmp_path / "app",
        research_data_root=tmp_path / "research",
    )
    owner = get_user_model().objects.create_superuser(
        "ndvi-description-admin", password="testpass"
    )
    call_command("seed_compute", only=[4], verbosity=0)
    algorithm = AlgorithmResource.objects.get(
        project_tag_id=1, identifier="raster-ndvi"
    )
    version = algorithm.versions.get()
    version.status = "published"
    version.runtime_digest = "sha256:" + "a" * 64
    version.save(update_fields=["status", "runtime_digest"])
    return owner, algorithm, version


def apply_description_migration():
    historical_apps = (
        MigrationExecutor(connection)
        .loader.project_state([("compute", "0004_import_request_source")])
        .apps
    )
    migration.populate_ndvi_description(
        historical_apps, SimpleNamespace(connection=connection)
    )


@pytest.mark.parametrize("old_description", migration.DEFAULT_DESCRIPTIONS)
def test_default_ndvi_copy_updates_without_changing_published_version(
    ndvi_catalog, old_description
):
    _, algorithm, version = ndvi_catalog
    algorithm.description = old_description
    algorithm.save(update_fields=["description"])
    resource_before = AlgorithmResource.objects.values().get(pk=algorithm.pk)
    version_before = AlgorithmVersion.objects.values().get(pk=version.pk)
    package_before = app_path(version.package_path).read_bytes()

    apply_description_migration()
    apply_description_migration()

    assert AlgorithmResource.objects.values().get(pk=algorithm.pk) == {
        **resource_before,
        "description": NDVI_DESCRIPTION,
    }
    assert AlgorithmVersion.objects.values().get(pk=version.pk) == version_before
    assert app_path(version.package_path).read_bytes() == package_before
    assert ComputeTask.objects.count() == 0


def test_description_migration_preserves_custom_copy_and_other_resources(ndvi_catalog):
    owner, algorithm, _ = ndvi_catalog
    algorithm.description = "团队为当前传感器制定的 NDVI 说明。"
    algorithm.save(update_fields=["description"])
    private = Project.objects.create(name="研究", code="ndvi-description-private")
    AlgorithmResource.objects.create(
        identifier="raster-ndvi",
        name="项目自有 NDVI",
        project_tag=private,
        description="",
        created_by=owner,
    )
    AlgorithmResource.objects.create(
        identifier="raster-ndwi",
        name="NDWI 水体指数",
        description=migration.DEFAULT_DESCRIPTIONS[1],
        created_by=owner,
    )
    resources_before = list(AlgorithmResource.objects.order_by("pk").values())

    apply_description_migration()

    assert list(AlgorithmResource.objects.order_by("pk").values()) == resources_before


def test_seed_sets_ndvi_copy_and_preserves_existing_resource_and_version(ndvi_catalog):
    _, algorithm, version = ndvi_catalog
    assert algorithm.description == NDVI_DESCRIPTION
    assert NDVI_DESCRIPTION == migration.NDVI_DESCRIPTION
    algorithm.name = "团队 NDVI"
    algorithm.description = "自定义的适用条件与影像说明。"
    algorithm.save(update_fields=["name", "description"])
    resource_before = AlgorithmResource.objects.values().get(pk=algorithm.pk)
    version_before = AlgorithmVersion.objects.values().get(pk=version.pk)
    package_before = app_path(version.package_path).read_bytes()

    call_command("seed_compute", only=[4], verbosity=0)

    assert AlgorithmResource.objects.values().get(pk=algorithm.pk) == resource_before
    assert AlgorithmVersion.objects.values().get(pk=version.pk) == version_before
    assert AlgorithmVersion.objects.filter(algorithm=algorithm).count() == 1
    assert app_path(version.package_path).read_bytes() == package_before
    assert ComputeTask.objects.count() == 0
