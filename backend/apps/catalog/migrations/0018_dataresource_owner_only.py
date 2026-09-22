from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0017_coordinate_data_categories"),
    ]

    operations = [
        migrations.AddField(
            model_name="dataresource",
            name="owner_only",
            field=models.BooleanField(
                default=False,
                help_text="启用后仅上传者和超级管理员可访问；默认项目成员可见。",
                verbose_name="仅上传者可见",
            ),
        ),
    ]
