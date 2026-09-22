import signal
import threading
import os
from apps.core.storage import app_path
from django.core.management.base import CommandError
from django.core.management.base import BaseCommand
from apps.agent.worker import serve


class Command(BaseCommand):
    help = "Run the separate local-model queue; never executes operators or code"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        path = app_path("cache", "agent-worker.lock")
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
                raise CommandError("另一个智能体工作进程已经运行") from exc
            stop = threading.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: stop.set())
            self.stdout.write("Agent worker started; read-only tools only.")
            serve(stop, once=options["once"])
