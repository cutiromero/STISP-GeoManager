from django.db import migrations


def grant(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    content_type, _ = ContentType.objects.get_or_create(
        app_label="core", model="featurepermission"
    )
    chat, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename="use_local_model",
        defaults={"name": "可使用本地模型对话"},
    )
    agent, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename="use_data_agent",
        defaults={"name": "可使用数据智能体"},
    )
    # Fresh installs let core initialize complete default groups after migration.
    for group in Group.objects.filter(
        name__in=("普通用户", "科研用户", "平台管理员", "超级管理员")
    ):
        group.permissions.add(chat)
        if group.name != "普通用户":
            group.permissions.add(agent)


class Migration(migrations.Migration):
    dependencies = [
        ("agent", "0001_initial"),
        ("core", "0008_alter_featurepermission_options"),
    ]
    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
