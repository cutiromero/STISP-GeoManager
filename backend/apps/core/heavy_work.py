"""Cross-process admission for existing raster work and the compute worker."""

from contextlib import contextmanager
import os
import threading
import time

from apps.core.storage import app_path

_thread_lock = threading.RLock()
_local = threading.local()


@contextmanager
def heavy_work(*, wait=True):
    if getattr(_local, "active", False):
        yield True
        return
    acquired = _thread_lock.acquire(blocking=wait)
    if not acquired:
        yield False
        return
    handle = None
    locked = False
    try:
        path = app_path("cache", "heavy-work.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+b")
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                _local.active = True
                break
            except OSError:
                if not wait:
                    break
                time.sleep(0.2)
        yield locked
    finally:
        _local.active = False
        if handle:
            if locked:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        _thread_lock.release()
