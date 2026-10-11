"""Actual file-backed WAL contention at workflow creation and idempotency."""

# ruff: noqa: F811
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import RequestFactory
from django.utils import timezone

from apps.agent.models import AgentRuntime, AgentWorkflow
from apps.agent.views import workflow_submit
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401


@pytest.fixture
def wal_workflows(setup_agent, tmp_path):
    """Clone the isolated pytest DB; never use application business storage."""
    env = setup_agent
    AgentRuntime.objects.create(name="workflow-worker", heartbeat=timezone.now())
    connection.ensure_connection()
    assert not connection.in_atomic_block
    wrapper = connections["default"]
    original_connection = wrapper.connection
    filename = tmp_path / "workflow-contention.sqlite"
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
    # Keep the original in-memory pytest connection alive while using its clone.
    wrapper.connection = None
    connections.settings["default"] = candidate
    wrapper.settings_dict = candidate
    env["database"] = filename
    try:
        yield env
    finally:
        wrapper.close()
        connections.settings["default"] = original
        wrapper.settings_dict = original
        wrapper.connection = original_connection


def submit(env, key="wal-workflow-key-01"):
    request = RequestFactory().post(
        "/api/agent/workflows/",
        json.dumps(
            {
                "workflowType": "hyperspectral_interpretation",
                "goal": "真实并发创建核验",
                "model": "mock",
                "resourceIds": [env["resource"].id],
                "parameters": {},
                "idempotencyKey": key,
            }
        ),
        content_type="application/json",
        **env["header"],
    )
    request.user = get_user_model().objects.get(pk=env["user"].id)
    with project_scope(env["scope"]):
        return workflow_submit(request)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("reserve_writer", [False, True])
def test_worker_heartbeat_cannot_invalidate_creation_read_snapshot(
    wal_workflows, reserve_writer
):
    env = wal_workflows
    observed = {}
    attempted, resume = threading.Event(), threading.Event()

    def heartbeat():
        with sqlite3.connect(env["database"], timeout=0) as worker:
            try:
                worker.execute(
                    "UPDATE agent_agentruntime SET heartbeat=? WHERE name='workflow-worker'",
                    (timezone.now().isoformat(),),
                )
                worker.commit()
                observed["blockedBeforeCreate"] = False
            except sqlite3.OperationalError as exc:
                observed["blockedBeforeCreate"] = True
                observed["sqliteCode"] = exc.sqlite_errorcode
                assert exc.sqlite_errorcode == sqlite3.SQLITE_BUSY
                worker.rollback()
            finally:
                attempted.set()
            assert resume.wait(5)
            worker.execute("PRAGMA busy_timeout=3000")
            worker.execute(
                "UPDATE agent_agentruntime SET heartbeat=? WHERE name='workflow-worker'",
                (timezone.now().isoformat(),),
            )
            worker.commit()
            observed["eventuallyCommitted"] = True

    thread = None

    def after_first_workflow_read(execute, sql, params, many, context):
        nonlocal thread
        if (
            not reserve_writer
            and sql.lstrip().upper().startswith("UPDATE")
            and '"idempotency_key" = "agent_agentworkflow"."idempotency_key"' in sql
        ):
            # Reproduce the old read-first transaction, keeping all real SQL.
            return None
        try:
            result = execute(sql, params, many, context)
        except Exception as exc:
            observed["submitSQLiteCode"] = getattr(
                exc.__cause__, "sqlite_errorcode", None
            )
            raise
        if (
            thread is None
            and connection.in_atomic_block
            and sql.lstrip().upper().startswith("SELECT")
            and '"agent_agentworkflow"' in sql
        ):
            thread = threading.Thread(target=heartbeat)
            thread.start()
            assert attempted.wait(5)
        return result

    try:
        with connection.execute_wrapper(after_first_workflow_read):
            response = submit(env)
    finally:
        resume.set()
        if thread:
            thread.join(5)
            assert not thread.is_alive()
    assert response.status_code == (202 if reserve_writer else 503), response.content
    assert observed["blockedBeforeCreate"] is reserve_writer
    if not reserve_writer:
        assert observed["submitSQLiteCode"] == sqlite3.SQLITE_BUSY_SNAPSHOT
    assert observed["eventuallyCommitted"] is True
    assert AgentWorkflow.objects.count() == int(reserve_writer)


@pytest.mark.parametrize("same_key", [True, False])
@pytest.mark.django_db(transaction=True)
def test_simultaneous_requests_keep_idempotency_and_one_active_workflow(
    wal_workflows, same_key
):
    env = wal_workflows
    barrier = threading.Barrier(2)

    def concurrent(index):
        try:
            barrier.wait(5)
            response = submit(
                env, "wal-same-request" if same_key else "wal-new-request-" + str(index)
            )
            return response.status_code, json.loads(response.content)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(concurrent, index) for index in range(2)]
        results = [future.result(timeout=10) for future in futures]
    statuses = sorted(status for status, _ in results)
    assert statuses == ([202, 202] if same_key else [202, 409]), results
    if same_key:
        assert results[0][1]["id"] == results[1][1]["id"]
        before = AgentWorkflow.objects.values().get()
        repeated = submit(env, "wal-same-request")
        assert repeated.status_code == 202
        assert AgentWorkflow.objects.values().get() == before
    assert AgentWorkflow.objects.count() == 1
