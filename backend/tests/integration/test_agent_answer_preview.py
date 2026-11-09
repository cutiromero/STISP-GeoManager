"""Real worker lifecycle and durable API previews before final validation."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest
from django.core.exceptions import PermissionDenied

from apps.agent import worker
from apps.agent.answer_preview import (
    PREVIEW_EVENT_KIND,
    stored_answer_preview,
    MAX_PREVIEW_CHARACTERS,
)
from apps.agent.models import AgentRun, RunEvent
from apps.agent.provider import ModelError
from apps.projects.context import project_scope
from apps.projects.models import ProjectMembership
from tests.integration.test_agent import setup_agent as setup_agent


@pytest.fixture
def env(setup_agent, monkeypatch):
    monkeypatch.setattr("apps.agent.research_intents.process", lambda *args: None)
    monkeypatch.setattr(worker, "model_window", lambda model: 32768)
    monkeypatch.setattr(worker, "prepare_context", lambda *args: (1, False))
    return setup_agent


def make_run(env, *, mode="agent", **values):
    env["conversation"].mode = mode
    env["conversation"].save(update_fields=["mode"])
    with project_scope(env["scope"]):
        return AgentRun.objects.create(
            owner=env["user"],
            conversation=env["conversation"],
            model="mock",
            prompt="说明一次普通交流",
            status="running",
            idempotency_key="preview-" + str(env["conversation"].runs.count()),
            **values,
        )


def read_run(env, run):
    response = env["client"].get(f"/api/agent/runs/{run.id}/", **env["header"])
    assert response.status_code == 200, response.content
    return response.json()["run"]


@pytest.mark.parametrize("mode", ["agent", "chat"])
def test_json_preview_is_persisted_and_readable_before_provider_finishes(
    env, monkeypatch, mode
):
    run = make_run(env, mode=mode)
    observed = []

    def generate(*args, **kwargs):
        yield '{"action":"final","answer":"第一段'
        current = read_run(env, run)
        observed.append(current["answerPreview"])
        assert current["status"] == "running" and current["answer"] == ""
        assert not run.events.filter(kind="text").exists()
        yield '，第二段"}'

    monkeypatch.setattr(worker, "stream", generate)
    worker.run_task(run.id)
    current = read_run(env, run)
    assert observed == ["第一段"]
    assert current["status"] == "succeeded"
    assert current["answer"] == "第一段，第二段"
    assert current["answerPreview"] == ""
    assert list(run.events.filter(kind="text").values_list("text", flat=True)) == [
        "第一段，第二段"
    ]
    assert run.events.filter(kind=PREVIEW_EVENT_KIND).last().text == ""


def test_plain_chat_streams_without_waiting_for_json(env, monkeypatch):
    run = make_run(env, mode="chat")

    def generate(*args, **kwargs):
        yield "普通正文先到"
        assert read_run(env, run)["answerPreview"] == "普通正文先到"
        yield "，后续补充。"

    monkeypatch.setattr(worker, "stream", generate)
    worker.run_task(run.id)
    run.refresh_from_db()
    assert (run.status, run.answer) == ("succeeded", "普通正文先到，后续补充。")


@pytest.mark.parametrize(
    "failure,status",
    [
        (ModelError("上游断流"), "failed"),
        (worker.Cancelled(), "cancelled"),
        (PermissionDenied("权限失效"), "interrupted"),
    ],
)
def test_failure_or_stop_keeps_only_already_authorized_snapshots(
    env, monkeypatch, failure, status
):
    run = make_run(env)
    monkeypatch.setattr(worker.time, "monotonic", lambda: 100.0)

    def generate(*args, **kwargs):
        yield '{"action":"final","answer":"已保存的开头'
        assert read_run(env, run)["answerPreview"] == "已保存的开头"
        yield "尚未获准落盘的尾部"
        raise failure

    monkeypatch.setattr(worker, "stream", generate)
    worker.run_task(run.id)
    current = read_run(env, run)
    assert current["status"] == status
    assert current["answer"] == ""
    assert current["answerPreview"] == "已保存的开头"
    assert not run.events.filter(kind="text").exists()


def test_real_project_revocation_prevents_new_preview_writes(env, monkeypatch):
    run = make_run(env)

    def generate(*args, **kwargs):
        yield '{"action":"final","answer":"撤权前已保存'
        ProjectMembership.objects.filter(
            project=env["project"], user=env["user"]
        ).delete()
        yield "撤权后" * 300

    monkeypatch.setattr(worker, "stream", generate)
    worker.run_task(run.id)
    run.refresh_from_db()
    assert run.status == "interrupted" and run.answer == ""
    assert stored_answer_preview(run) == "撤权前已保存"
    denied = env["client"].get(f"/api/agent/runs/{run.id}/", **env["header"])
    assert denied.status_code in {403, 404}


def test_rejected_citations_and_next_tool_reset_the_previous_preview(env, monkeypatch):
    run = make_run(env)
    calls = []

    def generate(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            yield '{"action":"final","answer":"尚未核验的[证据 999]'
            assert read_run(env, run)["answerPreview"] == "尚未核验的[证据 999]"
            yield '"}'
        elif len(calls) == 2:
            assert read_run(env, run)["answerPreview"] == ""
            yield '{"action":"search_resources","arguments":{"query":"资料"}}'
        else:
            assert read_run(env, run)["answerPreview"] == ""
            yield '{"action":"final","answer":"核查后的完整回答"}'

    monkeypatch.setattr(worker, "stream", generate)
    monkeypatch.setattr(worker, "execute", lambda *args: ({"items": []}, []))
    worker.run_task(run.id)
    current = read_run(env, run)
    assert len(calls) == 3
    assert current["status"] == "succeeded" and current["answer"] == "核查后的完整回答"
    previews = list(
        run.events.filter(kind=PREVIEW_EVENT_KIND).values_list("text", flat=True)
    )
    assert "" in previews and not any("arguments" in text for text in previews)
    assert list(run.events.filter(kind="text").values_list("text", flat=True)) == [
        "核查后的完整回答"
    ]


def test_preview_does_not_bypass_unread_compute_output_validation(env, monkeypatch):
    state = {
        "messages": [{"role": "user", "content": "解释计算输出"}],
        "currentIndex": 0,
        "outputIds": [88],
    }
    run = make_run(env, execution_state=state)
    monkeypatch.setattr(
        worker,
        "stream",
        lambda *args, **kwargs: iter(
            ['{"action":"final","answer":"没有实际读取输出的解释"}']
        ),
    )
    worker.run_task(run.id)
    current = read_run(env, run)
    assert current["status"] == "failed" and current["answer"] == ""
    assert current["answerPreview"] == ""
    assert not run.events.filter(kind="text").exists()


def test_answer_past_old_preview_limit_streams_without_rewriting_context(
    env, monkeypatch
):
    state = {
        "messages": [{"role": "user", "content": "已记录的工具背景" * 10000}],
        "currentIndex": 0,
        "actions": 0,
    }
    run = make_run(env, execution_state=state)
    answer = "遥" * 26000

    def generate(*args, **kwargs):
        yield '{"action":"final","answer":"'
        for offset in range(0, len(answer), 1000):
            yield answer[offset : offset + 1000]
        assert read_run(env, run)["answerPreview"] == answer
        yield '"}'

    monkeypatch.setattr(worker, "stream", generate)
    worker.run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded" and run.answer == answer
    assert run.execution_state == state
    assert all(
        len(text) <= MAX_PREVIEW_CHARACTERS
        for text in run.events.filter(kind=PREVIEW_EVENT_KIND).values_list(
            "text", flat=True
        )
    )


def test_many_tiny_provider_chunks_are_batched_for_preview_persistence(
    env, monkeypatch
):
    run = make_run(env)
    monkeypatch.setattr(worker.time, "monotonic", lambda: 100.0)

    def generate(*args, **kwargs):
        yield '{"action":"final","answer":"'
        yield from ("字" for _ in range(500))
        yield '"}'

    monkeypatch.setattr(worker, "stream", generate)
    worker.run_task(run.id)
    run.refresh_from_db()
    snapshots = [
        text
        for text in run.events.filter(kind=PREVIEW_EVENT_KIND).values_list(
            "text", flat=True
        )
        if text
    ]
    assert run.status == "succeeded" and run.answer == "字" * 500
    assert len(snapshots) <= 3


@pytest.mark.parametrize("content", ["thinking", "preview"])
def test_slow_authorization_and_persistence_do_not_throttle_tiny_chunks(
    env, monkeypatch, content
):
    run = make_run(env, thinking_mode="deep")
    clock, checks, observed = [100.0], [], {}
    monkeypatch.setattr(worker.time, "monotonic", lambda: clock[0])
    original_guard, original_event = worker.guard, worker.event

    def slow_guard(*args, **kwargs):
        checks.append(clock[0])
        clock[0] += 0.75
        return original_guard(*args, **kwargs)

    def slow_event(run, kind, text):
        original_event(run, kind, text)
        if kind in {"thinking", PREVIEW_EVENT_KIND}:
            clock[0] += 0.25

    def generate(model, messages, maximum, guard, **options):
        started, baseline = clock[0], len(checks)
        if content == "preview":
            yield '{"action":"final","answer":"'
        for _ in range(1000):
            clock[0] += 0.001
            guard()
            if content == "thinking":
                options["on_thinking"]("字")
            else:
                yield "字"
        observed.update(checks=len(checks) - baseline, seconds=clock[0] - started)
        yield (
            '{"action":"final","answer":"已完成"}' if content == "thinking" else '"}'
        )

    monkeypatch.setattr(worker, "guard", slow_guard)
    monkeypatch.setattr(worker, "event", slow_event)
    monkeypatch.setattr(worker, "stream", generate)
    worker.run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded"
    assert observed["checks"] < 20 and observed["seconds"] < 20
    if content == "thinking":
        assert (
            "".join(run.events.filter(kind="thinking").values_list("text", flat=True))
            == "字" * 1000
        )
        assert run.events.filter(kind="thinking").count() < 20
    else:
        assert run.answer == "字" * 1000
        assert run.events.filter(kind=PREVIEW_EVENT_KIND).count() < 20


def test_thinking_final_flush_rechecks_cancellation_without_publishing_tail(
    env, monkeypatch
):
    run = make_run(env, thinking_mode="deep")
    monkeypatch.setattr(worker.time, "monotonic", lambda: 100.0)

    def generate(model, messages, maximum, guard, **options):
        guard()
        options["on_thinking"]("已保存")
        options["on_thinking"]("尚未保存的尾部")
        AgentRun.objects.filter(pk=run.pk).update(cancel_requested=True)
        yield '{"action":"final","answer":"不能发布"}'

    monkeypatch.setattr(worker, "stream", generate)
    worker.run_task(run.id)
    run.refresh_from_db()
    assert run.status == "cancelled" and run.answer == ""
    assert list(run.events.filter(kind="thinking").values_list("text", flat=True)) == [
        "已保存"
    ]


def test_only_final_answers_enter_future_model_context(env):
    previous = make_run(env, answer="已经核验的正式回答")
    previous.status = "succeeded"
    previous.save(update_fields=["status"])
    RunEvent.objects.create(
        run=previous, kind=PREVIEW_EVENT_KIND, text="不可信预览，永不进入模型上下文"
    )
    current = make_run(env)
    with project_scope(env["scope"]):
        messages = worker.context_messages(
            current, worker.policy(), worker.registry()["mock"]
        )
    text = json.dumps(messages, ensure_ascii=False)
    assert "已经核验的正式回答" in text
    assert "不可信预览" not in text
    assert stored_answer_preview(previous) == ""


def test_research_thinking_uses_the_existing_worker_buffer(env, monkeypatch):
    run = make_run(env)

    def process(run, user, policy, guard, event):
        event("thinking", "真实思考片段一")
        event("thinking", "真实思考片段二")
        return "角色判断已完成"

    monkeypatch.setattr("apps.agent.research_intents.process", process)
    worker.run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded"
    assert (
        "".join(run.events.filter(kind="thinking").values_list("text", flat=True))
        == "真实思考片段一真实思考片段二"
    )


def test_short_thinking_is_visible_before_body_and_terminal_status(
    env, settings, monkeypatch
):
    settings.AGENT_MODELS[0]["qwen"] = True
    run = make_run(env, thinking_mode="deep")
    monkeypatch.setattr(worker.time, "monotonic", lambda: 100.0)

    def generate(*args, **kwargs):
        kwargs["on_thinking"]("先核查")
        assert list(
            run.events.filter(kind="thinking").values_list("text", flat=True)
        ) == ["先核查"]
        kwargs["on_thinking"]("再作答。")
        assert list(
            run.events.filter(kind="thinking").values_list("text", flat=True)
        ) == ["先核查"]
        yield '{"action":"final","answer":"正文首段'
        current = read_run(env, run)
        assert current["thinkingText"] == "先核查再作答。"
        assert len(current["thinkingText"]) == 7
        assert current["status"] == "running" and current["answer"] == ""
        yield '与后续正文"}'

    monkeypatch.setattr(worker, "stream", generate)
    worker.run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded" and run.answer == "正文首段与后续正文"


@pytest.mark.parametrize(
    "failure", [ModelError("断流"), worker.Cancelled(), PermissionDenied("撤权")]
)
def test_failed_run_does_not_flush_pending_thinking_after_stop(
    env, monkeypatch, failure
):
    run = make_run(env)
    monkeypatch.setattr(worker.time, "monotonic", lambda: 100.0)

    def generate(*args, **kwargs):
        kwargs["on_thinking"]("已授权保存")
        kwargs["on_thinking"]("尚未落盘的尾部")
        raise failure
        yield

    monkeypatch.setattr(worker, "stream", generate)
    worker.run_task(run.id)
    run.refresh_from_db()
    assert run.status in {"failed", "cancelled", "interrupted"}
    assert list(run.events.filter(kind="thinking").values_list("text", flat=True)) == [
        "已授权保存"
    ]


@pytest.mark.django_db(transaction=True)
def test_actual_http_stream_persists_preview_while_upstream_waits(
    env, settings, monkeypatch
):
    release = threading.Event()
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()

            def frame(text):
                payload = {"choices": [{"delta": {"content": text}}]}
                self.wfile.write(("data: " + json.dumps(payload) + "\n\n").encode())
                self.wfile.flush()

            frame('{"action":"final","answer":"真实HTTP首段')
            if not release.wait(5):
                return
            frame('与后续正文"}')
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_event = worker.event

    def event(run, kind, text):
        original_event(run, kind, text)
        if kind == PREVIEW_EVENT_KIND and text == "真实HTTP首段":
            run.refresh_from_db()
            observed.append((run.status, run.answer, stored_answer_preview(run)))
            release.set()

    try:
        settings.AGENT_MODELS[0]["base_url"] = (
            f"http://127.0.0.1:{server.server_port}/v1"
        )
        monkeypatch.setattr(worker, "event", event)
        run = make_run(env)
        worker.run_task(run.id)
        run.refresh_from_db()
        assert observed == [("running", "", "真实HTTP首段")]
        assert run.status == "succeeded", run.detail
        assert run.answer == "真实HTTP首段与后续正文"
        assert stored_answer_preview(run) == ""
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(2)
    assert not thread.is_alive()
