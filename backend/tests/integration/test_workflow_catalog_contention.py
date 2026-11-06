"""File-backed WAL interleaving while adding task-scoped catalog references."""

import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import sqlite3
import threading

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import OperationalError, connection, connections
from django.test import RequestFactory
from django.utils import timezone

from apps.agent.models import AgentPolicy, AgentRuntime, WorkflowUpload
from apps.agent.views import workflow_catalog_references
from apps.projects.models import ProjectMembership
from tests.integration.test_workflow_catalog_references import catalog_entry

pytest_plugins = ["tests.integration.test_geology_generic_workflow"]


@pytest.fixture
def wal_catalog(generic, tmp_path):
    """Clone only the isolated pytest database into a temporary WAL file."""
    env = {**generic, "catalog": [catalog_entry(generic), catalog_entry(generic)]}
    AgentRuntime.objects.create(name="catalog-worker", heartbeat=timezone.now())
    connection.ensure_connection()
    assert not connection.in_atomic_block
    wrapper = connections["default"]
    original_connection = wrapper.connection
    filename = tmp_path / "catalog-contention.sqlite"
    with closing(sqlite3.connect(filename)) as target:
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
    env["database"] = filename
    try:
        yield env
    finally:
        wrapper.close()
        connections.settings["default"] = original
        wrapper.settings_dict = original
        wrapper.connection = original_connection


def reference(env, resource_ids=None):
    request = RequestFactory().post(
        "/api/agent/workflow-uploads/references/",
        json.dumps(
            {
                "batchId": env["batch"],
                "resourceIds": resource_ids
                if resource_ids is not None
                else [item.id for item in env["catalog"]],
            }
        ),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )
    request.user = get_user_model().objects.get(pk=env["owner"].id)
    return workflow_catalog_references(request)


@pytest.mark.parametrize("reserve_writer", [False, True])
@pytest.mark.django_db(transaction=True)
def test_catalog_reference_reserves_writer_before_permission_reads(
    wal_catalog, reserve_writer
):
    env = wal_catalog
    observed = {}
    attempted, resume = threading.Event(), threading.Event()

    def heartbeat():
        with closing(sqlite3.connect(env["database"], timeout=0)) as worker:
            try:
                worker.execute(
                    "UPDATE agent_agentruntime SET heartbeat=? WHERE name='catalog-worker'",
                    (timezone.now().isoformat(),),
                )
                worker.commit()
                observed["blockedBeforeReference"] = False
            except sqlite3.OperationalError as exc:
                observed["blockedBeforeReference"] = True
                observed["heartbeatSQLiteCode"] = exc.sqlite_errorcode
                assert exc.sqlite_errorcode == sqlite3.SQLITE_BUSY
                worker.rollback()
            finally:
                attempted.set()
            assert resume.wait(5)
            worker.execute("PRAGMA busy_timeout=3000")
            worker.execute(
                "UPDATE agent_agentruntime SET heartbeat=? WHERE name='catalog-worker'",
                (timezone.now().isoformat(),),
            )
            worker.commit()
            observed["eventuallyCommitted"] = True

    future = None

    def after_first_permission_read(execute, sql, params, many, context):
        nonlocal future
        if (
            not reserve_writer
            and sql.lstrip().upper().startswith("UPDATE")
            and '"last_login" = "auth_user"."last_login"' in sql
        ):
            # Negative control: retain the real reads and inserts without a reservation.
            return None
        try:
            result = execute(sql, params, many, context)
        except OperationalError as exc:
            observed["referenceSQLiteCode"] = getattr(
                exc.__cause__, "sqlite_errorcode", None
            )
            raise
        if (
            future is None
            and connection.in_atomic_block
            and sql.lstrip().upper().startswith("SELECT")
        ):
            future = executor.submit(heartbeat)
            assert attempted.wait(5)
        return result

    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            with connection.execute_wrapper(after_first_permission_read):
                response = reference(env)
        finally:
            resume.set()
            if future:
                future.result(timeout=5)
    assert response.status_code == (200 if reserve_writer else 503), (
        response.content,
        observed,
    )
    assert observed["blockedBeforeReference"] is reserve_writer
    if not reserve_writer:
        assert observed["referenceSQLiteCode"] == sqlite3.SQLITE_BUSY_SNAPSHOT
    assert observed["eventuallyCommitted"] is True
    assert WorkflowUpload.objects.filter(batch_id=env["batch"]).count() == (
        len(env["catalog"]) if reserve_writer else 0
    )
    if reserve_writer:
        initial = json.loads(response.content)["items"]
        repeated = reference(env)
        assert repeated.status_code == 200
        assert json.loads(repeated.content)["items"] == initial


@pytest.mark.parametrize("denied", ["permission", "membership", "operator"])
@pytest.mark.django_db(transaction=True)
def test_writer_reservation_keeps_permission_denials_atomic(wal_catalog, denied):
    env = wal_catalog
    if denied == "permission":
        env["owner"].user_permissions.remove(
            Permission.objects.get(
                content_type__app_label="catalog", codename="add_dataresource"
            )
        )
    elif denied == "membership":
        ProjectMembership.objects.filter(
            project=env["project"], user=env["owner"]
        ).delete()
    else:
        policy = AgentPolicy.objects.get(pk=1)
        policy.value["operatorEnabled"] = False
        policy.save(update_fields=["value"])
    original = get_user_model().objects.filter(pk=env["owner"].pk).values().get()
    response = reference(env)
    assert response.status_code == 403, response.content
    assert not WorkflowUpload.objects.filter(batch_id=env["batch"]).exists()
    assert (
        get_user_model().objects.filter(pk=env["owner"].pk).values().get() == original
    )


@pytest.mark.django_db(transaction=True)
def test_catalog_profile_failure_rolls_back_earlier_reference(wal_catalog):
    env = wal_catalog
    broken = env["catalog"][1]
    broken.storage_path = "missing-layer"
    broken.save(update_fields=["storage_path"])
    original = get_user_model().objects.filter(pk=env["owner"].pk).values().get()
    response = reference(env)
    assert response.status_code == 400, response.content
    assert "资料画像" in json.loads(response.content)["detail"]
    assert not WorkflowUpload.objects.filter(batch_id=env["batch"]).exists()
    assert (
        get_user_model().objects.filter(pk=env["owner"].pk).values().get() == original
    )
