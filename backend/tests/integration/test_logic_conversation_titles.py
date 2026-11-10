from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
import threading

import pytest
from django.core.management import call_command

from apps.agent import conversation_titles as titles, provider
from apps.agent.conversation_titles import DEFAULT_LOGIC_PROMPT, update_logic_title
from apps.agent.models import AgentRun
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent as setup_agent


@pytest.fixture
def logic(setup_agent, monkeypatch):
    monkeypatch.setattr(provider, "model_window", lambda model: 32768)
    monkeypatch.setattr(
        "apps.agent.context.count_tokens",
        lambda model, messages, *args: sum(len(row["content"]) for row in messages),
    )
    env = setup_agent
    env["project"].code = "02"
    env["project"].save(update_fields=["code"])
    env["resource"].name = "海德乌拉岩性图"
    env["resource"].save(update_fields=["name"])
    return env


def make_run(env, prompt="你好", **values):
    with project_scope(env["scope"]):
        return AgentRun.objects.create(
            owner=env["user"],
            conversation=env["conversation"],
            model="mock",
            prompt=prompt,
            status="succeeded",
            idempotency_key="title-first",
            **values,
        )


def selected_model(settings):
    settings.AGENT_MODELS[0].update(model_id="selected-live-model", qwen=True)


def test_title_budget_overflow_preserves_existing_title_without_generating(
    logic, settings, monkeypatch
):
    selected_model(settings)
    run = make_run(logic)
    monkeypatch.setattr("apps.agent.context.count_tokens", lambda *args: 100000)
    monkeypatch.setattr(
        provider,
        "model_request",
        lambda *args, **kwargs: pytest.fail("超限标题不能发送生成请求"),
    )
    assert not titles.generate_conversation_title(run.pk)
    run.conversation.refresh_from_db()
    assert run.conversation.title == "新会话"


def response(title):
    return {"choices": [{"message": {"content": json.dumps({"title": title})}}]}


def test_greeting_uses_first_sentence_without_requesting_a_model(logic, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("提交接口不能同步生成标题")

    monkeypatch.setattr(provider, "model_request", forbidden)
    env = logic
    result = env["client"].post(
        f"/api/agent/conversations/{env['conversation'].id}/runs/",
        json.dumps(
            {
                "model": "mock",
                "prompt": "你好！聊聊遥感",
                "idempotencyKey": "greet-first",
            }
        ),
        content_type="application/json",
        **env["header"],
    )
    assert result.status_code == 202, result.content
    env["conversation"].refresh_from_db()
    assert env["conversation"].title == "你好"


def test_material_title_uses_goal_without_date_number_or_fixed_template(logic):
    run = make_run(
        logic,
        "核查地层接触关系。保留原始边界",
        resource_ids=[logic["resource"].id],
        research_intent={"_uploadBatchId": "a" * 32},
    )
    with project_scope(logic["scope"]):
        assert update_logic_title(run)
    assert run.conversation.title == "海德乌拉岩性图：核查地层接触关系"
    assert not update_logic_title(run)


@pytest.mark.parametrize(
    "custom", ["我的自定义地质分析", DEFAULT_LOGIC_PROMPT + " 个人笔记"]
)
def test_custom_titles_are_never_replaced(logic, custom):
    run = make_run(logic, DEFAULT_LOGIC_PROMPT, resource_ids=[logic["resource"].id])
    run.conversation.title = custom
    run.conversation.save(update_fields=["title"])
    with project_scope(logic["scope"]):
        assert not update_logic_title(run)
    assert run.conversation.title == custom


def test_default_material_title_is_just_the_material_name(logic):
    run = make_run(logic, DEFAULT_LOGIC_PROMPT, resource_ids=[logic["resource"].id])
    with project_scope(logic["scope"]):
        assert update_logic_title(run)
    assert run.conversation.title == "海德乌拉岩性图"


def test_backfill_recognizes_legacy_greetings_and_is_dry_run_and_idempotent(logic):
    run = make_run(logic)
    conversation = run.conversation
    conversation.title = f"地质资料 岩性·构造·蚀变检查 11-05 10:20 #{run.id}"
    conversation.save(update_fields=["title"])
    original = conversation.title
    output = StringIO()
    call_command("backfill_logic_titles", stdout=output)
    conversation.refresh_from_db()
    assert conversation.title == original
    assert "待回填 1" in output.getvalue()
    call_command("backfill_logic_titles", apply=True, stdout=StringIO())
    conversation.refresh_from_db()
    assert conversation.title == "你好"
    output = StringIO()
    call_command("backfill_logic_titles", apply=True, stdout=output)
    assert "已回填 0" in output.getvalue()


def test_other_project_titles_are_untouched(setup_agent):
    run = make_run(setup_agent, DEFAULT_LOGIC_PROMPT)
    with project_scope(setup_agent["scope"]):
        assert not update_logic_title(run)
    assert run.conversation.title == "新会话"


def test_model_title_uses_selected_model_and_bounded_input(
    logic, settings, monkeypatch
):
    selected_model(settings)
    run = make_run(logic, "你好" + "后续问题" * 200)
    calls = []

    def summarize(model, path, body, *, timeout):
        calls.append((model, path, body, timeout))
        return response("遥感研究交流")

    monkeypatch.setattr(provider, "model_request", summarize)
    assert titles.generate_conversation_title(run.id)
    run.conversation.refresh_from_db()
    assert run.conversation.title == "遥感研究交流"
    model, path, body, timeout = calls[0]
    assert model.model_id == body["model"] == "selected-live-model"
    assert path == "/v1/chat/completions"
    assert body["max_tokens"] == 64 and timeout == 8
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert len(json.loads(body["messages"][1]["content"])["message"]) == 600


def test_concurrent_user_rename_wins_over_model_title(logic, settings, monkeypatch):
    selected_model(settings)
    run = make_run(logic)

    def summarize(*args, **kwargs):
        run.conversation.title = "我刚刚起的名字"
        run.conversation.save(update_fields=["title", "updated_at"])
        return response("问候交流")

    monkeypatch.setattr(provider, "model_request", summarize)
    assert not titles.generate_conversation_title(run.id)
    run.conversation.refresh_from_db()
    assert run.conversation.title == "我刚刚起的名字"


@pytest.mark.parametrize(
    "invalid", ["", "长" * 29, "第一行\n第二行", "<script>", "问候 #188"]
)
def test_invalid_model_title_keeps_fallback(logic, settings, monkeypatch, invalid):
    selected_model(settings)
    run = make_run(logic)
    with project_scope(logic["scope"]):
        update_logic_title(run)
    monkeypatch.setattr(provider, "model_request", lambda *a, **k: response(invalid))
    assert not titles.generate_conversation_title(run.id)
    run.conversation.refresh_from_db()
    assert run.conversation.title == "你好"


def test_failed_title_request_does_not_change_completed_answer(
    logic, settings, monkeypatch
):
    selected_model(settings)
    run = make_run(logic, answer="这是完整回答")

    def timeout(*args, **kwargs):
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(provider, "model_request", timeout)
    assert not titles.generate_conversation_title(run.id)
    run.refresh_from_db()
    assert (run.status, run.answer) == ("succeeded", "这是完整回答")


def test_optional_title_has_no_backlog_and_joins_its_thread(logic, monkeypatch):
    run = make_run(logic)
    started, release = threading.Event(), threading.Event()

    def summarize(run_id):
        started.set()
        assert release.wait(2)
        raise TimeoutError("optional title failed")

    monkeypatch.setattr(titles, "generate_conversation_title", summarize)
    thread = titles.enqueue_conversation_title(run.id)
    try:
        assert started.wait(2)
        assert titles.enqueue_conversation_title(run.id) is None
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    again = titles.enqueue_conversation_title(run.id)
    again.join(3)
    assert not again.is_alive()


@pytest.mark.parametrize("case", ["other_project", "later_turn", "failed"])
def test_enqueue_skips_ineligible_runs_without_starting_a_thread(
    logic, monkeypatch, case
):
    run = make_run(logic)
    if case == "other_project":
        logic["project"].code = "ordinary-project"
        logic["project"].save(update_fields=["code"])
    elif case == "later_turn":
        run.pk = None
        run.idempotency_key = "title-second"
        run.save()
    else:
        run.status = "failed"
        run.save(update_fields=["status"])

    def forbidden(*args, **kwargs):
        pytest.fail("非首轮成功逻辑对话不应创建标题线程")

    monkeypatch.setattr(titles.threading, "Thread", forbidden)
    assert titles.enqueue_conversation_title(run.id) is None


def test_model_title_reaches_actual_bounded_http_transport(logic, settings):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            received.append(
                (
                    self.path,
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            payload = json.dumps(response("问候与研究交流")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        selected_model(settings)
        settings.AGENT_MODELS[0]["base_url"] = (
            f"http://127.0.0.1:{server.server_port}/v1"
        )
        run = make_run(logic)
        assert titles.generate_conversation_title(run.id)
        assert received[0][0] == "/v1/chat/completions"
        assert received[0][1]["max_tokens"] == 64
        run.conversation.refresh_from_db()
        assert run.conversation.title == "问候与研究交流"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
    assert not thread.is_alive()
