from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0021_logic_configuration")]

    operations = [
        migrations.RemoveConstraint(
            model_name="agentworkflow", name="agent_one_active_workflow_user"
        ),
        migrations.AddConstraint(
            model_name="agentworkflow",
            constraint=models.UniqueConstraint(
                fields=("owner",),
                condition=models.Q(status__in=("queued", "running", "waiting_compute")),
                name="agent_one_active_workflow_user",
            ),
        ),
    ]
