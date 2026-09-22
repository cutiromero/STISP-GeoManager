from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DataResourceGroup",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        max_length=120, unique=True, verbose_name="组别名称"
                    ),
                ),
                (
                    "sort_order",
                    models.PositiveIntegerField(default=100, verbose_name="排序"),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="创建时间"),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="更新时间"),
                ),
            ],
            options={
                "verbose_name": "数据资源组别",
                "verbose_name_plural": "数据资源组别",
                "ordering": ("sort_order", "id"),
            },
        ),
        migrations.AddField(
            model_name="dataresource",
            name="inventory_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="resources",
                to="catalog.dataresourcegroup",
                verbose_name="存量数据组别",
            ),
        ),
    ]
