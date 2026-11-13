"""Real WAL writers must not invalidate the browser renewal read snapshot."""

# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.db import close_old_connections, connection
from django.test import RequestFactory
from django.utils import timezone

from apps.core.browser_sessions import (
    SESSION_KEY,
    browser_session_view,
    prepare_browser_session,
)
from tests.integration.test_agent import setup_agent  # noqa: F401
from tests.integration.test_workflow_submit_contention import wal_workflows  # noqa: F401


def browser_request(env, store, action, page, token, sequence=1):
    request = RequestFactory().post(
        "/api/auth/browser-session/",
        json.dumps(dict(action=action, pageId=page, token=token, sequence=sequence)),
        content_type="application/json",
    )
    request.user = env["user"]
    request.session = SessionStore(session_key=store.session_key)
    return request


def browser_session(env):
    store = SessionStore()
    request = RequestFactory().get("/")
    request.session = store
    prepare_browser_session(request)
    store.save()
    assert (
        browser_session_view(
            browser_request(
                env,
                store,
                "start",
                "initial_page_12345678",
                "a" * 64,
            )
        ).status_code
        == 200
    )
    return store


@pytest.mark.django_db(transaction=True)
@pytest.mark.efficiency
@pytest.mark.parametrize("reserve_writer", [False, True])
def test_worker_progress_does_not_invalidate_session_renewal_snapshot(
    wal_workflows, reserve_writer
):
    env = wal_workflows
    store = browser_session(env)
    attempted, resume = threading.Event(), threading.Event()
    observed = {}
    thread = None

    def worker_write():
        with sqlite3.connect(env["database"], timeout=0) as writer:
            try:
                writer.execute(
                    "UPDATE agent_agentruntime SET heartbeat=? WHERE name='workflow-worker'",
                    (timezone.now().isoformat(),),
                )
                writer.commit()
                observed["blocked"] = False
            except sqlite3.OperationalError as error:
                assert error.sqlite_errorcode == sqlite3.SQLITE_BUSY
                observed["blocked"] = True
                writer.rollback()
            finally:
                attempted.set()
            assert resume.wait(5)

    def after_read(execute, sql, params, many, context):
        nonlocal thread
        if (
            not reserve_writer
            and sql.lstrip().upper().startswith("UPDATE")
            and '"session_data" = "django_session"."session_data"' in sql
        ):
            return None
        try:
            result = execute(sql, params, many, context)
        except Exception as error:
            observed["snapshotError"] = getattr(
                error.__cause__, "sqlite_errorcode", None
            )
            raise
        if (
            thread is None
            and connection.in_atomic_block
            and sql.lstrip().upper().startswith("SELECT")
            and '"django_session"' in sql
        ):
            thread = threading.Thread(target=worker_write)
            thread.start()
            assert attempted.wait(5)
        return result

    try:
        with connection.execute_wrapper(after_read):
            response = browser_session_view(
                browser_request(
                    env,
                    store,
                    "heartbeat",
                    "initial_page_12345678",
                    "a" * 64,
                    2,
                )
            )
    finally:
        resume.set()
        if thread:
            thread.join(5)
            assert not thread.is_alive()
    assert response.status_code == 200
    assert observed["blocked"] is reserve_writer
    if reserve_writer:
        assert "snapshotError" not in observed
    else:
        assert observed["snapshotError"] == sqlite3.SQLITE_BUSY_SNAPSHOT
    state = SessionStore(session_key=store.session_key)[SESSION_KEY]
    assert state["pages"]["initial_page_12345678"]["sequence"] == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.efficiency
def test_two_real_browser_tabs_preserve_each_others_session_lease(wal_workflows):
    env = wal_workflows
    store = browser_session(env)
    barrier = threading.Barrier(2)

    def join(index):
        close_old_connections()
        try:
            request = browser_request(
                env, store, "join", f"another_page_{index}_12345678", str(index) * 64
            )
            barrier.wait(timeout=5)
            return browser_session_view(request).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(join, [1, 2])) == [200, 200]
    state = SessionStore(session_key=store.session_key)[SESSION_KEY]
    assert set(state["pages"]) == {
        "initial_page_12345678",
        "another_page_1_12345678",
        "another_page_2_12345678",
    }
    assert "a" * 64 not in json.dumps(state)
