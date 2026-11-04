"""Human review is durable, scoped, and never converted into edit commands."""

# ruff: noqa: F811
import json

import pytest

from apps.agent.demo_workflow import advance_demo, confirm_demo, prepare_demo
from apps.agent.models import AgentWorkflow
from apps.agent.workflow import resume_waiting
from apps.compute.models import ComputeImport, ComputeTask
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo, finish_task, scenario  # noqa: F401

pytestmark = pytest.mark.django_db


def review(env, workflow, **body):
    return env["client"].post(
        f"/api/agent/workflows/{workflow.id}/confirm/",
        data=json.dumps({"planHash": workflow.plan_hash, **body}),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


def awaiting_review(env):
    workflow = scenario(env)
    prepare_demo(workflow, env["owner"], env["policy"])
    confirm_demo(workflow, env["owner"], env["policy"], workflow.plan_hash)
    advance_demo(workflow.id)
    output = finish_task(workflow, review=True)
    resume_waiting()
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval"
    return workflow, output


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_review_feedback_is_persisted_and_does_not_edit_data(demo, decision):
    workflow, output = awaiting_review(demo)
    original_hash = workflow.plan_hash
    original_outputs = workflow.plan["reviewOutputs"]
    before_tasks = ComputeTask.objects.count()
    response = review(
        demo,
        workflow,
        decision=decision,
        feedback="已核对修改位置，需要保留边界核验说明",
    )
    assert response.status_code == 200, response.content
    review_step = next(
        entry
        for entry in response.json()["steps"]
        if entry["kind"] == "review_feedback"
    )
    assert review_step["decision"] is None
    assert review_step["action"]["decision"] == decision
    workflow.refresh_from_db()
    record = workflow.steps.get(kind="review_feedback")
    assert record.action == {
        "decision": decision,
        "feedback": "已核对修改位置，需要保留边界核验说明",
        "planHash": original_hash,
    }
    assert workflow.checkpoints.filter(
        node="human_review_feedback", state=record.action
    ).exists()
    assert ComputeTask.objects.count() == before_tasks
    assert output.task.outputs.filter(pk=output.id).exists()
    assert not ComputeImport.objects.exists()
    if decision == "approve":
        from apps.agent.demo_decisions import decision_payload

        feedback_context = decision_payload(
            workflow,
            {"name": "final_analysis", "identifier": "finish"},
            [],
            workflow.plan["stages"][0]["results"],
        )["humanReviewFeedback"]
        assert feedback_context == [
            {
                "stepSequence": record.sequence,
                "decision": "approve",
                "feedback": record.action["feedback"],
                "stage": "early_ndvi",
                "reviewedOutputs": original_outputs,
            }
        ]
        assert workflow.status == "waiting_compute"
        assert workflow.plan["stages"][0]["manualApproved"] is True
        resume_waiting()
        assert ComputeImport.objects.filter(output=output).count() == 1
    else:
        assert workflow.status == "cancelled" and workflow.cancel_requested
        assert workflow.plan["reviewOutputs"] == original_outputs
        resume_waiting()
        advance_demo(workflow.id)
        assert not ComputeImport.objects.exists()
        assert ComputeTask.objects.count() == before_tasks
        saved = demo["client"].get(
            f"/api/agent/workflows/{workflow.id}/",
            HTTP_X_PROJECT_ID=str(demo["project"].id),
        )
        assert saved.status_code == 200
        assert saved.json()["status"] == "cancelled"
        assert any(
            s["action"].get("feedback") == record.action["feedback"]
            for s in saved.json()["steps"]
        )


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "edit"},
        {"decision": []},
        {"feedback": []},
        {"feedback": "x" * 4001},
    ],
)
def test_invalid_review_is_not_persisted(demo, body):
    workflow, _ = awaiting_review(demo)
    assert review(demo, workflow, **body).status_code == 400
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval"
    assert not workflow.steps.filter(kind="review_feedback").exists()


def test_workflow_json_preserves_model_decision_and_separates_human_review(demo):
    from apps.agent.models import AgentWorkflowStep
    from apps.agent.views import workflow_json

    workflow = scenario(demo)
    judgement = {
        "problem": "核对地图完整性",
        "findings": ["读取到制图范围"],
        "judgement": "继续检查",
        "uncertainties": [],
        "nextAction": "inspect",
        "algorithmReason": "依据实际范围检查",
        "evidenceRefs": [],
        "modelMode": "real",
        "modelName": "configured",
    }
    AgentWorkflowStep.objects.create(
        workflow=workflow,
        sequence=1,
        kind="analysis_decision",
        action={"decision": judgement},
    )
    AgentWorkflowStep.objects.create(
        workflow=workflow,
        sequence=2,
        kind="review_feedback",
        action={"decision": "approve", "feedback": "已核对"},
    )
    steps = workflow_json(workflow)["steps"]
    assert steps[0]["decision"] == judgement
    assert steps[1]["decision"] is None
    assert steps[1]["action"] == {"decision": "approve", "feedback": "已核对"}


def test_next_model_request_receives_actual_user_feedback_as_scoped_review_context(
    demo, settings
):
    from unittest.mock import patch
    from apps.agent.demo_decisions import decide
    from apps.agent.policy import default_policy
    from apps.agent.views import record_workflow_review
    from tests.integration.test_demo_edit_context import model_response

    workflow, _ = awaiting_review(demo)
    record_workflow_review(
        workflow,
        "approve",
        "已核对修改范围；后续报告仍须注明证据不足",
        workflow.plan_hash,
        workflow.plan["reviewOutputs"],
    )
    settings.AGENT_MODELS[0] = {**settings.AGENT_MODELS[0], "model_id": "qwen-fixture"}
    value = model_response("raster-ndvi", [])
    value["decision"]["evidenceRefs"] = [
        {"kind": "resource", "id": str(demo["inputs"]["early_image"])}
    ]
    stage = {
        "name": "early_ndvi",
        "identifier": "raster-ndvi",
        "parameters": {},
        "bindings": {"image": "early_image"},
    }
    with (
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=800),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            return_value=iter([json.dumps(value)]),
        ) as stream,
    ):
        decide(workflow, demo["owner"], default_policy(), stage, [], lambda: None)
    messages = stream.call_args.args[1]
    request = json.loads(messages[1]["content"])
    assert (
        request["humanReviewFeedback"][0]["feedback"]
        == "已核对修改范围；后续报告仍须注明证据不足"
    )
    assert request["humanReviewFeedback"][0]["stage"] == "early_ndvi"
    assert "不是算法参数或编辑命令" in messages[0]["content"]
    assert not stage.get("edits")


def test_stale_or_paused_review_cannot_continue_or_record_feedback(demo):
    workflow, _ = awaiting_review(demo)
    response = review(
        demo, workflow, planHash="stale", decision="approve", feedback="意见"
    )
    assert response.status_code == 409
    AgentWorkflow.objects.filter(pk=workflow.id).update(
        status="paused", pause_requested=True, paused_from="waiting_approval"
    )
    assert review(demo, workflow, decision="reject", feedback="意见").status_code == 409
    assert not workflow.steps.filter(kind="review_feedback").exists()
