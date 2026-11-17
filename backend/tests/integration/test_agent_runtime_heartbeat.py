"""Queue leases must not upgrade read snapshots or claim the same task twice."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections
from django.db.backends.sqlite3.base import DatabaseWrapper
from django.test.utils import CaptureQueriesContext

from apps.agent import worker, workflow_worker
from apps.agent.models import AgentRuntime, AgentWorkflow, AgentRun, Conversation
from apps.agent.runtime_heartbeat import pulse

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.efficiency]


@pytest.fixture
def wal_database(tmp_path):
    # Shared in-memory SQLite uses table locks, unlike the deployed WAL database.
    target = tmp_path / "queue-wal.db"
    connection.ensure_connection()
    with sqlite3.connect(target) as backup:
        connection.connection.backup(backup)
    original = connections["default"]
    original_settings = connections.settings["default"]
    settings = {**original.settings_dict, "NAME": str(target)}
    connections.settings["default"] = settings
    connections["default"] = DatabaseWrapper(settings, alias="default")
    try:
        yield
    finally:
        connection.close()
        connections["default"] = original
        connections.settings["default"] = original_settings


def test_existing_lease_starts_with_one_write_without_read_snapshot():
    pulse("worker", detail={"status": "online"})
    with CaptureQueriesContext(connection) as queries:
        pulse("worker")
    assert len(queries) == 1
    assert queries[0]["sql"].startswith("UPDATE")
    assert AgentRuntime.objects.get(name="worker").detail == {"status": "online"}


@pytest.mark.parametrize("queue", [worker, workflow_worker])
def test_idle_claim_does_not_acquire_sqlite_writer(queue):
    with CaptureQueriesContext(connection) as queries:
        assert queue.claim() is None
    assert all(row["sql"].startswith("SELECT") for row in queries)


@pytest.mark.parametrize("queue", [worker, workflow_worker])
def test_concurrent_claims_and_heartbeats_do_not_lose_or_duplicate_work(
    monkeypatch, queue, wal_database
):
    actor = get_user_model().objects.create(username="lease_concurrency")
    if queue is worker:
        conversation = Conversation.objects.create(owner=actor)
        task = AgentRun.objects.create(
            owner=actor,
            conversation=conversation,
            model="mock",
            prompt="并发领取",
            idempotency_key="lease-task",
        )
        monkeypatch.setattr(
            worker, "policy", lambda: {"models": [{"alias": "mock", "concurrency": 3}]}
        )
    else:
        task = AgentWorkflow.objects.create(
            owner=actor, goal="并发领取", idempotency_key="lease-task"
        )
    pulse("worker")
    pulse("workflow-worker")
    barrier = threading.Barrier(2)

    def claim_and_beat(name):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            claimed = queue.claim()
            for _ in range(12):
                pulse(name)
            return claimed
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(claim_and_beat, name) for name in ("worker", "workflow-worker")
        ]
        claimed = [future.result(timeout=10) for future in futures]
    assert claimed.count(task.pk) == 1 and claimed.count(None) == 1
    task.refresh_from_db()
    assert task.status == "running"
