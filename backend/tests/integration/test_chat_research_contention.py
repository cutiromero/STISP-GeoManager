"""File-backed WAL interleaving of chat startup and the real heartbeat write."""

# ruff: noqa: F811
import copy
import sqlite3
import threading

import pytest
from django.db import OperationalError, connection, connections
from django.utils import timezone

from apps.agent.models import AgentRuntime, AgentWorkflow
from tests.integration.test_chat_research_intent import bridge, parsed, run
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401


@pytest.fixture
def wal_research(demo, tmp_path):
    AgentRuntime.objects.create(name="worker", heartbeat=timezone.now())
    connection.ensure_connection()
    assert not connection.in_atomic_block
    wrapper = connections["default"]
    original_connection = wrapper.connection
    filename = tmp_path / "chat-research-contention.sqlite"
    with sqlite3.connect(filename) as target:
        original_connection.backup(target)
        assert target.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    original = connections.settings["default"]
    candidate = copy.deepcopy(original)
    candidate.update(
        NAME=str(filename),
        OPTIONS={
            "timeout": 3,
            "init_command": "PRAGMA journal_mode=WAL;PRAGMA busy_timeout=3000",
        },
    )
    wrapper.connection = None
    connections.settings["default"] = candidate
    wrapper.settings_dict = candidate
    demo["database"] = filename
    try:
        yield demo
    finally:
        wrapper.close()
        connections.settings["default"] = original
        wrapper.settings_dict = original
        wrapper.connection = original_connection


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("reserve_writer", [False, True])
def test_chat_startup_reserves_writer_before_nested_permission_reads(
    wal_research, reserve_writer
):
    env = wal_research
    item = run(env)
    original_key = item.idempotency_key
    observed = {}
    attempted, resume = threading.Event(), threading.Event()

    def heartbeat():
        with sqlite3.connect(env["database"], timeout=0) as worker:
            try:
                worker.execute(
                    "UPDATE agent_agentruntime SET heartbeat=? WHERE name='worker'",
                    (timezone.now().isoformat(),),
                )
                worker.commit()
                observed["blockedBeforeCreate"] = False
            except sqlite3.OperationalError as exc:
                observed["blockedBeforeCreate"] = True
                observed["heartbeatSQLiteCode"] = exc.sqlite_errorcode
                worker.rollback()
            finally:
                attempted.set()
            assert resume.wait(5)
            worker.execute("PRAGMA busy_timeout=3000")
            worker.execute(
                "UPDATE agent_agentruntime SET heartbeat=? WHERE name='worker'",
                (timezone.now().isoformat(),),
            )
            worker.commit()
            observed["eventuallyCommitted"] = True

    thread = None

    def after_first_permission_read(execute, sql, params, many, context):
        nonlocal thread
        if (
            not reserve_writer
            and sql.lstrip().upper().startswith("UPDATE")
            and '"idempotency_key" = "agent_agentrun"."idempotency_key"' in sql
        ):
            # Only omit the new outer reservation; retain real nested SQL.
            return None
        try:
            result = execute(sql, params, many, context)
        except OperationalError as exc:
            observed["startupSQLiteCode"] = getattr(
                exc.__cause__, "sqlite_errorcode", None
            )
            raise
        if (
            thread is None
            and connection.in_atomic_block
            and sql.lstrip().upper().startswith("SELECT")
        ):
            thread = threading.Thread(target=heartbeat)
            thread.start()
            assert attempted.wait(5)
        return result

    try:
        with connection.execute_wrapper(after_first_permission_read):
            if reserve_writer:
                assert "已开始" in bridge(env, item, parsed(env))
            else:
                with pytest.raises(OperationalError):
                    bridge(env, item, parsed(env))
    finally:
        resume.set()
        if thread:
            thread.join(5)
            assert not thread.is_alive()
    assert thread is not None
    assert observed["blockedBeforeCreate"] is reserve_writer
    if reserve_writer:
        assert observed["heartbeatSQLiteCode"] == sqlite3.SQLITE_BUSY
    else:
        assert observed["startupSQLiteCode"] == sqlite3.SQLITE_BUSY_SNAPSHOT
    assert observed["eventuallyCommitted"] is True
    item.refresh_from_db()
    assert item.idempotency_key == original_key
    assert bool(item.research_workflow_id) is reserve_writer
    assert AgentWorkflow.objects.count() == int(reserve_writer)
    if reserve_writer:
        workflow_id = item.research_workflow_id
        assert item.research_intent["workflowId"] == str(workflow_id)
        bridge(env, item, parsed(env))
        item.refresh_from_db()
        assert item.research_workflow_id == workflow_id
        assert AgentWorkflow.objects.count() == 1
