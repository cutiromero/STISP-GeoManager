from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.core.backup_service import BackupServiceError, start_backup_run
from apps.core.models import BackupRun


class Command(BaseCommand):
    help = "Run a configured data backup plan synchronously."

    def add_arguments(self, parser):
        parser.add_argument(
            "--plan",
            choices=BackupRun.PlanType.values,
            required=True,
            help="Backup plan to run: platform or research.",
        )
        parser.add_argument(
            "--target",
            choices=BackupRun.TargetType.values,
            help="Optional target override: local or object_storage.",
        )

    def handle(self, *args, **options):
        try:
            run = start_backup_run(
                plan_type=options["plan"],
                target_type=options.get("target"),
                trigger=BackupRun.Trigger.SCHEDULED,
                run_async=False,
            )
        except BackupServiceError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(f"Backup run {run.id} finished with status {run.status}")
        )
        if run.status == BackupRun.Status.FAILED:
            raise CommandError(run.error_message or "Backup failed")
