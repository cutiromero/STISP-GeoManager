"""Process-safe storage locks shared by version preparation and display caches."""

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import time


class StorageLockTimeout(TimeoutError):
    pass


@contextmanager
def storage_lock(path: Path, *, wait=True, timeout=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)

            def acquire(blocking):
                msvcrt.locking(
                    stream.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1
                )

            def release():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire(blocking):
                fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))

            def release():
                fcntl.flock(stream, fcntl.LOCK_UN)

        if timeout is None or not wait:
            acquire(wait)
        else:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    acquire(False)
                    break
                except OSError as error:
                    if error.errno not in {
                        errno.EACCES,
                        errno.EAGAIN,
                        errno.EWOULDBLOCK,
                    }:
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise StorageLockTimeout("同一数据的准备尚未完成") from error
                    time.sleep(min(0.01, remaining))
        try:
            yield
        finally:
            release()
