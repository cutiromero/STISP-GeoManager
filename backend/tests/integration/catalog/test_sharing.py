import hashlib
import json
from dataclasses import replace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.catalog.models import (
    DataResource,
    MapComposition,
    MapCompositionVersion,
    ShareInvitation,
    WorkspaceScene,
)
from apps.compute.models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeImport,
    ComputeInput,
    ComputeOutput,
    ComputeTask,
)
from apps.core.initialization import PLATFORM_ADMIN_GROUP_NAME
from apps.projects.models import Project, ProjectMembership


pytestmark = pytest.mark.django_db


@pytest.fixture
def env(settings, tmp_path):
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=tmp_path / "app",
        research_data_root=tmp_path / "research",
    )
    users = [
        get_user_model().objects.create_user(name, password="test-password")
        for name in ("share-owner", "share-reader", "share-other")
    ]
    features = Permission.objects.filter(
        codename__in=[
            "browse_data",
            "load_vector_layer",
            "load_raster_layer",
            "view_dataresource",
            "view_workspacescene",
            "view_mapcomposition",
            "view_own_task",
            "export_dataresource",
            "add_dataresource",
        ]
    )
    for user in users:
        user.user_permissions.add(*features)
    owner, recipient, stranger = users
    project = Project.objects.create(name="邀请测试项目", code="sharing-test")
    other_project = Project.objects.create(name="其他邀请项目", code="sharing-other")
    for user in users:
        ProjectMembership.objects.create(project=project, user=user)
    resource = DataResource.objects.create(
        project_tag=project,
        name="公开输入表",
        code="share-table",
        data_type="table",
        status="active",
        maintainer=owner,
    )
    scene = WorkspaceScene.objects.create(
        project_tag=project,
        owner=owner,
        name="共享工程",
        kind="project",
        snapshot={"groups": [{"children": [{"sourceResource": {"id": resource.id}}]}]},
    )
    composition = MapComposition.objects.create(
        project_tag=project,
        owner=owner,
        project=scene,
        name="草稿专题",
        layout={"title": "可查看不可改"},
        source_workspace_snapshot=scene.snapshot,
    )
    algorithm = AlgorithmResource.objects.create(
        project_tag=project, identifier="share-test", name="分享测试", created_by=owner
    )
    version = AlgorithmVersion.objects.create(
        algorithm=algorithm,
        version="1.0.0",
        checksum="a" * 64,
        package_path="test.zip",
        manifest={},
    )
    task = ComputeTask.objects.create(
        project_tag=project,
        owner=owner,
        version=version,
        name="不应共享整个任务",
        status="succeeded",
        parameters={"secret": "not-shared"},
        idempotency_key="test-task",
        request_hash="b" * 64,
    )
    ComputeInput.objects.create(
        task=task,
        key="table",
        resource=resource,
        snapshot={"privateSnapshot": "not-shared"},
    )
    raw = b"name,value\nA,1\n"
    path = settings.PROJECT_CONFIG.app_path("compute", "shared.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    outputs = [
        ComputeOutput.objects.create(
            task=task,
            key=key,
            label=key,
            kind="table",
            file_name="shared.csv",
            path="compute/shared.csv",
            size_bytes=len(raw),
            checksum=hashlib.sha256(raw).hexdigest(),
            metadata={"rowCount": 1, "hostPath": "not-shared"},
        )
        for key in ("chosen", "other")
    ]
    clients = []
    for user in users:
        client = Client()
        client.force_login(user)
        clients.append(client)
    return {
        "owner": owner,
        "recipient": recipient,
        "stranger": stranger,
        "project": project,
        "other_project": other_project,
        "resource": resource,
        "scene": scene,
        "composition": composition,
        "task": task,
        "output": outputs[0],
        "other_output": outputs[1],
        "clients": clients,
    }


def post(env, suffix, body=None, actor=0, project=None):
    return env["clients"][actor].post(
        "/api/sharing/" + suffix,
        data=json.dumps(body or {}),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(project or env["project"].id),
    )


def invite(env, kind="compute_output", identity=None, key="send-1"):
    identity = (
        identity
        or env[
            {
                "compute_output": "output",
                "workspace": "scene",
                "composition": "composition",
            }[kind]
        ].id
    )
    return post(
        env,
        "invitations/",
        {
            "kind": kind,
            "objectId": identity,
            "username": env["recipient"].username,
            "idempotencyKey": key,
        },
    )


def accept(env, invitation, decision="accept", key="answer-1"):
    return post(
        env,
        f"invitations/{invitation}/respond/",
        {"decision": decision, "idempotencyKey": key},
        actor=1,
        project=1,
    )


def test_exact_username_precheck_self_and_cross_project(env):
    body = {
        "kind": "workspace",
        "objectId": env["scene"].id,
        "username": env["recipient"].username,
    }
    assert post(env, "check/", body).json()["eligible"]
    for name in ("share-rea", "SHARE-READER", env["owner"].username):
        response = post(env, "check/", {**body, "username": name})
        assert response.status_code == 200 and not response.json()["eligible"]
        assert "recipient" not in response.json()
    assert not post(env, "check/", body, project=1).json()["eligible"]
    assert ShareInvitation._base_manager.count() == 0


@pytest.mark.parametrize("platform_admin", [False, True])
def test_workspace_private_list_search_direct_access_and_management(
    env, platform_admin
):
    reader = env["clients"][1]
    if platform_admin:
        group, _ = Group.objects.get_or_create(name=PLATFORM_ADMIN_GROUP_NAME)
        env["recipient"].groups.add(group)
    env["recipient"].user_permissions.add(
        *Permission.objects.filter(
            codename__in=["change_workspacescene", "delete_workspacescene"]
        )
    )
    suffix = f"?projectTagId={env['project'].id}"
    base = f"/api/catalog/workspaces/{env['scene'].id}/"
    for url in (
        "/api/catalog/workspaces/" + suffix,
        "/api/catalog/workspaces/" + suffix + "&q=共享工程",
        "/api/admin/workspaces/" + suffix,
    ):
        response = reader.get(url)
        assert response.status_code == 200
        assert response.json()["items"] == [] and response.json()["total"] == 0
    assert reader.get(base + suffix).status_code == 404
    for url, body in (
        (base, {"name": "不应修改"}),
        (base, {"action": "delete"}),
        (
            f"/api/admin/workspaces/{env['scene'].id}/",
            {"action": "setStatus", "status": "inactive"},
        ),
        (
            f"/api/admin/workspaces/{env['scene'].id}/",
            {"action": "delete", "confirmationName": env["scene"].name},
        ),
    ):
        response = reader.post(
            url + suffix, data=json.dumps(body), content_type="application/json"
        )
        assert response.status_code == 404
    env["scene"].refresh_from_db()
    assert env["scene"].name == "共享工程" and env["scene"].status == "active"
    assert (
        post(
            env,
            "invitations/",
            {
                "kind": "workspace",
                "objectId": env["scene"].id,
                "username": env["stranger"].username,
                "idempotencyKey": "private-share",
            },
            actor=1,
        ).status_code
        == 403
    )
    env["recipient"].user_permissions.add(
        Permission.objects.get(codename="add_mapcomposition")
    )
    response = reader.post(
        "/api/catalog/map-compositions/" + suffix,
        data=json.dumps(
            {"projectId": env["scene"].id, "name": "越权来源", "layout": {}}
        ),
        content_type="application/json",
    )
    assert response.status_code == 404


@pytest.mark.parametrize("platform_admin", [False, True])
def test_workspace_accept_grants_read_only_and_pending_or_reject_does_not(
    env, platform_admin
):
    reader = env["clients"][1]
    if platform_admin:
        group, _ = Group.objects.get_or_create(name=PLATFORM_ADMIN_GROUP_NAME)
        env["recipient"].groups.add(group)
    suffix = f"?projectTagId={env['project'].id}"
    detail = f"/api/catalog/workspaces/{env['scene'].id}/" + suffix
    listing = "/api/catalog/workspaces/" + suffix + "&q=共享工程"
    rejected = invite(env, "workspace").json()["id"]
    assert reader.get(detail).status_code == 404
    assert reader.get(listing).json()["items"] == []
    assert accept(env, rejected, "reject").json()["status"] == "rejected"
    assert reader.get(detail).status_code == 404
    invitation = invite(env, "workspace", key="send-workspace-again").json()["id"]
    assert (
        accept(env, invitation, key="accept-workspace").json()["status"] == "accepted"
    )
    value = reader.get(detail).json()
    assert value["snapshot"] == env["scene"].snapshot
    assert not any(
        value[key] for key in ("isOwner", "canEdit", "canDelete", "canManageAccess")
    )
    assert [item["id"] for item in reader.get(listing).json()["items"]] == [
        env["scene"].id
    ]
    for url in (detail, f"/api/admin/workspaces/{env['scene'].id}/" + suffix):
        response = reader.post(
            url,
            data=json.dumps({"action": "update", "name": "不可修改"}),
            content_type="application/json",
        )
        assert response.status_code in (403, 404)


@pytest.mark.parametrize(
    "change",
    [
        "private_dependency",
        "sender_membership",
        "recipient_membership",
        "sender_owner",
        "inactive",
    ],
)
def test_accepted_workspace_access_rechecks_live_dependencies(env, change):
    invitation = invite(env, "workspace").json()["id"]
    assert accept(env, invitation).json()["status"] == "accepted"
    reader = env["clients"][1]
    url = f"/api/catalog/workspaces/{env['scene'].id}/?projectTagId={env['project'].id}"
    assert reader.get(url).status_code == 200
    if change == "private_dependency":
        DataResource._base_manager.filter(pk=env["resource"].id).update(owner_only=True)
    elif change.endswith("membership"):
        actor = env["owner" if change.startswith("sender") else "recipient"]
        ProjectMembership.objects.filter(project=env["project"], user=actor).delete()
    elif change == "sender_owner":
        WorkspaceScene._base_manager.filter(pk=env["scene"].id).update(
            owner=env["stranger"]
        )
    else:
        WorkspaceScene._base_manager.filter(pk=env["scene"].id).update(
            status="inactive"
        )
    assert reader.get(url).status_code in (403, 404)


def test_sharing_composition_does_not_grant_private_source_workspace(env):
    invitation = invite(env, "composition").json()["id"]
    assert accept(env, invitation).json()["status"] == "accepted"
    url = f"/api/catalog/map-compositions/{env['composition'].id}/?projectTagId={env['project'].id}"
    reader = env["clients"][1]
    assert reader.get(url).json()["canLoadSourceProject"] is False
    invitation = invite(env, "workspace", key="workspace-source").json()["id"]
    assert accept(env, invitation, key="accept-source").json()["status"] == "accepted"
    assert reader.get(url).json()["canLoadSourceProject"] is True


def test_send_rechecks_recipient_after_successful_precheck(env):
    body = {
        "kind": "workspace",
        "objectId": env["scene"].id,
        "username": env["recipient"].username,
    }
    assert post(env, "check/", body).json()["eligible"]
    ProjectMembership.objects.filter(
        project=env["project"], user=env["recipient"]
    ).delete()
    assert invite(env, "workspace").status_code == 403
    assert ShareInvitation._base_manager.count() == 0


@pytest.mark.parametrize("kind", ["workspace", "compute_output"])
def test_existing_superadmin_can_share_managed_objects(env, kind):
    get_user_model().objects.filter(pk=env["stranger"].id).update(is_superuser=True)
    response = post(
        env,
        "invitations/",
        {
            "kind": kind,
            "objectId": env["scene" if kind == "workspace" else "output"].id,
            "username": env["recipient"].username,
            "idempotencyKey": "admin-share",
        },
        actor=2,
    )
    assert response.status_code == 201
    assert response.json()["sender"]["username"] == env["stranger"].username


def test_pending_invite_is_not_grant_and_only_one_output_after_accept(env):
    created = invite(env)
    assert created.status_code == 201
    invitation = created.json()["id"]
    reader = env["clients"][1]
    url = f"/api/compute/outputs/{env['output'].id}/preview/?projectTagId={env['project'].id}"
    assert reader.get(url).status_code == 404
    assert accept(env, invitation).json()["status"] == "accepted"
    opened = reader.get(f"/api/sharing/invitations/{invitation}/open/")
    assert opened.status_code == 200
    value = opened.json()
    assert value["target"]["openUrl"] == f"/compute?sharedInvitation={invitation}"
    assert value["output"]["id"] == env["output"].id
    assert "hostPath" not in value["output"]["metadata"]
    assert "task" not in value and "inputs" not in value
    assert reader.get(url).status_code == 200
    assert (
        reader.get(
            f"/api/compute/tasks/{env['task'].id}/?projectTagId={env['project'].id}"
        ).status_code
        == 404
    )
    assert (
        reader.get(
            f"/api/compute/outputs/{env['other_output'].id}/preview/?projectTagId={env['project'].id}"
        ).status_code
        == 404
    )


def test_sender_and_recipient_notifications_persist_and_mark_separately(env):
    invitation = invite(env, "workspace").json()["id"]
    reader, owner = env["clients"][1], env["clients"][0]
    inbox = reader.get("/api/sharing/invitations/?box=received").json()
    assert inbox["total"] == inbox["unreadCount"] == 1
    assert inbox["items"][0]["target"]["projectTagId"] == env["project"].id
    assert (
        post(env, f"invitations/{invitation}/read/", actor=1).json()["unread"] is False
    )
    assert owner.get("/api/sharing/invitations/?box=sent").json()["unreadCount"] == 0
    assert accept(env, invitation, "reject").json()["status"] == "rejected"
    assert owner.get("/api/sharing/invitations/?box=sent").json()["unreadCount"] == 1
    assert post(env, f"invitations/{invitation}/read/").json()["unread"] is False
    assert reader.get(f"/api/sharing/invitations/{invitation}/open/").status_code == 409
    assert ShareInvitation._base_manager.get(pk=invitation).status == "rejected"


def test_send_and_response_idempotency_and_old_decision_conflict(env):
    first = invite(env)
    invitation = first.json()["id"]
    assert invite(env).status_code == 200
    assert invite(env, key="another-click").json()["id"] == invitation
    assert ShareInvitation._base_manager.count() == 1
    assert invite(env, identity=env["other_output"].id).status_code == 409
    assert accept(env, invitation).json()["status"] == "accepted"
    assert accept(env, invitation, key="another-answer").json()["status"] == "accepted"
    assert accept(env, invitation, "reject").status_code == 409
    assert ShareInvitation._base_manager.count() == 1


@pytest.mark.parametrize(
    "change",
    ["private", "membership", "feature", "disabled", "missing", "sender_rights"],
)
def test_permission_changes_before_accept_fail_and_notify_sender(env, change):
    invitation = invite(env).json()["id"]
    if change == "private":
        DataResource._base_manager.filter(pk=env["resource"].id).update(owner_only=True)
    elif change == "membership":
        ProjectMembership.objects.filter(
            project=env["project"], user=env["owner"]
        ).delete()
    elif change == "feature":
        env["recipient"].user_permissions.remove(
            *Permission.objects.filter(codename="view_own_task")
        )
    elif change == "disabled":
        get_user_model().objects.filter(pk=env["owner"].id).update(is_active=False)
    elif change == "missing":
        env["output"].delete()
    else:
        ComputeTask._base_manager.filter(pk=env["task"].id).update(
            owner=env["stranger"]
        )
    response = accept(env, invitation)
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert "未能接受" in response.json()["detail"]
    assert ShareInvitation._base_manager.get(pk=invitation).sender_read_at is None


def test_private_dependency_rejected_without_changing_private_flag(env):
    DataResource._base_manager.filter(pk=env["resource"].id).update(owner_only=True)
    for kind in ("workspace", "composition", "compute_output"):
        response = invite(env, kind, key=kind)
        assert response.status_code == 403
    assert ShareInvitation._base_manager.count() == 0
    env["resource"].refresh_from_db()
    assert env["resource"].owner_only


def test_live_grant_rechecks_input_rights_and_download_permissions(env):
    invitation = invite(env).json()["id"]
    accept(env, invitation)
    reader = env["clients"][1]
    url = f"/api/compute/outputs/{env['output'].id}/file/?projectTagId={env['project'].id}"
    response = reader.get(url)
    assert response.status_code == 200
    assert b"A,1" in b"".join(response.streaming_content)
    env["recipient"].user_permissions.remove(
        *Permission.objects.filter(codename="export_dataresource")
    )
    assert reader.get(url).status_code == 403
    DataResource._base_manager.filter(pk=env["resource"].id).update(owner_only=True)
    assert (
        reader.get(
            f"/api/compute/outputs/{env['output'].id}/preview/?projectTagId={env['project'].id}"
        ).status_code
        == 404
    )
    assert reader.get(f"/api/sharing/invitations/{invitation}/open/").status_code == 403
    assert ShareInvitation._base_manager.get(pk=invitation).status == "unavailable"


def test_other_user_cannot_share_read_respond_or_open(env):
    assert (
        post(
            env,
            "invitations/",
            {
                "kind": "workspace",
                "objectId": env["scene"].id,
                "username": env["recipient"].username,
                "idempotencyKey": "stolen",
            },
            actor=2,
        ).status_code
        == 403
    )
    invitation = invite(env).json()["id"]
    for action in ("read", "respond"):
        body = (
            {"decision": "accept", "idempotencyKey": "third-party"}
            if action == "respond"
            else {}
        )
        assert (
            post(env, f"invitations/{invitation}/{action}/", body, actor=2).status_code
            == 404
        )
    assert (
        env["clients"][2]
        .get(f"/api/sharing/invitations/{invitation}/open/")
        .status_code
        == 404
    )
    assert env["clients"][2].get("/api/sharing/invitations/").json()["total"] == 0


def test_composition_draft_accepted_read_without_management(env):
    reader = env["clients"][1]
    url = f"/api/catalog/map-compositions/{env['composition'].id}/?projectTagId={env['project'].id}"
    assert reader.get(url).status_code == 404
    invitation = invite(env, "composition").json()["id"]
    accept(env, invitation)
    response = reader.get(url)
    assert response.status_code == 200
    assert response.json()["layout"] == env["composition"].layout
    assert not response.json()["canEditLayout"] and not response.json()["canDelete"]
    assert (
        reader.post(
            url,
            data=json.dumps({"description": "unauthorized"}),
            content_type="application/json",
        ).status_code
        == 404
    )
    DataResource._base_manager.filter(pk=env["resource"].id).update(owner_only=True)
    assert reader.get(url).status_code == 404


def test_revoked_project_hidden_from_cross_project_box(env):
    invite(env, "workspace")
    ProjectMembership.objects.filter(
        project=env["project"], user=env["recipient"]
    ).delete()
    assert env["clients"][1].get("/api/sharing/invitations/").json()["items"] == []


def test_sharing_does_not_bypass_private_import_or_deleted_input(env):
    private = DataResource.objects.create(
        project_tag=env["project"],
        name="仅本人结果",
        code="private-result",
        data_type="table",
        owner_only=True,
        maintainer=env["owner"],
    )
    ComputeImport.objects.create(
        output=env["output"],
        requested_by=env["owner"],
        name=private.name,
        status="ready",
        resource=private,
    )
    assert invite(env).status_code == 403
    ComputeImport.objects.all().delete()
    ComputeInput.objects.filter(task=env["task"]).update(resource=None)
    assert invite(env).status_code == 403


def test_all_hidden_and_cross_project_snapshot_dependencies_are_checked(env):
    hidden = DataResource.objects.create(
        project_tag=env["project"],
        name="隐藏图层",
        code="hidden-private",
        data_type="table",
        owner_only=True,
        maintainer=env["owner"],
    )
    foreign = DataResource.objects.create(
        project_tag=env["other_project"],
        name="外项目图层",
        code="foreign-table",
        data_type="table",
        maintainer=env["owner"],
    )
    for resource in (hidden, foreign):
        env["scene"].snapshot = {
            "groups": [
                {
                    "visible": False,
                    "children": [{"sourceResource": {"id": resource.id}}],
                }
            ]
        }
        env["scene"].save()
        assert invite(env, "workspace").status_code == 403


def test_owner_missing_view_permission_cannot_use_share_fallback(env):
    env["owner"].user_permissions.remove(
        *Permission.objects.filter(codename="view_own_task")
    )
    response = env["clients"][0].get(
        f"/api/compute/outputs/{env['output'].id}/preview/?projectTagId={env['project'].id}"
    )
    assert response.status_code == 403


def test_result_import_still_requires_own_feature_permission(env):
    invitation = invite(env).json()["id"]
    accept(env, invitation)
    env["recipient"].user_permissions.remove(
        *Permission.objects.filter(codename="add_dataresource")
    )
    response = env["clients"][1].post(
        f"/api/compute/outputs/{env['output'].id}/import/?projectTagId={env['project'].id}",
        data=json.dumps({"name": "导入单结果"}),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )
    assert response.status_code == 403, response.content
    assert not ComputeImport.objects.filter(output=env["output"]).exists()


def test_global_accept_checks_version_only_private_dependencies(env):
    env["scene"].snapshot = {"groups": []}
    env["scene"].save()
    env["composition"].source_workspace_snapshot = {"groups": []}
    env["composition"].save()
    version = MapCompositionVersion.objects.create(
        project_tag=env["project"],
        composition=env["composition"],
        version_number=1,
        format="png",
        width_px=1,
        height_px=1,
        preview_path="unused.png",
        artifact_path="unused.png",
        workspace_snapshot={"groups": []},
    )
    invitation = invite(env, "composition").json()["id"]
    DataResource._base_manager.filter(pk=env["resource"].id).update(owner_only=True)
    version.workspace_snapshot = {
        "groups": [{"children": [{"sourceResource": {"id": env["resource"].id}}]}]
    }
    version.save()
    response = accept(env, invitation)
    assert response.status_code == 200 and response.json()["status"] == "unavailable"


def test_shared_composition_version_files_keep_export_permission(env, settings):
    for number in (1, 2):
        path = settings.PROJECT_CONFIG.app_path("exports", f"v{number}.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test-preview")
        MapCompositionVersion.objects.create(
            project_tag=env["project"],
            composition=env["composition"],
            version_number=number,
            format="png",
            width_px=1,
            height_px=1,
            preview_path=f"exports/v{number}.png",
            artifact_path=f"exports/v{number}.png",
            layout_snapshot={},
            workspace_snapshot=env["scene"].snapshot,
        )
    invitation = invite(env, "composition").json()["id"]
    accept(env, invitation)
    reader = env["clients"][1]
    base = f"/api/catalog/map-compositions/{env['composition'].id}/versions/"
    assert (
        reader.get(
            base + f"1/file/?variant=preview&projectTagId={env['project'].id}"
        ).status_code
        == 404
    )
    response = reader.get(
        base + f"2/file/?variant=preview&projectTagId={env['project'].id}"
    )
    assert response.status_code == 200
    response.close()
    assert (
        reader.get(
            base + f"2/file/?variant=artifact&projectTagId={env['project'].id}"
        ).status_code
        == 403
    )
