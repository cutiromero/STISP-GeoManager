"""Import safety and repeatability; GIS computation is outside these tests."""

import hashlib
import json
import shutil
import zipfile
from dataclasses import replace
from io import BytesIO, StringIO
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.agent.management.commands import prepare_real_geology_case as command
from apps.catalog.models import DataResource, ResultArtifact
from apps.compute.models import AlgorithmResource, AlgorithmVersion
from apps.core.storage import app_path
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project


def file_item(path, *, code="initial-map", kind="vector"):
    return {
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "name": "真实地图测试资料",
        "code": code,
        "kind": kind,
        "description": "临时导入测试；未计算真实图件。",
    }


@pytest.mark.parametrize("outside", ["../outside.csv", "absolute"])
def test_checked_file_rejects_paths_outside_manifest_directory(tmp_path, outside):
    root = tmp_path / "material"
    root.mkdir()
    external = tmp_path / "outside.csv"
    external.write_text("a,b\n1,2\n", encoding="utf-8")
    item = file_item(external)
    item["file"] = str(external) if outside == "absolute" else outside
    with pytest.raises(CommandError, match="清单目录内"):
        command.checked_file(root, item)


@pytest.mark.parametrize("failure", ["missing", "changed"])
def test_checked_file_rejects_missing_or_changed_content(tmp_path, failure):
    path = tmp_path / "initial.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    item = file_item(path)
    assert command.checked_file(tmp_path, item) == path
    if failure == "missing":
        path.unlink()
    else:
        path.write_text("a,b\n1,3\n", encoding="utf-8")
    with pytest.raises(CommandError, match="内容校验失败"):
        command.checked_file(tmp_path, item)


@pytest.fixture
def material_context(settings, tmp_path, monkeypatch):
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=tmp_path / "app",
        research_data_root=tmp_path / "research",
    )
    original_program = settings.PROGRAM_ROOT
    settings.PROGRAM_ROOT = tmp_path / "program"
    for name in ("geology-age-check", "geology-age-edit"):
        directory = settings.PROGRAM_ROOT / "examples/compute" / name
        directory.mkdir(parents=True)
        for filename in command.PACKAGE_FILES:
            shutil.copyfile(
                original_program / "examples/compute" / name / filename,
                directory / filename,
            )
    user = get_user_model().objects.create_superuser(
        "real-import-test", password="test"
    )
    project = Project.objects.create(name="临时真实材料验证", code="real-import-test")
    root = tmp_path / "material"
    root.mkdir()
    resources = []
    for kind, filename in (
        ("vector", "initial.gpkg"),
        ("raster", "prediction.tif"),
        ("table", "context.csv"),
    ):
        path = root / filename
        path.write_bytes(b"name,value\ncontext,1\n")
        resources.append(file_item(path, code="case-" + kind, kind=kind))
    artifact_path = root / "areas.csv"
    artifact_path.write_bytes(b"class,area_m2\n0,841\n8,1682\n")
    artifact = {
        **file_item(artifact_path),
        "name": "测试面积成果",
        "resultType": "table",
        "resources": [item["code"] for item in resources],
    }
    manifest = {
        "schemaVersion": 1,
        "resources": resources,
        "artifacts": [artifact],
        "algorithms": ["geology-age-check", "geology-age-edit"],
    }
    calls = []

    def register(name, kind):
        calls.append(kind)
        return DataResource.objects.create(
            name=name, code="stub-" + kind, data_type=kind, maintainer=user
        )

    def vector_import(upload, payload, importing_user):
        assert importing_user == user
        assert upload.name == "initial.gpkg"
        return {"resourceId": register(payload["name"], "vector").id}

    def raster_import(path, **kwargs):
        assert path.name == "prediction.tif"
        return SimpleNamespace(data_resource=register(kwargs["name"], "raster"))

    def table_import(**kwargs):
        assert kwargs["df"].iloc[0]["name"] == "context"
        return {"resourceId": register(kwargs["name"], "table").id}

    monkeypatch.setattr(command, "commit_vector_import", vector_import)
    monkeypatch.setattr(command, "import_raster_file", raster_import)
    monkeypatch.setattr(command, "import_plain_table", table_import)
    manifest_path = root / "manifest.json"
    record_path = tmp_path / "record.json"

    def run(payload=None, **options):
        manifest_path.write_text(
            json.dumps(manifest if payload is None else payload), encoding="utf-8"
        )
        output = StringIO()
        call_command(
            "prepare_real_geology_case",
            manifest=str(manifest_path),
            project_id=project.pk,
            user_id=user.pk,
            record=str(record_path),
            stdout=output,
            **options,
        )
        return output.getvalue()

    return SimpleNamespace(
        user=user,
        project=project,
        root=root,
        manifest=manifest,
        run=run,
        record=record_path,
        calls=calls,
    )


def test_preflight_checks_all_files_without_import_or_record(material_context):
    env = material_context
    assert "无业务写入" in env.run(dry_run=True)
    assert not env.calls and not env.record.exists()
    assert DataResource.objects.count() == ResultArtifact.objects.count() == 0
    assert AlgorithmResource.objects.count() == AlgorithmVersion.objects.count() == 0
    (env.root / env.manifest["artifacts"][0]["file"]).write_bytes(b"changed")
    with pytest.raises(CommandError, match="内容校验失败"):
        env.run()
    assert not env.calls and not DataResource.objects.exists()


@pytest.mark.parametrize("change", ["source", "inactive"])
def test_existing_resource_requires_original_signature_and_active_state(
    material_context, change
):
    env = material_context
    item = env.manifest["resources"][0]
    scope = ProjectScope((env.project.pk,), env.project.pk, env.user.pk, True)
    with project_scope(scope):
        original = DataResource.objects.create(
            name="已入库资料",
            code=item["code"],
            data_type="vector",
            source="geology-case-20261012:" + item["sha256"],
        )
        assert command.import_resource(env.user, env.root, item).pk == original.pk
        assert not env.calls
        if change == "source":
            original.source = "another-material-signature"
        else:
            original.status = "inactive"
        original.save()
        with pytest.raises(CommandError, match="同编码资料已变更"):
            command.import_resource(env.user, env.root, item)
        original.refresh_from_db()
        assert DataResource.objects.count() == 1 and not env.calls
        assert original.source == (
            "another-material-signature"
            if change == "source"
            else "geology-case-20261012:" + item["sha256"]
        )


def test_repeat_import_preserves_resources_artifacts_links_and_algorithm_versions(
    material_context,
):
    env = material_context
    env.run()
    first = json.loads(env.record.read_text(encoding="utf-8"))
    artifact = ResultArtifact.objects.get(pk=first["artifacts"]["测试面积成果"])
    linked_ids = set(artifact.related_resources.values_list("id", flat=True))
    assert linked_ids == set(first["resources"].values())
    assert artifact.project_tag_id == env.project.pk and artifact.status == "published"
    assert AlgorithmVersion.objects.count() == 2
    assert set(AlgorithmVersion.objects.values_list("status", flat=True)) == {"draft"}
    for version in AlgorithmVersion.objects.all():
        with zipfile.ZipFile(app_path(version.package_path)) as archive:
            assert set(archive.namelist()) == set(command.PACKAGE_FILES)
            assert archive.read("age_logic.py")
    file_path = artifact.file_path
    artifact.related_resources.add(*DataResource.objects.filter(pk__in=linked_ids))
    env.run()
    second = json.loads(env.record.read_text(encoding="utf-8"))
    artifact.refresh_from_db()
    assert first == second
    assert env.calls == ["vector", "raster", "table"]
    assert DataResource.objects.count() == 3 and ResultArtifact.objects.count() == 1
    assert AlgorithmResource.objects.count() == AlgorithmVersion.objects.count() == 2
    assert artifact.file_path == file_path
    assert set(artifact.related_resources.values_list("id", flat=True)) == linked_ids


def test_repeat_import_rejects_changed_artifact_associations(material_context):
    env = material_context
    env.run()
    artifact = ResultArtifact.objects.get()
    artifact.related_resources.remove(artifact.related_resources.first())
    remaining = set(artifact.related_resources.values_list("id", flat=True))
    with pytest.raises(CommandError, match="数据关联已变化"):
        env.run()
    assert set(artifact.related_resources.values_list("id", flat=True)) == remaining
    assert env.calls == ["vector", "raster", "table"]


@pytest.fixture
def source_package(tmp_path, monkeypatch):
    directory = tmp_path / "geology-age-check"
    directory.mkdir()
    contents = {name: (name + "\n").encode() for name in command.PACKAGE_FILES}
    for name, content in contents.items():
        (directory / name).write_bytes(content)
    path = tmp_path / "registered.zip"
    path.write_bytes(command.package(directory).read())
    version = SimpleNamespace(
        package_path="registered.zip", checksum=command.digest(path)
    )
    monkeypatch.setattr(command, "app_path", lambda _: path)
    return directory, path, version, contents


def test_algorithm_package_includes_helper_and_reuses_identical_sources(source_package):
    directory, path, version, contents = source_package
    with zipfile.ZipFile(BytesIO(command.package(directory).read())) as archive:
        assert set(archive.namelist()) == {
            "main.py",
            "age_logic.py",
            "operator.yaml",
            "README.md",
        }
        assert archive.read("age_logic.py") == contents["age_logic.py"]
    # Source comparison accepts older ZIP timestamps when file contents match.
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in contents.items():
            archive.writestr(
                zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0)), content
            )
    version.checksum = command.digest(path)
    command.verify_version_source(version, directory)


@pytest.mark.parametrize(
    "filename", ["main.py", "age_logic.py", "operator.yaml", "README.md"]
)
def test_registered_algorithm_rejects_changed_source_files(source_package, filename):
    directory, _, version, _ = source_package
    (directory / filename).write_bytes(b"updated source")
    with pytest.raises(CommandError, match="源码已变化"):
        command.verify_version_source(version, directory)


def test_registered_algorithm_rejects_damaged_checksum(source_package):
    directory, path, version, _ = source_package
    with path.open("ab") as stream:
        stream.write(b"tampering")
    with pytest.raises(CommandError, match="算法包校验失败"):
        command.verify_version_source(version, directory)


@pytest.mark.parametrize("omitted", ["age_logic.py", "README.md"])
def test_registered_algorithm_rejects_incomplete_package(source_package, omitted):
    directory, path, version, contents = source_package
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in contents.items():
            if name != omitted:
                archive.writestr(name, content)
    version.checksum = command.digest(path)
    with pytest.raises(CommandError, match="源码已变化"):
        command.verify_version_source(version, directory)
