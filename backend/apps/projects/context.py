from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectScope:
    ids: tuple[int, ...]
    selected: int | None
    user_id: int | None = None
    superadmin: bool = False
    public_read: bool = False


current_scope = ContextVar("project_scope", default=None)


@contextmanager
def project_scope(scope):
    token = current_scope.set(scope)
    try:
        yield
    finally:
        current_scope.reset(token)


def selected_project_id():
    from django.core.exceptions import ValidationError

    scope = current_scope.get()
    if scope is not None and scope.selected is None:
        raise ValidationError("请先选择一个具体项目标签")
    return scope.selected if scope is not None else 1


def is_superadmin(user):
    from apps.core.initialization import is_superadmin_user

    return bool(
        user.is_authenticated and (user.is_superuser or is_superadmin_user(user))
    )


def require_live_membership():
    """Re-check queued work after membership or account status changes."""
    from django.contrib.auth import get_user_model
    from django.core.exceptions import PermissionDenied
    from .models import Project, ProjectMembership

    scope = current_scope.get()
    if scope is None:
        return
    if scope.user_id is None:
        if scope.selected != 1:
            raise PermissionDenied("项目访问权限已失效")
        return
    user = get_user_model().objects.filter(pk=scope.user_id, is_active=True).first()
    if user is None:
        raise PermissionDenied("任务账号已停用")
    if is_superadmin(user) or scope.selected == 1:
        return
    if (
        not Project.objects.filter(pk=scope.selected, is_active=True).exists()
        or not ProjectMembership.objects.filter(
            user=user, project_id=scope.selected
        ).exists()
    ):
        raise PermissionDenied("项目访问权限已撤回，任务已停止")
