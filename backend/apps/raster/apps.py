from django.apps import AppConfig

_startup_scan_started = False


class RasterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.raster"
    verbose_name = "栅格数据"

    def ready(self) -> None:
        global _startup_scan_started
        if _startup_scan_started:
            return
        _startup_scan_started = True

        import os
        import sys
        from django.conf import settings

        if settings.PROJECT_CONFIG.runtime.disable_raster_startup_scan:
            return
        if not _server_startup_command(sys.argv):
            return
        if _runserver_autoreload_parent(sys.argv, os.environ):
            return

        # Startup and API-triggered scans go through the same single-flight job
        # and the same bounded heavy-task executor.
        from django.db import close_old_connections, connection

        from apps.raster.services.jobs import start_scan_job

        close_old_connections()
        try:
            start_scan_job()
        finally:
            # This is the startup thread's connection. The executor worker has
            # its own thread-local connection lifecycle.
            connection.close()


def _server_startup_command(argv: list[str]) -> bool:
    if "test" in argv or "migrate" in argv or "collectstatic" in argv:
        return False
    if len(argv) > 1 and argv[1] == "runserver":
        return True
    command_text = " ".join(argv)
    return any(name in command_text for name in ("waitress", "uvicorn", "daphne"))


def _runserver_autoreload_parent(argv: list[str], environ) -> bool:
    return (
        len(argv) > 1 and argv[1] == "runserver" and environ.get("RUN_MAIN") != "true"
    )
