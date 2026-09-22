from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from apps.core.initialization import (
    DEFAULT_USER_GROUP_NAME,
    GUEST_GROUP_NAME,
    PLATFORM_ADMIN_GROUP_NAME,
    PREVIOUS_GUEST_GROUP_PERMISSIONS,
    PREVIOUS_PLATFORM_ADMIN_GROUP_PERMISSIONS,
    PREVIOUS_RESEARCH_USER_GROUP_PERMISSIONS,
    RESEARCH_USER_GROUP_NAME,
    SUPERADMIN_GROUP_NAME,
    default_user_group_permissions,
    ensure_superadmin_defaults,
    guest_group_permissions,
    is_superadmin_user,
    platform_admin_group_permissions,
    protected_group_permissions,
    research_user_group_permissions,
)
from apps.core.models import UserProfile
from apps.core.permissions import (
    FEATURE_PERMISSIONS,
    FEATURE_PERMISSION_NAMES,
    FeaturePermissionDef,
    ensure_feature_permissions,
    feature_denied_response,
    feature_permission_ids_for,
    feature_permission_queryset,
    group_names,
    has_feature_perm,
    permission_denied_message,
)


class FeaturePermissionDefTests(TestCase):
    def test_perm_name_format(self):
        perm = FeaturePermissionDef(
            "core", "FeaturePermission", "query_data", "查询数据", "数据权限"
        )
        self.assertEqual(perm.perm_name, "core.query_data")

    def test_feature_permissions_not_empty(self):
        self.assertGreater(len(FEATURE_PERMISSIONS), 0)

    def test_all_permissions_have_required_fields(self):
        for perm in FEATURE_PERMISSIONS:
            self.assertTrue(perm.app_label)
            self.assertTrue(perm.model_name)
            self.assertTrue(perm.codename)
            self.assertTrue(perm.name)
            self.assertTrue(perm.group)

    def test_feature_permission_names_tuple(self):
        self.assertEqual(len(FEATURE_PERMISSION_NAMES), len(FEATURE_PERMISSIONS))
        for name in FEATURE_PERMISSION_NAMES:
            self.assertIn(".", name)

    def test_create_user_permission_is_registered(self):
        self.assertIn("core.create_user", FEATURE_PERMISSION_NAMES)
        self.assertTrue(
            Permission.objects.filter(
                content_type__app_label="core",
                codename="create_user",
            ).exists()
        )

    def test_ensure_feature_permissions_creates_registered_permissions(self):
        Permission.objects.filter(
            content_type__app_label="core",
            content_type__model="featurepermission",
            codename="view_operation_logs",
        ).delete()

        ensure_feature_permissions()

        self.assertTrue(
            Permission.objects.filter(
                content_type__app_label="core",
                content_type__model="featurepermission",
                codename="view_operation_logs",
            ).exists()
        )


class HasFeaturePermTests(TestCase):
    def test_returns_false_for_anonymous_user(self):
        from django.contrib.auth.models import AnonymousUser

        user = AnonymousUser()
        self.assertFalse(has_feature_perm(user, "core.query_data"))

    def test_returns_true_for_superuser(self):
        user = get_user_model().objects.create_superuser(
            username="super", password="pass12345"
        )
        self.assertTrue(has_feature_perm(user, "core.query_data"))

    def test_returns_true_for_user_with_permission(self):
        user = get_user_model().objects.create_user(
            username="perm-user", password="pass12345"
        )

        perm = Permission.objects.get(
            content_type__app_label="core", codename="query_data"
        )
        user.user_permissions.add(perm)
        self.assertTrue(has_feature_perm(user, "core.query_data"))

    def test_returns_false_for_user_without_permission(self):
        user = get_user_model().objects.create_user(
            username="no-perm", password="pass12345"
        )
        self.assertFalse(has_feature_perm(user, "core.query_data"))

    def test_returns_true_for_group_inherited_permission(self):
        user = get_user_model().objects.create_user(
            username="group-perm-user", password="pass12345"
        )
        group = Group.objects.create(name="后台用户")
        perm = Permission.objects.get(
            content_type__app_label="core", codename="query_data"
        )
        group.permissions.add(perm)
        user.groups.add(group)

        self.assertTrue(has_feature_perm(user, "core.query_data"))

    def test_user_disabled_permission_overrides_group_grant(self):
        user = get_user_model().objects.create_user(
            username="disabled-group-perm-user", password="pass12345"
        )
        group = Group.objects.create(name="可关闭后台用户")
        perm = Permission.objects.get(
            content_type__app_label="core", codename="query_data"
        )
        group.permissions.add(perm)
        user.groups.add(group)
        UserProfile.objects.create(
            user=user,
            disabled_permissions=["core.query_data"],
        )

        self.assertFalse(has_feature_perm(user, "core.query_data"))


class SuperadminInitializationTests(TestCase):
    def test_ensure_superadmin_defaults_creates_group_and_grants_all_permissions(self):
        get_user_model().objects.all().delete()
        Group.objects.filter(name=SUPERADMIN_GROUP_NAME).delete()

        user, group = ensure_superadmin_defaults()

        self.assertEqual(group.name, SUPERADMIN_GROUP_NAME)
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "admin")
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertTrue(user.groups.filter(id=group.id).exists())
        self.assertTrue(is_superadmin_user(user))
        group_permissions = {
            f"{permission.content_type.app_label}.{permission.codename}"
            for permission in group.permissions.select_related("content_type")
        }
        self.assertEqual(group_permissions, set(protected_group_permissions()))
        self.assertIn("core.manage_data_backup", group_permissions)

    def test_ensure_superadmin_defaults_creates_platform_data_admin_group(
        self,
    ):
        ensure_superadmin_defaults(create_account=False)

        group = Group.objects.get(name=PLATFORM_ADMIN_GROUP_NAME)
        group_permissions = _group_feature_permissions(group)
        self.assertEqual(group_permissions, platform_admin_group_permissions())
        self.assertIn("core.manage_auth", group_permissions)
        self.assertIn("core.manage_feature_permissions", group_permissions)
        self.assertIn("catalog.change_dataresource", group_permissions)
        self.assertIn("raster.manage_raster_dataset", group_permissions)
        self.assertNotIn("core.manage_system_settings", group_permissions)
        self.assertNotIn("core.view_system_logs", group_permissions)
        self.assertNotIn("core.view_dashboard_system_card", group_permissions)
        self.assertNotIn("core.manage_data_backup", group_permissions)

    def test_ensure_superadmin_defaults_creates_research_user_group(self):
        ensure_superadmin_defaults(create_account=False)

        group = Group.objects.get(name=RESEARCH_USER_GROUP_NAME)
        group_permissions = _group_feature_permissions(group)
        self.assertEqual(group_permissions, research_user_group_permissions())
        self.assertIn("catalog.add_dataresource", group_permissions)
        self.assertIn("catalog.export_dataresource", group_permissions)
        self.assertIn("core.ai_interpretation", group_permissions)
        self.assertIn("catalog.delete_workspacescene", group_permissions)
        self.assertNotIn("catalog.delete_dataresource", group_permissions)
        self.assertNotIn("core.manage_auth", group_permissions)

    def test_previous_builtin_role_defaults_are_migrated_to_stable_defaults(self):
        migrations = (
            (
                PLATFORM_ADMIN_GROUP_NAME,
                PREVIOUS_PLATFORM_ADMIN_GROUP_PERMISSIONS,
                platform_admin_group_permissions(),
            ),
            (
                RESEARCH_USER_GROUP_NAME,
                PREVIOUS_RESEARCH_USER_GROUP_PERMISSIONS,
                research_user_group_permissions(),
            ),
            (
                GUEST_GROUP_NAME,
                PREVIOUS_GUEST_GROUP_PERMISSIONS,
                guest_group_permissions(),
            ),
        )
        for group_name, previous_permissions, _ in migrations:
            group = Group.objects.get(name=group_name)
            group.permissions.set(
                [
                    Permission.objects.get(
                        content_type__app_label=permission_name.split(".", 1)[0],
                        codename=permission_name.split(".", 1)[1],
                    )
                    for permission_name in previous_permissions
                ]
            )

        ensure_superadmin_defaults(create_account=False)

        for group_name, _, expected_permissions in migrations:
            with self.subTest(group_name=group_name):
                group = Group.objects.get(name=group_name)
                self.assertEqual(
                    _group_feature_permissions(group), expected_permissions
                )

    def test_ensure_superadmin_defaults_creates_default_user_group_for_basic_browsing(
        self,
    ):
        ensure_superadmin_defaults(create_account=False)

        group = Group.objects.get(name=DEFAULT_USER_GROUP_NAME)
        group_permissions = _group_feature_permissions(group)
        self.assertEqual(group_permissions, default_user_group_permissions())
        self.assertIn("catalog.view_workspacescene", group_permissions)
        self.assertIn("catalog.view_mapcomposition", group_permissions)
        self.assertIn("core.load_vector_layer", group_permissions)
        self.assertIn("core.load_raster_layer", group_permissions)
        self.assertNotIn("catalog.add_dataresource", group_permissions)
        self.assertNotIn("catalog.add_workspacescene", group_permissions)
        self.assertNotIn("catalog.change_workspacescene", group_permissions)
        self.assertNotIn("catalog.add_mapcomposition", group_permissions)
        self.assertNotIn("catalog.change_mapcomposition", group_permissions)
        self.assertNotIn("catalog.view_dataresource", group_permissions)
        self.assertNotIn("catalog.change_dataresource", group_permissions)
        self.assertNotIn("catalog.delete_dataresource", group_permissions)
        self.assertNotIn("catalog.export_dataresource", group_permissions)
        self.assertNotIn("core.custom_symbolization", group_permissions)
        self.assertNotIn("core.ai_interpretation", group_permissions)
        self.assertNotIn("raster.manage_raster_dataset", group_permissions)
        self.assertNotIn("core.manage_data_backup", group_permissions)
        self.assertNotIn("core.manage_auth", group_permissions)

    def test_existing_legacy_default_user_group_is_migrated_to_current_defaults(
        self,
    ):
        group = Group.objects.get(name=DEFAULT_USER_GROUP_NAME)
        legacy_permissions = [
            Permission.objects.get(
                content_type__app_label=permission_name.split(".", 1)[0],
                codename=permission_name.split(".", 1)[1],
            )
            for permission_name in (
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
                "core.load_vector_layer",
                "core.load_raster_layer",
                "raster.manage_raster_dataset",
            )
        ]
        group.permissions.set(legacy_permissions)

        ensure_superadmin_defaults(create_account=False)

        group.refresh_from_db()
        self.assertEqual(
            _group_feature_permissions(group), default_user_group_permissions()
        )

    def test_existing_custom_default_user_group_keeps_custom_permissions_and_minimum(
        self,
    ):
        group = Group.objects.get(name=DEFAULT_USER_GROUP_NAME)
        group.permissions.set(
            [
                Permission.objects.get(
                    content_type__app_label="core", codename="query_data"
                )
            ]
        )

        ensure_superadmin_defaults(create_account=False)

        group.refresh_from_db()
        self.assertEqual(
            _group_feature_permissions(group),
            {"core.query_data", "catalog.view_mapcomposition"},
        )

    def test_ensure_superadmin_defaults_creates_guest_group_for_public_browsing(
        self,
    ):
        ensure_superadmin_defaults(create_account=False)

        group = Group.objects.get(name=GUEST_GROUP_NAME)
        group_permissions = _group_feature_permissions(group)
        self.assertEqual(group_permissions, guest_group_permissions())
        self.assertIn("core.browse_data", group_permissions)
        self.assertIn("core.query_data", group_permissions)
        self.assertIn("core.load_vector_layer", group_permissions)
        self.assertIn("core.load_raster_layer", group_permissions)
        self.assertIn("catalog.view_workspacescene", group_permissions)
        self.assertNotIn("catalog.add_dataresource", group_permissions)
        self.assertNotIn("catalog.export_dataresource", group_permissions)
        self.assertNotIn("core.manage_data_backup", group_permissions)

    def test_ensure_superadmin_defaults_preserves_guest_group_custom_permissions(
        self,
    ):
        ensure_superadmin_defaults(create_account=False)
        group = Group.objects.get(name=GUEST_GROUP_NAME)
        group.permissions.set(
            [
                Permission.objects.get(
                    content_type__app_label="core", codename="query_data"
                )
            ]
        )

        ensure_superadmin_defaults(create_account=False)

        group.refresh_from_db()
        group_permissions = _group_feature_permissions(group)
        self.assertEqual(group_permissions, {"core.query_data"})

    def test_existing_superuser_is_attached_to_superadmin_group(self):
        user = get_user_model().objects.create_superuser(
            username="manual-super",
            password="StrongPass12345",
        )

        ensure_superadmin_defaults()

        self.assertTrue(user.groups.filter(name=SUPERADMIN_GROUP_NAME).exists())


def _group_feature_permissions(group: Group) -> set[str]:
    feature_ids = set(feature_permission_queryset().values_list("id", flat=True))
    return {
        f"{permission.content_type.app_label}.{permission.codename}"
        for permission in group.permissions.select_related("content_type")
        if permission.id in feature_ids
    }


class GroupNamesTests(TestCase):
    def test_returns_ungrouped_for_user_without_groups(self):
        user = get_user_model().objects.create_user(
            username="no-group", password="pass12345"
        )
        self.assertEqual(group_names(user), "未分配角色")

    def test_returns_group_name(self):
        user = get_user_model().objects.create_user(
            username="with-group", password="pass12345"
        )
        group = Group.objects.create(name="科研辅助组")
        user.groups.add(group)
        self.assertEqual(group_names(user), "科研辅助组")

    def test_returns_multiple_group_names(self):
        user = get_user_model().objects.create_user(
            username="multi-group", password="pass12345"
        )
        group1 = Group.objects.create(name="科研辅助组")
        group2 = Group.objects.create(name="数据协作组")
        user.groups.add(group1, group2)
        names = group_names(user)
        self.assertIn("科研辅助组", names)
        self.assertIn("数据协作组", names)


class PermissionDeniedMessageTests(TestCase):
    def test_includes_group_name(self):
        user = get_user_model().objects.create_user(
            username="denied-user", password="pass12345"
        )
        message = permission_denied_message(user)
        self.assertIn("未分配角色", message)
        self.assertIn("无权限", message)


class FeatureDeniedResponseTests(TestCase):
    def test_returns_403_status(self):
        user = get_user_model().objects.create_user(
            username="denied-response", password="pass12345"
        )
        response = feature_denied_response(user)
        self.assertEqual(response.status_code, 403)

    def test_contains_detail_message(self):
        user = get_user_model().objects.create_user(
            username="denied-response2", password="pass12345"
        )
        response = feature_denied_response(user)
        import json

        data = json.loads(response.content)
        self.assertIn("detail", data)
        self.assertIn("无权限", data["detail"])


class FeaturePermissionQuerysetTests(TestCase):
    def test_returns_permissions_for_feature_apps(self):
        queryset = feature_permission_queryset()
        self.assertGreater(queryset.count(), 0)
        for perm in queryset:
            self.assertIn(
                perm.content_type.app_label, {"core", "catalog", "raster", "compute"}
            )


class FeaturePermissionIdsForTests(TestCase):
    def test_returns_empty_set_for_new_group(self):
        group = Group.objects.create(name="测试组")
        ids = feature_permission_ids_for(group)
        self.assertEqual(ids, set())

    def test_returns_assigned_permission_ids(self):
        group = Group.objects.create(name="测试组2")
        from django.contrib.auth.models import Permission

        perm = Permission.objects.get(
            content_type__app_label="core", codename="browse_data"
        )
        group.permissions.add(perm)
        ids = feature_permission_ids_for(group)
        self.assertIn(perm.id, ids)
