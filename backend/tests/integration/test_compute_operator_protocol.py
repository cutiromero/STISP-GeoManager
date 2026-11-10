import copy
import io
import json

from django.core.management import call_command
import pytest

from apps.compute.failures import generic_failure
from apps.compute.models import AlgorithmResource, AlgorithmVersion, ComputeTask
from apps.compute.operator_catalog import operator_catalog
from apps.compute.packages import ComputeError
from apps.compute.services import submit, task_action
from apps.compute.worker import run_task, task_scope
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_compute import setup_compute, post

pytestmark = pytest.mark.django_db


@pytest.fixture
def v2(setup_compute, tmp_path):
    env = setup_compute
    call_command("new_operator", "test-v2", directory=tmp_path, stdout=io.StringIO())
    manifest = json.loads((tmp_path / "test-v2/operator.yaml").read_text())
    manifest["identifier"] = env["version"].algorithm.identifier
    env["version"].manifest = manifest
    env["version"].save(update_fields=["manifest"])
    env["body"].update(inputs={"source": env["resource"].pk}, parameters={})
    return env


def test_preflight_api_machine_readable_gaps_and_type(v2):
    response = post(v2, "preflight/")
    assert response.status_code == 400
    assert response.json()["gaps"][0]["code"] == "MISSING_ROLE"
    assert response.json()["gaps"][0]["role"] == "name"
    response = post(
        v2, "preflight/", {**v2["body"], "fieldMappings": {"source": {"name": "value"}}}
    )
    assert response.status_code == 400
    assert response.json()["gaps"][0]["code"] == "FIELD_TYPE"
    assert response.json()["gaps"][0]["actual"] == "number"
    assert (
        post(
            v2,
            "preflight/",
            {**v2["body"], "fieldMappings": {"source": {"name": "region"}}},
        ).status_code
        == 200
    )


def test_repeat_submit_and_retry_preserve_bindings_and_idempotency(v2, monkeypatch):
    from apps.compute import services

    monkeypatch.setattr(services, "runtime_state", lambda user: {"available": True})
    env = v2
    manifest = env["version"].manifest
    manifest["inputs"][0]["repeat"] = {"min": 1, "max": 2, "labelRequired": True}
    env["version"].save(update_fields=["manifest"])
    body = {
        **env["body"],
        "inputs": {"source": [{"resourceId": env["resource"].pk, "label": "观测"}]},
        "fieldMappings": {"source__1": {"name": "region"}},
    }
    with project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    ):
        task = submit(env["owner"], body)
        assert submit(env["owner"], body).pk == task.pk
        assert task.input_records.get().key == "source__1"
        assert task.field_mappings == {"source__1": {"name": "region"}}
        assert task.input_collections["source"][0]["label"] == "观测"
        task.status = "failed"
        task.save(update_fields=["status"])
        retried = task_action(task, env["owner"], "retry")
        assert retried.input_collections == task.input_collections
        assert retried.field_mappings == task.field_mappings


def test_worker_persists_structured_error_and_query_returns_it(
    setup_compute, monkeypatch
):
    from apps.compute import worker

    env = setup_compute
    response = post(env, "tasks/")
    task = ComputeTask.objects.get(pk=response.json()["id"])
    failure = {
        "code": "INPUT_INVALID",
        "message": "不符合前置条件",
        "inputs": ["table"],
        "parameters": [],
        "remedy": "replace_data",
        "details": {"observed": 3},
    }

    def fail(*args):
        raise ComputeError(failure["message"], failure=failure)

    monkeypatch.setattr(worker, "execute", fail)
    with task_scope(task):
        run_task(task)
    task.refresh_from_db()
    assert task.failure == failure
    result = env["client"].get(
        f"/api/compute/tasks/{task.pk}/", HTTP_X_PROJECT_ID=str(env["project"].pk)
    )
    assert result.json()["failure"] == failure
    assert result.json()["error"] == failure["message"]


def test_catalog_keeps_project_acl_flags_filters_and_byte_limit(v2):
    env = v2
    manifest = copy.deepcopy(env["version"].manifest)
    manifest["agent"]["enabled"] = True
    manifest["capabilities"]["summary"] = "中文能力" * 1000
    env["version"].manifest = manifest
    env["version"].save(update_fields=["manifest"])
    rows = operator_catalog(
        env["owner"],
        env["project"],
        operation="convert",
        data_type="table",
        keyword="中文",
        max_bytes=1024,
    )
    assert len(rows) == 1 and rows[0]["truncated"]
    assert (
        len(json.dumps(rows[0], ensure_ascii=False, separators=(",", ":")).encode())
        <= 1024
    )
    assert operator_catalog(env["owner"], env["project"], operation="infer") == []
    with pytest.raises(ComputeError, match="项目访问"):
        operator_catalog(env["outsider"], env["project"])
    manifest["agent"]["enabled"] = False
    env["version"].save(update_fields=["manifest"])
    assert operator_catalog(env["owner"], env["project"]) == []


def test_catalog_lists_legacy_manifest_and_excludes_draft_disabled_and_other_projects(
    setup_compute,
):
    env = setup_compute
    assert operator_catalog(env["owner"], env["project"])[0]["schemaVersion"] == 1
    algorithm = env["version"].algorithm
    for project_id, enabled, status in (
        (env["other_project"].pk, True, "published"),
        (env["project"].pk, False, "published"),
        (env["project"].pk, True, "draft"),
    ):
        private = AlgorithmResource._base_manager.create(
            identifier=f"hidden-{project_id}-{enabled}-{status}",
            name="不应出现",
            created_by=env["admin"],
            project_tag_id=project_id,
            enabled=enabled,
        )
        AlgorithmVersion.objects.create(
            algorithm=private,
            version="1.0.0",
            manifest=env["version"].manifest,
            checksum="a" * 64,
            package_path="unused.zip",
            status=status,
        )
    rows = operator_catalog(env["owner"], env["project"])
    assert [row["identifier"] for row in rows] == [algorithm.identifier]
    algorithm.enabled = False
    algorithm.save(update_fields=["enabled"])
    assert operator_catalog(env["owner"], env["project"]) == []


def test_v1_upload_warns_without_rejecting(setup_compute):
    from apps.compute.serializers import version_data

    assert "第2版" in version_data(setup_compute["version"])["warnings"][0]


@pytest.mark.efficiency
def test_repeat_preflight_reuses_metadata_within_submission(v2, monkeypatch):
    from apps.compute import services

    env = v2
    spec = env["version"].manifest["inputs"][0]
    spec["repeat"] = {"min": 1, "max": 2, "labelRequired": True}
    env["version"].save(update_fields=["manifest"])
    original, calls = services.candidate, []

    def counted(resource, **kwargs):
        calls.append(resource.pk)
        return original(resource, **kwargs)

    monkeypatch.setattr(services, "candidate", counted)
    body = {
        **env["body"],
        "inputs": {
            "source": [
                {"resourceId": env["resource"].pk, "label": label}
                for label in ("甲", "乙")
            ]
        },
        "fieldMappings": {
            key: {"name": "region"} for key in ("source__1", "source__2")
        },
    }
    with project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    ):
        services.validate_submission(env["owner"], body)
    assert calls == [env["resource"].pk]
