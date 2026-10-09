import json
from functools import wraps

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.audit.service import log_operation
from apps.core.api import api_login_required
from apps.core.initialization import GUEST_GROUP_NAME
from apps.projects.context import is_superadmin
from apps.compute.services import ComputeError
from .config import registry
from .models import (
    AgentPolicy,
    AgentRuntime,
    AgentWorkflow,
    AgentAttachment,
    Conversation,
    AgentRun,
    ACTIVE,
    WORKFLOW_ACTIVE,
)
from .policy import (
    allowed,
    policy,
    require_access,
    visible_models,
    worker_online,
    validate_policy,
    daily_quota,
)
from .tools import check_evidence, resources, resolve_resource, brief
from .attachments import delete_attachment, serialize_attachment, store_attachment
from .budgets import budget_options, resolve_budget


class ApiProblem(Exception):
    def __init__(self, detail, status=400):
        self.detail, self.status = detail, status


def endpoint(methods):
    def decorate(func):
        @api_login_required
        @wraps(func)
        def wrapped(request, *args, **kwargs):
            try:
                if request.method not in methods:
                    return JsonResponse({"detail": "不支持的请求方法"}, status=405)
                if not request.headers.get("X-Project-Id"):
                    raise ApiProblem("请显式选择当前项目")
                return func(request, *args, **kwargs)
            except ApiProblem as e:
                return JsonResponse({"detail": e.detail}, status=e.status)
            except ComputeError as e:
                return JsonResponse({"detail": str(e)}, status=e.status)
            except PermissionDenied as e:
                return JsonResponse({"detail": str(e)}, status=403)
            except Http404:
                return JsonResponse({"detail": "对象不存在或无权访问"}, status=404)
            except (ValidationError, ValueError, TypeError, KeyError) as e:
                detail = (
                    "；".join(e.messages)
                    if isinstance(e, ValidationError)
                    else "请求参数无效"
                )
                return JsonResponse({"detail": detail}, status=400)
            except IntegrityError:
                return JsonResponse({"detail": "已有活动运行，请稍后重试"}, status=409)
            except OperationalError:
                return JsonResponse({"detail": "服务正忙，请稍后重试"}, status=503)

        return wrapped

    return decorate


def body(request, keys, max_bytes=256000):
    if len(request.body) > max_bytes:
        raise ApiProblem("请求过大")
    value = json.loads(request.body)
    if not isinstance(value, dict) or set(value) - set(keys):
        raise ApiProblem("请求字段无效")
    return value


def conversation_json(c):
    return {
        "id": c.id,
        "projectId": c.project_tag_id,
        "mode": c.mode,
        "title": c.title,
        "archived": c.archived,
        "createdAt": c.created_at.isoformat(),
        "updatedAt": c.updated_at.isoformat(),
    }


def run_json(r, user):
    p = require_access(user, r.conversation.mode)
    if r.conversation.mode == "agent":
        check_evidence(r, user, p)
    return {
        "id": r.id,
        "conversationId": r.conversation_id,
        "model": r.model,
        "thinkingMode": r.thinking_mode,
        "budgetProfile": r.budget_snapshot.get("budgetProfile", ""),
        "generationParameters": _run_parameters(r),
        "status": r.status,
        "prompt": r.prompt,
        "answer": r.answer,
        "detail": r.detail,
        "evidence": r.evidence,
        "computeIntent": _compute_intent(r, user, p),
        "createdAt": r.created_at.isoformat(),
        "updatedAt": r.updated_at.isoformat(),
        "contextTruncated": r.context_truncated,
        "attachmentIds": list(r.attachment_ids or []),
        "internetEnabled": bool(r.internet_enabled),
        "thinkingText": "".join(
            item.text for item in r.events.filter(kind="thinking").order_by("id")
        ),
        "thinkingDurationMs": _thinking_duration_ms(r),
        "attachments": [
            serialize_attachment(item)
            for item in AgentAttachment.objects.filter(
                conversation_id=r.conversation_id, pk__in=r.attachment_ids or []
            )
        ],
    }


def _compute_intent(run, user, p):
    from .compute_intents import serialize

    return serialize(run, user, p) if run.conversation.mode == "agent" else None


def _run_parameters(run):
    parameters = run.events.filter(kind="parameters").order_by("-id").first()
    result = json.loads(parameters.text) if parameters else {}
    usages = [json.loads(item.text) for item in run.events.filter(kind="usage")]
    if usages:
        result["lastGeneratedTokens"] = usages[-1].get("completion_tokens", 0)
        result["modelCalls"] = len(usages)
        result["generatedTokens"] = sum(
            item.get("completion_tokens", 0) for item in usages
        )
    return result


def _thinking_duration_ms(run):
    events = list(run.events.filter(kind="thinking").order_by("created_at"))
    if not events:
        return 0
    end = run.updated_at if run.status not in ACTIVE else timezone.now()
    return max(0, int((end - events[0].created_at).total_seconds() * 1000))


def own_conversation(user, pk):
    c = get_object_or_404(Conversation.objects, pk=pk, owner=user)
    require_access(user, c.mode)
    return c


@endpoint(["GET"])
def bootstrap(request):
    p = policy()
    chat, agent = allowed(request.user, "chat", p), allowed(request.user, "agent", p)
    return JsonResponse(
        {
            "canChat": chat,
            "canAgent": agent,
            "canManage": is_superadmin(request.user),
            "budgets": budget_options(request.user, p),
            "thinkingEnabled": bool(p.get("thinkingEnabled", True)),
            "defaultReasoningEffort": p["reasoningEffort"],
            "internetEnabled": bool(p.get("internetEnabled", False)),
            "allowAttachments": bool(p.get("allowAttachments", False)),
            "maxAttachmentBytes": int(p.get("maxAttachmentBytes", 20 * 1024 * 1024)),
            "maxAttachments": int(p.get("maxAttachments", 8)),
            "models": visible_models(request.user, p=p) if chat or agent else [],
            "workerOnline": worker_online(),
            "defaultChatModel": p["defaultChatModel"] if chat else "",
            "defaultAgentModel": p["defaultAgentModel"] if agent else "",
            "capabilities": (["chat"] if chat else [])
            + (["read_data", "analyze_data", "attachments"] if agent else []),
        }
    )


@endpoint(["GET", "POST"])
def conversations(request):
    if request.method == "POST":
        value = body(request, ["mode", "title"])
        mode = value.get("mode")
        if mode not in {"chat", "agent"}:
            raise ApiProblem("模式无效")
        require_access(request.user, mode)
        title = value.get("title", "新会话")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            raise ApiProblem("标题长度须为1至120字")
        c = Conversation.objects.create(
            owner=request.user, mode=mode, title=title.strip()
        )
        return JsonResponse(conversation_json(c), status=201)
    mode = request.GET.get("mode", "chat")
    if mode not in {"chat", "agent"}:
        raise ApiProblem("模式无效")
    require_access(request.user, mode)
    qs = Conversation.objects.filter(
        owner=request.user, mode=mode, archived=request.GET.get("archived") == "true"
    )
    qs = qs.filter(title__icontains=request.GET.get("q", "")[:120])
    return JsonResponse({"items": [conversation_json(c) for c in qs[:200]]})


@endpoint(["GET", "PATCH", "DELETE"])
def conversation_detail(request, conversation_id):
    c = own_conversation(request.user, conversation_id)
    if request.method == "GET":
        runs = list(c.runs.select_related("conversation").order_by("-id")[:100])
        return JsonResponse(
            {
                "conversation": conversation_json(c),
                "runs": [run_json(r, request.user) for r in reversed(runs)],
                "attachments": [
                    serialize_attachment(item) for item in c.attachments.all()
                ],
            }
        )
    if request.method == "DELETE":
        with transaction.atomic():
            # Acquire write lock before checking active work, also serializes submit.
            Conversation.objects.filter(pk=c.pk).update(updated_at=timezone.now())
            if c.runs.filter(status__in=ACTIVE).exists():
                raise ApiProblem("请先停止活动运行", 409)
            c.delete()
        return JsonResponse({"detail": "会话已删除"})
    value = body(request, ["title", "archived"])
    if "title" in value:
        if (
            not isinstance(value["title"], str)
            or not 1 <= len(value["title"].strip()) <= 120
        ):
            raise ApiProblem("标题长度须为1至120字")
        c.title = value["title"].strip()
    if "archived" in value:
        if type(value["archived"]) is not bool:
            raise ApiProblem("归档状态无效")
        if c.runs.filter(status__in=ACTIVE).exists():
            raise ApiProblem("请先停止活动运行", 409)
        c.archived = value["archived"]
    c.save(update_fields=["title", "archived", "updated_at"])
    return JsonResponse(conversation_json(c))


@endpoint(["POST"])
def submit(request, conversation_id):
    c = own_conversation(request.user, conversation_id)
    prompt_limit = budget_options(request.user, policy())["maxPromptCharacters"]
    value = body(
        request,
        [
            "model",
            "prompt",
            "idempotencyKey",
            "resourceIds",
            "thinkingMode",
            "reasoningEffort",
            "attachmentIds",
            "internetEnabled",
            "budgetProfile",
            "maxOutputTokens",
        ],
        max_bytes=max(256000, prompt_limit * 6 + 8192),
    )
    alias, prompt, key = (
        value.get("model"),
        value.get("prompt"),
        value.get("idempotencyKey"),
    )
    selected = value.get("resourceIds", [])
    attachment_ids = value.get("attachmentIds", [])
    internet_enabled = value.get("internetEnabled", False)
    thinking_mode = value.get("thinkingMode", "fast")
    reasoning_effort = value.get("reasoningEffort", "")
    if "reasoningEffort" in value and (
        not isinstance(reasoning_effort, str)
        or reasoning_effort not in {"low", "medium", "xhigh"}
        or thinking_mode != "deep"
    ):
        raise ApiProblem("思考强度须在深度思考模式下选择低、标准或高")
    budget_profile = value.get("budgetProfile", "")
    output_tokens = value.get("maxOutputTokens")
    if (
        not isinstance(alias, str)
        or not isinstance(prompt, str)
        or not 1 <= len(prompt.strip()) <= prompt_limit
        or not isinstance(budget_profile, str)
        or not isinstance(key, str)
        or not 8 <= len(key) <= 80
        or thinking_mode not in {"fast", "deep"}
        or type(internet_enabled) is not bool
    ):
        raise ApiProblem("模型、问题或幂等键无效")
    if (
        not isinstance(selected, list)
        or len(selected) > 3
        or any(type(i) is not int or i < 1 for i in selected)
    ):
        raise ApiProblem("最多选择3个数据资源")
    if (
        not isinstance(attachment_ids, list)
        or len(attachment_ids) > int(policy().get("maxAttachments", 8))
        or any(type(item) is not int or item < 1 for item in attachment_ids)
    ):
        raise ApiProblem("最多选择8个附件")
    selected = sorted(set(selected))
    attachment_ids = sorted(set(attachment_ids))
    with transaction.atomic():
        Conversation.objects.filter(pk=c.pk).update(updated_at=timezone.now())
        existing = c.runs.filter(idempotency_key=key).first()
        if existing:
            if (
                existing.model,
                existing.prompt,
                existing.resource_ids,
                existing.thinking_mode,
                existing.reasoning_effort,
                existing.attachment_ids,
                existing.internet_enabled,
                existing.budget_profile,
                existing.budget_snapshot.get("requestedMaxOutputTokens"),
            ) != (
                alias,
                prompt.strip(),
                selected,
                thinking_mode,
                reasoning_effort,
                attachment_ids,
                internet_enabled,
                budget_profile,
                output_tokens,
            ):
                raise ApiProblem("幂等键已用于不同请求", 409)
            return JsonResponse(run_json(existing, request.user), status=202)
        c.refresh_from_db()
        if c.archived:
            raise ApiProblem("请先恢复归档会话", 409)
        p = require_access(request.user, c.mode, alias)
        model_config = registry()[alias]
        if thinking_mode == "deep":
            if not p.get("thinkingEnabled", True):
                raise ApiProblem("深度思考已由管理员关闭", 403)
            if not model_config.qwen:
                raise ApiProblem("当前模型不支持深度思考", 400)
        if c.mode == "chat" and selected:
            raise ApiProblem("普通聊天不访问平台数据")
        if internet_enabled and not p.get("internetEnabled", False):
            raise ApiProblem("联网检索尚未由管理员开启", 403)
        for resource_id in selected:
            resolve_resource(request.user, p, resource_id)
        attachments = list(
            AgentAttachment.objects.filter(
                conversation=c, owner=request.user, pk__in=attachment_ids
            )
        )
        if len(attachments) != len(attachment_ids):
            raise ApiProblem("附件不存在或不属于当前会话")
        if any(
            item.kind == "document" and not p.get("allowDocuments", False)
            for item in attachments
        ):
            raise ApiProblem("文档分析尚未由管理员开启", 403)
        if (
            any(item.kind == "image" for item in attachments)
            and not model_config.vision
        ):
            raise ApiProblem("当前模型未验收图片分析能力", 400)
        for previous in c.runs.all():
            if c.mode == "agent":
                check_evidence(previous, request.user, p)
        if not worker_online():
            raise ApiProblem("模型工作进程未就绪，请联系管理员", 503)
        available = visible_models(request.user, c.mode, p)
        if not any(m["alias"] == alias and m["status"] == "online" for m in available):
            raise ApiProblem("该模型当前离线或尚未验收", 503)
        serving_window = next(
            m["contextWindowTokens"] for m in available if m["alias"] == alias
        )
        budget_snapshot = resolve_budget(
            request.user, p, budget_profile, output_tokens, serving_window
        )
        if AgentRun._base_manager.filter(
            owner=request.user, status__in=ACTIVE
        ).exists():
            raise ApiProblem("您已有排队或生成中的任务", 409)
        if AgentRun._base_manager.filter(status__in=ACTIVE).count() >= 30:
            raise ApiProblem("当前排队已满", 429)
        if AgentRun._base_manager.filter(
            owner=request.user, created_at__date=timezone.localdate()
        ).count() >= daily_quota(request.user, p):
            raise ApiProblem("今日使用额度已用完", 429)
        r = AgentRun.objects.create(
            conversation=c,
            owner=request.user,
            model=alias,
            thinking_mode=thinking_mode,
            reasoning_effort=reasoning_effort,
            prompt=prompt.strip(),
            idempotency_key=key,
            resource_ids=selected,
            attachment_ids=attachment_ids,
            internet_enabled=internet_enabled,
            budget_profile=budget_profile,
            budget_snapshot=budget_snapshot,
        )
        if c.title == "新会话":
            c.title = prompt.strip()[:60]
            c.save(update_fields=["title", "updated_at"])
    log_operation(
        request.user,
        "agent",
        "submit",
        "success",
        target_type="agent_run",
        target_id=r.id,
        message=f"mode={c.mode}; model={alias}",
    )
    return JsonResponse(run_json(r, request.user), status=202)


@endpoint(["GET", "POST"])
def conversation_attachments(request, conversation_id):
    """Upload and list bounded files used by a conversation."""

    c = own_conversation(request.user, conversation_id)
    if request.method == "GET":
        return JsonResponse(
            {"items": [serialize_attachment(item) for item in c.attachments.all()]}
        )
    if c.archived:
        raise ApiProblem("请先恢复归档会话", 409)
    p = require_access(request.user, c.mode)
    if not p.get("allowAttachments", False):
        raise ApiProblem("附件分析尚未由管理员开启", 403)
    upload = request.FILES.get("file")
    if upload is None:
        raise ApiProblem("请选择附件")
    attachment = store_attachment(
        conversation=c,
        owner=request.user,
        upload=upload,
        max_bytes=p.get("maxAttachmentBytes", 20 * 1024 * 1024),
        max_count=p.get("maxAttachments", 8),
        max_characters=max(
            120000, budget_options(request.user, p)["maxPromptCharacters"]
        ),
    )
    log_operation(
        request.user,
        "agent",
        "upload_attachment",
        "success",
        target_type="agent_attachment",
        target_id=attachment.id,
        message=f"conversation={c.id}; kind={attachment.kind}",
    )
    return JsonResponse(serialize_attachment(attachment), status=201)


@endpoint(["POST"])
def upload_attachment(request):
    """Compatibility upload endpoint for generated clients.

    The conversation-scoped route is preferred; this form accepts an explicit
    conversationId and applies exactly the same ownership and policy checks.
    """
    raw_id = request.POST.get("conversationId")
    if not raw_id or not str(raw_id).isdigit():
        raise ApiProblem("请提供会话 ID")
    return conversation_attachments(request, int(raw_id))


@endpoint(["DELETE"])
def attachment_detail(request, conversation_id, attachment_id):
    c = own_conversation(request.user, conversation_id)
    attachment = get_object_or_404(
        AgentAttachment.objects, pk=attachment_id, conversation=c, owner=request.user
    )
    if any(
        attachment.id in (run.attachment_ids or [])
        for run in AgentRun._base_manager.filter(conversation=c, status__in=ACTIVE)
    ):
        raise ApiProblem("附件正在被活动运行使用，请稍后删除", 409)
    delete_attachment(attachment)
    log_operation(
        request.user,
        "agent",
        "delete_attachment",
        "success",
        target_type="agent_attachment",
        target_id=attachment_id,
        message=f"conversation={c.id}",
    )
    return JsonResponse({"detail": "附件已删除"})


@endpoint(["GET"])
def run_detail(request, run_id):
    r = get_object_or_404(
        AgentRun.objects.select_related("conversation"), pk=run_id, owner=request.user
    )
    data = run_json(r, request.user)
    after = int(request.GET.get("after", "0"))
    if not 0 <= after < 2**63:
        raise ApiProblem("事件游标无效")
    events = list(r.events.filter(pk__gt=after)[:100])
    return JsonResponse(
        {
            "run": data,
            "events": [
                {
                    "id": e.id,
                    "kind": e.kind,
                    "text": e.text,
                    "createdAt": e.created_at.isoformat(),
                }
                for e in events
            ],
            "cursor": events[-1].id if events else after,
        }
    )


@endpoint(["POST"])
def cancel(request, run_id):
    r = get_object_or_404(
        AgentRun.objects.select_related("conversation"), pk=run_id, owner=request.user
    )
    # Ownership is enough to stop consumption, even after usage permission revocation.
    AgentRun.objects.filter(pk=r.id).update(cancel_requested=True)
    AgentRun.objects.filter(pk=r.id, status="queued").update(
        status="cancelled", detail="已取消", updated_at=timezone.now()
    )
    r.refresh_from_db()
    return JsonResponse(run_json(r, request.user))


@endpoint(["GET"])
def compute_tasks(request, run_id):
    from .compute_tools import run_tasks

    run = get_object_or_404(AgentRun.objects, pk=run_id, owner=request.user)
    p = require_access(request.user, "agent", run.model)
    return JsonResponse(run_tasks(run, request.user, p))


@endpoint(["GET", "POST"])
def compute_intent(request, run_id):
    from .compute_intents import update

    run = get_object_or_404(
        AgentRun.objects.select_related("conversation"), pk=run_id, owner=request.user
    )
    p = require_access(request.user, "agent", run.model)
    if run.conversation.mode != "agent":
        raise ApiProblem("普通对话没有计算计划")
    check_evidence(run, request.user, p)
    if request.method == "POST":
        value = body(
            request, ["action", "planRevision", "inputs", "parameters", "autoImport"]
        )
        update(run, request.user, p, value)
        run.refresh_from_db()
        log_operation(
            request.user,
            "agent",
            "compute_intent",
            "success",
            target_type="agent_run",
            target_id=run.id,
            message=value["action"],
        )
    return JsonResponse(run_json(run, request.user))


@endpoint(["GET"])
def resource_list(request):
    p = require_access(request.user, "agent")
    query = request.GET.get("q", "")[:200]
    found = (
        resources(request.user, p)
        .filter(Q(name__icontains=query) | Q(description__icontains=query))
        .order_by("name")[:50]
    )
    return JsonResponse({"items": [brief(r) for r in found]})


def workflow_json(workflow, include_steps=True):
    data = {
        "id": str(workflow.id),
        "projectId": workflow.project_tag_id,
        "workflowType": workflow.workflow_type,
        "goal": workflow.goal,
        "model": workflow.model,
        "status": workflow.status,
        "detail": workflow.detail,
        "currentStep": workflow.current_step,
        "iteration": workflow.iteration,
        "operatorSteps": workflow.operator_steps,
        "maxIterations": workflow.max_iterations,
        "maxOperatorSteps": workflow.max_operator_steps,
        "executeOperators": workflow.execute_operators,
        "resourceIds": workflow.resource_ids,
        "algorithmVersionId": workflow.algorithm_version_id,
        "parameters": workflow.parameters,
        "plan": workflow.plan,
        "planHash": workflow.plan_hash,
        "importResults": workflow.import_results,
        "resultResourceIds": workflow.result_resource_ids,
        "resultIds": workflow.result_ids,
        "evidence": workflow.evidence,
        "createdAt": workflow.created_at.isoformat(),
        "updatedAt": workflow.updated_at.isoformat(),
        "runtime": "durable_state_machine",
    }
    if include_steps:
        data["steps"] = [
            {
                "id": item.id,
                "sequence": item.sequence,
                "kind": item.kind,
                "status": item.status,
                "message": item.message,
                "action": item.action,
                "inputRefs": item.input_refs,
                "outputRefs": item.output_refs,
                "metrics": item.metrics,
                "computeTaskId": str(item.compute_task_id)
                if item.compute_task_id
                else "",
                "errorCode": item.error_code,
                "startedAt": item.started_at.isoformat(),
                "finishedAt": item.finished_at.isoformat() if item.finished_at else "",
            }
            for item in workflow.steps.all()
        ]
    return data


@endpoint(["GET", "POST"])
def workflow_submit(request):
    if request.method == "GET":
        from .workflow import _authorize

        require_access(request.user, "agent")
        visible = []
        for workflow in AgentWorkflow.objects.filter(owner=request.user).order_by(
            "-created_at"
        )[:30]:
            try:
                _authorize(workflow)
                visible.append(workflow_json(workflow))
            except PermissionDenied:
                continue
        return JsonResponse({"items": visible})
    value = body(
        request,
        [
            "workflowType",
            "goal",
            "model",
            "resourceIds",
            "algorithmVersionId",
            "parameters",
            "executeOperators",
            "idempotencyKey",
            "inputs",
            "importResults",
        ],
    )
    p = require_access(request.user, "agent", value.get("model"))
    if not p.get("workflowEnabled", True):
        raise ApiProblem("科研工作流功能已关闭", 403)
    goal = value.get("goal")
    model = value.get("model")
    workflow_type = value.get("workflowType", "hyperspectral_interpretation")
    key = value.get("idempotencyKey")
    resources_selected = value.get("resourceIds", [])
    parameters = value.get("parameters", {})
    execute_operators = value.get("executeOperators", False)
    algorithm_id = value.get("algorithmVersionId")
    inputs = value.get("inputs", {})
    import_results = value.get("importResults", True)
    if (
        not isinstance(goal, str)
        or not 1 <= len(goal.strip()) <= 12000
        or not isinstance(workflow_type, str)
        or not 1 <= len(workflow_type) <= 40
        or not isinstance(model, str)
        or not isinstance(key, str)
        or not 8 <= len(key) <= 80
        or not isinstance(resources_selected, list)
        or len(resources_selected) > p["maxResources"]
        or any(type(i) is not int or i < 1 for i in resources_selected)
        or not isinstance(parameters, dict)
        or len(parameters) > 60
        or type(execute_operators) is not bool
        or (algorithm_id is not None and type(algorithm_id) is not int)
        or not isinstance(inputs, dict)
        or len(inputs) > 30
        or any(
            not isinstance(k, str) or type(v) is not int or v < 1
            for k, v in inputs.items()
        )
        or type(import_results) is not bool
    ):
        raise ApiProblem("科研工作流参数无效")
    if execute_operators and not p.get("operatorEnabled", False):
        raise ApiProblem("智能体自动调用算子尚未由超级管理员开启", 403)
    if execute_operators:
        raise ApiProblem("请先生成计划，再使用确认执行入口")
    resources_selected = sorted(set(resources_selected))
    with transaction.atomic():
        existing = AgentWorkflow._base_manager.filter(
            owner=request.user,
            project_tag_id=request.headers.get("X-Project-Id"),
            idempotency_key=key,
        ).first()
        if existing:
            if (
                existing.goal != goal.strip()
                or existing.model != model
                or existing.policy_snapshot.get("request") != value
            ):
                raise ApiProblem("幂等键已用于不同科研工作流", 409)
            return JsonResponse(workflow_json(existing), status=202)
        if AgentWorkflow._base_manager.filter(
            owner=request.user, status__in=WORKFLOW_ACTIVE
        ).exists():
            raise ApiProblem("您已有活动科研工作流，请等待完成", 409)
        workflow = AgentWorkflow.objects.create(
            owner=request.user,
            workflow_type=workflow_type,
            goal=goal.strip(),
            model=model,
            max_iterations=p["maxIterations"],
            max_operator_steps=p["maxOperatorSteps"],
            execute_operators=execute_operators,
            resource_ids=resources_selected,
            algorithm_version_id=algorithm_id,
            parameters=parameters,
            plan={"inputs": inputs},
            import_results=import_results,
            idempotency_key=key,
            policy_snapshot={
                "request": value,
                "revision": AgentPolicy.objects.filter(pk=1)
                .values_list("updated_at", flat=True)
                .first()
                .isoformat()
                if AgentPolicy.objects.filter(pk=1).exists()
                else "",
                "maxIterations": p["maxIterations"],
                "maxOperatorSteps": p["maxOperatorSteps"],
                "operatorEnabled": p.get("operatorEnabled", False),
            },
        )
    return JsonResponse(workflow_json(workflow), status=202)


@endpoint(["POST"])
def workflow_confirm(request, workflow_id):
    from .workflow import validate_confirmed_plan

    value = body(request, ["planHash"])
    with transaction.atomic():
        workflow = get_object_or_404(
            AgentWorkflow.objects.select_for_update(),
            pk=workflow_id,
            owner=request.user,
        )
        p = require_access(request.user, "agent", workflow.model)
        if not p.get("workflowEnabled", True):
            raise ApiProblem("科研工作流功能已关闭", 403)
        if (
            not isinstance(value.get("planHash"), str)
            or value["planHash"] != workflow.plan_hash
        ):
            raise ApiProblem("执行计划已变化，请刷新后确认", 409)
        if workflow.execute_operators and workflow.status in WORKFLOW_ACTIVE:
            return JsonResponse(workflow_json(workflow))
        if workflow.status != "waiting_approval" or workflow.cancel_requested:
            raise ApiProblem("此计划当前不能确认执行", 409)
        validate_confirmed_plan(workflow, request.user, p)
        workflow.execute_operators = True
        workflow.status, workflow.detail = "queued", "已确认，等待计算中心执行"
        workflow.save(
            update_fields=["execute_operators", "status", "detail", "updated_at"]
        )
    return JsonResponse(workflow_json(workflow))


@endpoint(["GET"])
def workflow_detail(request, workflow_id):
    from .workflow import _authorize

    workflow = get_object_or_404(
        AgentWorkflow.objects, pk=workflow_id, owner=request.user
    )
    _authorize(workflow)
    return JsonResponse(workflow_json(workflow))


@endpoint(["POST"])
def workflow_cancel(request, workflow_id):
    workflow = get_object_or_404(
        AgentWorkflow.objects, pk=workflow_id, owner=request.user
    )
    require_access(request.user, "agent", workflow.model)
    AgentWorkflow.objects.filter(pk=workflow.id, status__in=WORKFLOW_ACTIVE).update(
        cancel_requested=True, detail="正在停止工作流", updated_at=timezone.now()
    )
    # A queued item is not claimable after cancellation, so close it here
    # instead of leaving an invisible forever-queued record.
    AgentWorkflow.objects.filter(
        pk=workflow.id, status__in=["queued", "waiting_approval"]
    ).update(status="cancelled", detail="已取消", updated_at=timezone.now())
    workflow.refresh_from_db()
    return JsonResponse(workflow_json(workflow))


def admin_json(user):
    saved = AgentPolicy.objects.filter(pk=1).first()
    return {
        "policy": policy(),
        "revision": saved.updated_at.isoformat() if saved else "",
        "models": visible_models(user, admin=True),
        "groups": list(
            Group.objects.exclude(name=GUEST_GROUP_NAME).values("id", "name")
        ),
        "users": [
            {"id": u.id, "name": u.get_full_name() or u.username}
            for u in get_user_model()
            .objects.filter(is_active=True)
            .exclude(groups__name=GUEST_GROUP_NAME)
            .exclude(username="guest")
        ],
        "queued": AgentRun._base_manager.filter(status="queued").count(),
        "running": AgentRun._base_manager.filter(status="running").count(),
        "workerOnline": worker_online(),
    }


@endpoint(["GET", "PUT"])
def admin(request):
    if not is_superadmin(request.user):
        raise PermissionDenied("仅超级管理员可管理智能体")
    if request.method == "PUT":
        value = body(request, ["policy", "revision"])
        validated = validate_policy(value["policy"])
        with transaction.atomic():
            AgentRuntime.objects.update_or_create(
                name="policy_lock", defaults={"heartbeat": timezone.now()}
            )
            saved = AgentPolicy.objects.filter(pk=1).first()
            if value.get("revision") != (saved.updated_at.isoformat() if saved else ""):
                raise ApiProblem("设置已被更新，请刷新后重试", 409)
            AgentPolicy.objects.update_or_create(pk=1, defaults={"value": validated})
        log_operation(
            request.user,
            "agent",
            "policy",
            "success",
            "智能体可见范围与使用策略已更新",
            request,
        )
    return JsonResponse(admin_json(request.user))
