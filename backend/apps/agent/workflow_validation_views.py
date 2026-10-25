"""Read-only independent evaluation, with the workflow's current permissions."""

from io import BytesIO

from django.http import FileResponse, JsonResponse

from apps.audit.service import log_operation
from apps.compute.access import require_actor
from apps.compute.packages import ComputeError
from .views import endpoint
from .workflow_report_views import _authorized
from .workflow_validation import PREVIEW_LIMIT, load_validation_file, validation_json


@endpoint(["GET"])
def workflow_validation(request, workflow_id):
    workflow, user, _ = _authorized(request, workflow_id, history=True)
    return JsonResponse(validation_json(workflow, user))


@endpoint(["GET"])
def workflow_validation_preview(request, workflow_id, file_key):
    workflow, _, _ = _authorized(request, workflow_id, history=True)
    item, content = load_validation_file(workflow, file_key)
    if item["contentType"] != "text/markdown":
        raise ComputeError("该评价文件不支持在线预览", 404)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ComputeError("评价文件编码无效", 409) from exc
    return JsonResponse(
        {
            "fileName": item["fileName"],
            "contentType": item["contentType"],
            "content": text[:PREVIEW_LIMIT],
            "truncated": len(text) > PREVIEW_LIMIT,
        }
    )


@endpoint(["GET"])
def workflow_validation_download(request, workflow_id, file_key):
    workflow, user, _ = _authorized(request, workflow_id, history=True)
    require_actor(user, workflow.project_tag_id, "catalog.export_dataresource")
    item, content = load_validation_file(workflow, file_key)
    log_operation(
        user,
        "智能体",
        "下载独立评价",
        "success",
        item["fileName"],
        request,
        event_code="agent.workflow_validation.download",
        target_code=str(workflow.id),
    )
    response = FileResponse(
        BytesIO(content),
        as_attachment=True,
        filename=item["fileName"],
        content_type=item["contentType"] + "; charset=utf-8",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
