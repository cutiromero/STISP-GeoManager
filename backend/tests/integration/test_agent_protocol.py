import io
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from apps.agent.config import ModelConfig, registry
from apps.agent.management.commands.mock_agent_model import MockHandler
from apps.agent.models import AgentAttachment, AgentRun
from apps.agent.policy import default_policy
from apps.agent.provider import stream
from apps.agent.worker import attach_inputs, context_messages, run_task
from apps.agent.worker import parse_agent_command
from apps.projects.context import project_scope
from tests.integration.test_agent import new_run, setup_agent  # noqa: F401


@pytest.mark.parametrize("resource_id", ["9", 9, "09", "0", "-1", "9.0", [9], True])
def test_resource_id_normalization_preserves_strict_validation(resource_id):
    command = parse_agent_command(
        json.dumps(
            {"action": "describe_resource", "arguments": {"resourceId": resource_id}}
        )
    )
    result = command["arguments"]["resourceId"]
    expected = 9 if resource_id == "9" else resource_id
    assert result == expected and type(result) is type(expected)


@pytest.mark.parametrize(
    "prefix,thought",
    [
        ("", ""),
        ("   ", ""),
        ("<think>reason</think>", "reason"),
        ("reason</think>", "reason"),
    ],
)
def test_structured_deep_response_keeps_command_out_of_thinking(
    monkeypatch, prefix, thought
):
    command = '{"action":"final","answer":"完成"}'
    text = prefix + command

    class Connection:
        sock = None

        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            pass

        def request(self, *args, **kwargs):
            pass

        def close(self):
            pass

        def getresponse(self):
            # Single-character chunks exercise split think tags and JSON prefixes.
            data = b"".join(
                b"data: "
                + json.dumps({"choices": [{"delta": {"content": char}}]}).encode()
                + b"\n\n"
                for char in text
            )
            response = io.BytesIO(data + b"data: [DONE]\n")
            response.status = 200
            return response

    monkeypatch.setattr("apps.agent.provider.http.client.HTTPConnection", Connection)
    thoughts = []
    model = ModelConfig("q", "Q", "http://127.0.0.1:1/v1", "q", qwen=True)
    result = "".join(
        stream(
            model,
            [],
            1024,
            lambda: None,
            structured=True,
            thinking=True,
            on_thinking=thoughts.append,
        )
    )
    assert json.loads(result) == json.loads(command)
    assert "".join(thoughts) == thought


@pytest.mark.django_db(transaction=True)
def test_deep_agent_direct_json_executes_tools_and_keeps_current_selection(
    setup_agent,  # noqa: F811
    settings,
):
    env = setup_agent
    captured = []

    class Handler(MockHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/v1/chat/completions":
                captured.append(json.loads(json.dumps(body)))
                # Reproduce vLLM JSON mode returning direct JSON despite deep mode.
                body["chat_template_kwargs"]["enable_thinking"] = False
            data = json.dumps(body).encode()
            self.headers.replace_header("Content-Length", str(len(data)))
            self.rfile = io.BytesIO(data)
            super().do_POST()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings.AGENT_MODELS = [
        {
            **settings.AGENT_MODELS[0],
            "qwen": True,
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
        }
    ]
    try:
        with project_scope(env["scope"]):
            AgentRun.objects.create(
                conversation=env["conversation"],
                owner=env["user"],
                model="mock",
                prompt="文件多大",
                answer="此前资源不同。",
                status="succeeded",
                resource_ids=[999],
                idempotency_key="old-selection",
            )
            run = new_run(env, resource_ids=[env["resource"].id], thinking_mode="deep")
            run.prompt = "分析该文件"
            run.save()
            attachment = AgentAttachment.objects.create(
                conversation=env["conversation"],
                owner=env["user"],
                name="说明.txt",
                path="unused",
                mime_type="text/plain",
                kind="document",
                checksum="selection-test",
                extracted_text="样地说明",
            )
            run.attachment_ids = [attachment.id]
            messages = attach_inputs(
                context_messages(run, default_policy(), registry()["mock"]),
                run,
                registry()["mock"],
                default_policy(),
            )
            current_text = messages[-1]["content"][0]["text"]
            assert f"本轮明确选择的资源ID：[{env['resource'].id}]" in current_text
            assert (
                "本轮用户问题：\n分析该文件" in current_text
                and "样地说明" in current_text
            )
        run_task(run.id)
        run.refresh_from_db()
        assert run.status == "succeeded", run.detail
        assert run.events.filter(kind="tool_completed").count() == 3
        assert not run.events.filter(kind="thinking").exists()
        assert run.answer and run.evidence
        assert all(e["resourceId"] == env["resource"].id for e in run.evidence)
        assert all(b["chat_template_kwargs"]["enable_thinking"] for b in captured)
        assert (
            f"本轮明确选择的资源ID：[{env['resource'].id}]"
            in captured[0]["messages"][-1]["content"]
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
