import uuid
from django.db import migrations, models


def assign_keys(apps, schema_editor):
    Import = apps.get_model("compute", "ComputeImport")
    for item in Import.objects.filter(storage_key__isnull=True).iterator():
        item.storage_key = uuid.uuid4()
        item.save(update_fields=["storage_key"])


class Migration(migrations.Migration):
    dependencies = [("compute", "0002_queue_and_permissions")]
    operations = [
        migrations.AddField(
            model_name="computeimport",
            name="storage_key",
            field=models.UUIDField(null=True, unique=True, editable=False),
        ),
        migrations.RunPython(assign_keys, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="computeimport",
            name="storage_key",
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
    ]
