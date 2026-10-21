"""Replacing inputs only invalidates an untouched, matching initial preview."""

# ruff: noqa: F811
from copy import deepcopy
import json

import pytest

from apps.agent.demo_workflow import prepare_demo
from apps.agent.workflow import step
from apps.compute.models import ComputeTask
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo, scenario  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def initial_plan(demo):
    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    assert workflow.status == "waiting_approval"
    assert workflow.plan["phase"] == "review_plan"
    return demo, workflow


def cancel(env, workflow, value):
    return env["client"].post(
        f"/api/agent/workflows/{workflow.id}/cancel/",
        data=json.dumps(value),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


def persisted_state(workflow):
    workflow.refresh_from_db()
    return deepcopy(
        {
            "status": workflow.status,
            "cancel_requested": workflow.cancel_requested,
            "pause_requested": workflow.pause_requested,
            "detail": workflow.detail,
            "plan": workflow.plan,
            "plan_hash": workflow.plan_hash,
            "execute_operators": workflow.execute_operators,
            "operator_steps": workflow.operator_steps,
            "idempotency_key": workflow.idempotency_key,
        }
    )


def test_replace_matching_initial_plan_cancels_without_starting_computation(
    initial_plan,
):
    env, workflow = initial_plan
    before = persisted_state(workflow)
    response = cancel(env, workflow, {"replacePlanHash": workflow.plan_hash})
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "cancelled"
    after = persisted_state(workflow)
    assert after["cancel_requested"] is True
    assert after["pause_requested"] is False
    assert after["detail"] == "初始执行计划已作废，可按新的资料和参数重新生成"
    for key in ("plan", "plan_hash", "execute_operators", "operator_steps"):
        assert after[key] == before[key]
    assert not ComputeTask.objects.exists()
    assert not workflow.steps.filter(compute_task_id__isnull=False).exists()

    # A repeated replacement request cannot cancel a new or advanced plan.
    response = cancel(env, workflow, {"replacePlanHash": workflow.plan_hash})
    assert response.status_code == 409, response.content
    assert persisted_state(workflow) == after


def test_stale_hash_keeps_original_plan_unchanged(initial_plan):
    env, workflow = initial_plan
    before = persisted_state(workflow)
    stale_hash = "a" * 64 if workflow.plan_hash != "a" * 64 else "b" * 64
    response = cancel(env, workflow, {"replacePlanHash": stale_hash})
    assert response.status_code == 409, response.content
    assert "未撤销" in response.json()["detail"]
    assert persisted_state(workflow) == before
    assert not ComputeTask.objects.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"status": status}
        for status in (
            "queued",
            "running",
            "waiting_compute",
            "paused",
            "succeeded",
            "cancelled",
        )
    ]
    + [{"execute_operators": True}, {"operator_steps": 1}],
)
def test_executing_or_noninitial_state_cannot_be_replaced(initial_plan, changes):
    env, workflow = initial_plan
    for key, value in changes.items():
        setattr(workflow, key, value)
    workflow.save(update_fields=list(changes))
    before = persisted_state(workflow)
    response = cancel(env, workflow, {"replacePlanHash": workflow.plan_hash})
    assert response.status_code == 409, response.content
    assert persisted_state(workflow) == before
    assert not ComputeTask.objects.exists()


@pytest.mark.parametrize("phase", ["review_modifications", "review_results"])
def test_later_approval_phase_is_not_an_initial_plan(initial_plan, phase):
    env, workflow = initial_plan
    workflow.plan = {**workflow.plan, "phase": phase}
    workflow.save(update_fields=["plan"])
    before = persisted_state(workflow)
    response = cancel(env, workflow, {"replacePlanHash": workflow.plan_hash})
    assert response.status_code == 409, response.content
    assert persisted_state(workflow) == before


def test_existing_compute_reference_protects_workflow_and_task(initial_plan):
    env, workflow = initial_plan
    task = ComputeTask.objects.create(
        owner=env["owner"],
        version=env["versions"]["raster-ndvi"],
        name="已关联计算",
        status="queued",
        idempotency_key="replace-plan-existing-task",
        request_hash="a" * 64,
    )
    linked_step = step(workflow, "submit_operator", compute_task_id=task.id)
    before = persisted_state(workflow)
    response = cancel(env, workflow, {"replacePlanHash": workflow.plan_hash})
    assert response.status_code == 409, response.content
    assert persisted_state(workflow) == before
    task.refresh_from_db()
    linked_step.refresh_from_db()
    assert task.status == "queued"
    assert linked_step.compute_task_id == task.id
    assert ComputeTask.objects.count() == 1


@pytest.mark.parametrize("value", [None, True, 12, "", "a" * 63, "a" * 65])
def test_invalid_replacement_hash_does_not_cancel(initial_plan, value):
    env, workflow = initial_plan
    before = persisted_state(workflow)
    response = cancel(env, workflow, {"replacePlanHash": value})
    assert response.status_code == 400, response.content
    assert persisted_state(workflow) == before


@pytest.mark.parametrize("status", ["queued", "waiting_approval"])
def test_ordinary_cancellation_still_accepts_no_body(initial_plan, status):
    env, workflow = initial_plan
    workflow.status = status
    workflow.save(update_fields=["status"])
    response = env["client"].generic(
        "POST",
        f"/api/agent/workflows/{workflow.id}/cancel/",
        data=b"",
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )
    assert response.status_code == 200, response.content
    workflow.refresh_from_db()
    assert workflow.status == "cancelled"
    assert workflow.cancel_requested is True
    assert workflow.detail == "已取消后续处理"
    assert not ComputeTask.objects.exists()
