from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0008_task_budgets")]
    operations = [
        migrations.AlterField(
            model_name="agentrun",
            name="budget_profile",
            field=models.CharField(
                max_length=16, blank=True, default="", db_default=""
            ),
        ),
        migrations.AlterField(
            model_name="agentrun",
            name="budget_snapshot",
            field=models.JSONField(default=dict, db_default={}),
        ),
    ]
