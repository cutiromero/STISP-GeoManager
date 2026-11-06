"""Input/start approval is bound to actual fields; fixed stages need no model vote."""

import json
from unittest.mock import patch

import pytest

from apps.agent.demo_workflow import advance_demo, prepare_demo
from apps.agent.input_execution import input_execution_authorized
from apps.catalog.models import DataResource
from apps.compute.models import ComputeTask
from apps.compute.packages import ComputeError
from tests.integration.test_generic_chat import answer, intake, seed_rules

pytestmark = pytest.mark.django_db
pytest_plugins = ["tests.integration.test_generic_chat"]


def ready_mapping(env):
    seed_rules(env)
    run, upload = intake(env)
    response = answer(env, run, answer="确认资料角色")
    assert response.status_code == 200
    run.refresh_from_db()
    workflow = run.research_workflow
    prepare_demo(workflow, env["owner"], env["policy"])
    workflow.refresh_from_db()
    return workflow, upload


def confirm(env, workflow, **extra):
    return env["client"].post(
        f"/api/agent/workflows/{workflow.id}/confirm/",
        json.dumps(
            {
                "planHash": workflow.plan_hash,
                "fieldMapping": {"lithology": {"name": "DCMC", "geo_sym": "DH"}},
                **extra,
            }
        ),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


@pytest.mark.parametrize("start", [False, True])
def test_explicit_input_start_removes_only_the_redundant_initial_plan(generic, start):
    workflow, _ = ready_mapping(generic)
    response = confirm(generic, workflow, executeAfterMapping=start)
    assert response.status_code == 200, response.content
    workflow.refresh_from_db()
    prepare_demo(workflow, generic["owner"], generic["policy"])
    workflow.refresh_from_db()
    assert workflow.execute_operators is start
    assert workflow.status == ("queued" if start else "waiting_approval")
    assert workflow.plan["phase"] == ("decide" if start else "review_plan")
    if start:
        with patch(
            "apps.agent.demo_workflow.decide",
            side_effect=AssertionError("fixed stage must not call a model"),
        ):
            advance_demo(workflow.id)
        workflow.refresh_from_db()
        assert workflow.status == "waiting_compute"
        assert workflow.operator_steps == 1 and workflow.iteration == 0
        assert ComputeTask.objects.count() == 1
        assert workflow.steps.filter(kind="automatic_stage").count() == 1
    else:
        assert not ComputeTask.objects.exists()


@pytest.mark.parametrize("change", ["mapping", "revision", "proof"])
def test_input_start_rejects_changes_after_confirmation(generic, change):
    workflow, upload = ready_mapping(generic)
    assert confirm(generic, workflow, executeAfterMapping=True).status_code == 200
    workflow.refresh_from_db()
    if change == "mapping":
        workflow.plan["confirmedMapping"]["lithology"]["name"] = "DH"
    elif change == "revision":
        resource = DataResource.objects.get(pk=upload.resource_id)
        resource.name = "确认后更新的资料"
        resource.save()
    else:
        workflow.steps.filter(kind="field_mapping_confirmed").delete()
    with pytest.raises(ComputeError, match="授权|变化"):
        input_execution_authorized(workflow, generic["owner"], generic["policy"])
    assert not ComputeTask.objects.exists()


@pytest.mark.parametrize("value", ["true", 1, None])
def test_input_start_flag_must_be_boolean(generic, value):
    workflow, _ = ready_mapping(generic)
    response = confirm(generic, workflow, executeAfterMapping=value)
    assert response.status_code == 400
    workflow.refresh_from_db()
    assert workflow.plan["phase"] == "review_mapping"
    assert "inputExecutionAuthorization" not in workflow.plan


def test_model_identified_complete_roles_go_directly_to_input_review(
    generic, monkeypatch
):
    from apps.agent import workflow_roles

    original = workflow_roles.recognize_roles

    def complete(*args, **kwargs):
        result = original(*args, **kwargs)
        return {**result, "source": "model"}

    monkeypatch.setattr(workflow_roles, "recognize_roles", complete)
    run, upload = intake(generic)
    assert run.research_workflow_id
    assert run.research_intent["questions"] == []
    assert run.research_workflow.execute_operators is False
    upload.refresh_from_db()
    assert upload.workflow_id == run.research_workflow_id
    assert not ComputeTask.objects.exists()


def test_input_review_can_reopen_roles_without_reusing_the_cancelled_workflow(generic):
    from apps.agent.models import AgentRun

    workflow, upload = ready_mapping(generic)
    source = AgentRun.objects.filter(research_workflow=workflow).order_by("id").first()
    response = answer(generic, source, answer="修改角色和字段")
    assert response.status_code == 200, response.content
    workflow.refresh_from_db()
    source.refresh_from_db()
    upload.refresh_from_db()
    assert workflow.status == "cancelled"
    assert source.research_workflow_id is None and upload.workflow_id is None
    assert source.research_intent["questions"]
    response = answer(generic, source, answer="确认资料角色")
    assert response.status_code == 200, response.content
    source.refresh_from_db()
    assert source.research_workflow_id != workflow.pk
    assert source.research_intent["inputSummary"][0]["resourceId"] == upload.resource_id
    assert not ComputeTask.objects.exists()


def test_automatic_unchanged_execution_requires_a_complete_empty_check():
    from types import SimpleNamespace
    from apps.agent.demo_workflow import _verified_empty_check

    result = {
        "key": "issues",
        "taskId": "actual-task",
        "scope": "all",
        "rowCount": 0,
        "rows": [],
    }
    workflow = SimpleNamespace(
        plan={
            "stages": [{"name": "check", "taskId": "actual-task", "results": [result]}]
        }
    )
    assert _verified_empty_check(workflow)
    for key, value in [
        ("scope", "representative"),
        ("rowCount", 1),
        ("taskId", "other-task"),
        ("rows", [{}]),
    ]:
        previous = result[key]
        result[key] = value
        assert not _verified_empty_check(workflow)
        result[key] = previous
