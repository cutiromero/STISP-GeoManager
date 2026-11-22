"""Hermes tool bridge for published GeoManager business workflows."""

import hashlib
import json
import logging
from functools import lru_cache

from django.conf import settings

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.business_flows.models import BusinessFlowVersion
from apps.business_flows.runtime import start_flow
from apps.business_flows.scopes import available_flows
from apps.business_flows.tools import (
    bind_geology_catalog_inputs,
    execute_business_flow_tool,
)
from apps.compute.packages import ComputeError
from apps.projects.context import ProjectScope, project_scope
from .capability_catalog import contracts, enabled
from .hermes_gateway import require_tool_key, session_identity
from .models import AgentRun, HermesSession, HermesToolReceipt
from .policy import fresh_user, require_access, visible_models
from .tool_contract_runtime import validate_arguments
from .views import ApiProblem, body

logger = logging.getLogger(__name__)
TOOLS = {"list_business_flows", "prepare_business_flow_inputs", "start_business_flow"}
WEB_ACCESS_CHECK = "check_public_web"


@lru_cache(maxsize=1)
def project_tools():
    inventory = settings.PROGRAM_ROOT / "deploy/hermes/toolsets.json"
    return frozenset(
        json.loads(inventory.read_text(encoding="utf-8"))["stisp_project_data"]
    )


def execution_context(session, user, *, model=""):
    return AgentRun(
        owner=user,
        project_tag_id=session.project_tag_id,
        model=model,
        evidence=[
            item
            for entries in session.tool_receipts.order_by("pk").values_list(
                "evidence", flat=True
            )
            for item in entries
        ],
    )


def reauthorize_transcript(session, user, policy):
    from .tools import check_evidence

    if session.mode != "agent":
        return
    context = execution_context(session, user)
    for name in {item["tool"] for item in context.evidence}:
        if not enabled(name, user, policy, run=context):
            raise PermissionDenied("本会话的工具访问权限已变更，请新建会话后继续")
    check_evidence(context, user, policy)


def record(session, name, fingerprint, turn_id, call_id, pairs):
    evidence = []
    for resource, result in pairs:
        references = {}
        for key, fields in (
            ("items", ("id", "entryId", "revision")),
            ("findings", ("id", "entryId", "revision")),
            ("documents", ("documentId", "documentSha256")),
        ):
            if name in {
                "search_knowledge",
                "read_knowledge_document",
                "check_knowledge_constraints",
            } and isinstance(result.get(key), list):
                references[key] = [
                    {field: value[field] for field in fields if field in value}
                    for value in result[key]
                    if isinstance(value, dict)
                ]
        evidence.append(
            {
                "resourceId": resource.pk if resource is not None else None,
                "tool": name,
                "result": references,
            }
        )
    HermesToolReceipt.objects.create(
        session=session,
        name=name,
        contract_version=contracts()[name]["version"],
        turn_id=turn_id,
        tool_call_id=call_id,
        argument_hash=fingerprint,
        evidence=evidence,
    )


def execute(session, name, arguments, turn_id, call_id=""):
    scope = ProjectScope(
        (session.project_tag_id,), session.project_tag_id, session.owner_id
    )
    with project_scope(scope):
        user = fresh_user(session.owner_id)
        current_policy = require_access(user, "agent")
        if name == WEB_ACCESS_CHECK:
            if (
                session.mode != "agent"
                or not session.internet_enabled
                or not current_policy.get("internetEnabled", False)
            ):
                raise PermissionDenied("请先在科研智能体输入栏开启联网检索")
            return {"allowed": True}
        if session.mode != "agent" or not enabled(name, user, current_policy):
            raise PermissionDenied("当前会话未开放业务流工具")
        fingerprint = validate_arguments(name, arguments)
        models = visible_models(user, "agent", current_policy)
        preferred = current_policy["defaultAgentModel"]
        alias = next(
            (model["alias"] for model in models if model["alias"] == preferred), ""
        )
        if not alias and models:
            alias = models[0]["alias"]
        if not alias:
            raise PermissionDenied("当前账号没有业务流执行模型")
        reauthorize_transcript(session, user, current_policy)
        if name in project_tools():
            from .capability_catalog import search
            from .tools import _execute_authorized

            context = execution_context(session, user, model=alias)
            if name == "search_tools":
                result = search(
                    user,
                    current_policy,
                    context,
                    arguments,
                    allowed=TOOLS | project_tools(),
                )
                pairs = [(None, {})]
            else:
                result, pairs = _execute_authorized(
                    context, name, arguments, user, current_policy, None
                )
            record(session, name, fingerprint, turn_id, call_id, pairs)
            return result
        if name != "start_business_flow":
            context = AgentRun(
                owner=user, project_tag_id=session.project_tag_id, model=alias
            )
            result, _ = execute_business_flow_tool(context, user, name, arguments)
            return result
        version = (
            BusinessFlowVersion.objects.select_related("flow")
            .filter(
                pk=arguments["versionId"],
                status="published",
                flow__is_active=True,
                flow__in=available_flows(session.project_tag_id),
            )
            .first()
        )
        if version is None:
            raise ComputeError("业务流版本不可执行", 404)
        identity = hashlib.sha256(
            f"{session.pk}:{turn_id}:{version.pk}".encode()
        ).hexdigest()
        key = f"hermes-{identity}"
        parameters = dict(arguments.get("parameters", {}))
        bind_geology_catalog_inputs(
            user, version, arguments["inputs"], parameters, key, batch_id=identity[:32]
        )
        workflow = start_flow(
            user,
            version,
            {
                **arguments,
                "parameters": parameters,
                "model": alias,
                "idempotencyKey": key,
            },
        )
        return {
            "workflowId": str(workflow.pk),
            "versionId": version.pk,
            "name": version.flow.name,
            "status": workflow.status,
        }


@csrf_exempt
@require_POST
def tool(request):
    try:
        require_tool_key(request)
        value = body(
            request, {"session_id", "turn_id", "tool_call_id", "name", "arguments"}
        )
        identity = session_identity(value.get("session_id"))
        name, arguments, turn_id = (
            value.get("name"),
            value.get("arguments"),
            value.get("turn_id"),
        )
        if (
            not identity
            or not isinstance(name, str)
            or name not in TOOLS | project_tools() | {WEB_ACCESS_CHECK}
            or not isinstance(arguments, dict)
            or not isinstance(turn_id, str)
            or not 1 <= len(turn_id) <= 200
        ):
            raise ValidationError("Hermes 工具调用身份或参数无效")
        call_id = value.get("tool_call_id", "")
        if not isinstance(call_id, str) or len(call_id) > 200:
            raise ValidationError("Hermes 工具调用编号无效")
        session = HermesSession._base_manager.filter(pk=identity).first()
        if session is None:
            raise PermissionDenied("Hermes 会话不可用")
        return JsonResponse(execute(session, name, arguments, turn_id, call_id))
    except PermissionDenied as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except ComputeError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    except (ApiProblem, ValidationError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            detail = "；".join(exc.messages)
        elif isinstance(exc, ApiProblem):
            detail = exc.detail
        else:
            detail = "Hermes 工具请求格式无效"
        return JsonResponse({"error": detail}, status=400)
    except Exception:
        logger.exception("Hermes business workflow tool failed")
        return JsonResponse({"error": "平台业务流工具处理失败"}, status=500)
