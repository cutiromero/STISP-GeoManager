"""Small JSON boundaries; execution uses the shared workflow runtime."""

import json
from types import SimpleNamespace
from functools import wraps

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404

from apps.core.api import api_login_required
from apps.compute.packages import ComputeError
from apps.projects.context import (
    is_superadmin,
    require_live_membership,
)
from . import catalog
from .models import BusinessFlowDefinition

# Configuration: requests and list pages are bounded metadata, not source files.
MAX_REQUEST_BYTES = 256 * 1024
PAGE_LIMIT = 50
MAX_LIST_OFFSET = 1_000_000


def endpoint(methods):
    def decorate(function):
        @api_login_required
        @wraps(function)
        def call(request, *args, **kwargs):
            try:
                if request.method not in methods:
                    return JsonResponse({"detail": "请求方法无效"}, status=405)
                if not request.headers.get("X-Project-Id"):
                    raise ValidationError("请显式选择当前项目")
                require_live_membership()
                return function(request, *args, **kwargs)
            except PermissionDenied as error:
                return JsonResponse({"detail": str(error)}, status=403)
            except (Http404, ObjectDoesNotExist):
                return JsonResponse({"detail": "业务流不存在或无权访问"}, status=404)
            except ValidationError as error:
                return JsonResponse({"detail": "；".join(error.messages)}, status=400)
            except ComputeError as error:
                return JsonResponse({"detail": str(error)}, status=error.status)
            except IntegrityError:
                return JsonResponse(
                    {"detail": "编码、版本或幂等键发生冲突，请刷新后重试"}, status=409
                )
            except OperationalError:
                return JsonResponse(
                    {"detail": "业务流正在更新，请稍后重试"}, status=503
                )

        return call

    return decorate


def body(request, allowed):
    if len(request.body) > MAX_REQUEST_BYTES:
        raise ValidationError("业务流请求超过256KiB限制")
    try:
        value = json.loads(request.body)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValidationError("请求不是有效JSON") from error
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValidationError("请求必须是对象且不能包含未定义字段")
    return value


def detail_value(flow, user):
    versions = list(flow.versions.order_by("-version")[:50])
    current = next(
        (item for item in versions if item.pk == flow.current_version_id), None
    )
    return {
        "flow": catalog.serialize_flow(flow),
        "version": catalog.serialize_version(current) if current else None,
        "versions": [catalog.serialize_version(item) for item in versions],
        "canManage": is_superadmin(user),
    }


@endpoint(["GET", "POST"])
def flows(request):
    if request.method == "POST":
        value = body(request, {"code", "name", "description", "isActive", "definition"})
        flow, _ = catalog.register_flow(request.user, value)
        return JsonResponse(detail_value(flow, request.user), status=201)
    try:
        offset = int(request.GET.get("offset", "0"))
        limit = int(request.GET.get("limit", str(PAGE_LIMIT)))
    except (TypeError, ValueError) as error:
        raise ValidationError("目录分页参数必须为整数") from error
    if not 0 <= offset <= MAX_LIST_OFFSET or not 1 <= limit <= PAGE_LIMIT:
        raise ValidationError("目录offset须为0至1000000，limit须为1至50")
    can_manage = is_superadmin(request.user)
    query = BusinessFlowDefinition.objects.select_related("current_version")
    if not can_manage:
        query = query.filter(is_active=True)
    text = request.GET.get("q", "")[:120].strip()
    if text:
        from django.db.models import Q

        query = query.filter(
            Q(name__icontains=text)
            | Q(description__icontains=text)
            | Q(code__icontains=text)
        )
    page = list(query.order_by("name", "id")[offset : offset + limit + 1])
    result = {
        "items": [catalog.serialize_summary(item) for item in page[:limit]],
        "canManage": can_manage,
    }
    if len(page) > limit:
        result["nextOffset"] = offset + limit
    return JsonResponse(result)


@endpoint(["GET", "PATCH"])
def flow_detail(request, flow_id):
    flow = get_object_or_404(
        BusinessFlowDefinition.objects.select_related("current_version"), pk=flow_id
    )
    if request.method == "PATCH":
        flow = catalog.update_flow(
            request.user,
            flow,
            body(request, {"name", "description", "isActive", "updatedAt"}),
        )
    return JsonResponse(detail_value(flow, request.user))


@endpoint(["POST"])
def versions(request, flow_id):
    flow = get_object_or_404(BusinessFlowDefinition.objects, pk=flow_id)
    value = body(request, {"definition", "updatedAt"})
    if "updatedAt" not in value:
        raise ValidationError("发布版本需要最后读取的updatedAt")
    flow, _ = catalog.publish_version(
        request.user, flow, value.get("definition"), expected=value["updatedAt"]
    )
    return JsonResponse(detail_value(flow, request.user), status=201)


@endpoint(["POST"])
def start(request, flow_id):
    from .runtime import start_flow, serialize_run

    flow = get_object_or_404(
        BusinessFlowDefinition.objects.select_related("current_version"), pk=flow_id
    )
    if not flow.is_active:
        raise ComputeError("此业务流已停用", 409)
    value = body(
        request,
        {
            "versionId",
            "model",
            "reviewerModel",
            "goal",
            "inputs",
            "parameters",
            "conversationId",
            "idempotencyKey",
            "inputAdapters",
            "agentEnabled",
            "reasoningEffort",
        },
    )
    for name in ("model", "reviewerModel"):
        if name in value and (
            not isinstance(value[name], str) or not 1 <= len(value[name]) <= 80
        ):
            raise ValidationError("执行与审核模型必须是已登记模型别名")
    if "goal" in value and (
        not isinstance(value["goal"], str)
        or not 1 <= len(value["goal"].strip()) <= 12000
    ):
        raise ValidationError("科研目标格式或长度无效")
    if "conversationId" in value and (
        type(value["conversationId"]) is not int or value["conversationId"] < 1
    ):
        raise ValidationError("会话编号无效")
    version_id = value.get("versionId", flow.current_version_id)
    if type(version_id) is not int:
        raise ValidationError("业务流版本编号无效")
    version = get_object_or_404(flow.versions, pk=version_id, status="published")
    workflow = start_flow(request.user, version, value)
    return JsonResponse(serialize_run(request.user, workflow), status=202)


@endpoint(["POST"])
def prepare_inputs(request, flow_id):
    from .runtime import _inputs
    from apps.agent.policy import require_access

    policy = require_access(request.user, "agent")
    flow = get_object_or_404(BusinessFlowDefinition.objects, pk=flow_id, is_active=True)
    value = body(request, {"versionId", "inputs", "inputAdapters", "uploadBatchId"})
    if type(value.get("versionId")) is not int:
        raise ValidationError("请选择真实发布版本")
    version = get_object_or_404(
        flow.versions, pk=value["versionId"], status="published"
    )
    _, _, planned = _inputs(
        request.user, version.definition, value, policy, preview=True
    )
    return JsonResponse(planned)


def own_workflow(user, workflow_id, *, allow_cancel=False):
    from apps.agent.models import AgentWorkflow
    from apps.agent.policy import require_access

    if not allow_cancel:
        require_access(user, "agent")
    workflow = get_object_or_404(AgentWorkflow.objects, pk=workflow_id, owner=user)
    if not isinstance(workflow.parameters.get("_businessFlow"), dict):
        raise Http404
    return workflow


@endpoint(["GET"])
def input_script(request, workflow_id):
    from .script_api import detail

    attempt = request.GET.get("attempt")
    if attempt is not None:
        try:
            attempt = int(attempt)
        except (TypeError, ValueError) as error:
            raise ValidationError("脚本尝试序号须为整数") from error
    value = detail(
        request.user,
        own_workflow(request.user, workflow_id),
        request.GET.get("role"),
        attempt,
    )
    return JsonResponse(value)


@endpoint(["POST"])
def input_clarification(request, workflow_id):
    from .script_api import clarify
    from .runtime import serialize_run

    workflow = clarify(
        request.user,
        own_workflow(request.user, workflow_id),
        body(request, {"role", "feedback", "revision", "idempotencyKey"}),
    )
    return JsonResponse(serialize_run(request.user, workflow))


@endpoint(["GET"])
def runs(request):
    from apps.agent.models import AgentWorkflow
    from apps.agent.policy import require_access

    require_access(request.user, "agent")
    from django.db.models import F
    from .runtime import canonical_current_node

    rows = (
        AgentWorkflow.objects.filter(
            owner=request.user, parameters___businessFlow__isnull=False
        )
        .annotate(
            flow_id=F("parameters___businessFlow__flowId"),
            version_id=F("parameters___businessFlow__versionId"),
            flow_name=F("parameters___businessFlow__name"),
            conversation_id=F("parameters___businessFlow__conversationId"),
            run_id=F("parameters___businessFlow__runId"),
            flow_revision=F("parameters___businessFlow__revision"),
        )
        .values(
            "id",
            "project_tag_id",
            "workflow_type",
            "goal",
            "status",
            "current_step",
            "created_at",
            "updated_at",
            "flow_id",
            "version_id",
            "flow_name",
            "conversation_id",
            "run_id",
            "flow_revision",
        )
        .order_by("-created_at")[:30]
    )
    items = []
    for item in rows:
        if any(
            type(item[name]) is not int or item[name] < 1
            for name in ("flow_id", "version_id")
        ):
            continue
        items.append(
            {
                "id": str(item["id"]),
                "projectId": item["project_tag_id"],
                "flowId": item["flow_id"],
                "versionId": item["version_id"],
                "name": item["flow_name"]
                if isinstance(item["flow_name"], str)
                else "业务流",
                "goal": item["goal"],
                "status": item["status"],
                "currentNode": canonical_current_node(
                    SimpleNamespace(
                        workflow_type=item["workflow_type"],
                        current_step=item["current_step"],
                    )
                ),
                "conversationId": item["conversation_id"],
                "runId": item["run_id"],
                "revision": item["flow_revision"]
                if type(item["flow_revision"]) is int
                else 0,
                "createdAt": item["created_at"].isoformat(),
                "updatedAt": item["updated_at"].isoformat(),
            }
        )
    return JsonResponse({"items": items})


@endpoint(["GET"])
def run_detail(request, workflow_id):
    from .runtime import serialize_run

    return JsonResponse(
        serialize_run(request.user, own_workflow(request.user, workflow_id))
    )


@endpoint(["POST"])
def decide(request, workflow_id):
    from .runtime import decide_flow, serialize_run

    value = body(
        request,
        {
            "nodeId",
            "revision",
            "decision",
            "feedback",
            "idempotencyKey",
            "skipEvidenceIds",
            "contextScope",
            "recoveryInputs",
            "recoveryParameters",
        },
    )
    if (
        not isinstance(value.get("nodeId"), str)
        or not 1 <= len(value["nodeId"]) <= 64
        or type(value.get("revision")) is not int
        or value["revision"] < 0
        or not isinstance(value.get("decision"), str)
        or value["decision"]
        not in {
            "approve",
            "request_changes",
            "retry_context",
            "retry_recovery",
            "skip_node",
        }
        or not isinstance(value.get("feedback", ""), str)
        or len(value.get("feedback", "")) > 4000
        or not isinstance(value.get("idempotencyKey"), str)
        or not 8 <= len(value["idempotencyKey"]) <= 80
    ):
        raise ValidationError("人工决定、节点修订或反馈格式无效")
    workflow = decide_flow(request.user, own_workflow(request.user, workflow_id), value)
    return JsonResponse(serialize_run(request.user, workflow))


@endpoint(["POST"])
def control(request, workflow_id, action):
    from .runtime import control_flow, serialize_run

    body(request, set()) if request.body else None
    workflow = control_flow(
        request.user,
        own_workflow(request.user, workflow_id, allow_cancel=action == "cancel"),
        action,
    )
    return JsonResponse(
        serialize_run(request.user, workflow, control_only=action == "cancel")
    )
