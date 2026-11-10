from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("compute", "0006_nullable_historical_input")]
    operations = [
        migrations.AddField(
            model_name="computetask",
            name="failure",
            field=models.JSONField(default=dict, blank=True, db_default={}),
        ),
        migrations.AddField(
            model_name="computetask",
            name="field_mappings",
            field=models.JSONField(default=dict, blank=True, db_default={}),
        ),
        migrations.AddField(
            model_name="computetask",
            name="input_collections",
            field=models.JSONField(default=dict, blank=True, db_default={}),
        ),
    ]
