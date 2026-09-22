from django.db import migrations


def regroup(apps, schema_editor):
    Dictionary = apps.get_model("catalog", "DictionaryItem")
    Resource = apps.get_model("catalog", "DataResource")
    Result = apps.get_model("catalog", "ResultArtifact")
    categories = {}
    for code, name, description, order in (
        ("spatial", "地理数据", "具有已解析地理坐标的矢量、栅格和坐标表格数据。", 10),
        ("non_spatial", "非地理数据", "没有地理坐标的表格、文档、图片及其他资料。", 20),
    ):
        categories[code], _ = Dictionary.objects.update_or_create(
            dict_type="data_category",
            code=code,
            defaults={
                "name": name,
                "description": description,
                "sort_order": order,
                "parent": None,
                "is_active": True,
                "is_selectable": True,
            },
        )
    # Keep old dictionary rows for historical references; never remove resources or files.
    Dictionary.objects.filter(dict_type="data_category").exclude(
        code__in=categories
    ).update(is_active=False, is_selectable=False)
    Resource.objects.all().update(category=categories["non_spatial"])
    Resource.objects.filter(data_type__in=["vector", "raster"]).exclude(
        coordinate_system=""
    ).update(category=categories["spatial"])
    # Imported renderings/documents do not contain georeferencing themselves.
    Result.objects.all().update(category=categories["non_spatial"])


class Migration(migrations.Migration):
    dependencies = [
        (
            "catalog",
            "0016_remove_workspacescene_uniq_workspace_scene_owner_kind_name_and_more",
        )
    ]
    operations = [migrations.RunPython(regroup)]
