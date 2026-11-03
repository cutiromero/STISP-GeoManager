"""Small, owner-scoped workflow index; full evidence is checked on detail reads."""

import re

from django.core.exceptions import ValidationError

from .models import AgentWorkflow


def summary_list(user, params):
    scenario = params.get("workflowType", "")
    if scenario and not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", scenario):
        raise ValidationError("研究场景格式无效")
    try:
        offset = int(params.get("offset", "0"))
        limit = int(params.get("limit", "20"))
    except (TypeError, ValueError) as error:
        raise ValidationError("历史分页参数无效") from error
    if offset < 0 or not 1 <= limit <= 100:
        raise ValidationError("历史分页范围无效")
    query = AgentWorkflow.objects.filter(owner=user)
    if scenario:
        query = query.filter(workflow_type=scenario)
    total = query.count()
    # Never read the potentially large plan/evidence or query steps for an index.
    rows = query.order_by("-created_at", "-id").values(
        "id",
        "project_tag_id",
        "workflow_type",
        "goal",
        "status",
        "detail",
        "current_step",
        "created_at",
        "updated_at",
    )[offset : offset + limit]
    items = [
        {
            "id": str(row["id"]),
            "projectId": row["project_tag_id"],
            "workflowType": row["workflow_type"],
            "goal": row["goal"][:300],
            "status": row["status"],
            "detail": row["detail"],
            "currentStep": row["current_step"],
            "createdAt": row["created_at"].isoformat(),
            "updatedAt": row["updated_at"].isoformat(),
        }
        for row in rows
    ]
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "hasMore": offset + len(items) < total,
    }
