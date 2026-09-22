import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("catalog", "0006_workspace_superadmin_visibility"),
    ]

    operations = [
        migrations.CreateModel(
            name="MapComposition",
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
                ("name", models.CharField(max_length=160, verbose_name="专题图名称")),
                (
                    "description",
                    models.TextField(blank=True, verbose_name="专题图说明"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "草稿"),
                            ("completed", "已生成成果"),
                            ("published", "已发布"),
                            ("archived", "已归档"),
                        ],
                        default="draft",
                        max_length=16,
                        verbose_name="状态",
                    ),
                ),
                (
                    "layout",
                    models.JSONField(blank=True, default=dict, verbose_name="版式配置"),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="创建时间"),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="更新时间"),
                ),
                (
                    "access_groups",
                    models.ManyToManyField(
                        blank=True,
                        related_name="map_compositions",
                        to="auth.group",
                        verbose_name="访问角色",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="map_compositions",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="所属用户",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="map_compositions",
                        to="catalog.workspacescene",
                        verbose_name="来源工程",
                    ),
                ),
            ],
            options={
                "verbose_name": "专题出图稿",
                "verbose_name_plural": "专题出图稿",
                "ordering": ("-updated_at", "id"),
                "permissions": [
                    ("export_mapcomposition", "导出专题图成果"),
                    ("publish_mapcomposition", "发布专题图成果"),
                ],
            },
        ),
        migrations.CreateModel(
            name="MapCompositionVersion",
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
                ("version_number", models.PositiveIntegerField(verbose_name="版本号")),
                (
                    "format",
                    models.CharField(
                        choices=[("png", "PNG"), ("jpg", "JPG"), ("pdf", "PDF")],
                        max_length=8,
                        verbose_name="格式",
                    ),
                ),
                (
                    "dpi",
                    models.PositiveSmallIntegerField(default=300, verbose_name="DPI"),
                ),
                ("width_px", models.PositiveIntegerField(verbose_name="宽度像素")),
                ("height_px", models.PositiveIntegerField(verbose_name="高度像素")),
                (
                    "note",
                    models.CharField(
                        blank=True, max_length=500, verbose_name="版本说明"
                    ),
                ),
                (
                    "preview_path",
                    models.CharField(max_length=500, verbose_name="预览文件路径"),
                ),
                (
                    "artifact_path",
                    models.CharField(max_length=500, verbose_name="成果文件路径"),
                ),
                (
                    "layout_snapshot",
                    models.JSONField(blank=True, default=dict, verbose_name="版式快照"),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="生成时间"),
                ),
                (
                    "composition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="versions",
                        to="catalog.mapcomposition",
                        verbose_name="出图稿",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_map_composition_versions",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="生成人",
                    ),
                ),
            ],
            options={
                "verbose_name": "专题图成果版本",
                "verbose_name_plural": "专题图成果版本",
                "ordering": ("-version_number", "-created_at"),
            },
        ),
        migrations.AddConstraint(
            model_name="mapcomposition",
            constraint=models.UniqueConstraint(
                fields=("owner", "project", "name"),
                name="uniq_map_composition_owner_project_name",
            ),
        ),
        migrations.AddConstraint(
            model_name="mapcompositionversion",
            constraint=models.UniqueConstraint(
                fields=("composition", "version_number"),
                name="uniq_map_composition_version_number",
            ),
        ),
    ]
