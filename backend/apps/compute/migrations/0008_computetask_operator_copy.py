from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("compute", "0007_operator_protocol")]

    operations = [
        migrations.AddField(
            model_name="computetask",
            name="operator_copy",
            field=models.JSONField(blank=True, db_default={}, default=dict),
        ),
    ]
