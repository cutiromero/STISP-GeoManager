from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("standards", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="resourcedomain",
            name="domain_type",
            field=models.CharField(
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
