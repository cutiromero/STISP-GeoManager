from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BuiltinGroupConfig:
    superadmin_name: str
    platform_admin_name: str
    research_user_name: str
    default_user_name: str
    guest_name: str
    superadmin_locked_permissions: tuple[str, ...]
    platform_admin_permissions: tuple[str, ...]
    previous_platform_admin_permissions: tuple[str, ...]
    research_user_permissions: tuple[str, ...]
    previous_research_user_permissions: tuple[str, ...]
    default_user_permissions: tuple[str, ...]
    previous_default_user_permissions: tuple[str, ...]
    legacy_default_user_permissions: tuple[str, ...]
    guest_permissions: tuple[str, ...]
    previous_guest_permissions: tuple[str, ...]


@dataclass(frozen=True)
class BuiltinAccountConfig:
    guest_username: str
    guest_display_name: str
    guest_department: str
    superadmin_username_env: str
    superadmin_password_env: str
    superadmin_email_env: str
    default_superadmin_username: str
    default_superadmin_email: str
    superadmin_display_name: str
    superadmin_department: str
    initial_password_file: str


BUILTIN_GROUPS = BuiltinGroupConfig(
    superadmin_name="超级管理员",
    platform_admin_name="平台管理员",
    research_user_name="科研用户",
    default_user_name="普通用户",
    guest_name="游客",
    superadmin_locked_permissions=(
        "core.manage_auth",
        "core.manage_feature_permissions",
        "core.manage_system_settings",
        "core.manage_data_backup",
    ),
    platform_admin_permissions=(
        "core.use_local_model",
        "core.use_data_agent",
        "compute.manage_algorithms",
        "compute.publish_algorithm",
        "compute.download_algorithm",
        "compute.manage_tasks",
        "compute.submit_task",
        "compute.view_own_task",
        "compute.cancel_own_task",
        "core.create_user",
        "core.manage_auth",
        "core.manage_feature_permissions",
        "core.view_operation_logs",
        "core.view_all_operation_logs",
        "core.view_dashboard_resource_card",
        "core.view_dashboard_layer_card",
        "core.view_dashboard_raster_card",
        "core.view_dashboard_user_card",
        "core.view_dashboard_active_users_card",
        "core.view_data_overview",
        "core.browse_data",
        "core.query_data",
        "core.custom_symbolization",
        "core.ai_interpretation",
        "catalog.add_dataresource",
        "catalog.view_dataresource",
        "catalog.change_dataresource",
        "catalog.delete_dataresource",
        "catalog.export_dataresource",
        "catalog.add_workspacescene",
        "catalog.view_workspacescene",
        "catalog.change_workspacescene",
        "catalog.delete_workspacescene",
        "catalog.add_mapcomposition",
        "catalog.view_mapcomposition",
        "catalog.change_mapcomposition",
        "catalog.delete_mapcomposition",
        "catalog.export_mapcomposition",
        "catalog.publish_mapcomposition",
        "catalog.restore_mapcomposition",
        "catalog.view_resultartifact",
        "catalog.add_resultartifact",
        "catalog.download_resultartifact",
        "catalog.publish_resultartifact",
        "catalog.delete_resultartifact",
        "core.load_vector_layer",
        "core.load_raster_layer",
        "raster.manage_raster_dataset",
    ),
    previous_platform_admin_permissions=(
        "core.create_user",
        "core.manage_auth",
        "core.manage_feature_permissions",
        "core.manage_system_settings",
        "core.view_operation_logs",
        "core.view_system_logs",
        "core.view_all_operation_logs",
        "core.view_dashboard_resource_card",
        "core.view_dashboard_layer_card",
        "core.view_dashboard_raster_card",
        "core.view_dashboard_user_card",
        "core.view_dashboard_active_users_card",
        "core.view_dashboard_system_card",
        "core.view_data_overview",
        "core.browse_data",
        "core.query_data",
        "core.custom_symbolization",
        "core.ai_interpretation",
        "catalog.add_dataresource",
        "catalog.view_dataresource",
        "catalog.change_dataresource",
        "catalog.delete_dataresource",
        "catalog.export_dataresource",
        "catalog.add_workspacescene",
        "catalog.view_workspacescene",
        "catalog.change_workspacescene",
        "catalog.delete_workspacescene",
        "catalog.add_mapcomposition",
        "catalog.view_mapcomposition",
        "catalog.change_mapcomposition",
        "catalog.delete_mapcomposition",
        "catalog.export_mapcomposition",
        "catalog.publish_mapcomposition",
        "core.load_vector_layer",
        "core.load_raster_layer",
        "raster.manage_raster_dataset",
    ),
    research_user_permissions=(
        "core.use_local_model",
        "core.use_data_agent",
        "compute.submit_task",
        "compute.view_own_task",
        "compute.cancel_own_task",
        "core.browse_data",
        "core.query_data",
        "core.load_vector_layer",
        "core.load_raster_layer",
        "core.custom_symbolization",
        "core.ai_interpretation",
        "core.view_data_overview",
        "catalog.add_dataresource",
        "catalog.view_dataresource",
        "catalog.export_dataresource",
        "catalog.add_workspacescene",
        "catalog.view_workspacescene",
        "catalog.change_workspacescene",
        "catalog.delete_workspacescene",
        "catalog.add_mapcomposition",
        "catalog.view_mapcomposition",
        "catalog.change_mapcomposition",
        "catalog.delete_mapcomposition",
        "catalog.export_mapcomposition",
        "catalog.publish_mapcomposition",
        "catalog.restore_mapcomposition",
        "catalog.view_resultartifact",
        "catalog.add_resultartifact",
        "catalog.download_resultartifact",
        "catalog.publish_resultartifact",
        "catalog.delete_resultartifact",
    ),
    previous_research_user_permissions=(
        "core.browse_data",
        "core.query_data",
        "core.load_vector_layer",
        "core.load_raster_layer",
        "core.custom_symbolization",
        "core.ai_interpretation",
        "core.view_data_overview",
        "catalog.add_dataresource",
        "catalog.view_dataresource",
        "catalog.export_dataresource",
        "catalog.add_workspacescene",
        "catalog.view_workspacescene",
        "catalog.change_workspacescene",
        "catalog.add_mapcomposition",
        "catalog.view_mapcomposition",
        "catalog.change_mapcomposition",
        "catalog.delete_mapcomposition",
        "catalog.export_mapcomposition",
        "catalog.publish_mapcomposition",
    ),
    default_user_permissions=(
        "core.use_local_model",
        "core.browse_data",
        "core.query_data",
        "core.load_vector_layer",
        "core.load_raster_layer",
        "catalog.view_workspacescene",
        "catalog.view_mapcomposition",
        "catalog.view_resultartifact",
    ),
    previous_default_user_permissions=(
        "core.browse_data",
        "core.query_data",
        "core.load_vector_layer",
        "core.load_raster_layer",
        "catalog.add_dataresource",
        "catalog.add_workspacescene",
        "catalog.view_workspacescene",
        "catalog.change_workspacescene",
        "catalog.add_mapcomposition",
        "catalog.view_mapcomposition",
        "catalog.change_mapcomposition",
        "catalog.delete_mapcomposition",
        "catalog.export_mapcomposition",
        "catalog.publish_mapcomposition",
    ),
    legacy_default_user_permissions=(
        "core.browse_data",
        "core.query_data",
        "core.custom_symbolization",
        "core.ai_interpretation",
        "catalog.export_dataresource",
        "catalog.add_dataresource",
        "catalog.view_dataresource",
        "catalog.change_dataresource",
        "catalog.delete_dataresource",
        "catalog.add_workspacescene",
        "catalog.view_workspacescene",
        "catalog.change_workspacescene",
        "catalog.delete_workspacescene",
        "catalog.add_mapcomposition",
        "catalog.view_mapcomposition",
        "catalog.change_mapcomposition",
        "catalog.delete_mapcomposition",
        "catalog.export_mapcomposition",
        "catalog.publish_mapcomposition",
        "core.load_vector_layer",
        "core.load_raster_layer",
        "raster.manage_raster_dataset",
    ),
    guest_permissions=(
        "core.browse_data",
        "core.query_data",
        "core.load_vector_layer",
        "core.load_raster_layer",
        "catalog.view_workspacescene",
        "catalog.view_mapcomposition",
        "catalog.view_resultartifact",
    ),
    previous_guest_permissions=(),
)

BUILTIN_ACCOUNTS = BuiltinAccountConfig(
    guest_username="guest",
    guest_display_name="游客",
    guest_department="公开访问",
    superadmin_username_env="HUYANG_SUPERADMIN_USERNAME",
    superadmin_password_env="HUYANG_SUPERADMIN_PASSWORD",
    superadmin_email_env="HUYANG_SUPERADMIN_EMAIL",
    default_superadmin_username="admin",
    default_superadmin_email="admin@example.local",
    superadmin_display_name="超级管理员",
    superadmin_department="系统管理",
    initial_password_file="initial_superadmin_password.txt",
)
