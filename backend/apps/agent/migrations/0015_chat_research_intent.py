from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("agent", "0014_agentrun_algorithm_selection_mode_and_more")]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="research_intent",
            field=models.JSONField(db_default={}, default=dict),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="research_workflow",
            field=models.ForeignKey(
                blank=True,
                null=True,
                related_name="chat_runs",
                on_delete=django.db.models.deletion.SET_NULL,
                to="agent.agentworkflow",
            ),
        ),
    ]
