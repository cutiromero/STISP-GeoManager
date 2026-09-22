from __future__ import annotations

from dataclasses import dataclass

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Permission
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse
from apps.core.localization import is_english
from django.db.models import Q


@dataclass(frozen=True)
class FeaturePermissionDef:
    app_label: str
    model_name: str
    codename: str
    name: str
    group: str

    @property
    def perm_name(self) -> str:
        return f"{self.app_label}.{self.codename}"

    @property
    def localized_name(self) -> str:
        return _english_permission_name(self.codename) if is_english() else self.name

    @property
    def localized_group(self) -> str:
        if not is_english():
            return self.group
        return {
            "人员权限": "People and roles",
            "后台权限": "Administration",
            "日志权限": "Logs",
            "概览权限": "Dashboard",
            "数据权限": "Data",
            "成果权限": "Results",
        }.get(self.group, self.group)


_CUSTOM_PERMISSION_ENGLISH = {
    "manage_feature_permissions": "Configure feature permissions",
    "create_user": "Create users",
    "view_operation_logs": "View operation logs",
    "view_system_logs": "View system logs",
    "view_all_operation_logs": "View all users' logs",
    "view_own_operation_logs": "View own logs",
    "view_group_operation_logs": "View logs for specified roles",
    "manage_system_settings": "Change system settings",
    "manage_data_backup": "Manage data backups",
    "manage_auth": "Change authentication and authorization",
    "view_dashboard_resource_card": "View dashboard data-resource card",
    "view_dashboard_layer_card": "View dashboard layer-count card",
    "view_dashboard_raster_card": "View dashboard raster-count card",
    "view_dashboard_user_card": "View dashboard user-count card",
    "view_dashboard_active_users_card": "View dashboard active-user card",
    "view_dashboard_system_card": "View dashboard system information",
    "view_data_overview": "View overall data statistics",
    "browse_data": "Browse data",
    "query_data": "Query data",
    "load_vector_layer": "Load vector layers",
    "load_raster_layer": "Load raster layers",
    "custom_symbolization": "Customize symbolization",
    "ai_interpretation": "Use AI interpretation",
}


def _english_permission_name(codename: str) -> str:
    custom = _CUSTOM_PERMISSION_ENGLISH.get(codename)
    if custom:
        return custom
    action, _, object_name = codename.partition("_")
    action_text = {
        "add": "Create",
        "view": "View",
        "change": "Edit",
        "delete": "Delete",
        "export": "Export",
        "publish": "Publish or unpublish",
        "restore": "Restore",
        "download": "Download",
    }.get(action, action.replace("_", " ").capitalize())
    object_text = {
        "dataresource": "data resources",
        "workspacescene": "workspace projects",
        "mapcomposition": "thematic-map drafts",
        "resultartifact": "result files",
    }.get(object_name, object_name.replace("_", " "))
    if codename == "restore_mapcomposition":
        return "Restore thematic map as a project"
    return f"{action_text} {object_text}".strip()


FEATURE_PERMISSIONS: tuple[FeaturePermissionDef, ...] = (
    FeaturePermissionDef("core", "FeaturePermission", "use_local_model", "本地模型对话", "数据权限"),
    FeaturePermissionDef("core", "FeaturePermission", "use_data_agent", "数据智能体", "数据权限"),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "manage_feature_permissions",
        "配置功能权限",
        "人员权限",
    ),
    FeaturePermissionDef(
        "core", "FeaturePermission", "create_user", "新建用户", "人员权限"
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "view_operation_logs",
        "查看操作日志",
        "后台权限",
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "view_system_logs",
        "查看系统日志",
        "后台权限",
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "view_all_operation_logs",
        "查看所有用户日志",
        "日志权限",
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "view_own_operation_logs",
        "查看自己的日志",
        "日志权限",
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "view_group_operation_logs",
        "查看指定角色日志",
        "日志权限",
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "manage_system_settings",
        "修改系统设置",
        "后台权限",
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "manage_data_backup",
        "管理数据备份",
        "后台权限",
    ),
    FeaturePermissionDef(
        "core", "FeaturePermission", "manage_auth", "修改认证授权", "人员权限"
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "view_dashboard_resource_card",
        "查看概览数据资源卡片",
        "概览权限",
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "view_dashboard_layer_card",
        "查看概览图层数卡片",
        "概览权限",
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "view_dashboard_raster_card",
        "查看概览栅格数量卡片",
        "概览权限",
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "view_dashboard_user_card",
        "查看概览用户数量卡片",
        "概览权限",
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "view_dashboard_active_users_card",
        "查看概览活跃用户卡片",
        "概览权限",
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "view_dashboard_system_card",
        "查看概览系统信息",
        "概览权限",
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "view_data_overview",
        "查看总数据情况",
        "概览权限",
    ),
    FeaturePermissionDef(
        "core", "FeaturePermission", "browse_data", "浏览数据", "数据权限"
    ),
    FeaturePermissionDef(
        "core", "FeaturePermission", "query_data", "查询数据", "数据权限"
    ),
    FeaturePermissionDef(
        "core", "FeaturePermission", "load_vector_layer", "加载矢量图层", "数据权限"
    ),
    FeaturePermissionDef(
        "core", "FeaturePermission", "load_raster_layer", "加载栅格图层", "数据权限"
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "custom_symbolization",
        "自定义符号化",
        "数据权限",
    ),
    FeaturePermissionDef(
        "core",
        "FeaturePermission",
        "ai_interpretation",
        "AI智能解译",
        "数据权限",
    ),
    FeaturePermissionDef(
        "catalog", "DataResource", "export_dataresource", "导出数据资源", "数据权限"
    ),
    FeaturePermissionDef(
        "catalog", "DataResource", "add_dataresource", "新增数据资源", "数据权限"
    ),
    FeaturePermissionDef(
        "catalog", "DataResource", "view_dataresource", "查看存量数据资源", "数据权限"
    ),
    FeaturePermissionDef(
        "catalog", "DataResource", "change_dataresource", "编辑数据资源", "数据权限"
    ),
    FeaturePermissionDef(
        "catalog", "DataResource", "delete_dataresource", "删除数据资源", "数据权限"
    ),
    FeaturePermissionDef(
        "catalog", "WorkspaceScene", "add_workspacescene", "新增工程专题", "数据权限"
    ),
    FeaturePermissionDef(
        "catalog", "WorkspaceScene", "view_workspacescene", "查看工程专题", "数据权限"
    ),
    FeaturePermissionDef(
        "catalog", "WorkspaceScene", "change_workspacescene", "编辑工程专题", "数据权限"
    ),
    FeaturePermissionDef(
        "catalog", "WorkspaceScene", "delete_workspacescene", "删除工程专题", "数据权限"
    ),
    FeaturePermissionDef(
        "catalog", "MapComposition", "add_mapcomposition", "新建专题出图稿", "数据权限"
    ),
    FeaturePermissionDef(
        "catalog", "MapComposition", "view_mapcomposition", "查看专题出图稿", "数据权限"
    ),
    FeaturePermissionDef(
        "catalog",
        "MapComposition",
        "change_mapcomposition",
        "编辑专题出图稿",
        "数据权限",
    ),
    FeaturePermissionDef(
        "catalog",
        "MapComposition",
        "delete_mapcomposition",
        "删除专题出图稿",
        "数据权限",
    ),
    FeaturePermissionDef(
        "catalog",
        "MapComposition",
        "export_mapcomposition",
        "导出专题图成果",
        "数据权限",
    ),
    FeaturePermissionDef(
        "catalog",
        "MapComposition",
        "publish_mapcomposition",
        "发布专题图成果",
        "数据权限",
    ),
    FeaturePermissionDef(
        "catalog",
        "MapComposition",
        "restore_mapcomposition",
        "还原专题图为工程",
        "数据权限",
    ),
    FeaturePermissionDef(
        "catalog", "ResultArtifact", "view_resultartifact", "查看成果文件", "成果权限"
    ),
    FeaturePermissionDef(
        "catalog", "ResultArtifact", "add_resultartifact", "导入成果文件", "成果权限"
    ),
    FeaturePermissionDef(
        "catalog",
        "ResultArtifact",
        "download_resultartifact",
        "下载成果文件",
        "成果权限",
    ),
    FeaturePermissionDef(
        "catalog",
        "ResultArtifact",
        "publish_resultartifact",
        "发布或下架成果文件",
        "成果权限",
    ),
    FeaturePermissionDef(
        "catalog",
        "ResultArtifact",
        "delete_resultartifact",
        "删除成果文件",
        "成果权限",
    ),
    FeaturePermissionDef(
        "raster",
        "RasterDataset",
        "manage_raster_dataset",
        "管理栅格数据集",
        "数据权限",
    ),
)

FEATURE_PERMISSIONS += tuple(
    FeaturePermissionDef('compute', model, code, name, '计算权限')
    for model, code, name in (
        ('AlgorithmResource', 'manage_algorithms', '登记和维护算法'),
        ('AlgorithmResource', 'publish_algorithm', '发布算法版本'),
        ('AlgorithmResource', 'download_algorithm', '下载算法源码包'),
        ('ComputeTask', 'submit_task', '提交计算任务'),
        ('ComputeTask', 'view_own_task', '查看本人计算'),
        ('ComputeTask', 'cancel_own_task', '取消本人计算'),
        ('ComputeTask', 'manage_tasks', '管理项目计算任务'),
    )
)
FEATURE_PERMISSION_NAMES = tuple(item.perm_name for item in FEATURE_PERMISSIONS)
ALWAYS_GRANTED_FEATURE_PERMISSIONS = frozenset({"core.view_own_operation_logs"})
GUEST_DENIED_FEATURE_PERMISSIONS = frozenset(
    {
        "core.view_operation_logs",
        "core.view_all_operation_logs",
        "core.view_own_operation_logs",
        "core.view_group_operation_logs",
    }
)
ADMIN_ACCESS_PERMISSIONS = (
    'compute.manage_algorithms',
    'compute.manage_tasks',
    "core.manage_feature_permissions",
    "core.create_user",
    "core.view_operation_logs",
    "core.view_system_logs",
    "core.view_all_operation_logs",
    "core.view_group_operation_logs",
    "core.manage_system_settings",
    "core.manage_data_backup",
    "core.manage_auth",
    "core.view_dashboard_resource_card",
    "core.view_dashboard_layer_card",
    "core.view_dashboard_raster_card",
    "core.view_dashboard_user_card",
    "core.view_dashboard_active_users_card",
    "core.view_dashboard_system_card",
)


def has_feature_perm(user, perm_name: str) -> bool:
    from apps.projects.context import current_scope, is_superadmin

    scope = current_scope.get()
    if is_superadmin(user):
        return True
    if (
        scope is not None
        and scope.selected == 1
        and scope.public_read
        and perm_name
        in {
            "core.browse_data",
            "core.query_data",
            "core.load_vector_layer",
            "core.load_raster_layer",
            "catalog.view_workspacescene",
            "catalog.view_mapcomposition",
            "catalog.view_resultartifact",
        }
    ):
        return True
    if not user.is_authenticated:
        return False
    if perm_name in _principal_denied_feature_permissions(user):
        return False
    if perm_name in ALWAYS_GRANTED_FEATURE_PERMISSIONS:
        return True
    if user.is_superuser:
        return perm_name not in disabled_feature_permissions(user)
    return user.has_perm(perm_name) and perm_name not in disabled_feature_permissions(
        user
    )


def can_access_admin(user) -> bool:
    """Return whether the user has at least one operations-admin capability."""
    return any(
        has_feature_perm(user, permission) for permission in ADMIN_ACCESS_PERMISSIONS
    )


def granted_feature_permissions(user) -> set[str]:
    if not user.is_authenticated:
        return set()
    if user.is_superuser:
        granted = set(FEATURE_PERMISSION_NAMES)
    else:
        granted = ALWAYS_GRANTED_FEATURE_PERMISSIONS | {
            permission
            for permission in FEATURE_PERMISSION_NAMES
            if user.has_perm(permission)
        }
    return granted - _principal_denied_feature_permissions(user)


def disabled_feature_permissions(user) -> set[str]:
    if not user.is_authenticated:
        return set()
    profile = _user_profile(user)
    if profile is None:
        return set()
    disabled = {
        permission
        for permission in profile.disabled_permissions
        if permission in FEATURE_PERMISSION_NAMES
    } - ALWAYS_GRANTED_FEATURE_PERMISSIONS
    from apps.core.initialization import (
        is_superadmin_user,
        superadmin_group_locked_permissions,
    )

    if is_superadmin_user(user):
        disabled -= superadmin_group_locked_permissions()
    return disabled


def effective_feature_permissions(user) -> set[str]:
    if user.is_superuser:
        effective = set(FEATURE_PERMISSION_NAMES)
    else:
        effective = (
            granted_feature_permissions(user) - disabled_feature_permissions(user)
        ) | ALWAYS_GRANTED_FEATURE_PERMISSIONS
    return effective - _principal_denied_feature_permissions(user)


def direct_feature_permissions(user) -> set[str]:
    if not user.is_authenticated:
        return set()
    feature_ids = set(feature_permission_queryset().values_list("id", flat=True))
    return {
        f"{permission.content_type.app_label}.{permission.codename}"
        for permission in user.user_permissions.filter(id__in=feature_ids)
        .select_related("content_type")
        .all()
    }


def _user_profile(user):
    try:
        return user.profile
    except ObjectDoesNotExist:
        return None


def _principal_denied_feature_permissions(user) -> set[str]:
    from apps.core.initialization import is_guest_user

    if is_guest_user(user):
        return set(GUEST_DENIED_FEATURE_PERMISSIONS)
    return set()


def group_names(user) -> str:
    names = (
        list(user.groups.values_list("name", flat=True))
        if user.is_authenticated
        else []
    )
    if names:
        return (", " if is_english() else "、").join(names)
    return "No assigned role" if is_english() else "未分配角色"


def permission_denied_message(user) -> str:
    roles = group_names(user)
    return (
        f'The current role "{roles}" does not have permission'
        if is_english()
        else f"当前角色“{roles}”无权限"
    )


def feature_denied_response(user) -> JsonResponse:
    return JsonResponse({"detail": permission_denied_message(user)}, status=403)


def feature_permission_queryset():
    query = Q()
    for item in FEATURE_PERMISSIONS:
        query |= Q(
            content_type__app_label=item.app_label,
            content_type__model=item.model_name.lower(),
            codename=item.codename,
        )
    if not query:
        return Permission.objects.none()
    return Permission.objects.select_related("content_type").filter(query)


def ensure_feature_permissions() -> None:
    for item in FEATURE_PERMISSIONS:
        model = apps.get_model(item.app_label, item.model_name)
        content_type = ContentType.objects.get_for_model(model)
        Permission.objects.update_or_create(
            content_type=content_type,
            codename=item.codename,
            defaults={"name": item.name},
        )


def feature_permission_ids_for(group) -> set[int]:
    feature_ids = feature_permission_queryset().values_list("id", flat=True)
    return set(
        group.permissions.filter(id__in=feature_ids).values_list("id", flat=True)
    )
