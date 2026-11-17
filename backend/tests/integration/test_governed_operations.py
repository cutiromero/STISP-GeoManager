"""Real user decisions, exact previews and new-only business writes."""

from datetime import timedelta
import hashlib
import json
from io import BytesIO
from PIL import Image
import sqlite3

import pytest
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.agent.attachments import store_attachment
from apps.agent.models import AgentOperation
from apps.agent.tools import execute
from apps.catalog.models import (
    DataResource,
    DictionaryItem,
    ResultArtifact,
    ShareInvitation,
    WorkspaceScene,
)
from apps.core.storage import app_path, table_data_path
from apps.projects.context import project_scope
from apps.projects.models import ProjectMembership
from tests.integration.test_agent import new_run, setup_agent  # noqa: F401
from tests.integration.test_agent_runtime_heartbeat import wal_database  # noqa: F401

# ruff: noqa: F811
pytestmark = pytest.mark.django_db


@pytest.fixture
def governed(setup_agent):
    env = setup_agent
    permissions = Permission.objects.filter(
        codename__in=[
            "add_dataresource",
            "view_dataresource",
            "view_workspacescene",
            "view_mapcomposition",
            "publish_mapcomposition",
            "view_resultartifact",
            "publish_resultartifact",
            "load_vector_layer",
            "browse_data",
        ]
    )
    env["user"].user_permissions.add(*permissions)
    env["other"].user_permissions.add(*permissions)
    ProjectMembership.objects.create(project=env["project"], user=env["other"])
    with project_scope(env["scope"]):
        attachment = store_attachment(
            conversation=env["conversation"],
            owner=env["user"],
            upload=SimpleUploadedFile(
                "sample.csv",
                b"name,lon,lat,value\nA,120.123456,30.123456,1\nB,120.234567,30.234567,2\n",
            ),
        )
        run = new_run(env, attachment_ids=[attachment.pk])
        path = app_path("exports", "results", "proof.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        image = BytesIO()
        Image.new("RGB", (8, 8), "white").save(image, format="PNG")
        path.write_bytes(image.getvalue())
        artifact = ResultArtifact.objects.create(
            owner=env["user"],
            name="待发布成果",
            category=DictionaryItem.objects.get_or_create(
                dict_type="data_category", code="spatial", defaults={"name": "地理数据"}
            )[0],
            file_path="exports/results/proof.png",
            file_name="proof.png",
        )
        scene = WorkspaceScene.objects.create(
            owner=env["user"],
            name="待分享工程",
            kind="project",
            snapshot={
                "groups": [
                    {"children": [{"sourceResource": {"id": env["resource"].pk}}]}
                ]
            },
        )
    return {
        **env,
        "run": run,
        "attachment": attachment,
        "artifact": artifact,
        "scene": scene,
    }


def preview(env, tool, args):
    with project_scope(env["scope"]):
        return execute(env["run"], tool, args)[0]


def decide(env, operation, decision="confirm", **extra):
    return env["client"].post(
        f"/api/agent/operations/{operation['id']}/",
        json.dumps({"decision": decision, "digest": operation["digest"], **extra}),
        content_type="application/json",
        **env["header"],
    )


def test_stopped_run_never_advertises_confirmation(governed):
    from apps.agent.models import AgentRun

    env = governed
    operation = preview(
        env, "preview_publication", {"kind": "result", "objectId": env["artifact"].pk}
    )
    AgentRun.objects.filter(pk=env["run"].pk).update(cancel_requested=True)
    response = env["client"].get(
        f"/api/agent/operations/{operation['id']}/", **env["header"]
    )
    assert response.status_code == 200
    assert response.json()["canConfirm"] is False
    assert "停止" in response.json()["detail"]


@pytest.mark.parametrize("switch", ["allowAttachments", "allowDocuments"])
def test_import_rechecks_attachment_policy_after_preview_read(
    governed, monkeypatch, switch
):
    from apps.agent import operation_proposals
    from apps.agent.models import AgentPolicy
    from apps.agent.policy import default_policy

    env = governed
    operation = preview(
        env,
        "preview_data_import",
        {
            "attachmentId": env["attachment"].pk,
            "name": "撤权后不能导入",
            "importMode": "table",
        },
    )
    original = operation_proposals.inspect

    def revoke_after_inspection(*args, **kwargs):
        value = original(*args, **kwargs)
        AgentPolicy.objects.update_or_create(
            pk=1, defaults={"value": {**default_policy(), switch: False}}
        )
        return value

    monkeypatch.setattr(operation_proposals, "inspect", revoke_after_inspection)
    before = DataResource._base_manager.count()
    response = decide(env, operation)
    assert response.status_code == 403, response.content
    assert DataResource._base_manager.count() == before
    assert AgentOperation._base_manager.get(pk=operation["id"]).status == "failed"


def test_unavailable_proposal_does_not_hide_other_operations_or_leak_old_preview(
    governed,
):
    env = governed
    unavailable = preview(
        env, "preview_publication", {"kind": "result", "objectId": env["artifact"].pk}
    )
    available = preview(
        env,
        "preview_share",
        {
            "kind": "workspace",
            "objectId": env["scene"].pk,
            "username": env["other"].username,
        },
    )
    env["artifact"].delete()
    response = env["client"].get(
        f"/api/agent/runs/{env['run'].pk}/operations/", **env["header"]
    )
    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert items[available["id"]]["canConfirm"] is True
    hidden = items[unavailable["id"]]
    assert hidden["canConfirm"] is False and hidden["result"] == {}
    assert env["artifact"].name not in json.dumps(hidden, ensure_ascii=False)
    assert decide(env, available).status_code == 200


@pytest.mark.parametrize("mode", ["table", "geographic"])
def test_import_is_new_private_real_and_confirmation_is_idempotent(governed, mode):
    env = governed
    args = {
        "attachmentId": env["attachment"].pk,
        "name": "新资料",
        "importMode": mode,
        **(
            {"longitudeColumn": "lon", "latitudeColumn": "lat"}
            if mode == "geographic"
            else {}
        ),
    }
    source = app_path(env["attachment"].path)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    total = DataResource._base_manager.count()
    operation = preview(env, "preview_data_import", args)
    again = preview(env, "preview_data_import", args)
    assert operation["id"] == again["id"] and operation["status"] == "pending"
    assert DataResource._base_manager.count() == total
    assert decide(env, operation, confirmed=True).status_code == 400
    response = decide(env, operation)
    assert response.status_code == 200, response.content
    result = response.json()
    assert result["status"] == "confirmed" and result["result"]["importedRows"] == 2
    resource = DataResource._base_manager.get(pk=result["result"]["resourceId"])
    assert resource.owner_only and resource.maintainer_id == env["user"].pk
    assert decide(env, operation).json()["result"] == result["result"]
    assert DataResource._base_manager.count() == total + 1
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    with (
        project_scope(env["scope"]),
        sqlite3.connect(table_data_path("data.sqlite")) as db,
    ):
        assert db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 4
        if mode == "table":
            assert (
                db.execute(
                    'SELECT COUNT(*) FROM "' + resource.storage_path + '"'
                ).fetchone()[0]
                == 2
            )


def test_expired_or_changed_publication_cannot_execute_and_repeat_is_single_effect(
    governed,
):
    env = governed
    args = {"kind": "result", "objectId": env["artifact"].pk}
    operation = preview(env, "preview_publication", args)
    env["artifact"].refresh_from_db()
    assert env["artifact"].status == "draft"
    AgentOperation.objects.filter(pk=operation["id"]).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    expired = decide(env, operation)
    assert expired.status_code == 409
    assert (
        expired.json()["code"] == "REVISION_CONFLICT"
        and expired.json()["retryable"] is False
    )
    operation = preview(env, "preview_publication", args)
    env["artifact"].name = "新的修订"
    env["artifact"].save(update_fields=["name", "updated_at"])
    assert decide(env, operation).status_code == 409
    operation = preview(env, "preview_publication", args)
    response = decide(env, operation)
    assert response.status_code == 200, response.content
    env["artifact"].refresh_from_db()
    stamp = env["artifact"].published_at
    assert env["artifact"].status == "published"
    assert decide(env, operation).status_code == 200
    env["artifact"].refresh_from_db()
    assert env["artifact"].published_at == stamp
    assert decide(env, operation, "reject").status_code == 409
    old_id = operation["id"]
    env["artifact"].status = "draft"
    env["artifact"].save(update_fields=["status", "updated_at"])
    fresh = preview(env, "preview_publication", args)
    assert fresh["id"] != old_id and fresh["status"] == "pending"


def test_share_only_sends_real_invitation_after_user_confirmation(governed):
    env = governed
    args = {
        "kind": "workspace",
        "objectId": env["scene"].pk,
        "username": env["other"].username,
    }
    operation = preview(env, "preview_share", args)
    assert ShareInvitation._base_manager.count() == 0
    response = decide(env, operation)
    assert response.status_code == 200, response.content
    invitation = ShareInvitation._base_manager.get()
    assert invitation.status == "pending" and invitation.recipient_id == env["other"].pk
    assert decide(env, operation).status_code == 200
    assert ShareInvitation._base_manager.count() == 1


@pytest.mark.parametrize(
    "change", ["recipient", "source", "permission", "stopped", "digest"]
)
def test_live_revalidation_blocks_revoked_or_stale_operations(governed, change):
    env = governed
    operation = preview(
        env,
        "preview_share",
        {
            "kind": "workspace",
            "objectId": env["scene"].pk,
            "username": env["other"].username,
        },
    )
    if change == "recipient":
        ProjectMembership.objects.filter(
            project=env["project"], user=env["other"]
        ).delete()
    elif change == "source":
        env["resource"].owner_only = True
        env["resource"].save(update_fields=["owner_only", "updated_at"])
    elif change == "permission":
        env["user"].user_permissions.remove(
            Permission.objects.get(
                codename="view_workspacescene", content_type__app_label="catalog"
            )
        )
    elif change == "stopped":
        env["run"].cancel_requested = True
        env["run"].save(update_fields=["cancel_requested"])
    else:
        operation["digest"] = "0" * 64
    response = decide(env, operation)
    assert response.status_code in {403, 409}, response.content
    assert not ShareInvitation._base_manager.exists()


def test_other_owner_and_project_cannot_read_or_decide_and_model_has_no_confirm_tool(
    governed,
):
    from apps.agent.tools import TOOLS

    env = governed
    operation = preview(
        env, "preview_publication", {"kind": "result", "objectId": env["artifact"].pk}
    )
    env["client"].force_login(env["other"])
    assert decide(env, operation).status_code == 404
    assert (
        env["client"]
        .get(f"/api/agent/runs/{env['run'].pk}/operations/", **env["header"])
        .status_code
        == 404
    )
    env["client"].force_login(env["user"])
    assert (
        env["client"]
        .get(f"/api/agent/operations/{operation['id']}/", HTTP_X_PROJECT_ID="1")
        .status_code
        == 404
    )
    assert not {"confirm_operation", "approve_operation", "grant_permissions"} & set(
        TOOLS
    )


def test_proposal_read_never_reopens_csv_and_csrf_is_required(governed, monkeypatch):
    from django.test import Client

    env = governed
    operation = preview(
        env,
        "preview_data_import",
        {
            "attachmentId": env["attachment"].pk,
            "name": "只读状态验收",
            "importMode": "table",
        },
    )

    def no_read(*args, **kwargs):
        raise AssertionError("Reading proposal status must not reopen raw attachments")

    monkeypatch.setattr("apps.agent.operation_proposals.attachment_source", no_read)
    response = env["client"].get(
        f"/api/agent/runs/{env['run'].pk}/operations/", **env["header"]
    )
    assert (
        response.status_code == 200
        and response.json()["items"][0]["id"] == operation["id"]
    )
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(env["user"])
    response = csrf_client.post(
        f"/api/agent/operations/{operation['id']}/",
        json.dumps({"decision": "confirm", "digest": operation["digest"]}),
        content_type="application/json",
        **env["header"],
    )
    assert response.status_code == 403
    assert AgentOperation.objects.get(pk=operation["id"]).status == "pending"


@pytest.mark.django_db(transaction=True)
@pytest.mark.efficiency
def test_concurrent_confirmation_claims_once_and_keeps_real_invitation(
    governed, wal_database
):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections
    from apps.agent.operation_proposals import decide as decide_service

    env = governed
    operation = preview(
        env,
        "preview_share",
        {
            "kind": "workspace",
            "objectId": env["scene"].pk,
            "username": env["other"].username,
        },
    )

    def confirm():
        close_old_connections()
        try:
            with project_scope(env["scope"]):
                item = AgentOperation.objects.select_related("run__conversation").get(
                    pk=operation["id"]
                )
                return decide_service(item, env["user"], "confirm", operation["digest"])
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: confirm(), range(2)))
    assert all(item["status"] in {"executing", "confirmed"} for item in results)
    assert ShareInvitation._base_manager.count() == 1
    assert AgentOperation._base_manager.get(pk=operation["id"]).status == "confirmed"


def test_model_preview_then_final_reports_confirmation_still_needed(
    governed, monkeypatch
):
    from apps.agent.worker import run_task
    from tests.integration.test_agent_interactions import mock_model

    env = governed
    captured = []
    mock_model(
        monkeypatch,
        [
            {
                "action": "preview_share",
                "arguments": {
                    "kind": "workspace",
                    "objectId": env["scene"].pk,
                    "username": env["other"].username,
                },
            },
            {"action": "final", "answer": "已准备分享预览。"},
        ],
        captured,
    )
    with project_scope(env["scope"]):
        run_task(env["run"].pk)
    env["run"].refresh_from_db()
    assert env["run"].status == "succeeded" and "尚未执行" in env["run"].answer
    assert not ShareInvitation._base_manager.exists()
    assert AgentOperation._base_manager.get(run=env["run"]).status == "pending"


def test_import_discovery_and_execution_share_attachment_policy(governed, monkeypatch):
    from apps.agent.models import AgentPolicy
    from apps.agent.policy import default_policy
    from django.core.exceptions import PermissionDenied

    env = governed
    AgentPolicy.objects.update_or_create(
        pk=1, defaults={"value": {**default_policy(), "allowAttachments": False}}
    )
    response = env["client"].get("/api/agent/capabilities/", **env["header"])
    assert response.status_code == 200 and "preview_data_import" not in {
        item["name"] for item in response.json()["items"]
    }
    with project_scope(env["scope"]), pytest.raises(PermissionDenied):
        execute(
            env["run"],
            "preview_data_import",
            {
                "attachmentId": env["attachment"].pk,
                "name": "拒绝导入",
                "importMode": "table",
            },
        )
    assert not AgentOperation._base_manager.exists()


def test_composition_publication_binds_real_version_and_source_acl(governed):
    from apps.catalog.models import MapComposition, MapCompositionVersion

    env = governed
    with project_scope(env["scope"]):
        composition = MapComposition.objects.create(
            owner=env["user"],
            project=env["scene"],
            name="专题图预览",
            layout={},
            source_workspace_snapshot=env["scene"].snapshot,
        )
        version = MapCompositionVersion.objects.create(
            composition=composition,
            version_number=1,
            format="png",
            width_px=8,
            height_px=8,
            preview_path=env["artifact"].file_path,
            artifact_path=env["artifact"].file_path,
            workspace_snapshot=env["scene"].snapshot,
            resource_manifest=[{"id": env["resource"].pk}],
            created_by=env["user"],
        )
    operation = preview(
        env,
        "preview_publication",
        {"kind": "composition", "objectId": composition.pk, "versionNumber": 1},
    )
    assert composition.status == "draft"
    response = decide(env, operation)
    assert response.status_code == 200, response.content
    composition.refresh_from_db()
    assert (
        composition.status == "published"
        and composition.published_version_id == version.pk
    )
    env["user"].user_permissions.remove(
        Permission.objects.get(
            codename="publish_mapcomposition", content_type__app_label="catalog"
        )
    )
    assert decide(env, operation).status_code == 403


def test_compute_output_share_keeps_task_private_and_waits_for_acceptance(governed):
    from apps.compute.models import (
        AlgorithmResource,
        AlgorithmVersion,
        ComputeTask,
        ComputeInput,
        ComputeOutput,
    )

    env = governed
    feature = Permission.objects.get(
        codename="view_own_task", content_type__app_label="compute"
    )
    for actor in [env["user"], env["other"]]:
        actor.user_permissions.add(feature)
    with project_scope(env["scope"]):
        algorithm = AlgorithmResource.objects.create(
            identifier="operation-test", name="验证算子", created_by=env["user"]
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
            name="独立计算",
            status="succeeded",
            idempotency_key="task",
            request_hash="a" * 64,
        )
        ComputeInput.objects.create(task=task, key="source", resource=env["resource"])
        output = ComputeOutput.objects.create(
            task=task,
            key="image",
            label="真实结果",
            kind="image",
            file_name="proof.png",
            path=env["artifact"].file_path,
            checksum="b" * 64,
            size_bytes=10,
        )
    operation = preview(
        env,
        "preview_share",
        {
            "kind": "compute_output",
            "objectId": output.pk,
            "username": env["other"].username,
        },
    )
    response = decide(env, operation)
    assert response.status_code == 200, response.content
    invitation = ShareInvitation._base_manager.get()
    assert (
        invitation.object_id == output.pk
        and invitation.kind == "compute_output"
        and invitation.status == "pending"
    )
    assert response.json()["result"].get("taskId") is None


def test_dead_confirmation_executor_is_retained_for_verification_without_reexecution(
    governed,
):
    from apps.agent.operation_proposals import reconcile_operations, public
    from apps.raster.services.executor_identity import current_identity

    env = governed
    operation = preview(
        env,
        "preview_share",
        {
            "kind": "workspace",
            "objectId": env["scene"].pk,
            "username": env["other"].username,
        },
    )
    AgentOperation._base_manager.filter(pk=operation["id"]).update(
        status="executing",
        execution_identity={**current_identity(), "instance": "old-process"},
    )
    reconcile_operations()
    item = AgentOperation._base_manager.get(pk=operation["id"])
    assert public(item)["status"] == "interrupted" and not public(item)["canConfirm"]
    assert decide(env, operation).json()["status"] == "interrupted"
    assert not ShareInvitation._base_manager.exists()
