"""A stale schema must be visible instead of silently masquerading as queue load."""

from unittest.mock import Mock

import pytest
from django.db import OperationalError

from apps.agent import worker
from apps.agent.models import AgentRuntime

pytestmark = pytest.mark.django_db


def setup_loop(monkeypatch, failure):
    monkeypatch.setattr(worker, "close_old_connections", lambda: None)
    monkeypatch.setattr(worker, "recover", lambda: None)
    monkeypatch.setattr(worker, "claim", lambda: None)
    monkeypatch.setattr(worker, "registry", lambda: {})
    monkeypatch.setattr("apps.agent.interactions.resume_compute", lambda: None)
    resume = Mock(side_effect=failure)
    monkeypatch.setattr("apps.agent.compute_tools.resume_followups", resume)
    return resume


def test_missing_schema_is_reported_and_not_swallowed(monkeypatch):
    resume = setup_loop(
        monkeypatch, OperationalError("no such column: agent_agentrun.interaction")
    )
    with pytest.raises(OperationalError, match="no such column"):
        worker.serve(once=True)
    assert resume.call_count == 1
    assert not AgentRuntime.objects.filter(name="worker").exists()


def test_temporary_sqlite_lock_is_retried_before_real_heartbeat(monkeypatch):
    resume = setup_loop(monkeypatch, [OperationalError("database is locked"), None])
    worker.serve(once=True)
    assert resume.call_count == 2
    assert AgentRuntime.objects.filter(name="worker", heartbeat__isnull=False).exists()
