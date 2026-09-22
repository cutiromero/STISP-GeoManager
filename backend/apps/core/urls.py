from django.urls import path

from apps.core import admin_api, auth_views, views

urlpatterns = [
    path("bootstrap/", views.bootstrap, name="bootstrap"),
    path("login/overview/", views.login_overview, name="login-overview"),
    path("health/", views.health, name="health"),
    path(
        "map/thumbnail-tiles/<int:z>/<int:x>/<int:y>.png",
        views.map_thumbnail_tile,
        name="map-thumbnail-tile",
    ),
    path("auth/csrf/", auth_views.csrf_cookie, name="csrf"),
    path("auth/login/", auth_views.login_view, name="login"),
    path("auth/guest-login/", auth_views.guest_login_view, name="guest-login"),
    path("auth/register/", auth_views.register_view, name="register"),
    path("auth/logout/", auth_views.logout_view, name="logout"),
    path("auth/me/", auth_views.me_view, name="me"),
    path(
        "admin/operation-logs/",
        admin_api.admin_operation_logs,
        name="admin-operation-logs",
    ),
    path(
        "admin/system-logs/",
        admin_api.admin_system_logs,
        name="admin-system-logs",
    ),
    path("admin/dashboard/", admin_api.admin_dashboard, name="admin-dashboard"),
    path(
        "admin/dashboard/server/",
        admin_api.admin_dashboard_server,
        name="admin-dashboard-server",
    ),
    path("admin/profile/", admin_api.admin_profile, name="admin-profile"),
    path(
        "admin/profile/update/",
        admin_api.update_admin_profile,
        name="admin-profile-update",
    ),
    path(
        "admin/profile/permissions/",
        admin_api.update_admin_profile_permissions,
        name="admin-profile-permissions",
    ),
    path(
        "admin/profile/password/",
        admin_api.update_admin_profile_password,
        name="admin-profile-password",
    ),
    path(
        "admin/profile/avatar/",
        admin_api.upload_avatar,
        name="admin-avatar-upload",
    ),
    path(
        "users/<int:user_id>/avatar/",
        admin_api.get_avatar,
        name="user-avatar-get",
    ),
    path("users/", admin_api.user_list, name="user-list"),
    path(
        "admin/role-applications/",
        admin_api.role_application_list,
        name="role-application-list",
    ),
    path(
        "admin/role-applications/<int:application_id>/review/",
        admin_api.role_application_review,
        name="role-application-review",
    ),
    path("users/<int:user_id>/", admin_api.user_detail, name="user-detail"),
    path(
        "users/<int:user_id>/password/reset/",
        admin_api.reset_user_password,
        name="user-password-reset",
    ),
    path(
        "users/<int:user_id>/groups/",
        admin_api.update_user_groups,
        name="user-groups",
    ),
    path(
        "users/<int:user_id>/permissions/",
        admin_api.update_user_permissions,
        name="user-permissions",
    ),
    path("groups/", admin_api.group_list, name="group-list"),
    path(
        "groups/<int:group_id>/",
        admin_api.group_detail,
        name="group-detail",
    ),
    path("admin/settings/", admin_api.admin_settings, name="admin-settings"),
    path(
        "admin/backups/overview/",
        admin_api.admin_backup_overview,
        name="admin-backup-overview",
    ),
    path(
        "admin/backups/settings/",
        admin_api.admin_backup_settings,
        name="admin-backup-settings",
    ),
    path(
        "admin/backups/targets/test/",
        admin_api.admin_backup_target_test,
        name="admin-backup-target-test",
    ),
    path(
        "admin/backups/runs/",
        admin_api.admin_backup_runs,
        name="admin-backup-runs",
    ),
    path(
        "admin/backups/runs/<int:run_id>/",
        admin_api.admin_backup_run_detail,
        name="admin-backup-run-detail",
    ),
    path(
        "admin/backups/runs/<int:run_id>/download/",
        admin_api.admin_backup_run_download,
        name="admin-backup-run-download",
    ),
    path(
        "admin/data/resources/",
        admin_api.admin_data_resources,
        name="admin-data-resources",
    ),
    path(
        "admin/data/resource-groups/",
        admin_api.admin_data_resource_groups,
        name="admin-data-resource-groups",
    ),
    path(
        "admin/data/resource-groups/<int:group_id>/",
        admin_api.admin_data_resource_group_detail,
        name="admin-data-resource-group-detail",
    ),
    path(
        "admin/data/resources/export/",
        admin_api.admin_data_resources_export,
        name="admin-data-resources-export",
    ),
    path(
        "admin/data/resources/<int:resource_id>/",
        admin_api.admin_data_resource_detail,
        name="admin-data-resource-detail",
    ),
]
