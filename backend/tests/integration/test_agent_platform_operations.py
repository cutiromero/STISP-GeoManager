"""Real private workspace updates, bounded exports and lifecycle controls."""

import hashlib
import json
from pathlib import Path
import time
import threading
from unittest.mock import patch
import zipfile

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.agent.models import AgentPolicy, AgentWorkflow, AgentToolCall
from apps.agent.platform_actions import platform_actions
from apps.agent.policy import default_policy
from apps.agent.tools import execute
from apps.catalog.models import WorkspaceScene
from apps.compute.packages import ComputeError
from apps.projects.context import project_scope
from apps.raster.models import RasterProcessingJob
from apps.raster.services import jobs
from tests.integration.test_agent import new_run, setup_agent  # noqa: F401
from tests.integration.test_agent_map_tools import mapped, call  # noqa: F401
from tests.integration.test_agent_runtime_heartbeat import wal_database  # noqa: F401

# ruff: noqa: F811
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def operations(mapped, wal_database, monkeypatch):
    env = mapped
    env["user"].user_permissions.add(
        *Permission.objects.filter(
            codename__in=["change_workspacescene", "export_dataresource"]
        )
    )
    executor = jobs._HeavyTaskExecutor(queue_size=4)
    monkeypatch.setattr(jobs, "_HEAVY_TASK_EXECUTOR", executor)
    yield env
    deadline = time.monotonic() + 10
    while executor._queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not executor._queue.unfinished_tasks
    for row in RasterProcessingJob._base_manager.filter(
        kind="export", created_by=env["user"]
    ):
        if row.artifact_path:
            path = Path(row.artifact_path)
            if path.is_file():
                jobs._delete_job_artifact(row.pk, path)


def prepare(env):
    run = new_run(env)
    result = call(
        run,
        "prepare_map_workspace",
        {"resourceIds": [env["vector"].pk], "name": "平台操作验收工程"},
    )
    detail = call(run, "get_map_workspace", {"workspaceId": result["workspaceId"]})
    return run, detail


def export_args(detail):
    return {
        "workspaceId": detail["workspaceId"],
        "expectedUpdatedAt": detail["updatedAt"],
        "expectedSources": detail["sourceVersions"],
    }


def wait_export(run, identity):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = call(run, "get_export_task", {"jobId": identity})
        if result["status"] in {"ready", "failed"}:
            return result
        time.sleep(0.05)
    raise AssertionError("Export did not finish")


@pytest.mark.parametrize("state", ["cancelled", "succeeded", "cancel_requested"])
@pytest.mark.parametrize("tool", ["cancel_export_task", "cancel_compute_task"])
def test_stopped_agent_cannot_cancel_other_task(setup_agent, state, tool):
    from apps.agent.models import AgentRun
    from apps.compute.models import AlgorithmResource, AlgorithmVersion, ComputeTask
    from apps.raster.services.executor_identity import current_identity

    env = setup_agent
    env["user"].user_permissions.add(
        *Permission.objects.filter(codename__in=["view_own_task", "cancel_own_task"])
    )
    with project_scope(env["scope"]):
        run = new_run(env)
        if tool == "cancel_export_task":
            job = RasterProcessingJob.objects.create(
                id="a" * 32,
                kind="export",
                status="queued",
                created_by=env["user"],
                executor_identity=current_identity(),
            )
            args = {"jobId": job.pk}
        else:
            algorithm = AlgorithmResource.objects.create(
                identifier="stopped-agent", name="合成算子", created_by=env["user"]
            )
            version = AlgorithmVersion.objects.create(
                algorithm=algorithm,
                version="1",
                checksum="a" * 64,
                package_path="test.zip",
                manifest={},
            )
            job = ComputeTask.objects.create(
                owner=env["user"],
                version=version,
                name="本人计算任务",
                status="queued",
                idempotency_key="stop-test",
                request_hash="a" * 64,
            )
            args = {"taskId": str(job.pk)}
        # Keep the in-memory run stale, as it can be during a model response.
        AgentRun.objects.filter(pk=run.pk).update(
            **(
                {"cancel_requested": True}
                if state == "cancel_requested"
                else {"status": state}
            )
        )
        with pytest.raises(ComputeError) as stopped:
            execute(run, tool, args)
        assert stopped.value.status == 409
        job.refresh_from_db()
        assert job.status == "queued"
        if tool == "cancel_export_task":
            assert not job.cancel_requested


@pytest.mark.parametrize("in_workflow", [False, True])
def test_active_agent_cancels_only_standalone_computation(setup_agent, in_workflow):
    from apps.agent.models import AgentWorkflowStep
    from apps.compute.models import AlgorithmResource, AlgorithmVersion, ComputeTask

    env = setup_agent
    env["user"].user_permissions.add(
        *Permission.objects.filter(codename__in=["view_own_task", "cancel_own_task"])
    )
    with project_scope(env["scope"]):
        run = new_run(env)
        algorithm = AlgorithmResource.objects.create(
            identifier="cancel-agent", name="合成算子", created_by=env["user"]
        )
        version = AlgorithmVersion.objects.create(
            algorithm=algorithm,
            version="1",
            checksum="a" * 64,
            package_path="test.zip",
            manifest={},
        )
        task = ComputeTask.objects.create(
            owner=env["user"],
            version=version,
            name="本人合成任务",
            status="queued",
            idempotency_key="active-cancel",
            request_hash="a" * 64,
        )
        if in_workflow:
            workflow = AgentWorkflow.objects.create(
                owner=env["user"],
                goal="合成父流程",
                model="mock",
                status="waiting_compute",
                idempotency_key="parent-control",
            )
            AgentWorkflowStep.objects.create(
                workflow=workflow, sequence=1, kind="compute", compute_task_id=task.pk
            )
            with pytest.raises(ComputeError, match="所属科研任务"):
                execute(run, "cancel_compute_task", {"taskId": str(task.pk)})
        else:
            result, _ = execute(run, "cancel_compute_task", {"taskId": str(task.pk)})
            assert result["status"] == "cancelled"
        task.refresh_from_db()
        assert task.status == ("queued" if in_workflow else "cancelled")


@pytest.mark.django_db(transaction=True)
def test_private_workspace_revision_and_visibility_never_modify_original(operations):
    env = operations
    before = hashlib.sha256(env["file"].read_bytes()).hexdigest()
    with project_scope(env["scope"]):
        run, detail = prepare(env)
        layer = detail["layers"][0]["id"]
        updated = call(
            run,
            "update_map_workspace",
            {
                "workspaceId": detail["workspaceId"],
                "expectedUpdatedAt": detail["updatedAt"],
                "name": "更新后的个人工程",
                "visibility": {layer: False},
            },
        )
        assert (
            updated["name"] == "更新后的个人工程"
            and updated["layers"][0]["visible"] is False
        )
        with pytest.raises(ComputeError) as conflict:
            call(
                run,
                "update_map_workspace",
                {
                    "workspaceId": detail["workspaceId"],
                    "expectedUpdatedAt": detail["updatedAt"],
                    "name": "过期覆盖",
                },
            )
        assert conflict.value.status == 409
        env["vector"].refresh_from_db()
        assert env["vector"].default_visualization == {}
        assert (
            WorkspaceScene.objects.get(pk=detail["workspaceId"]).owner_id
            == env["user"].pk
        )
    assert hashlib.sha256(env["file"].read_bytes()).hexdigest() == before


@pytest.mark.efficiency
@pytest.mark.django_db(transaction=True)
def test_export_retries_reuse_real_job_and_actual_full_vector_file(operations):
    env = operations
    before = hashlib.sha256(env["file"].read_bytes()).hexdigest()
    with project_scope(env["scope"]):
        run, detail = prepare(env)
        with patch(
            "apps.agent.export_tools.query_resource",
            wraps=__import__(
                "apps.agent.export_tools", fromlist=["query_resource"]
            ).query_resource,
        ) as reader:
            first = call(run, "export_map_workspace", export_args(detail))
            second = call(run, "export_map_workspace", export_args(detail))
            result = wait_export(run, first["jobId"])
            assert first["jobId"] == second["jobId"] and reader.call_count == 1
        assert result["status"] == "ready" and result["artifactAvailable"]
        path = jobs.get_job_artifact_path(first["jobId"])
        with zipfile.ZipFile(path) as archive:
            name = next(
                name for name in archive.namelist() if name.endswith(".geojson")
            )
            data = json.loads(archive.read(name))
            assert len(data["features"]) == 3
            assert {item["properties"]["name"] for item in data["features"]} == {
                "岩性A",
                "岩性B",
            }
        actions = platform_actions(run, env["user"], default_policy())
        assert any(
            item["kind"] == "export" and item["jobId"] == first["jobId"]
            for item in actions
        )
        with patch(
            "apps.agent.workspace_tools.source_version",
            side_effect=AssertionError("Polling must not reopen original files"),
        ):
            assert execute(run, "get_export_task", {"jobId": first["jobId"]})[0][
                "artifactAvailable"
            ]
        assert RasterProcessingJob.objects.filter(kind="export").count() == 1
    assert hashlib.sha256(env["file"].read_bytes()).hexdigest() == before


@pytest.mark.django_db(transaction=True)
def test_changed_source_rejects_export_and_revocation_blocks_download(operations):
    env = operations
    with project_scope(env["scope"]):
        run, detail = prepare(env)
        env["vector"].description = "资料元信息新修订"
        env["vector"].save(update_fields=["description", "updated_at"])
        with pytest.raises(ComputeError) as changed:
            call(run, "export_map_workspace", export_args(detail))
        assert (
            changed.value.status == 409
            and not RasterProcessingJob.objects.filter(kind="export").exists()
        )
        detail = call(run, "get_map_workspace", {"workspaceId": detail["workspaceId"]})
        created = call(run, "export_map_workspace", export_args(detail))
        ready = wait_export(run, created["jobId"])
        assert ready["artifactAvailable"]
        permission = Permission.objects.get(
            content_type__app_label="catalog", codename="export_dataresource"
        )
        env["user"].user_permissions.remove(permission)
        with pytest.raises(PermissionDenied):
            execute(run, "get_export_task", {"jobId": created["jobId"]})
    response = env["client"].get(
        f"/api/catalog/export/jobs/{created['jobId']}/download/", **env["header"]
    )
    assert response.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_research_controls_preserve_approval_and_reject_newer_user_decisions(
    operations,
):
    env = operations
    policy = default_policy()
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": policy})
    with project_scope(env["scope"]):
        run = new_run(env)
        task = AgentWorkflow.objects.create(
            owner=env["user"],
            goal="用户真实科研任务",
            model="mock",
            status="waiting_approval",
            plan={"phase": "review_plan", "human": {"approved": False}},
            idempotency_key="platform-control",
            heartbeat=timezone.now(),
        )
        initial = call(run, "get_research_task", {"workflowId": str(task.pk)})
        assert "goal" not in initial
        paused = call(
            run,
            "control_research_task",
            {
                "workflowId": str(task.pk),
                "action": "pause",
                "expectedControlEpoch": initial["controlEpoch"],
            },
        )
        assert paused["status"] == "paused"
        repeated = call(
            run,
            "control_research_task",
            {
                "workflowId": str(task.pk),
                "action": "pause",
                "expectedControlEpoch": initial["controlEpoch"],
            },
        )
        assert (
            repeated["replayed"] and repeated["controlEpoch"] == paused["controlEpoch"]
        )
        with pytest.raises(ComputeError) as conflict:
            call(
                run,
                "control_research_task",
                {
                    "workflowId": str(task.pk),
                    "action": "resume",
                    "expectedControlEpoch": initial["controlEpoch"],
                },
            )
        assert conflict.value.status == 409
        resumed = call(
            run,
            "control_research_task",
            {
                "workflowId": str(task.pk),
                "action": "resume",
                "expectedControlEpoch": paused["controlEpoch"],
            },
        )
        assert resumed["status"] == "waiting_approval"
        task.refresh_from_db()
        assert task.plan["human"]["approved"] is False
        assert (
            AgentToolCall.objects.filter(
                run=run, idempotency_key__startswith="control-"
            ).count()
            == 2
        )


@pytest.mark.django_db(transaction=True)
def test_cancelled_export_stops_before_read_and_cannot_publish_file(
    operations, monkeypatch
):
    from apps.agent import export_tools

    env = operations
    entered, release = threading.Event(), threading.Event()
    original = export_tools._items

    def blocked(*args, **kwargs):
        if kwargs.get("materialize", True):
            entered.set()
            assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(export_tools, "_items", blocked)
    with project_scope(env["scope"]):
        run, detail = prepare(env)
        with patch(
            "apps.agent.export_tools.query_resource", wraps=export_tools.query_resource
        ) as reader:
            created = call(run, "export_map_workspace", export_args(detail))
            try:
                assert entered.wait(5)
                cancelled = call(run, "cancel_export_task", {"jobId": created["jobId"]})
                assert cancelled["cancelRequested"]
            finally:
                release.set()
            terminal = wait_export(run, created["jobId"])
            assert (
                terminal["status"] == "failed"
                and terminal["cancelRequested"]
                and not terminal["artifactAvailable"]
            )
            assert reader.call_count == 0


@pytest.mark.parametrize("max_steps", [0, 8])
@pytest.mark.django_db(transaction=True)
def test_export_parks_model_then_resumes_after_real_file_without_model_polling(
    operations, monkeypatch, max_steps
):
    from apps.agent import export_tools
    from apps.agent.export_followups import resume_exports
    from apps.agent.worker import run_task, claim
    from tests.integration.test_agent_interactions import mock_model

    env = operations
    entered, release = threading.Event(), threading.Event()
    original = export_tools._items

    def blocked(*args, **kwargs):
        if kwargs.get("materialize", True):
            entered.set()
            assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(export_tools, "_items", blocked)
    with project_scope(env["scope"]):
        run, detail = prepare(env)
        AgentPolicy.objects.update_or_create(
            pk=1, defaults={"value": {**default_policy(), "maxSteps": max_steps}}
        )
        run.prompt = "请把准备好的个人工程导出，完成后提供下载入口"
        run.save(update_fields=["prompt"])
        captured = []
        mock_model(
            monkeypatch,
            [
                {"action": "export_map_workspace", "arguments": export_args(detail)},
                {"action": "final", "answer": "导出文件已就绪，可点击下方按钮下载。"},
            ],
            captured,
        )
        try:
            run_task(run.pk)
            run.refresh_from_db()
            assert (
                entered.wait(5)
                and run.status == "waiting_compute"
                and len(captured) == 1
            )
            identity = run.execution_state["exportJobIds"][0]
        finally:
            release.set()
        terminal = wait_export(run, identity)
        assert terminal["artifactAvailable"]
        resume_exports()
        run.refresh_from_db()
        assert run.status == "queued" and len(captured) == 1
        assert claim() == run.pk
        run_task(run.pk)
        run.refresh_from_db()
        assert run.status == "succeeded" and len(captured) == 2
        assert any(
            action["kind"] == "export"
            for action in platform_actions(run, env["user"], default_policy())
        )
        url = f"/api/catalog/export/jobs/{identity}/download/"
        for _ in range(2):
            response = env["client"].get(url, **env["header"])
            assert response.status_code == 200
            assert b"".join(response.streaming_content).startswith(b"PK")
            response.close()
        assert jobs.get_job_artifact_path(identity).is_file()


@pytest.mark.django_db(transaction=True)
def test_finished_export_download_rechecks_source_owner_only(operations):
    env = operations
    with project_scope(env["scope"]):
        run, detail = prepare(env)
        exported = call(run, "export_map_workspace", export_args(detail))
        assert wait_export(run, exported["jobId"])["artifactAvailable"]
        env["vector"].owner_only = True
        env["vector"].maintainer = env["admin"]
        env["vector"].save(update_fields=["owner_only", "maintainer", "updated_at"])
    response = env["client"].get(
        f"/api/catalog/export/jobs/{exported['jobId']}/download/", **env["header"]
    )
    assert response.status_code == 403
