from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0004_add_other_domain_type"),
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
                    ("vector", "矢量数据"),
                    ("other", "其他类型"),
                ],
                max_length=32,
                verbose_name="业务数据类型",
            ),
        ),
        migrations.CreateModel(
            name="VectorDataset",
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
                    "source_file_name",
                    models.CharField(max_length=255, verbose_name="源文件名"),
                ),
                (
                    "source_format",
                    models.CharField(
                        choices=[
                            ("SHAPEFILE", "Shapefile"),
                            ("GEOJSON", "GeoJSON"),
                            ("GPKG", "GeoPackage"),
                        ],
                        max_length=20,
                        verbose_name="源格式",
                    ),
                ),
                (
                    "source_archive_path",
                    models.CharField(
                        blank=True, max_length=255, verbose_name="原始文件归档相对路径"
                    ),
                ),
                (
                    "source_layer_name",
                    models.CharField(
                        blank=True, max_length=255, verbose_name="源图层名称"
                    ),
                ),
                (
                    "source_encoding",
                    models.CharField(
                        blank=True, max_length=40, verbose_name="源属性编码"
                    ),
                ),
                ("source_crs", models.TextField(blank=True, verbose_name="源坐标系")),
                (
                    "source_epsg",
                    models.IntegerField(blank=True, null=True, verbose_name="源 EPSG"),
                ),
                (
                    "normalized_epsg",
                    models.PositiveIntegerField(
                        default=4326, verbose_name="标准化 EPSG"
                    ),
                ),
                (
                    "geometry_type",
                    models.CharField(max_length=64, verbose_name="几何类型"),
                ),
                (
                    "feature_count",
                    models.PositiveBigIntegerField(default=0, verbose_name="要素数"),
                ),
                (
                    "vertex_count",
                    models.PositiveBigIntegerField(default=0, verbose_name="顶点数"),
                ),
                (
                    "field_count",
                    models.PositiveIntegerField(default=0, verbose_name="字段数"),
                ),
                (
                    "valid_geometry_count",
                    models.PositiveBigIntegerField(
                        default=0, verbose_name="有效几何数"
                    ),
                ),
                (
                    "invalid_geometry_count",
                    models.PositiveBigIntegerField(
                        default=0, verbose_name="无效几何数"
                    ),
                ),
                (
                    "empty_geometry_count",
                    models.PositiveBigIntegerField(default=0, verbose_name="空几何数"),
                ),
                (
                    "null_geometry_count",
                    models.PositiveBigIntegerField(
                        default=0, verbose_name="空值几何数"
                    ),
                ),
                (
                    "bounds",
                    models.JSONField(blank=True, default=list, verbose_name="边界"),
                ),
                (
                    "checksum_sha256",
                    models.CharField(
                        blank=True, max_length=64, verbose_name="源文件 SHA256"
                    ),
                ),
                (
                    "render_strategy",
                    models.CharField(
                        choices=[("geojson", "GeoJSON"), ("vector_tile", "矢量瓦片")],
                        default="geojson",
                        max_length=20,
                        verbose_name="渲染策略",
                    ),
                ),
                (
                    "import_summary",
                    models.JSONField(
                        blank=True, default=dict, verbose_name="导入质量摘要"
                    ),
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
                    "resource",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vector_dataset",
                        to="catalog.dataresource",
                        verbose_name="数据资源",
                    ),
                ),
            ],
            options={
                "verbose_name": "矢量数据集",
                "verbose_name_plural": "矢量数据集",
                "ordering": ("-created_at", "id"),
            },
        ),
    ]
