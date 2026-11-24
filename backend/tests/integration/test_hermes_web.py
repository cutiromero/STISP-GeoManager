from contextlib import contextmanager
from io import BytesIO
from uuid import uuid4

import pytest

from apps.agent import hermes_gateway as gateway
from apps.agent.models import AgentPolicy, AgentWorkflow, HermesSession
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.catalog import register_flow
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import ProjectMembership
from tests.integration.test_agent import setup_agent  # noqa: F401
from tests.integration.test_compute import setup_compute  # noqa: F401


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
    assert response.json()["error"] == "请使用已获授权的科研智能体工具"


def test_version_guides_hermes_without_starting_legacy_workflow(
    setup_agent,  # noqa: F811
    monkeypatch,
    settings,
):
    env = setup_agent
    settings.AGENT_MODELS = []
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

    def tool(name, arguments):
        return env["client"].post(
            "/internal/hermes/tool/",
            {
                "session_id": gateway.platform_session_id(session.pk),
                "turn_id": "turn-test",
                "name": name,
                "arguments": arguments,
            },
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer tool-test",
        )

    response = tool("get_research_workflow", {"versionId": version.pk})
    assert response.status_code == 200, response.content
    plan = response.json()
    assert plan["dataRoles"][0]["key"] == "source"
    assert plan["suggestedSteps"][0]["title"] == "梳理资料与研究线索"
    assert plan["suggestedSteps"][1]["after"] == ["summarize"]
    assert "describe_resource" in plan["suggestedSteps"][0]["suggestedTools"]
    assert "contract" not in plan["suggestedSteps"][0]
    assert (
        tool("get_research_workflow", {"versionId": version.pk + 1}).status_code == 404
    )
    assert (
        tool("list_business_flows", {"query": "资料评估"}).json()["items"][0][
            "versionId"
        ]
        == version.pk
    )
    assert tool("search_resources", {"query": "人工"}).status_code == 200
    assert not AgentWorkflow._base_manager.filter(owner=env["user"]).exists()
    catalog = env["client"].get(
        "/api/agent/workflow-uploads/references/?usage=research&source=registered",
        **env["header"],
    )
    assert catalog.status_code == 200, catalog.content
    assert [item["id"] for item in catalog.json()["items"]] == [env["resource"].pk]


def test_hermes_compute_retries_and_reads_real_output(
    setup_compute,  # noqa: F811
    monkeypatch,
):
    from django.contrib.auth.models import Permission
    from apps.agent.hermes_tools import execute, reauthorize_transcript
    from apps.agent.policy import policy
    from apps.compute.models import ComputeImport, ComputeTask
    from apps.compute.packages import ComputeError
    from apps.compute.worker import process_import, run_task, task_scope

    env = setup_compute
    owner = env["owner"]
    owner.user_permissions.add(
        *Permission.objects.filter(
            codename__in=["use_local_model", "use_data_agent", "query_data"]
        )
    )
    AgentPolicy.objects.create(pk=1, value={"operatorEnabled": True})
    scope = ProjectScope((env["project"].pk,), env["project"].pk, owner.pk)
    with project_scope(scope):
        session = HermesSession.objects.create(mode="agent", owner=owner)
        another = HermesSession.objects.create(mode="agent", owner=owner)

    args = {key: value for key, value in env["body"].items() if key != "idempotencyKey"}
    with pytest.raises(ComputeError):
        execute(session, "submit_research_compute", {**args, "inputs": {}}, "turn1")
    first = execute(session, "submit_research_compute", args, "turn1")
    assert (
        execute(session, "submit_research_compute", args, "turn1")["taskId"]
        == first["taskId"]
    )
    assert (
        execute(session, "get_research_compute", {"taskId": first["taskId"]}, "turn1")[
            "status"
        ]
        == "queued"
    )
    with pytest.raises(ComputeError):
        execute(another, "get_research_compute", {"taskId": first["taskId"]}, "turn2")

    def run_operator(attempt, package, inputs, results, manifest, heartbeat):
        (results / "summary.csv").write_text("group,mean,count\nA,3,2\nB,8,1\n")
        heartbeat(True)

    monkeypatch.setattr("apps.compute.worker.execute", run_operator)
    with project_scope(scope):
        task = ComputeTask.objects.get(pk=first["taskId"])
    with task_scope(task):
        run_task(task)
    result = execute(
        session, "get_research_compute", {"taskId": first["taskId"]}, "turn2"
    )
    assert result["status"] == "succeeded", result
    output_id = result["outputs"][0]["id"]
    output = execute(session, "read_research_output", {"outputId": output_id}, "turn2")
    assert output["columns"] == ["group", "mean", "count"]
    assert output["total"] == 2
    registered = execute(
        session, "register_research_output", {"outputId": output_id}, "turn2"
    )
    with task_scope(task):
        process_import(ComputeImport.objects.get(pk=registered["importId"]))
    followup = execute(
        session, "get_research_compute", {"taskId": first["taskId"]}, "turn3"
    )
    assert followup["outputs"][0]["importStatus"] == "ready", followup["outputs"][0]
    assert followup["outputs"][0]["resourceId"]
    with project_scope(scope):
        reauthorize_transcript(session, owner, policy())


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
    monkeypatch.setattr(
        gateway,
        "request",
        lambda *args, **kwargs: {
            "run_id": RUN,
            "session_id": identifier,
            "status": "completed",
        },
    )
    address = BASE + f"/v1/runs/{RUN}"
    assert (
        environment["client"].get(address, **environment["header"]).status_code == 200
    )
    resource = environment["resource"]
    type(resource)._base_manager.filter(pk=resource.pk).update(status="disabled")
    assert (
        environment["client"].get(address, **environment["header"]).status_code == 403
    )
