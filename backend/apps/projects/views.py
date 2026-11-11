import json

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods
from django.core.exceptions import ValidationError

from apps.audit.service import log_operation
from .access import available_projects, default_project_id, public_project_allowed
from .assignments import set_project_assignments
from .context import is_superadmin
from .models import Project, ProjectMembership
from .models import ProjectFeature
from .features import UNSET, feature_state, serialize_feature, set_feature


def can_assign(user):
    return is_superadmin(user)


def serialize(project, features=None):
    return {
        "id": project.id,
        "name": project.name,
        "code": project.code,
        "description": project.description,
        "isDefault": project.is_default,
        "isActive": project.is_active,
        "sortOrder": project.sort_order,
        **feature_state(
            project,
            list(ProjectFeature.objects.all()) if features is None else features,
        ),
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
        query = available_projects(request.user).prefetch_related("feature_settings")
        features = list(ProjectFeature.objects.all())
        return JsonResponse(
            {
                "items": [serialize(p, features) for p in query],
                "canManage": is_superadmin(request.user),
                "canAssign": can_assign(request.user),
                "defaultProjectId": default_project_id(request.user),
                "featureCatalog": [serialize_feature(f) for f in features]
                if is_superadmin(request.user)
                else [],
                "assignableItems": [
                    serialize(p, features)
                    for p in Project.objects.filter(
                        deleted_at__isnull=True
                    ).prefetch_related("feature_settings")
                ]
                if can_assign(request.user)
                else [],
            }
        )
    if not is_superadmin(request.user):
        return JsonResponse({"detail": "只有超级管理员可以创建项目标签"}, status=403)
    data = payload(request)
    project = Project(created_by=request.user)
    apply_values(project, data)
    if Project.objects.filter(code=project.code, deleted_at__isnull=False).exists():
        return JsonResponse(
            {"detail": "该编码保留用于已删除项目的审计记录，请使用新的编码"}, status=400
        )
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


@require_http_methods(["POST", "DELETE"])
def project_detail(request, project_id):
    if request.method == "DELETE" and not request.user.is_authenticated:
        return JsonResponse({"detail": "请先登录"}, status=401)
    if not is_superadmin(request.user):
        return JsonResponse({"detail": "只有超级管理员可以维护项目标签"}, status=403)
    project = get_object_or_404(Project, pk=project_id, deleted_at__isnull=True)
    if request.method == "DELETE":
        from .deletion import remove

        if len(request.body) > 4096:
            return JsonResponse({"detail": "删除请求过大"}, status=400)

        data = payload(request)
        if set(data) - {"confirmedName", "deleteExclusiveData", "confirmationToken"}:
            return JsonResponse({"detail": "删除参数无效"}, status=400)
        try:
            return JsonResponse(remove(project, request.user, data, request))
        except ValidationError as error:
            return JsonResponse({"detail": "；".join(error.messages)}, status=409)
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
        allow_public = data.get("allowPublicProject", public_project_allowed(user))
        ids = set_project_assignments(
            user, data.get("projectIds"), allow_public, assigned_by=request.user
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


@require_http_methods(["POST"])
def project_feature(request, project_id, feature_key):
    if not is_superadmin(request.user):
        return JsonResponse({"detail": "只有超级管理员可以维护项目功能"}, status=403)
    project = get_object_or_404(Project, pk=project_id, deleted_at__isnull=True)
    feature = get_object_or_404(ProjectFeature, key=feature_key)
    data = payload(request)
    set_feature(
        request.user,
        feature,
        project=project,
        enabled=data.get("enabled", UNSET),
        config=data.get("config", UNSET),
        request=request,
    )
    return JsonResponse(serialize(project))


@require_http_methods(["POST"])
def global_feature(request, feature_key):
    if not is_superadmin(request.user):
        return JsonResponse({"detail": "只有超级管理员可以维护项目功能"}, status=403)
    feature = get_object_or_404(ProjectFeature, key=feature_key)
    data = payload(request)
    row = set_feature(
        request.user,
        feature,
        enabled=data.get("enabled", UNSET),
        config=data.get("config", UNSET),
        request=request,
    )
    return JsonResponse(serialize_feature(row))


@require_http_methods(["GET"])
def project_deletion_preview(request, project_id):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "请先登录"}, status=401)
    if not is_superadmin(request.user):
        return JsonResponse({"detail": "只有超级管理员可以删除项目"}, status=403)
    from .deletion import preview

    project = get_object_or_404(Project, pk=project_id, deleted_at__isnull=True)
    try:
        return JsonResponse(preview(project, request.user))
    except ValidationError as error:
        return JsonResponse({"detail": "；".join(error.messages)}, status=409)
