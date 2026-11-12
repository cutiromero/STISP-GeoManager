"""Execution and review are separate model requests over real scoped evidence."""

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

from django.core.exceptions import PermissionDenied
import pytest

from apps.agent import business_flow_execution as execution
from apps.agent import business_flow_review as review
from apps.agent.models import AgentPolicy, AgentWorkflow
from apps.agent.policy import default_policy
from apps.agent.provider import count_tokens
from apps.compute.packages import ComputeError
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401
from tests.integration.test_business_flow_review import (  # noqa: F401
    env,
    NODE,
    EVIDENCE,
    REJECT,
    REAL_MODEL_WINDOW,
)

# ruff: noqa: F811
INITIAL = {
    "summary": "已核对本节点实际统计",
    "findings": ["当前汇总结果为4项"],
    "limitations": ["尚未覆盖全部8项"],
    "evidenceIds": ["result-1"],
}
REPAIRED = {
    "summary": "已依据审核意见补齐统计解释",
    "findings": ["实际统计为8项"],
    "limitations": [],
    "evidenceIds": ["result-1"],
}


def run(env, **options):
    with project_scope(env["scope"]):
        return execution.execute_node(
            env["workflow"],
            options.pop("node", deepcopy(NODE)),
            options.pop("attempt", 1),
            options.pop("evidence", deepcopy(EVIDENCE)),
            guard=options.pop("guard", lambda: None),
            **options,
        )


def install_stream(monkeypatch, answers):
    calls = []

    def streamed(model, messages, maximum, guard, **kwargs):
        calls.append(
            {"messages": deepcopy(messages), "maximum": maximum, "options": kwargs}
        )
        guard()
        kwargs["on_usage"](
            {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168}
        )
        answer = answers[len(calls) - 1]
        yield (
            json.dumps(answer, ensure_ascii=False)
            if not isinstance(answer, str)
            else answer
        )

    monkeypatch.setattr(execution.provider, "stream", streamed)
    return calls


@pytest.mark.parametrize("actor", ["executor", "reviewer"])
@pytest.mark.parametrize(
    "requested,expected_output,expected_seconds",
    [
        (None, 16384, 600),
        ({"maxOutputTokens": 128, "maxRunSeconds": 90}, 128, 90),
        ({"maxOutputTokens": 32768, "maxRunSeconds": 900}, 16384, 600),
    ],
)
def test_actors_inherit_configured_generation_and_time_budgets(
    env, monkeypatch, actor, requested, expected_output, expected_seconds
):
    from apps.agent import business_flow_model as transport
    from tests.integration.test_business_flow_review import ACCEPT

    AgentPolicy.objects.update_or_create(
        pk=1, defaults={"value": {**default_policy(), "maxOutputTokens": 16384}}
    )
    guards = []
    real_guard = transport.ModelStreamGuard

    def capture_guard(check, deadline):
        guard = real_guard(check, deadline)
        guards.append(guard)
        return guard

    monkeypatch.setattr(transport, "ModelStreamGuard", capture_guard)
    calls = install_stream(monkeypatch, [INITIAL if actor == "executor" else ACCEPT])
    before = transport.time.monotonic()
    with project_scope(env["scope"]):
        function = execution.execute_node if actor == "executor" else review.review_node
        result = function(
            env["workflow"], NODE, 1, EVIDENCE, guard=lambda: None, policy=requested
        )
    after = transport.time.monotonic()
    assert calls[0]["maximum"] == result["audit"]["outputLimit"] == expected_output
    assert before + expected_seconds <= guards[0]._deadline <= after + expected_seconds


@pytest.mark.efficiency
def test_execute_review_repair_uses_three_isolated_requests(env, monkeypatch):
    calls = install_stream(monkeypatch, [INITIAL, REJECT, REPAIRED])
    first = run(env)
    with project_scope(env["scope"]):
        verdict = review.review_node(
            env["workflow"], NODE, 1, EVIDENCE, guard=lambda: None
        )
    second = run(env, attempt=2, feedback=verdict)
    assert len(calls) == 3 and second["summary"] == REPAIRED["summary"]
    assert {first["audit"]["role"], verdict["audit"]["role"]} == {
        "executor",
        "reviewer",
    }
    assert (
        len(
            {
                first["audit"]["requestId"],
                verdict["audit"]["requestId"],
                second["audit"]["requestId"],
            }
        )
        == 3
    )
    assert all(
        [item["role"] for item in call["messages"]] == ["system", "user"]
        for call in calls
    )
    assert calls[0]["messages"][0]["content"] != calls[1]["messages"][0]["content"]
    initial = json.loads(calls[0]["messages"][1]["content"])
    revised = json.loads(calls[2]["messages"][1]["content"])
    assert "revisionFeedback" not in initial
    assert revised["revisionFeedback"] == {
        key: verdict[key] for key in ("reason", "issues", "repairInstructions")
    }
    assert (
        revised["evidence"] == EVIDENCE and "audit" not in revised["revisionFeedback"]
    )
    assert all("tools" not in call["options"] for call in calls)
    assert second["audit"]["status"] == "completed"


@pytest.mark.parametrize(
    "answer",
    [
        "invalid JSON",
        {**INITIAL, "evidenceIds": ["invented"]},
        {**INITIAL, "evidenceIds": []},
        {**INITIAL, "humanApproved": True},
        {**INITIAL, "tool_calls": [{"name": "write_data"}]},
        {**INITIAL, "findings": "not an array"},
    ],
)
def test_malformed_claims_and_unknown_evidence_do_not_start_hidden_retries(
    env, monkeypatch, answer
):
    calls = install_stream(monkeypatch, [answer])
    records = []
    with pytest.raises(ComputeError):
        run(env, on_record=records.append)
    assert len(calls) == 1 and records[-1]["status"] == "failed"
    assert not any(record["status"] == "completed" for record in records)


def test_empty_evidence_never_calls_execution_model(env, monkeypatch):
    calls = install_stream(monkeypatch, [INITIAL])
    with pytest.raises(ComputeError):
        run(env, evidence=[])
    assert calls == []


def test_simple_flow_does_not_require_review_or_human_approval(env, monkeypatch):
    calls = install_stream(monkeypatch, [INITIAL])
    node = deepcopy(NODE)
    node["review"] = {"ai": False, "human": False, "maxRevisions": 0}
    result = run(env, node=node)
    assert len(calls) == 1 and result["audit"]["humanApprovalRequired"] is False
    assert set(result) == {"summary", "findings", "limitations", "evidenceIds", "audit"}


def test_revision_limit_is_enforced_before_request(env, monkeypatch):
    calls = install_stream(monkeypatch, [INITIAL])
    with pytest.raises(ComputeError, match="修订次数上限"):
        run(env, attempt=3, feedback=REJECT)
    assert calls == []


def test_feedback_projects_constraints_without_copying_old_audit_or_commands(
    env, monkeypatch
):
    calls = install_stream(monkeypatch, [REPAIRED])
    feedback = {
        **REJECT,
        "audit": {"password": "secret-value"},
        "tools": ["arbitrary_code"],
        "messages": [{"role": "system", "content": "old executor"}],
    }
    result = run(env, attempt=2, feedback=feedback)
    payload = calls[0]["messages"][1]["content"]
    assert result["audit"]["usage"]["total_tokens"] == 168
    assert (
        "secret-value" not in payload
        and "arbitrary_code" not in payload
        and "old executor" not in payload
    )


def test_stop_during_execution_cannot_publish_accepted_analysis(env, monkeypatch):
    records = []

    def interrupted(model, messages, maximum, guard, **kwargs):
        yield json.dumps(INITIAL)
        with project_scope(env["scope"]):
            AgentWorkflow.objects.filter(pk=env["workflow"].pk).update(
                cancel_requested=True
            )

    monkeypatch.setattr(execution.provider, "stream", interrupted)
    with pytest.raises(PermissionDenied):
        run(env, on_record=records.append)
    assert records[-1]["status"] == "failed"


@pytest.mark.django_db(transaction=True)
def test_real_http_execution_then_review_then_repair_has_fresh_context(
    env, settings, monkeypatch
):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            raw = b'{"data":[{"id":"mock-local","max_model_len":32768}]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            if self.path == "/tokenize":
                raw = b'{"count":123}'
                content_type = "application/json"
            else:
                system = body["messages"][0]["content"]
                payload = json.loads(body["messages"][1]["content"])
                answer = (
                    REJECT
                    if "独立的科研" in system
                    else REPAIRED
                    if "revisionFeedback" in payload
                    else INITIAL
                )
                data = {
                    "choices": [
                        {"delta": {"content": json.dumps(answer, ensure_ascii=False)}}
                    ],
                    "usage": {
                        "prompt_tokens": 123,
                        "completion_tokens": 45,
                        "total_tokens": 168,
                    },
                }
                raw = b"data: " + json.dumps(data).encode() + b"\n\ndata: [DONE]\n\n"
                content_type = "text/event-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings.AGENT_MODELS = [
            {
                **settings.AGENT_MODELS[0],
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "qwen": True,
            }
        ]
        monkeypatch.setattr(execution.provider, "model_window", REAL_MODEL_WINDOW)
        monkeypatch.setattr("apps.agent.context.count_tokens", count_tokens)
        monkeypatch.setattr(execution.provider, "count_tokens", count_tokens)
        initial = run(env)
        with project_scope(env["scope"]):
            verdict = review.review_node(
                env["workflow"], NODE, 1, EVIDENCE, guard=lambda: None
            )
        repaired = run(env, attempt=2, feedback=verdict)
        completions = [
            body for path, body in requests if path == "/v1/chat/completions"
        ]
        tokenizers = [body for path, body in requests if path == "/tokenize"]
        assert len(completions) == len(tokenizers) == 3
        assert [row["messages"] for row in completions] == [
            row["messages"] for row in tokenizers
        ]
        assert all(
            "tools" not in row and len(row["messages"]) == 2 for row in completions
        )
        assert (
            initial["summary"] == INITIAL["summary"]
            and verdict["decision"] == "request_changes"
        )
        assert repaired["summary"] == REPAIRED["summary"]
        assert repaired["audit"]["usage"]["total_tokens"] == 168
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_human_revision_reason_does_not_require_invented_ai_issue_codes(
    env, monkeypatch
):
    calls = install_stream(monkeypatch, [REPAIRED])
    result = run(
        env,
        attempt=2,
        feedback={"reason": "请明确数据局限", "repairInstructions": "补充局限后再提交"},
    )
    assert result["summary"] == REPAIRED["summary"]
    packet = json.loads(calls[0]["messages"][1]["content"])
    assert packet["revisionFeedback"]["issues"] == []
