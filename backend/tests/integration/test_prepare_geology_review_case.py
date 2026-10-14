"""Reviewed input import is scoped, repeatable and preserves previous packages."""

from dataclasses import replace
import hashlib
from io import StringIO
import json
from pathlib import Path
import runpy
import shutil
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import box
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.agent.management.commands import prepare_geology_review_case as command
from apps.catalog.models import DataResource
from apps.compute.models import AlgorithmVersion
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project

pytestmark = pytest.mark.django_db


@pytest.fixture
def inputs(settings, tmp_path):
    original = Path(settings.PROGRAM_ROOT)
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=tmp_path / "app",
        research_data_root=tmp_path / "research",
    )
    settings.PROGRAM_ROOT = tmp_path / "program"
    for name in command.ALGORITHMS:
        shutil.copytree(
            original / "examples/compute" / name,
            settings.PROGRAM_ROOT / "examples/compute" / name,
        )
    root = tmp_path / "runtime-inputs"
    root.mkdir()
    private = tmp_path / "acceptance-only"
    private.mkdir()
    (private / "reference.txt").write_text("Not a runtime input", encoding="utf-8")
    frame = gpd.GeoDataFrame(
        {"feature_id": ["unit-1"], "class": [0]},
        geometry=[box(95.9, 35.8, 96, 35.9)],
        crs=4326,
    )
    frame.to_file(root / "地图.gpkg", layer="data", driver="GPKG", index=False)
    frame.to_file(root / "覆盖.gpkg", layer="data", driver="GPKG", index=False)
    (root / "规则.csv").write_text(
        "rule_id,name\ncoverage,内部漏填\n", encoding="utf-8-sig"
    )
    bundle = runpy.run_path(str(original / "scripts/geology_review_data.py"))[
        "knowledge"
    ]()
    (root / "expert_knowledge.json").write_text(
        json.dumps(bundle, ensure_ascii=False), encoding="utf-8"
    )
    rows = []
    for code, file, kind in [
        ("geology-review-initial", "地图.gpkg", "vector"),
        ("geology-review-coverage", "覆盖.gpkg", "vector"),
        ("geology-review-rules", "规则.csv", "table"),
    ]:
        rows.append(
            {
                "code": code,
                "name": code,
                "file": file,
                "kind": kind,
                "layer": "data",
                "description": "演示案例",
                "sha256": hashlib.sha256((root / file).read_bytes()).hexdigest(),
            }
        )
    manifest = {
        "schemaVersion": 1,
        "resources": rows,
        "algorithms": sorted(command.ALGORITHMS),
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    user = get_user_model().objects.create_superuser("review-import", "", "test-only")
    project = Project.objects.create(name="临时地质项目", code="geology-review-import")
    kwargs = {
        "manifest": path,
        "project_id": project.id,
        "user_id": user.id,
        "record": tmp_path / "objects.json",
        "stdout": StringIO(),
    }
    return kwargs, path, manifest, user, project


def test_import_is_repeatable_and_keeps_acceptance_out_of_resources(inputs):
    kwargs, _, _, user, project = inputs
    call_command("prepare_geology_review_case", **kwargs)
    first = json.loads(kwargs["record"].read_text(encoding="utf-8"))
    call_command("prepare_geology_review_case", **kwargs)
    assert json.loads(kwargs["record"].read_text(encoding="utf-8")) == first
    with project_scope(ProjectScope((project.id,), project.id, user.id, True)):
        resources = list(DataResource.objects.all())
        assert {item.code for item in resources} == command.CODES
        assert all(
            item.source.startswith("geology-review-input:") for item in resources
        )
        assert all(item.provider == "地质成果检查演示案例" for item in resources)
    assert AlgorithmVersion.objects.count() == 2
    assert set(AlgorithmVersion.objects.values_list("status", flat=True)) == {"draft"}


def test_extra_reference_manifest_is_rejected_before_import(inputs):
    kwargs, path, value, _, _ = inputs
    value["resources"].append({**value["resources"][0], "code": "reference-only"})
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(CommandError, match="三项运行资料"):
        call_command("prepare_geology_review_case", **kwargs)
    assert not AlgorithmVersion.objects.exists()
    assert not DataResource._base_manager.exists()


def test_changed_input_rejected_and_dry_run_has_no_writes(inputs):
    kwargs, path, value, _, _ = inputs
    call_command("prepare_geology_review_case", **kwargs, dry_run=True)
    assert (
        not AlgorithmVersion.objects.exists()
        and not DataResource._base_manager.exists()
    )
    (path.parent / value["resources"][2]["file"]).write_text(
        "changed", encoding="utf-8"
    )
    with pytest.raises(CommandError, match="内容校验失败"):
        call_command("prepare_geology_review_case", **kwargs)
    assert (
        not AlgorithmVersion.objects.exists()
        and not DataResource._base_manager.exists()
    )


def test_package_has_only_reviewed_operator_files(settings):
    directory = Path(settings.PROGRAM_ROOT) / "examples/compute/geology-map-check"
    uploaded = command.package(directory)
    with zipfile.ZipFile(uploaded) as archive:
        assert set(archive.namelist()) == set(command.PACKAGE_FILES)
