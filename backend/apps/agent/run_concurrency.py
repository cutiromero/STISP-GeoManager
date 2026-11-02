"""Shared atomic admission for ordinary chat and data-agent model work."""

from functools import wraps
import time

from django.db import OperationalError, connection, transaction
from django.utils import timezone

from apps.compute.packages import ComputeError
from .models import ACTIVE, AgentRun, AgentRuntime

USER_RUN_LIMIT = 3
GLOBAL_RUN_LIMIT = 30
WAITING = ("waiting_input", "waiting_review", "waiting_compute")


def retry_run_admission(function):
    """Retry the complete transaction after a transient SQLite writer conflict."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        nested = connection.in_atomic_block
        for attempt in range(6):
            try:
                return function(*args, **kwargs)
            except OperationalError as exc:
                if (
                    connection.vendor != "sqlite"
                    or nested
                    or attempt == 5
                    or not any(
                        word in str(exc).casefold() for word in ("locked", "busy")
                    )
                ):
                    raise
                time.sleep(0.03 * (attempt + 1))

    return wrapped


def lock_run_queue() -> None:
    """Use the worker's queue row before reads establish a SQLite WAL snapshot.

    UPDATE also takes a row lock on other databases. The worker creates this
    record on its first claim; the empty UPDATE reserves SQLite's writer when
    an installation has not claimed its first run yet.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Run admission requires an atomic transaction")
    now = timezone.now()
    if not AgentRuntime.objects.filter(name="queue").update(heartbeat=now):
        AgentRuntime.objects.get_or_create(name="queue", defaults={"heartbeat": now})


def require_run_capacity(
    owner_id: int, conversation_id: int, *, exclude_run_id=None
) -> None:
    """Caller holds lock_run_queue through the subsequent create/status update."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Run admission requires an atomic transaction")
    runs = AgentRun._base_manager.all()
    if exclude_run_id is not None:
        runs = runs.exclude(pk=exclude_run_id)
    if runs.filter(
        conversation_id=conversation_id, status__in=(*ACTIVE, *WAITING)
    ).exists():
        raise ComputeError(
            "当前会话已有正在处理或等待的任务，请在原任务中继续或停止后再提问", 409
        )
    active = runs.filter(status__in=ACTIVE)
    if active.filter(owner_id=owner_id).count() >= USER_RUN_LIMIT:
        raise ComputeError(
            "当前账号已有3个排队或执行中的问题；快速对话与科研智能体合计最多同时处理3个，请等待完成或停止一个后重试",
            409,
        )
    if active.count() >= GLOBAL_RUN_LIMIT:
        raise ComputeError("当前平台处理队列已满，请稍后重试", 429)
