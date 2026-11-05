"""Paused workflows keep real computation and explicit approval recoverable."""

# ruff: noqa: F811
from datetime import timedelta
import json
from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.utils import timezone

from apps.agent.demo_workflow import _save, advance_demo, confirm_demo, prepare_demo
from apps.agent.models import AgentCheckpoint, AgentWorkflow
from apps.agent.workflow import resume_waiting, run_workflow
from apps.agent.workflow_controls import save_workflow_state
from apps.agent.workflow_worker import claim, recover
from apps.compute.models import ComputeImport, ComputeTask
from apps.projects.models import ProjectMembership
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import (  # noqa: F401
    demo,
    finish_task,
    mark_imports_ready,
    scenario,
)

pytestmark = pytest.mark.django_db


def control(env, workflow, action):
    return env["client"].post(
        f"/api/agent/workflows/{workflow.id}/{action}/",
        data="{}",
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


def prepared(env, *, execute=True):
    workflow = scenario(env)
    prepare_demo(workflow, env["owner"], env["policy"])
    if execute:
        confirm_demo(workflow, env["owner"], env["policy"], workflow.plan_hash)
    return workflow


def test_pause_queued_is_durable_idempotent_and_releases_slot(demo):
    workflow = prepared(demo)
    response = control(demo, workflow, "pause")
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "paused"
    assert response.json()["pauseRequested"] is True
    assert response.json()["pausedFrom"] == "queued"
    assert control(demo, workflow, "pause").json()["status"] == "paused"
    assert claim() is None
    advance_demo(workflow.id)
    assert not ComputeTask.objects.exists()
    another = AgentWorkflow.objects.create(
        owner=demo["owner"], model="mock", goal="another", idempotency_key="another"
    )
    assert control(demo, workflow, "resume").status_code == 409
    assert control(demo, another, "cancel").json()["status"] == "cancelled"
    assert control(demo, workflow, "resume").json()["status"] == "queued"
    assert control(demo, workflow, "resume").json()["status"] == "queued"


def test_running_pause_survives_inflight_decision_save_and_submits_nothing(demo):
    workflow = prepared(demo)
    assert claim() == workflow.id
    from apps.agent.demo_workflow import decide

    def decision_with_pause(*args, **kwargs):
        decision, edits = decide(*args, **kwargs)
        response = control(demo, workflow, "pause")
        assert response.status_code == 200, response.content
        assert response.json()["pauseRequested"] is True
        # A model-attempt checkpoint is saved while the old worker is still
        # unwinding. Resume becomes available only at its final safe save.
        _save(args[0])
        current = AgentWorkflow.objects.get(pk=workflow.id)
        assert current.status == "running" and current.pause_requested
        assert control(demo, workflow, "resume").status_code == 409
        return decision, edits

    with patch("apps.agent.demo_workflow.decide", side_effect=decision_with_pause):
        advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "paused" and workflow.pause_requested
    assert not ComputeTask.objects.exists()
    assert control(demo, workflow, "resume").status_code == 200
    advance_demo(workflow.id)
    assert ComputeTask.objects.count() == 1


@pytest.mark.parametrize("response_saved", [False, True])
def test_real_model_pause_boundaries_preserve_response_and_never_resend(
    demo, settings, response_saved
):
    from apps.agent.model_guard import ModelStreamGuard
    from tests.integration.test_demo_edit_context import model_response

    poll_time = [0.0]

    def stream_guard(check, deadline):
        return ModelStreamGuard(check, deadline, clock=lambda: poll_time[0])

    workflow = prepared(demo)
    assert claim() == workflow.id
    settings.AGENT_MODELS[0] = {**settings.AGENT_MODELS[0], "model_id": "qwen-fixture"}
    value = model_response("raster-ndvi", [])
    value["decision"]["evidenceRefs"] = [
        {"kind": "resource", "id": str(demo["inputs"]["early_image"])}
    ]

    def stream(model, messages, output, guard, **options):
        if response_saved:
            yield json.dumps(value)
        assert control(demo, workflow, "pause").status_code == 200
        # Simulate the next watchdog poll rather than depending on real sleep.
        poll_time[0] += 0.5
        if not response_saved:
            guard()

    with (
        patch("apps.agent.demo_workflow.ModelStreamGuard", side_effect=stream_guard),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=800),
        patch(
            "apps.agent.demo_decisions.provider.stream", side_effect=stream
        ) as request,
    ):
        advance_demo(workflow.id)
        workflow.refresh_from_db()
        assert workflow.status == "paused"
        attempt = workflow.plan["stages"][0]["modelAttempts"][0]
        assert attempt["status"] == (
            "response_received" if response_saved else "requesting"
        )
        assert bool(attempt.get("response")) is response_saved
        assert not ComputeTask.objects.exists()
        assert control(demo, workflow, "resume").status_code == 200
        advance_demo(workflow.id)
        workflow.refresh_from_db()
        assert request.call_count == 1
        assert workflow.plan["actualModelCallCount"] == 1
        if response_saved:
            assert workflow.status == "waiting_compute"
            assert ComputeTask.objects.count() == 1
            assert (
                workflow.plan["stages"][0]["recoveredResponseState"]
                == "validated_without_new_request"
            )
        else:
            assert workflow.status == "failed"
            assert "完整分析响应未保存" in workflow.detail
            assert not ComputeTask.objects.exists()


@pytest.mark.parametrize("save", [_save, save_workflow_state])
def test_stale_model_state_cannot_overwrite_pause_request(demo, save):
    workflow = prepared(demo)
    stale = AgentWorkflow.objects.get(pk=workflow.id)
    assert control(demo, workflow, "pause").status_code == 200
    stale.plan["savedAnalysis"] = {"message": "实际分析结果"}
    stale.status = "running"
    save(stale)
    workflow.refresh_from_db()
    assert workflow.status == "paused" and workflow.pause_requested
    assert workflow.plan["savedAnalysis"]["message"] == "实际分析结果"


@pytest.mark.parametrize("stale_status", ["running", "waiting_approval", "paused"])
def test_stale_model_save_cannot_replace_paused_approval_gate(demo, stale_status):
    workflow = prepared(demo, execute=False)
    stale = AgentWorkflow.objects.get(pk=workflow.id)
    original_hash = workflow.plan_hash
    assert control(demo, workflow, "pause").status_code == 200
    stale.plan = {**stale.plan, "phase": "decide"}
    stale.status, stale.execute_operators = stale_status, True
    _save(stale)
    workflow.refresh_from_db()
    assert workflow.status == "paused" and workflow.paused_from == "waiting_approval"
    assert workflow.plan_hash == original_hash
    assert workflow.plan["phase"] == "review_plan"
    assert not workflow.execute_operators
    assert control(demo, workflow, "resume").json()["status"] == "waiting_approval"
    run_workflow(workflow.id)
    assert not ComputeTask.objects.exists()


def test_paused_computation_finishes_without_import_or_resubmission(demo):
    workflow = prepared(demo)
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    task_id = workflow.plan["stages"][0]["taskId"]
    assert control(demo, workflow, "pause").json()["pausedFrom"] == "waiting_compute"
    output = finish_task(workflow)
    resume_waiting()
    run_workflow(workflow.id)
    assert not ComputeImport.objects.exists()
    assert ComputeTask.objects.count() == 1
    assert control(demo, workflow, "resume").status_code == 200
    resume_waiting()
    assert ComputeImport.objects.filter(output=output).count() == 1
    mark_imports_ready(demo)
    resume_waiting()
    workflow.refresh_from_db()
    assert workflow.plan["stageIndex"] == 1
    assert workflow.plan["stages"][0]["taskId"] == task_id
    assert ComputeTask.objects.count() == 1


def test_pause_arriving_while_reading_results_blocks_import(demo):
    workflow = prepared(demo)
    advance_demo(workflow.id)
    finish_task(workflow)
    from apps.agent.demo_workflow import read_results

    def result_with_pause(*args, **kwargs):
        results = read_results(*args, **kwargs)
        assert control(demo, workflow, "pause").status_code == 200
        return results

    with patch("apps.agent.demo_workflow.read_results", side_effect=result_with_pause):
        resume_waiting()
    workflow.refresh_from_db()
    assert workflow.status == "paused"
    assert not ComputeImport.objects.exists()
    assert workflow.plan["stages"][0].get("results")
    assert control(demo, workflow, "resume").status_code == 200
    resume_waiting()
    assert ComputeImport.objects.count() == 1
    assert ComputeTask.objects.count() == 1


@pytest.mark.parametrize("approval", ["plan", "quality", "decision"])
def test_resume_keeps_explicit_approval_gate(demo, approval):
    workflow = prepared(demo, execute=approval != "plan")
    if approval == "quality":
        advance_demo(workflow.id)
        finish_task(workflow, review=True)
        resume_waiting()
    elif approval == "decision":
        workflow.plan["phase"] = "review_results"
        workflow.plan["reviewOutputs"] = []
        workflow.plan["stages"][0]["status"] = "needs_review"
        workflow.status = "waiting_approval"
        _save(workflow)
    workflow.refresh_from_db()
    before = ComputeTask.objects.count()
    assert control(demo, workflow, "pause").json()["pausedFrom"] == "waiting_approval"
    assert control(demo, workflow, "resume").json()["status"] == "waiting_approval"
    run_workflow(workflow.id)
    resume_waiting()
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval"
    stage = workflow.plan["stages"][0]
    assert not stage.get("manualApproved") and not stage.get("decisionApproved")
    assert not ComputeImport.objects.exists()
    assert ComputeTask.objects.count() == before


@pytest.mark.parametrize("changed", ["membership", "algorithm", "input"])
def test_resume_rechecks_permission_and_frozen_versions(demo, changed):
    workflow = prepared(demo)
    assert control(demo, workflow, "pause").status_code == 200
    if changed == "membership":
        ProjectMembership.objects.filter(
            user=demo["owner"], project=demo["project"]
        ).delete()
    elif changed == "algorithm":
        version = demo["versions"]["raster-ndvi"]
        version.status = "draft"
        version.save(update_fields=["status"])
    else:
        from apps.catalog.models import DataResource

        DataResource.objects.filter(pk=demo["inputs"]["early_image"]).update(
            updated_at=timezone.now() + timedelta(seconds=1)
        )
    response = control(demo, workflow, "resume")
    assert response.status_code in {403, 404}, response.content
    workflow.refresh_from_db()
    assert workflow.status == "paused" and workflow.pause_requested
    assert not ComputeTask.objects.exists()


def test_cancel_paused_closes_workflow_and_rejects_resume(demo):
    workflow = prepared(demo)
    assert control(demo, workflow, "pause").status_code == 200
    response = control(demo, workflow, "cancel")
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "cancelled"
    assert response.json()["pauseRequested"] is False
    assert control(demo, workflow, "resume").status_code == 409
    assert claim() is None


def test_recovery_acknowledges_pause_instead_of_requeuing(demo):
    workflow = prepared(demo)
    assert claim() == workflow.id
    assert control(demo, workflow, "pause").json()["status"] == "running"
    AgentWorkflow.objects.filter(pk=workflow.id).update(
        heartbeat=timezone.now() - timedelta(seconds=91)
    )
    recover()
    workflow.refresh_from_db()
    assert workflow.status == "paused"
    assert claim() is None
    assert control(demo, workflow, "resume").json()["status"] == "queued"


def test_unpaused_and_finished_controls_conflict(demo):
    workflow = prepared(demo)
    assert control(demo, workflow, "resume").status_code == 409
    AgentWorkflow.objects.filter(pk=workflow.id).update(status="succeeded")
    assert control(demo, workflow, "pause").status_code == 409
    assert control(demo, workflow, "resume").status_code == 409


def generic_workflow(env, *, status="queued"):
    return AgentWorkflow.objects.create(
        owner=env["owner"],
        model="mock",
        goal="表格统计",
        status=status,
        workflow_type="hyperspectral_interpretation",
        resource_ids=[env["resource"].id],
        algorithm_version_id=env["version"].id,
        parameters=env["body"]["parameters"],
        plan={"inputs": env["body"]["inputs"]},
        idempotency_key="generic-pause",
    )


def confirm_generic(env, workflow):
    return env["client"].post(
        f"/api/agent/workflows/{workflow.id}/confirm/",
        data=json.dumps({"planHash": workflow.plan_hash}),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


def test_generic_workflow_uses_same_pause_controls_and_existing_task(demo):
    workflow = generic_workflow(demo)
    run_workflow(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval", workflow.detail
    response = confirm_generic(demo, workflow)
    assert response.status_code == 200, response.content
    run_workflow(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "waiting_compute", workflow.detail
    task_id = workflow.steps.get(kind="submit_operator").compute_task_id
    assert control(demo, workflow, "pause").status_code == 200
    resume_waiting()
    assert ComputeTask.objects.count() == 1
    assert not ComputeImport.objects.exists()
    assert control(demo, workflow, "resume").status_code == 200
    resume_waiting()
    assert workflow.steps.get(kind="submit_operator").compute_task_id == task_id
    assert ComputeTask.objects.count() == 1


@pytest.mark.parametrize("confirm", [False, True])
def test_generic_approval_packet_is_complete_before_resume_and_confirmation(
    demo, confirm
):
    workflow = generic_workflow(demo, status="running")
    from apps.agent.workflow import save_workflow_state as real_save

    def final_save(current, *args, **kwargs):
        assert control(demo, workflow, "pause").json()["pauseRequested"]
        real_save(current, *args, **kwargs)
        visible = AgentWorkflow.objects.get(pk=workflow.id)
        assert visible.status == "paused" and visible.paused_from == "waiting_approval"
        assert visible.steps.filter(kind="discover_inputs").count() == 1
        assert visible.steps.filter(kind="build_plan").count() == 1
        assert (
            AgentCheckpoint.objects.filter(workflow=visible, node="review_plan").count()
            == 1
        )
        assert control(demo, workflow, "resume").json()["status"] == "waiting_approval"
        if confirm:
            response = confirm_generic(demo, visible)
            assert response.status_code == 200, response.content
            assert response.json()["executeOperators"] is True

    with patch("apps.agent.workflow.save_workflow_state", side_effect=final_save):
        run_workflow(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == ("queued" if confirm else "waiting_approval")
    assert workflow.execute_operators is confirm
    assert not workflow.pause_requested
    assert not ComputeTask.objects.exists()


def test_generic_plan_storage_failure_does_not_publish_partial_approval(demo):
    workflow = generic_workflow(demo, status="running")
    initial_plan = dict(workflow.plan)
    with patch(
        "apps.agent.workflow.checkpoint",
        side_effect=OperationalError("database is locked"),
    ):
        with pytest.raises(OperationalError, match="database is locked"):
            run_workflow(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "running"
    assert workflow.plan == initial_plan and not workflow.plan_hash
    assert not workflow.steps.exists()
    assert not AgentCheckpoint.objects.filter(workflow=workflow).exists()
    assert not ComputeTask.objects.exists()
