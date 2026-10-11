"""Preparing demos preserves existing projects and registered source versions."""

import hashlib
import json
import zipfile

import pytest
from django.core.management.base import CommandError
from django.core.management import call_command

from apps.agent.management.commands.prepare_dual_demo import (
    PACKAGE_FILES,
    demo_project,
    demo_policy_value,
    preflight_algorithm_sources,
    package,
    verify_version_source,
)
from apps.compute.packages import checksum
from apps.core.storage import app_path
from apps.projects.models import Project
from apps.agent.models import AgentPolicy
from apps.catalog.models import DataResource
from apps.compute.models import AlgorithmResource, AlgorithmVersion
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


def test_explicit_geology_project_preserves_different_live_name(setup_compute):
    env = setup_compute
    existing = Project.objects.create(
        name="核地院逻辑推理",
        code="02",
        description="人工介绍",
        sort_order=7,
        created_by=env["owner"],
    )
    before = Project.objects.count()
    for _ in range(2):
        assert (
            demo_project(
                env["admin"],
                "demo-geology-reasoning",
                "地质逻辑推理",
                project_id=existing.id,
            ).id
            == existing.id
        )
    existing.refresh_from_db()
    assert Project.objects.count() == before
    assert (
        existing.name,
        existing.code,
        existing.description,
        existing.sort_order,
    ) == (
        "核地院逻辑推理",
        "02",
        "人工介绍",
        7,
    )
    assert existing.created_by_id == env["owner"].id


def test_explicit_inactive_project_and_nonadmin_user_fail_before_writes(setup_compute):
    env = setup_compute
    existing = Project.objects.create(name="停用", code="inactive", is_active=False)
    counts = (
        Project.objects.count(),
        AgentPolicy.objects.count(),
        DataResource.objects.count(),
    )
    for options in (
        {"geology_project_id": existing.id, "user_id": env["admin"].id},
        {"geology_project_id": 999999, "user_id": env["admin"].id},
        {"user_id": env["owner"].id},
    ):
        with pytest.raises(CommandError):
            call_command("prepare_dual_demo", **options)
        assert counts == (
            Project.objects.count(),
            AgentPolicy.objects.count(),
            DataResource.objects.count(),
        )


def test_demo_policy_only_raises_budget_minima_and_preserves_manual_settings(
    setup_compute,
):
    original = {
        "operatorEnabled": False,
        "maxResources": 30,
        "maxIterations": 25,
        "maxOperatorSteps": 40,
        "maxSteps": 77,
        "defaultAgentModel": "manual-model",
        "agentAudience": {"restricted": True, "userIds": [9]},
        "quotas": [{"userId": 9, "dailyRuns": 15}],
        "customPolicy": {"manual": True},
    }
    updated = demo_policy_value(original)
    assert all(updated[key] == value for key, value in original.items())
    assert demo_policy_value(updated) == updated
    low = demo_policy_value(
        {"maxResources": 2, "maxIterations": 3, "maxOperatorSteps": 4}
    )
    assert (low["maxResources"], low["maxIterations"], low["maxOperatorSteps"]) == (
        12,
        10,
        12,
    )


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


def test_target_version_conflict_preflight_stops_before_project_policy_or_data_writes(
    setup_compute,
    version_sources,
    settings,
):
    env = setup_compute
    version, path, source = version_sources
    settings.PROGRAM_ROOT = env["tmp"] / "program"
    from apps.agent.management.commands.prepare_dual_demo import ALGORITHMS

    for identifier in ALGORITHMS:
        directory = settings.PROGRAM_ROOT / "examples/compute" / identifier
        directory.mkdir(parents=True)
        for filename in PACKAGE_FILES:
            (directory / filename).write_bytes((source / filename).read_bytes())
        manifest = json.loads((directory / "operator.yaml").read_text())
        manifest["identifier"] = identifier
        (directory / "operator.yaml").write_text(json.dumps(manifest))
    algorithm = AlgorithmResource.objects.create(
        project_tag=env["project"],
        identifier="geology-edit",
        name="已登记版本",
        created_by=env["admin"],
    )
    AlgorithmVersion.objects.create(
        algorithm=algorithm,
        version=version.version,
        manifest=version.manifest,
        checksum=version.checksum,
        package_path=version.package_path,
        status="published",
    )
    policy = AgentPolicy.objects.create(
        value={"maxResources": 99, "operatorEnabled": False}
    )
    before = (
        Project.objects.count(),
        DataResource.objects.count(),
        AlgorithmVersion.objects.count(),
    )
    original = path.read_bytes()
    with pytest.raises(CommandError, match="提高 operator.yaml 的版本号"):
        call_command(
            "prepare_dual_demo",
            user_id=env["admin"].id,
            geology_project_id=env["project"].id,
        )
    assert before == (
        Project.objects.count(),
        DataResource.objects.count(),
        AlgorithmVersion.objects.count(),
    )
    policy.refresh_from_db()
    assert policy.value == {"maxResources": 99, "operatorEnabled": False}
    assert path.read_bytes() == original


def test_public_same_version_source_difference_is_reported_without_overwrite(
    setup_compute,
    version_sources,
    settings,
):
    env = setup_compute
    version, path, source = version_sources
    algorithm = version.algorithm
    algorithm.identifier = "raster-ndvi"
    algorithm.save(update_fields=["identifier"])
    from apps.agent.management.commands.prepare_dual_demo import ALGORITHMS

    for identifier in ALGORITHMS:
        directory = env["tmp"] / "examples/compute" / identifier
        directory.mkdir(parents=True)
        for filename in PACKAGE_FILES:
            (directory / filename).write_bytes((source / filename).read_bytes())
        manifest = json.loads((directory / "operator.yaml").read_text())
        manifest["identifier"] = identifier
        (directory / "operator.yaml").write_text(json.dumps(manifest))
    original = path.read_bytes()
    report = preflight_algorithm_sources(env["tmp"], {"ecology": None, "geology": None})
    assert report == [
        {
            "identifier": "raster-ndvi",
            "version": version.version,
            "versionId": version.id,
            "sourceMatches": False,
        }
    ]
    version.refresh_from_db()
    assert path.read_bytes() == original
    assert version.status == "published" and version.checksum == checksum(path)
