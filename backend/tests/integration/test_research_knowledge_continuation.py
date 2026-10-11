"""Research auto routing persists task scope without widening explicit selections."""

import json
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.agent.demo_workflow import prepare_demo
from apps.agent.models import AgentWorkflow
from apps.agent.research_intents import _auto_continuation_selection, process
from apps.agent.selections import knowledge_domains
from apps.catalog.models import DataResource
from apps.knowledge.models import KnowledgeEntry
from tests.integration.test_chat_research_intent import (
    bridge,
    catalog,
    parsed,
    post,
    run,
)
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401

pytestmark = pytest.mark.django_db
AUTO_DOMAINS = {"remote_sensing", "arid_ecology"}


def establish(env):
    first = run(env, "请分析两期影像植被变化并选择调查优先区")
    first.knowledge_selection = {"mode": "auto", "domains": [], "_contextRunIds": []}
    first.save()
    bridge(env, first, parsed(env))
    workflow = first.research_workflow
    prepare_demo(workflow, env["owner"], env["policy"])
    workflow.refresh_from_db()
    entries = [
        KnowledgeEntry.objects.create(
            title="模拟 NDVI " + domain,
            domain=domain,
            category="模拟测试",
            statement="测试科研续答保留实际知识分区",
            status="published",
            updated_by=env["owner"],
        )
        for domain in AUTO_DOMAINS
    ]
    workflow.evidence = [
        {"id": e.id, "revision": e.revision, "domain": e.domain} for e in entries
    ]
    workflow.status = "succeeded"
    workflow.save()
    first.refresh_from_db()
    return first, workflow, entries


def followup(env, first, prompt="接着刚才的生态分析，补充新增观测并更新调查建议"):
    later = run(env, prompt, conversation=first.conversation)
    later.knowledge_selection = {"mode": "auto", "domains": [], "_contextRunIds": []}
    later.save()
    return later


def test_new_research_task_records_its_actual_auto_domains(demo):  # noqa: F811
    first = run(demo, "请评估生态风险并选择调查优先区")
    first.knowledge_selection = {"mode": "auto", "domains": []}
    first.save()
    assert knowledge_domains(first) == ["arid_ecology"]
    bridge(demo, first, parsed(demo))
    first.refresh_from_db()
    assert set(knowledge_domains(first)) == AUTO_DOMAINS
    assert set(knowledge_domains(first, "油气管道")) == AUTO_DOMAINS
    assert first.knowledge_selection["mode"] == "auto"
    assert first.knowledge_selection["domains"] == []


def test_actual_parser_receives_bound_workflow_for_new_ecology_evidence(demo):  # noqa: F811
    first, original, _ = establish(demo)
    later = followup(demo, first)
    assert knowledge_domains(later) == ["arid_ecology"]
    updated = DataResource.objects.create(
        name="模拟 · 新增观测",
        code="new-observation",
        data_type="table",
        maintainer=demo["owner"],
    )
    choices = catalog(demo)
    choices["scenarios"][0]["inputs"]["context"].append(
        {"id": updated.id, "name": updated.name, "sourceNote": "模拟新增证据"}
    )
    response = parsed(demo, "update")
    response["inputs"]["context"] = updated.id
    with (
        patch("apps.agent.research_presets.discover", return_value=choices),
        patch("apps.agent.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=256),
        patch("apps.agent.provider.stream", return_value=iter([json.dumps(response)])),
    ):
        process(later, demo["owner"], demo["policy"], lambda: None, lambda *args: None)
    later.refresh_from_db()
    assert set(knowledge_domains(later)) == AUTO_DOMAINS
    assert later.knowledge_selection["_researchSourceRunId"] == first.id
    request = later.research_intent["_parserAudit"]["request"]
    assert request["priorIntent"]["workflowId"] == str(original.id)
    assert request["workflow"]["status"] == "succeeded"
    assert later.research_workflow.plan["previousWorkflowId"] == str(original.id)
    assert later.research_workflow.plan["inputs"]["context"] == updated.id
    assert later.research_intent["originRunId"] == later.id
    assert AgentWorkflow.objects.count() == 2


def test_short_status_continuation_keeps_only_task_domains(demo):  # noqa: F811
    first, workflow, _ = establish(demo)
    later = followup(demo, first, "跑完了吗")
    bridge(demo, later, parsed(demo, "status"))
    later.refresh_from_db()
    assert later.research_workflow_id == workflow.id
    assert set(knowledge_domains(later)) == AUTO_DOMAINS
    assert AgentWorkflow.objects.count() == 1


@pytest.mark.parametrize("mode", ["none", "manual"])
def test_explicit_knowledge_narrowing_never_inherits_domains(demo, mode):  # noqa: F811
    first, _, _ = establish(demo)
    later = followup(demo, first)
    later.knowledge_selection = {
        "mode": mode,
        "domains": ["arid_ecology"] if mode == "manual" else [],
        "_resolvedDomains": list(AUTO_DOMAINS),
    }
    later.save()
    with (
        patch("apps.agent.research_presets.discover", return_value=catalog(demo)),
        patch(
            "apps.agent.research_intents.interpret",
            return_value=(parsed(demo, "update"), {}),
        ) as model,
        pytest.raises(ValidationError, match="本会话没有"),
    ):
        process(later, demo["owner"], demo["policy"], lambda: None, lambda *args: None)
    assert model.call_args.args[4] is None and model.call_args.args[5] is None
    assert knowledge_domains(later) == (["arid_ecology"] if mode == "manual" else [])
    assert "_researchSourceRunId" not in later.knowledge_selection
    assert AgentWorkflow.objects.count() == 1


def test_full_manual_knowledge_scope_remains_manual(demo):  # noqa: F811
    first, workflow, _ = establish(demo)
    later = followup(demo, first)
    later.knowledge_selection = {"mode": "manual", "domains": list(AUTO_DOMAINS)}
    later.save()
    bridge(demo, later, parsed(demo, "status"))
    later.refresh_from_db()
    assert later.research_workflow_id == workflow.id
    assert "_resolvedDomains" not in later.knowledge_selection
    assert set(knowledge_domains(later)) == AUTO_DOMAINS


@pytest.mark.parametrize("ceiling", ["data", "algorithm"])
def test_auto_knowledge_does_not_bypass_data_or_algorithm_selection(
    demo,  # noqa: F811
    ceiling,
):
    first, _, _ = establish(demo)
    later = followup(demo, first)
    if ceiling == "data":
        later.resource_ids = [demo["inputs"]["context"]]
        later.data_selection_mode = "manual"
    else:
        later.algorithm_selection_mode = "manual"
        later.algorithm_version_ids = [demo["versions"]["raster-ndvi"].id]
    later.save()
    with (
        patch("apps.agent.research_presets.discover", return_value=catalog(demo)),
        patch(
            "apps.agent.research_intents.interpret",
            return_value=({"action": "ordinary"}, {}),
        ) as model,
    ):
        assert (
            process(
                later, demo["owner"], demo["policy"], lambda: None, lambda *args: None
            )
            is None
        )
    later.refresh_from_db()
    assert model.call_args.args[4] is None
    assert "_resolvedDomains" not in later.knowledge_selection
    assert "_researchSourceRunId" not in later.knowledge_selection


@pytest.mark.parametrize("boundary", ["owner_id", "project_tag_id", "conversation_id"])
def test_inheritance_requires_same_authorized_research_context(demo, boundary):  # noqa: F811
    first, _, _ = establish(demo)
    later = followup(demo, first)
    setattr(later, boundary, getattr(later, boundary) + 1000)
    assert _auto_continuation_selection(first, later) is None


@pytest.mark.parametrize("revocation", ["resource", "knowledge"])
def test_revoked_source_blocks_model_and_domain_persistence(demo, revocation):  # noqa: F811
    first, _, entries = establish(demo)
    later = followup(demo, first)
    if revocation == "resource":
        DataResource.objects.filter(pk=demo["inputs"]["early_image"]).update(
            owner_only=True, maintainer=demo["outsider"]
        )
    else:
        KnowledgeEntry.objects.filter(pk=entries[0].id).update(status="draft")
    with (
        patch("apps.agent.research_intents.interpret") as model,
        pytest.raises(PermissionDenied),
    ):
        process(later, demo["owner"], demo["policy"], lambda: None, lambda *args: None)
    model.assert_not_called()
    later.refresh_from_db()
    assert "_resolvedDomains" not in later.knowledge_selection


def test_unrelated_topic_keeps_ordinary_auto_domain_inference(demo):  # noqa: F811
    first, _, _ = establish(demo)
    later = followup(demo, first, "请更新地质填图并检查修改结果")
    with (
        patch("apps.agent.research_presets.discover", return_value=catalog(demo)),
        patch(
            "apps.agent.research_intents.interpret",
            return_value=({"action": "ordinary"}, {}),
        ) as model,
    ):
        assert (
            process(
                later, demo["owner"], demo["policy"], lambda: None, lambda *args: None
            )
            is None
        )
    later.refresh_from_db()
    assert model.call_args.args[4] is None
    assert knowledge_domains(later) == ["geology"]
    assert "_resolvedDomains" not in later.knowledge_selection


def test_hidden_domain_markers_do_not_change_public_selection_or_submit_replay(
    demo,  # noqa: F811
):
    first, _, _ = establish(demo)
    body = {
        "model": first.model,
        "prompt": first.prompt,
        "idempotencyKey": first.idempotency_key,
        "knowledgeSelection": {"mode": "auto", "domains": []},
    }
    response = demo["client"].post(
        f"/api/agent/conversations/{first.conversation_id}/runs/",
        json.dumps(body),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(demo["project"].id),
    )
    assert response.status_code == 202, response.content
    assert response.json()["id"] == first.id
    assert response.json()["knowledgeSelection"] == {"mode": "auto", "domains": []}
    assert set(response.json()["resolvedKnowledgeDomains"]) == AUTO_DOMAINS


def test_parser_ordinary_action_restores_original_auto_topic_scope(demo):  # noqa: F811
    first, _, _ = establish(demo)
    later = followup(demo, first, "新增一个油气管道遥感报告，请介绍监测方法")
    with (
        patch("apps.agent.research_presets.discover", return_value=catalog(demo)),
        patch(
            "apps.agent.research_intents.interpret",
            return_value=({"action": "ordinary"}, {}),
        ) as model,
    ):
        assert (
            process(
                later, demo["owner"], demo["policy"], lambda: None, lambda *args: None
            )
            is None
        )
    assert model.call_args.args[4] is not None
    later.refresh_from_db()
    assert knowledge_domains(later) == ["remote_sensing", "pipelines"]
    assert "_resolvedDomains" not in later.knowledge_selection
    assert "_researchSourceRunId" not in later.knowledge_selection


def test_answer_replay_after_workflow_creation_reuses_frozen_run(demo):  # noqa: F811
    first = run(demo)
    first.knowledge_selection = {"mode": "auto", "domains": []}
    first.save()
    question = parsed(demo, "clarify")
    question["parameters"].pop("nir")
    bridge(demo, first, question)
    first.refresh_from_db()
    value = {
        "action": "answer",
        "revision": first.research_intent["revision"],
        "answers": {"nir": "2"},
    }
    online = [{"alias": "mock", "status": "online", "contextWindowTokens": 32768}]
    with (
        patch("apps.agent.views.worker_online", return_value=True),
        patch("apps.agent.views.visible_models", return_value=online),
        patch("apps.agent.research_actions.visible_models", return_value=online),
    ):
        submitted = post(demo, first, value)
    assert submitted.status_code == 202, submitted.content
    answer = first.conversation.runs.get(pk=submitted.json()["id"])
    bridge(demo, answer, parsed(demo))
    answer.status = "succeeded"
    answer.save(update_fields=["status"])
    replay = post(demo, first, value)
    assert replay.status_code == 202, replay.content
    assert replay.json()["id"] == answer.id
    assert replay.json()["knowledgeSelection"] == {"mode": "auto", "domains": []}
    assert set(replay.json()["resolvedKnowledgeDomains"]) == AUTO_DOMAINS
    assert first.conversation.runs.count() == 2
    assert AgentWorkflow.objects.count() == 1
