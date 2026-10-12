from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0015_chat_research_intent")]

    operations = [
        migrations.AddField(
            model_name="agentworkflow",
            name="pause_requested",
            field=models.BooleanField(default=False, db_default=False),
        ),
        migrations.AddField(
            model_name="agentworkflow",
            name="paused_from",
            field=models.CharField(
                max_length=24, blank=True, default="", db_default=""
            ),
        ),
        migrations.RemoveConstraint(
            model_name="agentworkflow", name="agent_one_active_workflow_user"
        ),
        migrations.AddConstraint(
            model_name="agentworkflow",
            constraint=models.UniqueConstraint(
                fields=("owner",),
                condition=models.Q(
                    status__in=(
                        "queued",
                        "running",
                        "waiting_compute",
                        "waiting_approval",
                        "paused",
                    )
                ),
                name="agent_one_active_workflow_user",
            ),
        ),
    ]
