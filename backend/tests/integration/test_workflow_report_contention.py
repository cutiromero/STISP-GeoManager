"""Simultaneous report requests serialize real file creation and database import."""

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

from apps.agent.workflow_report_views import workflow_report, workflow_report_import
from apps.audit.models import OperationLog
from apps.catalog.models import DataResource
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401
from tests.integration.test_workflow_reports import completed  # noqa: F401
from tests.integration.test_workflow_reports import request as report_request


@pytest.fixture
def wal_reports(completed, tmp_path):
    env = completed
    connection.ensure_connection()
    assert not connection.in_atomic_block
    wrapper = connections["default"]
    original_connection = wrapper.connection
    filename = tmp_path / "workflow-report-contention.sqlite"
    with sqlite3.connect(filename) as target:
        original_connection.backup(target)
        assert target.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    original = connections.settings["default"]
    candidate = copy.deepcopy(original)
    candidate.update(
        NAME=str(filename),
        OPTIONS={
            "timeout": 5,
            "init_command": "PRAGMA journal_mode=WAL;PRAGMA busy_timeout=5000",
        },
    )
    wrapper.connection = None
    connections.settings["default"] = candidate
    wrapper.settings_dict = candidate
    try:
        yield env
    finally:
        wrapper.close()
        connections.settings["default"] = original
        wrapper.settings_dict = original
        wrapper.connection = original_connection


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("action", ["generate", "import"])
def test_simultaneous_generation_and_import_are_idempotent(wal_reports, action):
    env = wal_reports
    if action == "import":
        assert report_request(env).status_code == 200
    barrier = threading.Barrier(2)

    def concurrent():
        try:
            actor = get_user_model().objects.get(pk=env["owner"].id)
            request = RequestFactory().post(
                "/api/agent/workflows/report/",
                data="{}",
                content_type="application/json",
                HTTP_X_PROJECT_ID=str(env["project"].id),
            )
            request.user = actor
            scope = ProjectScope((env["project"].id,), env["project"].id, actor.id)
            barrier.wait(5)
            view = workflow_report_import if action == "import" else workflow_report
            with project_scope(scope):
                response = view(request, env["workflow"].id)
            return response.status_code, json.loads(response.content)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(concurrent) for _ in range(2)]
        responses = [future.result(timeout=20) for future in futures]
    assert [status for status, _ in responses] == [200, 200], responses
    assert responses[0][1] == responses[1][1]
    assert (
        OperationLog.objects.filter(event_code="agent.workflow_report.generate").count()
        == 1
    )
    assert DataResource.objects.filter(
        source=f"workflow-report:{env['workflow'].id}"
    ).count() == (1 if action == "import" else 0)
    assert OperationLog.objects.filter(
        event_code="agent.workflow_report.import"
    ).count() == (1 if action == "import" else 0)
