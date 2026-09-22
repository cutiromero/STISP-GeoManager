from django.db import migrations


def rename_public(apps, schema_editor):
    apps.get_model("projects", "Project").objects.using(
        schema_editor.connection.alias
    ).filter(pk=1, is_default=True).update(name="公开")


def rename_default(apps, schema_editor):
    apps.get_model("projects", "Project").objects.using(
        schema_editor.connection.alias
    ).filter(pk=1, is_default=True).update(name="默认")


class Migration(migrations.Migration):
    dependencies = [("projects", "0001_initial")]
    operations = [migrations.RunPython(rename_public, rename_default)]
