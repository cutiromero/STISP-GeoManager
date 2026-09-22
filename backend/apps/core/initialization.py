from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import OperationalError, ProgrammingError, transaction

from apps.core.models import UserProfile
from apps.core.emails import normalize_account_email
from apps.core.passwords import generate_password
from apps.core.permissions import (
    FEATURE_PERMISSION_NAMES,
    ensure_feature_permissions,
    feature_permission_queryset,
)
from apps.core.configuration import BUILTIN_ACCOUNTS, BUILTIN_GROUPS

SUPERADMIN_GROUP_NAME = BUILTIN_GROUPS.superadmin_name
PLATFORM_ADMIN_GROUP_NAME = BUILTIN_GROUPS.platform_admin_name
RESEARCH_USER_GROUP_NAME = BUILTIN_GROUPS.research_user_name
DEFAULT_USER_GROUP_NAME = BUILTIN_GROUPS.default_user_name
GUEST_GROUP_NAME = BUILTIN_GROUPS.guest_name
GUEST_USERNAME = BUILTIN_ACCOUNTS.guest_username
SUPERADMIN_USERNAME_ENV = BUILTIN_ACCOUNTS.superadmin_username_env
SUPERADMIN_PASSWORD_ENV = BUILTIN_ACCOUNTS.superadmin_password_env
SUPERADMIN_EMAIL_ENV = BUILTIN_ACCOUNTS.superadmin_email_env
DEFAULT_SUPERADMIN_USERNAME = BUILTIN_ACCOUNTS.default_superadmin_username
DEFAULT_SUPERADMIN_EMAIL = BUILTIN_ACCOUNTS.default_superadmin_email
INITIAL_PASSWORD_FILE = BUILTIN_ACCOUNTS.initial_password_file
LOCKED_SUPERADMIN_PERMISSIONS = BUILTIN_GROUPS.superadmin_locked_permissions
PLATFORM_ADMIN_GROUP_PERMISSIONS = BUILTIN_GROUPS.platform_admin_permissions
PREVIOUS_PLATFORM_ADMIN_GROUP_PERMISSIONS = (
    BUILTIN_GROUPS.previous_platform_admin_permissions
)
RESEARCH_USER_GROUP_PERMISSIONS = BUILTIN_GROUPS.research_user_permissions
PREVIOUS_RESEARCH_USER_GROUP_PERMISSIONS = (
    BUILTIN_GROUPS.previous_research_user_permissions
)
GUEST_GROUP_PERMISSIONS = BUILTIN_GROUPS.guest_permissions
PREVIOUS_GUEST_GROUP_PERMISSIONS = BUILTIN_GROUPS.previous_guest_permissions
DEFAULT_USER_GROUP_PERMISSIONS = BUILTIN_GROUPS.default_user_permissions
PREVIOUS_DEFAULT_USER_GROUP_PERMISSIONS = (
    BUILTIN_GROUPS.previous_default_user_permissions
)
LEGACY_DEFAULT_USER_GROUP_PERMISSIONS = BUILTIN_GROUPS.legacy_default_user_permissions


def ensure_superadmin_defaults(
    *, create_account: bool = True, attach_existing_superusers: bool = True
) -> tuple[Any | None, Group]:
    with transaction.atomic():
        ensure_feature_permissions()
        ensure_platform_admin_group()
        ensure_research_user_group()
        ensure_default_user_group()
        ensure_guest_group()
        ensure_guest_user()
        group, _ = Group.objects.get_or_create(name=SUPERADMIN_GROUP_NAME)
        _grant_all_feature_permissions(group)
        user = _ensure_initial_superadmin(group) if create_account else None
        if attach_existing_superusers:
            _attach_existing_superusers(group)
        return user, group


def ensure_superadmin_defaults_after_migrate(**kwargs) -> None:
    ensure_superadmin_defaults()


def print_superadmin_credentials_on_startup() -> None:
    if not _server_startup_command():
        return
    try:
        user, _ = ensure_superadmin_defaults()
    except (OperationalError, ProgrammingError):
        return
    username = user.get_username() if user is not None else superadmin_username()
    password = _initial_password()
    print(
        "\n".join(
            [
                f"{SUPERADMIN_GROUP_NAME}账号已就绪：",
                f"用户名: {username}",
                f"密码: {password}",
            ]
        ),
        flush=True,
    )


def is_superadmin_group(group: Group) -> bool:
    return group.name == SUPERADMIN_GROUP_NAME


def is_platform_admin_group(group: Group) -> bool:
    return group.name == PLATFORM_ADMIN_GROUP_NAME


def is_platform_admin_user(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and user.groups.filter(name=PLATFORM_ADMIN_GROUP_NAME).exists()
    )


def is_research_user_group(group: Group) -> bool:
    return group.name == RESEARCH_USER_GROUP_NAME


def is_guest_group(group: Group) -> bool:
    return group.name == GUEST_GROUP_NAME


def is_default_user_group(group: Group) -> bool:
    return group.name == DEFAULT_USER_GROUP_NAME


def is_builtin_group(group: Group) -> bool:
    return group.name in builtin_group_names()


def builtin_group_names() -> set[str]:
    return {
        SUPERADMIN_GROUP_NAME,
        PLATFORM_ADMIN_GROUP_NAME,
        RESEARCH_USER_GROUP_NAME,
        DEFAULT_USER_GROUP_NAME,
        GUEST_GROUP_NAME,
    }


def ensure_platform_admin_group() -> Group:
    group, created = Group.objects.get_or_create(name=PLATFORM_ADMIN_GROUP_NAME)
    if created or _matches_previous_group_permissions(
        group, PREVIOUS_PLATFORM_ADMIN_GROUP_PERMISSIONS
    ):
        _set_group_permissions(group, PLATFORM_ADMIN_GROUP_PERMISSIONS)
    _add_group_permissions(group, ("catalog.restore_mapcomposition",))
    return group


def ensure_research_user_group() -> Group:
    group, created = Group.objects.get_or_create(name=RESEARCH_USER_GROUP_NAME)
    if created or _matches_previous_group_permissions(
        group, PREVIOUS_RESEARCH_USER_GROUP_PERMISSIONS
    ):
        _set_group_permissions(group, RESEARCH_USER_GROUP_PERMISSIONS)
    _add_group_permissions(group, ("catalog.restore_mapcomposition",))
    return group


def ensure_default_user_group() -> Group:
    group, created = Group.objects.get_or_create(name=DEFAULT_USER_GROUP_NAME)
    if created:
        _set_group_permissions(group, DEFAULT_USER_GROUP_PERMISSIONS)
    elif _matches_previous_group_permissions(
        group,
        PREVIOUS_DEFAULT_USER_GROUP_PERMISSIONS,
        LEGACY_DEFAULT_USER_GROUP_PERMISSIONS,
    ):
        _set_group_permissions(group, DEFAULT_USER_GROUP_PERMISSIONS)
    # Viewing published map compositions is part of the built-in ordinary-user
    # contract. Keep this minimum permission even when an older installation's
    # role permissions have drifted away from one of the exact legacy sets.
    _add_group_permissions(group, ("catalog.view_mapcomposition",))
    return group


def ensure_guest_group() -> Group:
    group, created = Group.objects.get_or_create(name=GUEST_GROUP_NAME)
    if created or _matches_previous_group_permissions(
        group, PREVIOUS_GUEST_GROUP_PERMISSIONS
    ):
        _set_group_permissions(group, GUEST_GROUP_PERMISSIONS)
    return group


def ensure_guest_user():
    User = get_user_model()
    guest_group = ensure_guest_group()
    with transaction.atomic():
        user, _ = User.objects.select_for_update().get_or_create(
            username=GUEST_USERNAME,
            defaults={
                "first_name": BUILTIN_ACCOUNTS.guest_display_name,
                "email": "",
                "is_active": True,
                "is_staff": False,
                "is_superuser": False,
            },
        )
        user.first_name = BUILTIN_ACCOUNTS.guest_display_name
        user.last_name = ""
        user.email = ""
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        password_changed = user.has_usable_password()
        if password_changed:
            user.set_unusable_password()
        update_fields = [
            "first_name",
            "last_name",
            "email",
            "is_active",
            "is_staff",
            "is_superuser",
        ]
        if password_changed:
            update_fields.append("password")
        user.save(update_fields=update_fields)
        user.groups.set([guest_group])
        user.user_permissions.clear()
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile_changed = False
        if profile.department != BUILTIN_ACCOUNTS.guest_department:
            profile.department = BUILTIN_ACCOUNTS.guest_department
            profile_changed = True
        if profile.normalized_email is not None:
            profile.normalized_email = None
            profile_changed = True
        if profile_changed:
            profile.save(update_fields=["department", "normalized_email", "updated_at"])
        return user


def is_guest_user(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "username", "") == GUEST_USERNAME
    )


def is_superadmin_user(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and user.groups.filter(name=SUPERADMIN_GROUP_NAME).exists()
    )


def is_initial_superadmin_user(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", True)
        and getattr(user, "username", "") == superadmin_username()
    )


def superadmin_group_locked_permissions() -> set[str]:
    return set(LOCKED_SUPERADMIN_PERMISSIONS)


def protected_group_permissions() -> list[str]:
    return list(FEATURE_PERMISSION_NAMES)


def guest_group_permissions() -> set[str]:
    return set(GUEST_GROUP_PERMISSIONS)


def platform_admin_group_permissions() -> set[str]:
    return set(PLATFORM_ADMIN_GROUP_PERMISSIONS)


def research_user_group_permissions() -> set[str]:
    return set(RESEARCH_USER_GROUP_PERMISSIONS)


def default_user_group_permissions() -> set[str]:
    return set(DEFAULT_USER_GROUP_PERMISSIONS)


def initial_password_path() -> Path:
    return settings.PROJECT_CONFIG.app_path("database", INITIAL_PASSWORD_FILE)


def superadmin_username() -> str:
    return _env_value(SUPERADMIN_USERNAME_ENV, DEFAULT_SUPERADMIN_USERNAME)


def _grant_all_feature_permissions(group: Group) -> None:
    permissions = list(feature_permission_queryset())
    if not permissions:
        return
    group.permissions.add(*permissions)


def _set_group_permissions(group: Group, permission_names: tuple[str, ...]) -> None:
    permissions = feature_permission_queryset()
    feature_ids = set(permissions.values_list("id", flat=True))
    permissions_by_name = {
        f"{permission.content_type.app_label}.{permission.codename}": permission
        for permission in permissions
    }
    selected_ids = [
        permissions_by_name[permission_name].id
        for permission_name in permission_names
        if permission_name in permissions_by_name
    ]
    non_feature_ids = set(
        group.permissions.exclude(id__in=feature_ids).values_list("id", flat=True)
    )
    group.permissions.set([*non_feature_ids, *selected_ids])


def _group_feature_permission_names(group: Group) -> set[str]:
    feature_ids = set(feature_permission_queryset().values_list("id", flat=True))
    return {
        f"{permission.content_type.app_label}.{permission.codename}"
        for permission in group.permissions.select_related("content_type").all()
        if permission.id in feature_ids
    }


def _matches_previous_group_permissions(
    group: Group, *permission_sets: tuple[str, ...]
) -> bool:
    current = _group_feature_permission_names(group)
    for permission_names in permission_sets:
        expected = set(permission_names)
        if current == expected:
            return True
        without_map_compositions = {
            permission for permission in expected if "mapcomposition" not in permission
        }
        if current == without_map_compositions:
            return True
    return False


def _add_group_permissions(group: Group, permission_names: tuple[str, ...]) -> None:
    permissions_by_name = {
        f"{permission.content_type.app_label}.{permission.codename}": permission
        for permission in feature_permission_queryset()
    }
    selected = [
        permissions_by_name[permission_name]
        for permission_name in permission_names
        if permission_name in permissions_by_name
    ]
    if selected:
        group.permissions.add(*selected)


def _ensure_initial_superadmin(group: Group):
    User = get_user_model()

    username = superadmin_username()
    email = _env_value(SUPERADMIN_EMAIL_ENV, DEFAULT_SUPERADMIN_EMAIL)
    password = _initial_password()
    user, created = User.objects.select_for_update().get_or_create(
        username=username,
        defaults={
            "email": email,
            "first_name": BUILTIN_ACCOUNTS.superadmin_display_name,
            "is_active": True,
            "is_staff": False,
            "is_superuser": False,
        },
    )
    if created:
        user.set_password(password)
    user.email = user.email or email
    user.first_name = user.first_name or BUILTIN_ACCOUNTS.superadmin_display_name
    user.is_active = True
    user.is_staff = False
    user.is_superuser = False
    user.save(
        update_fields=[
            "email",
            "first_name",
            "is_active",
            "is_staff",
            "is_superuser",
            "password",
        ]
    )
    user.groups.add(group)
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile_changed = False
    if not profile.department:
        profile.department = BUILTIN_ACCOUNTS.superadmin_department
        profile_changed = True
    normalized_email = normalize_account_email(user.email)
    if (
        normalized_email
        and profile.normalized_email != normalized_email
        and not UserProfile.objects.exclude(user=user)
        .filter(normalized_email=normalized_email)
        .exists()
    ):
        profile.normalized_email = normalized_email
        profile_changed = True
    if profile_changed:
        profile.save(update_fields=["department", "normalized_email", "updated_at"])
    return user


def _attach_existing_superusers(group: Group) -> None:
    User = get_user_model()
    for user in User.objects.select_for_update().filter(is_superuser=True):
        changed = False
        if not user.is_staff:
            user.is_staff = True
            changed = True
        if not user.is_active:
            user.is_active = True
            changed = True
        if changed:
            user.save(update_fields=["is_staff", "is_active"])
        user.groups.add(group)


def _initial_password() -> str:
    env_password = os.environ.get(SUPERADMIN_PASSWORD_ENV, "").strip()
    if env_password:
        return env_password

    path = initial_password_path()
    if path.exists():
        return path.read_text(encoding="utf-8").strip()

    password = generate_password(length=8)
    if not _running_tests():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{password}\n", encoding="utf-8")
        path.chmod(0o600)
    return password


def _env_value(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def _running_tests() -> bool:
    return "test" in sys.argv


def _server_startup_command() -> bool:
    if _running_tests():
        return False
    if len(sys.argv) > 1 and sys.argv[1] == "runserver":
        return os.environ.get("RUN_MAIN") == "true"
    command_text = " ".join([Path(sys.argv[0]).name, *sys.argv[1:]])
    return any(name in command_text for name in ("waitress", "uvicorn", "daphne"))
