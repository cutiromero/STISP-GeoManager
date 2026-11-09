"""Bound agent read work without retaining authorization or progress snapshots."""

# ruff: noqa: F811

from datetime import timedelta
import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.agent.models import AgentRun, Conversation, RunEvent
from apps.agent.policy import default_policy
from apps.agent.selections import check_context_sources
from apps.agent.views import run_json
from apps.agent.run_activity import load_run_activity
from apps.agent.worker import context_messages
from apps.catalog.models import DataResource
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401

pytestmark = pytest.mark.efficiency


def saved_run(env, **values):
    return AgentRun.objects.create(
        conversation=env["conversation"],
        owner=env["user"],
        model="mock",
        prompt="核对资料",
        status=values.pop("status", "succeeded"),
        idempotency_key=uuid4().hex,
        knowledge_selection=values.pop("knowledge_selection", {"_contextRunIds": []}),
        **values,
    )


def event_queries(queries):
    return [item for item in queries if '"agent_runevent"' in item["sql"]]


def seed_events(run):
    for kind, text in (
        ("parameters", '{"inputTokens":11}'),
        ("thinking", "核对"),
        ("usage", '{"completion_tokens":2}'),
        ("answer_preview", "旧预览"),
        ("parameters", '{"inputTokens":22}'),
        ("thinking", "资料。"),
        ("usage", '{"completion_tokens":3}'),
        ("answer_preview", "当前预览"),
        ("tool_completed", "真实工具结果"),
    ):
        RunEvent.objects.create(run=run, kind=kind, text=text)


def test_run_progress_reads_event_payload_once_and_preserves_values(setup_agent):
    env = setup_agent
    with project_scope(env["scope"]):
        run = saved_run(env, status="running")
        seed_events(run)
        start = timezone.now() - timedelta(seconds=3)
        RunEvent.objects.filter(run=run, kind="thinking").update(created_at=start)
        with CaptureQueriesContext(connection) as queries:
            payload = run_json(run, env["user"])
        assert payload["generationParameters"] == {
            "inputTokens": 22,
            "lastGeneratedTokens": 3,
            "modelCalls": 2,
            "generatedTokens": 5,
        }
        assert payload["answerPreview"] == "当前预览"
        assert payload["thinkingText"] == "核对资料。"
        assert payload["thinkingDurationMs"] >= 3000
        assert len(event_queries(queries)) == 1


def test_conversation_event_queries_do_not_grow_per_turn(setup_agent):
    env = setup_agent
    with project_scope(env["scope"]):
        # Chat isolates event I/O from independently checked resource permissions.
        Conversation.objects.filter(pk=env["conversation"].pk).update(mode="chat")
        for _ in range(30):
            seed_events(saved_run(env))
    with CaptureQueriesContext(connection) as queries:
        response = env["client"].get(
            f"/api/agent/conversations/{env['conversation'].pk}/", **env["header"]
        )
    assert response.status_code == 200, response.content
    runs = response.json()["runs"]
    assert len(runs) == 30
    assert all(item["thinkingText"] == "核对资料。" for item in runs)
    assert all(item["answerPreview"] == "" for item in runs)
    assert all(item["generationParameters"]["generatedTokens"] == 5 for item in runs)
    assert len(event_queries(queries)) == 1


def test_poll_keeps_incremental_event_cursor_and_full_thinking(setup_agent):
    env = setup_agent
    with project_scope(env["scope"]):
        run = saved_run(env, status="running")
        seed_events(run)
        after = run.events.order_by("id").first().id
    with CaptureQueriesContext(connection) as queries:
        response = env["client"].get(
            f"/api/agent/runs/{run.pk}/?after={after}", **env["header"]
        )
    assert response.status_code == 200, response.content
    payload = response.json()
    assert payload["run"]["thinkingText"] == "核对资料。"
    assert len(payload["events"]) == 8
    assert all(item["id"] > after for item in payload["events"])
    assert payload["cursor"] == payload["events"][-1]["id"]
    assert len(event_queries(queries)) == 2


def test_history_guard_loads_exact_sources_once_and_still_checks_revocation(
    setup_agent,
):
    env = setup_agent
    with project_scope(env["scope"]):
        source = saved_run(env, resource_ids=[env["resource"].id])
        run = saved_run(
            env, status="running", knowledge_selection={"_contextRunIds": [source.pk]}
        )
        with CaptureQueriesContext(connection) as queries:
            check_context_sources(run, env["user"], default_policy())
        source_queries = [
            item for item in queries if 'FROM "agent_agentrun"' in item["sql"]
        ]
        assert len(source_queries) == 1
        DataResource.objects.filter(pk=env["resource"].pk).update(
            owner_only=True, maintainer=env["other"]
        )
        with pytest.raises(PermissionDenied):
            check_context_sources(run, env["user"], default_policy())
        source.delete()
        with pytest.raises(PermissionDenied, match="历史来源发生变化"):
            check_context_sources(run, env["user"], default_policy())


def test_activity_does_not_fetch_superseded_previews_or_foreign_events(setup_agent):
    env = setup_agent
    with project_scope(env["scope"]):
        run = saved_run(env, status="running")
        seed_events(run)
        other_conversation = Conversation.objects.create(
            owner=env["other"], mode="agent"
        )
        other = AgentRun.objects.create(
            conversation=other_conversation,
            owner=env["other"],
            model="mock",
            prompt="private",
            idempotency_key=uuid4().hex,
        )
        RunEvent.objects.create(run=other, kind="thinking", text="PRIVATE_SECRET")
        # Only the most recent parameter snapshot is authoritative.
        oldest = run.events.filter(kind="parameters").order_by("id").first()
        RunEvent.objects.filter(pk=oldest.pk).update(text="obsolete malformed snapshot")
        with CaptureQueriesContext(connection) as queries:
            activities = load_run_activity([run])
        assert set(activities) == {run.pk}
        assert "PRIVATE_SECRET" not in json.dumps(activities)
        assert len(queries) == 1
        with connection.cursor() as cursor:
            cursor.execute(queries[0]["sql"])
            rows = cursor.fetchall()
        assert (
            len(rows) == 6
        )  # 2 thinking + 2 usage + latest parameters + latest preview
        assert all(
            "旧预览" not in row and "obsolete malformed snapshot" not in row
            for row in rows
        )


def test_progress_is_fresh_on_next_read_and_finished_duration_is_stable(setup_agent):
    env = setup_agent
    with project_scope(env["scope"]):
        run = saved_run(env, status="running")
        seed_events(run)
        first = run_json(run, env["user"])
        RunEvent.objects.create(run=run, kind="thinking", text="新增依据。")
        RunEvent.objects.create(run=run, kind="answer_preview", text="更新预览")
        second = run_json(run, env["user"])
        assert first["thinkingText"] == "核对资料。"
        assert second["thinkingText"] == "核对资料。新增依据。"
        assert second["answerPreview"] == "更新预览"
        run.status = "succeeded"
        run.save(update_fields=["status", "updated_at"])
        RunEvent.objects.filter(run=run, kind="thinking").update(
            created_at=run.updated_at - timedelta(seconds=2)
        )
        final = run_json(run, env["user"])
        assert final["answerPreview"] == ""
        assert final["thinkingDurationMs"] == 2000


def test_context_build_queries_checked_ancestry_once_and_keeps_exact_ids(setup_agent):
    from apps.agent import selections

    env = setup_agent
    with project_scope(env["scope"]):
        source = saved_run(env, answer="已核查说明")
        current = saved_run(env, status="running")
        with patch.object(
            selections, "history_sources", wraps=selections.history_sources
        ) as ancestry:
            messages = context_messages(current, default_policy(), None)
        assert ancestry.call_count == 1
        assert len(messages) == 3
        assert "已核查说明" in messages[1]["content"]
        assert current.knowledge_selection["_contextRunIds"] == [source.pk]


def test_activity_does_not_bypass_revoked_history_access(setup_agent):
    env = setup_agent
    with project_scope(env["scope"]):
        run = saved_run(
            env,
            evidence=[
                {
                    "id": 1,
                    "tool": "describe_resource",
                    "resourceId": env["resource"].pk,
                    "result": {"fields": []},
                }
            ],
        )
        activity = load_run_activity([run])[run.pk]
        DataResource.objects.filter(pk=env["resource"].pk).update(
            owner_only=True, maintainer=env["other"]
        )
        with pytest.raises(PermissionDenied):
            run_json(run, env["user"], activity=activity)
