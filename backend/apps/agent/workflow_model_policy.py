"""Apply a verified conversation run's model choices to workflow execution."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied

from apps.projects.context import current_scope

from .budgets import apply_budget
from .config import registry
from .models import AgentRun


REASONING_EFFORTS = {"low", "medium", "xhigh"}


def _model(policy, alias):
    model = registry().get(alias)
    if model is None:
        raise PermissionDenied("科研任务模型已不可用")
    if policy["reasoningEffort"] not in REASONING_EFFORTS:
        raise PermissionDenied("科研任务思考强度无效")
    return model


def run_model_policy(run, user, policy):
    """Use a run with a live authorized policy; no workflow binding is required."""
    conversation = run.conversation
    scope = current_scope.get()
    if (
        run.owner_id != user.id
        or conversation.owner_id != user.id
        or conversation.project_tag_id != run.project_tag_id
        or conversation.mode != "agent"
        or (scope is not None and scope.selected != run.project_tag_id)
    ):
        raise PermissionDenied("科研任务来源不属于当前用户或项目")
    if run.cancel_requested or conversation.archived:
        raise PermissionDenied("科研任务来源已停止或归档")
    model = _model(policy, run.model)
    if run.thinking_mode not in {"fast", "deep"} or (
        run.reasoning_effort and run.reasoning_effort not in REASONING_EFFORTS
    ):
        raise PermissionDenied("科研任务来源的思考选择无效")
    thinking = run.thinking_mode == "deep"
    if thinking and not policy.get("thinkingEnabled", True):
        raise PermissionDenied("逻辑推理已由管理员关闭")
    if thinking and not model.qwen:
        raise PermissionDenied("当前模型已不支持逻辑推理")
    result = dict(policy)
    if run.budget_snapshot:
        # Authorization must not contact the model on every live guard poll.
        # The request tokenizer later checks this ceiling against the actual
        # service window; a changed role or disabled budget fails here first.
        result, _ = apply_budget(
            user,
            result,
            run.budget_snapshot,
            run.budget_snapshot["contextWindowTokens"],
        )
    if run.reasoning_effort:
        result["reasoningEffort"] = run.reasoning_effort
    result["_thinking"] = thinking
    return result


def workflow_model_policy(workflow, user, policy):
    """Resolve trusted run bindings; an invalid source never becomes a default."""
    if workflow.owner_id != user.id:
        raise PermissionDenied("科研任务不属于当前用户")
    execution = workflow.plan.get("chatExecution", {})
    if not isinstance(execution, dict):
        raise PermissionDenied("科研任务来源记录无效")
    keys = [key for key in ("originRunId", "requestRunId") if key in execution]
    if not keys:
        model = _model(policy, workflow.model)
        return {
            **policy,
            "_thinking": bool(policy.get("thinkingEnabled", True) and model.qwen),
        }
    identities = [execution[key] for key in keys]
    if any(type(identity) is not int or identity < 1 for identity in identities):
        raise PermissionDenied("科研任务来源运行编号无效")
    runs = {
        run.id: run
        for run in AgentRun._base_manager.select_related("conversation").filter(
            pk__in=identities,
            owner_id=workflow.owner_id,
            project_tag_id=workflow.project_tag_id,
            research_workflow_id=workflow.id,
        )
    }
    if (
        len(runs) != len(set(identities))
        or len({run.conversation_id for run in runs.values()}) != 1
    ):
        raise PermissionDenied("科研任务来源与用户、项目或工作流绑定不一致")
    # The request run records the user's most recent explicit launch choices.
    source = runs[execution.get("requestRunId", execution.get("originRunId"))]
    if source.model != workflow.model:
        raise PermissionDenied("科研任务模型与来源运行的选择不一致")
    return run_model_policy(source, user, policy)
