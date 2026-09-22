from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models import Q, QuerySet

from apps.core.initialization import (
    SUPERADMIN_GROUP_NAME,
    is_superadmin_user,
    superadmin_username,
)


def can_view_superadmin_principals(user) -> bool:
    return bool(getattr(user, "is_authenticated", False) and is_superadmin_user(user))


def visible_groups_for(queryset: QuerySet[Group], viewer) -> QuerySet[Group]:
    if can_view_superadmin_principals(viewer):
        return queryset
    return queryset.exclude(name=SUPERADMIN_GROUP_NAME)


def selectable_access_groups_for(queryset: QuerySet[Group], viewer) -> QuerySet[Group]:
    return queryset.exclude(name=SUPERADMIN_GROUP_NAME)


def visible_users_for(queryset: QuerySet, viewer) -> QuerySet:
    if can_view_superadmin_principals(viewer):
        return queryset
    return queryset.exclude(
        Q(username=superadmin_username())
        | Q(is_superuser=True)
        | Q(groups__name=SUPERADMIN_GROUP_NAME)
    ).distinct()


def visible_operation_logs_for(queryset: QuerySet, viewer) -> QuerySet:
    if can_view_superadmin_principals(viewer):
        return queryset
    return queryset.exclude(
        Q(user__username=superadmin_username())
        | Q(user__is_superuser=True)
        | Q(user__groups__name=SUPERADMIN_GROUP_NAME)
    ).distinct()


def visible_group_ids_for(group_ids: list[int], viewer) -> list[int]:
    if can_view_superadmin_principals(viewer):
        return group_ids
    visible_ids = set(
        visible_groups_for(
            Group.objects.filter(id__in=group_ids).only("id", "name"), viewer
        ).values_list("id", flat=True)
    )
    return [group_id for group_id in group_ids if group_id in visible_ids]


def user_is_visible_to(viewer, target) -> bool:
    User = get_user_model()
    return visible_users_for(User.objects.filter(pk=target.pk), viewer).exists()


def group_is_visible_to(viewer, group: Group) -> bool:
    return visible_groups_for(Group.objects.filter(pk=group.pk), viewer).exists()
