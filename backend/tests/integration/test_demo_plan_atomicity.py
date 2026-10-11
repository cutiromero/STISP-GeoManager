"""Plan preparation and chat confirmation remain recoverable across database failures."""

# ruff: noqa: F811

import copy
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.utils import timezone

from apps.agent.demo_workflow import advance_demo, confirm_demo
from apps.agent.models import AgentCheckpoint, AgentRun, AgentWorkflow
from apps.agent.workflow import checkpoint, resume_waiting, step
from apps.agent.workflow_worker import claim, recover
from apps.catalog.models import DataResource
from apps.compute.models import ComputeTask
from tests.integration.test_chat_research_intent import bridge, parsed, run
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo, finish_task, scenario  # noqa: F401
from tests.integration.test_dual_demo_workflow import (
    completed_ecology,  # noqa: F401
    update_workflow,
)


def chat_update(env):
    workflow = update_workflow(env)
    source = run(env, "使用补充收获记录后的观测更新分析并保存成果")
    source.research_workflow = workflow
    token = {
        "revision": "test-frozen-authorization",
        "originRunId": source.id,
        "requestRunId": source.id,
    }
    source.research_intent = {
        "_executionAuthorized": True,
        "_initialExecutionAuthorization": token,
        "inputs": copy.deepcopy(workflow.plan["inputs"]),
        "_inputRevisions": {
            role: DataResource.objects.get(pk=identity).updated_at.isoformat()
            for role, identity in workflow.plan["inputs"].items()
        },
    }
    source.save()
    workflow.plan["chatExecution"] = {
        **token,
        "initialPlanAuthorized": True,
        "algorithmVersionIds": [env["versions"]["ecology-priority"].id],
        "algorithmSelectionMode": "auto",
        "selectedAlgorithmVersionIds": [],
    }
    workflow.save(update_fields=["plan"])
    return workflow


@pytest.mark.parametrize(
    "mode,boundary",
    [
        ("manual_start", "demo_plan"),
        ("manual_start", "checkpoint"),
        ("chat_start", "checkpoint"),
        ("chat_start", "confirm"),
        ("chat_start", "chat_audit"),
        ("chat_update", "checkpoint"),
        ("chat_update", "confirm"),
        ("chat_update", "chat_audit"),
    ],
)
def test_plan_save_failure_rolls_back_and_recovery_keeps_authorization(
    mode, boundary, request
):
    env = request.getfixturevalue(
        "completed_ecology" if mode == "chat_update" else "demo"
    )
    if mode == "manual_start":
        workflow = scenario(env)
    elif mode == "chat_start":
        source = run(env)
        bridge(env, source, parsed(env))
        workflow = source.research_workflow
    else:
        workflow = chat_update(env)
    task_count = ComputeTask.objects.count()
    original_plan = copy.deepcopy(workflow.plan)
    assert claim() == workflow.id

    def failed_step(current, kind, **kwargs):
        result = step(current, kind, **kwargs)
        if kind == (
            "demo_plan" if boundary == "demo_plan" else "chat_execution_authorized"
        ):
            raise OperationalError("database is locked")
        return result

    def failed_checkpoint(current, node, state):
        checkpoint(current, node, state)
        raise OperationalError("database is locked")

    def failed_confirmation(*args, **kwargs):
        confirm_demo(*args, **kwargs)
        raise OperationalError("database is locked")

    if boundary in {"demo_plan", "chat_audit"}:
        failure = patch("apps.agent.demo_workflow.step", side_effect=failed_step)
    elif boundary == "checkpoint":
        failure = patch(
            "apps.agent.demo_workflow.checkpoint", side_effect=failed_checkpoint
        )
    else:
        failure = patch(
            "apps.agent.demo_workflow.confirm_demo", side_effect=failed_confirmation
        )
    with failure, pytest.raises(OperationalError, match="database is locked"):
        advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "running" and not workflow.execute_operators
    assert workflow.plan == original_plan
    assert not workflow.steps.exists()
    assert not AgentCheckpoint.objects.filter(workflow=workflow).exists()
    assert ComputeTask.objects.count() == task_count
    AgentWorkflow.objects.filter(pk=workflow.id).update(
        heartbeat=timezone.now() - timedelta(seconds=91)
    )
    recover()
    assert claim() == workflow.id
    with patch("apps.agent.demo_decisions.provider.stream") as stream:
        advance_demo(workflow.id)
    stream.assert_not_called()
    workflow.refresh_from_db()
    manual = mode == "manual_start"
    assert workflow.status == ("waiting_approval" if manual else "queued")
    assert workflow.execute_operators is not manual
    assert workflow.plan["phase"] == ("review_plan" if manual else "decide")
    assert workflow.iteration == workflow.operator_steps == 0
    assert workflow.steps.filter(kind="demo_plan").count() == 1
    assert workflow.steps.filter(kind="chat_execution_authorized").count() == (
        0 if manual else 1
    )
    assert (
        AgentCheckpoint.objects.filter(workflow=workflow, node="review_plan").count()
        == 1
    )
    assert ComputeTask.objects.count() == task_count
    if mode == "chat_update":
        assert len(workflow.plan["stages"]) == 1
        assert (
            workflow.plan["previousAnalysis"]["addedEvidence"][0]["evidence_id"] == "E2"
        )
    if not manual:
        advance_demo(workflow.id)
        assert ComputeTask.objects.count() == task_count + 1
        finish_task(workflow, review=True)
        resume_waiting()
        workflow.refresh_from_db()
        assert workflow.status == "waiting_approval"
        assert workflow.plan["phase"] == "review_results"
        assert not workflow.plan["stages"][0].get("manualApproved")


@pytest.mark.parametrize(
    "revoked", ["authorization", "source_cancel", "conversation", "input"]
)
def test_chat_update_auto_confirmation_rechecks_original_permission(
    completed_ecology, revoked
):
    env = completed_ecology
    workflow = chat_update(env)
    source = AgentRun.objects.get(pk=workflow.plan["chatExecution"]["requestRunId"])
    if revoked == "authorization":
        source.research_intent["_executionAuthorized"] = False
    elif revoked == "source_cancel":
        source.cancel_requested = True
    elif revoked == "conversation":
        source.conversation.archived = True
        source.conversation.save(update_fields=["archived"])
    else:
        source.research_intent["_inputRevisions"]["context"] = "changed"
    source.save()
    assert claim() == workflow.id
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "interrupted" and not workflow.execute_operators
    assert not workflow.steps.filter(kind="chat_execution_authorized").exists()
    assert ComputeTask.objects.count() == 4
