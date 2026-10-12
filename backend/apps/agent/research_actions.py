"""Chat answers re-enter the model; quality approval remains explicit and scoped."""

from __future__ import annotations

from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import AgentRun, AgentWorkflow, Conversation
from .policy import require_access, visible_models
from .research_intents import serialize
from .selections import knowledge_selection
from .workflow import _state_hash


def update(request, run_id, value):
    from .views import ApiProblem, run_json, submit_value

    if value.get("action") not in {"answer", "confirm", "cancel"} or not isinstance(
        value.get("revision"), str
    ):
        raise ApiProblem("科研交互动作或修订无效")
    answers, text = value.get("answers", {}), value.get("answer", "")
    if (
        not isinstance(answers, dict)
        or len(answers) > 8
        or any(
            not isinstance(k, str) or not isinstance(v, str) or len(v) > 12000
            for k, v in answers.items()
        )
        or not isinstance(text, str)
        or len(text) > 12000
    ):
        raise ApiProblem("科研问题答案无效")
    available_models = None
    if value["action"] == "answer":
        before = get_object_or_404(AgentRun.objects, pk=run_id, owner=request.user)
        digest = _state_hash(value)
        if not any(
            r["digest"] == digest
            for r in before.research_intent.get("_answerReceipts", [])
        ):
            preflight_policy = require_access(request.user, "agent", before.model)
            available_models = visible_models(request.user, "agent", preflight_policy)
    with transaction.atomic():
        # Reserve SQLite writer before reading the row/revision.
        AgentRun.objects.filter(pk=run_id, owner=request.user).update(
            idempotency_key=F("idempotency_key")
        )
        source = get_object_or_404(
            AgentRun.objects.select_for_update().select_related("conversation"),
            pk=run_id,
            owner=request.user,
        )
        p = require_access(request.user, "agent", source.model)
        data = serialize(source, request.user, p)
        if data is None:
            raise ApiProblem("此对话没有科研任务", 409)
        digest = _state_hash(value)
        receipts = source.research_intent.get("_answerReceipts", [])
        for receipt in receipts:
            if receipt["digest"] == digest:
                answered = get_object_or_404(
                    AgentRun.objects.select_related("conversation"),
                    pk=receipt["runId"],
                    owner=request.user,
                    conversation_id=source.conversation_id,
                )
                return JsonResponse(run_json(answered, request.user), status=202)
        if data["revision"] != value["revision"]:
            raise ApiProblem("科研问题或审核计划已变化，请刷新后操作", 409)
        if value["action"] == "answer":
            if data["status"] != "clarifying":
                raise ApiProblem("当前任务没有待回答问题", 409)
            questions = {q["key"]: q for q in data["questions"]}
            if set(answers) - set(questions):
                raise ApiProblem("答案不对应当前科研问题")
            for key, answer in answers.items():
                options = questions[key]["options"]
                if options and answer not in {o["value"] for o in options}:
                    raise ApiProblem("请选择当前问题提供的有效选项")
            if not text.strip() and not answers:
                raise ApiProblem("请回答问题或补充说明")
            parts = [
                f"{questions[key]['label']}：{answer}"
                for key, answer in answers.items()
            ]
            if text.strip():
                parts.append(text.strip())
            prompt = "\n".join(parts)
            run_value = {
                "model": source.model,
                "prompt": prompt,
                "idempotencyKey": "research-answer-" + digest[:48],
                "resourceIds": source.resource_ids,
                "thinkingMode": source.thinking_mode,
                **(
                    {"reasoningEffort": source.reasoning_effort}
                    if source.reasoning_effort
                    else {}
                ),
                "budgetProfile": source.budget_profile,
                "knowledgeSelection": knowledge_selection(source),
                "algorithmSelectionMode": source.algorithm_selection_mode,
                "algorithmVersionIds": source.algorithm_version_ids,
                "dataSelectionMode": source.data_selection_mode,
                **(
                    {"demoScenario": source.research_intent["_demoScenario"]}
                    if source.research_intent.get("_demoScenario")
                    else {}
                ),
            }
            response = submit_value(
                request,
                source.conversation,
                run_value,
                available_models=available_models,
            )
            created = AgentRun.objects.get(
                conversation=source.conversation,
                idempotency_key=run_value["idempotencyKey"],
            )
            created.research_intent = {
                **created.research_intent,
                "_resumeSourceRunId": source.id,
            }
            created.save(update_fields=["research_intent", "updated_at"])
            source.research_intent["_answerReceipts"] = [
                *receipts,
                {"digest": digest, "runId": created.id},
            ][-20:]
            source.save(update_fields=["research_intent", "updated_at"])
            return response
        if answers or text:
            raise ApiProblem("审核或取消操作不接受问题答案")
        if value["action"] == "confirm":
            if not source.research_workflow_id:
                raise ApiProblem("任务尚未生成可审核计划", 409)
            from .demo_workflow import confirm_demo

            workflow = AgentWorkflow.objects.select_for_update().get(
                pk=source.research_workflow_id, owner=request.user
            )
            confirm_demo(workflow, request.user, p, workflow.plan_hash)
        else:
            if source.research_workflow_id:
                workflow = AgentWorkflow.objects.select_for_update().get(
                    pk=source.research_workflow_id, owner=request.user
                )
                workflow.cancel_requested = True
                if workflow.status in {"queued", "waiting_approval", "paused"}:
                    workflow.status, workflow.detail = "cancelled", "用户已取消科研任务"
                    workflow.pause_requested = False
                workflow.save(
                    update_fields=[
                        "cancel_requested",
                        "pause_requested",
                        "status",
                        "detail",
                        "updated_at",
                    ]
                )
            source.research_intent.update(
                status="cancelled", message="用户已取消科研任务", questions=[]
            )
            source.save(update_fields=["research_intent", "updated_at"])
            Conversation.objects.filter(pk=source.conversation_id).update(
                updated_at=timezone.now()
            )
        source.refresh_from_db()
        return JsonResponse(run_json(source, request.user))
