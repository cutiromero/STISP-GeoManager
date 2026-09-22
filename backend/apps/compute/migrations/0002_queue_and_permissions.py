from django.db import migrations


def configure(apps, schema_editor):
    RuntimeLease = apps.get_model("compute", "RuntimeLease")
    RuntimeLease.objects.get_or_create(name="queue")
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    definitions = {
        "algorithmresource": [
            ("manage_algorithms", "登记和维护算法"),
            ("publish_algorithm", "发布算法版本"),
            ("download_algorithm", "下载算法源码包"),
        ],
        "computetask": [
            ("submit_task", "提交计算任务"),
            ("view_own_task", "查看本人计算"),
            ("cancel_own_task", "取消本人计算"),
            ("manage_tasks", "管理项目计算任务"),
        ],
    }
    user_permissions = []
    all_permissions = []
    for model, items in definitions.items():
        content_type, _ = ContentType.objects.get_or_create(
            app_label="compute", model=model
        )
        for code, name in items:
            permission, _ = Permission.objects.get_or_create(
                content_type=content_type, codename=code, defaults={"name": name}
            )
            all_permissions.append(permission)
            if code in {"submit_task", "view_own_task", "cancel_own_task"}:
                user_permissions.append(permission)
    for name, permissions in [
        ("科研用户", user_permissions),
        ("平台管理员", all_permissions),
    ]:
        group = Group.objects.filter(name=name).first()
        if group:
            group.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [
        ("compute", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(configure, migrations.RunPython.noop)]
