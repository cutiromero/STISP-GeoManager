"""Owner/project-authorized report generation, preview, export and registration."""

from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404

from apps.audit.service import log_operation
from apps.compute.access import require_actor
from apps.compute.packages import ComputeError
from .models import AgentWorkflow
from .views import body, endpoint
from .workflow import _authorize
from .workflow_reports import (
    CONTENT_TYPE,
    PREVIEW_LIMIT,
    authorize_context,
    generate_report,
    import_report,
    load_report,
    report_json,
)


def _authorized(request, workflow_id):
    workflow = get_object_or_404(
        AgentWorkflow.objects.select_related("project_tag"),
        pk=workflow_id,
        owner=request.user,
    )
    user, policy = _authorize(workflow)
    authorize_context(workflow, user, policy)
    return workflow, user, policy


def _empty_body(request):
    if request.body:
        body(request, [])


@endpoint(["POST"])
def workflow_report(request, workflow_id):
    _empty_body(request)
    workflow, user, policy = _authorized(request, workflow_id)
    data = generate_report(workflow, user, policy, request)
    return JsonResponse(report_json(workflow, user, data))


@endpoint(["GET"])
def workflow_report_preview(request, workflow_id):
    workflow, user, _ = _authorized(request, workflow_id)
    data, path = load_report(workflow, user)
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ComputeError("报告文件编码无效", 409) from exc
    return JsonResponse(
        {
            "fileName": data["fileName"],
            "contentType": CONTENT_TYPE,
            "content": content[:PREVIEW_LIMIT],
            "truncated": len(content) > PREVIEW_LIMIT,
        }
    )


@endpoint(["GET"])
def workflow_report_download(request, workflow_id):
    workflow, user, _ = _authorized(request, workflow_id)
    require_actor(user, workflow.project_tag_id, "catalog.export_dataresource")
    data, path = load_report(workflow, user)
    log_operation(
        user,
        "智能体",
        "下载分析报告",
        "success",
        data["label"],
        request,
        event_code="agent.workflow_report.download",
        target_code=str(workflow.id),
    )
    response = FileResponse(
        path.open("rb"),
        as_attachment=True,
        filename=data["fileName"],
        content_type=CONTENT_TYPE + "; charset=utf-8",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@endpoint(["POST"])
def workflow_report_import(request, workflow_id):
    _empty_body(request)
    workflow, user, policy = _authorized(request, workflow_id)
    data = import_report(workflow, user, policy, request)
    return JsonResponse(report_json(workflow, user, data))
