from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0003_dataresource_domain_type"),
    ]

    operations = [
        migrations.AlterField(
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
                    ("other", "其他类型"),
                ],
                max_length=32,
                verbose_name="业务数据类型",
            ),
        ),
    ]
