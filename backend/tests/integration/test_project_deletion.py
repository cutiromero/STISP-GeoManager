from dataclasses import replace
import json
import os
import sqlite3
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from apps.catalog.models import DataResource, WorkspaceScene
from apps.compute.models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeTask,
    ComputeInput,
)
from apps.core.storage import table_data_path, research_path
from apps.raster.models import RasterDataset
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project, ProjectMembership

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def env(client, settings, tmp_path, transactional_db):
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=tmp_path / "app",
        research_data_root=tmp_path / "research",
    )
    admin = get_user_model().objects.create_superuser("project-delete-admin")
    member = get_user_model().objects.create_user("project-delete-member")
    project = Project.objects.create(name="待删除项目", code="delete-target")
    other = Project.objects.create(name="保留项目", code="keep-target")
    ProjectMembership.objects.create(user=member, project=project)
    client.force_login(admin)

    def resource(code, project_id=project.pk, filename=None):
        with project_scope(ProjectScope((project_id,), project_id, admin.pk, True)):
            path = table_data_path(filename or code + ".txt")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code)
            row = DataResource.objects.create(
                name=code,
                code=code,
                data_type="document",
                file_format="TXT",
                storage_path="table/" + path.name,
                maintainer=admin,
            )
            return row, path

    return {
        "client": client,
        "admin": admin,
        "member": member,
        "project": project,
        "other": other,
        "resource": resource,
    }


def preview(s, project=None):
    return s["client"].get(
        f"/api/projects/{(project or s['project']).pk}/deletion-preview/"
    )


def confirmation(s):
    response = preview(s)
    assert response.status_code == 200, response.content
    return {
        "confirmedName": s["project"].name,
        "deleteExclusiveData": True,
        "confirmationToken": response.json()["confirmationToken"],
    }


def remove(s, value):
    return s["client"].delete(
        f"/api/projects/{s['project'].pk}/",
        json.dumps(value),
        content_type="application/json",
    )


def test_requires_superadmin_and_protects_public_project(env):
    s = env
    s["client"].logout()
    assert preview(s).status_code == 401
    assert remove(s, {}).status_code == 401
    s["client"].force_login(s["admin"])
    assert preview(s, Project.objects.get(pk=1)).status_code == 409
    s["client"].force_login(s["member"])
    assert preview(s).status_code == 403
    assert remove(s, {}).status_code == 403
    assert Project.objects.get(pk=s["project"].pk).deleted_at is None


def test_deletes_exclusive_files_and_hides_project_preserving_public_and_other_data(
    env,
):
    s = env
    own, path = s["resource"]("owned")
    common, common_path = s["resource"]("public", 1)
    other, other_path = s["resource"]("other", s["other"].pk)
    value = confirmation(s)
    assert path.exists(), "preview is read only"
    response = remove(s, value)
    assert response.status_code == 200, response.content
    assert not path.exists()
    assert not DataResource._base_manager.filter(pk=own.pk).exists()
    assert common_path.exists() and other_path.exists()
    assert DataResource._base_manager.filter(pk__in=[common.pk, other.pk]).count() == 2
    s["project"].refresh_from_db()
    assert s["project"].deleted_at and not s["project"].is_active
    listed = s["client"].get("/api/projects/").json()
    assert s["project"].pk not in {
        p["id"] for p in listed["items"] + listed["assignableItems"]
    }
    assert (
        s["client"]
        .post(
            f"/api/projects/{s['project'].pk}/",
            {"isActive": True},
            content_type="application/json",
        )
        .status_code
        == 404
    )


def test_foreign_saved_project_reference_retains_common_dataset(env):
    s = env
    shared, shared_path = s["resource"]("shared")
    private, private_path = s["resource"]("private")
    with project_scope(ProjectScope((s["other"].pk,), s["other"].pk)):
        WorkspaceScene.objects.create(
            owner=s["admin"], name="通用数据工程", snapshot={"resourceIds": [shared.pk]}
        )
    p = preview(s).json()
    assert p["sharedResourceCount"] == 1 and p["resourceCount"] == 1
    response = remove(s, confirmation(s))
    assert response.status_code == 200, response.content
    assert shared_path.exists() and not private_path.exists()
    assert DataResource._base_manager.filter(pk=shared.pk).exists()


def test_foreign_compute_input_retains_common_dataset(env):
    s = env
    shared, path = s["resource"]("shared-input")
    with project_scope(ProjectScope((s["other"].pk,), s["other"].pk)):
        algorithm = AlgorithmResource.objects.create(
            identifier="shared-compute", name="计算", created_by=s["admin"]
        )
        version = AlgorithmVersion.objects.create(
            algorithm=algorithm, version="1", checksum="x", package_path="x"
        )
        task = ComputeTask.objects.create(
            owner=s["admin"],
            version=version,
            status="succeeded",
            name="其他项目计算",
            idempotency_key="shared",
            request_hash="x",
        )
        ComputeInput.objects.create(task=task, key="source", resource=shared)
    response = remove(s, confirmation(s))
    assert response.status_code == 200, response.content
    assert path.exists() and DataResource._base_manager.filter(pk=shared.pk).exists()
    assert ComputeInput.objects.filter(task=task, resource=shared).exists()


def test_foreign_symlink_storage_is_preserved_without_broad_directory_deletion(env):
    s = env
    own, path = s["resource"]("shared-physical")
    alias, alias_path = s["resource"]("alias", s["other"].pk)
    alias_path.unlink()
    alias_path.symlink_to(path)
    p = preview(s).json()
    assert p["sharedFileCount"] >= 1
    response = remove(s, confirmation(s))
    assert response.status_code == 200, response.content
    assert path.exists() and alias_path.read_text() == "shared-physical"
    assert DataResource._base_manager.filter(pk=alias.pk).exists()


def test_batch_shared_only_within_deleted_project_is_removed_once(env):
    s = env
    a, path = s["resource"]("same-a", filename="same.txt")
    with project_scope(ProjectScope((s["project"].pk,), s["project"].pk)):
        DataResource.objects.create(
            name="same-b",
            code="same-b",
            data_type="document",
            file_format="TXT",
            storage_path="table/same.txt",
        )
    response = remove(s, confirmation(s))
    assert response.status_code == 200, response.content
    assert not path.exists()


def test_changed_scope_and_incomplete_confirmation_do_not_delete(env):
    s = env
    _, path = s["resource"]("first")
    value = confirmation(s)
    assert remove(s, {**value, "confirmedName": "wrong"}).status_code == 409
    assert remove(s, {**value, "deleteExclusiveData": False}).status_code == 409
    s["resource"]("new-after-preview")
    assert remove(s, value).status_code == 409
    assert path.exists() and Project.objects.get(pk=s["project"].pk).deleted_at is None
    fresh = confirmation(s)
    path.write_text("changed source contents")
    assert remove(s, fresh).status_code == 409


def test_audit_failure_restores_staged_files_and_metadata(env):
    s = env
    row, path = s["resource"]("rollback")
    value = confirmation(s)
    with patch(
        "apps.projects.deletion.log_operation",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            remove(s, value)
    assert path.exists() and DataResource._base_manager.filter(pk=row.pk).exists()
    assert Project.objects.get(pk=s["project"].pk).deleted_at is None


def test_batch_database_cleanup_reuses_one_attachment_for_many_tables(env):
    s = env
    with project_scope(ProjectScope((s["project"].pk,), s["project"].pk)):
        path = table_data_path("data.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as database:
            for index in range(13):
                database.execute(f"CREATE TABLE rows_{index} (value TEXT)")
                database.execute(f"INSERT INTO rows_{index} VALUES ('private')")
                DataResource.objects.create(
                    name=f"table-{index}",
                    code=f"table-{index}",
                    data_type="table",
                    file_format="SQLITE",
                    storage_path=f"rows_{index}",
                )
    response = remove(s, confirmation(s))
    assert response.status_code == 200, response.content
    with sqlite3.connect(path) as database:
        assert (
            database.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'rows_%'"
            ).fetchall()
            == []
        )


def test_hardlinked_database_used_by_another_project_is_not_modified(env):
    s = env
    with project_scope(ProjectScope((s["project"].pk,), s["project"].pk)):
        original = table_data_path("data.sqlite")
        original.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(original) as database:
            database.execute("CREATE TABLE common_rows (value TEXT)")
            database.execute("INSERT INTO common_rows VALUES ('common')")
        DataResource.objects.create(
            name="common",
            code="common",
            data_type="table",
            file_format="SQLITE",
            storage_path="common_rows",
        )
    with project_scope(ProjectScope((s["other"].pk,), s["other"].pk)):
        linked = table_data_path("data.sqlite")
        linked.parent.mkdir(parents=True, exist_ok=True)
        os.link(original, linked)
        DataResource.objects.create(
            name="linked",
            code="linked",
            data_type="table",
            file_format="SQLITE",
            storage_path="common_rows",
        )
    p = preview(s).json()
    assert p["sharedResourceCount"] == 1
    response = remove(s, confirmation(s))
    assert response.status_code == 200, response.content
    with sqlite3.connect(linked) as database:
        assert database.execute("SELECT value FROM common_rows").fetchone() == (
            "common",
        )


def test_project_with_pending_computation_cannot_be_deleted(env):
    s = env
    with project_scope(ProjectScope((s["project"].pk,), s["project"].pk)):
        algorithm = AlgorithmResource.objects.create(
            identifier="busy", name="busy", created_by=s["admin"]
        )
        version = AlgorithmVersion.objects.create(
            algorithm=algorithm, version="1", checksum="x", package_path="x"
        )
        ComputeTask.objects.create(
            owner=s["admin"],
            version=version,
            name="busy",
            status="queued",
            idempotency_key="busy",
            request_hash="x",
        )
    assert preview(s).status_code == 409


def test_shared_multifile_raster_preserves_every_source_component(env):
    s = env
    with project_scope(ProjectScope((s["project"].pk,), s["project"].pk)):
        directory = research_path("raster/original/uploaded/source")
        directory.mkdir(parents=True)
        for name in ("scene.hdr", "scene.img", "manifest.json"):
            (directory / name).write_text(name)
        resource = DataResource.objects.create(
            name="原始栅格", code="raw-raster", data_type="raster"
        )
        RasterDataset.objects.create(
            name="原始栅格",
            code="raw-raster",
            data_resource=resource,
            status="ready",
            source_relative_path="uploaded/source/scene.hdr",
            source_manifest=[{"name": "scene.hdr"}, {"name": "scene.img"}],
        )
    with project_scope(ProjectScope((s["other"].pk,), s["other"].pk)):
        alias = research_path("raster/original/uploaded/common")
        alias.parent.mkdir(parents=True)
        alias.symlink_to(directory, target_is_directory=True)
        other_resource = DataResource.objects.create(
            name="通用栅格", code="common-raster", data_type="raster"
        )
        RasterDataset.objects.create(
            name="通用栅格",
            code="common-raster",
            data_resource=other_resource,
            status="ready",
            source_relative_path="uploaded/common/scene.hdr",
            source_manifest=[{"name": "scene.hdr"}, {"name": "scene.img"}],
        )
    response = remove(s, confirmation(s))
    assert response.status_code == 200, response.content
    for name in ("scene.hdr", "scene.img", "manifest.json"):
        assert (alias / name).read_text() == name
