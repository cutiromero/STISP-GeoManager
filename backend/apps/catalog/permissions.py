from django.db.models import Q

from apps.core.initialization import (
    GUEST_GROUP_NAME,
    PLATFORM_ADMIN_GROUP_NAME,
    SUPERADMIN_GROUP_NAME,
)


def user_group_ids(user) -> set[int]:
    if user.is_anonymous:
        return set()
    cached = getattr(user, "_huyang_group_ids", None)
    if cached is None:
        cached = set(user.groups.values_list("id", flat=True))
        setattr(user, "_huyang_group_ids", cached)
    return cached


def effective_access_group_ids(user) -> set[int]:
    """Return the user's roles plus the public guest audience.

    Sharing an object with the guest role marks it as public. Authenticated
    users must retain access to that public content even though their account
    is not a member of the dedicated guest group.
    """
    group_ids = set(user_group_ids(user))
    guest_group_id = getattr(user, "_huyang_guest_group_id", None)
    if guest_group_id is None:
        from django.contrib.auth.models import Group

        guest_group_id = (
            Group.objects.filter(name=GUEST_GROUP_NAME)
            .values_list("id", flat=True)
            .first()
            or 0
        )
        setattr(user, "_huyang_guest_group_id", guest_group_id)
    if guest_group_id:
        group_ids.add(guest_group_id)
    return group_ids


def user_is_superadmin_group_member(user) -> bool:
    if user.is_anonymous:
        return False
    cached = getattr(user, "_huyang_is_superadmin_group_member", None)
    if cached is None:
        cached = user.groups.filter(name=SUPERADMIN_GROUP_NAME).exists()
        setattr(user, "_huyang_is_superadmin_group_member", cached)
    return bool(cached)


def user_is_platform_admin_group_member(user) -> bool:
    if user.is_anonymous:
        return False
    cached = getattr(user, "_huyang_is_platform_admin_group_member", None)
    if cached is None:
        cached = user.groups.filter(name=PLATFORM_ADMIN_GROUP_NAME).exists()
        setattr(user, "_huyang_is_platform_admin_group_member", cached)
    return bool(cached)


def user_has_full_data_access(user) -> bool:
    return bool(
        not user.is_anonymous
        and (
            user.is_superuser
            or user_is_superadmin_group_member(user)
            or user_is_platform_admin_group_member(user)
        )
    )


def user_can_bypass_owner_only(user) -> bool:
    """Only the uploader and super administrators may read owner-only data."""
    return bool(
        not user.is_anonymous
        and (user.is_superuser or user_is_superadmin_group_member(user))
    )


def project_access_filter(user):
    from apps.projects.context import current_scope, is_superadmin
    from apps.projects.models import Project
    from apps.projects.middleware import models_q

    scope = current_scope.get()
    if scope is not None:
        return Q(project_tag_id__in=scope.ids)
    if is_superadmin(user):
        return Q()
    ids = Project.objects.filter(is_active=True).filter(models_q(user)).values("id")
    return Q(project_tag_id__in=ids)


def access_filter(user):
    return project_access_filter(user)


def resource_access_filter(user):
    query = project_access_filter(user)
    if not user.is_authenticated:
        return query & Q(status="active", owner_only=False)
    if user_can_bypass_owner_only(user):
        return query
    owner_visibility = Q(owner_only=False) | Q(maintainer=user)
    if user_has_full_data_access(user):
        return query & owner_visibility
    visible = (Q(status="active") | Q(maintainer=user)) & owner_visibility
    return query & visible


def related_access_filter(user, relation: str):
    if user_can_bypass_owner_only(user):
        return Q()
    relation_prefix = f"{relation}__"
    if not user.is_authenticated:
        return Q(**{relation: None}) | Q(
            **{
                relation_prefix + "status": "active",
                relation_prefix + "owner_only": False,
            }
        )
    visible = Q(**{relation_prefix + "owner_only": False}) | Q(
        **{relation_prefix + "maintainer": user}
    )
    return (
        Q(**{relation: None})
        | (Q(**{relation_prefix + "status": "active"}) & visible)
    )


def filter_accessible(queryset, user):
    query = (
        resource_access_filter(user)
        if _model_has_field(queryset.model, "maintainer")
        else access_filter(user)
    )
    return queryset.filter(query).distinct()


def filter_accessible_layers(queryset, user):
    return queryset.filter(
        access_filter(user) & related_access_filter(user, "data_resource")
    ).distinct()


def user_can_access(obj, user) -> bool:
    if not type(obj).objects.filter(project_access_filter(user), pk=obj.pk).exists():
        return False
    if hasattr(obj, "owner_only") and obj.owner_only and not (
        user_can_bypass_owner_only(user)
        or (
            user.is_authenticated
            and getattr(obj, "maintainer_id", None) == user.id
        )
    ):
        return False
    if user_has_full_data_access(user):
        return True
    if hasattr(obj, "data_resource_id"):
        return bool(getattr(obj, "is_active", True)) and (
            obj.data_resource_id is None or user_can_access(obj.data_resource, user)
        )
    if getattr(obj, "status", "active") != "active":
        return user.is_authenticated and getattr(obj, "maintainer_id", None) == user.id
    return True


def _model_has_field(model, field_name: str) -> bool:
    return any(field.name == field_name for field in model._meta.get_fields())
