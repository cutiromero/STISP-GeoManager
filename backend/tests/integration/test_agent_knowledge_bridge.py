"""Agent citations, document authorization and final compute status snapshots."""

import json
from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.agent.models import AgentPolicy
from apps.agent.policy import default_policy
from apps.agent.tools import TOOLS, check_evidence, evidence_items, execute
from apps.agent.worker import (
    append_compute_status,
    append_requested_fields,
    run_task,
    tool_enabled,
)
from apps.knowledge.models import KnowledgeDocument, KnowledgeEntry, KnowledgeLibrary
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent, new_run  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def knowledge_agent(setup_agent, settings, monkeypatch):  # noqa: F811
    s = setup_agent
    settings.WEKNORA_CONFIG = {}
    with project_scope(s["scope"]):
        entry = KnowledgeEntry.objects.create(
            title="平衡条件",
            category="矿物",
            subject="甲",
            predicate="联系",
            object="乙",
            statement="同一平衡域中需核查",
            status="published",
            revision=7,
        )
        library = KnowledgeLibrary.objects.create(
            scope_key="agent-docs", visibility="project"
        )
        doc = KnowledgeDocument.objects.create(
            library=library,
            owner=s["other"],
            title="矿物报告",
            filename="minerals.pdf",
            source_url="https://example.org/minerals",
            sha256="a" * 64,
            original_path="test.pdf",
            upstream_document_id="upstream-doc",
            status="completed",
        )
        run = new_run(s)
        run.evidence = evidence_items(
            run, "list_compute_algorithms", [(None, {"items": []})]
        )
    monkeypatch.setattr(
        "apps.knowledge.services.search_entries",
        lambda *a, **kw: {
            "items": [
                {
                    "id": entry.id,
                    "revision": entry.revision,
                    "title": entry.title,
                    "statement": entry.statement,
                    "conditions": ["同一平衡域"],
                }
            ]
        },
    )
    monkeypatch.setattr(
        "apps.knowledge.library.search_documents",
        lambda *a, **kw: {
            "items": [
                {
                    "documentId": doc.id,
                    "title": doc.title,
                    "sourceUrl": doc.source_url,
                    "content": "原文：样品需要区分矿物形成阶段。",
                    "score": 0.8,
                    "matchType": "vector",
                    "chunkId": "chunk-1",
                }
            ],
            "available": True,
            "detail": "原文语义与关键词混合检索",
        },
    )
    return s, entry, doc, run


def test_sources_have_actual_evidence_citations_and_no_catalog_ids(knowledge_agent):
    s, entry, doc, run = knowledge_agent
    with project_scope(s["scope"]):
        result, pairs = execute(run, "search_knowledge", {"query": "矿物同现能否判错"})
        additions = evidence_items(run, "search_knowledge", pairs)
        assert result["items"][0]["id"] == entry.id
        assert result["items"][0]["citation"] == "[证据 2]"
        assert result["documents"][0]["citation"] == "[证据 3]"
        assert result["documents"][0]["documentId"] == doc.id
        assert result["documents"][0]["sourceUrl"] == doc.source_url
        assert result["documents"][0]["content"].startswith("原文：")
        assert [item["id"] for item in additions] == [2, 3]
        assert all(item["resourceId"] is None for item in additions)
        run.evidence += additions
        check_evidence(run, s["user"], {})
        doc.visibility = "owner_only"
        doc.save(update_fields=["visibility"])
        with pytest.raises(PermissionDenied, match="知识资料"):
            check_evidence(run, s["user"], {})


def test_changed_document_or_rule_invalidates_history(knowledge_agent):
    s, entry, doc, run = knowledge_agent
    with project_scope(s["scope"]):
        _, pairs = execute(run, "search_knowledge", {"query": "矿物"})
        run.evidence += evidence_items(run, "search_knowledge", pairs)
        doc.sha256 = "b" * 64
        doc.save(update_fields=["sha256"])
        with pytest.raises(PermissionDenied, match="知识资料"):
            check_evidence(run, s["user"], {})
        doc.sha256 = "a" * 64
        doc.save(update_fields=["sha256"])
        entry.revision += 1
        entry.save(update_fields=["revision"])
        with pytest.raises(PermissionDenied, match="知识依据"):
            check_evidence(run, s["user"], {})


def test_saved_knowledge_snapshots_survive_revision_but_not_access_changes(
    knowledge_agent,
):
    s, entry, doc, run = knowledge_agent
    with project_scope(s["scope"]):
        _, pairs = execute(run, "search_knowledge", {"query": "矿物"})
        run.evidence += evidence_items(run, "search_knowledge", pairs)
        snapshot = list(run.evidence)
        doc.sha256 = "b" * 64
        doc.save(update_fields=["sha256"])
        entry.revision += 1
        entry.save(update_fields=["revision"])
        check_evidence(run, s["user"], {}, history=True)
        assert run.evidence == snapshot
        with pytest.raises(PermissionDenied):
            check_evidence(run, s["user"], {})
        doc.visibility = "owner_only"
        doc.save(update_fields=["visibility"])
        with pytest.raises(PermissionDenied, match="知识资料"):
            check_evidence(run, s["user"], {}, history=True)


def test_document_passages_are_bounded_and_outage_is_explicit(
    knowledge_agent, monkeypatch
):
    s, _, doc, run = knowledge_agent
    monkeypatch.setattr(
        "apps.knowledge.library.search_documents",
        lambda *a, **kw: {
            "items": [
                {
                    "documentId": doc.id,
                    "title": doc.title,
                    "sourceUrl": doc.source_url,
                    "content": "矿" * 12000,
                    "score": 0.8,
                    "matchType": "vector",
                    "chunkId": str(i),
                }
                for i in range(6)
            ],
            "available": True,
            "detail": "混合检索",
        },
    )
    with project_scope(s["scope"]):
        result, _ = execute(run, "search_knowledge", {"query": "矿物"})
        assert result["documents"] and result["documents"][0]["excerptTruncated"]
        assert len(json.dumps(result, ensure_ascii=False).encode()) <= 24000
        monkeypatch.setattr(
            "apps.knowledge.library.search_documents",
            lambda *a, **kw: {
                "items": [],
                "available": False,
                "detail": "文档检索暂不可用",
            },
        )
        result, _ = execute(run, "search_knowledge", {"query": "矿物"})
        assert result["items"] and not result["documentSearch"]["available"]


def test_knowledge_document_paging_and_live_access(knowledge_agent, settings):
    s, _, doc, run = knowledge_agent
    text = "霞石与石英的形成阶段需结合岩相证据核查。" * 1000
    doc.extracted_path = "agent-minerals/extracted.md"
    path = settings.PROJECT_CONFIG.app_path("uploads", "knowledge", doc.extracted_path)
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    with project_scope(s["scope"]):
        doc.save(update_fields=["extracted_path"])
        args = {"documentId": doc.id, "offset": 17, "limit": 8000}
        result, pairs = execute(run, "read_knowledge_document", args)
        item = result["documents"][0]
        assert item["content"] == text[17:8017]
        assert item["nextOffset"] == 8017 and item["truncated"]
        assert item["documentSha256"] == doc.sha256
        assert item["citation"] == "[证据 2]"
        assert item["sourceKind"] == "document_excerpt"
        additions = evidence_items(run, "read_knowledge_document", pairs)
        assert len(additions) == 1 and additions[0]["resourceId"] is None
        run.evidence += additions
        check_evidence(run, s["user"], default_policy())
        result, _ = execute(
            run, "read_knowledge_document", {"documentId": doc.id, "offset": len(text)}
        )
        assert result["documents"][0]["content"] == ""
        assert result["documents"][0]["nextOffset"] is None
        doc.visibility = "owner_only"
        doc.save(update_fields=["visibility"])
        with pytest.raises(PermissionDenied):
            check_evidence(run, s["user"], default_policy())
        run.evidence = []
        with pytest.raises(PermissionDenied):
            execute(run, "read_knowledge_document", args)


def test_knowledge_full_document_policy_and_invalid_parameters(knowledge_agent):
    s, _, doc, run = knowledge_agent
    with project_scope(s["scope"]):
        for args in (
            {"documentId": True},
            {"documentId": "1"},
            {"documentId": doc.id, "offset": -1},
            {"documentId": doc.id, "limit": 8001},
            {"documentId": doc.id, "limit": 0},
        ):
            with pytest.raises(ValidationError):
                execute(run, "read_knowledge_document", args)
        with pytest.raises(PermissionDenied):
            execute(run, "read_knowledge_document", {"documentId": doc.id + 100000})
        p = {**default_policy(), "allowDocuments": False}
        AgentPolicy.objects.update_or_create(pk=1, defaults={"value": p})
        assert not tool_enabled(TOOLS["read_knowledge_document"], p, run)
        with pytest.raises(PermissionDenied, match="文档正文"):
            execute(run, "read_knowledge_document", {"documentId": doc.id})
        run.evidence = [{"tool": "read_knowledge_document", "result": {}}]
        with pytest.raises(PermissionDenied, match="文档读取"):
            check_evidence(run, s["user"], p)


def task_card(status="succeeded", import_status="ready", tracking="completed"):
    return {
        "task": {
            "id": "task-id",
            "name": "真实计算结果",
            "status": status,
            "stage": "等待计算资源",
            "progress": 0,
            "outputs": [
                {
                    "importStatus": import_status,
                    "resourceId": 88,
                    "resourceName": "真实结果",
                    "resourceLocation": "研究项目 / 数据资源 / 真实结果",
                }
            ],
        },
        "autoImport": True,
        "trackingStatus": tracking,
    }


def test_field_list_fills_only_an_explicit_request_from_current_evidence():
    run = SimpleNamespace(
        prompt="有哪些字段？计算一个数值字段的平均值。",
        evidence=[
            {
                "id": 3,
                "resourceId": 17,
                "tool": "describe_resource",
                "result": {"fields": [{"name": "region"}, {"name": "value"}]},
            }
        ],
    )
    answer = "value 平均值为4.6667。"
    filled = append_requested_fields(answer, run)
    assert '数据 17 的字段清单：`["region", "value"]`。[证据 3]' in filled
    assert (
        append_requested_fields("字段 region、value。", run) == "字段 region、value。"
    )
    run.prompt = "计算value字段的平均值。"
    assert append_requested_fields(answer, run) == answer
    run.prompt = "List all columns and summarize the value field."
    assert "region" in append_requested_fields(answer, run)
    run.evidence = []
    assert append_requested_fields(answer, run) == answer


@pytest.mark.parametrize(
    "card, expected, forbidden",
    [
        (task_card(), "已保存至", "尚未入库"),
        (task_card("queued", "none", "waiting_compute"), "等待计算资源", "已入库"),
        (task_card("succeeded", "none", "blocked"), "自动入库已暂停", "已入库"),
    ],
)
def test_final_status_uses_current_task_not_model_snapshot(
    monkeypatch, card, expected, forbidden
):
    monkeypatch.setattr(
        "apps.agent.compute_tools.run_tasks", lambda *a: {"items": [card]}
    )
    from types import SimpleNamespace

    run = SimpleNamespace(evidence=[], compute_intent={})
    answer = append_compute_status("任务已提交。", run, None, {})
    assert expected in answer and forbidden not in answer


def test_final_refresh_needs_no_second_model_call(setup_agent, monkeypatch):  # noqa: F811
    s = setup_agent
    calls = []

    def stream(*args, **kwargs):
        calls.append(True)
        yield json.dumps({"action": "final", "answer": "任务已提交。"})

    monkeypatch.setattr("apps.agent.worker.stream", stream)
    monkeypatch.setattr("apps.agent.worker.model_window", lambda *a: 32768)
    monkeypatch.setattr("apps.agent.worker.prepare_context", lambda *a: (100, False))
    monkeypatch.setattr(
        "apps.agent.compute_tools.run_tasks", lambda *a: {"items": [task_card()]}
    )
    with project_scope(s["scope"]):
        run = new_run(s)
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded", run.detail
    assert calls == [True]
    assert "已保存至" in run.answer
