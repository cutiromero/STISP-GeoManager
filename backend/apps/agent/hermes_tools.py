"""Hermes tool bridge for published GeoManager business workflows."""

import json
import logging
from functools import lru_cache

from django.conf import settings

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import OperationalError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.business_flows.tools import execute_business_flow_tool
from apps.compute.packages import ComputeError
from apps.projects.context import ProjectScope, project_scope
from .capability_catalog import contracts
from . import hermes_research as research
from .hermes_gateway import require_tool_key, session_identity
from .models import AgentRun, HermesSession, HermesToolReceipt
from .policy import fresh_user, require_access
from .tool_contract_runtime import validate_arguments
from .views import ApiProblem, body

logger = logging.getLogger(__name__)
TOOLS = {"list_business_flows", *research.PERMISSIONS}
WEB_ACCESS_CHECK = "check_public_web"


@lru_cache(maxsize=1)
def project_tools():
    inventory = settings.PROGRAM_ROOT / "deploy/hermes/toolsets.json"
    return frozenset(
        json.loads(inventory.read_text(encoding="utf-8"))["stisp_project_data"]
    )


def execution_context(session, user):
    return AgentRun(
        owner=user,
        project_tag_id=session.project_tag_id,
        model=None,
        evidence=[
            item
            for entries in session.tool_receipts.order_by("pk").values_list(
                "evidence", flat=True
            )
            for item in entries
        ],
    )


def authorize_project_evidence(user, policy, identities, context):
    from .resource_discovery import discover_resources

    visible = set(
        discover_resources(user, policy, sorted(identities)).values_list(
            "id", flat=True
        )
    )
    if visible != identities:
        raise PermissionDenied("会话中的资料已失效或无权访问")


def reauthorize_transcript(session, user, policy):
    from .tools import check_evidence

    if session.mode != "agent":
        return
    context = execution_context(session, user)
    for name in {item["tool"] for item in context.evidence}:
        if not research.tool_allowed(name, user, policy, run=context):
            raise PermissionDenied("本会话的工具访问权限已变更，请新建会话后继续")
    check_evidence(
        context, user, policy, authorize_resources=authorize_project_evidence
    )
    for task_id in {
        item["result"]["taskId"]
        for item in context.evidence
        if item["tool"] in research.PERMISSIONS and "taskId" in item["result"]
    }:
        research.session_task(session, user, policy, task_id)


def record(session, name, fingerprint, turn_id, call_id, pairs):
    evidence = []
    for resource, result in pairs:
        references = {}
        if (
            name in research.PERMISSIONS
            and name != "submit_research_compute"
            and "taskId" in result
        ):
            references["taskId"] = result["taskId"]
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
        contract_version=(research.native_contracts().get(name) or contracts()[name])[
            "version"
        ],
        turn_id=turn_id,
        tool_call_id=call_id,
        argument_hash=fingerprint,
        evidence=evidence,
    )


def execute(session, name, arguments, turn_id, call_id="", *, approval_digest=None):
    scope = ProjectScope(
        (session.project_tag_id,), session.project_tag_id, session.owner_id
    )
    with project_scope(scope):
        user = fresh_user(session.owner_id)
        current_policy = require_access(user, session.mode)
        if name == WEB_ACCESS_CHECK:
            if not session.internet_enabled or not current_policy.get(
                "internetEnabled", False
            ):
                raise PermissionDenied("请在会话输入栏开启联网检索")
            return {"allowed": True}
        if session.mode != "agent" or not research.tool_allowed(
            name, user, current_policy
        ):
            raise PermissionDenied("请使用已获授权的科研智能体工具")
        native = research.native_contracts().get(name)
        fingerprint = validate_arguments(
            name, arguments, schema=native["inputSchema"] if native else None
        )
        reauthorize_transcript(session, user, current_policy)
        if name == "get_research_workflow":
            return research.workflow_plan(
                arguments.get("versionId"), arguments.get("name")
            )
        if name == "list_business_flows":
            context = AgentRun(
                owner=user, project_tag_id=session.project_tag_id, model=None
            )
            result, _ = execute_business_flow_tool(context, user, name, arguments)
            return result
        if native:
            result = research.compute_tool(
                session,
                user,
                current_policy,
                name,
                arguments,
                turn_id=turn_id,
                fingerprint=fingerprint,
                approval_digest=approval_digest,
            )
            record(session, name, fingerprint, turn_id, call_id, [(None, result)])
            return result
        from .tools import _execute_authorized

        context = execution_context(session, user)
        result, pairs = _execute_authorized(
            context,
            name,
            arguments,
            user,
            current_policy,
            None,
            workflow_catalog=True,
            apply_resource_budget=False,
        )
        record(session, name, fingerprint, turn_id, call_id, pairs)
        return result


@csrf_exempt
@require_POST
def tool(request):
    try:
        require_tool_key(request)
        value = body(
            request,
            {
                "session_id",
                "turn_id",
                "tool_call_id",
                "name",
                "arguments",
                "approval_digest",
            },
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
        return JsonResponse(
            execute(
                session,
                name,
                arguments,
                turn_id,
                call_id,
                approval_digest=value.get("approval_digest"),
            )
        )
    except PermissionDenied as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except ComputeError as exc:
        return JsonResponse(
            {"error": str(exc), **({"inputGaps": exc.gaps} if exc.gaps else {})},
            status=exc.status,
        )
    except (ApiProblem, ValidationError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            detail = "；".join(exc.messages)
        elif isinstance(exc, ApiProblem):
            detail = exc.detail
        else:
            detail = "Hermes 工具请求格式无效"
        return JsonResponse({"error": detail}, status=400)
    except OperationalError as exc:
        if any(reason in str(exc).casefold() for reason in ("locked", "busy")):
            return JsonResponse(
                {"error": "平台工具服务繁忙", "retryable": True}, status=503
            )
        logger.exception("Hermes platform tool storage failed")
        return JsonResponse({"error": "平台工具暂不可用"}, status=500)
    except Exception:
        logger.exception("Hermes platform tool failed")
        return JsonResponse({"error": "平台工具暂不可用"}, status=500)
