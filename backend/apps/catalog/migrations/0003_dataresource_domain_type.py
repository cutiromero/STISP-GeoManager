from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("standards", "0001_initial"),
        ("catalog", "0002_dataresourcegroup_dataresource_inventory_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="dataresource",
            name="domain_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("germplasm", "种质数据"),
                    ("genome", "基因组数据"),
                    ("individual", "个体数据"),
                    ("community", "群落数据"),
                    ("population", "种群数据"),
                    ("field_survey", "野外调查数据"),
                    ("remote_sensing", "遥感影像数据"),
                    ("molecular", "分子数据"),
                ],
                max_length=32,
                verbose_name="业务数据类型",
            ),
        ),
    ]
