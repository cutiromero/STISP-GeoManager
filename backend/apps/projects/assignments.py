"""Shared project assignment validation for existing and newly created users."""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.models import UserProfile

from .context import is_superadmin
from .models import Project, ProjectMembership


def set_project_assignments(
    user, project_ids: object, allow_public: object, *, assigned_by
) -> set[int]:
    if not isinstance(project_ids, list) or any(
        type(identity) is not int or identity < 1 for identity in project_ids
    ):
        raise ValidationError("projectIds 必须为项目 ID 数组")
    ids = set(project_ids) - {1}
    if type(allow_public) is not bool:
        raise ValidationError("allowPublicProject 必须为布尔值")
    if not allow_public and is_superadmin(user):
        raise ValidationError("超级管理员始终拥有全部项目权限")
    if not allow_public and not ids:
        raise ValidationError("关闭公开项目访问时，请至少分配一个启用项目")
    with transaction.atomic():
        if Project.objects.filter(id__in=ids, is_active=True).count() != len(ids):
            raise ValidationError("包含无效或停用项目")
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.allow_public_project = allow_public
        profile.save(update_fields=["allow_public_project", "updated_at"])
        ProjectMembership.objects.filter(user=user).delete()
        ProjectMembership.objects.bulk_create(
            [
                ProjectMembership(
                    project_id=identity, user=user, assigned_by=assigned_by
                )
                for identity in ids
            ]
        )
    return ids
