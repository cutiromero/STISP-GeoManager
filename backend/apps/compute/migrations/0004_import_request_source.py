from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("compute", "0003_computeimport_storage_key")]
    operations = [
        migrations.AddField(
            model_name="computeimport",
            name="request_source",
            field=models.CharField(
                max_length=100, blank=True, default="", db_default=""
            ),
        ),
    ]
