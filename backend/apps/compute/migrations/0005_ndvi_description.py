from django.db import migrations


NDVI_DESCRIPTION = (
    "选择同一幅多波段反射率影像的红光、近红外波段，"
    "按 (近红外−红光)/(近红外＋红光) 计算 NDVI，用于植被覆盖与长势的辅助分析。"
    "输出单波段 Float32 GeoTIFF，保留坐标系、分辨率及范围；"
    "无效像元与零分母标记为 NoData（−9999）。"
)
DEFAULT_DESCRIPTIONS = (
    "",
    "平台提供的算法接入示例，须在隔离环境试运行后发布。",
    "NDVI示例的标准接入示例；管理员须使用小样试运行并核对结果后发布。",
)


def populate_ndvi_description(apps, schema_editor):
    # Update catalog metadata only; published package contents remain immutable.
    algorithm = apps.get_model("compute", "AlgorithmResource")
    algorithm.objects.using(schema_editor.connection.alias).filter(
        project_tag_id=1,
        identifier="raster-ndvi",
        description__in=DEFAULT_DESCRIPTIONS,
    ).update(description=NDVI_DESCRIPTION)


class Migration(migrations.Migration):
    dependencies = [("compute", "0004_import_request_source")]
    operations = [
        migrations.RunPython(populate_ndvi_description, migrations.RunPython.noop)
    ]
