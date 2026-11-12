"""Workflow model choices come from bound runs and current authorization."""

import pytest
from django.core.exceptions import PermissionDenied

from apps.agent.budgets import resolve_budget
from apps.agent.models import AgentPolicy, AgentRun, AgentWorkflow, Conversation
from apps.agent.policy import default_policy, policy
from apps.agent.workflow import _authorize
from apps.agent.workflow_model_policy import run_model_policy
from apps.projects.context import project_scope
from apps.projects.models import Project, ProjectMembership
from tests.integration.test_agent import setup_agent as setup_agent


@pytest.fixture
def linked(setup_agent, settings):
    env = setup_agent
    settings.AGENT_MODELS[0]["qwen"] = True
    with project_scope(env["scope"]):
        workflow = AgentWorkflow.objects.create(
            owner=env["user"],
            workflow_type="geology_generic",
            goal="核查资料关系",
            model="mock",
            idempotency_key="thinking-workflow",
        )
        source = AgentRun.objects.create(
            owner=env["user"],
            conversation=env["conversation"],
            model="mock",
            prompt="核查资料关系",
            thinking_mode="deep",
            reasoning_effort="low",
            research_workflow=workflow,
            idempotency_key="thinking-origin",
            status="succeeded",
        )
        workflow.plan = {"chatExecution": {"originRunId": source.id}}
        workflow.save(update_fields=["plan"])
    return {**env, "workflow": workflow, "source": source}


def authorize(env, *, history=False):
    with project_scope(env["scope"]):
        return _authorize(env["workflow"], history=history)[1]


def save_policy(value):
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": value})


def test_new_policy_defaults_to_standard_effort(linked):
    assert default_policy()["reasoningEffort"] == "medium"
    saved = default_policy()
    saved["reasoningEffort"] = "medium"
    save_policy(saved)
    assert policy()["reasoningEffort"] == "medium"


@pytest.mark.parametrize(
    "mode,effort,thinking,expected",
    [
        ("deep", "low", True, "low"),
        ("deep", "medium", True, "medium"),
        ("deep", "xhigh", True, "xhigh"),
        ("deep", "", True, "medium"),
        ("fast", "", False, "medium"),
        ("fast", "low", False, "low"),
    ],
)
def test_origin_run_thinking_choice_reaches_workflow_policy(
    linked, mode, effort, thinking, expected
):
    AgentRun._base_manager.filter(pk=linked["source"].id).update(
        thinking_mode=mode, reasoning_effort=effort
    )
    result = authorize(linked)
    assert result["_thinking"] is thinking
    assert result["reasoningEffort"] == expected
    assert "_thinking" not in policy()


def test_request_run_is_the_latest_explicit_choice(linked):
    with project_scope(linked["scope"]):
        request = AgentRun.objects.create(
            owner=linked["user"],
            conversation=linked["conversation"],
            model="mock",
            prompt="确认开始",
            thinking_mode="deep",
            reasoning_effort="xhigh",
            research_workflow=linked["workflow"],
            idempotency_key="thinking-request",
        )
    linked["workflow"].plan["chatExecution"]["requestRunId"] = request.id
    assert authorize(linked)["reasoningEffort"] == "xhigh"
    linked["workflow"].plan = {"chatExecution": {"requestRunId": request.id}}
    assert authorize(linked)["reasoningEffort"] == "xhigh"


def test_request_run_may_select_another_model_than_the_origin(linked, settings):
    settings.AGENT_MODELS.append(
        {**settings.AGENT_MODELS[0], "alias": "selected-second"}
    )
    linked["workflow"].model = "selected-second"
    with project_scope(linked["scope"]):
        request = AgentRun.objects.create(
            owner=linked["user"],
            conversation=linked["conversation"],
            model="selected-second",
            prompt="换用该模型确认开始",
            thinking_mode="deep",
            reasoning_effort="xhigh",
            research_workflow=linked["workflow"],
            idempotency_key="thinking-another-model",
        )
    linked["workflow"].plan["chatExecution"]["requestRunId"] = request.id
    assert authorize(linked)["reasoningEffort"] == "xhigh"


@pytest.mark.parametrize(
    "wrong", ["owner", "project", "workflow", "model", "conversation"]
)
def test_forged_source_binding_fails_instead_of_using_defaults(linked, wrong):
    values = {}
    if wrong == "owner":
        values["owner_id"] = linked["other"].id
    elif wrong == "project":
        values["project_tag_id"] = Project.objects.create(
            code="different-source", name="其他项目"
        ).id
    elif wrong == "workflow":
        values["research_workflow_id"] = None
    elif wrong == "model":
        values["model"] = "another-model"
    else:
        with project_scope(linked["scope"]):
            values["conversation_id"] = Conversation.objects.create(
                owner=linked["other"], mode="agent"
            ).id
    AgentRun._base_manager.filter(pk=linked["source"].id).update(**values)
    with pytest.raises(PermissionDenied):
        authorize(linked)


@pytest.mark.parametrize("identity", [True, "1", None, -1, 999999])
def test_invalid_source_id_does_not_fall_back_to_policy(linked, identity):
    linked["workflow"].plan["chatExecution"]["originRunId"] = identity
    with pytest.raises(PermissionDenied):
        authorize(linked)


def test_origin_and_request_must_share_a_conversation_and_binding(linked):
    with project_scope(linked["scope"]):
        conversation = Conversation.objects.create(owner=linked["user"], mode="agent")
        request = AgentRun.objects.create(
            owner=linked["user"],
            conversation=conversation,
            model="mock",
            prompt="开始",
            research_workflow=linked["workflow"],
            idempotency_key="another-conversation",
        )
    linked["workflow"].plan["chatExecution"]["requestRunId"] = request.id
    with pytest.raises(PermissionDenied):
        authorize(linked)


@pytest.mark.parametrize(
    "qwen,enabled,expected",
    [(True, True, True), (True, False, False), (False, True, False)],
)
def test_direct_workflow_uses_current_policy_and_model_capability(
    linked, settings, qwen, enabled, expected
):
    linked["workflow"].plan = {}
    settings.AGENT_MODELS[0]["qwen"] = qwen
    current = default_policy()
    current["thinkingEnabled"] = enabled
    save_policy(current)
    result = authorize(linked)
    assert result["_thinking"] is expected
    assert result["reasoningEffort"] == "medium"


@pytest.mark.parametrize(
    "change",
    ["thinking_disabled", "model_capability", "cancelled", "archived", "membership"],
)
def test_live_execution_revocations_stop_existing_workflows(linked, settings, change):
    assert authorize(linked)["_thinking"]
    if change == "thinking_disabled":
        current = default_policy()
        current["thinkingEnabled"] = False
        save_policy(current)
    elif change == "model_capability":
        settings.AGENT_MODELS[0]["qwen"] = False
    elif change == "cancelled":
        AgentRun._base_manager.filter(pk=linked["source"].id).update(
            cancel_requested=True
        )
    elif change == "archived":
        Conversation._base_manager.filter(pk=linked["conversation"].id).update(
            archived=True
        )
    else:
        ProjectMembership.objects.filter(
            user=linked["user"], project=linked["project"]
        ).delete()
    with pytest.raises(PermissionDenied):
        authorize(linked)


def test_history_remains_readable_when_source_is_archived_or_thinking_disabled(linked):
    current = default_policy()
    current["thinkingEnabled"] = False
    save_policy(current)
    Conversation._base_manager.filter(pk=linked["conversation"].id).update(
        archived=True
    )
    assert "_thinking" not in authorize(linked, history=True)


@pytest.mark.parametrize("effort,expected", [("", "medium"), ("low", "low")])
def test_source_budget_is_rechecked_and_explicit_effort_takes_precedence(
    linked, effort, expected
):
    current = default_policy()
    current["taskBudgetsEnabled"] = True
    save_policy(current)
    snapshot = resolve_budget(linked["user"], current, "normal", output=1024)
    AgentRun._base_manager.filter(pk=linked["source"].id).update(
        budget_snapshot=snapshot, reasoning_effort=effort
    )
    result = authorize(linked)
    assert result["maxOutputTokens"] == 1024
    assert result["maxContextTokens"] == snapshot["contextWindowTokens"] - 1024 - 256
    assert result["maxRunSeconds"] == snapshot["maxRunSeconds"]
    assert result["reasoningEffort"] == expected
    current["budgetLimits"]["standard"]["maxOutputTokens"] = 512
    save_policy(current)
    with pytest.raises(PermissionDenied, match="预算"):
        authorize(linked)


def test_pre_workflow_run_policy_does_not_require_workflow_binding(linked):
    source = linked["source"]
    source.research_workflow = None
    with project_scope(linked["scope"]):
        result = run_model_policy(source, linked["user"], default_policy())
    assert result["_thinking"] is True
    assert result["reasoningEffort"] == "low"
