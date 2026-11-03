"""Per-user public opt-out applies to APIs, workers, knowledge and sharing."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.core.exceptions import PermissionDenied

from apps.agent.models import Conversation
from apps.catalog.models import DataResource, ShareInvitation, WorkspaceScene
from apps.catalog.share_access import actor_scope, validate_share
from apps.catalog.sharing import personal_query
from apps.compute.access import require_actor
from apps.compute.packages import ComputeError
from apps.content.models import Article
from apps.core.models import UserProfile
from apps.knowledge.library import visible_documents
from apps.knowledge.models import KnowledgeDocument, KnowledgeEntry, KnowledgeLibrary
from apps.knowledge.services import visible_entries
from apps.projects.access import can_access_project, default_project_id
from apps.projects.context import ProjectScope, project_scope, require_live_membership
from apps.projects.models import Project, ProjectMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def env(client):
    users = get_user_model()
    admin = users.objects.create_superuser("public-policy-admin")
    user = users.objects.create_user("public-policy-researcher")
    other = users.objects.create_user("public-policy-other")
    user.user_permissions.add(
        *Permission.objects.filter(
            codename__in=[
                "browse_data",
                "query_data",
                "view_dataresource",
                "view_workspacescene",
                "load_vector_layer",
                "use_local_model",
                "use_data_agent",
                "view_own_task",
            ]
        )
    )
    other.user_permissions.add(*user.user_permissions.all())
    private = Project.objects.create(name="逻辑推理", code="public-policy-logic")
    ProjectMembership.objects.create(user=user, project=private)
    public_data = DataResource.objects.create(
        name="公开资源", code="public-policy-public", data_type="table"
    )
    private_data = DataResource.objects.create(
        project_tag=private,
        name="逻辑推理资源",
        code="public-policy-private",
        data_type="table",
    )
    return {
        "admin": admin,
        "user": user,
        "other": other,
        "project": private,
        "public": public_data,
        "private": private_data,
    }


def restrict(env):
    profile, _ = UserProfile.objects.get_or_create(user=env["user"])
    profile.allow_public_project = False
    profile.save(update_fields=["allow_public_project"])
    return profile


def test_defaults_preserve_existing_users_and_anonymous_public(client, env):
    for user in (None, env["user"], env["other"]):
        client.logout()
        if user:
            client.force_login(user)
        result = client.get("/api/projects/").json()
        assert 1 in {item["id"] for item in result["items"]}
        assert result["defaultProjectId"] == 1
        assert (
            client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID="1").status_code
            == 200
        )
    assert can_access_project(AnonymousUser(), 1)


def test_restricted_user_defaults_to_assigned_project_and_cannot_request_public(
    client, env
):
    restrict(env)
    client.force_login(env["user"])
    result = client.get("/api/projects/").json()
    assert [item["id"] for item in result["items"]] == [env["project"].id]
    assert result["defaultProjectId"] == env["project"].id
    rows = client.get("/api/catalog/resources/").json()["items"]
    assert [item["id"] for item in rows] == [env["private"].id]
    for kwargs in ({"HTTP_X_PROJECT_ID": "1"}, {"QUERY_STRING": "projectTagId=1"}):
        assert client.get("/api/catalog/resources/", **kwargs).status_code == 404
        assert (
            client.get(
                f"/api/catalog/resources/{env['public'].id}/profile/", **kwargs
            ).status_code
            == 404
        )
    assert (
        client.get(
            f"/api/catalog/resources/{env['public'].id}/profile/",
            HTTP_X_PROJECT_ID=str(env["project"].id),
        ).status_code
        == 404
    )


def test_membership_in_public_does_not_override_explicit_denial(client, env):
    restrict(env)
    ProjectMembership.objects.create(user=env["user"], project_id=1)
    assert not can_access_project(env["user"], 1)
    assert default_project_id(env["user"]) == env["project"].id
    client.force_login(env["user"])
    assert (
        client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID="1").status_code == 404
    )


def test_only_superadmin_changes_policy_and_omission_preserves_it(client, env):
    route = f"/api/projects/assignments/{env['user'].id}/"
    body = {"projectIds": [env["project"].id], "allowPublicProject": False}
    client.force_login(env["user"])
    assert client.post(route, body, content_type="application/json").status_code == 403
    client.force_login(env["admin"])
    response = client.post(route, body, content_type="application/json")
    assert (
        response.status_code == 200 and response.json()["allowPublicProject"] is False
    )
    result = client.post(
        route, {"projectIds": [env["project"].id]}, content_type="application/json"
    )
    assert result.json()["allowPublicProject"] is False
    assert client.get(route).json()["allowPublicProject"] is False
    body["allowPublicProject"] = True
    assert (
        client.post(route, body, content_type="application/json").json()[
            "allowPublicProject"
        ]
        is True
    )
    assert can_access_project(env["user"], 1)


@pytest.mark.parametrize(
    "body",
    [
        {"projectIds": [], "allowPublicProject": False},
        {"projectIds": [], "allowPublicProject": "false"},
        {"projectIds": [999999], "allowPublicProject": False},
    ],
)
def test_invalid_policy_is_atomic(client, env, body):
    client.force_login(env["admin"])
    response = client.post(
        f"/api/projects/assignments/{env['user'].id}/",
        body,
        content_type="application/json",
    )
    assert response.status_code == 400
    assert can_access_project(env["user"], 1)
    assert ProjectMembership.objects.filter(
        user=env["user"], project=env["project"]
    ).exists()


def test_superadmin_retains_all_projects_and_cannot_be_restricted(client, env):
    client.force_login(env["admin"])
    response = client.post(
        f"/api/projects/assignments/{env['admin'].id}/",
        {"projectIds": [env["project"].id], "allowPublicProject": False},
        content_type="application/json",
    )
    assert response.status_code == 400
    UserProfile.objects.get_or_create(
        user=env["admin"], defaults={"allow_public_project": False}
    )
    assert can_access_project(env["admin"], 1)
    assert (
        client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID="1").status_code == 200
    )


def test_auth_and_editorial_content_remain_accessible(client, env):
    restrict(env)
    article = Article.objects.create(
        kind="news", title="平台公开动态", category="动态", status="published"
    )
    client.force_login(env["user"])
    assert client.get("/api/auth/me/").status_code == 200
    assert client.get("/api/auth/csrf/").status_code == 200
    assert client.get("/api/projects/", HTTP_X_PROJECT_ID="1").status_code == 200
    assert (
        client.get(
            f"/api/content/articles/{article.id}/", HTTP_X_PROJECT_ID="1"
        ).status_code
        == 200
    )


def test_worker_and_compute_authorization_observe_live_policy_without_user_refresh(env):
    user = env["user"]
    with project_scope(ProjectScope((1,), 1, user.id)):
        require_live_membership()
        require_actor(user, 1)
        restrict(env)
        with pytest.raises(PermissionDenied, match="项目访问权限"):
            require_live_membership()
        with pytest.raises(ComputeError, match="项目访问权限"):
            require_actor(user, 1)
    with project_scope(ProjectScope((env["project"].id,), env["project"].id, user.id)):
        require_live_membership()
        require_actor(user, env["project"].id)


def test_structured_and_document_knowledge_do_not_reinclude_public(env):
    entries, docs = [], []
    for pid in (1, env["project"].id):
        entry = KnowledgeEntry.objects.create(
            project_tag_id=pid,
            title=f"知识{pid}",
            category="地质",
            subject="地层",
            predicate="属于",
            object="时代",
            statement="依据",
            status="published",
        )
        library = KnowledgeLibrary.objects.create(
            project_tag_id=pid, scope_key=f"policy:{pid}"
        )
        doc = KnowledgeDocument.objects.create(
            project_tag_id=pid,
            library=library,
            owner=env["user"],
            title=f"文献{pid}",
            filename="source.md",
            sha256=str(pid) * 64,
            original_path="source.md",
            status="completed",
        )
        entries.append(entry.id)
        docs.append(doc.id)
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["user"].id)
    ):
        assert set(visible_entries(env["user"]).values_list("id", flat=True)) == set(
            entries
        )
        assert set(visible_documents(env["user"]).values_list("id", flat=True)) == set(
            docs
        )
        restrict(env)
        assert list(visible_entries(env["user"]).values_list("id", flat=True)) == [
            entries[1]
        ]
        assert list(visible_documents(env["user"]).values_list("id", flat=True)) == [
            docs[1]
        ]


def test_public_chat_history_is_preserved_but_not_a_cross_project_bypass(client, env):
    conversation = Conversation.objects.create(
        owner=env["user"], mode="chat", title="以前的公开对话"
    )
    restrict(env)
    client.force_login(env["user"])
    for pid in (1, env["project"].id):
        response = client.get(
            f"/api/agent/conversations/{conversation.id}/", HTTP_X_PROJECT_ID=str(pid)
        )
        assert response.status_code == 404
    assert Conversation._base_manager.filter(
        pk=conversation.id, title="以前的公开对话"
    ).exists()


def test_shares_and_notifications_cannot_restore_forbidden_public_access(client, env):
    scene = WorkspaceScene.objects.create(
        owner=env["other"], name="原有公开工程", snapshot={}
    )
    invitation = ShareInvitation.objects.create(
        project_tag_id=1,
        sender=env["other"],
        recipient=env["user"],
        kind="workspace",
        object_id=scene.id,
        object_name=scene.name,
        status="accepted",
        request_key="public-policy",
    )
    with actor_scope(env["other"], 1):
        validate_share("workspace", scene.id, env["other"], env["user"], 1)
    restrict(env)
    assert not personal_query(env["user"]).filter(pk=invitation.id).exists()
    with (
        actor_scope(env["other"], 1),
        pytest.raises(ComputeError, match="项目访问权限"),
    ):
        validate_share("workspace", scene.id, env["other"], env["user"], 1)
    client.force_login(env["user"])
    assert client.get("/api/sharing/invitations/").json()["items"] == []
    assert (
        client.get(f"/api/sharing/invitations/{invitation.id}/open/").status_code == 404
    )
    assert (
        client.get(
            f"/api/catalog/workspaces/{scene.id}/", HTTP_X_PROJECT_ID="1"
        ).status_code
        == 404
    )
