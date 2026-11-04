"""Generic upload intake remains conversation-owned and explicitly confirmed."""

import json
import csv
import io
from pathlib import Path

import pytest

from apps.agent.demo_workflow import prepare_demo
from apps.agent.models import AgentRun, AgentWorkflow, Conversation
from apps.agent.research_intents import process, serialize
from apps.agent.workflow_uploads import delete_upload, store_upload
from apps.compute.packages import ComputeError
from apps.compute.models import AlgorithmResource, AlgorithmVersion
from apps.compute.packages import validate_manifest
from apps.core.storage import table_data_path
from apps.knowledge.models import KnowledgeEntry
from tests.integration.test_geology_generic_workflow import geojson

pytestmark = pytest.mark.django_db
pytest_plugins = ["tests.integration.test_geology_generic_workflow"]


@pytest.fixture(autouse=True)
def online_model(monkeypatch):
    online = [{"alias": "mock", "status": "online", "contextWindowTokens": 32768}]
    monkeypatch.setattr("apps.agent.views.worker_online", lambda: True)
    monkeypatch.setattr("apps.agent.views.visible_models", lambda *args: online)
    monkeypatch.setattr(
        "apps.agent.research_actions.visible_models", lambda *args: online
    )


def intake(env, *, catalog=False):
    env["project"].code = "02"
    env["project"].save(update_fields=["code"])
    for suffix in ("check", "apply", "relations", "prospect"):
        manifest = validate_manifest(
            json.loads(
                (
                    Path(__file__).resolve().parents[3]
                    / f"examples/compute/geology-multi-{suffix}/operator.yaml"
                ).read_text(encoding="utf-8")
            )
        )
        algorithm = AlgorithmResource.objects.create(
            identifier=manifest["identifier"],
            name=manifest["name"],
            created_by=env["owner"],
        )
        AlgorithmVersion.objects.create(
            algorithm=algorithm,
            version="1.0.0",
            status="published",
            manifest=manifest,
            checksum="d" * 64,
            runtime_digest="sha256:" + "a" * 64,
        )
    upload = store_upload(env["owner"], env["project"].id, geojson(), env["batch"])
    if catalog:
        from apps.agent.workflow_uploads import add_catalog_references

        resource = upload.resource
        resource.source = "catalog-demo"
        resource.owner_only = False
        resource.save(update_fields=["source", "owner_only"])
        upload.delete()
        upload = add_catalog_references(
            env["owner"], env["project"].id, env["batch"], [resource.id]
        )[0]
    conversation = Conversation.objects.create(owner=env["owner"], mode="agent")
    response = env["client"].post(
        f"/api/agent/conversations/{conversation.id}/runs/",
        json.dumps(
            {
                "model": "mock",
                "prompt": "检查地质图并比较远景区",
                "idempotencyKey": "chat-generic",
                "uploadBatchId": env["batch"],
            }
        ),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )
    assert response.status_code == 202, response.content
    run = AgentRun.objects.get(pk=response.json()["id"])
    process(run, env["owner"], env["policy"], lambda: None, lambda *args: None)
    run.refresh_from_db()
    run.status = "succeeded"
    run.save(update_fields=["status"])
    return run, upload


def answer(env, run, **value):
    run.refresh_from_db()
    intent = serialize(run, env["owner"], env["policy"])
    return env["client"].post(
        f"/api/agent/runs/{run.id}/research-intent/",
        json.dumps({"action": "answer", "revision": intent["revision"], **value}),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


@pytest.mark.parametrize("catalog", [False, True])
def test_chat_roles_bind_then_fields_confirm_and_restore(generic, catalog):
    run, upload = intake(generic, catalog=catalog)
    assert run.research_intent["scenario"] == "geology_generic"
    assert run.research_workflow_id is None
    assert run.research_intent["parameters"]["roleAnswers"] == {
        f"upload_{upload.resource_id}": "lithology"
    }
    response = answer(
        generic, run, answers=run.research_intent["parameters"]["roleAnswers"]
    )
    assert response.status_code == 200, response.content
    run.refresh_from_db()
    workflow = run.research_workflow
    upload.refresh_from_db()
    assert upload.workflow_id == workflow.id
    assert workflow.plan["chatExecution"]["initialPlanAuthorized"] is False
    prepare_demo(workflow, generic["owner"], generic["policy"])
    workflow.refresh_from_db()
    assert workflow.plan["phase"] == "review_mapping"
    response = answer(generic, run, answer="随便继续吧，所有问题你决定")
    assert response.status_code == 400, response.content
    workflow.refresh_from_db()
    assert workflow.plan["phase"] == "review_mapping"
    response = answer(generic, run, answer="确认字段含义")
    assert response.status_code == 200, response.content
    workflow.refresh_from_db()
    assert workflow.plan["phase"] == "build_inputs"
    assert workflow.plan["confirmedMapping"]["lithology"]["name"] == "DCMC"
    detail = generic["client"].get(
        f"/api/agent/conversations/{run.conversation_id}/",
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert detail.status_code == 200, detail.content
    assert detail.json()["runs"][0]["researchIntent"]["workflowId"] == str(workflow.id)


def test_role_text_is_bounded_and_never_silently_confirms(generic):
    run, upload = intake(generic)
    response = answer(generic, run, answer="把第1份资料改为构造线")
    assert response.status_code == 400
    response = answer(generic, run, answer="把第1份资料改为研究区范围")
    assert response.status_code == 200, response.content
    assert (
        response.json()["researchIntent"]["parameters"]["roleAnswers"][
            f"upload_{upload.resource_id}"
        ]
        == "coverage"
    )
    assert not AgentWorkflow.objects.exists()
    response = answer(generic, run, answer="确认资料角色")
    assert response.status_code == 400
    response = answer(generic, run, answer="把第1份资料改为地质图")
    assert response.status_code == 200
    response = answer(generic, run, answer="确认资料角色")
    assert response.status_code == 200, response.content
    assert AgentWorkflow.objects.count() == 1


def test_claim_is_idempotent_and_cannot_be_reused_or_deleted(generic):
    run, upload = intake(generic)
    value = {
        "model": "mock",
        "prompt": run.prompt,
        "idempotencyKey": "chat-generic",
        "uploadBatchId": generic["batch"],
    }
    url = f"/api/agent/conversations/{run.conversation_id}/runs/"
    response = generic["client"].post(
        url,
        json.dumps(value),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert response.status_code == 202, response.content
    assert response.json()["id"] == run.id
    value["idempotencyKey"] = "another-request"
    response = generic["client"].post(
        url,
        json.dumps(value),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert response.status_code == 409, response.content
    with pytest.raises(ComputeError, match="作为任务依据保留"):
        delete_upload(generic["owner"], upload.id)


def test_foreign_conversation_and_batch_are_hidden(generic):
    run, upload = intake(generic)
    from django.contrib.auth import get_user_model

    other = get_user_model().objects.create_user(
        username="generic-other", is_superuser=True, is_staff=True
    )
    generic["client"].force_login(other)
    response = generic["client"].get(
        f"/api/agent/conversations/{run.conversation_id}/",
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert response.status_code == 404
    response = answer(generic, run, answer="确认资料角色")
    assert response.status_code == 404
    response = generic["client"].get(
        "/api/agent/workflow-uploads/",
        {"batchId": generic["batch"]},
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert response.status_code == 200
    assert response.json()["items"] == []
    conversation = Conversation.objects.create(owner=other, mode="agent")
    response = generic["client"].post(
        f"/api/agent/conversations/{conversation.id}/runs/",
        json.dumps(
            {
                "model": "mock",
                "prompt": "检查",
                "idempotencyKey": "foreign",
                "uploadBatchId": generic["batch"],
            }
        ),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert response.status_code == 409


def test_plan_and_scoped_approval_use_original_checks(
    generic, monkeypatch, record_property
):
    from apps.agent.demo_workflow import _save
    from apps.agent.geology_multi import FIELDS, SCENARIO
    from tests.integration.test_geology_multi_workflow import fixture_review

    entries = []
    for rule_id in ("L-03", "A-01"):
        entries.append(
            KnowledgeEntry.objects.create(
                title=rule_id,
                domain="geology",
                status="draft",
                statement="核对当前实测依据",
                conditions=["本示范区"],
                exceptions=["不足时保留"],
                sources=[{"title": "测试规则", "locator": rule_id}],
                rule_config={
                    "trialScope": {
                        "scenario": SCENARIO,
                        "projectId": generic["project"].id,
                        "ruleId": rule_id,
                        "ruleVersion": "0.1-draft",
                    },
                    "parameters": {"threshold": 0.5},
                    "rule": {"id": rule_id},
                },
            )
        )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS)
    writer.writeheader()
    for entry in entries:
        writer.writerow(
            {
                "rule_id": entry.title,
                "rule_version": "0.1-draft",
                "knowledge_id": entry.id,
                "knowledge_revision": entry.revision,
                "params_json": "{}",
                "rule_json": "{}",
                "units_json": '{"T3b2":{"name":"八宝山组二段"}}',
                "aliases_json": '{"八宝山组二段":"T3b2"}',
            }
        )
    path = table_data_path("generic-chat/rules.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stream.getvalue(), encoding="utf-8")
    generic["rules"].storage_path = "table/generic-chat/rules.csv"
    generic["rules"].file_format = "CSV"
    generic["rules"].save()
    run, _ = intake(generic)
    assert answer(generic, run, answer="确认资料角色").status_code == 200
    run.refresh_from_db()
    workflow = run.research_workflow
    prepare_demo(workflow, generic["owner"], generic["policy"])
    assert answer(generic, run, answer="确认字段含义").status_code == 200
    workflow.refresh_from_db()
    prepare_demo(workflow, generic["owner"], generic["policy"])
    workflow.refresh_from_db()
    assert workflow.plan["phase"] == "review_plan"
    assert not workflow.execute_operators
    assert answer(generic, run, answer="都听你的").status_code == 400
    response = answer(generic, run, answer="确认计划")
    assert response.status_code == 200, response.content
    workflow.refresh_from_db()
    assert workflow.execute_operators and workflow.status == "queued"
    workflow, stage, results = fixture_review(
        {**generic, "workflow": workflow, "entries": entries}
    )
    _save(workflow)
    monkeypatch.setattr(
        "apps.agent.geology_multi_review.read_results", lambda *args: results
    )
    monkeypatch.setattr(
        "apps.agent.geology_multi_review.authorized_task", lambda *args: object()
    )
    response = answer(generic, run, answer="只批准岩性类建议")
    assert response.status_code == 200, response.content
    workflow.refresh_from_db()
    review = workflow.plan["modificationReview"]
    assert review["approvedSuggestionIds"] == [review["suggestions"][0]["id"]]
    assert review["unapprovedSuggestionIds"] == [review["suggestions"][1]["id"]]
    assert workflow.plan["stages"][1]["approvedEdits"][0]["feature_id"] == "N0"
    assert len(workflow.plan["stages"][1]["approvedEdits"]) == 1
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    sizes = {}
    for view in ("card", "full"):
        with CaptureQueriesContext(connection) as queries:
            response = generic["client"].get(
                f"/api/agent/workflows/{workflow.id}/?view={view}",
                HTTP_X_PROJECT_ID=str(generic["project"].id),
            )
        assert response.status_code == 200, response.content
        sizes[view] = len(response.content)
        record_property(f"{view}_bytes", sizes[view])
        record_property(f"{view}_queries", len(queries))
    assert sizes["card"] < sizes["full"]


def test_role_confirmation_replay_and_stale_revision(generic):
    run, upload = intake(generic)
    value = {
        "action": "answer",
        "revision": run.research_intent["revision"],
        "answer": "确认资料角色",
    }
    url = f"/api/agent/runs/{run.id}/research-intent/"
    first = generic["client"].post(
        url,
        json.dumps(value),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    second = generic["client"].post(
        url,
        json.dumps(value),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert first.status_code == 200, first.content
    assert second.status_code == 202, second.content
    assert first.json()["id"] == second.json()["id"]
    retry = generic["client"].post(
        f"/api/agent/conversations/{run.conversation_id}/runs/",
        json.dumps(
            {
                "model": "mock",
                "prompt": run.prompt,
                "idempotencyKey": "chat-generic",
                "uploadBatchId": generic["batch"],
            }
        ),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert retry.status_code == 202, retry.content
    assert retry.json()["id"] == run.id
    assert AgentWorkflow.objects.count() == 1
    assert AgentRun.objects.count() == 2
    value["answer"] = "确认计划"
    stale = generic["client"].post(
        url,
        json.dumps(value),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert stale.status_code == 409
    upload.refresh_from_db()
    assert upload.workflow_id == AgentWorkflow.objects.get().id


def test_other_project_keeps_ordinary_chat_and_rejects_upload_intake(generic):
    generic["project"].code = "other-research"
    generic["project"].save(update_fields=["code"])
    store_upload(generic["owner"], generic["project"].id, geojson(), generic["batch"])
    conversation = Conversation.objects.create(owner=generic["owner"], mode="agent")
    value = {
        "model": "mock",
        "prompt": "请解释地质研究",
        "idempotencyKey": "other-chat",
    }
    url = f"/api/agent/conversations/{conversation.id}/runs/"
    ordinary = generic["client"].post(
        url,
        json.dumps(value),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert ordinary.status_code == 202, ordinary.content
    value.update(uploadBatchId=generic["batch"], idempotencyKey="other-upload")
    rejected = generic["client"].post(
        url,
        json.dumps(value),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert rejected.status_code == 400


def test_generic_reply_quota_does_not_create_workflow(generic):
    from apps.agent.models import AgentPolicy

    run, _ = intake(generic)
    policy = AgentPolicy.objects.get(pk=1)
    policy.value = {**policy.value, "dailyRuns": 1}
    policy.save(update_fields=["value"])
    response = answer(generic, run, answer="确认资料角色")
    assert response.status_code == 429, response.content
    assert not AgentWorkflow.objects.exists()
    assert AgentRun.objects.count() == 1
