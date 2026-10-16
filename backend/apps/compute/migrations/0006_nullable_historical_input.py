import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("compute", "0005_ndvi_description")]
    operations = [
        migrations.AlterField(
            model_name="computeinput",
            name="resource",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="catalog.dataresource",
            ),
        )
    ]
