"""Account-wide compute slots; parked workflows remain independently actionable."""

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import F

from apps.compute.packages import ComputeError
from .models import AgentRun, AgentWorkflow, WORKFLOW_COMPUTING


def workflow_summary(workflow):
    run = (
        AgentRun._base_manager.filter(research_workflow=workflow, owner=workflow.owner)
        .select_related("conversation")
        .order_by("created_at", "id")
        .first()
    )
    return {
        "id": str(workflow.id),
        "goal": workflow.goal,
        "workflowType": workflow.workflow_type,
        "status": workflow.status,
        "updatedAt": workflow.updated_at.isoformat(),
        "projectId": workflow.project_tag_id,
        "conversationId": run.conversation_id if run else None,
        "conversationTitle": run.conversation.title if run else None,
    }


def require_compute_slot(user, workflow_id=None):
    owners = get_user_model().objects.filter(pk=user.pk)
    if connection.vendor == "sqlite":
        owners.update(last_login=F("last_login"))
    owners.select_for_update().get()
    blocker = (
        AgentWorkflow._base_manager.filter(owner=user, status__in=WORKFLOW_COMPUTING)
        .exclude(pk=workflow_id)
        .first()
    )
    if blocker:
        summary = workflow_summary(blocker)
        conversation = (
            f"对话「{summary['conversationTitle'] or '未命名'}」（{summary['conversationId']}）"
            if summary["conversationId"] is not None
            else "独立任务（未关联对话）"
        )
        raise ComputeError(
            f"任务「{blocker.goal[:100]}」（{blocker.id}）正在计算或排队，"
            f"位于项目{blocker.project_tag_id}的{conversation}。"
            "请在活动任务提示中点“查看”，可结束该任务后重试；当前确认或暂停点保持不变。",
            409,
        )
