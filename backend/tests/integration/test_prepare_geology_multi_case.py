"""Both deployed and local geology project codes reuse the explicit project ID."""

import hashlib
import io
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.agent.management.commands.prepare_geology_multi_case import ROLES, SCENARIO
from apps.catalog.models import DataResource
from apps.knowledge.models import KnowledgeEntry
from apps.projects.models import Project

pytestmark = pytest.mark.django_db


def material_manifest(tmp_path):
    data = b"verified material"
    (tmp_path / "sample.bin").write_bytes(data)
    item = {"file": "sample.bin", "sha256": hashlib.sha256(data).hexdigest()}
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "scenario": SCENARIO,
                "resources": [{**item, "role": role} for role in ROLES],
                "artifacts": [item, item],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "trial_knowledge.json").write_text(
        json.dumps(
            {
                "scenario": SCENARIO,
                "rules": [
                    {"id": f"{prefix}-{index:02}"}
                    for prefix, count in [("L", 4), ("S", 5), ("A", 5), ("P", 3)]
                    for index in range(1, count + 1)
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("code", ["02", "demo-geology-reasoning"])
def test_preflight_accepts_explicit_existing_geology_project_without_writes(
    tmp_path, code
):
    project = Project.objects.create(name="现有地质项目", code=code)
    user = get_user_model().objects.create_superuser("import-admin", password="test")
    record = tmp_path / "import.json"
    resources, knowledge = DataResource.objects.count(), KnowledgeEntry.objects.count()
    output = io.StringIO()
    call_command(
        "prepare_geology_multi_case",
        manifest=material_manifest(tmp_path),
        project_id=project.id,
        user_id=user.id,
        record=record,
        dry_run=True,
        stdout=output,
    )
    assert "预检通过" in output.getvalue()
    assert DataResource.objects.count() == resources
    assert KnowledgeEntry.objects.count() == knowledge
    assert not record.exists()
    assert not (tmp_path / "inputs/rules.csv").exists()


@pytest.mark.parametrize("code,superadmin", [("unrelated", True), ("02", False)])
def test_preflight_rejects_other_project_or_non_admin(tmp_path, code, superadmin):
    project = Project.objects.create(name="指定项目", code=code)
    user = get_user_model().objects.create_user(
        "import-user", password="test", is_superuser=superadmin
    )
    with pytest.raises(CommandError, match="逻辑推理项目.*超级管理员"):
        call_command(
            "prepare_geology_multi_case",
            manifest=material_manifest(tmp_path),
            project_id=project.id,
            user_id=user.id,
            record=tmp_path / "import.json",
            dry_run=True,
        )
