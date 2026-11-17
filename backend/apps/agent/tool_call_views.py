from django.http import Http404, JsonResponse

from .models import AgentRun
from .policy import require_access
from .selections import check_history_evidence
from .views import ApiProblem, endpoint


@endpoint(["GET"])
def tool_calls(request, run_id):
    run = (
        AgentRun.objects.select_related("conversation")
        .filter(pk=run_id, owner=request.user)
        .first()
    )
    if run is None:
        raise Http404
    policy = require_access(request.user, "agent")
    check_history_evidence(run, request.user, policy)
    if set(request.GET) - {"offset", "limit"}:
        raise ApiProblem("未声明的查询参数")
    try:
        offset = int(request.GET.get("offset", 0))
        limit = int(request.GET.get("limit", 30))
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError
    except ValueError as error:
        raise ApiProblem("分页参数无效") from error
    query = run.tool_calls.order_by("created_at", "id")
    total = query.count()
    return JsonResponse(
        {
            "runId": run.pk,
            "projectId": run.project_tag_id,
            "total": total,
            "nextOffset": offset + limit if offset + limit < total else None,
            "items": [
                {
                    "id": str(call.pk),
                    "tool": call.tool,
                    "contractVersion": call.contract_version,
                    "effect": call.effect,
                    "status": call.status,
                    "requestHash": call.request_hash,
                    "argumentKeys": call.argument_keys,
                    "resultRefs": call.result_refs,
                    "error": call.error,
                    "createdAt": call.created_at.isoformat(),
                    "updatedAt": call.updated_at.isoformat(),
                }
                for call in query[offset : offset + limit]
            ],
        }
    )
