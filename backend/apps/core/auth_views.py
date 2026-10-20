import json

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.audit.events import (
    AUTH_GUEST_LOGIN_SUCCESS,
    AUTH_LOGIN_FAILED,
    AUTH_LOGIN_SUCCESS,
    AUTH_REGISTER_LOGIN_SUCCESS,
)
from apps.audit.service import log_operation
from apps.core.api import api_login_required
from apps.core.browser_sessions import prepare_browser_session
from apps.core.emails import AccountEmailError, validate_account_email
from apps.core.initialization import (
    ensure_default_user_group,
    ensure_guest_user,
    ensure_superadmin_defaults,
    is_superadmin_user,
)
from apps.core.passwords import password_validation_errors
from apps.core.localization import localized
from apps.core.models import RoleApplication, UserProfile
from apps.core.permissions import (
    can_access_admin,
    disabled_feature_permissions,
    direct_feature_permissions,
    effective_feature_permissions,
    feature_permission_queryset,
    has_feature_perm,
)
from apps.core.principal_visibility import visible_group_ids_for
from apps.core.role_applications import serialize_role_application
from apps.core.views import registration_allowed


@require_GET
@ensure_csrf_cookie
def csrf_cookie(request):
    return JsonResponse({"detail": "csrf cookie set"})


@require_POST
def login_view(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeError):
        return JsonResponse(
            {
                "detail": localized(
                    "请求体不是有效 JSON", "The request body is not valid JSON"
                )
            },
            status=400,
        )

    if not isinstance(payload, dict):
        return JsonResponse(
            {
                "detail": localized(
                    "请求体必须是 JSON 对象", "The request body must be a JSON object"
                )
            },
            status=400,
        )
    for field in (
        "username",
        "password",
        "passwordConfirm",
        "accountPurpose",
        "displayName",
        "department",
        "applicationReason",
    ):
        if field in payload and not isinstance(payload[field], str):
            return JsonResponse(
                {"detail": localized(f"{field} 必须为文本", f"{field} must be text")},
                status=400,
            )
    if "remember" in payload and type(payload["remember"]) is not bool:
        return JsonResponse(
            {
                "detail": localized(
                    "remember 必须为布尔值", "remember must be a boolean"
                )
            },
            status=400,
        )

    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        log_operation(
            None,
            "认证授权",
            "用户登录",
            "failed",
            f"登录失败：{username}",
            request,
            event_code=AUTH_LOGIN_FAILED,
        )
        return JsonResponse(
            {"detail": localized("账号或密码错误", "Incorrect account or password")},
            status=400,
        )

    login(request, user)
    prepare_browser_session(request)
    log_operation(
        user,
        "认证授权",
        "用户登录",
        "success",
        "登录成功",
        request,
        event_code=AUTH_LOGIN_SUCCESS,
    )
    return JsonResponse({"user": serialize_user(user)})


@require_POST
def guest_login_view(request):
    ensure_superadmin_defaults(create_account=False, attach_existing_superusers=False)
    user = ensure_guest_user()
    login(request, user)
    prepare_browser_session(request)
    log_operation(
        user,
        "认证授权",
        "游客登录",
        "success",
        "游客登录成功",
        request,
        event_code=AUTH_GUEST_LOGIN_SUCCESS,
    )
    return JsonResponse({"user": serialize_user(user)})


@require_POST
def register_view(request):
    if not registration_allowed():
        return JsonResponse(
            {
                "detail": localized(
                    "当前系统未开放自助注册",
                    "Self-registration is currently disabled",
                )
            },
            status=403,
        )

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeError):
        return JsonResponse(
            {
                "detail": localized(
                    "请求体不是有效 JSON", "The request body is not valid JSON"
                )
            },
            status=400,
        )

    if not isinstance(payload, dict):
        return JsonResponse(
            {
                "detail": localized(
                    "请求体必须是 JSON 对象", "The request body must be a JSON object"
                )
            },
            status=400,
        )
    for field in (
        "username",
        "password",
        "passwordConfirm",
        "accountPurpose",
        "displayName",
        "department",
        "applicationReason",
    ):
        if field in payload and not isinstance(payload[field], str):
            return JsonResponse(
                {"detail": localized(f"{field} 必须为文本", f"{field} must be text")},
                status=400,
            )
    if "remember" in payload and type(payload["remember"]) is not bool:
        return JsonResponse(
            {
                "detail": localized(
                    "remember 必须为布尔值", "remember must be a boolean"
                )
            },
            status=400,
        )

    username = str(payload.get("username", "")).strip()
    account_purpose = str(payload.get("accountPurpose", "")).strip()
    display_name = str(payload.get("displayName", "")).strip()
    department = str(payload.get("department", "")).strip()
    application_reason = str(payload.get("applicationReason", "")).strip()
    password = str(payload.get("password", ""))
    password_confirm = str(payload.get("passwordConfirm", ""))
    if not username:
        return JsonResponse(
            {"detail": localized("请输入账号", "Enter your account")}, status=400
        )
    if account_purpose not in {"standard", "research"}:
        return JsonResponse(
            {
                "detail": localized(
                    "accountPurpose 必须是 standard 或 research",
                    "accountPurpose must be standard or research",
                )
            },
            status=400,
        )
    try:
        email = validate_account_email(payload.get("email"))
    except AccountEmailError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    if account_purpose == "research":
        if not display_name:
            return JsonResponse(
                {
                    "detail": localized(
                        "申请科研用户时请输入姓名",
                        "Enter your name when applying for research access",
                    )
                },
                status=400,
            )
        if len(display_name) > 150:
            return JsonResponse(
                {
                    "detail": localized(
                        "姓名不能超过 150 个字符",
                        "The name cannot exceed 150 characters",
                    )
                },
                status=400,
            )
        if not department:
            return JsonResponse(
                {
                    "detail": localized(
                        "申请科研用户时请输入单位或部门",
                        "Enter an organization or department when applying for research access",
                    )
                },
                status=400,
            )
        if len(department) > 120:
            return JsonResponse(
                {
                    "detail": localized(
                        "单位或部门不能超过 120 个字符",
                        "The organization or department cannot exceed 120 characters",
                    )
                },
                status=400,
            )
        if not application_reason:
            return JsonResponse(
                {
                    "detail": localized(
                        "申请科研用户时请输入申请说明",
                        "Enter an application statement for research access",
                    )
                },
                status=400,
            )
        if len(application_reason) > 500:
            return JsonResponse(
                {
                    "detail": localized(
                        "申请说明不能超过 500 个字符",
                        "The application statement cannot exceed 500 characters",
                    )
                },
                status=400,
            )
    if password != password_confirm:
        return JsonResponse(
            {"detail": localized("两次输入的密码不一致", "The passwords do not match")},
            status=400,
        )
    password_errors = password_validation_errors(password)
    if password_errors:
        return JsonResponse({"detail": "；".join(password_errors)}, status=400)

    ensure_superadmin_defaults(attach_existing_superusers=False)
    default_user_group = ensure_default_user_group()
    User = get_user_model()
    if User.objects.filter(username=username).exists():
        return JsonResponse(
            {"detail": localized("账号已存在", "The account already exists")},
            status=400,
        )
    user = User(username=username, email=email, first_name=display_name)
    role_application = None
    try:
        with transaction.atomic():
            user.set_password(password)
            user.save()
            user.groups.add(default_user_group)
            UserProfile.objects.create(
                user=user,
                department=department,
                normalized_email=email,
            )
            if account_purpose == "research":
                role_application = RoleApplication.objects.create(
                    user=user,
                    requested_role=RoleApplication.RequestedRole.RESEARCH,
                    reason=application_reason,
                )
    except IntegrityError:
        if User.objects.filter(email__iexact=email).exists():
            return JsonResponse(
                {
                    "detail": localized(
                        "邮箱已被使用", "The email address is already in use"
                    )
                },
                status=400,
            )
        return JsonResponse(
            {"detail": localized("账号已存在", "The account already exists")},
            status=400,
        )

    login(request, user)
    prepare_browser_session(request)
    message = (
        localized(
            "用户注册成功，科研用户权限申请已提交",
            "Registration succeeded and the research-access application was submitted",
        )
        if role_application
        else localized(
            "用户注册成功，已分配普通用户角色",
            "Registration succeeded with standard-user access",
        )
    )
    log_operation(
        user,
        "认证授权",
        "用户注册",
        "success",
        message,
        request,
        event_code=AUTH_REGISTER_LOGIN_SUCCESS,
    )
    return JsonResponse(
        {
            "user": serialize_user(user),
            "detail": message,
            "roleApplication": (
                serialize_role_application(role_application, include_user=False)
                if role_application
                else None
            ),
        }
    )


@require_POST
@api_login_required
def logout_view(request):
    user = request.user
    logout(request)
    log_operation(user, "认证授权", "用户退出", "success", "退出登录", request)
    return JsonResponse({"detail": localized("已退出", "Signed out")})


@require_GET
def me_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False}, status=401)
    return JsonResponse({"authenticated": True, "user": serialize_user(request.user)})


def serialize_user(user):
    groups = list(user.groups.values_list("name", flat=True))
    group_ids = list(user.groups.values_list("id", flat=True))
    profile = _profile_values(user)
    can_create_data = has_feature_perm(user, "catalog.add_dataresource")
    can_view_data = has_feature_perm(user, "catalog.view_dataresource")
    can_change_data = has_feature_perm(user, "catalog.change_dataresource")
    can_delete_data = has_feature_perm(user, "catalog.delete_dataresource")
    can_create_workspace = has_feature_perm(user, "catalog.add_workspacescene")
    can_view_workspace = has_feature_perm(user, "catalog.view_workspacescene")
    can_change_workspace = has_feature_perm(user, "catalog.change_workspacescene")
    can_delete_workspace = has_feature_perm(user, "catalog.delete_workspacescene")
    can_create_map_composition = has_feature_perm(user, "catalog.add_mapcomposition")
    can_view_map_composition = has_feature_perm(user, "catalog.view_mapcomposition")
    can_change_map_composition = has_feature_perm(user, "catalog.change_mapcomposition")
    can_delete_map_composition = has_feature_perm(user, "catalog.delete_mapcomposition")
    permissions = {
        "canAccessAdmin": can_access_admin(user),
        "canManageFeaturePermissions": has_feature_perm(
            user, "core.manage_feature_permissions"
        ),
        "canCreateUser": has_feature_perm(user, "core.create_user"),
        "canViewOperationLogs": has_feature_perm(user, "core.view_operation_logs"),
        "canViewAllOperationLogs": has_feature_perm(
            user, "core.view_all_operation_logs"
        ),
        "canViewOwnOperationLogs": has_feature_perm(
            user, "core.view_own_operation_logs"
        ),
        "canViewGroupOperationLogs": has_feature_perm(
            user, "core.view_group_operation_logs"
        ),
        "canViewSystemLogs": has_feature_perm(user, "core.view_system_logs"),
        "canManageSystemSettings": has_feature_perm(
            user, "core.manage_system_settings"
        ),
        "canManageDataBackup": has_feature_perm(user, "core.manage_data_backup")
        and is_superadmin_user(user),
        "canManageAuth": has_feature_perm(user, "core.manage_auth"),
        "canViewDashboardResourceCard": has_feature_perm(
            user, "core.view_dashboard_resource_card"
        ),
        "canViewDashboardLayerCard": has_feature_perm(
            user, "core.view_dashboard_layer_card"
        ),
        "canViewDashboardRasterCard": has_feature_perm(
            user, "core.view_dashboard_raster_card"
        ),
        "canViewDashboardUserCard": has_feature_perm(
            user, "core.view_dashboard_user_card"
        ),
        "canViewDashboardActiveUsersCard": has_feature_perm(
            user, "core.view_dashboard_active_users_card"
        ),
        "canViewDashboardSystemCard": has_feature_perm(
            user, "core.view_dashboard_system_card"
        ),
        "canViewDataOverview": has_feature_perm(user, "core.view_data_overview"),
        "canBrowseData": has_feature_perm(user, "core.browse_data"),
        "canQueryData": has_feature_perm(user, "core.query_data"),
        "canUploadData": can_create_data,
        "canViewDataResources": can_view_data,
        "canCreateDataResources": can_create_data,
        "canChangeDataResources": can_change_data,
        "canDeleteDataResources": can_delete_data,
        "canLoadVectorLayer": has_feature_perm(user, "core.load_vector_layer"),
        "canLoadRasterLayer": has_feature_perm(user, "core.load_raster_layer"),
        "canUseCustomSymbolization": has_feature_perm(
            user, "core.custom_symbolization"
        ),
        "canUseAiInterpretation": has_feature_perm(user, "core.ai_interpretation"),
        "canExportData": has_feature_perm(user, "catalog.export_dataresource"),
        "canViewWorkspaces": can_view_workspace,
        "canCreateWorkspaces": can_create_workspace,
        "canChangeWorkspaces": can_change_workspace,
        "canDeleteWorkspaces": can_delete_workspace,
        "canViewMapCompositions": can_view_map_composition,
        "canCreateMapCompositions": can_create_map_composition,
        "canChangeMapCompositions": can_change_map_composition,
        "canDeleteMapCompositions": can_delete_map_composition,
        "canExportMapCompositions": has_feature_perm(
            user, "catalog.export_mapcomposition"
        ),
        "canPublishMapCompositions": has_feature_perm(
            user, "catalog.publish_mapcomposition"
        ),
        "canRestoreMapCompositions": has_feature_perm(
            user, "catalog.restore_mapcomposition"
        ),
        "canViewResultArtifacts": has_feature_perm(user, "catalog.view_resultartifact"),
        "canImportResultArtifacts": has_feature_perm(
            user, "catalog.add_resultartifact"
        ),
        "canDownloadResultArtifacts": has_feature_perm(
            user, "catalog.download_resultartifact"
        ),
        "canPublishResultArtifacts": has_feature_perm(
            user, "catalog.publish_resultartifact"
        ),
        "canDeleteResultArtifacts": has_feature_perm(
            user, "catalog.delete_resultartifact"
        ),
        "canManageRasterData": has_feature_perm(user, "raster.manage_raster_dataset")
        or can_change_data,
    }
    return {
        "id": user.id,
        "username": user.get_username(),
        "displayName": user.get_full_name() or user.get_username(),
        "email": user.email,
        "avatarUrl": profile["avatar_url"],
        "department": profile["department"],
        "isStaff": user.is_staff,
        "isSuperuser": user.is_superuser,
        "roles": groups,
        "groupIds": group_ids,
        "isActive": user.is_active,
        "groupPermissions": sorted(group_feature_permissions(user)),
        "directPermissions": sorted(direct_feature_permissions(user)),
        "disabledPermissions": sorted(disabled_feature_permissions(user)),
        "effectivePermissions": sorted(effective_feature_permissions(user)),
        "operationLogGroupIds": visible_group_ids_for(
            profile["operation_log_group_ids"], user
        ),
        "permissions": permissions,
    }


def _profile_values(user):
    try:
        profile = user.profile
    except ObjectDoesNotExist:
        return {"avatar_url": "", "department": "", "operation_log_group_ids": []}
    avatar_url = profile.avatar_url
    if profile.avatar_data:
        avatar_url = f"/api/users/{user.id}/avatar/"
    return {
        "avatar_url": avatar_url,
        "department": profile.department,
        "operation_log_group_ids": profile.operation_log_group_ids,
    }


def group_feature_permissions(user) -> set[str]:
    if not user.is_authenticated:
        return set()
    feature_ids = set(feature_permission_queryset().values_list("id", flat=True))
    return {
        f"{permission.content_type.app_label}.{permission.codename}"
        for group in user.groups.prefetch_related("permissions__content_type").all()
        for permission in group.permissions.all()
        if permission.id in feature_ids
    }
