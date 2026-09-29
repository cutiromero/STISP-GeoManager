import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent", "0010_user_reasoning_effort"),
        ("compute", "0003_computeimport_storage_key"),
    ]
    operations = [
        migrations.AddField(
            model_name="agentworkflow",
            name="plan",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="agentworkflow",
            name="plan_hash",
            field=models.CharField(max_length=64, blank=True),
        ),
        migrations.AddField(
            model_name="agentworkflow",
            name="import_results",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="agentworkflow",
            name="result_resource_ids",
            field=models.JSONField(default=list),
        ),
        migrations.CreateModel(
            name="AgentComputeFollowup",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("auto_import", models.BooleanField(default=False)),
                ("output_keys", models.JSONField(default=list)),
                ("import_name", models.CharField(max_length=160, blank=True)),
                (
                    "status",
                    models.CharField(
                        max_length=24, default="waiting_compute", db_index=True
                    ),
                ),
                ("detail", models.CharField(max_length=300, blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="compute_followups",
                        to="agent.agentrun",
                    ),
                ),
                (
                    "task",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agent_followup",
                        to="compute.computetask",
                    ),
                ),
            ],
        ),
    ]
