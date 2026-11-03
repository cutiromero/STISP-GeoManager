"""Persistent, opt-in invitations and personal notification inboxes."""

import hashlib
import json
from functools import wraps

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Q
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.audit.service import log_operation
from apps.compute.packages import ComputeError
from apps.compute.serializers import output_data
from apps.core.api import api_login_required
from apps.core.initialization import is_guest_user
from apps.projects.context import is_superadmin, selected_project_id
from apps.projects.models import Project

from .models import ShareInvitation
from .share_access import actor_scope, validate_share


def endpoint(methods):
    def decorator(view):
        @require_http_methods(methods)
        @api_login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_active or is_guest_user(request.user):
                return JsonResponse({"detail": "当前账号不能使用邀请分享"}, status=403)
            try:
                return view(request, *args, **kwargs)
            except ComputeError as exc:
                return JsonResponse({"detail": str(exc)}, status=exc.status)

        return wrapped

    return decorator


def payload(request) -> dict:
    if len(request.body) > 8192:
        raise ComputeError("分享请求过大")
    try:
        value = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ComputeError("请求须为有效JSON") from exc
    if not isinstance(value, dict):
        raise ComputeError("请求须为JSON对象")
    return value


def text(value, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ComputeError(f"{name}须为1至{maximum}字符")
    return value.strip()


def check_request(body: dict):
    kind = body.get("kind")
    object_id = body.get("objectId")
    if (
        kind not in ShareInvitation.Kind.values
        or type(object_id) is not int
        or object_id < 1
    ):
        raise ComputeError("请选择有效的分享类型和单个对象")
    username = text(body.get("username"), "准确用户名", 150)
    recipient = (
        get_user_model().objects.filter(username=username, is_active=True).first()
    )
    if recipient is None:
        raise ComputeError("用户名不存在或账号已停用，请核对完整用户名")
    return kind, object_id, recipient


def person(user) -> dict:
    return {
        "username": user.get_username(),
        "displayName": user.get_full_name() or user.get_username(),
    }


def target(kind: str, object_id: int, name: str, project, invitation_id=None) -> dict:
    url = {
        "workspace": f"/map?sceneId={object_id}&projectTagId={project.id}",
        "composition": f"/map?compositionId={object_id}&projectTagId={project.id}",
        "compute_output": f"/compute?sharedInvitation={invitation_id}"
        if invitation_id
        else "",
    }[kind]
    return {
        "kind": kind,
        "objectId": object_id,
        "name": name,
        "projectTagId": project.id,
        "projectName": project.name,
        "openUrl": url,
    }


def object_name(kind, item) -> str:
    return item.label if kind == "compute_output" else item.name


def serialize(invitation, user) -> dict:
    received = invitation.recipient_id == user.id
    unread = (
        invitation.recipient_read_at is None
        if received
        else invitation.status != "pending" and invitation.sender_read_at is None
    )
    return {
        "id": invitation.id,
        "status": invitation.status,
        "sender": person(invitation.sender),
        "recipient": person(invitation.recipient),
        "target": target(
            invitation.kind,
            invitation.object_id,
            invitation.object_name,
            invitation.project_tag,
            invitation.id,
        ),
        "createdAt": invitation.created_at.isoformat(),
        "respondedAt": invitation.responded_at.isoformat()
        if invitation.responded_at
        else None,
        "unread": unread,
        "detail": invitation.detail,
        "canRespond": received and invitation.status == "pending",
    }


def personal_query(user):
    projects = Project.objects.filter(is_active=True)
    if not is_superadmin(user):
        projects = projects.filter(Q(is_default=True) | Q(memberships__user=user))
    return ShareInvitation._base_manager.filter(
        Q(sender=user) | Q(recipient=user),
        project_tag__in=projects,
    ).select_related("sender", "recipient", "project_tag")


def personal_invitation(user, invitation_id: int):
    item = personal_query(user).filter(pk=invitation_id).first()
    if item is None:
        raise ComputeError("邀请不存在或当前账号无权访问", 404)
    return item


@endpoint(["POST"])
def check(request):
    try:
        kind, identity, recipient = check_request(payload(request))
        project_id = selected_project_id()
        item = validate_share(kind, identity, request.user, recipient, project_id)
    except ComputeError as exc:
        return JsonResponse({"eligible": False, "detail": str(exc)})
    project = Project.objects.get(pk=project_id)
    return JsonResponse(
        {
            "eligible": True,
            "detail": "权限核对通过，可以发出邀请",
            "target": target(kind, identity, object_name(kind, item), project),
            "recipient": person(recipient),
        }
    )


@endpoint(["GET", "POST"])
def invitations(request):
    if request.method == "POST":
        return create(request)
    box = request.GET.get("box", "received")
    try:
        limit, offset = (
            int(request.GET.get("limit", 30)),
            int(request.GET.get("offset", 0)),
        )
        if box not in {"received", "sent"} or not 1 <= limit <= 100 or offset < 0:
            raise ValueError
    except ValueError as exc:
        raise ComputeError("收发箱或分页参数无效") from exc
    query = personal_query(request.user).filter(
        **{"recipient" if box == "received" else "sender": request.user}
    )
    unread = (
        query.filter(recipient_read_at__isnull=True)
        if box == "received"
        else query.exclude(status="pending").filter(sender_read_at__isnull=True)
    )
    return JsonResponse(
        {
            "items": [
                serialize(item, request.user)
                for item in query.annotate(
                    notification_at=Coalesce("responded_at", "created_at")
                ).order_by("-notification_at", "-id")[offset : offset + limit]
            ],
            "total": query.count(),
            "unreadCount": unread.count(),
            "limit": limit,
            "offset": offset,
        }
    )


def create(request):
    body = payload(request)
    key = text(body.get("idempotencyKey"), "幂等键", 80)
    kind, identity, recipient = check_request(body)
    project_id = selected_project_id()
    digest = hashlib.sha256(
        json.dumps([project_id, kind, identity, recipient.id]).encode()
    ).hexdigest()
    with transaction.atomic():
        # An UPDATE reserves SQLite's writer before checking unique live invitations.
        ShareInvitation._base_manager.filter(sender=request.user).update(
            sender_read_at=F("sender_read_at")
        )
        same_key = ShareInvitation._base_manager.filter(
            sender=request.user, request_key=key
        ).first()
        if same_key and same_key.request_hash != digest:
            raise ComputeError("幂等键已用于另一个邀请", 409)
        item = validate_share(kind, identity, request.user, recipient, project_id)
        existing = (
            same_key
            or ShareInvitation._base_manager.filter(
                sender=request.user,
                recipient=recipient,
                project_tag_id=project_id,
                kind=kind,
                object_id=identity,
                status__in=("pending", "accepted"),
            ).first()
        )
        if existing:
            return JsonResponse(serialize(existing, request.user))
        invitation = ShareInvitation.objects.create(
            sender=request.user,
            recipient=recipient,
            kind=kind,
            object_id=identity,
            object_name=object_name(kind, item),
            request_key=key,
            request_hash=digest,
        )
        log_operation(
            request.user,
            "邀请分享",
            "发送邀请",
            "success",
            invitation.object_name,
            request,
            target_type="share_invitation",
            target_id=invitation.id,
        )
    return JsonResponse(serialize(invitation, request.user), status=201)


@endpoint(["POST"])
def respond(request, invitation_id: int):
    body = payload(request)
    decision = body.get("decision")
    key = text(body.get("idempotencyKey"), "幂等键", 80)
    if decision not in {"accept", "reject"}:
        raise ComputeError("请选择接受或拒绝")
    with transaction.atomic():
        ShareInvitation._base_manager.filter(
            pk=invitation_id, recipient=request.user
        ).update(detail=F("detail"))
        invitation = personal_invitation(request.user, invitation_id)
        if invitation.recipient_id != request.user.id:
            raise ComputeError("只有接收人可以回应邀请", 403)
        if invitation.status != "pending":
            if invitation.response_decision == decision:
                return JsonResponse(serialize(invitation, request.user))
            raise ComputeError("邀请已有决定或已失效，请刷新查看", 409)
        invitation.status = "accepted" if decision == "accept" else "rejected"
        invitation.detail = (
            "对方已接受分享邀请" if decision == "accept" else "对方已拒绝分享邀请"
        )
        if decision == "accept":
            try:
                validate_share(
                    invitation.kind,
                    invitation.object_id,
                    invitation.sender,
                    invitation.recipient,
                    invitation.project_tag_id,
                )
            except ComputeError as exc:
                invitation.status, invitation.detail = (
                    "unavailable",
                    "邀请未能接受：" + str(exc),
                )
        invitation.response_key, invitation.response_decision = key, decision
        invitation.responded_at = invitation.recipient_read_at = timezone.now()
        invitation.sender_read_at = None
        with actor_scope(request.user, invitation.project_tag_id):
            invitation.save(
                update_fields=[
                    "status",
                    "detail",
                    "response_key",
                    "response_decision",
                    "responded_at",
                    "recipient_read_at",
                    "sender_read_at",
                ]
            )
            log_operation(
                request.user,
                "邀请分享",
                "回应邀请",
                "success",
                invitation.detail,
                request,
                target_type="share_invitation",
                target_id=invitation.id,
            )
    return JsonResponse(serialize(invitation, request.user))


@endpoint(["POST"])
def read(request, invitation_id: int):
    invitation = personal_invitation(request.user, invitation_id)
    field = (
        "recipient_read_at"
        if invitation.recipient_id == request.user.id
        else "sender_read_at"
    )
    ShareInvitation._base_manager.filter(pk=invitation.id).update(
        **{field: timezone.now()}
    )
    setattr(invitation, field, timezone.now())
    return JsonResponse(serialize(invitation, request.user))


@endpoint(["GET"])
def open_invitation(request, invitation_id: int):
    invitation = personal_invitation(request.user, invitation_id)
    if invitation.status != "accepted":
        raise ComputeError("邀请尚未接受或已失效，不能打开", 409)
    try:
        item = validate_share(
            invitation.kind,
            invitation.object_id,
            invitation.sender,
            invitation.recipient,
            invitation.project_tag_id,
        )
    except ComputeError as exc:
        ShareInvitation._base_manager.filter(
            pk=invitation.id, status="accepted"
        ).update(
            status="unavailable",
            detail="分享已失效：" + str(exc),
            sender_read_at=None,
            recipient_read_at=None,
            responded_at=timezone.now(),
        )
        raise ComputeError("分享已失效：" + str(exc), 403) from exc
    result = {
        "target": target(
            invitation.kind,
            invitation.object_id,
            object_name(invitation.kind, item),
            invitation.project_tag,
            invitation.id,
        )
    }
    if invitation.kind == "compute_output":
        with actor_scope(request.user, invitation.project_tag_id):
            result["output"] = output_data(item)
        result["output"]["metadata"] = {
            key: value
            for key, value in item.metadata.items()
            if key
            in {
                "bounds",
                "crs",
                "width",
                "height",
                "bands",
                "bandCount",
                "dtypes",
                "nodata",
                "fields",
                "columns",
                "featureCount",
                "rowCount",
                "geometryType",
                "statistics",
            }
        }
    return JsonResponse(result)
