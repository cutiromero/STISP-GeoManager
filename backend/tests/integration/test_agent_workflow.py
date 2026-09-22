import json

import pytest

from apps.agent.models import AgentWorkflow
from apps.agent.workflow import HAS_LANGGRAPH, run_workflow
from tests.integration.test_agent import setup_agent  # noqa: F401


def create_workflow(env, **overrides):
    payload = {
        "workflowType": "hyperspectral_interpretation",
        "goal": "识别影像中的矿物和岩性，并检查成矿理论约束",
        "model": "mock",
        "resourceIds": [env["resource"].id],
        "parameters": {},
        "executeOperators": False,
        "idempotencyKey": "workflow-key-01",
    }
    payload.update(overrides)
    response = env["client"].post(
        "/api/agent/workflows/",
        json.dumps(payload),
        content_type="application/json",
        **env["header"],
    )
    return response


@pytest.mark.django_db
def test_workflow_plan_is_persisted_and_does_not_execute_operator(setup_agent):
    env = setup_agent
    response = create_workflow(env)
    assert response.status_code == 202, response.content
    workflow_id = response.json()["id"]
    workflow = AgentWorkflow.objects.get(pk=workflow_id)
    run_workflow(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "succeeded"
    assert workflow.current_step == "finalize"
    assert [step.kind for step in workflow.steps.all()] == [
        "discover_inputs",
        "build_plan",
        "finalize",
    ]
    assert not workflow.execute_operators
    assert workflow.steps.filter(compute_task_id__isnull=False).count() == 0


@pytest.mark.django_db
def test_workflow_operator_request_requires_admin_policy(setup_agent):
    response = create_workflow(setup_agent, executeOperators=True, idempotencyKey="workflow-key-02")
    assert response.status_code == 403
    assert AgentWorkflow.objects.count() == 0


def test_langgraph_is_optional_for_offline_local_replay():
    assert isinstance(HAS_LANGGRAPH, bool)
