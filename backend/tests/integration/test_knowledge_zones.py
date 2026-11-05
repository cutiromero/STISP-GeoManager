"""Subject areas and run selectors retain permission and execution boundaries."""
# ruff: noqa: F811

import json
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.agent.compute_intents import process, serialize as intent_json, update
from apps.agent.models import AgentComputeFollowup, AgentRun
from apps.agent.policy import default_policy
from apps.agent.selections import knowledge_domains, normalize
from apps.agent.tools import TOOLS, execute
from apps.agent.worker import context_messages, tool_enabled
from apps.knowledge import library
from apps.knowledge.models import KnowledgeEntry
from apps.knowledge.services import search_entries
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401
from tests.integration.test_agent_compute_intent import (
    env as compute_env,  # noqa: F401
    setup_compute,  # noqa: F401
    run,
)  # noqa: F401
from tests.integration.test_knowledge_library import env as library_env  # noqa: F401

pytestmark = pytest.mark.django_db


def create_run(s, prompt, **values):
    selection = values.pop("knowledge_selection", {"mode": "auto", "domains": []})
    return AgentRun.objects.create(
        conversation=s["conversation"],
        owner=s["user"],
        model="mock",
        prompt=prompt,
        status="succeeded",
        idempotency_key=f"zones-{s['conversation'].runs.count()}",
        knowledge_selection={**selection, "_contextRunIds": []},
        **values,
    )


def create_entry(domain, title="NDVI资料", **values):
    return KnowledgeEntry.objects.create(
        domain=domain,
        title=title,
        category="原细类",
        subject="NDVI",
        predicate="依据",
        object="植被",
        statement="NDVI反映红光与近红外比值。",
        status="published",
        **values,
    )


def test_domain_filter_keeps_category_and_public_permission(setup_agent):
    s = setup_agent
    with project_scope(s["scope"]):
        ecology = create_entry("arid_ecology")
        create_entry("geology", "矿物NDVI资料")
        result = search_entries(s["user"], "NDVI", domains=["arid_ecology"])
        assert [row["id"] for row in result["items"]] == [ecology.id]
        assert result["items"][0]["category"] == "原细类"
        assert {row["id"] for row in result["domains"]} == {
            "remote_sensing",
            "pipelines",
            "geology",
            "arid_ecology",
        }
        assert next(d for d in result["domains"] if d["id"] == "geology")["count"] == 1


def test_ndvi_auto_retrieval_really_excludes_minerals(setup_agent, settings):
    s = setup_agent
    settings.WEKNORA_CONFIG = {}
    with project_scope(s["scope"]):
        for domain in ("remote_sensing", "arid_ecology", "geology"):
            create_entry(domain)
        item = create_run(
            s,
            "计算NDVI研究干旱区植被",
            knowledge_selection={"mode": "auto", "domains": []},
        )
        result, _ = execute(item, "search_knowledge", {"query": "NDVI"})
        assert set(result["domains"]) == {"remote_sensing", "arid_ecology"}
        assert {row["domain"] for row in result["items"]} == set(result["domains"])
        # Changing the tool query cannot expand the user-selected task topic.
        result, _ = execute(item, "search_knowledge", {"query": "矿物"})
        assert "geology" not in result["domains"]
        assert knowledge_domains(create_run(s, "油气管道沿线的NDVI变化")) == [
            "remote_sensing",
            "pipelines",
            "arid_ecology",
        ]


def test_manual_and_all_knowledge_modes(setup_agent, settings):
    s = setup_agent
    settings.WEKNORA_CONFIG = {}
    with project_scope(s["scope"]):
        for domain in ("remote_sensing", "arid_ecology", "geology"):
            create_entry(domain)
        item = create_run(
            s, "NDVI", knowledge_selection={"mode": "manual", "domains": ["geology"]}
        )
        result, _ = execute(item, "search_knowledge", {"query": "NDVI"})
        assert {row["domain"] for row in result["items"]} == {"geology"}
        item.knowledge_selection = {"mode": "all", "domains": []}
        result, _ = execute(item, "search_knowledge", {"query": "NDVI"})
        assert len(result["items"]) == 3


def test_none_disables_every_knowledge_tool_and_old_context(setup_agent):
    s = setup_agent
    with project_scope(s["scope"]):
        prior = create_run(
            s,
            "地质问题",
            answer="旧知识结论不应混入",
            evidence=[
                {
                    "id": 1,
                    "resourceId": None,
                    "tool": "search_knowledge",
                    "result": {"items": []},
                }
            ],
        )
        item = create_run(
            s, "直接解释", knowledge_selection={"mode": "none", "domains": []}
        )
        for name in (
            "search_knowledge",
            "read_knowledge_document",
            "check_knowledge_constraints",
        ):
            assert not tool_enabled(TOOLS[name], default_policy(), item)
            with pytest.raises(PermissionDenied, match="不参考"):
                execute(item, name, {})
        messages = context_messages(item, default_policy(), None)
        assert prior.answer not in json.dumps(messages, ensure_ascii=False)


def test_persist_restore_and_idempotency_include_preferences(setup_agent):
    s = setup_agent
    payload = {
        "model": "mock",
        "prompt": "分析当前数据",
        "idempotencyKey": "zones-submit-01",
        "dataSelectionMode": "manual",
        "resourceIds": [s["resource"].id],
        "knowledgeSelection": {"mode": "manual", "domains": ["arid_ecology"]},
        "algorithmSelectionMode": "auto",
        "algorithmVersionIds": [],
    }
    url = f"/api/agent/conversations/{s['conversation'].id}/runs/"
    first = s["client"].post(
        url, json.dumps(payload), content_type="application/json", **s["header"]
    )
    assert first.status_code == 202, first.content
    response = first.json()
    assert response["knowledgeSelection"] == payload["knowledgeSelection"]
    assert response["resourceIds"] == payload["resourceIds"]
    assert response["dataSelectionMode"] == "manual"
    restored = (
        s["client"]
        .get(f"/api/agent/runs/{response['id']}/", **s["header"])
        .json()["run"]
    )
    assert restored["knowledgeSelection"] == payload["knowledgeSelection"]
    payload["knowledgeSelection"] = {"mode": "none", "domains": []}
    conflict = s["client"].post(
        url, json.dumps(payload), content_type="application/json", **s["header"]
    )
    assert conflict.status_code == 409


@pytest.mark.parametrize(
    "value, selected",
    [
        ({"knowledgeSelection": {"mode": "manual", "domains": []}}, []),
        ({"knowledgeSelection": {"mode": "none", "domains": ["geology"]}}, []),
        ({"algorithmSelectionMode": "manual"}, []),
        ({"dataSelectionMode": "manual"}, []),
        ({"dataSelectionMode": "auto"}, [1]),
    ],
)
def test_empty_or_inconsistent_manual_selection_rejected(value, selected):
    with pytest.raises(ValidationError):
        normalize(value, selected)


def test_manual_algorithms_filter_listing_and_execution(compute_env):
    env = compute_env
    item = run(env, "处理这张影像")
    item.algorithm_selection_mode = "manual"
    item.algorithm_version_ids = [env["ndvi"].id]
    item.knowledge_selection = {"mode": "none", "domains": []}
    item.save()
    listing, _ = execute(item, "list_compute_algorithms", {})
    assert {v["id"] for a in listing["items"] for v in a["versions"]} == {
        env["ndvi"].id
    }
    with pytest.raises(PermissionDenied, match="手选"):
        execute(item, "execute_operator", {"versionId": env["ndwi"].id})
    message = process(item, env["owner"], env["policy"])
    assert "卡片" in message
    assert item.compute_intent["versionId"] == env["ndvi"].id
    assert item.compute_intent["knowledgeEvidenceIds"] == []
    assert not any(e["tool"] == "search_knowledge" for e in item.evidence)


def test_manual_multiple_algorithms_ask_for_choice(compute_env):
    env = compute_env
    item = run(env, "计算这个影像")
    item.algorithm_selection_mode = "manual"
    item.algorithm_version_ids = [env["ndvi"].id, env["ndwi"].id]
    assert "多个算法" in process(item, env["owner"], env["policy"])
    assert not item.compute_intent


def test_compute_card_cannot_escape_selected_data(compute_env):
    env = compute_env
    item = run(env, "计算NDVI")
    item.data_selection_mode = "manual"
    item.save()
    process(item, env["owner"], env["policy"])
    card = intent_json(item, env["owner"], env["policy"])
    assert [r["id"] for r in card["inputCandidates"]] == [env["raster"].id]
    with pytest.raises(PermissionDenied):
        update(
            item,
            env["owner"],
            env["policy"],
            {
                "planRevision": item.compute_intent["planRevision"],
                "action": "update",
                "inputs": {"image": env["resource"].id},
            },
        )


def test_documents_and_wiki_cannot_bypass_domain(library_env):
    env = library_env
    with project_scope(ProjectScope((1,), 1, env.admin.id, True)):
        documents = []
        for domain in ("remote_sensing", "geology"):
            doc = library.upload_document(
                env.admin,
                SimpleUploadedFile(f"{domain}.txt", b"source original text"),
                title=domain,
                domain=domain,
            )
            documents.append(doc)
        remote, geology = documents
        assert remote.library_id != geology.library_id
        with pytest.raises(library.WeKnoraError):
            library.read_document(env.admin, geology.id, domains=["remote_sensing"])
        env.engine.hybrid_search.return_value = [
            {
                "knowledge_id": d.upstream_document_id,
                "chunk_type": "text",
                "content": "original",
                "score": 1,
            }
            for d in documents
        ]
        result = library.search_documents(
            env.admin, "source", domains=["remote_sensing"]
        )
        assert [r["documentId"] for r in result["items"]] == [remote.id]
        env.engine.wiki_pages.return_value = {
            "pages": [
                {
                    "slug": "mixed",
                    "title": "混合页",
                    "source_refs": [d.upstream_document_id for d in documents],
                }
            ]
        }
        assert library.list_wiki(env.admin, domains=["remote_sensing"])["items"] == []


def test_selected_algorithm_topic_informs_auto_knowledge(compute_env):
    env = compute_env
    item = run(env, "运行")
    item.algorithm_selection_mode = "manual"
    item.algorithm_version_ids = [env["ndvi"].id]
    assert set(knowledge_domains(item)) == {"remote_sensing", "arid_ecology"}
    item.prompt = "计算NDWI"
    with pytest.raises(ValidationError, match="不一致"):
        process(item, env["owner"], env["policy"])


def test_followup_parameter_card_continues_with_none(compute_env):
    env = compute_env
    initial = run(env, "计算NDVI")
    process(initial, env["owner"], env["policy"])
    followup = run(env, "对啊，红光第3波段，近红外第8波段")
    followup.knowledge_selection = {"mode": "none", "domains": []}
    followup.save()
    with patch("apps.agent.compute_intents.submit_plan", return_value="真实提交入口"):
        assert process(followup, env["owner"], env["policy"]) == "真实提交入口"
    assert followup.compute_intent["parameters"] == {"red": 3, "nir": 8}
    assert not followup.compute_intent["knowledgeEvidenceIds"]


def test_document_classification_preserves_file_and_checks_owner(library_env):
    env = library_env
    with project_scope(
        ProjectScope((env.project.id,), env.project.id, env.admin.id, True)
    ):
        doc = library.upload_document(
            env.admin,
            SimpleUploadedFile("legacy.txt", b"immutable source"),
            title="历史资料",
            visibility="owner_only",
        )
        sha, original = doc.sha256, library._safe_path(doc.original_path).read_bytes()
        response = env.client.patch(
            f"/api/knowledge/documents/{doc.id}/",
            json.dumps({"domain": "arid_ecology"}),
            content_type="application/json",
            HTTP_X_PROJECT_ID=str(env.project.id),
        )
        assert response.status_code == 200, response.content
        assert response.json()["domain"] == "arid_ecology"
        doc.refresh_from_db()
        assert (doc.sha256, library._safe_path(doc.original_path).read_bytes()) == (
            sha,
            original,
        )
        env.client.force_login(env.other)
        denied = env.client.patch(
            f"/api/knowledge/documents/{doc.id}/",
            json.dumps({"domain": "geology"}),
            content_type="application/json",
            HTTP_X_PROJECT_ID=str(env.project.id),
        )
        assert denied.status_code == 404


def test_task_queries_and_import_obey_algorithm_and_data_selection(compute_env):
    from apps.compute.services import submit

    env = compute_env
    task = submit(env["owner"], env["body"])
    item = run(env, "查询进度", selected=False)
    AgentComputeFollowup.objects.create(run=item, task=task)
    item.algorithm_selection_mode = "manual"
    item.algorithm_version_ids = [env["ndvi"].id]
    for tool in ("get_compute_task", "import_compute_result"):
        with pytest.raises(PermissionDenied, match="手选"):
            execute(item, tool, {"taskId": str(task.id)})
    result, _ = execute(item, "list_compute_tasks", {})
    assert not result["items"]
    item.algorithm_selection_mode = "auto"
    item.resource_ids = [env["raster"].id]
    with pytest.raises(PermissionDenied, match="手选"):
        execute(item, "get_compute_task", {"taskId": str(task.id)})


def test_no_kb_new_turn_is_independent_of_revoked_old_knowledge(setup_agent):
    s = setup_agent
    with project_scope(s["scope"]):
        entry = create_entry("geology")
        create_run(
            s,
            "地质判断",
            evidence=[
                {
                    "id": 1,
                    "resourceId": None,
                    "tool": "search_knowledge",
                    "result": {"items": [{"id": entry.id, "revision": entry.revision}]},
                }
            ],
        )
        entry.status = "retired"
        entry.save()
    response = s["client"].post(
        f"/api/agent/conversations/{s['conversation'].id}/runs/",
        json.dumps(
            {
                "model": "mock",
                "prompt": "独立说明",
                "idempotencyKey": "no-kb-revoked-01",
                "knowledgeSelection": {"mode": "none", "domains": []},
            }
        ),
        content_type="application/json",
        **s["header"],
    )
    assert response.status_code == 202, response.content
    from apps.agent.worker import guard
    import time

    item = AgentRun._base_manager.get(pk=response.json()["id"])
    item.status = "running"
    item.save(update_fields=["status"])
    guard(item.id, time.monotonic() + 30)


def test_legacy_domain_assignment_changes_no_text(setup_agent):
    from importlib import import_module
    from django.apps import apps

    with project_scope(setup_agent["scope"]):
        entry = create_entry("geology", title="干旱区NDVI监测")
        original = (entry.title, entry.statement, entry.category, entry.revision)
        migration = import_module(
            "apps.knowledge.migrations.0003_knowledgedocument_domain_knowledgeentry_domain"
        )
        migration.assign_legacy(apps, None)
        entry.refresh_from_db()
        assert entry.domain == "arid_ecology"
        assert (
            entry.title,
            entry.statement,
            entry.category,
            entry.revision,
        ) == original


def test_multiple_versions_of_same_algorithm_require_explicit_version(compute_env):
    from apps.compute.models import AlgorithmVersion
    from apps.agent.compute_intents import match_version

    env = compute_env
    original = env["ndvi"]
    second = AlgorithmVersion.objects.create(
        algorithm=original.algorithm,
        version="2.0.0",
        manifest={**original.manifest, "version": "2.0.0"},
        checksum="b" * 64,
        package_path=original.package_path,
        status="published",
        runtime_digest=original.runtime_digest,
    )
    item = run(env, "计算NDVI")
    item.algorithm_selection_mode = "manual"
    item.algorithm_version_ids = [original.id, second.id]
    assert match_version(item) is None
    assert "多个算法版本" in process(item, env["owner"], env["policy"])
    item.prompt = "计算NDVI 2.0.0"
    assert match_version(item).id == second.id


def test_manual_version_validation_retains_agent_safety_policy(compute_env):
    from apps.agent.selections import validate_selected_versions

    env = compute_env
    version = env["ndvi"]
    version.manifest = {**version.manifest, "agent": {"enabled": False}}
    version.save(update_fields=["manifest"])
    with pytest.raises(PermissionDenied, match="不允许"):
        validate_selected_versions({"algorithm_version_ids": [version.id]})


@pytest.mark.parametrize(
    "tool",
    [
        "execute_operator",
        "get_compute_task",
        "list_compute_tasks",
        "import_compute_result",
    ],
)
def test_all_task_history_uses_real_algorithm_and_input_scope(compute_env, tool):
    from apps.compute.services import submit
    from apps.agent.selections import history_compatible

    env = compute_env
    task = submit(env["owner"], env["body"])
    old = run(env, "旧任务状态", selected=False)
    old.knowledge_selection = {"mode": "auto", "domains": [], "_contextRunIds": []}
    # Even a matching-looking snapshot cannot override the actual task version.
    result = {"taskId": str(task.id), "versionId": env["ndvi"].id}
    old.evidence = [
        {
            "id": 1,
            "tool": tool,
            "resourceId": None,
            "result": {"items": [result]} if tool == "list_compute_tasks" else result,
        }
    ]
    old.save()
    current = run(env, "查询当前选定任务", selected=False)
    current.algorithm_selection_mode = "manual"
    current.algorithm_version_ids = [env["ndvi"].id]
    assert not history_compatible(old, current)
    current.algorithm_selection_mode = "auto"
    current.resource_ids = [env["raster"].id]
    assert not history_compatible(old, current)
    current.resource_ids = [env["resource"].id]
    assert history_compatible(old, current)


def test_followup_counts_only_tasks_in_current_selection(compute_env):
    from apps.compute.services import submit
    from apps.agent.compute_intents import conversation_tasks

    env = compute_env
    table = submit(env["owner"], env["body"])
    ndvi = submit(
        env["owner"],
        {
            "name": "影像NDVI",
            "versionId": env["ndvi"].id,
            "inputs": {"image": env["raster"].id},
            "parameters": {"red": 3, "nir": 8},
            "idempotencyKey": "zones-followup-ndvi",
            "trial": False,
        },
    )
    for task in (table, ndvi):
        old = run(env, "已提交", selected=False)
        AgentComputeFollowup.objects.create(run=old, task=task)
        old.evidence = [
            {
                "id": 1,
                "tool": "get_compute_task",
                "resourceId": None,
                "result": {"taskId": str(task.id)},
            }
        ]
        old.save()
    current = run(env, "跑完了吗")
    current.algorithm_selection_mode = "manual"
    current.algorithm_version_ids = [env["ndvi"].id]
    current.save()
    assert conversation_tasks(current) == [str(ndvi.id)]
    assert "多项" not in process(current, env["owner"], env["policy"])


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(
    "mode, domains", [("none", []), ("manual", ["remote_sensing"])]
)
def test_derived_knowledge_summaries_are_filtered_without_direct_evidence(
    setup_agent, legacy, mode, domains
):
    from apps.agent.selections import history_compatible

    s = setup_agent
    with project_scope(s["scope"]):
        entry = create_entry("geology", "矿物依据")
        first = create_run(
            s,
            "地质推理",
            answer="矿物来源内容",
            evidence=[
                {
                    "id": 1,
                    "resourceId": None,
                    "tool": "search_knowledge",
                    "result": {"items": [{"id": entry.id, "revision": entry.revision}]},
                }
            ],
        )
        summary = create_run(s, "总结上轮", answer="继承的矿物结论")
        context_messages(summary, default_policy(), None)
        summary.refresh_from_db()
        assert first.id in summary.knowledge_selection["_contextRunIds"]
        if legacy:
            summary.knowledge_selection.pop("_contextRunIds")
            summary.save(update_fields=["knowledge_selection"])
        current = create_run(
            s, "独立说明", knowledge_selection={"mode": mode, "domains": domains}
        )
        assert not history_compatible(summary, current)
        rendered = json.dumps(
            context_messages(current, default_policy(), None), ensure_ascii=False
        )
        assert "继承的矿物结论" not in rendered
        assert "矿物来源内容" not in rendered


def test_summary_source_permission_is_rechecked(setup_agent):
    s = setup_agent
    with project_scope(s["scope"]):
        entry = create_entry("geology")
        create_run(
            s,
            "地质判断",
            evidence=[
                {
                    "id": 1,
                    "resourceId": None,
                    "tool": "search_knowledge",
                    "result": {"items": [{"id": entry.id, "revision": entry.revision}]},
                }
            ],
        )
        summary = create_run(s, "总结上轮", answer="旧资料派生结论")
        context_messages(summary, default_policy(), None)
        entry.status = "retired"
        entry.save()
        current = create_run(s, "地质说明")
        rendered = json.dumps(
            context_messages(current, default_policy(), None), ensure_ascii=False
        )
        assert "旧资料派生结论" not in rendered
