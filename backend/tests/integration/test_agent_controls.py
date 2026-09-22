import io
import json
import threading
from http.server import ThreadingHTTPServer

import pytest
from django.test import Client

from apps.agent.config import ModelConfig
from apps.agent.context import prepare_context
from apps.agent.management.commands.mock_agent_model import MockHandler
from apps.agent.policy import default_policy
from apps.agent.provider import ModelError, stream
from apps.agent.worker import run_task, tool_enabled
from apps.agent.tools import TOOLS
from apps.projects.context import project_scope
from tests.integration.test_agent import new_run, setup_agent  # noqa: F401


@pytest.mark.django_db(transaction=True)
def test_admin_save_reaches_real_http_model_request(setup_agent, settings):  # noqa: F811
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
        client = Client()
        client.force_login(env["admin"])
        for index, (output, temperature, top_p, effort) in enumerate(
            [(512, 0.4, 0.8, "low"), (1024, 0.7, 0.95, "medium")]
        ):
            policy = default_policy()
            policy.update(
                maxOutputTokens=output,
                temperature=temperature,
                topP=top_p,
                reasoningEffort=effort,
            )
            revision = client.get("/api/agent/admin/", **env["header"]).json()[
                "revision"
            ]
            response = client.put(
                "/api/agent/admin/",
                json.dumps({"policy": policy, "revision": revision}),
                content_type="application/json",
                **env["header"],
            )
            assert response.status_code == 200, response.content
            with project_scope(env["scope"]):
                env["conversation"].mode = "chat"
                env["conversation"].save()
                from apps.agent.models import AgentRun

                run = AgentRun.objects.create(
                    conversation=env["conversation"],
                    owner=env["user"],
                    model="mock",
                    prompt="test",
                    status="running",
                    thinking_mode="deep",
                    idempotency_key=f"controls-{index}",
                )
                run.idempotency_key = f"controls-{index}"
                run.save()
            run_task(run.id)
            run.refresh_from_db()
            assert run.status == "succeeded", run.detail
            sent = [body for path, body in requests if path == "/v1/chat/completions"][
                -1
            ]
            assert (sent["max_tokens"], sent["temperature"], sent["top_p"]) == (
                output,
                temperature,
                top_p,
            )
            assert sent["chat_template_kwargs"] == {
                "enable_thinking": True,
                "reasoning_effort": effort,
            }
            counted = [body for path, body in requests if path == "/tokenize"][-1]
            assert counted["messages"] == sent["messages"]
            assert counted["chat_template_kwargs"] == sent["chat_template_kwargs"]
            params = json.loads(run.events.filter(kind="parameters").last().text)
            assert params["maxOutputTokens"] == output
            assert params["contextWindowTokens"] == 32768
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_length_keeps_unclosed_implicit_reasoning_and_usage(monkeypatch):
    class Connection:
        sock = None

        def __init__(self, *a, **k):
            pass

        def connect(self):
            pass

        def request(self, *a, **k):
            pass

        def close(self):
            pass

        def getresponse(self):
            chunks = [
                {
                    "choices": [
                        {
                            "delta": {"content": "synthetic segment"},
                            "finish_reason": None,
                        }
                    ]
                },
                {"choices": [{"delta": {}, "finish_reason": "length"}]},
                {"choices": [], "usage": {"completion_tokens": 128}},
            ]
            response = io.BytesIO(
                b"".join(b"data: " + json.dumps(x).encode() + b"\n\n" for x in chunks)
                + b"data: [DONE]\n"
            )
            response.status = 200
            return response

    monkeypatch.setattr("apps.agent.provider.http.client.HTTPConnection", Connection)
    reasoning, usage = [], []
    model = ModelConfig("q", "Q", "http://127.0.0.1:1/v1", "q", qwen=True)
    with pytest.raises(ModelError, match="已生成内容已保留"):
        list(
            stream(
                model,
                [],
                128,
                lambda: None,
                thinking=True,
                on_thinking=reasoning.append,
                on_usage=usage.append,
            )
        )
    assert "".join(reasoning) == "synthetic segment"
    assert usage == [{"completion_tokens": 128}]


def test_actual_count_trims_history_then_attachment_preserving_question(monkeypatch):
    monkeypatch.setattr(
        "apps.agent.context.count_tokens",
        lambda model, messages, *args: len(json.dumps(messages, ensure_ascii=False)),
    )
    p = {
        "maxOutputTokens": 256,
        "maxContextTokens": 600,
        "maxContextBytes": 10000,
        "reasoningEffort": "low",
    }
    current = {
        "role": "user",
        "content": [
            {"type": "text", "text": "CURRENT\n\n【附件：file】\n" + "x" * 2000}
        ],
    }
    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "old" * 100},
        {"role": "assistant", "content": "answer" * 100},
        current,
    ]
    count, trimmed = prepare_context(messages, current, None, p, 1200, True)
    assert trimmed and count <= 600
    assert len(messages) == 2 and current["content"][0]["text"].startswith(
        "CURRENT\n\n"
    )


def test_disabled_tools_not_advertised():
    from types import SimpleNamespace

    p = {
        "internetEnabled": False,
        "systemInfoEnabled": True,
        "operatorEnabled": True,
        "allowDocuments": True,
        "allowCompare": True,
    }
    run = SimpleNamespace(internet_enabled=True)
    assert not tool_enabled(TOOLS["search_web"], p, run)
    assert tool_enabled(TOOLS["execute_operator"], p, run)
