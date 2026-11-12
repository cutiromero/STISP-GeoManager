import uuid
from unittest.mock import Mock, patch

import pytest

from apps.agent.models import AgentRun, Conversation, WorkflowUpload
from apps.agent import generic_chat
from apps.agent.demo_workflow import advance_demo, prepare_demo, _save
from apps.compute.models import ComputeTask
from tests.integration.test_generic_chat import confirmed_catalog_configuration
from tests.integration.test_workflow_input_start import ready_mapping, confirm

pytestmark = pytest.mark.django_db
pytest_plugins = ["tests.integration.test_generic_chat"]


def test_real_model_rechecks_reused_roles_and_publishes_its_reason(
    generic, settings, monkeypatch
):
    original, upload = confirmed_catalog_configuration(generic)
    old = original.research_workflow
    old.status = "cancelled"
    old.save(update_fields=["status"])
    settings.AGENT_MODELS[0]["model_id"] = "qwen-role-review"
    batch = uuid.uuid4().hex
    WorkflowUpload.objects.create(
        owner=generic["owner"],
        source="catalog",
        resource=upload.resource,
        batch_id=batch,
        file_name=upload.file_name,
        profile=upload.profile,
    )
    conversation = Conversation.objects.create(owner=generic["owner"], mode="agent")
    run = AgentRun.objects.create(
        owner=generic["owner"],
        conversation=conversation,
        model="mock",
        prompt="检查所选资料",
        idempotency_key="review-reused-roles",
        research_intent={
            "_uploadBatchId": batch,
            "_reuseConfirmedConfiguration": True,
            "_requestedReuse": True,
            "_combinedInputReview": True,
        },
    )
    thinking = []

    def recognize(*args, **options):
        assert options["previous_roles"] == {"lithology": upload.resource_id}
        options["on_thinking"]("依据矢量面、地层名称和代号字段判断资料角色")
        return {
            "source": "model",
            "items": [
                {
                    "resourceId": upload.resource_id,
                    "role": "lithology",
                    "reason": "矢量面包含地层名称与代号字段",
                }
            ],
        }

    model = Mock(side_effect=recognize)
    monkeypatch.setattr("apps.agent.workflow_roles.recognize_roles", model)
    generic_chat.prepare(
        run,
        generic["owner"],
        generic["policy"],
        lambda: None,
        on_thinking=thinking.append,
    )
    run.refresh_from_db()
    assert model.call_count == 1 and thinking
    assert run.research_workflow_id
    assert run.research_intent["inputSummary"][0]["roleSource"] == "model"
    assert "矢量面" in run.research_intent["inputSummary"][0]["roleReason"]
    assert run.research_workflow.plan["reusedFieldMapping"]


def test_initial_dispatch_uses_one_model_decision_before_any_compute(generic):
    workflow, _ = ready_mapping(generic)
    assert confirm(generic, workflow, executeAfterMapping=True).status_code == 200
    workflow.refresh_from_db()
    prepare_demo(workflow, generic["owner"], generic["policy"])
    workflow.refresh_from_db()
    from apps.catalog.models import DataResource
    from apps.compute.data import candidate

    empty_faults = DataResource.objects.get(pk=workflow.plan["inputs"]["faults"])
    fault_metadata = candidate(empty_faults, semantic_metadata=True)
    assert fault_metadata["bounds"] == []
    assert fault_metadata["fieldTypes"]["line_id"] == "string"
    workflow.plan["modelPlanning"] = True
    _save(workflow)
    from apps.agent.demo_workflow import decide
    from apps.agent.workflow import _authorize

    expected_policy = _authorize(workflow)[1]

    assert not ComputeTask.objects.exists()
    with patch("apps.agent.demo_workflow.decide", wraps=decide) as model:
        advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert model.call_count == 1
    for key in ("reasoningEffort", "maxOutputTokens", "_thinking"):
        assert model.call_args.args[2][key] == expected_policy[key]
    assert workflow.plan["stages"][0]["decision"]["nextAction"] == "geology-multi-check"
    assert ComputeTask.objects.count() == 1


def test_failed_preparation_keeps_verified_rules_and_owned_history_readable(generic):
    from apps.knowledge.trial_rules import authorize_trial_evidence

    workflow, _ = ready_mapping(generic)
    assert confirm(generic, workflow, executeAfterMapping=True).status_code == 200
    workflow.refresh_from_db()
    workflow.max_iterations = 0
    workflow.save(update_fields=["max_iterations"])
    advance_demo(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == "failed"
    assert not ComputeTask.objects.exists()
    assert workflow.plan["trialRuleBindings"] and workflow.evidence
    expected = {row["id"] for row in workflow.plan["trialRuleBindings"]}
    assert (
        authorize_trial_evidence(workflow, generic["owner"], history=True) == expected
    )
    source = AgentRun.objects.filter(research_workflow=workflow).order_by("pk").first()
    response = generic["client"].get(
        f"/api/agent/conversations/{source.conversation_id}/",
        HTTP_X_PROJECT_ID=str(generic["project"].pk),
    )
    assert response.status_code == 200, response.content
