from django.db import migrations, models
from django.utils import timezone


def resolve_duplicate_active_runs(apps, schema_editor):
    BackupRun = apps.get_model("core", "BackupRun")
    for plan_type in ("platform", "research"):
        active_runs = list(
            BackupRun.objects.filter(
                plan_type=plan_type,
                status__in=("queued", "running"),
            ).order_by("-created_at", "-pk")
        )
        for stale_run in active_runs[1:]:
            stale_run.status = "failed"
            stale_run.error_message = "启动时检测到同计划重复活动任务，已安全终止"
            stale_run.finished_at = timezone.now()
            stale_run.save(
                update_fields=("status", "error_message", "finished_at")
            )


class Migration(migrations.Migration):
    dependencies = [("core", "0006_role_application_and_email_identity")]

    operations = [
        migrations.RunPython(
            resolve_duplicate_active_runs,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="backuprun",
            constraint=models.UniqueConstraint(
                fields=("plan_type",),
                condition=models.Q(status__in=("queued", "running")),
                name="uniq_active_backup_run_per_plan",
            ),
        ),
    ]
