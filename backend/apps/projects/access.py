"""One live project boundary for HTTP requests, workers and shared sources."""

from django.db.models import Q

from .context import is_superadmin
from .models import Project


def public_project_allowed(user) -> bool:
    if not user.is_authenticated:
        return True
    if not user.is_active:
        return False
    if is_superadmin(user):
        return True
    from apps.core.models import UserProfile

    # Read current policy instead of a related-object cache: queued work and
    # accepted shares must observe an administrator's revocation immediately.
    return not UserProfile.objects.filter(
        user_id=user.pk, allow_public_project=False
    ).exists()


def project_access_query(user) -> Q:
    query = Q(is_default=True) if public_project_allowed(user) else Q(pk__in=[])
    if user.is_authenticated and user.is_active:
        query |= Q(memberships__user=user, is_default=False)
    return query


def available_projects(user):
    query = Project.objects.filter(deleted_at__isnull=True)
    if not is_superadmin(user):
        query = (
            query.filter(is_active=True).filter(project_access_query(user)).distinct()
        )
    return query


def default_project_id(user) -> int | None:
    projects = available_projects(user).filter(is_active=True)
    if projects.filter(pk=1).exists():
        return 1
    return projects.values_list("id", flat=True).first()


def can_access_project(user, project_id: int) -> bool:
    return available_projects(user).filter(pk=project_id, is_active=True).exists()
