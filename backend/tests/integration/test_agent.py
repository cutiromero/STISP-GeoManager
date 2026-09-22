from dataclasses import replace
from datetime import timedelta
from http.server import ThreadingHTTPServer
import json
import sqlite3
import threading
import time

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission, Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.utils import timezone

from apps.agent.config import ModelConfig, registry
from apps.agent.models import (
    AgentWorkflow,
    Conversation,
    AgentRun,
    AgentRuntime,
    AgentPolicy,
)
from apps.agent.policy import default_policy, validate_policy
from apps.agent.tools import execute, evidence_items
from apps.agent.worker import (
    run_task,
    recover,
    claim,
    Cancelled,
    parse_agent_command,
    context_budget_bytes,
)
from apps.agent.workflow_worker import (
    recover as recover_workflows,
    run_once as run_workflow_once,
)
from apps.agent.provider import stream, check_model
from apps.agent.management.commands.mock_agent_model import MockHandler
from apps.catalog.models import DataResource
from apps.core.storage import table_data_path
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project, ProjectMembership


@pytest.fixture
def setup_agent(settings, tmp_path):
    settings.AGENT_MODELS = [
        {
            "alias": "mock",
            "name": "Mock",
            "base_url": "http://127.0.0.1:19100/v1",
            "model_id": "mock-local",
            "agent": True,
        }
    ]
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=tmp_path / "app",
        research_data_root=tmp_path / "research",
    )
    user = get_user_model().objects.create_user("agent_owner", password="testpass")
    user.user_permissions.add(
        *Permission.objects.filter(
            codename__in=[
                "use_local_model",
                "use_data_agent",
                "browse_data",
                "query_data",
            ]
        )
    )
    other = get_user_model().objects.create_user("agent_other", password="testpass")
    admin = get_user_model().objects.create_superuser(
        "agent_admin", password="testpass"
    )
    project = Project.objects.create(code="agent-private", name="Agent private")
    ProjectMembership.objects.create(project=project, user=user)
    scope = ProjectScope((project.id,), project.id, user.id)
    with project_scope(scope):
        path = table_data_path("data.sqlite")
        path.parent.mkdir(parents=True)
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE samples (year INTEGER, value REAL, region TEXT)")
            conn.executemany(
                "INSERT INTO samples VALUES (?,?,?)",
                [(2024, 2, "A"), (2024, 4, "A"), (2025, 8, "B"), (2025, None, "B")],
            )
            conn.execute("CREATE TABLE secrets (password TEXT)")
            conn.execute("INSERT INTO secrets VALUES ('never send this')")
        resource = DataResource.objects.create(
            name="人工样地",
            code="agent-synthetic",
            data_type="table",
            file_format="SQLITE",
            storage_path="samples",
        )
        conversation = Conversation.objects.create(owner=user, mode="agent")
    AgentRuntime.objects.update_or_create(
        name="worker", defaults={"heartbeat": timezone.now()}
    )
    AgentRuntime.objects.update_or_create(
        name="model:mock",
        defaults={"heartbeat": timezone.now(), "detail": {"status": "online"}},
    )
    client = Client()
    client.force_login(user)
    return dict(
        user=user,
        other=other,
        admin=admin,
        project=project,
        scope=scope,
        resource=resource,
        conversation=conversation,
        client=client,
        header={"HTTP_X_PROJECT_ID": str(project.id)},
    )


def new_run(s, **overrides):
    return AgentRun.objects.create(
        conversation=s["conversation"],
        owner=s["user"],
        model="mock",
        prompt="统计样地",
        status="running",
        idempotency_key="abcdefgh",
        heartbeat=timezone.now(),
        **overrides,
    )


def test_permissions_and_project_isolation(setup_agent):
    s = setup_agent
    c = s["client"]
    assert Client().get("/api/agent/bootstrap/").status_code == 401
    assert c.get("/api/agent/bootstrap/").status_code == 400
    assert c.get("/api/agent/bootstrap/", **s["header"]).json()["canAgent"]
    c.force_login(s["other"])
    assert c.get("/api/agent/conversations/", **s["header"]).status_code == 404
    c.force_login(s["admin"])
    assert (
        c.get(
            f"/api/agent/conversations/{s['conversation'].id}/", **s["header"]
        ).status_code
        == 404
    )


def test_guest_and_ordinary_user(setup_agent):
    s = setup_agent
    c = s["client"]
    c.force_login(s["other"])
    ordinary = Group.objects.get(name="普通用户")
    s["other"].groups.add(ordinary)
    data = c.get("/api/agent/bootstrap/", HTTP_X_PROJECT_ID="1").json()
    assert data["canChat"] and not data["canAgent"]
    s["other"].groups.add(Group.objects.get(name="游客"))
    assert not c.get("/api/agent/bootstrap/", HTTP_X_PROJECT_ID="1").json()["canChat"]


def test_admin_policy_restricts_and_is_superadmin_only(setup_agent):
    s = setup_agent
    c = s["client"]
    url = "/api/agent/admin/"
    assert c.get(url, **s["header"]).status_code == 403
    c.force_login(s["admin"])
    data = c.get(url, **s["header"]).json()
    data["policy"]["agentAudience"]["deniedUserIds"] = [s["user"].id]
    value = {"revision": data["revision"], "policy": data["policy"]}
    assert (
        c.put(
            url, json.dumps(value), content_type="application/json", **s["header"]
        ).status_code
        == 200
    )
    assert (
        c.put(
            url, json.dumps(value), content_type="application/json", **s["header"]
        ).status_code
        == 409
    )
    c.force_login(s["user"])
    assert not c.get("/api/agent/bootstrap/", **s["header"]).json()["canAgent"]


def test_idempotency_cancel_and_hidden_ids(setup_agent):
    s = setup_agent
    c = s["client"]
    url = f"/api/agent/conversations/{s['conversation'].id}/runs/"
    payload = {"model": "mock", "prompt": "分析", "idempotencyKey": "unique-key-01"}
    first = c.post(
        url, json.dumps(payload), content_type="application/json", **s["header"]
    )
    assert first.status_code == 202, first.content
    second = c.post(
        url, json.dumps(payload), content_type="application/json", **s["header"]
    )
    assert first.json()["id"] == second.json()["id"]
    payload["prompt"] = "changed"
    assert (
        c.post(
            url, json.dumps(payload), content_type="application/json", **s["header"]
        ).status_code
        == 409
    )
    run_id = first.json()["id"]
    assert (
        c.post(f"/api/agent/runs/{run_id}/cancel/", **s["header"]).json()["status"]
        == "cancelled"
    )
    c.force_login(s["admin"])
    assert c.get(f"/api/agent/runs/{run_id}/", **s["header"]).status_code == 404


def test_stats_filters_and_read_only(setup_agent):
    s = setup_agent
    with project_scope(s["scope"]):
        r = new_run(s)
        result, pairs = execute(
            r, "summarize_data", {"resourceId": s["resource"].id, "fields": ["value"]}
        )
        stats = result["statistics"][0]
        assert stats["mean"] == pytest.approx(14 / 3) and stats["missingCount"] == 1
        assert result["scope"] == "full"
        result, _ = execute(
            r,
            "aggregate_data",
            {
                "resourceId": s["resource"].id,
                "groupBy": "year",
                "field": "value",
                "metric": "mean",
            },
        )
        assert result["groups"] == [
            {"group": 2024, "value": 3.0},
            {"group": 2025, "value": 8.0},
        ]
        result, _ = execute(
            r,
            "read_rows",
            {
                "resourceId": s["resource"].id,
                "fields": ["value"],
                "filters": [{"field": "year", "op": "eq", "value": 2024}],
            },
        )
        assert result["rows"] == [{"value": 2.0}, {"value": 4.0}]
        with pytest.raises(ValidationError):
            execute(r, "execute_operator", {})
        with pytest.raises(ValidationError):
            execute(
                r,
                "read_rows",
                {"resourceId": s["resource"].id, "sql": "SELECT * FROM secrets"},
            )
        with pytest.raises(ValidationError):
            execute(
                r, "read_rows", {"resourceId": s["resource"].id, "fields": ["password"]}
            )


def test_search_resources_table_keyword_matches_data_type(setup_agent):
    s = setup_agent
    with project_scope(s["scope"]):
        result, _ = execute(new_run(s), "search_resources", {"query": "table"})
    assert result["items"][0]["id"] == s["resource"].id


def test_sample_is_not_population(setup_agent):
    s = setup_agent
    with project_scope(s["scope"]):
        with sqlite3.connect(table_data_path("data.sqlite")) as db:
            db.executemany('INSERT INTO samples VALUES (2025,100,"A")', [()] * 10001)
        result, _ = execute(
            new_run(s),
            "summarize_data",
            {"resourceId": s["resource"].id, "fields": ["value"]},
        )
        assert (
            result["truncated"]
            and result["scannedRows"] == 10000
            and result["scope"] == "prefix_sample"
        )


def test_revoked_resource_blocks_history_and_execution(setup_agent):
    s = setup_agent
    with project_scope(s["scope"]):
        r = new_run(s)
        _, pairs = execute(r, "describe_resource", {"resourceId": s["resource"].id})
        r.evidence = evidence_items(r, "describe_resource", pairs)
        r.save()
        s["resource"].status = "inactive"
        s["resource"].save()
        with pytest.raises(PermissionDenied):
            execute(r, "search_resources", {})
    assert s["client"].get(f"/api/agent/runs/{r.id}/", **s["header"]).status_code == 403
    assert (
        s["client"]
        .get(f"/api/agent/conversations/{s['conversation'].id}/", **s["header"])
        .status_code
        == 403
    )


def test_membership_revoked_after_queue_stops_worker(setup_agent, monkeypatch):
    s = setup_agent
    with project_scope(s["scope"]):
        r = new_run(s)
    ProjectMembership.objects.filter(user=s["user"], project=s["project"]).delete()
    called = []
    monkeypatch.setattr("apps.agent.worker.stream", lambda *a, **k: called.append(True))
    run_task(r.id)
    r.refresh_from_db()
    assert r.status == "interrupted" and not called


def test_restart_never_replays_running_task(setup_agent):
    s = setup_agent
    with project_scope(s["scope"]):
        r = new_run(s)
    AgentRun.objects.filter(pk=r.id).update(
        heartbeat=timezone.now() - timedelta(minutes=2)
    )
    recover()
    r.refresh_from_db()
    assert r.status == "interrupted" and claim() is None


def test_scoped_selection_and_compare_policy(setup_agent):
    s = setup_agent
    with project_scope(s["scope"]):
        r = new_run(s, resource_ids=[999999])
        assert execute(r, "search_resources", {})[0]["items"] == []
        with pytest.raises(PermissionDenied):
            execute(r, "describe_resource", {"resourceId": s["resource"].id})
        p = default_policy()
        p["allowCompare"] = False
        AgentPolicy.objects.create(value=p)
        with pytest.raises(PermissionDenied):
            execute(r, "compare_summaries", {"evidenceIds": [1, 2]})


def test_registry_rejects_arbitrary_addresses(settings):
    settings.AGENT_MODELS = [
        {
            "alias": "bad",
            "name": "bad",
            "base_url": "http://example.com/v1",
            "model_id": "x",
        }
    ]
    with pytest.raises(ValueError):
        registry()


def test_context_budget_reserves_output_tokens_and_uses_model_window(setup_agent):
    p = default_policy()
    p["maxContextBytes"] = 128000
    model = ModelConfig(
        alias="qwen",
        name="Qwen",
        base_url="http://127.0.0.1:19100/v1",
        model_id="qwen",
        context_window_tokens=32768,
    )
    assert context_budget_bytes(p, model) == p["maxContextBytes"]


def test_deep_thinking_requires_qwen_and_is_persisted(setup_agent, settings):
    s = setup_agent
    url = f"/api/agent/conversations/{s['conversation'].id}/runs/"
    payload = {
        "model": "mock",
        "prompt": "深度分析",
        "idempotencyKey": "deep-thinking-01",
        "thinkingMode": "deep",
    }
    denied = s["client"].post(
        url, json.dumps(payload), content_type="application/json", **s["header"]
    )
    assert denied.status_code == 400
    settings.AGENT_MODELS = [{**settings.AGENT_MODELS[0], "qwen": True}]
    accepted = s["client"].post(
        url, json.dumps(payload), content_type="application/json", **s["header"]
    )
    assert accepted.status_code == 202, accepted.content
    assert accepted.json()["thinkingMode"] == "deep"
    assert AgentRun.objects.get(pk=accepted.json()["id"]).thinking_mode == "deep"


def test_qwen_reasoning_content_is_separate_from_answer(monkeypatch):
    captured = {}

    class Response:
        status = 200

        def __init__(self):
            self.lines = iter(
                [
                    'data: {"choices":[{"delta":{"reasoning_content":"先判断。"}}]}\n'.encode(),
                    'data: {"choices":[{"delta":{"content":"答案"}}]}\n'.encode(),
                    b"data: [DONE]\n",
                ]
            )

        def readline(self, _limit):
            return next(self.lines, b"")

        def read(self, _limit):
            return b""

    class Connection:
        def __init__(self, *_args, **_kwargs):
            self.sock = self

        def connect(self):
            return None

        def request(self, _method, _path, body, headers):
            captured.update(json.loads(body))

        def getresponse(self):
            return Response()

        def shutdown(self, *_args):
            return None

        def close(self):
            return None

    monkeypatch.setattr("apps.agent.provider.http.client.HTTPConnection", Connection)
    thoughts = []
    model = ModelConfig(
        alias="qwen",
        name="Qwen",
        base_url="http://127.0.0.1:19100/v1",
        model_id="qwen",
        qwen=True,
    )
    answer = list(
        stream(
            model,
            [{"role": "user", "content": "你好"}],
            256,
            lambda: None,
            thinking=True,
            on_thinking=thoughts.append,
        )
    )
    assert "".join(answer) == "答案"
    assert "".join(thoughts) == "先判断。"
    assert captured["chat_template_kwargs"] == {
        "enable_thinking": True,
        "reasoning_effort": "medium",
    }


def test_policy_accepts_explicit_operator_enablement(setup_agent):
    p = default_policy()
    p["operatorEnabled"] = True
    assert validate_policy(p)["operatorEnabled"] is True


def test_agent_command_parser_accepts_qwen_wrappers():
    assert parse_agent_command(
        '<think>internal</think>\n```json\n{"action":"final","answer":"完成"}\n```'
    ) == {"action": "final", "answer": "完成"}
    assert parse_agent_command('{"action":"search_resources","query":"table"}') == {
        "action": "search_resources",
        "arguments": {"query": "table"},
    }
    assert parse_agent_command(
        '{"action":"describe_resource","parameters":{"resourceId":1}}'
    ) == {"action": "describe_resource", "arguments": {"resourceId": 1}}


@pytest.mark.django_db(transaction=True)
def test_real_mock_http_multistep_worker(setup_agent, settings):
    s = setup_agent
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings.AGENT_MODELS = [
        {
            **settings.AGENT_MODELS[0],
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
        }
    ]
    try:
        assert check_model(registry()["mock"])
        with project_scope(s["scope"]):
            r = new_run(s)
        run_task(r.id)
        r.refresh_from_db()
        assert r.status == "succeeded", r.detail
        assert len(r.evidence) >= 3 and "4.666" in r.answer
        assert r.events.filter(kind="tool_completed").count() == 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_http_stream_cancellation(setup_agent, settings):
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings.AGENT_MODELS = [
        {
            **settings.AGENT_MODELS[0],
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
        }
    ]
    started = time.monotonic()

    def guard():
        if time.monotonic() - started > 0.12:
            raise Cancelled()

    try:
        with pytest.raises(Cancelled):
            list(
                stream(
                    registry()["mock"],
                    [{"role": "user", "content": "hello"}],
                    200,
                    guard,
                )
            )
        assert time.monotonic() - started < 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.django_db(transaction=True)
def test_workflow_claim_executes_plan_and_persists_checkpoints(setup_agent):
    s = setup_agent
    response = s["client"].post(
        "/api/agent/workflows/",
        json.dumps(
            {
                "workflowType": "hyperspectral_interpretation",
                "goal": "识别目标影像中的矿物和岩性",
                "model": "mock",
                "resourceIds": [s["resource"].id],
                "parameters": {},
                "executeOperators": False,
                "idempotencyKey": "workflow-plan-01",
            }
        ),
        content_type="application/json",
        **s["header"],
    )
    assert response.status_code == 202, response.content
    workflow_id = response.json()["id"]
    assert AgentWorkflow.objects.get(pk=workflow_id).status == "queued"

    run_workflow_once()

    workflow = AgentWorkflow.objects.get(pk=workflow_id)
    assert workflow.status == "succeeded", workflow.detail
    assert [step.kind for step in workflow.steps.all()] == [
        "discover_inputs",
        "build_plan",
        "finalize",
    ]
    assert workflow.checkpoints.count() == 2
    assert workflow.resource_ids == [s["resource"].id]


@pytest.mark.django_db(transaction=True)
def test_workflow_cancel_closes_queued_item(setup_agent):
    s = setup_agent
    response = s["client"].post(
        "/api/agent/workflows/",
        json.dumps(
            {
                "goal": "取消前的计划",
                "model": "mock",
                "resourceIds": [],
                "parameters": {},
                "executeOperators": False,
                "idempotencyKey": "workflow-cancel-01",
            }
        ),
        content_type="application/json",
        **s["header"],
    )
    assert response.status_code == 202, response.content
    workflow_id = response.json()["id"]
    cancelled = s["client"].post(
        f"/api/agent/workflows/{workflow_id}/cancel/", **s["header"]
    )
    assert cancelled.status_code == 200, cancelled.content
    workflow = AgentWorkflow.objects.get(pk=workflow_id)
    assert workflow.status == "cancelled"
    assert workflow.cancel_requested


@pytest.mark.django_db(transaction=True)
def test_workflow_recovery_does_not_restart_waiting_compute(setup_agent):
    s = setup_agent
    with project_scope(s["scope"]):
        workflow = AgentWorkflow.objects.create(
            owner=s["user"],
            goal="等待计算",
            model="mock",
            status="waiting_compute",
            heartbeat=timezone.now() - timedelta(minutes=5),
            idempotency_key="workflow-wait-01",
        )
    recover_workflows()
    workflow.refresh_from_db()
    assert workflow.status == "waiting_compute"
