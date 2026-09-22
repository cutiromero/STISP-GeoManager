from __future__ import annotations

import logging
import os
import sys
import threading
import time

logger = logging.getLogger(__name__)

_scheduler_started = False


def start_backup_scheduler_once() -> None:
    global _scheduler_started
    if _scheduler_started:
        return
    if not _server_startup_command(sys.argv):
        return
    if _runserver_autoreload_parent(sys.argv, os.environ):
        return
    _scheduler_started = True
    threading.Thread(
        target=_scheduler_loop,
        name="core-backup-scheduler",
        daemon=True,
    ).start()


def _scheduler_loop() -> None:
    while True:
        try:
            from django.db import close_old_connections, connection

            from apps.core.backup_service import start_due_backup_runs

            close_old_connections()
            try:
                runs = start_due_backup_runs()
                if runs:
                    logger.info("已触发 %s 个计划数据备份任务", len(runs))
            finally:
                connection.close()
        except Exception:
            logger.exception("计划数据备份检查失败")
        time.sleep(60)


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
