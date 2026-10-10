from functools import wraps

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from apps.audit.service import log_operation
from apps.core.api import api_login_required
from . import library
from .views import body, errors
from .weknora_client import WeKnoraError


def service_errors(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except WeKnoraError as exc:
            return JsonResponse({"detail": str(exc)}, status=exc.status)

    return wrapped


@require_http_methods(["GET", "POST"])
@api_login_required
@errors
@service_errors
def documents(request):
    if request.method == "GET":
        return JsonResponse(
            library.list_documents(request.user, domains=_domains(request))
        )
    if not {"title", "visibility"}.issubset(request.POST):
        raise ValidationError("请明确填写标题和资料可见范围")
    if set(request.POST) - {"title", "sourceUrl", "visibility", "domain"} or set(
        request.FILES
    ) != {"file"}:
        raise ValidationError("上传字段无效，请选择一份资料")
    doc = library.upload_document(
        request.user,
        request.FILES["file"],
        title=request.POST.get("title", ""),
        source_url=request.POST.get("sourceUrl", ""),
        visibility=request.POST.get("visibility", "project"),
        domain=request.POST.get("domain", "geology"),
    )
    log_operation(
        request.user,
        "knowledge",
        "upload",
        "success",
        request=request,
        target_type="knowledge_document",
        target_id=doc.id,
        target_name=doc.title,
    )
    return JsonResponse(library.serialize_document(request.user, doc))


@require_http_methods(["POST"])
@api_login_required
@errors
@service_errors
def retry(request, document_id):
    doc = library.retry_document(request.user, document_id)
    log_operation(
        request.user,
        "knowledge",
        "retry",
        "success",
        request=request,
        target_type="knowledge_document",
        target_id=doc.id,
        target_name=doc.title,
    )
    return JsonResponse(library.serialize_document(request.user, doc))


@require_http_methods(["PATCH"])
@api_login_required
@errors
@service_errors
def classify(request, document_id):
    data = body(request)
    if not isinstance(data, dict) or set(data) != {"domain"}:
        raise ValidationError("请提供资料所属知识分区")
    doc = library.classify_document(request.user, document_id, data["domain"])
    log_operation(
        request.user,
        "knowledge",
        "classify",
        "success",
        request=request,
        target_type="knowledge_document",
        target_id=doc.id,
        target_name=doc.title,
    )
    return JsonResponse(library.serialize_document(request.user, doc))


@require_http_methods(["POST"])
@api_login_required
@errors
@service_errors
def search(request):
    data = body(request)
    if not isinstance(data, dict) or set(data) - {"query", "limit", "domains"}:
        raise ValidationError("检索输入无效")
    return JsonResponse(
        library.search_documents(
            request.user,
            data.get("query"),
            data.get("limit", 6),
            domains=data.get("domains"),
        )
    )


@require_http_methods(["GET"])
@api_login_required
@errors
@service_errors
def wiki(request):
    return JsonResponse(library.list_wiki(request.user, domains=_domains(request)))


def _domains(request):
    return [request.GET["domain"]] if "domain" in request.GET else None
