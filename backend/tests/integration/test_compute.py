import io
import json
import sqlite3
import stat
import zipfile
from dataclasses import replace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.test import Client
from django.utils import timezone

from apps.catalog.models import DataResource
from apps.compute.models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeTask,
    ComputeImport,
    RuntimeLease,
)
from apps.compute.packages import ComputeError, inspect_package
from apps.compute.templates import build_package
from apps.compute.views import store_version
from apps.compute.worker import run_task, task_scope, process_import
from apps.core.storage import table_data_path
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project, ProjectMembership


@pytest.fixture
def setup_compute(settings, tmp_path):
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=tmp_path / "app",
        research_data_root=tmp_path / "research",
    )
    owner = get_user_model().objects.create_user("compute_owner", password="testpass")
    owner.user_permissions.add(
        *Permission.objects.filter(
            codename__in=[
                "submit_task",
                "view_own_task",
                "cancel_own_task",
                "browse_data",
                "add_dataresource",
                "export_dataresource",
            ]
        )
    )
    admin = get_user_model().objects.create_superuser(
        "compute_admin", password="testpass"
    )
    outsider = get_user_model().objects.create_user(
        "compute_other", password="testpass"
    )
    project = Project.objects.create(name="计算测试私有项目", code="compute-test")
    other_project = Project.objects.create(name="另一个计算项目", code="compute-other")
    ProjectMembership.objects.create(project=project, user=owner)
    RuntimeLease.objects.update_or_create(name="queue")
    RuntimeLease.objects.update_or_create(
        name="worker",
        defaults={
            "heartbeat": timezone.now(),
            "detail": {"ready": True, "imageDigest": "sha256:" + "a" * 64},
        },
    )
    with project_scope(ProjectScope((1,), 1, admin.id, True)):
        package, identifier = build_package(3)
        algorithm = AlgorithmResource.objects.create(
            identifier=identifier, name="表格统计", created_by=admin
        )
        version = store_version(
            algorithm,
            UploadedFile(io.BytesIO(package), name="operator.zip", size=len(package)),
        )
        version.status = "published"
        version.runtime_digest = "sha256:" + "a" * 64
        version.save()
    with project_scope(ProjectScope((project.id,), project.id, owner.id)):
        path = table_data_path("data.sqlite")
        path.parent.mkdir(parents=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE samples (region TEXT, value REAL)")
            db.executemany(
                "INSERT INTO samples VALUES (?,?)", [("A", 2), ("A", 4), ("B", 8)]
            )
            db.execute("CREATE TABLE secret_unselected (password TEXT)")
            db.execute("INSERT INTO secret_unselected VALUES ('hidden')")
        resource = DataResource.objects.create(
            name="输入表格",
            code="input",
            data_type="table",
            file_format="SQLITE",
            storage_path="samples",
            item_count=3,
        )
    body = {
        "name": "统计任务",
        "versionId": version.id,
        "inputs": {"table": resource.id},
        "parameters": {"group": "region", "value": "value", "method": "mean"},
        "idempotencyKey": "key1",
    }
    client = Client()
    client.force_login(owner)
    return {
        "owner": owner,
        "admin": admin,
        "outsider": outsider,
        "project": project,
        "other_project": other_project,
        "version": version,
        "resource": resource,
        "body": body,
        "client": client,
        "tmp": tmp_path,
    }


def post(env, path, body=None, project=None):
    return env["client"].post(
        "/api/compute/" + path,
        data=json.dumps(body if body is not None else env["body"]),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(project or env["project"].id),
    )


def test_public_algorithm_private_inputs_and_idempotency(setup_compute):
    env = setup_compute
    response = post(env, "tasks/")
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["projectTagId"] == env["project"].id
    assert data["version"]["manifest"]["identifier"] == "table-group-summary"
    assert post(env, "tasks/").json()["id"] == data["id"]
    assert ComputeTask.objects.count() == 1
    changed = {**env["body"], "name": "different"}
    assert post(env, "tasks/", changed).status_code == 409
    assert post(env, "tasks/", project=1).status_code == 404


def test_no_cross_project_or_other_users_tasks(setup_compute):
    env = setup_compute
    task_id = post(env, "tasks/").json()["id"]
    client = env["client"]
    client.force_login(env["outsider"])
    assert (
        client.get(
            f"/api/compute/tasks/{task_id}/", HTTP_X_PROJECT_ID=str(env["project"].id)
        ).status_code
        == 404
    )
    ProjectMembership.objects.create(project=env["project"], user=env["outsider"])
    assert (
        client.get(
            f"/api/compute/tasks/{task_id}/", HTTP_X_PROJECT_ID=str(env["project"].id)
        ).status_code
        == 404
    )
    client.force_login(env["admin"])
    assert (
        client.get(
            f"/api/compute/tasks/{task_id}/", HTTP_X_PROJECT_ID=str(env["project"].id)
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/compute/tasks/{task_id}/", HTTP_X_PROJECT_ID="1").status_code
        == 404
    )


def test_offline_runtime_rejects_submission_and_preflight_still_works(setup_compute):
    env = setup_compute
    RuntimeLease.objects.filter(name="worker").update(detail={"ready": False})
    assert post(env, "preflight/").status_code == 200
    assert post(env, "tasks/").status_code == 503
    assert ComputeTask.objects.count() == 0


@pytest.mark.parametrize(
    "parameters",
    [
        {"group": "hidden", "value": "value"},
        {"group": "region", "value": "value", "method": "invalid"},
        {"group": "region", "value": "value", "extra": 1},
    ],
)
def test_parameter_validation(setup_compute, parameters):
    env = setup_compute
    assert (
        post(env, "tasks/", {**env["body"], "parameters": parameters}).status_code
        == 400
    )


def test_project_header_required_and_management_gate(setup_compute):
    env = setup_compute
    client = env["client"]
    assert (
        client.post(
            "/api/compute/tasks/",
            data=json.dumps(env["body"]),
            content_type="application/json",
        ).status_code
        == 400
    )
    assert (
        post(env, "algorithms/", {"identifier": "new", "name": "算法"}).status_code
        == 403
    )
    client.force_login(env["admin"])
    result = post(env, "algorithms/", {"identifier": "new", "name": "算法"})
    assert result.status_code == 200
    assert result.json()["projectTagId"] == env["project"].id


def test_algorithm_delete_removes_unreferenced_versions_and_package(
    setup_compute, django_capture_on_commit_callbacks
):
    env = setup_compute
    env["client"].force_login(env["admin"])
    with project_scope(ProjectScope((1,), 1, env["admin"].id, True)):
        package, identifier = build_package(4)
        algorithm = AlgorithmResource.objects.create(
            identifier=identifier, name="临时算法", created_by=env["admin"]
        )
        version = store_version(
            algorithm,
            UploadedFile(io.BytesIO(package), name="operator.zip", size=len(package)),
        )
    package_path = env["tmp"] / "app" / version.package_path
    assert package_path.is_file()
    with django_capture_on_commit_callbacks(execute=True):
        response = env["client"].delete(
            f"/api/compute/algorithms/{algorithm.id}/", HTTP_X_PROJECT_ID="1"
        )
    assert response.status_code == 200, response.content
    assert not AlgorithmResource._base_manager.filter(pk=algorithm.id).exists()
    assert not AlgorithmVersion._base_manager.filter(pk=version.id).exists()
    assert not package_path.exists()


def test_algorithm_delete_preserves_task_history(setup_compute):
    env = setup_compute
    task_id = post(env, "tasks/").json()["id"]
    task = ComputeTask.objects.get(pk=task_id)
    env["client"].force_login(env["admin"])
    response = env["client"].delete(
        f"/api/compute/algorithms/{task.version.algorithm_id}/",
        HTTP_X_PROJECT_ID="1",
    )
    assert response.status_code == 409
    assert AlgorithmResource._base_manager.filter(pk=task.version.algorithm_id).exists()


def test_algorithm_delete_requires_permission_and_current_project(setup_compute):
    env = setup_compute
    url = f"/api/compute/algorithms/{env['version'].algorithm_id}/"
    assert env["client"].delete(url, HTTP_X_PROJECT_ID="1").status_code == 403
    env["client"].force_login(env["admin"])
    assert env["client"].delete(url).status_code == 400
    assert (
        env["client"].delete(url, HTTP_X_PROJECT_ID=str(env["project"].id)).status_code
        == 404
    )
    assert AlgorithmVersion.objects.filter(pk=env["version"].id).exists()


def test_algorithm_delete_rollback_preserves_package(setup_compute):
    env = setup_compute
    env["client"].force_login(env["admin"])
    version = env["version"]
    with patch(
        "apps.compute.views.audit", side_effect=ComputeError("audit failed", 503)
    ):
        response = env["client"].delete(
            f"/api/compute/algorithms/{version.algorithm_id}/", HTTP_X_PROJECT_ID="1"
        )
    assert response.status_code == 503
    assert AlgorithmVersion.objects.filter(pk=version.id).exists()
    assert (env["tmp"] / "app" / version.package_path).is_file()


def test_version_requires_successful_trial_and_is_immutable(setup_compute):
    env = setup_compute
    env["client"].force_login(env["admin"])
    env["version"].status = "draft"
    env["version"].save()
    assert (
        post(
            env, f"versions/{env['version'].id}/", {"action": "publish"}, project=1
        ).status_code
        == 409
    )
    package, _ = build_package(3)
    response = env["client"].post(
        f"/api/compute/algorithms/{env['version'].algorithm_id}/versions/",
        {"file": SimpleUploadedFile("operator.zip", package)},
        HTTP_X_PROJECT_ID="1",
    )
    assert response.status_code == 409
    assert AlgorithmVersion.objects.count() == 1


def test_worker_fixes_only_selected_table_and_validates_result(setup_compute):
    env = setup_compute
    data = post(env, "tasks/").json()
    task = ComputeTask.objects.get(pk=data["id"])

    def fake_container(attempt, package, inputs, results, manifest, heartbeat):
        source = (inputs / "table.csv").read_text()
        assert "hidden" not in source
        assert not list(inputs.glob("*.sqlite"))
        (results / "summary.csv").write_text(
            "region,value\nA,3\nB,8\n", encoding="utf-8"
        )
        heartbeat(True)

    with task_scope(task), patch("apps.compute.worker.execute", fake_container):
        run_task(task)
    task.refresh_from_db()
    assert task.status == "succeeded", task.error
    assert task.outputs.count() == 1
    assert task.input_records.get().checksum
    output = task.outputs.get()
    imported = post(env, f"outputs/{output.id}/import/", {"name": "统计结果"})
    assert imported.status_code == 200, imported.content
    assert (
        post(env, f"outputs/{output.id}/import/", {"name": "统计结果"}).status_code
        == 200
    )
    assert ComputeImport.objects.count() == 1
    record = ComputeImport.objects.get()
    with task_scope(task):
        process_import(record)
    record.refresh_from_db()
    assert record.status == "ready", record.error
    assert record.resource.project_tag_id == env["project"].id
    assert record.resource.source == f"compute-output:{record.storage_key}"
    # Repeating import after success cannot create another resource.
    before = DataResource.objects.count()
    post(env, f"outputs/{output.id}/import/", {"name": "第二个名字"})
    with task_scope(task):
        process_import(record)
    assert DataResource.objects.count() == before


def test_cancel_fences_late_output(setup_compute):
    env = setup_compute
    task = ComputeTask.objects.get(pk=post(env, "tasks/").json()["id"])

    def cancelled(attempt, package, inputs, results, manifest, heartbeat):
        ComputeTask.objects.filter(pk=task.pk).update(status="cancelling")
        (results / "summary.csv").write_text("x\n1\n")

    with task_scope(task), patch("apps.compute.worker.execute", cancelled):
        run_task(task)
    task.refresh_from_db()
    assert task.status == "cancelled"
    assert not task.outputs.exists()


def test_membership_revocation_prevents_compute(setup_compute):
    env = setup_compute
    task = ComputeTask.objects.get(pk=post(env, "tasks/").json()["id"])
    ProjectMembership.objects.filter(user=env["owner"]).delete()
    with task_scope(task), patch("apps.compute.worker.execute") as execute:
        run_task(task)
    execute.assert_not_called()
    task.refresh_from_db()
    assert task.status == "failed"
    assert not task.outputs.exists()


def test_queue_quota_and_cancel(setup_compute):
    env = setup_compute
    ids = []
    for i in range(3):
        response = post(env, "tasks/", {**env["body"], "idempotencyKey": str(i)})
        assert response.status_code == 200
        ids.append(response.json()["id"])
    assert (
        post(env, "tasks/", {**env["body"], "idempotencyKey": "fourth"}).status_code
        == 409
    )
    response = post(env, f"tasks/{ids[0]}/", {"action": "cancel"})
    assert response.json()["status"] == "cancelled"
    assert (
        post(env, "tasks/", {**env["body"], "idempotencyKey": "fourth"}).status_code
        == 200
    )


def test_untrusted_package_never_imported(setup_compute):
    env = setup_compute
    package, _ = build_package(3)
    stream = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(package)) as original,
        zipfile.ZipFile(stream, "w") as result,
    ):
        for item in original.infolist():
            result.writestr(
                item.filename,
                b'raise RuntimeError("must not run")'
                if item.filename == "main.py"
                else original.read(item),
            )
    path = env["tmp"] / "package.zip"
    path.write_bytes(stream.getvalue())
    assert inspect_package(path)["identifier"] == "table-group-summary"


@pytest.mark.parametrize(
    "name,mode",
    [
        ("../escape.py", 0),
        ("/escape.py", 0),
        ("C:/escape.py", 0),
        ("main.py", 0),
        ("link", stat.S_IFLNK | 0o777),
    ],
)
def test_package_rejects_unsafe_paths(setup_compute, name, mode):
    env = setup_compute
    data, _ = build_package(3)
    stream = io.BytesIO(data)
    with zipfile.ZipFile(stream, "a") as archive:
        item = zipfile.ZipInfo(name)
        item.external_attr = mode << 16
        archive.writestr(item, "malicious")
    path = env["tmp"] / "bad.zip"
    path.write_bytes(stream.getvalue())
    with pytest.raises(ComputeError):
        inspect_package(path)


def test_anon_public_catalog_but_no_execution(setup_compute):
    client = Client()
    assert client.get("/api/compute/algorithms/").status_code == 200
    assert client.get("/api/compute/tasks/").status_code == 401
    assert client.get("/api/compute/inputs/").status_code == 401
