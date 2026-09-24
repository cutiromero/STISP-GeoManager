import io
import json
import threading
from http.server import ThreadingHTTPServer

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client

from apps.agent.attachments import extract_text
from apps.agent.budgets import apply_budget, check_budget_access, resolve_budget
from apps.agent.management.commands.mock_agent_model import MockHandler
from apps.agent.models import AgentPolicy, AgentRun, AgentRuntime, Conversation
from apps.agent.policy import default_policy, validate_policy
from apps.agent.worker import run_task
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401


def enabled_policy():
    policy = default_policy()
    policy["taskBudgetsEnabled"] = True
    return policy


def test_role_limits_and_snapshot(setup_agent):  # noqa: F811
    env = setup_agent
    policy = enabled_policy()
    normal = resolve_budget(env["user"], policy, "reasoning", service_window=262144)
    assert (
        normal["contextWindowTokens"],
        normal["maxOutputTokens"],
        normal["maxRunSeconds"],
    ) == (65536, 16384, 600)
    privileged = resolve_budget(
        env["admin"], policy, "reasoning", service_window=262144
    )
    actual, window = apply_budget(env["admin"], policy, privileged, 262144)
    assert (window, actual["maxOutputTokens"], actual["maxContextTokens"]) == (
        262144,
        65536,
        196352,
    )
    policy["budgetProfiles"]["reasoning"]["maxOutputTokens"] = 1024
    assert (
        apply_budget(env["admin"], policy, privileged, 262144)[0]["maxOutputTokens"]
        == 65536
    )
    with pytest.raises(PermissionDenied):
        check_budget_access(env["user"], policy, privileged)
    policy["budgetLimits"]["superadmin"]["maxRunSeconds"] = 1800
    with pytest.raises(PermissionDenied):
        check_budget_access(env["admin"], policy, privileged)


@pytest.mark.parametrize("output", [True, 0, 16385, 262144, "65536"])
def test_cannot_request_more_than_role_allows(setup_agent, output):  # noqa: F811
    with pytest.raises(ValidationError):
        resolve_budget(setup_agent["user"], enabled_policy(), "normal", output, 262144)


def test_small_model_and_invalid_policy(setup_agent):  # noqa: F811
    policy = enabled_policy()
    budget = resolve_budget(
        setup_agent["admin"], policy, "reasoning", service_window=32768
    )
    assert budget["maxOutputTokens"] == 16384
    with pytest.raises(ValidationError):
        resolve_budget(setup_agent["admin"], policy, "normal", 32768, 32768)
    policy["budgetLimits"]["superadmin"]["maxOutputTokens"] = 262144
    with pytest.raises(ValidationError):
        validate_policy(policy)


def test_long_document_extraction_preserves_tail():
    text = "a" * 200000 + "TAIL-CODE"
    assert extract_text(text.encode(), ".txt")[1] == "truncated"
    assert extract_text(text.encode(), ".txt", 1048576) == (text, "ready")


def test_submission_budget_and_idempotency(setup_agent):  # noqa: F811
    env = setup_agent
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": enabled_policy()})
    AgentRuntime.objects.filter(name="model:mock").update(
        detail={"status": "online", "contextWindowTokens": 262144}
    )
    data = {
        "model": "mock",
        "prompt": "分析",
        "idempotencyKey": "budget-idempotency",
        "budgetProfile": "reasoning",
    }
    endpoint = f"/api/agent/conversations/{env['conversation'].id}/runs/"
    c = env["client"]
    rejected = c.post(
        endpoint,
        json.dumps({**data, "maxOutputTokens": 65536}),
        content_type="application/json",
        **env["header"],
    )
    assert rejected.status_code == 400
    response = c.post(
        endpoint, json.dumps(data), content_type="application/json", **env["header"]
    )
    assert response.status_code == 202, response.content
    run = AgentRun._base_manager.get(pk=response.json()["id"])
    assert run.budget_snapshot["maxOutputTokens"] == 16384
    assert (
        c.post(
            endpoint, json.dumps(data), content_type="application/json", **env["header"]
        ).json()["id"]
        == run.id
    )
    assert (
        c.post(
            endpoint,
            json.dumps({**data, "budgetProfile": "materials"}),
            content_type="application/json",
            **env["header"],
        ).status_code
        == 409
    )
    bootstrap = c.get("/api/agent/bootstrap/", **env["header"]).json()
    assert bootstrap["budgets"]["tier"] == "standard"
    assert bootstrap["budgets"]["limits"]["contextWindowTokens"] == 65536


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("user_effort", ["", "medium"])
def test_admin_profile_save_reaches_http_request(setup_agent, settings, user_effort):  # noqa: F811
    requests = []

    class Handler(MockHandler):
        def do_POST(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append((self.path, json.loads(data)))
            self.rfile = io.BytesIO(data)
            super().do_POST()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings.AGENT_MODELS = [
            {
                **settings.AGENT_MODELS[0],
                "qwen": True,
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            }
        ]
        env = setup_agent
        c = Client()
        c.force_login(env["admin"])
        for index, (tokens, effort) in enumerate([(1024, "low"), (2048, "xhigh")]):
            policy = enabled_policy()
            policy["budgetProfiles"]["reasoning"].update(
                maxOutputTokens=tokens, reasoningEffort=effort
            )
            revision = c.get("/api/agent/admin/", **env["header"]).json()["revision"]
            saved = c.put(
                "/api/agent/admin/",
                json.dumps({"policy": policy, "revision": revision}),
                content_type="application/json",
                **env["header"],
            )
            assert saved.status_code == 200, saved.content
            with project_scope(env["scope"]):
                conversation = Conversation.objects.create(
                    owner=env["admin"], mode="chat"
                )
                run = AgentRun.objects.create(
                    conversation=conversation,
                    owner=env["admin"],
                    model="mock",
                    prompt="hello",
                    thinking_mode="deep",
                    reasoning_effort=user_effort,
                    status="running",
                    idempotency_key=f"budget-http-{index}",
                    budget_profile="reasoning",
                    budget_snapshot=resolve_budget(
                        env["admin"], policy, "reasoning", service_window=32768
                    ),
                )
            run_task(run.id)
            run.refresh_from_db()
            assert run.status == "succeeded", run.detail
            sent = [body for path, body in requests if path == "/v1/chat/completions"][
                -1
            ]
            assert sent["max_tokens"] == tokens
            assert sent["chat_template_kwargs"]["reasoning_effort"] == (
                user_effort or effort
            )
            params = json.loads(run.events.filter(kind="parameters").last().text)
            assert params["maxRunSeconds"] == 3600
            assert params["maxContextTokens"] == 32768 - tokens - 256
            assert params["budgetProfile"] == "reasoning"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_native_prompt_passes_request_body_guard(setup_agent):  # noqa: F811
    env = setup_agent
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": enabled_policy()})
    c = Client()
    c.force_login(env["admin"])
    created = c.post(
        "/api/agent/conversations/",
        json.dumps({"mode": "chat"}),
        content_type="application/json",
        **env["header"],
    )
    assert created.status_code == 201, created.content
    response = c.post(
        f"/api/agent/conversations/{created.json()['id']}/runs/",
        json.dumps(
            {
                "model": "mock",
                "prompt": "岩" * 100000,
                "idempotencyKey": "large-budget-prompt",
                "budgetProfile": "materials",
            }
        ),
        content_type="application/json",
        **env["header"],
    )
    assert response.status_code == 202, response.content
