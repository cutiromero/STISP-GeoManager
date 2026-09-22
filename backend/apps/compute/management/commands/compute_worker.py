import logging
import os
import sqlite3
import threading
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, close_old_connections
from apps.core.storage import app_path
from apps.compute.worker import worker_tick, pulse

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the durable compute worker and scheduled result cleanup"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        path = app_path("cache", "compute-worker.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise CommandError("另一个计算工作进程已经运行") from exc
            stop = threading.Event()

            def heartbeat():
                while not stop.wait(8):
                    close_old_connections()
                    try:
                        pulse()
                    except Exception:
                        self.stderr.write("Worker heartbeat temporarily unavailable")
                    finally:
                        close_old_connections()

            thread = threading.Thread(target=heartbeat, daemon=True)
            thread.start()
            recovered = False
            self.stdout.write("Compute worker started; isolated runtime only.")
            try:
                while True:
                    close_old_connections()
                    try:
                        recovered = worker_tick(recovered=recovered)
                    except OperationalError as exc:
                        code = getattr(exc.__cause__, "sqlite_errorcode", 0)
                        if options["once"] or code & 0xFF not in (
                            sqlite3.SQLITE_BUSY,
                            sqlite3.SQLITE_LOCKED,
                        ):
                            raise
                        # A tick may have acquired a task before encountering
                        # contention. Reconcile fenced attempts on the next tick.
                        recovered = False
                        close_old_connections()
                        logger.warning("Compute database busy; retrying next tick")
                    if options["once"]:
                        break
                    time.sleep(3)
            except KeyboardInterrupt:
                self.stdout.write("Compute worker stopped.")
            finally:
                stop.set()
                thread.join(timeout=2)
