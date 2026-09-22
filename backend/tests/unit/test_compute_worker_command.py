import sqlite3
from unittest.mock import Mock, call

from django.db import OperationalError
import pytest

from apps.compute.management.commands import compute_worker


def database_error(code):
    cause = sqlite3.OperationalError("database busy")
    cause.sqlite_errorcode = code
    error = OperationalError(str(cause))
    error.__cause__ = cause
    return error


@pytest.fixture
def command_env(tmp_path, monkeypatch):
    monkeypatch.setattr(
        compute_worker, "app_path", lambda *parts: tmp_path.joinpath(*parts)
    )
    monkeypatch.setattr(compute_worker.threading, "Thread", Mock())
    monkeypatch.setattr(compute_worker, "close_old_connections", Mock())
    sleep = Mock()
    monkeypatch.setattr(compute_worker.time, "sleep", sleep)
    return sleep


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, 517])
def test_worker_recovers_after_transient_database_lock(command_env, monkeypatch, code):
    tick = Mock(side_effect=[True, database_error(code), True, KeyboardInterrupt])
    monkeypatch.setattr(compute_worker, "worker_tick", tick)

    compute_worker.Command().handle(once=False)

    assert tick.call_args_list == [
        call(recovered=False),
        call(recovered=True),
        call(recovered=False),
        call(recovered=True),
    ]
    assert command_env.call_args_list == [call(3)] * 3


@pytest.mark.parametrize(
    "once,code", [(True, sqlite3.SQLITE_BUSY), (False, sqlite3.SQLITE_IOERR)]
)
def test_worker_does_not_hide_other_database_errors(
    command_env, monkeypatch, once, code
):
    tick = Mock(side_effect=database_error(code))
    monkeypatch.setattr(compute_worker, "worker_tick", tick)

    with pytest.raises(OperationalError):
        compute_worker.Command().handle(once=once)
    command_env.assert_not_called()
