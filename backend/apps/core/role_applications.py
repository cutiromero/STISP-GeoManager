from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from apps.core.initialization import (
    ensure_default_user_group,
    ensure_research_user_group,
)
from apps.core.models import RoleApplication


class RoleApplicationReviewError(ValueError):
    pass


def serialize_role_application(
    application: RoleApplication, *, include_user: bool
) -> dict:
    payload = {
        "id": application.id,
        "userId": application.user_id,
        "requestedRole": application.requested_role,
        "status": application.status,
        "reason": application.reason,
        "reviewNote": application.review_note,
        "createdAt": timezone.localtime(application.created_at).isoformat(),
        "reviewedAt": (
            timezone.localtime(application.reviewed_at).isoformat()
            if application.reviewed_at
            else None
        ),
    }
    if include_user:
        payload["user"] = serialize_role_application_user(application.user)
        payload["reviewer"] = (
            serialize_role_application_user(application.reviewer)
            if application.reviewer_id
            else None
        )
    return payload


def serialize_role_application_user(user) -> dict:
    try:
        department = user.profile.department
    except ObjectDoesNotExist:
        department = ""
    return {
        "id": user.id,
        "username": user.get_username(),
        "displayName": user.get_full_name() or user.get_username(),
        "email": user.email,
        "department": department,
    }


def review_role_application(
    application_id: int,
    *,
    reviewer,
    action: str,
    review_note: str,
) -> RoleApplication:
    if action not in {"approve", "reject"}:
        raise RoleApplicationReviewError("action 必须是 approve 或 reject")

    with transaction.atomic():
        application = (
            RoleApplication.objects.select_for_update()
            .select_related("user", "user__profile", "reviewer", "reviewer__profile")
            .get(pk=application_id)
        )
        if application.status != RoleApplication.Status.PENDING:
            raise RoleApplicationReviewError("该角色申请已经审核")
        if application.user_id == reviewer.id:
            raise RoleApplicationReviewError("不能审核自己的角色申请")

        if action == "approve":
            ordinary_group = ensure_default_user_group()
            research_group = ensure_research_user_group()
            application.user.groups.remove(ordinary_group)
            application.user.groups.add(research_group)
            application.status = RoleApplication.Status.APPROVED
        else:
            application.status = RoleApplication.Status.REJECTED

        application.reviewer = reviewer
        application.review_note = review_note
        application.reviewed_at = timezone.now()
        application.save(
            update_fields=[
                "status",
                "reviewer",
                "review_note",
                "reviewed_at",
                "updated_at",
            ]
        )
        return application
