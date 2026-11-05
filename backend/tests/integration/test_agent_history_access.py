"""Saved history survives metadata edits; execution and privacy stay strict."""
# ruff: noqa: F811 - reusable pytest fixtures are injected by name.

import json
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied

from apps.agent.demo_workflow import authorize_demo
from apps.agent.models import AgentPolicy, AgentRun, RunEvent
from apps.agent.policy import default_policy
from apps.agent.research_intents import authorize_run
from apps.agent.workflow import _authorize, _state_hash
from apps.catalog.models import DataResource
from apps.compute.models import ComputeImport, ComputeOutput, ComputeTask
from apps.projects.context import project_scope
from apps.projects.models import ProjectMembership
from tests.integration.test_agent import setup_agent  # noqa: F401
from tests.integration.test_agent_deleted_history import (
    prepare_history,
    delete_confirmed,
)


def bind_input_provenance(env):
    """The historical input is an actual imported result from an earlier task."""
    resource = env["resource"]
    downstream = ComputeTask.objects.get(input_records__resource=resource)
    upstream = ComputeTask.objects.create(
        name="历史输入原计算",
        owner=env["user"],
        version=downstream.version,
        status="succeeded",
        idempotency_key="history-input-origin",
        request_hash="origin",
    )
    output = ComputeOutput.objects.create(
        task=upstream,
        key="samples",
        label=resource.name,
        kind=resource.data_type,
        file_name="samples.sqlite",
        path="history/samples.sqlite",
        size_bytes=100,
        checksum="b" * 64,
    )
    ComputeImport.objects.create(
        output=output,
        requested_by=env["user"],
        name=resource.name,
        status="ready",
        resource=resource,
    )


def history(env):
    AgentPolicy.objects.create(value={**default_policy(), "operatorEnabled": True})
    with project_scope(env["scope"]):
        item = prepare_history(env, research=True)
        bind_input_provenance(env)
        item.compute_intent = {}
        item.research_intent["_inputRevisions"] = {
            "map": env["resource"].updated_at.isoformat()
        }
        item.save(update_fields=["compute_intent", "research_intent"])
        workflow = item.research_workflow
        workflow.workflow_type = "geology_map_review"
        workflow.plan.update(
            scenarioVersion=1,
            inputSnapshots=dict(item.research_intent["_inputRevisions"]),
            algorithms={},
            stages=[],
        )
        workflow.import_results = False
        workflow.plan_hash = _state_hash(workflow.plan)
        workflow.save(
            update_fields=["plan", "plan_hash", "import_results", "workflow_type"]
        )
        RunEvent.objects.create(
            run=item, kind="thinking", text="已读取实际资料并核对统计。"
        )
    return item


def get_run(env, item):
    return env["client"].get(f"/api/agent/runs/{item.id}/", **env["header"])


def assert_saved_content(env, item):
    response = get_run(env, item)
    assert response.status_code == 200, response.content
    saved = response.json()["run"]
    assert saved["prompt"] == item.prompt and saved["answer"] == item.answer
    assert saved["thinkingText"] == "已读取实际资料并核对统计。"
    assert saved["evidence"] == item.evidence
    return saved


@pytest.mark.parametrize("workflow_status", ["succeeded", "waiting_compute"])
def test_renaming_input_keeps_original_chat_and_workflow_readable(
    setup_agent, workflow_status
):
    env = setup_agent
    item = history(env)
    with project_scope(env["scope"]):
        resource = env["resource"]
        resource.name = "更新后的资料名称"
        resource.description = "补充说明"
        resource.save()
        workflow = item.research_workflow
        workflow.status = workflow_status
        workflow.save(update_fields=["status"])
    assert_saved_content(env, item)
    detail = env["client"].get(f"/api/agent/workflows/{workflow.id}/", **env["header"])
    assert detail.status_code == 200, detail.content
    listing = env["client"].get("/api/agent/workflows/", **env["header"])
    assert str(workflow.id) in {row["id"] for row in listing.json()["items"]}
    # A read does not update frozen execution revisions or silently approve new data.
    item.refresh_from_db()
    with project_scope(env["scope"]):
        with pytest.raises(PermissionDenied, match="科研资料已变化"):
            authorize_run(
                item, env["user"], {**default_policy(), "operatorEnabled": True}
            )
        with pytest.raises(PermissionDenied, match="原始输入已变化"):
            authorize_demo(
                workflow, env["user"], {**default_policy(), "operatorEnabled": True}
            )


def stage_output(env, item):
    with project_scope(env["scope"]):
        resource = DataResource.objects.create(
            name="修正后地质图",
            code="history-stage-output",
            data_type="vector",
            is_compute_result=True,
        )
        task = ComputeTask.objects.get(input_records__resource=env["resource"])
        output = ComputeOutput.objects.create(
            task=task,
            key="corrected",
            label="修正后地质图",
            kind="vector",
            file_name="corrected.gpkg",
            path="history/corrected.gpkg",
            size_bytes=100,
            checksum="a" * 64,
        )
        ComputeImport.objects.create(
            output=output,
            requested_by=env["user"],
            name=resource.name,
            status="ready",
            resource=resource,
        )
        workflow = item.research_workflow
        workflow.steps.create(
            sequence=1,
            kind="submit_operator",
            status="succeeded",
            compute_task_id=task.id,
        )
        workflow.plan["stages"] = [
            {
                "taskId": str(task.id),
                "outputs": [
                    {
                        "resourceId": resource.id,
                        "outputId": output.id,
                        "checksum": output.checksum,
                        "resourceRevision": resource.updated_at.isoformat(),
                    }
                ],
            }
        ]
        workflow.plan_hash = _state_hash(workflow.plan)
        workflow.save(update_fields=["plan", "plan_hash"])
    return resource, output


def test_output_rename_is_history_only_and_import_relation_stays_verified(setup_agent):
    env = setup_agent
    item = history(env)
    resource, output = stage_output(env, item)
    resource.name = "新的结果名称"
    with project_scope(env["scope"]):
        resource.save()
    assert_saved_content(env, item)
    with project_scope(env["scope"]):
        with pytest.raises(PermissionDenied, match="下游输入"):
            authorize_demo(
                item.research_workflow,
                env["user"],
                {**default_policy(), "operatorEnabled": True},
            )
        ComputeImport.objects.filter(output=output).update(status="failed")
    assert get_run(env, item).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_followup_history_and_workflow_get_retain_confirmed_deleted_stage(setup_agent):
    env = setup_agent
    item = history(env)
    with project_scope(env["scope"]):
        workflow = item.research_workflow
        workflow.plan["stages"] = [{"outputs": [{"resourceId": env["resource"].id}]}]
        workflow.save(update_fields=["plan"])
        later = AgentRun.objects.create(
            conversation=item.conversation,
            owner=env["user"],
            model="mock",
            prompt="这次结果如何",
            answer="这是已保存的后续说明。",
            status="succeeded",
            idempotency_key="history-followup",
            knowledge_selection={"_contextRunIds": [item.id]},
        )
    delete_confirmed(env)
    assert_saved_content(env, item)
    assert get_run(env, later).status_code == 200
    detail = env["client"].get(f"/api/agent/workflows/{workflow.id}/", **env["header"])
    assert detail.status_code == 200, detail.content
    with project_scope(env["scope"]):
        workflow.refresh_from_db()
        item.refresh_from_db()
        with pytest.raises(PermissionDenied):
            authorize_run(
                item, env["user"], {**default_policy(), "operatorEnabled": True}
            )
        with pytest.raises(PermissionDenied):
            authorize_demo(
                workflow, env["user"], {**default_policy(), "operatorEnabled": True}
            )
        with pytest.raises(PermissionDenied, match="引用的数据已删除"):
            _authorize(workflow)


@pytest.mark.parametrize(
    "restriction", ["owner_only", "membership", "data_type", "operator"]
)
def test_read_history_never_bypasses_actual_revocation(setup_agent, restriction):
    env = setup_agent
    item = history(env)
    with project_scope(env["scope"]):
        if restriction == "owner_only":
            DataResource.objects.filter(pk=env["resource"].id).update(owner_only=True)
        elif restriction == "membership":
            ProjectMembership.objects.filter(
                user=env["user"], project=env["project"]
            ).delete()
        else:
            change = (
                {"dataTypes": ["raster"]}
                if restriction == "data_type"
                else {"operatorEnabled": False}
            )
            AgentPolicy.objects.update(value={**default_policy(), **change})
    assert get_run(env, item).status_code in {403, 404}


def test_changed_revision_cannot_be_approved_as_the_original_plan(setup_agent):
    env = setup_agent
    item = history(env)
    with project_scope(env["scope"]):
        env["resource"].name = "修改后资料"
        env["resource"].save()
        workflow = item.research_workflow
        workflow.status = "waiting_approval"
        workflow.plan["phase"] = "review_plan"
        workflow.plan_hash = _state_hash(workflow.plan)
        workflow.save(update_fields=["status", "plan", "plan_hash"])
    response = env["client"].post(
        f"/api/agent/workflows/{workflow.id}/confirm/",
        json.dumps({"planHash": workflow.plan_hash}),
        content_type="application/json",
        **env["header"],
    )
    assert response.status_code == 403, response.content
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval" and not workflow.execute_operators


def test_compute_history_does_not_reopen_live_candidate_forms(setup_agent):
    from apps.agent.compute_intents import serialize

    env = setup_agent
    with project_scope(env["scope"]):
        item = prepare_history(env)
        version = ComputeTask.objects.get(owner=env["user"]).version
        version.manifest = {"inputs": []}
        version.save(update_fields=["manifest"])
        item.compute_intent.update(
            {
                "status": "submitted",
                "message": "完成",
                "parameters": {},
                "missingInputs": [],
                "missingParameters": [],
                "warnings": [],
                "knowledgeEvidenceIds": [],
                "taskId": None,
                "autoImport": False,
                "planRevision": "saved",
            }
        )
        with patch("apps.agent.compute_intents._candidate") as candidate:
            data = serialize(item, env["user"], default_policy(), history=True)
        assert data["inputCandidates"] == []
        candidate.assert_not_called()
        with pytest.raises(PermissionDenied, match="不在当前业务数据范围"):
            serialize(item, env["user"], default_policy())
        # Pending parameter cards still need current choices during normal polling.
        bind_input_provenance(env)
        version.manifest = {"inputs": [{"key": "image", "kind": "table"}]}
        version.save(update_fields=["manifest"])
        for status, intent_status in [
            ("waiting_input", "submitted"),
            ("succeeded", "collecting"),
        ]:
            item.status = status
            item.compute_intent["status"] = intent_status
            with patch(
                "apps.agent.compute_intents._candidate",
                return_value={"id": env["resource"].id},
            ) as candidate:
                data = serialize(item, env["user"], default_policy(), history=True)
            assert data["inputCandidates"] == [{"id": env["resource"].id}]
            candidate.assert_called_once()
        item.save(update_fields=["status", "compute_intent"])
    response = get_run(env, item)
    assert response.status_code == 200, response.content
    candidates = response.json()["run"]["computeIntent"]["inputCandidates"]
    selected = next(row for row in candidates if row["id"] == env["resource"].id)
    assert selected["name"] == env["resource"].name
