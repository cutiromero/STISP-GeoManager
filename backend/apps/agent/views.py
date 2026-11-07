import json
from functools import wraps

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError, transaction, connection
from django.db.models import Q, F
from django.http import HttpResponse, JsonResponse, Http404
from django.middleware.gzip import GZipMiddleware
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
from .run_concurrency import lock_run_queue, require_run_capacity, retry_run_admission


class ApiProblem(Exception):
    def __init__(self, detail, status=400):
        self.detail, self.status = detail, status


def endpoint(methods, *, require_project=True):
    def decorate(func):
        @api_login_required
        @wraps(func)
        def wrapped(request, *args, **kwargs):
            try:
                if request.method not in methods:
                    return JsonResponse({"detail": "不支持的请求方法"}, status=405)
                if require_project and not request.headers.get("X-Project-Id"):
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
    from .selections import check_history_evidence, serialize as selection_json
    from .interactions import public_question
    from .answer_preview import stored_answer_preview

    p = require_access(user, r.conversation.mode)
    if r.conversation.mode == "agent":
        check_history_evidence(r, user, p)
    return {
        "id": r.id,
        **selection_json(r),
        "conversationId": r.conversation_id,
        "model": r.model,
        "thinkingMode": r.thinking_mode,
        "budgetProfile": r.budget_snapshot.get("budgetProfile", ""),
        "generationParameters": _run_parameters(r),
        "status": r.status,
        "prompt": r.prompt,
        "answer": r.answer,
        "answerPreview": stored_answer_preview(r),
        "detail": r.detail,
        "evidence": r.evidence,
        "computeIntent": _compute_intent(r, user, p),
        "researchIntent": _research_intent(r, user, p),
        "interaction": public_question(r.interaction) if r.interaction else None,
        "interactionHistory": [public_question(item) for item in r.interaction_history],
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

    return (
        serialize(run, user, p, history=True)
        if run.conversation.mode == "agent"
        else None
    )


def _research_intent(run, user, p):
    from .research_intents import serialize

    return (
        serialize(run, user, p, history=True)
        if run.conversation.mode == "agent"
        else None
    )


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
    from .selections import algorithm_options
    from apps.knowledge.domains import domain_options
    from apps.knowledge.services import visible_entries

    p = policy()
    chat, agent = allowed(request.user, "chat", p), allowed(request.user, "agent", p)
    return JsonResponse(
        {
            "canChat": chat,
            "canAgent": agent,
            "knowledgeDomains": domain_options(visible_entries(request.user)),
            "algorithmOptions": algorithm_options() if agent else [],
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
        from .interactions import BLOCKING

        if c.runs.filter(status__in=BLOCKING).exists():
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
            "knowledgeSelection",
            "algorithmSelectionMode",
            "algorithmVersionIds",
            "dataSelectionMode",
            "demoScenario",
            "uploadBatchId",
            "reuseConfirmedConfiguration",
            "combineInputReview",
        ],
        max_bytes=max(256000, prompt_limit * 6 + 8192),
    )
    return submit_value(request, c, value)


@retry_run_admission
def submit_value(request, c, value, *, available_models=None):
    """The same quota, model, scope and idempotency checks for chat answers."""
    submission_policy = policy()
    prompt_limit = budget_options(request.user, submission_policy)[
        "maxPromptCharacters"
    ]
    demo_scenario = value.get("demoScenario")
    upload_batch = value.get("uploadBatchId")
    reuse_configuration = value.get("reuseConfirmedConfiguration", False)
    combined_review = value.get("combineInputReview", False)
    if type(combined_review) is not bool or (combined_review and not upload_batch):
        raise ApiProblem("合并资料核对需要逻辑推理资料批次")
    if type(reuse_configuration) is not bool or (
        reuse_configuration and not upload_batch
    ):
        raise ApiProblem("复用配置需要逻辑推理资料批次")
    if upload_batch is not None:
        from apps.core.client_build import current_browser

        if not current_browser(request):
            raise ApiProblem(
                "平台已更新，请刷新页面后使用新版逻辑推理；已上传资料保留", 409
            )
        from .generic_chat import validate_batch

        validate_batch(
            request.user,
            c,
            upload_batch,
            run=c.runs.filter(idempotency_key=value.get("idempotencyKey")).first(),
        )
        if demo_scenario:
            raise ApiProblem("上传资料与演示场景不能同时提交")
    if demo_scenario is not None and (
        demo_scenario
        not in {
            "ecology_investigation",
            "geology_correction",
            "geology_age_correction",
            "geology_map_review",
            "geology_multi_element_reasoning",
        }
        or c.mode != "agent"
    ):
        raise ApiProblem("演示场景无效或未使用智能体模式")
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
        raise ApiProblem("思考强度须在逻辑推理模式下选择低、标准或高")
    budget_profile = value.get("budgetProfile", "")
    output_tokens = value.get("maxOutputTokens")
    if (
        upload_batch is not None
        and isinstance(prompt, str)
        and len(prompt.strip()) > 12000
    ):
        raise ApiProblem("逻辑推理需求最多12000字，请精简后发送")
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
        or (
            submission_policy["maxResources"] > 0
            and len(selected) > submission_policy["maxResources"]
        )
        or any(type(i) is not int or i < 1 for i in selected)
    ):
        raise ApiProblem("数据资源选择无效或超过管理员设置的资源额度")
    if (
        not isinstance(attachment_ids, list)
        or len(attachment_ids) > submission_policy["maxAttachments"]
        or any(type(item) is not int or item < 1 for item in attachment_ids)
    ):
        raise ApiProblem("附件选择无效或超过管理员设置的附件额度")
    selected = sorted(set(selected))
    from .selections import knowledge_selection, normalize, validate_selected_versions

    selections = normalize(value, selected)
    attachment_ids = sorted(set(attachment_ids))
    if available_models is None and not c.runs.filter(idempotency_key=key).exists():
        preflight_policy = require_access(request.user, c.mode, alias)
        # Model health requests finish before acquiring a database write lock.
        available_models = visible_models(request.user, c.mode, preflight_policy)
    with transaction.atomic():
        lock_run_queue()
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
                knowledge_selection(existing),
                existing.algorithm_selection_mode,
                existing.algorithm_version_ids,
                existing.data_selection_mode,
                existing.research_intent.get("_demoScenario"),
                existing.research_intent.get("_uploadBatchId"),
                existing.research_intent.get("_requestedReuse", False),
                existing.research_intent.get("_combinedInputReview", False),
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
                selections["knowledge_selection"],
                selections["algorithm_selection_mode"],
                selections["algorithm_version_ids"],
                selections["data_selection_mode"],
                demo_scenario,
                upload_batch,
                reuse_configuration,
                combined_review,
            ):
                raise ApiProblem("幂等键已用于不同请求", 409)
            return JsonResponse(run_json(existing, request.user), status=202)
        c.refresh_from_db()
        if c.archived:
            raise ApiProblem("请先恢复归档会话", 409)
        if upload_batch is not None:
            validate_batch(request.user, c, upload_batch)
        p = require_access(request.user, c.mode, alias)
        model_config = registry()[alias]
        if thinking_mode == "deep":
            if not p.get("thinkingEnabled", True):
                raise ApiProblem("逻辑推理已由管理员关闭", 403)
            if not model_config.qwen:
                raise ApiProblem("当前模型不支持逻辑推理", 400)
        if c.mode == "chat" and selected:
            raise ApiProblem("普通聊天不访问平台数据")
        if c.mode == "chat" and (
            selections["algorithm_version_ids"]
            or selections["knowledge_selection"]["mode"] in {"manual", "all"}
        ):
            raise ApiProblem("普通聊天不调用平台算法或知识库，请切换智能体")
        validate_selected_versions(selections)
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
        # Unrelated or revoked history is omitted when constructing model context.
        # It must not prevent a new, independently authorized user request.
        if not worker_online():
            raise ApiProblem("模型工作进程未就绪，请联系管理员", 503)
        available = available_models or []
        if not any(m["alias"] == alias and m["status"] == "online" for m in available):
            raise ApiProblem("该模型当前离线或尚未验收", 503)
        serving_window = next(
            m["contextWindowTokens"] for m in available if m["alias"] == alias
        )
        budget_snapshot = resolve_budget(
            request.user, p, budget_profile, output_tokens, serving_window
        )
        require_run_capacity(request.user.id, c.id)
        quota = daily_quota(request.user, p)
        if (
            quota > 0
            and AgentRun._base_manager.filter(
                owner=request.user, created_at__date=timezone.localdate()
            ).count()
            >= quota
        ):
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
            **{
                **selections,
                "knowledge_selection": {
                    **selections["knowledge_selection"],
                    "_contextRunIds": [],
                },
            },
            attachment_ids=attachment_ids,
            internet_enabled=internet_enabled,
            budget_profile=budget_profile,
            budget_snapshot=budget_snapshot,
            research_intent=(
                {
                    "_uploadBatchId": upload_batch,
                    "_reuseConfirmedConfiguration": reuse_configuration,
                    "_requestedReuse": reuse_configuration,
                    "_combinedInputReview": combined_review,
                }
                if upload_batch
                else {"_demoScenario": demo_scenario}
                if demo_scenario
                else {}
            ),
        )
        from .conversation_titles import update_logic_title

        if not update_logic_title(r) and c.title == "新会话":
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
    from .interactions import BLOCKING

    if any(
        attachment.id in (run.attachment_ids or [])
        for run in AgentRun._base_manager.filter(conversation=c, status__in=BLOCKING)
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
    with transaction.atomic():
        AgentRun.objects.filter(pk=r.id).update(cancel_requested=True)
        r.refresh_from_db()
        if r.interaction.get("status") == "pending":
            card = {**r.interaction, "status": "cancelled"}
            AgentRun.objects.filter(pk=r.id).update(
                interaction=card,
                interaction_history=[
                    card if item["questionId"] == card["questionId"] else item
                    for item in r.interaction_history
                ],
            )
        AgentRun.objects.filter(
            pk=r.id,
            status__in=["queued", "waiting_input", "waiting_review", "waiting_compute"],
        ).update(
            status="cancelled",
            detail="已停止后续处理；已提交计算可能继续，可在任务卡单独停止"
            if r.compute_followups.filter(
                task__status__in=["queued", "validating", "running", "cancelling"]
            ).exists()
            else "已取消，后续操作不会继续启动",
            updated_at=timezone.now(),
        )
    if r.research_workflow_id:
        AgentWorkflow.objects.filter(
            pk=r.research_workflow_id, owner=request.user
        ).update(cancel_requested=True)
    r.refresh_from_db()
    return JsonResponse(run_json(r, request.user))


@endpoint(["POST"])
def interaction(request, run_id):
    from .interactions import answer

    run = get_object_or_404(
        AgentRun.objects.select_related("conversation"), pk=run_id, owner=request.user
    )
    p = require_access(request.user, run.conversation.mode, run.model)
    if run.conversation.mode == "agent":
        check_evidence(run, request.user, p)
    value = body(
        request,
        ["action", "questionId", "revision", "submissionKey", "answers", "text"],
    )
    answer(run, request.user, value)
    log_operation(
        request.user,
        "agent",
        "answer_interaction",
        "success",
        target_type="agent_run",
        target_id=run.id,
        message=value["action"],
    )
    return JsonResponse(
        run_json(run, request.user), status=202 if run.status == "queued" else 200
    )


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


@endpoint(["POST"])
def research_intent(request, run_id):
    from .research_actions import update

    value = body(request, ["action", "revision", "answers", "answer"])
    return update(request, run_id, value)


@endpoint(["GET"], require_project=False)
def research_demos(request):
    from .research_presets import list_demos

    p = require_access(request.user, "agent")
    view = request.GET.get("view", "")
    if view not in ("", "summary"):
        raise ApiProblem("场景列表格式无效")
    scenario = request.GET.get("scenario")
    from .demo_workflow import GRAPHS

    if scenario is not None and scenario not in GRAPHS:
        raise ApiProblem("研究场景无效")
    return JsonResponse(
        list_demos(request.user, p, summary=view == "summary", scenario=scenario)
    )


def workflow_json(workflow, include_steps=True, view="full"):
    card = view == "card"
    plan = workflow.plan
    if not card and workflow.workflow_type in {
        "geology_generic",
        "geology_multi_element_reasoning",
    }:
        from .geology_multi_results import public_plan

        plan = public_plan(plan)
    data = {
        "id": str(workflow.id),
        "projectId": workflow.project_tag_id,
        "workflowType": workflow.workflow_type,
        "goal": workflow.goal,
        "model": workflow.model,
        "status": workflow.status,
        "pauseRequested": workflow.pause_requested,
        "pausedFrom": workflow.paused_from or None,
        "detail": workflow.detail,
        "currentStep": workflow.current_step,
        "iteration": workflow.iteration,
        "operatorSteps": workflow.operator_steps,
        "maxIterations": workflow.max_iterations,
        "maxOperatorSteps": workflow.max_operator_steps,
        "executeOperators": workflow.execute_operators,
        "resourceIds": workflow.resource_ids,
        "algorithmVersionId": workflow.algorithm_version_id,
        "parameters": {} if card else workflow.parameters,
        "plan": plan
        if not card
        else {
            "phase": workflow.plan.get("phase"),
            "stageIndex": workflow.plan.get("stageIndex"),
            "deletedResources": workflow.plan.get("deletedResources", []),
            **{
                key: workflow.plan[key]
                for key in (
                    "fieldMappingReview",
                    "reusedConfiguration",
                    "retainedReview",
                )
                if key in workflow.plan
            },
            "stages": [
                {
                    key: stage[key]
                    for key in ("name", "identifier", "status", "taskId", "outputs")
                    if key in stage
                }
                for stage in workflow.plan.get("stages", [])
            ],
        },
        "planHash": workflow.plan_hash,
        "importResults": workflow.import_results,
        "resultResourceIds": workflow.result_resource_ids,
        "resultIds": workflow.result_ids,
        "evidence": [] if card else workflow.evidence,
        "createdAt": workflow.created_at.isoformat(),
        "updatedAt": workflow.updated_at.isoformat(),
        "runtime": "durable_state_machine",
    }
    if workflow.workflow_type in {"geology_generic", "geology_multi_element_reasoning"}:
        from .workflow_task_summary import task_summary

        data["taskSummary"] = task_summary(workflow)
        from .workflow_resources import display_input_names

        data["plan"] = {
            **data["plan"],
            "previousRounds": [
                {
                    "planHash": snapshot["planHash"],
                    "stages": [
                        {
                            key: stage[key]
                            for key in (
                                "name",
                                "identifier",
                                "status",
                                "taskId",
                                "outputs",
                            )
                            if key in stage
                        }
                        for stage in snapshot.get("stages", [])
                    ],
                }
                for snapshot in workflow.plan.get("retainedReviewHistory", [])
            ],
            "inputNames": display_input_names(workflow),
        }
    from .model_activity import latest_model_activity

    activity = latest_model_activity(workflow)
    if activity is not None:
        data["modelActivity"] = activity
    if card:
        data.update(view="card", steps=[], stepCount=workflow.steps.count())
    elif include_steps:
        data["steps"] = [
            {
                "id": item.id,
                "sequence": item.sequence,
                "kind": item.kind,
                "status": item.status,
                "message": item.message,
                "action": item.action,
                "decision": item.action.get("decision")
                if isinstance(item.action.get("decision"), dict)
                else None,
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
    if not card and workflow.plan.get("modificationReview") is not None:
        data["modificationReview"] = workflow.plan["modificationReview"]
    return data


@endpoint(["GET", "POST"])
def workflow_submit(request):
    if request.method == "GET":
        from .workflow import authorize_workflow_history

        require_access(request.user, "agent")
        view = request.GET.get("view", "")
        if view == "summary":
            from .workflow_history import summary_list

            return JsonResponse(summary_list(request.user, request.GET))
        if view:
            raise ApiProblem("历史列表格式无效")
        visible = []
        for workflow in AgentWorkflow.objects.filter(owner=request.user).order_by(
            "-created_at"
        )[:30]:
            try:
                authorize_workflow_history(workflow)
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
            "knowledgeSelection",
            "previousWorkflowId",
            "uploadBatchId",
        ],
    )
    from .workflow_creation import create_workflow

    workflow = create_workflow(request.user, request.headers.get("X-Project-Id"), value)
    return JsonResponse(workflow_json(workflow), status=202)


@endpoint(["GET", "POST"])
def workflow_uploads(request):
    from .workflow_uploads import (
        batch_uploads,
        require_upload_access,
        store_upload,
        upload_json,
    )

    project = request.headers.get("X-Project-Id")
    if request.method == "GET":
        require_upload_access(request.user, project)
        items = batch_uploads(request.user, request.GET.get("batchId"))
        return JsonResponse({"items": [upload_json(item) for item in items]})
    if set(request.POST) - {"batchId"} or set(request.FILES) != {"file"}:
        raise ApiProblem("请上传一个文件并提供批次号")
    upload = store_upload(
        request.user, project, request.FILES["file"], request.POST.get("batchId")
    )
    log_operation(
        request.user,
        "agent",
        "upload_workflow_file",
        "success",
        upload.file_name,
        target_type="data_resource",
        target_id=upload.resource_id,
    )
    return JsonResponse(upload_json(upload), status=201)


@endpoint(["POST"])
def workflow_upload_batch(request):
    from .workflow_bundles import store_batch

    if set(request.POST) != {"batchId"} or set(request.FILES) != {"files"}:
        raise ApiProblem("请上传资料文件并提供批次号")
    result = store_batch(
        request.user,
        request.headers.get("X-Project-Id"),
        request.FILES.getlist("files"),
        request.POST.get("batchId"),
    )
    log_operation(
        request.user,
        "agent",
        "upload_workflow_batch",
        "success",
        f"登记{len(result['items'])}份资料，失败{len(result['errors'])}份",
    )
    return JsonResponse(result)


@endpoint(["GET", "POST"])
def workflow_catalog_references(request):
    from .workflow_uploads import add_catalog_references, catalog_resources, upload_json

    project = request.headers.get("X-Project-Id")
    if request.method == "GET":
        query = request.GET.get("q", "")[:200]
        available = catalog_resources(request.user, project)
        try:
            page = int(request.GET.get("page", "1"))
            size = int(request.GET.get("pageSize", "20"))
            directory = request.GET.get("directoryId")
            directory = int(directory) if directory is not None else None
            if (
                page < 1
                or not 1 <= size <= 50
                or (directory is not None and directory < 0)
            ):
                raise ValueError
        except ValueError:
            raise ApiProblem("分页或目录参数无效")
        directories = list(
            available.order_by("inventory_group_id")
            .values_list("inventory_group_id", "inventory_group__name")
            .distinct()
        )
        found = (
            available.select_related("inventory_group")
            .filter(Q(name__icontains=query) | Q(description__icontains=query))
            .order_by("-updated_at", "-created_at", "-id")
        )
        if directory is not None:
            found = found.filter(inventory_group_id=directory or None)
        total = found.count()
        return JsonResponse(
            {
                "items": [
                    {
                        **brief(item),
                        "directoryId": item.inventory_group_id,
                        "directoryName": item.inventory_group.name
                        if item.inventory_group
                        else "",
                        "createdAt": item.created_at.isoformat(),
                        "updatedAt": item.updated_at.isoformat(),
                    }
                    for item in found[(page - 1) * size : page * size]
                ],
                "total": total,
                "page": page,
                "pageSize": size,
                "directories": [
                    {"id": identity or 0, "name": name or "未分组"}
                    for identity, name in directories
                ],
            }
        )
    value = body(request, ["batchId", "resourceIds"])
    items = add_catalog_references(
        request.user, project, value.get("batchId"), value.get("resourceIds")
    )
    log_operation(
        request.user,
        "agent",
        "reference_workflow_catalog",
        "success",
        f"引用{len(items)}份系统数据",
    )
    return JsonResponse({"items": [upload_json(item) for item in items]})


@endpoint(["GET", "POST"])
def logic_configuration(request):
    from .logic_configuration import configuration_json, read_configuration
    from .workflow_uploads import add_catalog_references, upload_json

    project = request.headers.get("X-Project-Id")
    value, unavailable = read_configuration(request.user, project)
    items = []
    if request.method == "POST":
        payload = body(request, ["batchId"])
        from .workflow_uploads import checked_batch

        batch = checked_batch(payload.get("batchId"))
        valid = (
            [
                identity
                for identity in value["resourceIds"]
                if identity not in unavailable
            ]
            if value
            else []
        )
        if valid:
            items = [
                upload_json(item)
                for item in add_catalog_references(request.user, project, batch, valid)
            ]
        log_operation(
            request.user,
            "agent",
            "restore_logic_configuration",
            "success",
            f"恢复{len(items)}份系统数据引用",
        )
    return JsonResponse(configuration_json(value, unavailable, items))


@endpoint(["POST"])
def workflow_recognize_roles(request):
    from .workflow_roles import recognize_roles

    value = body(request, ["batchId", "model"])
    if not isinstance(value.get("model"), str):
        raise ApiProblem("请选择模型")
    return JsonResponse(
        recognize_roles(
            request.user,
            request.headers.get("X-Project-Id"),
            value.get("batchId"),
            value["model"],
        )
    )


@endpoint(["GET"])
def workflow_active(request):
    from .models import WORKFLOW_COMPUTING, WORKFLOW_PARKED
    from .workflow_slots import workflow_summary

    policy = require_access(request.user, "agent")
    if not policy.get("workflowEnabled", True):
        raise ApiProblem("MH-workflow功能已关闭", 403)
    workflow = (
        AgentWorkflow._base_manager.filter(
            owner=request.user, status__in=WORKFLOW_COMPUTING
        )
        .order_by("-updated_at")
        .first()
    )
    parked = AgentWorkflow._base_manager.filter(
        owner=request.user, status__in=WORKFLOW_PARKED
    ).order_by("-updated_at")
    return JsonResponse(
        {
            "item": workflow_summary(workflow) if workflow else None,
            "parked": [workflow_summary(item) for item in parked],
        }
    )


@endpoint(["DELETE"])
def workflow_upload_detail(request, upload_id):
    from .workflow_uploads import delete_upload, require_upload_access

    require_upload_access(request.user, request.headers.get("X-Project-Id"))
    delete_upload(request.user, upload_id)
    log_operation(
        request.user,
        "agent",
        "delete_workflow_upload",
        "success",
        target_type="workflow_upload",
        target_code=str(upload_id),
    )
    return HttpResponse(status=204)


@endpoint(["POST"])
def workflow_confirm(request, workflow_id):
    from .workflow import validate_confirmed_plan
    from apps.core.client_build import current_browser

    if not current_browser(request):
        raise ApiProblem("平台已更新，请刷新页面后继续；已上传资料和任务进度保留", 409)

    value = body(
        request,
        [
            "planHash",
            "decision",
            "feedback",
            "selectedSuggestionIds",
            "suggestionSelection",
            "alterationActions",
            "fieldMapping",
            "executeAfterMapping",
            "applyRuleSuggestions",
        ],
        max_bytes=1024 * 1024,
    )
    decision, feedback = value.get("decision", "approve"), value.get("feedback", "")
    selected = value.get("selectedSuggestionIds")
    if "suggestionSelection" in value and "selectedSuggestionIds" in value:
        raise ApiProblem("请只提交一种审批选择方式")
    if (
        not isinstance(decision, str)
        or decision not in {"approve", "reject"}
        or not isinstance(feedback, str)
        or len(feedback) > 4000
    ):
        raise ApiProblem("审核结论或意见无效")
    if "selectedSuggestionIds" in value and (
        not isinstance(selected, list)
        or any(
            not isinstance(identity, str) or not 1 <= len(identity) <= 64
            for identity in selected
        )
        or len(set(selected)) != len(selected)
    ):
        raise ApiProblem("建议选择格式无效")
    with transaction.atomic():
        if connection.vendor == "sqlite":
            # Confirmations write approval records; reserve SQLite before reading
            # the plan so concurrent heartbeats cannot invalidate its snapshot.
            AgentWorkflow.objects.filter(pk=workflow_id, owner=request.user).update(
                idempotency_key=F("idempotency_key")
            )
        workflow = get_object_or_404(
            AgentWorkflow.objects.select_for_update(),
            pk=workflow_id,
            owner=request.user,
        )
        if "executeAfterMapping" in value and (
            type(value["executeAfterMapping"]) is not bool
            or workflow.workflow_type != "geology_generic"
            or workflow.plan.get("phase") != "review_mapping"
            or decision != "approve"
            or "fieldMapping" not in value
        ):
            raise ApiProblem("只有通用地质资料字段确认时可以同时授权开始分析", 400)
        if "applyRuleSuggestions" in value and (
            type(value["applyRuleSuggestions"]) is not bool
            or workflow.workflow_type != "geology_generic"
            or workflow.plan.get("phase") != "review_mapping"
            or decision != "approve"
            or value.get("executeAfterMapping") is not True
            or "fieldMapping" not in value
        ):
            raise ApiProblem("自动规则处置须在本次资料确认并开始分析时明确授权", 400)
        if "suggestionSelection" in value:
            if (
                workflow.workflow_type
                not in {"geology_generic", "geology_multi_element_reasoning"}
                or workflow.plan.get("phase") != "review_modifications"
                or decision != "approve"
            ):
                raise ApiProblem("当前阶段不支持紧凑审批选择")
            from .workflow_projection import resolve_selection

            selected = resolve_selection(workflow.plan, value["suggestionSelection"])
        if "alterationActions" in value and (
            workflow.workflow_type
            not in {"geology_generic", "geology_multi_element_reasoning"}
            or workflow.plan.get("phase") != "review_modifications"
            or decision != "approve"
        ):
            raise ApiProblem("当前阶段不支持蚀变组动作选择")
        if (
            selected is not None
            and len(selected) > 30
            and workflow.workflow_type
            not in {"geology_generic", "geology_multi_element_reasoning"}
        ):
            raise ApiProblem("建议选择格式无效")
        p = require_access(request.user, "agent", workflow.model)
        if not p.get("workflowEnabled", True):
            raise ApiProblem("MH-workflow功能已关闭", 403)
        if (
            not isinstance(value.get("planHash"), str)
            or value["planHash"] != workflow.plan_hash
        ):
            raise ApiProblem("执行计划已变化，请刷新后确认", 409)
        if workflow.status == "paused" or workflow.pause_requested:
            raise ApiProblem("请先继续科研任务，再确认执行", 409)
        review_outputs = workflow.plan.get("reviewOutputs", [])
        if decision == "reject":
            from .workflow import _authorize, _state_hash

            if workflow.status != "waiting_approval" or workflow.cancel_requested:
                raise ApiProblem("此计划当前不能审核", 409)
            if _state_hash(workflow.plan) != workflow.plan_hash:
                raise ApiProblem("执行计划已变化，请刷新后确认", 409)
            _authorize(workflow)
            if workflow.plan.get("scenarioVersion"):
                from .demo_workflow import authorize_demo

                authorize_demo(workflow, request.user, p)
            elif workflow.plan.get("phase") != "review_mapping":
                validate_confirmed_plan(workflow, request.user, p)
            record_workflow_review(
                workflow, "reject", feedback, value["planHash"], review_outputs
            )
            workflow.status, workflow.detail = (
                "cancelled",
                "审核未通过，已停止后续处理；候选成果与审核意见保留",
            )
            workflow.cancel_requested, workflow.pause_requested = True, False
            workflow.save(
                update_fields=[
                    "status",
                    "detail",
                    "cancel_requested",
                    "pause_requested",
                    "updated_at",
                ]
            )
            return JsonResponse(workflow_json(workflow))
        if workflow.workflow_type in {
            "ecology_investigation",
            "geology_correction",
            "geology_age_correction",
            "geology_map_review",
            "geology_multi_element_reasoning",
            "geology_generic",
        }:
            from .demo_workflow import confirm_demo

            confirm_demo(
                workflow,
                request.user,
                p,
                value["planHash"],
                selected,
                value.get("fieldMapping"),
                **(
                    {"execute_after_mapping": value["executeAfterMapping"]}
                    if "executeAfterMapping" in value
                    else {}
                ),
                **(
                    {"apply_rule_suggestions": value["applyRuleSuggestions"]}
                    if "applyRuleSuggestions" in value
                    else {}
                ),
                **(
                    {"alteration_actions": value["alterationActions"]}
                    if "alterationActions" in value
                    else {}
                ),
            )
            record_workflow_review(
                workflow, "approve", feedback, value["planHash"], review_outputs
            )
            return JsonResponse(workflow_json(workflow))
        if workflow.status == "paused" or workflow.pause_requested:
            raise ApiProblem("请先继续科研任务，再确认执行", 409)
        if workflow.execute_operators and workflow.status in WORKFLOW_ACTIVE:
            return JsonResponse(workflow_json(workflow))
        if workflow.status != "waiting_approval" or workflow.cancel_requested:
            raise ApiProblem("此计划当前不能确认执行", 409)
        validate_confirmed_plan(workflow, request.user, p)
        from .workflow_slots import require_compute_slot

        require_compute_slot(request.user, workflow.id)
        workflow.execute_operators = True
        workflow.status, workflow.detail = "queued", "已确认，等待计算中心执行"
        workflow.save(
            update_fields=["execute_operators", "status", "detail", "updated_at"]
        )
        record_workflow_review(
            workflow, "approve", feedback, value["planHash"], review_outputs
        )
    return JsonResponse(workflow_json(workflow))


def record_workflow_review(workflow, decision, feedback, plan_hash, review_outputs):
    from .workflow import checkpoint, step

    feedback = feedback.strip()
    action = {"decision": decision, "feedback": feedback, "planHash": plan_hash}
    stages = workflow.plan.get("stages", [])
    index = workflow.plan.get("stageIndex", -1)
    stage = (
        stages[index].get("name", workflow.current_step)
        if type(index) is int and 0 <= index < len(stages)
        else workflow.current_step
    )
    step(
        workflow,
        "review_feedback",
        message="用户审核通过，继续处理"
        if decision == "approve"
        else "用户审核未通过，停止后续处理",
        action=action,
        input_refs={"stage": stage},
        output_refs={"reviewOutputs": review_outputs},
    )
    checkpoint(workflow, "human_review_feedback", action)


@endpoint(["GET"])
def workflow_detail(request, workflow_id):
    from .workflow import authorize_workflow_history

    view = request.GET.get("view", "full")
    if view not in {"full", "card", "compare", "inspection"}:
        raise ApiProblem("工作流详情视图无效")
    workflow = get_object_or_404(
        AgentWorkflow.objects, pk=workflow_id, owner=request.user
    )
    authorize_workflow_history(workflow)
    if view in {"compare", "inspection"}:
        from .workflow_projection import page_options, project_workflow

        part, offset, limit = page_options(request.GET, view)
        element = request.GET.get("element", "all")
        if (
            element not in {"all", "lithology", "structure", "alteration"}
            or view != "compare"
            and element != "all"
        ):
            raise ApiProblem("工作流分页要素无效")
        data = project_workflow(
            workflow,
            workflow_json(workflow, view="card"),
            view,
            part,
            offset,
            limit,
            request.GET.get("suggestionId", "")[:100],
            element,
        )
    else:
        data = workflow_json(workflow, view=view)
    response = JsonResponse(data)
    if workflow.workflow_type in {"geology_generic", "geology_multi_element_reasoning"}:
        return GZipMiddleware(lambda _: response)(request)
    return response


@endpoint(["POST"])
def workflow_pause(request, workflow_id):
    from .workflow import _authorize
    from .workflow_controls import locked_workflow

    if request.body:
        body(request, [])
    with transaction.atomic():
        get_object_or_404(AgentWorkflow.objects, pk=workflow_id, owner=request.user)
        workflow = locked_workflow(workflow_id)
        _authorize(workflow)
        if workflow.status not in WORKFLOW_ACTIVE or workflow.cancel_requested:
            raise ApiProblem("此科研任务当前不能暂停", 409)
        if workflow.pause_requested or workflow.status == "paused":
            return JsonResponse(workflow_json(workflow))
        workflow.pause_requested = True
        workflow.paused_from = workflow.status
        if workflow.status != "running":
            workflow.status, workflow.detail = "paused", "已暂停，可从当前步骤继续"
        else:
            workflow.detail = "正在暂停；当前步骤到达保存点后停止后续处理"
        workflow.save(
            update_fields=[
                "pause_requested",
                "paused_from",
                "status",
                "detail",
                "updated_at",
            ]
        )
    return JsonResponse(workflow_json(workflow))


@endpoint(["POST"])
def workflow_resume(request, workflow_id):
    from .workflow import _authorize, validate_confirmed_plan
    from .workflow_controls import locked_workflow

    if request.body:
        body(request, [])
    with transaction.atomic():
        get_object_or_404(AgentWorkflow.objects, pk=workflow_id, owner=request.user)
        workflow = locked_workflow(workflow_id)
        user, p = _authorize(workflow)
        if workflow.cancel_requested:
            raise ApiProblem("已取消的科研任务不能继续", 409)
        if workflow.plan.get("deletedResources"):
            raise ApiProblem(
                "该科研任务的历史数据已被删除，请重新选择数据后发起任务", 409
            )
        if workflow.plan.get("scenarioVersion"):
            from .demo_workflow import authorize_demo

            authorize_demo(workflow, user, p)
        elif workflow.plan.get("algorithmVersionId"):
            validate_confirmed_plan(workflow, user, p)
        if workflow.status != "paused":
            if (
                workflow.paused_from
                and not workflow.pause_requested
                and workflow.status in WORKFLOW_ACTIVE
            ):
                return JsonResponse(workflow_json(workflow))
            raise ApiProblem("此科研任务当前没有可继续的暂停点", 409)
        continuation = workflow.paused_from
        if continuation not in {
            "queued",
            "running",
            "waiting_compute",
            "waiting_approval",
        }:
            raise ApiProblem("暂停点无效，请重新创建任务", 409)
        workflow.status = "queued" if continuation == "running" else continuation
        if workflow.status != "waiting_approval":
            from .workflow_slots import require_compute_slot

            require_compute_slot(user, workflow.id)
        workflow.pause_requested = False
        workflow.detail = (
            "已继续，等待用户确认原审核计划"
            if continuation == "waiting_approval"
            else "已继续，将复用已有计算与结果接着处理"
        )
        workflow.save(
            update_fields=["status", "pause_requested", "detail", "updated_at"]
        )
    return JsonResponse(workflow_json(workflow))


@endpoint(["POST"])
def workflow_cancel(request, workflow_id):
    value = body(request, ["replacePlanHash"]) if request.body else {}
    if "replacePlanHash" in value:
        expected = value["replacePlanHash"]
        if not isinstance(expected, str) or len(expected) != 64:
            raise ApiProblem("请提供最后读取的初始执行计划摘要")
        with transaction.atomic():
            AgentWorkflow.objects.filter(pk=workflow_id, owner=request.user).update(
                idempotency_key=F("idempotency_key")
            )
            workflow = get_object_or_404(
                AgentWorkflow.objects.select_for_update(),
                pk=workflow_id,
                owner=request.user,
            )
            require_access(request.user, "agent", workflow.model)
            if (
                workflow.status != "waiting_approval"
                or workflow.plan.get("phase") != "review_plan"
                or workflow.plan_hash != expected
                or workflow.execute_operators
                or workflow.operator_steps != 0
                or workflow.steps.filter(compute_task_id__isnull=False).exists()
            ):
                raise ApiProblem("原计划已变化或开始执行，未撤销，请刷新后核对", 409)
            workflow.status = "cancelled"
            workflow.cancel_requested = True
            workflow.pause_requested = False
            workflow.detail = "初始执行计划已作废，可按新的资料和参数重新生成"
            workflow.save(
                update_fields=[
                    "status",
                    "cancel_requested",
                    "pause_requested",
                    "detail",
                    "updated_at",
                ]
            )
        return JsonResponse(workflow_json(workflow))
    workflow = get_object_or_404(
        AgentWorkflow.objects, pk=workflow_id, owner=request.user
    )
    require_access(request.user, "agent", workflow.model)
    from .workflow_cancellation import stop_workflow

    workflow = stop_workflow(workflow.id, request.user.id)
    return JsonResponse(workflow_json(workflow, view="card"))


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


@endpoint(["POST"])
def workflow_retained_review(request, workflow_id):
    from .retained_review import reopen
    from .workflow_controls import locked_workflow
    from apps.core.client_build import current_browser

    if not current_browser(request):
        raise ApiProblem("平台已更新，请刷新后继续核查", 409)
    value = body(request, ["planHash"])
    with transaction.atomic():
        get_object_or_404(AgentWorkflow.objects, pk=workflow_id, owner=request.user)
        workflow = locked_workflow(workflow_id)
        policy = require_access(request.user, "agent", workflow.model)
        reopen(workflow, request.user, policy, value.get("planHash"))
    return JsonResponse(workflow_json(workflow, view="card"))


@endpoint(["POST"])
def workflow_retry_imports(request, workflow_id):
    from .retained_review import retry_imports
    from .workflow_controls import locked_workflow
    from apps.core.client_build import current_browser

    if not current_browser(request):
        raise ApiProblem("平台已更新，请刷新后重试入库", 409)
    value = body(request, ["planHash"])
    with transaction.atomic():
        get_object_or_404(AgentWorkflow.objects, pk=workflow_id, owner=request.user)
        workflow = locked_workflow(workflow_id)
        policy = require_access(request.user, "agent", workflow.model)
        retry_imports(workflow, request.user, policy, value.get("planHash"))
    return JsonResponse(workflow_json(workflow, view="card"))
