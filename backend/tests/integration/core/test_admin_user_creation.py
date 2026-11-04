"""Account creation applies the same live project rules as later assignments."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError

from apps.audit.models import OperationLog
from apps.catalog.models import WorkspaceScene
from apps.core.initialization import (
    GUEST_USERNAME,
    SUPERADMIN_GROUP_NAME,
    superadmin_username,
)
from apps.core.models import UserProfile
from apps.projects.models import Project, ProjectMembership


pytestmark = pytest.mark.django_db


@pytest.fixture
def actors(client):
    users = get_user_model()
    admin = users.objects.create_user("creation-superadmin")
    supergroup, _ = Group.objects.get_or_create(name=SUPERADMIN_GROUP_NAME)
    admin.groups.add(supergroup)
    admin.user_permissions.add(
        *Permission.objects.filter(codename__in=["manage_auth", "create_user"])
    )
    manager = users.objects.create_user("creation-manager")
    manager.user_permissions.add(
        *Permission.objects.filter(codename__in=["manage_auth", "create_user"])
    )
    role = Group.objects.create(name="创建用户测试角色")
    project = Project.objects.create(name="创建用户逻辑推理", code="creation-geology")
    inactive = Project.objects.create(
        name="已停用创建项目", code="creation-inactive", is_active=False
    )
    client.force_login(admin)
    return admin, manager, role, project, inactive


def create(client, actors, **fields):
    return client.post(
        "/api/users/",
        {"username": "created-scope-user", "groupIds": [actors[2].id], **fields},
        content_type="application/json",
    )


@pytest.mark.parametrize("email", [None, "", "   "])
def test_superadmin_can_create_multiple_users_without_email(client, actors, email):
    for index in range(2):
        response = create(client, actors, username=f"no-email-{index}", email=email)
        assert response.status_code == 201, response.content
        user = get_user_model().objects.get(pk=response.json()["id"])
        assert user.email == "" and user.profile.normalized_email is None
        assert user.profile.allow_public_project
        assert not ProjectMembership.objects.filter(user=user).exists()
        generated = response.json()["generatedPassword"]
        assert (
            generated and user.check_password(generated) and user.password != generated
        )
        listed = client.get("/api/users/").json()["items"]
        assert all(
            "generatedPassword" not in item and "password" not in item
            for item in listed
        )


def test_superadmin_creation_without_project_fields_keeps_default_behavior(
    client, actors
):
    response = create(client, actors)
    assert response.status_code == 201
    user = get_user_model().objects.get(pk=response.json()["id"])
    assert user.profile.allow_public_project
    assert user.groups.filter(pk=actors[2].id).exists()


def test_creation_project_scope_is_effective_immediately(client, actors):
    response = create(
        client,
        actors,
        projectIds=[actors[3].id],
        allowPublicProject=False,
        department="地质研究",
    )
    assert response.status_code == 201, response.content
    user = get_user_model().objects.get(pk=response.json()["id"])
    assert not user.profile.allow_public_project
    assert user.profile.department == "地质研究"
    membership = ProjectMembership.objects.get(user=user)
    assert (
        membership.project_id == actors[3].id
        and membership.assigned_by_id == actors[0].id
    )
    client.force_login(user)
    data = client.get("/api/projects/").json()
    assert [item["id"] for item in data["items"]] == [actors[3].id]
    assert data["defaultProjectId"] == actors[3].id


@pytest.mark.parametrize(
    "fields",
    [
        {"projectIds": [], "allowPublicProject": False},
        {"projectIds": [999999]},
        {"projectIds": [True]},
        {"projectIds": ["2"]},
        {"projectIds": "2"},
        {"projectIds": None},
        {"allowPublicProject": "false"},
        {"allowPublicProject": 0},
        {"allowPublicProject": None},
    ],
)
def test_invalid_creation_project_policy_does_not_leave_account(client, actors, fields):
    before = (
        get_user_model().objects.count(),
        UserProfile.objects.count(),
        ProjectMembership.objects.count(),
    )
    response = create(client, actors, **fields)
    assert response.status_code == 400, response.content
    assert not get_user_model().objects.filter(username="created-scope-user").exists()
    assert before == (
        get_user_model().objects.count(),
        UserProfile.objects.count(),
        ProjectMembership.objects.count(),
    )


def test_creation_rejects_inactive_projects(client, actors):
    response = create(client, actors, projectIds=[actors[4].id])
    assert response.status_code == 400
    assert not get_user_model().objects.filter(username="created-scope-user").exists()


def test_creation_normalizes_public_id_and_duplicate_private_assignments(
    client, actors
):
    response = create(
        client,
        actors,
        projectIds=[1, actors[3].id, actors[3].id],
        allowPublicProject=True,
    )
    assert response.status_code == 201, response.content
    user = get_user_model().objects.get(pk=response.json()["id"])
    assert user.profile.allow_public_project
    assert list(
        ProjectMembership.objects.filter(user=user).values_list("project_id", flat=True)
    ) == [actors[3].id]


@pytest.mark.parametrize("fields", [{"projectIds": []}, {"allowPublicProject": True}])
def test_ordinary_manager_cannot_supply_creation_project_policy(client, actors, fields):
    client.force_login(actors[1])
    response = create(client, actors, email="manager-created@example.com", **fields)
    assert response.status_code == 403
    assert not get_user_model().objects.filter(username="created-scope-user").exists()


def test_ordinary_manager_still_requires_email(client, actors):
    client.force_login(actors[1])
    assert create(client, actors).status_code == 400
    response = create(client, actors, email="manager-created@example.com")
    assert response.status_code == 201, response.content


def test_optional_email_still_validates_provided_email_and_uniqueness(client, actors):
    assert create(client, actors, email="invalid").status_code == 400
    assert create(client, actors, email="One@example.com").status_code == 201
    duplicate = create(
        client, actors, username="duplicate-email", email="one@EXAMPLE.COM"
    )
    assert duplicate.status_code == 400
    assert not get_user_model().objects.filter(username="duplicate-email").exists()


def test_assignment_failure_rolls_back_user_roles_and_profile(client, actors):
    before = (
        get_user_model().objects.count(),
        UserProfile.objects.count(),
        ProjectMembership.objects.count(),
    )
    with patch(
        "apps.core.admin_api.set_project_assignments",
        side_effect=ValidationError("项目已停用"),
    ):
        response = create(
            client, actors, projectIds=[actors[3].id], allowPublicProject=False
        )
    assert response.status_code == 400
    assert not get_user_model().objects.filter(username="created-scope-user").exists()
    assert before == (
        get_user_model().objects.count(),
        UserProfile.objects.count(),
        ProjectMembership.objects.count(),
    )


def rename(client, identity, username, **fields):
    return client.post(
        f"/api/users/{identity}/",
        {"username": username, **fields},
        content_type="application/json",
    )


def test_superadmin_renames_existing_account_preserving_identity_password_and_relations(
    client, actors
):
    user = get_user_model().objects.create_user(
        "rename-original", password="old-user-password"
    )
    user.groups.add(actors[2])
    profile = UserProfile.objects.create(user=user, department="原部门")
    membership = ProjectMembership.objects.create(user=user, project=actors[3])
    scene = WorkspaceScene.objects.create(
        project_tag=actors[3], owner=user, name="原工程"
    )
    identity, password_hash = user.pk, user.password
    response = rename(client, identity, "renamed-user")
    assert response.status_code == 200, response.content
    user.refresh_from_db()
    assert (
        user.pk == identity
        and user.username == "renamed-user"
        and user.password == password_hash
    )
    assert user.profile.pk == profile.pk and user.profile.department == "原部门"
    assert user.groups.filter(pk=actors[2].id).exists()
    assert ProjectMembership.objects.get(pk=membership.pk).user_id == identity
    assert WorkspaceScene.objects.get(pk=scene.pk).owner_id == identity
    log = OperationLog.objects.filter(action="修改用户名", target_id=identity).latest(
        "id"
    )
    assert "rename-original" in log.message and "renamed-user" in log.message
    client.logout()
    assert client.login(username="renamed-user", password="old-user-password")
    client.logout()
    assert not client.login(username="rename-original", password="old-user-password")


@pytest.mark.parametrize(
    "username", ["", "   ", "bad name", "bad/name", "a" * 151, 123, None]
)
def test_invalid_rename_does_not_change_username_or_status(client, actors, username):
    target = actors[1]
    response = rename(client, target.id, username, isActive=False)
    assert response.status_code == 400
    target.refresh_from_db()
    assert target.username == "creation-manager" and target.is_active


def test_duplicate_rename_is_rejected_atomically(client, actors):
    response = rename(client, actors[1].id, actors[0].username, isActive=False)
    assert response.status_code == 400
    actors[1].refresh_from_db()
    assert actors[1].username == "creation-manager" and actors[1].is_active


def test_ordinary_manager_cannot_rename_even_when_supplying_unchanged_name(
    client, actors
):
    client.force_login(actors[1])
    assert rename(client, actors[1].id, actors[1].username).status_code == 403
    actors[1].refresh_from_db()
    assert actors[1].username == "creation-manager"


@pytest.mark.parametrize("username", [GUEST_USERNAME, superadmin_username()])
def test_system_account_usernames_are_immutable_and_reserved(client, actors, username):
    target, _ = get_user_model().objects.get_or_create(username=username)
    assert rename(client, target.id, "changed-system-account").status_code == 400
    target.refresh_from_db()
    assert target.username == username
    assert rename(client, actors[1].id, username).status_code == 400


def test_superadmin_can_rename_self_without_invalidating_session(client, actors):
    response = rename(client, actors[0].id, "renamed-superadmin")
    assert response.status_code == 200, response.content
    assert client.get("/api/auth/me/").json()["authenticated"]
    assert (
        client.get("/api/auth/me/").json()["user"]["username"] == "renamed-superadmin"
    )


def test_rename_capabilities_match_backend_protection(client, actors):
    for username in (GUEST_USERNAME, superadmin_username()):
        get_user_model().objects.get_or_create(username=username)
    users = {
        item["username"]: item for item in client.get("/api/users/").json()["items"]
    }
    assert users[actors[1].username]["canRenameUsername"]
    assert users[actors[0].username]["canRenameUsername"]
    assert not users[GUEST_USERNAME]["canRenameUsername"]
    assert not users[superadmin_username()]["canRenameUsername"]
    client.force_login(actors[1])
    assert not any(
        item["canRenameUsername"] for item in client.get("/api/users/").json()["items"]
    )


def test_superadmin_can_rename_and_update_status_together(client, actors):
    response = rename(client, actors[1].id, "renamed-inactive", isActive=False)
    assert response.status_code == 200, response.content
    actors[1].refresh_from_db()
    assert actors[1].username == "renamed-inactive" and not actors[1].is_active
