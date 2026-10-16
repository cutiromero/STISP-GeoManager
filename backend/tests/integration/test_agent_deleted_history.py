"""Confirmed deletion retains readable history without relaxing live access."""
# ruff: noqa: F811 - reusable pytest fixtures are injected by name.

import json

import pytest
from django.contrib.auth.models import Permission

from apps.agent.models import AgentPolicy, AgentRun, AgentWorkflow
from apps.agent.policy import default_policy
from apps.catalog.models import DataResource
from apps.compute.models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeInput,
    ComputeTask,
)
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401


def prepare_history(env, *, research=False):
    env["user"].user_permissions.add(
        Permission.objects.get(codename="delete_dataresource")
    )
    with project_scope(env["scope"]):
        resource = env["resource"]
        resource.is_compute_result = True
        resource.save(update_fields=["is_compute_result"])
        algorithm = AlgorithmResource.objects.create(
            identifier="history", name="历史算法", created_by=env["user"]
        )
        version = AlgorithmVersion.objects.create(
            algorithm=algorithm, version="1", checksum="history", status="published"
        )
        task = ComputeTask.objects.create(
            name="历史任务",
            owner=env["user"],
            version=version,
            status="succeeded",
            idempotency_key="historical-task",
            request_hash="x",
        )
        ComputeInput.objects.create(task=task, key="image", resource=resource)
        run = AgentRun.objects.create(
            conversation=env["conversation"],
            owner=env["user"],
            model="mock",
            prompt="统计计算结果",
            answer="结果均值为4",
            status="succeeded",
            idempotency_key="history-run",
            resource_ids=[resource.id],
            evidence=[
                {
                    "id": "E1",
                    "tool": "describe_resource",
                    "resourceId": resource.id,
                    "result": {"name": resource.name},
                }
            ],
            compute_intent={"versionId": version.id, "inputs": {"image": resource.id}},
        )
        if research:
            workflow = AgentWorkflow.objects.create(
                owner=env["user"],
                goal="历史分析",
                model="mock",
                status="succeeded",
                idempotency_key="history-workflow",
                resource_ids=[resource.id],
                plan={"inputs": {"map": resource.id}},
            )
            run.research_workflow = workflow
            run.research_intent = {
                "originRunId": run.id,
                "revision": "r1",
                "scenario": "geology_map_review",
                "status": "succeeded",
                "goal": "历史分析",
                "message": "已完成",
                "questions": [],
                "inputs": {"map": resource.id},
                "parameters": {},
                "inputSummary": [],
                "workflowId": str(workflow.id),
            }
            run.save(update_fields=["research_workflow", "research_intent"])
    return run


def delete_confirmed(env):
    endpoint = "/api/catalog/resources/"
    value = {"resourceIds": [env["resource"].id]}
    preview = env["client"].post(
        endpoint + "delete-preview/",
        json.dumps(value),
        content_type="application/json",
        **env["header"],
    )
    assert preview.status_code == 200, preview.content
    response = env["client"].post(
        endpoint + "delete/",
        json.dumps(
            {
                **value,
                "confirmed": True,
                "historyConfirmationToken": preview.json()["confirmationToken"],
            }
        ),
        content_type="application/json",
        **env["header"],
    )
    assert response.json()["deletedCount"] == 1, response.content


@pytest.mark.parametrize("research", [False, True])
def test_confirmed_deletion_keeps_conversation_readable(setup_agent, research):
    env = setup_agent
    run = prepare_history(env, research=research)
    delete_confirmed(env)
    response = env["client"].get(
        f"/api/agent/conversations/{run.conversation_id}/", **env["header"]
    )
    assert response.status_code == 200, response.content
    saved = response.json()["runs"][0]
    assert saved["answer"] == "结果均值为4"
    assert saved["computeIntent"] is None
    run.refresh_from_db()
    assert run.execution_state["deletedResources"][0]["name"] == env["resource"].name


def test_missing_or_revoked_resource_is_not_a_deletion_receipt(setup_agent):
    env = setup_agent
    run = prepare_history(env)
    with project_scope(env["scope"]):
        DataResource.objects.filter(pk=env["resource"].id).update(owner_only=True)
    response = env["client"].get(
        f"/api/agent/conversations/{run.conversation_id}/", **env["header"]
    )
    assert response.status_code == 403


def test_deleted_input_task_preserves_original_manual_selection(setup_agent):
    env = setup_agent
    run = prepare_history(env)
    env["user"].user_permissions.add(Permission.objects.get(codename="view_own_task"))
    with project_scope(env["scope"]):
        task = ComputeTask.objects.get(owner=env["user"])
        run.evidence.append(
            {
                "id": "E2",
                "tool": "get_compute_task",
                "resourceId": None,
                "result": {"taskId": str(task.id)},
            }
        )
        run.save(update_fields=["evidence"])
    delete_confirmed(env)
    response = env["client"].get(f"/api/agent/runs/{run.id}/", **env["header"])
    assert response.status_code == 200, response.content
    assert response.json()["run"]["evidence"][1]["result"]["taskId"] == str(task.id)


@pytest.mark.parametrize(
    "restriction", ["missing_receipt", "active", "data_type", "task_data_type"]
)
def test_tombstone_does_not_enable_missing_proof_or_resumed_execution(
    setup_agent, restriction
):
    env = setup_agent
    run = prepare_history(env)
    delete_confirmed(env)
    with project_scope(env["scope"]):
        run.refresh_from_db()
        if restriction == "missing_receipt":
            run.execution_state = {}
            run.save(update_fields=["execution_state"])
        elif restriction == "active":
            run.status = "running"
            run.save(update_fields=["status"])
        else:
            AgentPolicy.objects.create(
                value={**default_policy(), "dataTypes": ["raster"]}
            )
            if restriction == "task_data_type":
                env["user"].user_permissions.add(
                    Permission.objects.get(codename="view_own_task")
                )
                task = ComputeTask.objects.get(owner=env["user"])
                run.evidence = [
                    {
                        "id": "E1",
                        "tool": "get_compute_task",
                        "resourceId": None,
                        "result": {"taskId": str(task.id)},
                    }
                ]
                run.resource_ids, run.compute_intent = [], {}
                run.save(update_fields=["evidence", "resource_ids", "compute_intent"])
    response = env["client"].get(f"/api/agent/runs/{run.id}/", **env["header"])
    assert response.status_code == 403, response.content


def test_revoked_owner_only_history_never_gets_a_readable_receipt(setup_agent):
    env = setup_agent
    run = prepare_history(env)
    with project_scope(env["scope"]):
        DataResource.objects.filter(pk=env["resource"].id).update(
            owner_only=True, maintainer=env["other"]
        )
    env["client"].force_login(env["admin"])
    delete_confirmed(env)
    env["client"].force_login(env["user"])
    response = env["client"].get(f"/api/agent/runs/{run.id}/", **env["header"])
    assert response.status_code == 403, response.content
    run.refresh_from_db()
    assert not run.execution_state.get("deletedResources")


def test_demo_history_checks_remaining_live_resources(setup_agent):
    env = setup_agent
    run = prepare_history(env, research=True)
    AgentPolicy.objects.create(value={**default_policy(), "operatorEnabled": True})
    with project_scope(env["scope"]):
        live = DataResource.objects.create(
            name="仍需授权的观测", code="live-proof", data_type="table"
        )
        workflow = run.research_workflow
        workflow.plan.update(
            {
                "scenarioVersion": 1,
                "inputSnapshots": {"map": env["resource"].updated_at.isoformat()},
                "algorithms": {},
                "stages": [{"outputs": [{"resourceId": live.id}]}],
            }
        )
        workflow.save(update_fields=["plan"])
    delete_confirmed(env)
    # The deleted input is readable history; an unrelated live privacy boundary remains.
    with project_scope(env["scope"]):
        DataResource.objects.filter(pk=live.id).update(owner_only=True)
    response = env["client"].get(f"/api/agent/runs/{run.id}/", **env["header"])
    assert response.status_code == 403, response.content


def test_demo_history_keeps_deleted_stage_readable(setup_agent):
    env = setup_agent
    run = prepare_history(env, research=True)
    AgentPolicy.objects.create(value={**default_policy(), "operatorEnabled": True})
    with project_scope(env["scope"]):
        workflow = run.research_workflow
        workflow.import_results = False
        workflow.plan.update(
            {
                "scenarioVersion": 1,
                "inputSnapshots": {"map": env["resource"].updated_at.isoformat()},
                "algorithms": {},
                "stages": [{"outputs": [{"resourceId": env["resource"].id}]}],
            }
        )
        workflow.save(update_fields=["plan", "import_results"])
    delete_confirmed(env)
    response = env["client"].get(f"/api/agent/runs/{run.id}/", **env["header"])
    assert response.status_code == 200, response.content
    assert response.json()["run"]["researchIntent"]["status"] == "succeeded"
