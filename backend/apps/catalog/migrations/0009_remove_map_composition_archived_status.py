from django.db import migrations, models


def preserve_archived_map_compositions(apps, schema_editor):
    composition_model = apps.get_model("catalog", "MapComposition")
    # 历史 archived 专题可能仍包含已生成版本和成果文件。新版状态枚举不再
    # 暴露 archived，但迁移不能以删除业务数据作为代价；统一安全转换为
    # completed，保留专题、版本、工程快照和成果登记。
    composition_model.objects.filter(status="archived").update(status="completed")


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0008_map_composition_publication_and_project_only"),
    ]

    operations = [
        migrations.RunPython(
            preserve_archived_map_compositions,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="mapcomposition",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "草稿"),
                    ("completed", "已生成成果"),
                    ("published", "已发布"),
                ],
                default="draft",
                max_length=16,
                verbose_name="状态",
            ),
        ),
    ]
