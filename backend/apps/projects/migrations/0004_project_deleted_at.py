from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0003_project_features")]

    operations = [
        migrations.AddField(
            model_name="project",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
