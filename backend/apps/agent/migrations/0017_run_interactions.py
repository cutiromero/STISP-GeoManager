from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0016_workflow_pause")]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="interaction",
            field=models.JSONField(default=dict, db_default={}),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="interaction_history",
            field=models.JSONField(default=list, db_default=[]),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="execution_state",
            field=models.JSONField(default=dict, db_default={}),
        ),
    ]
