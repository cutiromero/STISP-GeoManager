"""Preparing demos preserves existing projects and registered source versions."""

import hashlib
import zipfile

import pytest
from django.core.management.base import CommandError

from apps.agent.management.commands.prepare_dual_demo import (
    PACKAGE_FILES,
    demo_project,
    package,
    verify_version_source,
)
from apps.compute.packages import checksum
from apps.core.storage import app_path
from apps.projects.models import Project
from tests.integration import test_compute as shared

setup_compute = shared.setup_compute


def test_reuse_unique_active_geology_project_preserves_manual_fields(setup_compute):
    env = setup_compute
    existing = Project.objects.create(
        name="地质逻辑推理",
        code="research-geology",
        description="已有人工填写的科研介绍",
        sort_order=17,
        created_by=env["owner"],
    )
    Project.objects.create(name="已人工改名的旧演示", code="demo-geology-reasoning")
    before = Project.objects.count()
    for _ in range(2):
        assert (
            demo_project(env["admin"], "demo-geology-reasoning", "地质逻辑推理").id
            == existing.id
        )
    existing.refresh_from_db()
    assert Project.objects.count() == before
    assert existing.code == "research-geology"
    assert existing.description == "已有人工填写的科研介绍"
    assert existing.sort_order == 17
    assert existing.created_by_id == env["owner"].id


def test_duplicate_active_geology_project_requires_explicit_resolution(setup_compute):
    env = setup_compute
    for code in ("geology-first", "geology-second"):
        Project.objects.create(name="地质逻辑推理", code=code)
    before = Project.objects.count()
    with pytest.raises(CommandError, match="多个活动"):
        demo_project(env["admin"], "demo-geology-reasoning", "地质逻辑推理")
    assert Project.objects.count() == before


def test_inactive_same_name_does_not_replace_active_geology_project(setup_compute):
    env = setup_compute
    Project.objects.create(name="地质逻辑推理", code="old-geology", is_active=False)
    existing = Project.objects.create(name="地质逻辑推理", code="current-geology")
    assert (
        demo_project(env["admin"], "demo-geology-reasoning", "地质逻辑推理").id
        == existing.id
    )


def test_create_demo_project_only_when_no_active_named_project_exists(setup_compute):
    env = setup_compute
    first = demo_project(env["admin"], "demo-geology-reasoning", "地质逻辑推理")
    second = demo_project(env["admin"], "demo-geology-reasoning", "地质逻辑推理")
    assert first.id == second.id
    assert first.created_by_id == env["admin"].id


@pytest.fixture
def version_sources(setup_compute):
    env = setup_compute
    version = env["version"]
    path = app_path(version.package_path)
    directory = env["tmp"] / "current-source"
    directory.mkdir()
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in PACKAGE_FILES}
    for name, content in contents.items():
        (directory / name).write_bytes(content)
    # Make container timestamps differ from package(directory), without changing source.
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in contents.items():
            entry = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content)
    version.checksum = checksum(path)
    version.save(update_fields=["checksum"])
    return version, path, directory


def test_identical_sources_reuse_version_despite_different_zip_timestamps(
    version_sources,
):
    version, path, directory = version_sources
    original = path.read_bytes()
    new_container = package(directory).read()
    assert hashlib.sha256(new_container).hexdigest() != version.checksum
    verify_version_source(version, directory)
    version.refresh_from_db()
    assert path.read_bytes() == original
    assert version.checksum == checksum(path)
    assert version.status == "published"


@pytest.mark.parametrize("filename", PACKAGE_FILES)
def test_changed_registered_source_requires_new_version(version_sources, filename):
    version, path, directory = version_sources
    original_digest = version.checksum
    source = directory / filename
    source.write_bytes(source.read_bytes() + b"\nchanged source\n")
    with pytest.raises(CommandError, match="提高 operator.yaml 的版本号"):
        verify_version_source(version, directory)
    version.refresh_from_db()
    assert version.checksum == checksum(path) == original_digest
    assert version.status == "published"


def test_existing_registered_package_still_requires_its_own_real_hash(version_sources):
    version, path, directory = version_sources
    path.write_bytes(path.read_bytes() + b"tampered container")
    with pytest.raises(CommandError, match="校验失败"):
        verify_version_source(version, directory)
