"""Concurrent sends and responses against an isolated file-backed WAL database."""

# ruff: noqa: F811

import copy
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import RequestFactory

from apps.catalog import sharing
from apps.catalog.models import ShareInvitation
from apps.catalog.share_access import actor_scope
from tests.integration.catalog.test_sharing import env  # noqa: F401


@pytest.fixture
def wal_shares(env, tmp_path):
    connection.ensure_connection()
    assert not connection.in_atomic_block
    wrapper = connections["default"]
    original_connection = wrapper.connection
    filename = tmp_path / "sharing-contention.sqlite"
    with sqlite3.connect(filename) as target:
        original_connection.backup(target)
        target.execute("PRAGMA journal_mode=WAL")
    original = connections.settings["default"]
    candidate = copy.deepcopy(original)
    candidate.update(
        NAME=str(filename),
        OPTIONS={
            "timeout": 10,
            "init_command": "PRAGMA journal_mode=WAL;PRAGMA busy_timeout=10000",
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


def call(env, view, body, actor=0, invitation=None):
    request = RequestFactory().post(
        "/api/sharing/invitations/", json.dumps(body), content_type="application/json"
    )
    request.user = get_user_model().objects.get(
        pk=env["owner" if actor == 0 else "recipient"].id
    )
    with actor_scope(request.user, env["project"].id):
        return view(request, invitation) if invitation else view(request)


@pytest.mark.django_db(transaction=True)
def test_simultaneous_same_object_sends_create_one_notification(wal_shares):
    data = wal_shares
    barrier = threading.Barrier(3)

    def run(index):
        try:
            barrier.wait(timeout=10)
            response = call(
                data,
                sharing.invitations,
                {
                    "kind": "workspace",
                    "objectId": data["scene"].id,
                    "username": data["recipient"].username,
                    "idempotencyKey": f"concurrent-{index}",
                },
            )
            return response.status_code, json.loads(response.content)["id"]
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=3) as pool:
        values = list(pool.map(run, range(3)))
    assert sorted(value[0] for value in values) == [200, 200, 201]
    assert len({value[1] for value in values}) == 1
    assert ShareInvitation._base_manager.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_opposite_responses_save_one_decision(wal_shares):
    data = wal_shares
    response = call(
        data,
        sharing.invitations,
        {
            "kind": "workspace",
            "objectId": data["scene"].id,
            "username": data["recipient"].username,
            "idempotencyKey": "opposite-send",
        },
    )
    invitation = json.loads(response.content)["id"]
    barrier = threading.Barrier(2)

    def run(decision):
        try:
            barrier.wait(timeout=10)
            return call(
                data,
                sharing.respond,
                {"decision": decision, "idempotencyKey": decision},
                actor=1,
                invitation=invitation,
            ).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(run, ("accept", "reject")))
    assert sorted(statuses) == [200, 409]
    saved = ShareInvitation._base_manager.get(pk=invitation)
    assert saved.status in {"accepted", "rejected"}
    assert (
        saved.response_decision
        == {"accepted": "accept", "rejected": "reject"}[saved.status]
    )
