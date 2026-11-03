from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0008_alter_featurepermission_options")]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="allow_public_project",
            field=models.BooleanField(default=True, verbose_name="允许访问公开项目"),
        )
    ]
