"""A worker heartbeat must not break the first model activity save in WAL."""

# ruff: noqa: F811

from copy import deepcopy
import json
import sqlite3
from unittest.mock import Mock

import pytest
from django.db import connection, connections

from apps.agent.config import registry
from apps.agent.model_activity import WorkflowModelActivity
from apps.agent.models import RunEvent
from apps.agent.policy import default_policy
from apps.agent.workflow_model_events import EVENT_KIND
from apps.business_flows.state import parent_run
from apps.projects.context import project_scope
from tests.integration.test_business_flow_legacy import legacy_flow  # noqa: F401
from tests.integration.test_agent import setup_agent  # noqa: F401


@pytest.mark.django_db(transaction=True)
def test_model_activity_reserves_writer_before_allocating_step(legacy_flow, tmp_path):
    workflow = legacy_flow["create"]()
    wrapper = connections["default"]
    assert not wrapper.in_atomic_block
    original_connection = wrapper.connection
    db_path = tmp_path / "activity.sqlite3"
    with sqlite3.connect(db_path) as clone:
        original_connection.backup(clone)
        assert clone.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    original = wrapper.settings_dict
    candidate = deepcopy(original)
    candidate.update(NAME=str(db_path), OPTIONS={"timeout": 1})
    wrapper.connection = None
    wrapper.settings_dict = candidate
    observed = []

    def concurrent_heartbeat(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if (
            not observed
            and sql.lstrip().upper().startswith("SELECT COUNT(*)")
            and 'FROM "agent_agentworkflowstep"' in sql
        ):
            with sqlite3.connect(db_path, timeout=0) as worker:
                try:
                    worker.execute(
                        "UPDATE agent_agentworkflow SET heartbeat = CURRENT_TIMESTAMP"
                    )
                    worker.commit()
                    observed.append("committed during sequence read")
                except sqlite3.OperationalError as exc:
                    assert exc.sqlite_errorcode == sqlite3.SQLITE_BUSY
                    observed.append("waited for activity transaction")
        return result

    try:
        with project_scope(legacy_flow["scope"]):
            activity = WorkflowModelActivity(
                workflow, "整理报告与成果", registry()["mock"], default_policy(), Mock()
            )
            with connection.execute_wrapper(concurrent_heartbeat):
                activity.progress({"status": "requesting", "attempt": 1})
            assert observed == ["waited for activity transaction"]
            step = workflow.steps.get(kind="model_activity")
            event = RunEvent.objects.get(run=parent_run(workflow), kind=EVENT_KIND)
            assert json.loads(event.text)["sequence"] == step.pk
        with sqlite3.connect(db_path, timeout=0) as worker:
            worker.execute(
                "UPDATE agent_agentworkflow SET heartbeat = CURRENT_TIMESTAMP"
            )
    finally:
        wrapper.close()
        wrapper.settings_dict = original
        wrapper.connection = original_connection
