"""Coalesce simultaneous renders of one tile without retaining idle locks."""

from collections.abc import Hashable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import threading


@dataclass
class _PendingTile:
    lock: threading.Lock = field(default_factory=threading.Lock)
    users: int = 0


_pending: dict[Hashable, _PendingTile] = {}
_registry_lock = threading.Lock()


@contextmanager
def tile_render_slot(key: Hashable) -> Iterator[None]:
    with _registry_lock:
        pending = _pending.setdefault(key, _PendingTile())
        pending.users += 1
    try:
        with pending.lock:
            yield
    finally:
        with _registry_lock:
            pending.users -= 1
            if not pending.users:
                del _pending[key]
