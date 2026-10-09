from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0012_workflow_database_defaults")]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="compute_intent",
            field=models.JSONField(default=dict, db_default={}),
        ),
    ]
