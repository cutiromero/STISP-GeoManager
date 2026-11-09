"""Bound read work across conversation size without caching access decisions."""

from unittest.mock import patch
from uuid import uuid4
import json

from django.db import connection
from django.test.utils import CaptureQueriesContext
import pytest

from apps.agent.models import AgentRun, Conversation
from apps.agent import tools
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401

# ruff: noqa: F811

pytestmark = pytest.mark.efficiency


@pytest.mark.parametrize("mode", ["chat", "agent"])
def test_conversation_read_work_is_bounded(setup_agent, mode):
    env = setup_agent
    Conversation.objects.filter(pk=env["conversation"].pk).update(mode=mode)
    results = []
    for size in [1, 30]:
        with project_scope(env["scope"]):
            count = AgentRun.objects.count()
            for _ in range(size - count):
                AgentRun.objects.create(
                    conversation=env["conversation"],
                    owner=env["user"],
                    model="mock",
                    prompt="读取已授权历史",
                    status="succeeded",
                    idempotency_key=uuid4().hex,
                    knowledge_selection={},
                )
        with (
            patch(
                "apps.agent.tools.check_evidence", wraps=tools.check_evidence
            ) as check,
            CaptureQueriesContext(connection) as queries,
        ):
            response = env["client"].get(
                f"/api/agent/conversations/{env['conversation'].pk}/", **env["header"]
            )
        assert response.status_code == 200
        assert len(response.json()["runs"]) == size
        operations = {
            name: sum(f'"{table}"' in q["sql"] for q in queries)
            for name, table in [
                ("policy", "agent_agentpolicy"),
                ("ancestry", "agent_agentrun"),
                ("attachments", "agent_agentattachment"),
            ]
        }
        results.append(
            {
                "turns": size,
                "queries": len(queries),
                "checks": check.call_count,
                **operations,
            }
        )
    assert results[-1]["policy"] == 2
    assert results[-1]["ancestry"] <= (2 if mode == "agent" else 1)
    assert results[-1]["attachments"] == 1
    assert results[-1]["checks"] == (30 if mode == "agent" else 0)
    print(json.dumps({"mode": mode, "operations": results}))


def test_exact_ancestors_are_checked_once_and_new_reads_see_revocation(setup_agent):
    from django.core.exceptions import PermissionDenied
    from apps.agent.policy import default_policy
    from apps.agent.selections import check_conversation_history

    env = setup_agent
    with project_scope(env["scope"]):

        def saved(**kw):
            return AgentRun.objects.create(
                conversation=env["conversation"],
                owner=env["user"],
                model="mock",
                prompt="历史",
                status="succeeded",
                idempotency_key=uuid4().hex,
                **kw,
            )

        ancestor = saved(knowledge_selection={"_contextRunIds": []})
        unrelated = saved(knowledge_selection={"_contextRunIds": []})
        current = saved(knowledge_selection={"_contextRunIds": [ancestor.pk]})
        with patch(
            "apps.agent.tools.check_evidence", wraps=tools.check_evidence
        ) as checked:
            assert check_conversation_history(
                [current], env["user"], default_policy()
            ) == {current.pk}
        assert {call.args[0].pk for call in checked.call_args_list} == {
            ancestor.pk,
            current.pk,
        }
        assert unrelated.pk not in {call.args[0].pk for call in checked.call_args_list}

        def revoked(source, *args, **kwargs):
            if source.pk == ancestor.pk:
                raise PermissionDenied("已撤权")

        with (
            patch("apps.agent.tools.check_evidence", side_effect=revoked),
            pytest.raises(PermissionDenied),
        ):
            check_conversation_history([current], env["user"], default_policy())


def test_legacy_ancestors_outside_the_display_window_still_require_access(setup_agent):
    from apps.agent.policy import default_policy
    from apps.agent.selections import check_conversation_history

    env = setup_agent
    with project_scope(env["scope"]):
        rows = [
            AgentRun.objects.create(
                conversation=env["conversation"],
                owner=env["user"],
                model="mock",
                prompt="旧历史",
                status="succeeded",
                idempotency_key=uuid4().hex,
                knowledge_selection={},
            )
            for _ in range(5)
        ]
        with patch(
            "apps.agent.tools.check_evidence", wraps=tools.check_evidence
        ) as checked:
            check_conversation_history(rows[-2:], env["user"], default_policy())
        assert {call.args[0].pk for call in checked.call_args_list} == {
            row.pk for row in rows
        }
        assert checked.call_count == 5


def test_history_reads_attachment_metadata_in_one_query(setup_agent):
    from apps.agent.models import AgentAttachment

    env = setup_agent
    with project_scope(env["scope"]):
        attachment = AgentAttachment.objects.create(
            owner=env["user"],
            conversation=env["conversation"],
            name="说明.txt",
            path="unused.txt",
            mime_type="text/plain",
            kind="document",
            checksum="a" * 64,
            extracted_text="真实附件说明",
        )
        for _ in range(30):
            AgentRun.objects.create(
                conversation=env["conversation"],
                owner=env["user"],
                model="mock",
                prompt="问题",
                status="succeeded",
                idempotency_key=uuid4().hex,
                knowledge_selection={"_contextRunIds": []},
                attachment_ids=[attachment.pk],
            )
    with CaptureQueriesContext(connection) as queries:
        response = env["client"].get(
            f"/api/agent/conversations/{env['conversation'].pk}/", **env["header"]
        )
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 30
    assert all(
        row["attachments"][0]["extractedText"] == "真实附件说明"
        for row in response.json()["runs"]
    )
    assert sum('"agent_agentattachment"' in row["sql"] for row in queries) == 1
