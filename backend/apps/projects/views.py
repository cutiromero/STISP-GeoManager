import json

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods
from django.core.exceptions import ValidationError

from apps.audit.service import log_operation
from apps.core.models import UserProfile
from .access import available_projects, default_project_id, public_project_allowed
from .context import is_superadmin
from .models import Project, ProjectMembership


def can_assign(user):
    return is_superadmin(user)


def serialize(project):
    return {
        "id": project.id,
        "name": project.name,
        "code": project.code,
        "description": project.description,
        "isDefault": project.is_default,
        "isActive": project.is_active,
        "sortOrder": project.sort_order,
    }


def payload(request):
    try:
        result = json.loads(request.body)
    except (ValueError, UnicodeError):
        raise ValidationError("请求必须是有效 JSON")
    if not isinstance(result, dict):
        raise ValidationError("请求必须是 JSON 对象")
    return result


@require_http_methods(["GET", "POST"])
def projects(request):
    if request.method == "GET":
        query = available_projects(request.user)
        return JsonResponse(
            {
                "items": [serialize(p) for p in query],
                "canManage": is_superadmin(request.user),
                "canAssign": can_assign(request.user),
                "defaultProjectId": default_project_id(request.user),
                "assignableItems": [serialize(p) for p in Project.objects.all()]
                if can_assign(request.user)
                else [],
            }
        )
    if not is_superadmin(request.user):
        return JsonResponse({"detail": "只有超级管理员可以创建项目标签"}, status=403)
    data = payload(request)
    project = Project(created_by=request.user)
    apply_values(project, data)
    project.full_clean()
    project.save()
    log_operation(
        request.user, "项目标签", "创建标签", "success", project.name, request
    )
    return JsonResponse(serialize(project), status=201)


def apply_values(project, data):
    for key, field in [
        ("name", "name"),
        ("description", "description"),
        ("sortOrder", "sort_order"),
        ("isActive", "is_active"),
    ]:
        if key in data:
            setattr(project, field, data[key])
    if project.pk is None:
        project.code = str(data.get("code", "")).strip()
    if not str(project.name).strip():
        raise ValidationError("项目名称不能为空")
    if project.is_default and project.name != "公开":
        raise ValidationError("内置公开项目名称不可更改")
    if project.is_default and not project.is_active:
        raise ValidationError("公开项目不能停用")


@require_http_methods(["POST"])
def project_detail(request, project_id):
    if not is_superadmin(request.user):
        return JsonResponse({"detail": "只有超级管理员可以维护项目标签"}, status=403)
    project = get_object_or_404(Project, pk=project_id)
    apply_values(project, payload(request))
    project.full_clean()
    project.save()
    log_operation(
        request.user, "项目标签", "修改标签", "success", project.name, request
    )
    return JsonResponse(serialize(project))


@require_http_methods(["GET", "POST"])
def assignments(request, user_id):
    if not can_assign(request.user):
        return JsonResponse({"detail": "无权分配项目标签"}, status=403)
    user = get_object_or_404(get_user_model(), pk=user_id)
    if not is_superadmin(request.user) and is_superadmin(user):
        return JsonResponse({"detail": "只有超管可维护超管账号"}, status=403)
    if request.method == "POST":
        data = payload(request)
        ids = data.get("projectIds")
        if not isinstance(ids, list) or any(type(i) is not int or i < 1 for i in ids):
            raise ValidationError("projectIds 必须为项目 ID 数组")
        ids = set(ids) - {1}
        if Project.objects.filter(id__in=ids, is_active=True).count() != len(ids):
            raise ValidationError("包含无效或停用项目")
        allow_public = data.get("allowPublicProject", public_project_allowed(user))
        if type(allow_public) is not bool:
            raise ValidationError("allowPublicProject 必须为布尔值")
        if not allow_public and is_superadmin(user):
            raise ValidationError("超级管理员始终拥有全部项目权限")
        if not allow_public and not ids:
            raise ValidationError("关闭公开项目访问时，请至少分配一个启用项目")
        with transaction.atomic():
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.allow_public_project = allow_public
            profile.save(update_fields=["allow_public_project", "updated_at"])
            ProjectMembership.objects.filter(user=user).delete()
            ProjectMembership.objects.bulk_create(
                [
                    ProjectMembership(project_id=i, user=user, assigned_by=request.user)
                    for i in ids
                ]
            )
        log_operation(
            request.user,
            "项目标签",
            "分配用户标签",
            "success",
            f"用户 {user_id}: {sorted(ids)}，公开项目访问：{allow_public}",
            request,
        )
    return JsonResponse(
        {
            "userId": user_id,
            "allowPublicProject": public_project_allowed(user),
            "projectIds": list(
                ProjectMembership.objects.filter(user=user).values_list(
                    "project_id", flat=True
                )
            ),
        }
    )
