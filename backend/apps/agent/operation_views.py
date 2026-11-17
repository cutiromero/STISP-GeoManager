"""Authenticated user decision boundary; deliberately absent from the tool registry."""

from functools import wraps

from django.http import Http404, JsonResponse
from apps.compute.packages import ComputeError

from .models import AgentOperation, AgentRun
from .operation_proposals import (
    authorize,
    decide,
    prepare,
    read_operation,
    list_operation,
)
from .tool_contract_runtime import validate_arguments, failure
from .views import ApiProblem, body, endpoint


def checked_operation(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except (ComputeError, ApiProblem) as error:
            if isinstance(error, ApiProblem):
                error = ComputeError(error.detail, error.status)
            return JsonResponse(failure(error), status=error.status)

    return wrapped


@endpoint(["GET", "POST"])
@checked_operation
def operations(request, run_id):
    run = (
        AgentRun.objects.select_related("conversation")
        .filter(pk=run_id, owner=request.user)
        .first()
    )
    if run is None:
        raise Http404
    authorize(run, request.user)
    if request.method == "POST":
        value = body(request, ["kind", "arguments"], max_bytes=16384)
        tools = {
            "import": "preview_data_import",
            "publish": "preview_publication",
            "share": "preview_share",
        }
        if set(value) != {"kind", "arguments"} or value["kind"] not in tools:
            raise ApiProblem("请选择有效的预览类型和参数")
        validate_arguments(tools[value["kind"]], value["arguments"])
        return JsonResponse(
            prepare(run, request.user, value["kind"], value["arguments"])
        )
    if request.GET:
        raise ApiProblem("操作预览列表不接受额外查询参数")
    return JsonResponse(
        {
            "runId": run.pk,
            "projectId": run.project_tag_id,
            "items": [
                list_operation(item, request.user)
                for item in run.operations.order_by("created_at", "id")[:8]
            ],
        }
    )


@endpoint(["GET", "POST"])
@checked_operation
def operation_detail(request, operation_id):
    operation = (
        AgentOperation.objects.select_related("run__conversation")
        .filter(pk=operation_id, run__owner=request.user)
        .first()
    )
    if operation is None:
        raise Http404
    authorize(operation.run, request.user)
    if request.method == "GET":
        if request.GET:
            raise ApiProblem("操作预览不接受额外查询参数")
        return JsonResponse(read_operation(operation, request.user))
    value = body(request, ["decision", "digest"], max_bytes=4096)
    if set(value) != {"decision", "digest"}:
        raise ApiProblem("确认须提供decision和服务端digest，不接受confirmed等额外字段")
    result = decide(operation, request.user, value["decision"], value["digest"])
    return JsonResponse(result, status=202 if result["status"] == "executing" else 200)
