from django.db import migrations, models


def classify_compute_results(apps, schema_editor):
    Dictionary = apps.get_model("catalog", "DictionaryItem")
    Resource = apps.get_model("catalog", "DataResource")
    Import = apps.get_model("compute", "ComputeImport")
    category, _ = Dictionary.objects.update_or_create(
        dict_type="data_category",
        code="compute_results",
        defaults={
            "name": "计算结果",
            "description": "计算中心和智能体计算后入库的结果，保留各自的地理属性和数据类型。",
            "sort_order": 30,
            "parent": None,
            "is_active": True,
            "is_selectable": False,
        },
    )
    # Only verified output/resource links are evidence of computed provenance.
    # A user-uploaded name or editable source string cannot classify a resource.
    linked_resources = Import.objects.filter(
        resource_id__isnull=False,
        resource__project_tag_id=models.F("output__task__project_tag_id"),
    ).values("resource_id")
    Resource.objects.filter(pk__in=linked_resources).update(
        is_compute_result=True, category=category
    )


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0018_dataresource_owner_only"),
        ("compute", "0005_ndvi_description"),
    ]

    operations = [
        migrations.AddField(
            model_name="dataresource",
            name="is_compute_result",
            field=models.BooleanField(
                default=False,
                db_default=False,
                editable=False,
                help_text="由计算结果入库流程登记；用户上传保留地理/非地理分类。",
                verbose_name="计算结果",
            ),
        ),
        migrations.RunPython(classify_compute_results, migrations.RunPython.noop),
    ]
