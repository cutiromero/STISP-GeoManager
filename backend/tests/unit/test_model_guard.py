"""Polling stays bounded without weakening cancellation, revocation or deadlines."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

from django.core.exceptions import PermissionDenied
import pytest

from apps.agent.model_guard import ModelStreamGuard
from apps.agent.provider import ModelError
from apps.agent.workflow_controls import WorkflowPaused

pytestmark = pytest.mark.unit


def test_many_stream_fragments_share_one_poll_and_refresh_at_next_interval():
    now = [0.0]
    authorize = Mock()
    guard = ModelStreamGuard(authorize, 10, clock=lambda: now[0])
    for _ in range(1000):
        guard()
    assert authorize.call_count == 1
    now[0] = 0.499
    guard()
    assert authorize.call_count == 1
    now[0] = 0.5
    guard()
    assert authorize.call_count == 2


def test_monitor_and_stream_threads_do_not_duplicate_a_full_poll():
    entered, release = Event(), Event()
    calls = []

    def authorize():
        calls.append(True)
        entered.set()
        assert release.wait(2)

    guard = ModelStreamGuard(authorize, 10, clock=lambda: 0)
    with ThreadPoolExecutor(max_workers=8) as pool:
        first = pool.submit(guard)
        assert entered.wait(2)
        others = [pool.submit(guard) for _ in range(7)]
        release.set()
        first.result(timeout=2)
        for future in others:
            future.result(timeout=2)
    assert len(calls) == 1


def test_watchdog_forces_live_check_when_stream_poll_is_out_of_phase():
    now, revoked = [0.0], [False]

    def authorize():
        if revoked[0]:
            raise PermissionDenied("权限已撤回")

    guard = ModelStreamGuard(authorize, 10, clock=lambda: now[0])
    guard()
    # A stream poll just after the watchdog starts shifts the cache window.
    now[0] = 0.5
    guard()
    revoked[0] = True
    now[0] = 0.95
    guard()
    with pytest.raises(PermissionDenied, match="权限已撤回"):
        guard.poll()


def test_forced_boundary_checks_do_not_reuse_a_successful_fragment_poll():
    authorize = Mock()
    guard = ModelStreamGuard(authorize, 10, clock=lambda: 0)
    guard()
    guard.poll()
    guard()
    assert authorize.call_count == 2


def test_watchdog_failure_is_shared_with_a_concurrent_stream_fragment():
    entered, release = Event(), Event()
    failure = PermissionDenied("知识依据已变化")
    revoked = [False]

    def authorize():
        if revoked[0]:
            entered.set()
            assert release.wait(2)
            raise failure

    guard = ModelStreamGuard(authorize, 10, clock=lambda: 0)
    guard()
    revoked[0] = True
    with ThreadPoolExecutor(max_workers=2) as pool:
        watchdog = pool.submit(guard.poll)
        assert entered.wait(2)
        fragment = pool.submit(guard)
        release.set()
        for future in (watchdog, fragment):
            with pytest.raises(PermissionDenied) as caught:
                future.result(timeout=2)
            assert caught.value is failure


def test_deadline_is_rechecked_after_waiting_for_another_poll():
    now = [0.0]
    entered, release = Event(), Event()

    def authorize():
        entered.set()
        assert release.wait(2)

    guard = ModelStreamGuard(authorize, 1, clock=lambda: now[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(guard)
        assert entered.wait(2)
        second = pool.submit(guard)
        now[0] = 2
        release.set()
        for future in (first, second):
            with pytest.raises(ModelError, match="时限"):
                future.result(timeout=2)


@pytest.mark.parametrize(
    "failure",
    [WorkflowPaused(), ModelError("任务已取消"), PermissionDenied("权限已撤回")],
)
def test_pause_cancel_and_revocation_are_observed_at_next_poll(failure):
    now, control = [0.0], [False]
    calls = []

    def authorize():
        calls.append(True)
        if control[0]:
            raise failure

    guard = ModelStreamGuard(authorize, 10, clock=lambda: now[0])
    guard()
    control[0] = True
    now[0] = 0.5
    with pytest.raises(type(failure)) as caught:
        guard()
    assert caught.value is failure
    with pytest.raises(type(failure)):
        guard()
    assert len(calls) == 2


def test_deadline_is_checked_for_every_cached_fragment_and_after_poll():
    now = [0.0]
    authorize = Mock()
    guard = ModelStreamGuard(authorize, 0.1, clock=lambda: now[0])
    guard()
    now[0] = 0.11
    with pytest.raises(ModelError, match="时限"):
        guard()
    assert authorize.call_count == 1

    def slow_authorize():
        now[0] = 2

    now[0] = 0
    guard = ModelStreamGuard(slow_authorize, 1, clock=lambda: now[0])
    with pytest.raises(ModelError, match="时限"):
        guard()


@pytest.mark.parametrize("interval", [0, -0.1, 0.501])
def test_poll_interval_cannot_exceed_existing_watchdog_cadence(interval):
    with pytest.raises(ValueError):
        ModelStreamGuard(lambda: None, 10, interval=interval)
