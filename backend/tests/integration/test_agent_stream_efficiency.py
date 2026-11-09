"""Real response iteration: early chunks, bounded slots, recovery and revocation."""

# ruff: noqa: F811

import json
from uuid import uuid4
from unittest.mock import patch

import pytest
from django.contrib.sessions.models import Session

from apps.agent import run_stream
from apps.agent.models import AgentRun, RunEvent
from apps.catalog.models import DataResource
from apps.projects.context import project_scope
from apps.projects.models import ProjectMembership
from tests.integration.test_agent import setup_agent  # noqa: F401

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.efficiency]


def create(env, **values):
    with project_scope(env["scope"]):
        return AgentRun.objects.create(
            owner=env["user"],
            conversation=env["conversation"],
            model="mock",
            prompt="核查资料",
            status="running",
            idempotency_key=uuid4().hex,
            **values,
        )


def connect(env, run):
    return env["client"].get(f"/api/agent/runs/{run.id}/stream/", **env["header"])


def decode(chunk):
    lines = chunk.decode().splitlines()
    event = next(line[7:] for line in lines if line.startswith("event: "))
    data = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
    return event, data


@pytest.fixture(autouse=True)
def immediate(monkeypatch):
    monkeypatch.setattr(run_stream, "POLL_SECONDS", 0)
    monkeypatch.setattr(run_stream, "AUTH_SECONDS", 0)


def test_partial_text_arrives_while_task_is_running_without_full_snapshot_per_chunk(
    setup_agent,
):
    env = setup_agent
    run = create(env)
    with patch.object(run_stream, "snapshot", wraps=run_stream.snapshot) as snapshots:
        response = connect(env, run)
        assert response.status_code == 200 and response.streaming
        assert (
            response["Content-Encoding"] == "identity"
            and response["X-Accel-Buffering"] == "no"
        )
        chunks = iter(response.streaming_content)
        kind, initial = decode(next(chunks))
        assert kind == "snapshot" and initial["run"]["status"] == "running"
        RunEvent.objects.create(run=run, kind="thinking", text="真实思考片段")
        kind, thinking = decode(next(chunks))
        assert kind == "progress" and thinking["events"][0]["text"] == "真实思考片段"
        RunEvent.objects.create(run=run, kind="answer_preview", text="正文开头")
        RunEvent.objects.create(run=run, kind="answer_delta", text="，继续回答")
        kind, answer = decode(next(chunks))
        assert kind == "progress" and answer["fromCursor"] == thinking["cursor"]
        assert [item["text"] for item in answer["events"]] == ["正文开头", "，继续回答"]
        assert snapshots.call_count == 1
        with project_scope(env["scope"]):
            run.status = "succeeded"
            run.answer = "核验后的完整回答"
            run.save(update_fields=["status", "answer", "updated_at"])
        kind, final = decode(next(chunks))
        assert (
            kind == "snapshot"
            and final["run"]["answer"] == "核验后的完整回答"
            and final["run"]["answerPreview"] == ""
        )
        assert decode(next(chunks)) == ("end", {"reason": "settled"})
        assert snapshots.call_count == 2
        response.close()


def test_reconnect_starts_with_exact_complete_preview_and_new_high_water_mark(
    setup_agent,
):
    env = setup_agent
    run = create(env)
    RunEvent.objects.create(run=run, kind="answer_preview", text="第一段")
    RunEvent.objects.create(run=run, kind="answer_delta", text="第二段")
    first = connect(env, run)
    kind, value = decode(next(iter(first.streaming_content)))
    assert value["run"]["answerPreview"] == "第一段第二段"
    first.close()
    event = RunEvent.objects.create(run=run, kind="answer_delta", text="第三段")
    second = connect(env, run)
    kind, value = decode(next(iter(second.streaming_content)))
    assert (
        value["run"]["answerPreview"] == "第一段第二段第三段"
        and value["cursor"] == event.id
    )
    second.close()
    assert RunEvent.objects.filter(run=run).count() == 3


@pytest.mark.parametrize("change", ["project", "resource", "logout"])
def test_open_connection_rechecks_access_before_sending_new_private_text(
    setup_agent, change
):
    env = setup_agent
    run = create(
        env,
        evidence=[
            {
                "id": 1,
                "tool": "describe_resource",
                "resourceId": env["resource"].id,
                "result": {},
            }
        ],
    )
    response = connect(env, run)
    chunks = iter(response.streaming_content)
    assert decode(next(chunks))[0] == "snapshot"
    if change == "project":
        ProjectMembership.objects.filter(
            project=env["project"], user=env["user"]
        ).delete()
    elif change == "resource":
        with project_scope(env["scope"]):
            DataResource.objects.filter(pk=env["resource"].id).update(
                owner_only=True, maintainer=env["other"]
            )
    else:
        Session.objects.filter(session_key=env["client"].session.session_key).delete()
    RunEvent.objects.create(run=run, kind="answer_delta", text="REVOKED_PRIVATE_TEXT")
    kind, value = decode(next(chunks))
    assert kind == "error" and value["status"] == (401 if change == "logout" else 403)
    assert "REVOKED_PRIVATE_TEXT" not in json.dumps(value)
    response.close()


def test_stream_slots_are_bounded_and_closing_unstarted_response_releases_slot(
    setup_agent,
):
    env = setup_agent
    run = create(env)
    responses = []
    try:
        for _ in range(run_stream.MAX_STREAMS):
            response = connect(env, run)
            assert response.status_code == 200
            responses.append(response)
        with patch.object(
            run_stream, "snapshot", wraps=run_stream.snapshot
        ) as snapshots:
            busy = connect(env, run)
            assert busy.status_code == 503 and busy["Retry-After"] == "5"
            assert snapshots.call_count == 0
        responses.pop().close()
        replacement = connect(env, run)
        assert replacement.status_code == 200
        responses.append(replacement)
    finally:
        for response in responses:
            response.close()


def test_owner_and_project_are_checked_before_opening_stream(setup_agent):
    env = setup_agent
    run = create(env)
    with project_scope(env["scope"]):
        AgentRun.objects.filter(pk=run.pk).update(owner=env["other"])
    response = connect(env, run)
    assert response.status_code == 404 and not response.streaming
