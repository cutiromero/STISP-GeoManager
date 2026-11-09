"""Independent review uses real authorization, bounded evidence and no human vote."""

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from uuid import uuid4

from django.core.exceptions import PermissionDenied
import pytest

from apps.agent import business_flow_review as review
from apps.agent.models import AgentPolicy, AgentWorkflow
from apps.agent.policy import default_policy
from apps.agent.provider import ModelError
from apps.agent.workflow_controls import WorkflowPaused
from apps.compute.packages import ComputeError
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401

# ruff: noqa: F811

REAL_MODEL_WINDOW = review.provider.model_window

NODE = {
    "id": "analyse",
    "title": "分析结果",
    "description": "检查实际资料",
    "kind": "analysis",
    "instruction": "以实际统计支持结论",
    "review": {"ai": True, "human": True, "maxRevisions": 1},
}
EVIDENCE = [
    {"id": "result-1", "kind": "analysis", "title": "实际统计", "result": {"count": 8}}
]
ACCEPT = {
    "decision": "accept",
    "reason": "实际统计支持节点要求",
    "issues": [],
    "repairInstructions": "",
    "evidenceIds": ["result-1"],
}
REJECT = {
    "decision": "request_changes",
    "reason": "统计与结论不一致",
    "issues": [
        {
            "code": "count_mismatch",
            "message": "结果未覆盖全部资料",
            "evidenceIds": ["result-1"],
        }
    ],
    "repairInstructions": "补齐缺少资料的实际统计，再重新提交本节点。",
    "evidenceIds": ["result-1"],
}


@pytest.fixture
def env(setup_agent, monkeypatch):
    data = setup_agent
    with project_scope(data["scope"]):
        workflow = AgentWorkflow.objects.create(
            owner=data["user"],
            model="mock",
            workflow_type="business_flow",
            goal="科研任务",
            status="running",
            idempotency_key=uuid4().hex,
        )
    monkeypatch.setattr(review.provider, "model_window", lambda model: 32768)
    monkeypatch.setattr("apps.agent.context.count_tokens", lambda *args: 123)
    return {**data, "workflow": workflow}


def install_stream(monkeypatch, verdict=ACCEPT, *, after=None):
    calls = []

    def streamed(model, messages, maximum, guard, **options):
        calls.append(
            {
                "model": model,
                "messages": deepcopy(messages),
                "maximum": maximum,
                "options": options,
            }
        )
        guard()
        options["on_usage"](
            {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168}
        )
        yield (
            json.dumps(verdict, ensure_ascii=False)
            if not isinstance(verdict, str)
            else verdict
        )
        if after:
            after()

    monkeypatch.setattr(review.provider, "stream", streamed)
    return calls


def run(env, **options):
    with project_scope(env["scope"]):
        return review.review_node(
            env["workflow"],
            options.pop("node", deepcopy(NODE)),
            options.pop("attempt", 1),
            options.pop("evidence", deepcopy(EVIDENCE)),
            guard=options.pop("guard", lambda: None),
            **options,
        )


def test_independent_requests_have_fresh_context_and_keep_human_gate(env, monkeypatch):
    calls = install_stream(monkeypatch)
    env["workflow"].plan = {
        "messages": [{"role": "system", "content": "EXECUTOR_SYSTEM_SECRET"}]
    }
    env["workflow"].save(update_fields=["plan"])
    records = []
    first = run(env, on_record=records.append)
    second = run(env)
    assert len(calls) == 2
    assert first["audit"]["requestId"] != second["audit"]["requestId"]
    assert first["decision"] == "accept" and first["humanApprovalRequired"] is True
    assert first["audit"]["role"] == "reviewer"
    assert first["audit"]["usage"] == {
        "prompt_tokens": 123,
        "completion_tokens": 45,
        "total_tokens": 168,
    }
    assert calls[0]["maximum"] <= review.MAX_OUTPUT_TOKENS
    assert calls[0]["options"]["structured"] is True
    assert calls[0]["options"]["thinking"] is False
    assert "tools" not in calls[0]["options"]
    assert [item["role"] for item in calls[0]["messages"]] == ["system", "user"]
    assert "EXECUTOR_SYSTEM_SECRET" not in json.dumps(calls[0]["messages"])
    assert records[-1]["status"] == "accepted"
    assert all("messages" not in item and "response" not in item for item in records)
    assert records[0]["requestSha256"] == records[-1]["requestSha256"]


def test_rejection_contains_actionable_feedback_without_hidden_second_request(
    env, monkeypatch
):
    calls = install_stream(monkeypatch, REJECT)
    result = run(env)
    assert result["decision"] == "request_changes"
    assert result["repairInstructions"] == REJECT["repairInstructions"]
    assert result["audit"]["status"] == "changes_requested"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "malicious",
    [
        {**ACCEPT, "humanApproved": True},
        {**ACCEPT, "humanApprovalRequired": False},
        {**ACCEPT, "decision": "approve_human_gate"},
        {**ACCEPT, "evidenceIds": ["invented-result"]},
        {**ACCEPT, "evidenceIds": []},
        {**REJECT, "issues": []},
        {**ACCEPT, "issues": REJECT["issues"]},
        "not json",
    ],
)
def test_untrusted_decisions_fail_closed_once(env, monkeypatch, malicious):
    calls = install_stream(monkeypatch, malicious)
    records = []
    with pytest.raises(ComputeError):
        run(env, on_record=records.append)
    assert len(calls) == 1
    assert records[-1]["status"] == "failed"
    assert all(item["status"] != "accepted" for item in records)


def test_accept_must_cover_all_actual_evidence(env, monkeypatch):
    calls = install_stream(monkeypatch)
    evidence = EVIDENCE + [
        {
            "id": "result-2",
            "kind": "output",
            "title": "质量统计",
            "result": {"count": 4},
        }
    ]
    with pytest.raises(ComputeError, match="不完整"):
        run(env, evidence=evidence)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "change,exception",
    [
        ({"cancel_requested": True}, PermissionDenied),
        ({"pause_requested": True}, WorkflowPaused),
        ({"status": "waiting_approval"}, PermissionDenied),
    ],
)
def test_user_stop_pause_and_human_wait_cannot_be_accepted(
    env, monkeypatch, change, exception
):
    def changed():
        with project_scope(env["scope"]):
            AgentWorkflow.objects.filter(pk=env["workflow"].pk).update(**change)

    calls = install_stream(monkeypatch, after=changed)
    records = []
    with pytest.raises(exception):
        run(env, on_record=records.append)
    assert len(calls) == 1
    assert records[-1]["status"] == "failed"


def test_source_revocation_from_executor_guard_stops_review(env, monkeypatch):
    calls = install_stream(monkeypatch)
    checks = []

    def guard():
        checks.append(True)
        if len(checks) > 1:
            raise PermissionDenied("实际证据已撤权")

    with pytest.raises(PermissionDenied, match="证据已撤权"):
        run(env, guard=guard)
    assert calls == []


def test_current_policy_revocation_stops_a_received_response(env, monkeypatch):
    def revoke():
        value = default_policy()
        value["agentEnabled"] = False
        AgentPolicy.objects.update_or_create(pk=1, defaults={"value": value})

    calls = install_stream(monkeypatch, after=revoke)
    with pytest.raises(PermissionDenied):
        run(env)
    assert len(calls) == 1


def test_model_error_is_not_a_pass_and_is_audited(env, monkeypatch):
    records = []

    def failed(*args, **kwargs):
        raise ModelError("模型连接提前中断")
        yield

    monkeypatch.setattr(review.provider, "stream", failed)
    with pytest.raises(ModelError, match="提前中断"):
        run(env, on_record=records.append)
    assert records[-1]["status"] == "failed"


@pytest.mark.parametrize(
    "node,attempt,evidence",
    [
        (
            {**NODE, "review": {"ai": False, "human": False, "maxRevisions": 0}},
            1,
            EVIDENCE,
        ),
        (NODE, 3, EVIDENCE),
        (NODE, 1, []),
        (NODE, 1, [{"id": "x", "kind": "output", "title": "未运行"}]),
        (NODE, 1, EVIDENCE + EVIDENCE),
    ],
)
def test_disabled_exhausted_and_missing_evidence_do_not_call_model(
    env, monkeypatch, node, attempt, evidence
):
    calls = install_stream(monkeypatch)
    with pytest.raises(ComputeError):
        run(env, node=node, attempt=attempt, evidence=evidence)
    assert calls == []


def test_input_budget_does_not_silently_drop_evidence(env, monkeypatch):
    calls = install_stream(monkeypatch)
    monkeypatch.setattr("apps.agent.context.count_tokens", lambda *args: 1000000)
    with pytest.raises(ModelError):
        run(env)
    assert calls == []


def test_current_budget_ceiling_wins_over_requested_policy(env, monkeypatch):
    calls = install_stream(monkeypatch)
    result = run(env, policy={**default_policy(), "maxOutputTokens": 128})
    assert calls[0]["maximum"] == result["audit"]["outputLimit"] == 128


@pytest.mark.django_db(transaction=True)
def test_real_http_review_request_has_no_execution_tools_or_history(env, settings):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            data = {"data": [{"id": "mock-local", "max_model_len": 32768}]}
            raw = json.dumps(data).encode()
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
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
            else:
                payload = {
                    "choices": [
                        {"delta": {"content": json.dumps(ACCEPT, ensure_ascii=False)}}
                    ],
                    "usage": {
                        "prompt_tokens": 123,
                        "completion_tokens": 45,
                        "total_tokens": 168,
                    },
                }
                raw = b"data: " + json.dumps(payload).encode() + b"\n\ndata: [DONE]\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
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
        # This test intentionally uses the real model window and token HTTP paths.
        with pytest.MonkeyPatch.context() as patcher:
            from apps.agent.provider import count_tokens

            patcher.setattr(review.provider, "model_window", REAL_MODEL_WINDOW)
            patcher.setattr("apps.agent.context.count_tokens", count_tokens)
            result = run(env)
        sent = [body for path, body in requests if path == "/v1/chat/completions"]
        assert len(sent) == 1 and result["decision"] == "accept"
        assert len(sent[0]["messages"]) == 2
        assert "tools" not in sent[0] and sent[0]["response_format"] == {
            "type": "json_object"
        }
        assert (
            sent[0]["messages"]
            == [body for path, body in requests if path == "/tokenize"][0]["messages"]
        )
        assert sent[0]["chat_template_kwargs"] == {
            "enable_thinking": False,
            "reasoning_effort": "low",
        }
        assert result["audit"]["usage"]["total_tokens"] == 168
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.efficiency
def test_review_preflight_and_completion_execute_once(env, monkeypatch):
    counts = {"window": 0, "tokens": 0, "completion": 0}

    def window(model):
        counts["window"] += 1
        return 32768

    def tokens(*args):
        counts["tokens"] += 1
        return 123

    def streamed(model, messages, maximum, guard, **kwargs):
        counts["completion"] += 1
        for character in json.dumps(ACCEPT, ensure_ascii=False):
            yield character

    monkeypatch.setattr(review.provider, "model_window", window)
    monkeypatch.setattr("apps.agent.context.count_tokens", tokens)
    monkeypatch.setattr(review.provider, "stream", streamed)
    assert run(env)["decision"] == "accept"
    assert counts == {"window": 1, "tokens": 1, "completion": 1}


def test_optional_human_gate_remains_optional(env, monkeypatch):
    install_stream(monkeypatch)
    node = deepcopy(NODE)
    node["review"]["human"] = False
    result = run(env, node=node)
    assert result["decision"] == "accept" and result["humanApprovalRequired"] is False


def test_unregistered_review_model_is_not_a_caller_supplied_endpoint(env, monkeypatch):
    calls = install_stream(monkeypatch)
    with pytest.raises(PermissionDenied, match="审核模型已不可用"):
        run(env, model_alias="http://untrusted.example/v1")
    assert calls == []


@pytest.mark.efficiency
def test_model_guard_does_not_fetch_the_large_workflow_plan(env, monkeypatch):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    install_stream(monkeypatch)
    with CaptureQueriesContext(connection) as queries:
        assert run(env)["decision"] == "accept"
    reads = [
        row["sql"]
        for row in queries
        if row["sql"].startswith("SELECT") and '"agent_agentworkflow"' in row["sql"]
    ]
    assert reads
    assert all(
        '"plan"' not in sql and '"parameters"' not in sql and '"evidence"' not in sql
        for sql in reads
    )
