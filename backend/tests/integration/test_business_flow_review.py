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
from apps.agent.business_flow_context import ContextReviewRequired
from apps.agent.workflow_controls import WorkflowPaused
from apps.compute.packages import ComputeError
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401

# ruff: noqa: F811

REAL_MODEL_WINDOW = review.provider.model_window
REAL_COUNT_TOKENS = review.provider.count_tokens

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
    monkeypatch.setattr(review.provider, "count_tokens", lambda *args: 123)
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
        answer = verdict(len(calls)) if callable(verdict) else verdict
        yield (
            json.dumps(answer, ensure_ascii=False)
            if not isinstance(answer, str)
            else answer
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
    assert calls[0]["maximum"] == default_policy()["maxOutputTokens"]
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


@pytest.mark.parametrize("language", ["json", "JSON", ""])
def test_complete_json_fence_preserves_strict_review_and_raw_audit(
    env, monkeypatch, language
):
    import hashlib

    raw = (
        "\n\n```" + language + "\n" + json.dumps(ACCEPT, ensure_ascii=False) + "\n```\n"
    )
    calls = install_stream(monkeypatch, raw)
    result = run(env)
    assert result["decision"] == "accept" and result["humanApprovalRequired"] is True
    assert result["audit"]["responseFormat"] == "json_fence"
    assert result["audit"]["responseSha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "wrapper",
    [
        lambda raw: "解释文字\n```json\n" + raw + "\n```",
        lambda raw: "```json\n" + raw + "\n```\n替用户批准",
        lambda raw: "```json\n" + raw + "\n```\n```json\n" + raw + "\n```",
        lambda raw: "```json\n" + raw,
        lambda raw: "```python\n" + raw + "\n```",
    ],
)
def test_fence_does_not_extract_json_from_prose_or_multiple_responses(
    env, monkeypatch, wrapper
):
    calls = install_stream(monkeypatch, wrapper(json.dumps(ACCEPT, ensure_ascii=False)))
    with pytest.raises(ComputeError):
        run(env)
    assert len(calls) == 2


def test_fenced_model_cannot_insert_a_human_approval(env, monkeypatch):
    calls = install_stream(
        monkeypatch,
        "```json\n"
        + json.dumps({**ACCEPT, "humanApproved": True}, ensure_ascii=False)
        + "\n```",
    )
    with pytest.raises(ComputeError, match="不能代替人工批准"):
        run(env)
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


def test_malformed_review_gets_one_audited_fresh_request_with_diagnostic(
    env, monkeypatch
):
    malformed = '{"decision":"accept","reason":"quote "unescaped""}'
    calls = install_stream(
        monkeypatch, lambda index: malformed if index == 1 else ACCEPT
    )
    records = []
    result = run(env, on_record=records.append)
    assert len(calls) == 2
    first, second = [json.loads(call["messages"][1]["content"]) for call in calls]
    assert first["evidence"] == second["evidence"]
    assert second["revisionFeedback"]["invalidResponse"] == malformed
    assert "Expecting" in second["revisionFeedback"]["diagnostic"]
    assert result["humanApprovalRequired"] is True
    assert result["audit"]["purpose"] == "review_protocol_repair"
    assert result["audit"]["previousRequestId"] != result["audit"]["requestId"]
    assert result["audit"]["timeLimitSeconds"] < records[0]["timeLimitSeconds"]
    assert any(row.get("responsePreview") == malformed for row in records)
    assert env["workflow"].plan["actualModelCallCount"] == 2


def test_repeated_malformed_review_stops_without_an_accepted_decision(env, monkeypatch):
    calls = install_stream(monkeypatch, "not json")
    records = []
    with pytest.raises(review.ReviewSyntaxError):
        run(env, on_record=records.append)
    assert len(calls) == 2
    assert records[-1]["status"] == "failed"
    assert not any(row["status"] == "accepted" for row in records)


def test_minimal_acceptance_omits_only_empty_display_fields(env, monkeypatch):
    install_stream(
        monkeypatch, {key: ACCEPT[key] for key in ("decision", "reason", "evidenceIds")}
    )
    result = run(env)
    assert result["decision"] == "accept"
    assert result["issues"] == [] and result["repairInstructions"] == ""
    assert result["humanApprovalRequired"] is True


def test_thinking_without_body_stays_a_failure_and_retains_actual_activity(
    env, monkeypatch
):
    def thinking_only(model, messages, maximum, guard, **options):
        guard()
        options["on_thinking"]("核对实际统计。")
        yield from ()

    monkeypatch.setattr(review.provider, "stream", thinking_only)
    with pytest.raises(review.ReviewSyntaxError, match="未返回结果正文"):
        run(env)
    records = list(env["workflow"].steps.filter(kind="model_activity"))
    assert len(records) == 2
    assert all(row.output_refs["modelActivity"]["thinkingChars"] > 0 for row in records)
    assert all(row.output_refs["modelResponse"]["content"] == "" for row in records)


def test_protocol_repair_does_not_reset_task_model_budget(env, monkeypatch):
    env["workflow"].max_iterations = 1
    env["workflow"].save(update_fields=["max_iterations"])
    calls = install_stream(monkeypatch, "not json")
    with pytest.raises(ContextReviewRequired):
        run(env)
    assert len(calls) == 1
    assert env["workflow"].plan["actualModelCallCount"] == 1


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
    monkeypatch.setattr(review.provider, "count_tokens", lambda *args: 1000000)
    with pytest.raises(ContextReviewRequired):
        run(env)
    assert calls == []


def test_current_budget_ceiling_wins_over_requested_policy(env, monkeypatch):
    calls = install_stream(monkeypatch)
    result = run(env, policy={**default_policy(), "maxOutputTokens": 128})
    assert calls[0]["maximum"] == result["audit"]["outputLimit"] == 128


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("effort", ["low", "medium", "xhigh"])
def test_real_http_review_request_has_no_execution_tools_or_history(
    env, settings, effort
):
    requests = []
    AgentPolicy.objects.update_or_create(
        pk=1, defaults={"value": {**default_policy(), "reasoningEffort": effort}}
    )

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
            patcher.setattr(review.provider, "count_tokens", REAL_COUNT_TOKENS)
            result = run(env)
        sent = [body for path, body in requests if path == "/v1/chat/completions"]
        assert len(sent) == 1 and result["decision"] == "accept"
        assert len(sent[0]["messages"]) == 2
        assert "tools" not in sent[0] and "response_format" not in sent[0]
        assert (
            sent[0]["messages"]
            == [body for path, body in requests if path == "/tokenize"][0]["messages"]
        )
        assert sent[0]["chat_template_kwargs"] == {
            "enable_thinking": True,
            "reasoning_effort": effort,
        }
        assert (
            sent[0]["chat_template_kwargs"]
            == [body for path, body in requests if path == "/tokenize"][0][
                "chat_template_kwargs"
            ]
        )
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
    monkeypatch.setattr(review.provider, "count_tokens", tokens)
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
