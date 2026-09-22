from django.apps import AppConfig

_startup_scan_started = False


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"
    verbose_name = "数据目录"

    def ready(self) -> None:
        global _startup_scan_started
        if _startup_scan_started:
            return
        _startup_scan_started = True

        import os
        import sys
        import threading

        from django.conf import settings

        if settings.PROJECT_CONFIG.runtime.disable_catalog_startup_scan:
            return
        if not _server_startup_command(sys.argv):
            return
        if _runserver_autoreload_parent(sys.argv, os.environ):
            return

        def run_scan() -> None:
            from django.db import close_old_connections, connection

            from apps.catalog.services import scan_catalog_sources_safely

            close_old_connections()
            try:
                scan_catalog_sources_safely()
            finally:
                connection.close()

        threading.Thread(
            target=run_scan, name="catalog-startup-scan", daemon=True
        ).start()


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
