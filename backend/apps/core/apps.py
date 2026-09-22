from django.apps import AppConfig

_startup_credentials_printed = False


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "系统核心"

    def ready(self):
        global _startup_credentials_printed
        from django.db.models.signals import post_migrate

        from apps.core.initialization import ensure_superadmin_defaults_after_migrate

        post_migrate.connect(
            ensure_superadmin_defaults_after_migrate,
            sender=self,
            dispatch_uid="apps.core.ensure_superadmin_defaults",
        )
        if not _startup_credentials_printed:
            _startup_credentials_printed = True
            self._print_credentials_async()
        from apps.core.backup_scheduler import start_backup_scheduler_once

        start_backup_scheduler_once()

    def _print_credentials_async(self):
        import os
        import sys
        import threading

        if len(sys.argv) > 1 and sys.argv[1] not in {"runserver"}:
            if "waitress" not in " ".join(sys.argv):
                return
        if "migrate" in sys.argv or "collectstatic" in sys.argv:
            return
        if (
            len(sys.argv) > 1
            and sys.argv[1] == "runserver"
            and os.environ.get("RUN_MAIN") != "true"
        ):
            return

        def run_print():
            from django.db import close_old_connections, connection

            from apps.core.initialization import print_superadmin_credentials_on_startup

            close_old_connections()
            try:
                print_superadmin_credentials_on_startup()
            finally:
                connection.close()

        threading.Thread(
            target=run_print, name="core-startup-credentials", daemon=True
        ).start()
