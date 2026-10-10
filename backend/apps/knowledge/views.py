import json
from functools import wraps

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import OperationalError, transaction
from django.db.models import F
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.core.api import api_login_required
from apps.audit.service import log_operation
from apps.projects.context import selected_project_id
from .models import KnowledgeEntry, KnowledgeRevision
from .services import (
    can_edit,
    check_constraints,
    require_project,
    search_entries,
    serialize,
    validate_entry,
    visible_entries,
)


def errors(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ValidationError as exc:
            return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
        except PermissionDenied as exc:
            return JsonResponse({"detail": str(exc)}, status=403)
        except OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            return JsonResponse(
                {"detail": "另一项知识更新正在写入，请刷新后重试"}, status=409
            )
        except (
            ValueError,
            TypeError,
            UnicodeDecodeError,
            RecursionError,
            OverflowError,
        ):
            return JsonResponse({"detail": "请求格式无效"}, status=400)

    return wrapped


def body(request):
    if len(request.body) > 80000:
        raise ValidationError("请求过大")
    return json.loads(request.body)


@require_http_methods(["GET", "POST"])
@api_login_required
@errors
def entries(request):
    if request.method == "GET":
        limit = int(request.GET.get("limit", 100))
        offset = int(request.GET.get("offset", 0))
        if not 1 <= limit <= 200 or offset < 0:
            raise ValidationError("分页范围无效")
        return JsonResponse(
            search_entries(
                request.user,
                request.GET.get("q", ""),
                limit,
                category=request.GET.get("category", ""),
                offset=offset,
                manage=request.GET.get("manage", "false") == "true",
                domains=[request.GET["domain"]] if "domain" in request.GET else None,
            )
        )
    require_project(request.user)
    if not can_edit(request.user):
        raise PermissionDenied("需要知识维护权限")
    data = validate_entry(body(request))
    with transaction.atomic():
        entry = KnowledgeEntry.objects.create(
            project_tag_id=selected_project_id(), updated_by=request.user, **data
        )
        KnowledgeRevision.objects.create(
            project_tag_id=entry.project_tag_id,
            entry=entry,
            revision=entry.revision,
            snapshot=serialize(entry),
        )
        log_operation(
            request.user,
            "knowledge",
            "create",
            "success",
            request=request,
            target_type="knowledge_entry",
            target_id=entry.id,
            target_name=entry.title,
        )
    return JsonResponse(serialize(entry))


@require_http_methods(["GET", "PATCH"])
@api_login_required
@errors
def detail(request, entry_id):
    entry = visible_entries(request.user, manage=True).filter(pk=entry_id).first()
    if entry is None:
        return JsonResponse({"detail": "知识不存在或无权访问"}, status=404)
    if request.method == "GET":
        return JsonResponse(serialize(entry))
    if not can_edit(request.user) or entry.project_tag_id != selected_project_id():
        raise PermissionDenied("只能维护当前项目知识；公共基础资料请切换到公开项目维护")
    payload = body(request)
    if isinstance(payload, dict):
        payload.setdefault("domain", entry.domain)
    data = validate_entry(payload)
    revision = payload.get("revision")
    if type(revision) is not int or revision != entry.revision:
        return JsonResponse({"detail": "知识已更新，请刷新后再保存"}, status=409)
    with transaction.atomic():
        # SQLite does not implement SELECT FOR UPDATE. An atomic conditional
        # write makes the revision check effective on every supported database.
        changed = KnowledgeEntry.objects.filter(pk=entry_id, revision=revision).update(
            **data,
            revision=F("revision") + 1,
            updated_by=request.user,
            updated_at=timezone.now(),
        )
        if not changed:
            return JsonResponse({"detail": "知识已更新，请刷新后再保存"}, status=409)
        # Preserve original seed/manual content before the first edit as well.
        KnowledgeRevision.objects.get_or_create(
            project_tag_id=entry.project_tag_id,
            entry=entry,
            revision=entry.revision,
            defaults={"snapshot": serialize(entry)},
        )
        current = KnowledgeEntry.objects.get(pk=entry_id)
        KnowledgeRevision.objects.create(
            project_tag_id=current.project_tag_id,
            entry=current,
            revision=current.revision,
            snapshot=serialize(current),
        )
        log_operation(
            request.user,
            "knowledge",
            "update",
            "success",
            request=request,
            target_type="knowledge_entry",
            target_id=current.id,
            target_name=current.title,
        )
    return JsonResponse(serialize(current))


@require_http_methods(["POST"])
@api_login_required
@errors
def check(request):
    data = body(request)
    if not isinstance(data, dict) or set(data) - {"facts", "entryIds"}:
        raise ValidationError("核查输入无效")
    return JsonResponse(
        check_constraints(request.user, data.get("facts"), data.get("entryIds"))
    )
