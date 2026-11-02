from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("agent", "0017_run_interactions")]

    operations = [
        migrations.RemoveConstraint(
            model_name="agentrun", name="agent_one_active_user"
        ),
    ]
