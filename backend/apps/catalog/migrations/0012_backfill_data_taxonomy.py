from django.db import migrations


SAFE_DOMAIN_MAPPING = {
    "germplasm": "thematic_gene_germplasm",
    "genome": "thematic_gene_germplasm",
    "molecular": "thematic_gene_germplasm",
    "individual": "thematic_individual",
    "population": "thematic_population",
    "community": "thematic_community",
}


def backfill_data_taxonomy(apps, schema_editor):
    dictionary_item = apps.get_model("catalog", "DictionaryItem")
    data_resource = apps.get_model("catalog", "DataResource")
    categories = {
        item.code: item
        for item in dictionary_item.objects.filter(
            dict_type="data_category", code__in=set(SAFE_DOMAIN_MAPPING.values())
        )
    }
    for domain_type, category_code in SAFE_DOMAIN_MAPPING.items():
        category = categories.get(category_code)
        if category is None:
            continue
        data_resource.objects.filter(
            category_id__isnull=True, domain_type=domain_type
        ).update(category_id=category.id)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0011_seed_data_taxonomy"),
    ]

    operations = [
        migrations.RunPython(backfill_data_taxonomy, migrations.RunPython.noop),
    ]
