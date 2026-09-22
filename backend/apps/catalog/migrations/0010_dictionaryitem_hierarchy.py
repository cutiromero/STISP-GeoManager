from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0009_remove_map_composition_archived_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="dictionaryitem",
            name="is_selectable",
            field=models.BooleanField(default=True, verbose_name="允许选择"),
        ),
        migrations.AddField(
            model_name="dictionaryitem",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="children",
                to="catalog.dictionaryitem",
                verbose_name="上级字典项",
            ),
        ),
        migrations.AddConstraint(
            model_name="dictionaryitem",
            constraint=models.CheckConstraint(
                condition=~models.Q(id=models.F("parent_id")),
                name="dictionary_parent_not_self",
            ),
        ),
        migrations.AddIndex(
            model_name="dictionaryitem",
            index=models.Index(
                fields=["dict_type", "parent", "is_active", "sort_order"],
                name="catalog_dic_type_parent_idx",
            ),
        ),
    ]
