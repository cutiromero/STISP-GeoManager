"""Bound live authorization checks while consuming many tiny model SSE frames."""

from collections.abc import Callable
import threading
import time

from .provider import ModelError


class ModelStreamGuard:
    """Share one authorization poll between the stream and its watchdog thread."""

    def __init__(
        self,
        check: Callable[[], None],
        deadline: float,
        *,
        interval: float = 0.5,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not 0 < interval <= 0.5:
            raise ValueError("模型授权检查间隔必须大于0且不超过0.5秒")
        self._check = check
        self._deadline = deadline
        self._interval = interval
        self._clock = clock or time.monotonic
        self._next_check = float("-inf")
        self._failure: Exception | None = None
        self._lock = threading.Lock()

    def _check_deadline(self) -> float:
        current = self._clock()
        if current > self._deadline:
            raise ModelError("场景分析已停止或达到本步时限")
        return current

    def __call__(self) -> None:
        self._poll(force=False)

    def poll(self) -> None:
        """Read live state at watchdog ticks and before execution boundaries."""
        self._poll(force=True)

    def _poll(self, *, force: bool) -> None:
        # Even cached stream frames check their monotonic deadline immediately.
        self._check_deadline()
        with self._lock:
            current = self._check_deadline()
            if self._failure is not None:
                raise self._failure
            if not force and current < self._next_check:
                return
            try:
                from .resource_discovery import discovery_scope

                with discovery_scope():
                    self._check()
            except Exception as error:
                # Both threads must observe the same pause, cancellation or
                # revocation instead of one thread continuing on an old poll.
                self._failure = error
                raise
            self._next_check = current + self._interval
            self._check_deadline()
