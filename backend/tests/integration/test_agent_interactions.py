"""Same-run questions preserve actual tools, user choices and cancellation."""
# ruff: noqa: F811 - pytest imports reusable fixtures by name.

import json

import pytest
from django.core.exceptions import ValidationError

from apps.agent.interactions import validate_question
from apps.agent.models import AgentRun
from apps.agent.worker import claim, run_task
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent, new_run  # noqa: F401


def question(**overrides):
    return {
        "kind": "input",
        "title": "选择统计方式",
        "reason": "已读取样地，统计目标还不明确",
        "questions": [
            {
                "key": "metric",
                "label": "希望怎样统计？",
                "type": "single",
                "required": True,
                "options": [
                    {"value": "mean", "label": "平均值"},
                    {"value": "sum", "label": "总量"},
                ],
                "defaultValue": "mean",
            }
        ],
        "plan": "按您选择的口径读取真实表格并统计",
        **overrides,
    }


def mock_model(monkeypatch, commands, captured=None):
    monkeypatch.setattr("apps.agent.worker.model_window", lambda _: 32768)
    monkeypatch.setattr("apps.agent.worker.prepare_context", lambda *a: (100, False))
    pending = iter(commands)

    def stream(*args, **kwargs):
        if captured is not None:
            captured.append(json.loads(json.dumps(args[1], ensure_ascii=False)))
        kwargs["on_thinking"]("测试服务返回的实际思考片段。")
        value = next(pending)
        yield (
            json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value
        )

    monkeypatch.setattr("apps.agent.worker.stream", stream)


def respond(env, run, **changes):
    run.refresh_from_db()
    card = run.interaction
    payload = {
        "action": "answer",
        "questionId": card["questionId"],
        "revision": card["revision"],
        "submissionKey": "answer-" + str(card["revision"]),
        "answers": {"metric": "sum"},
        **changes,
    }
    response = env["client"].post(
        f"/api/agent/runs/{run.id}/interaction/",
        json.dumps(payload),
        content_type="application/json",
        **env["header"],
    )
    return response, payload


def test_same_run_wait_restore_answer_uses_actual_tool_and_history(
    setup_agent, monkeypatch
):
    env, captures = setup_agent, []
    with project_scope(env["scope"]):
        run = new_run(env)
    mock_model(
        monkeypatch,
        [
            {
                "action": "describe_resource",
                "arguments": {"resourceId": env["resource"].id},
            },
            {"action": "ask_user", "arguments": question()},
        ],
        captures,
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_input" and not run.answer
    assert len(run.evidence) == 1 and run.execution_state["actions"] == 1
    assert run.events.filter(kind="thinking").exists()
    assert claim() is None  # Waiting releases the worker slot.
    read = env["client"].get(f"/api/agent/runs/{run.id}/", **env["header"])
    assert read.json()["run"]["interaction"]["status"] == "pending"
    assert (
        read.json()["run"]["interactionHistory"][0]["questionId"]
        == run.interaction["questionId"]
    )
    response, first = respond(env, run, text="只统计2024年的记录")
    assert response.status_code == 202, response.content
    assert (
        env["client"]
        .post(
            f"/api/agent/runs/{run.id}/interaction/",
            json.dumps(first),
            content_type="application/json",
            **env["header"],
        )
        .status_code
        == 202
    )
    assert (
        AgentRun._base_manager.filter(conversation_id=run.conversation_id).count() == 1
    )
    assert claim() == run.id
    second = question(
        title="结果要按地区展示吗？",
        questions=[
            {"key": "format", "label": "展示方式", "type": "text", "required": True}
        ],
    )
    mock_model(
        monkeypatch,
        [
            {
                "action": "aggregate_data",
                "arguments": {
                    "resourceId": env["resource"].id,
                    "field": "value",
                    "metric": "sum",
                    "filters": [{"field": "year", "op": "eq", "value": 2024}],
                },
            },
            {"action": "ask_user", "arguments": second},
        ],
        captures,
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_input" and len(run.interaction_history) == 2
    assert run.interaction_history[0]["answer"]["answers"] == {"metric": "sum"}
    assert "2024" in json.dumps(captures[-1], ensure_ascii=False)
    assert sum(ev["tool"] == "describe_resource" for ev in run.evidence) == 1
    stale = {**first, "submissionKey": "stale-new-key"}
    assert (
        env["client"]
        .post(
            f"/api/agent/runs/{run.id}/interaction/",
            json.dumps(stale),
            content_type="application/json",
            **env["header"],
        )
        .status_code
        == 409
    )
    response, _ = respond(env, run, answers={"format": "简短文字"})
    assert response.status_code == 202
    assert claim() == run.id
    mock_model(
        monkeypatch,
        [
            {
                "action": "final",
                "answer": "按补充条件统计了2024年数据，结果见实际统计证据。",
            }
        ],
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded" and len(run.interaction_history) == 2
    assert all(item["status"] == "answered" for item in run.interaction_history)
    assert not run.events.filter(kind="text", text__contains="action").exists()


@pytest.mark.parametrize("mode", ["agent", "chat"])
def test_text_answer_and_cancellation_are_durable(setup_agent, monkeypatch, mode):
    env = setup_agent
    with project_scope(env["scope"]):
        env["conversation"].mode = mode
        env["conversation"].save()
        run = new_run(env)
    mock_model(monkeypatch, [{"action": "ask_user", "arguments": question()}])
    run_task(run.id)
    response, submitted = respond(
        env, run, answers={}, text="先分析变化趋势，暂不计算平均值"
    )
    assert response.status_code == 202
    assert claim() == run.id
    mock_model(
        monkeypatch,
        [{"action": "ask_user", "arguments": question(title="需要哪段时间？")}],
    )
    run_task(run.id)
    response, _ = respond(env, run, action="cancel", answers={})
    assert response.status_code == 200
    run.refresh_from_db()
    assert run.status == "cancelled" and run.cancel_requested
    assert run.interaction["status"] == "cancelled" and claim() is None
    old = {**submitted, "submissionKey": "late-answer"}
    assert (
        env["client"]
        .post(
            f"/api/agent/runs/{run.id}/interaction/",
            json.dumps(old),
            content_type="application/json",
            **env["header"],
        )
        .status_code
        == 409
    )


def test_chat_cannot_acquire_platform_tools(setup_agent, monkeypatch):
    env = setup_agent
    with project_scope(env["scope"]):
        env["conversation"].mode = "chat"
        env["conversation"].save()
        run = new_run(env)
    mock_model(
        monkeypatch,
        [
            {"action": "search_resources", "arguments": {}},
            {
                "action": "final",
                "answer": "普通模型对话无法读取平台资源，请告诉我资料内容。",
            },
        ],
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded" and not run.evidence
    assert not run.events.filter(kind="tool_started").exists()


@pytest.mark.parametrize("approve", ["approve", "reject"])
def test_review_requires_explicit_answer_and_rejection_never_resumes(
    setup_agent, monkeypatch, approve
):
    env = setup_agent
    review = question(
        kind="review",
        questions=[
            {
                "key": "approval",
                "label": "是否批准当前方案？",
                "type": "single",
                "required": True,
                "options": [
                    {"value": "approve", "label": "批准"},
                    {"value": "reject", "label": "拒绝"},
                ],
            }
        ],
    )
    with project_scope(env["scope"]):
        run = new_run(env)
    mock_model(monkeypatch, [{"action": "ask_user", "arguments": review}])
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_review"
    invalid, _ = respond(env, run, answers={}, text="请继续")
    assert invalid.status_code == 400
    result, payload = respond(env, run, answers={"approval": approve})
    assert result.status_code == (202 if approve == "approve" else 200)
    run.refresh_from_db()
    assert run.status == ("queued" if approve == "approve" else "cancelled")
    duplicate = env["client"].post(
        f"/api/agent/runs/{run.id}/interaction/",
        json.dumps(payload),
        content_type="application/json",
        **env["header"],
    )
    assert duplicate.status_code == result.status_code
    assert len(run.interaction_history) == 1


def test_question_validation_rejects_unknown_options_and_false_review():
    assert validate_question(question())["questions"][0]["defaultValue"] == "mean"
    with pytest.raises(ValidationError, match="approval"):
        validate_question(question(kind="review"))
    with pytest.raises(ValidationError, match="有效选项"):
        validate_question(
            question(
                questions=[{**question()["questions"][0], "defaultValue": "missing"}]
            )
        )
