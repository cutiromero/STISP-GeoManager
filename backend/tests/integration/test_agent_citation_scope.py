"""History is background; current references require this run's actual tools."""
# ruff: noqa: F811 - pytest imports reusable fixtures by name.

import json
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from apps.agent.citations import (
    historical_answer,
    source_locators,
    validate_answer_citations,
)
from apps.agent.models import AgentRun
from apps.agent.policy import default_policy
from apps.agent.tools import evidence_items, execute
from apps.agent.worker import claim, context_messages, run_task
from apps.projects.context import project_scope
from tests.integration.test_agent import new_run, setup_agent  # noqa: F401
from tests.integration.test_agent_interactions import mock_model, question, respond
from tests.integration.test_agent_knowledge_bridge import knowledge_agent  # noqa: F401


def current_run(env, prompt="解释当前资料"):
    return AgentRun.objects.create(
        conversation=env["conversation"],
        owner=env["user"],
        model="mock",
        prompt=prompt,
        status="running",
        idempotency_key="fresh-citation-run",
    )


def save_history(env, run):
    with project_scope(env["scope"]):
        _, pairs = execute(run, "search_knowledge", {"query": "矿物"})
        run.evidence += evidence_items(run, "search_knowledge", pairs)
        run.status = "succeeded"
        run.prompt = "请解释[证据 2]"
        run.answer = "同一平衡域需要核查。[证据 2]"
        run.save()


@pytest.mark.parametrize(
    "tool,result,expected",
    [
        (
            "get_compute_task",
            {
                "taskId": "3ad3e878-0e8e-43db-a4b1-af74669b38fb",
                "versionId": 7,
                "outputs": [{"id": 21, "resourceId": 31, "metadata": {"mean": 0.5}}],
            },
            [
                {"taskId": "3ad3e878-0e8e-43db-a4b1-af74669b38fb", "versionId": 7},
                {
                    "taskId": "3ad3e878-0e8e-43db-a4b1-af74669b38fb",
                    "outputId": 21,
                    "resourceId": 31,
                },
            ],
        ),
        (
            "list_compute_tasks",
            {
                "items": [
                    {"taskId": "3ad3e878-0e8e-43db-a4b1-af74669b38fb", "versionId": 7}
                ]
            },
            [{"taskId": "3ad3e878-0e8e-43db-a4b1-af74669b38fb", "versionId": 7}],
        ),
        (
            "read_compute_output",
            {"output": {"id": 21, "resourceId": 31}, "mean": 0.5},
            [{"outputId": 21, "resourceId": 31}],
        ),
        (
            "search_knowledge",
            {
                "items": [{"id": 71, "citation": "[证据 2]", "statement": "旧结论"}],
                "documents": [{"documentId": 81, "evidenceId": 3, "content": "旧原文"}],
            },
            [{"entryId": 71}, {"documentId": 81}],
        ),
        (
            "read_knowledge_document",
            {"documents": [{"documentId": 81, "citation": "[证据 3]"}]},
            [{"documentId": 81}],
        ),
        (
            "check_knowledge_constraints",
            {"findings": [{"entryId": 71, "detail": "旧检查结论"}]},
            [{"entryId": 71}],
        ),
        (
            "list_compute_algorithms",
            {"items": [{"id": 100, "versions": [{"id": 7, "manifest": {"id": 500}}]}]},
            [{"versionId": 7}],
        ),
        (
            "describe_resource",
            {"taskId": "not-a-task", "nested": {"documentId": 81}},
            [],
        ),
        (
            "get_compute_task",
            {"taskId": "not-a-task", "versionId": True, "outputs": [{"id": -1}]},
            [],
        ),
    ],
)
def test_history_locators_keep_known_source_ids_without_old_results(
    tool, result, expected
):
    evidence = {"id": 1, "tool": tool, "name": "旧对象[证据 1]", "result": result}
    assert source_locators(evidence) == expected
    run = SimpleNamespace(id=42, answer="旧答复。[证据 1]", evidence=[evidence])
    answer = historical_answer(run)
    assert "[证据 1]" not in answer
    index = json.loads(answer.split("：", 1)[1])
    assert index[0]["sourceLocators"] == expected
    assert all(
        key not in json.dumps(index, ensure_ascii=False)
        for key in (
            "citation",
            "evidenceId",
            "metadata",
            "statement",
            "content",
            "manifest",
        )
    )


@pytest.mark.parametrize("has_evidence", [False, True])
def test_history_namespaces_answer_prompt_and_omits_nested_tool_citations(
    knowledge_agent, has_evidence
):
    env, _, _, old = knowledge_agent
    save_history(env, old)
    if not has_evidence:
        old.evidence = []
        old.save(update_fields=["evidence"])
    with project_scope(env["scope"]):
        run = current_run(env)
        messages = context_messages(run, default_policy(), None)
    rendered = json.dumps(messages[:-1], ensure_ascii=False)
    assert f"[历史运行 {old.id} 的证据 2]" in rendered
    assert "[证据 2]" not in rendered
    assert '"citation"' not in rendered
    assert "原文：样品需要区分矿物形成阶段" not in rendered
    assert not run.evidence  # Context never imports old evidence into this run.
    if has_evidence:
        assert "历史来源索引" in historical_answer(old)


@pytest.mark.parametrize("revoked", ["document", "entry"])
def test_history_scope_still_checks_revoked_sources(knowledge_agent, revoked):
    env, entry, doc, old = knowledge_agent
    save_history(env, old)
    with project_scope(env["scope"]):
        if revoked == "document":
            doc.visibility = "owner_only"
            doc.save(update_fields=["visibility"])
        else:
            entry.status = "retired"
            entry.save(update_fields=["status"])
        run = current_run(env)
        messages = context_messages(run, default_policy(), None)
    assert old.answer not in json.dumps(messages, ensure_ascii=False)
    assert len(messages) == 1


@pytest.mark.parametrize(
    "answer,is_agent",
    [
        ("无法核实的结论。[证据 2]", True),
        ("无法核实的结论。[证据 1、2]", True),
        ("无法核实的结论。[证据 x]", True),
        ("无法核实的结论。[证据 0]", True),
        ("无法核实的结论。[历史运行 9 的证据 1]", True),
        ("无法核实的结论。[历史任务9·证据1]", True),
        ("声称读过平台资料。[证据 1]", False),
    ],
)
def test_final_rejects_unknown_malformed_and_chat_platform_references(answer, is_agent):
    with pytest.raises(ValidationError, match="不属于本轮真实证据"):
        validate_answer_citations(answer, [{"id": 1}], is_agent=is_agent)


@pytest.mark.parametrize(
    "answer", ["无需引用的解释。", "结果。[证据1]", "结果。[证据 1、2]"]
)
def test_current_actual_reference_formats_remain_valid(answer):
    validate_answer_citations(answer, [{"id": 1}, {"id": 2}], is_agent=True)


def test_invalid_history_reference_must_correct_with_real_retrieval(
    knowledge_agent, monkeypatch
):
    env, entry, _, old = knowledge_agent
    save_history(env, old)
    with project_scope(env["scope"]):
        run = current_run(env)
    captured = []
    mock_model(
        monkeypatch,
        [
            {"action": "final", "answer": "沿用旧结论。[证据 2]"},
            {"action": "search_knowledge", "arguments": {"query": "矿物形成阶段"}},
            {"action": "final", "answer": "本次检索支持同一平衡域中需核查。[证据 1]"},
        ],
        captured,
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded", run.detail
    assert "沿用旧结论" not in run.answer
    assert len(captured) == 3
    assert "不属于本轮真实证据" in captured[1][-1]["content"]
    assert "不能仅删除引用" in captured[1][-1]["content"]
    assert len(run.evidence) == 2 and run.evidence[0]["id"] == 1
    assert run.evidence[0]["result"]["items"][0]["id"] == entry.id
    assert run.events.filter(kind="tool_started").count() == 1


def test_old_one_and_new_one_are_separate_sources(knowledge_agent, monkeypatch):
    env, _, _, old = knowledge_agent
    save_history(env, old)
    old.answer = "旧算法目录为空。[证据 1]"
    old.save(update_fields=["answer"])
    with project_scope(env["scope"]):
        run = current_run(env)
    captured = []
    mock_model(
        monkeypatch,
        [
            {
                "action": "describe_resource",
                "arguments": {"resourceId": env["resource"].id},
            },
            {"action": "final", "answer": "当前资料包含year等字段。[证据 1]"},
        ],
        captured,
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded", run.detail
    assert f"[历史运行 {old.id} 的证据 1]" in json.dumps(
        captured[0], ensure_ascii=False
    )
    assert run.evidence[0]["id"] == 1
    assert run.evidence[0]["tool"] == "describe_resource"
    assert old.evidence[0]["tool"] == "list_compute_algorithms"


def test_chat_history_does_not_grant_platform_evidence(setup_agent, monkeypatch):
    env = setup_agent
    with project_scope(env["scope"]):
        env["conversation"].mode = "chat"
        env["conversation"].save(update_fields=["mode"])
        old = new_run(env)
        old.status, old.answer = "succeeded", "旧平台结论。[证据 1]"
        old.evidence = [
            {"id": 1, "tool": "search_resources", "result": {"secret": "old-payload"}}
        ]
        old.save()
        run = current_run(env)
    captured = []
    mock_model(
        monkeypatch,
        [
            {"action": "final", "answer": "已经核实。[证据 1]"},
            {"action": "final", "answer": "我不能读取平台资料，请提供具体资料。"},
        ],
        captured,
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded" and not run.evidence
    assert "没有平台证据权限" in captured[1][-1]["content"]
    assert "old-payload" not in json.dumps(captured, ensure_ascii=False)
    assert not run.events.filter(kind="tool_started").exists()


def test_same_run_wait_preserves_actual_reference_without_requery(
    setup_agent, monkeypatch
):
    env = setup_agent
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
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_input" and run.evidence[0]["id"] == 1
    restored = env["client"].get(f"/api/agent/runs/{run.id}/", **env["header"])
    assert restored.status_code == 200
    response, _ = respond(env, run)
    assert response.status_code == 202 and claim() == run.id
    mock_model(
        monkeypatch,
        [{"action": "final", "answer": "沿用本任务读取的真实字段。[证据 1]"}],
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded", run.detail
    assert len(run.evidence) == 1
    assert run.events.filter(kind="tool_started").count() == 1
