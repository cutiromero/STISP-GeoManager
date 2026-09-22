from django.db import migrations


def grant_result_permissions_to_builtin_groups(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    content_type, _ = ContentType.objects.get_or_create(
        app_label="catalog", model="resultartifact"
    )
    permissions = {}
    for codename, name in (
        ("view_resultartifact", "Can view 成果文件"),
        ("add_resultartifact", "Can add 成果文件"),
        ("delete_resultartifact", "Can delete 成果文件"),
        ("download_resultartifact", "下载成果文件"),
        ("publish_resultartifact", "发布成果文件"),
    ):
        permissions[codename], _ = Permission.objects.get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )

    grants = {
        "平台管理员": tuple(permissions),
        "科研用户": tuple(permissions),
        "普通用户": ("view_resultartifact",),
        "游客": ("view_resultartifact",),
        "超级管理员": tuple(permissions),
    }
    for group_name, codenames in grants.items():
        group = Group.objects.filter(name=group_name).first()
        if group is not None:
            group.permissions.add(*(permissions[name] for name in codenames))


class Migration(migrations.Migration):
    dependencies = [("catalog", "0013_resultartifact")]

    operations = [
        migrations.AlterModelOptions(
            name="resultartifact",
            options={
                "ordering": ("-published_at", "-updated_at", "id"),
                "permissions": [
                    ("download_resultartifact", "下载成果文件"),
                    ("publish_resultartifact", "发布成果文件"),
                ],
                "verbose_name": "成果文件",
                "verbose_name_plural": "成果文件",
            },
        ),
        migrations.RunPython(
            grant_result_permissions_to_builtin_groups,
            migrations.RunPython.noop,
        ),
    ]
