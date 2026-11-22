from contextlib import contextmanager
from io import BytesIO
from uuid import uuid4

import pytest

from apps.agent import hermes_gateway as gateway
from apps.agent.models import AgentPolicy, AgentWorkflow, HermesSession
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.catalog import register_flow
from apps.projects.context import project_scope
from apps.projects.models import ProjectMembership
from tests.integration.test_agent import setup_agent  # noqa: F401


pytestmark = pytest.mark.django_db
BASE = "/api/agent/hermes"
RUN = "run_" + "1" * 32


def test_admission_uses_native_run_and_session_ownership(
    setup_agent,  # noqa: F811
    monkeypatch,
    settings,
):
    env = setup_agent
    settings.HERMES_WEB_ENABLED = True
    monkeypatch.setenv("STISP_HERMES_GATEWAY_KEY", "gateway-test")
    calls = []
    session_id = ""

    def request(method, path, **kwargs):
        nonlocal session_id
        calls.append((method, path, kwargs))
        if path == "/api/sessions":
            session_id = kwargs["payload"]["id"]
            return {"object": "hermes.session"}
        if method == "POST":
            return {"run_id": RUN, "status": "started", "replayed": len(calls) > 2}
        return {"run_id": RUN, "session_id": session_id, "status": "running"}

    monkeypatch.setattr(gateway, "request", request)
    client = env["client"]
    project = env["header"]
    response = client.post(
        BASE + "/api/sessions",
        {"mode": "agent"},
        content_type="application/json",
        **project,
    )
    assert response.status_code == 201
    assert response.json()["session"]["id"] == session_id
    for replayed in (False, True):
        response = client.post(
            BASE + "/v1/runs",
            {"input": "请检查资料", "session_id": session_id},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="test-request",
            **project,
        )
        assert response.status_code == 202
        assert response.json()["replayed"] is replayed
    first, second = calls[1][2], calls[2][2]
    assert first == second
    assert first["payload"]["session_id"] == session_id
    assert first["headers"]["Idempotency-Key"] != "test-request"
    assert client.get(BASE + f"/v1/runs/{RUN}", **project).status_code == 200
    client.force_login(env["admin"])
    assert client.get(BASE + f"/v1/runs/{RUN}", **project).status_code == 404
    assert (
        client.get(BASE + f"/api/sessions/{session_id}/messages", **project).status_code
        == 404
    )


def test_sse_retains_native_frame_and_checks_browser_session(
    setup_agent,  # noqa: F811
    monkeypatch,
    settings,
):
    env = setup_agent
    settings.HERMES_WEB_ENABLED = True
    monkeypatch.setenv("STISP_HERMES_GATEWAY_KEY", "gateway-test")
    with project_scope(env["scope"]):
        identity = HermesSession.objects.create(
            id=uuid4(), mode="agent", owner=env["user"], title="SSE"
        ).pk
    session_id = gateway.platform_session_id(identity)
    monkeypatch.setattr(
        gateway, "request", lambda *args, **kwargs: {"session_id": session_id}
    )
    upstream = (
        b': keepalive\n\nid: 8\ndata: {"event":"message.delta","delta":"x","seq":8}\n\n'
    )

    class Stream(BytesIO):
        status = 200

    @contextmanager
    def connect(method, path, *, headers):
        assert method == "GET"
        assert path == f"/v1/runs/{RUN}/events"
        assert headers["Last-Event-ID"] == "7"
        with Stream(upstream) as stream:
            yield stream

    monkeypatch.setattr(gateway, "connect", connect)
    client = env["client"]
    address = BASE + f"/v1/runs/{RUN}/events"
    response = client.get(address, HTTP_LAST_EVENT_ID="7", **env["header"])
    assert b"".join(response.streaming_content) == upstream
    response = client.get(address, HTTP_LAST_EVENT_ID="7", **env["header"])
    client.logout()
    assert b"".join(response.streaming_content) == b""


def test_tool_bridge_checks_service_key_and_rejects_chat_scope(
    setup_agent,  # noqa: F811
    monkeypatch,
    settings,
):
    env = setup_agent
    settings.HERMES_WEB_ENABLED = True
    monkeypatch.setenv("STISP_HERMES_GATEWAY_KEY", "gateway-test")
    monkeypatch.setenv("STISP_HERMES_TOOL_KEY", "tool-test")
    with project_scope(env["scope"]):
        identity = HermesSession.objects.create(
            mode="chat", owner=env["user"], title="Chat"
        ).pk
    payload = {
        "session_id": gateway.platform_session_id(identity),
        "turn_id": "turn-test",
        "name": "list_business_flows",
        "arguments": {},
    }
    client = env["client"]
    address = "/internal/hermes/tool/"
    response = client.post(address, payload, content_type="application/json")
    assert response.status_code == 403
    response = client.post(
        address,
        payload,
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer tool-test",
    )
    assert response.status_code == 403
    assert response.json()["error"] == "当前会话未开放业务流工具"


def test_tool_bridge_starts_real_versioned_workflow_once(
    setup_agent,  # noqa: F811
    monkeypatch,
    settings,
):
    env = setup_agent
    settings.HERMES_WEB_ENABLED = True
    monkeypatch.setenv("STISP_HERMES_GATEWAY_KEY", "gateway-test")
    monkeypatch.setenv("STISP_HERMES_TOOL_KEY", "tool-test")
    with project_scope(env["scope"]):
        _, version = register_flow(
            env["admin"],
            {
                "code": "hermes-source",
                "name": "资料评估",
                "description": "整理资料适用范围",
                "definition": source_summary_definition(),
            },
        )
        session = HermesSession.objects.create(
            mode="agent", owner=env["user"], title="Hermes 业务流"
        )
    payload = {
        "session_id": gateway.platform_session_id(session.pk),
        "turn_id": "turn-test",
        "name": "start_business_flow",
        "arguments": {
            "versionId": version.pk,
            "inputs": {"source": env["resource"].pk},
            "goal": "评估合成资料",
        },
    }
    client = env["client"]
    for attempt in range(2):
        response = client.post(
            "/internal/hermes/tool/",
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer tool-test",
        )
        assert response.status_code == 200, response.content
        with project_scope(env["scope"]):
            workflow = AgentWorkflow.objects.get(
                pk=response.json()["workflowId"], owner=env["user"]
            )
            assert workflow.resource_ids == [env["resource"].pk]
            assert AgentWorkflow.objects.filter(owner=env["user"]).count() == 1


def test_web_tools_require_session_opt_in_and_live_project_access(
    setup_agent,  # noqa: F811
    monkeypatch,
    settings,
):
    env = setup_agent
    settings.HERMES_WEB_ENABLED = True
    monkeypatch.setenv("STISP_HERMES_GATEWAY_KEY", "gateway-test")
    monkeypatch.setenv("STISP_HERMES_TOOL_KEY", "tool-test")
    monkeypatch.setattr(gateway, "request", lambda *args, **kwargs: {})
    client = env["client"]
    browser = env["header"]

    start = client.post(
        BASE + "/api/sessions",
        {"mode": "agent", "internet_enabled": True},
        content_type="application/json",
        **browser,
    )
    assert start.status_code == 403
    enable = AgentPolicy.objects.create(pk=1, value={"internetEnabled": True})
    start = client.post(
        BASE + "/api/sessions",
        {"mode": "agent"},
        content_type="application/json",
        **browser,
    )
    assert start.status_code == 201
    session = start.json()["session"]
    assert session["internet_enabled"] is False
    assert (
        client.get(BASE + "/v1/capabilities", **browser).json()["public_web_enabled"]
        is True
    )
    payload = {
        "session_id": session["id"],
        "turn_id": "turn-web",
        "name": "check_public_web",
        "arguments": {},
    }
    address = BASE + f"/api/sessions/{session['id']}"

    def check():
        return client.post(
            "/internal/hermes/tool/",
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer tool-test",
        )

    def set_web(value):
        return client.patch(
            address,
            {"internet_enabled": value},
            content_type="application/json",
            **browser,
        )

    assert check().status_code == 403

    assert set_web("true").status_code == 400
    assert set_web(True).json()["session"]["internet_enabled"] is True
    assert check().json() == {"allowed": True}
    assert set_web(False).json()["session"]["internet_enabled"] is False
    assert check().status_code == 403
    assert set_web(True).status_code == 200
    client.force_login(env["admin"])
    assert set_web(False).status_code == 404
    client.force_login(env["user"])
    enable.value = {"internetEnabled": False}
    enable.save(update_fields=["value"])
    assert check().status_code == 403
    enable.value = {"internetEnabled": True}
    enable.save(update_fields=["value"])
    ProjectMembership.objects.filter(project=env["project"], user=env["user"]).delete()
    assert check().status_code == 403


def test_native_project_tool_returns_scoped_catalog_with_a_receipt(
    setup_agent,  # noqa: F811
    monkeypatch,
    settings,
):
    from apps.agent.models import HermesToolReceipt

    environment = setup_agent
    settings.HERMES_WEB_ENABLED = True
    monkeypatch.setenv("STISP_HERMES_GATEWAY_KEY", "gateway-test")
    monkeypatch.setenv("STISP_HERMES_TOOL_KEY", "tool-test")
    with project_scope(environment["scope"]):
        session = HermesSession.objects.create(
            mode="agent", owner=environment["user"], title="Native tools"
        )
    identifier = gateway.platform_session_id(session.pk)
    response = environment["client"].post(
        "/internal/hermes/tool/",
        {
            "session_id": identifier,
            "tool_call_id": "tool-1",
            "turn_id": "turn-native",
            "name": "search_resources",
            "arguments": {"query": "人工样地", "limit": 5},
        },
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer tool-test",
    )
    assert response.status_code == 200, response.content
    assert response.json()["items"][0]["id"] == environment["resource"].pk
    receipt = HermesToolReceipt.objects.get(session=session, name="search_resources")
    assert receipt.tool_call_id == "tool-1"
    assert receipt.evidence[0]["resourceId"] == environment["resource"].pk
