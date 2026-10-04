import io
import zipfile
from dataclasses import replace

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.compute.models import AlgorithmResource
from apps.compute.packages import inspect_package
from apps.compute.templates import build_package
from apps.projects.context import ProjectScope, project_scope


def test_geometry_repair_seed_is_draft_and_preserves_manual_edits(settings, tmp_path):
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG, app_data=tmp_path / "app"
    )
    admin = get_user_model().objects.create_superuser(
        "repair_admin", password="testpass"
    )
    call_command("seed_geometry_repair", stdout=io.StringIO())
    with project_scope(ProjectScope((1,), 1, admin.id, True)):
        algorithm = AlgorithmResource.objects.get(identifier="vector-geometry-repair")
        version = algorithm.versions.get()
        assert version.status == "draft"
        assert version.manifest["agent"]["enabled"] is True
        assert not version.runtime_digest
        algorithm.name = "人工维护名称"
        algorithm.enabled = False
        algorithm.save(update_fields=["name", "enabled"])
        version.status = "published"
        version.save(update_fields=["status"])
        call_command("seed_geometry_repair", stdout=io.StringIO())
        algorithm.refresh_from_db()
        version.refresh_from_db()
        assert algorithm.name == "人工维护名称"
        assert not algorithm.enabled
        assert algorithm.versions.count() == 1
        assert version.status == "published"


def test_geometry_repair_package_uses_existing_validation_and_public_template(tmp_path):
    data, identifier = build_package(7)
    path = tmp_path / "repair.zip"
    path.write_bytes(data)
    manifest = inspect_package(path)
    assert identifier == manifest["identifier"] == "vector-geometry-repair"
    assert [output["key"] for output in manifest["outputs"]] == [
        "repaired",
        "repair_log",
        "repair_summary",
        "repair_audit",
    ]
    assert manifest["outputs"][0]["required"] is False
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {"main.py", "operator.yaml", "README.md"}


def test_geometry_repair_registration_requires_active_superadmin():
    get_user_model().objects.update(is_active=False)
    get_user_model().objects.create_user("ordinary", password="testpass")
    with pytest.raises(CommandError, match="超级管理员"):
        call_command("seed_geometry_repair", stdout=io.StringIO())
