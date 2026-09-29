from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0011_compute_followup_workflow_plan")]
    operations = [
        migrations.AlterField(
            model_name="agentworkflow",
            name="plan",
            field=models.JSONField(default=dict, db_default={}),
        ),
        migrations.AlterField(
            model_name="agentworkflow",
            name="plan_hash",
            field=models.CharField(max_length=64, blank=True, db_default=""),
        ),
        migrations.AlterField(
            model_name="agentworkflow",
            name="import_results",
            field=models.BooleanField(default=True, db_default=True),
        ),
        migrations.AlterField(
            model_name="agentworkflow",
            name="result_resource_ids",
            field=models.JSONField(default=list, db_default=[]),
        ),
    ]
