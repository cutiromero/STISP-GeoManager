"""Conversation-owned generic geology intake and explicit stage answers."""

from __future__ import annotations

import re
from types import SimpleNamespace

from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.models import F

from apps.compute.packages import ComputeError
from apps.compute.project_tools import GEOLOGY_PROJECT_CODES
from apps.projects.models import Project

from .geology_generic import LABELS, MINERALS
from .models import AgentRun
from .workflow import _state_hash
from .workflow_uploads import batch_uploads, checked_batch, require_upload_access


def validate_batch(user, conversation, batch_id, *, run=None):
    batch_id = checked_batch(batch_id)
    if (
        conversation.mode != "agent"
        or not Project.objects.filter(
            pk=conversation.project_tag_id, code__in=GEOLOGY_PROJECT_CODES
        ).exists()
    ):
        raise ComputeError("请在逻辑推理项目的智能体对话上传资料")
    require_upload_access(user, conversation.project_tag_id)
    uploads = list(batch_uploads(user, batch_id).order_by("created_at", "id"))
    if not uploads or any(
        item.project_tag_id != conversation.project_tag_id
        or (
            item.workflow_id
            and (run is None or item.workflow_id != run.research_workflow_id)
        )
        for item in uploads
    ):
        raise ComputeError("上传批次不存在或已用于其他任务", 409)
    claimed = AgentRun._base_manager.filter(
        owner=user, research_intent___uploadBatchId=batch_id
    )
    if run:
        claimed = claimed.exclude(pk=run.pk)
    if claimed.exists():
        raise ComputeError("该上传批次已关联其他对话研究任务", 409)
    return uploads


def prepare(run, user, policy, guard, *, on_thinking=None):
    from .research_intents import _save
    from .workflow_roles import compatible, recognize_roles

    batch_id = run.research_intent["_uploadBatchId"]
    uploads = validate_batch(user, run.conversation, batch_id, run=run)
    if not policy.get("workflowEnabled", True) or not policy.get("operatorEnabled"):
        raise PermissionDenied("MH-workflow或智能体算法调用已关闭")
    from .logic_configuration import matching_configuration

    reusable = matching_configuration(run, uploads)
    suggested = (
        {
            "items": [
                {
                    "resourceId": item.resource_id,
                    "role": next(
                        (
                            role
                            for role, identity in reusable["roles"].items()
                            if identity == item.resource_id
                        ),
                        None,
                    ),
                    "reason": "沿用上次已确认角色",
                }
                for item in uploads
            ]
        }
        if reusable
        else recognize_roles(
            user,
            run.project_tag_id,
            batch_id,
            run.model,
            source_run=run,
            on_thinking=on_thinking,
        )
    )
    suggestions = {item["resourceId"]: item for item in suggested["items"]}
    questions, answers = [], {}
    for index, upload in enumerate(uploads, 1):
        key = f"upload_{upload.resource_id}"
        suggestion = suggestions[upload.resource_id]
        answers[key] = suggestion["role"] or "skip"
        questions.append(
            {
                "key": key,
                "label": f"第{index}份：{upload.file_name}",
                "kind": "choice",
                "required": True,
                "options": [
                    {
                        "value": role,
                        "label": label,
                        **(
                            {"description": suggestion["reason"]}
                            if role == suggestion["role"]
                            else {}
                        ),
                    }
                    for role, label in LABELS.items()
                    if compatible(upload, role)
                ]
                + [{"value": "skip", "label": "不使用"}],
            }
        )
    intent = {
        "originRunId": run.id,
        "revision": "",
        "scenario": "geology_generic",
        "status": "clarifying",
        "goal": run.prompt,
        "message": "请核对资料角色，确认后继续。原始文件不变。",
        "questions": questions,
        "inputs": {},
        "parameters": {"roleAnswers": answers},
        "inputSummary": [],
        "workflowId": None,
        "_uploadBatchId": batch_id,
        "_reuseConfirmedConfiguration": bool(reusable),
        "_requestedReuse": run.research_intent.get("_requestedReuse", False),
    }
    intent["revision"] = _state_hash(intent)
    guard()
    _save(run, intent)
    if reusable:
        reused_answers = {
            f"upload_{item.resource_id}": next(
                (
                    role
                    for role, identity in reusable["roles"].items()
                    if identity == item.resource_id
                ),
                "skip",
            )
            for item in uploads
        }
        answer(run, user, policy, reused_answers, "")
        return "沿用上次已确认的角色和字段；本次计划与处置仍需确认。"
    return intent["message"]


def answer(source, user, policy, answers, text):
    from .demo_workflow import confirm_demo
    from .research_intents import _save

    intent = source.research_intent
    workflow = source.research_workflow
    if answers and text.strip():
        raise ComputeError("请分别提交角色选择或文字修改，避免含义冲突；尚未确认")
    if workflow:
        from .workflow import _authorize

        _authorize(workflow)
        if text.strip() == "修改角色和字段":
            if (
                not workflow.plan.get("reusedConfiguration")
                or workflow.status != "waiting_approval"
                or workflow.plan.get("phase") != "review_plan"
                or workflow.plan.get("chatExecution", {}).get("initialPlanAuthorized")
            ):
                raise ComputeError("仅在本次计划批准前可以重新核对角色和字段", 409)
            from .demo_workflow import _save as save_workflow
            from .models import WorkflowUpload

            workflow.status = "cancelled"
            workflow.cancel_requested = True
            workflow.detail = "用户重新核对角色和字段，原计划未执行"
            save_workflow(workflow)
            WorkflowUpload.objects.filter(workflow=workflow, owner=user).update(
                workflow=None
            )
            source.research_workflow = None
            _save(
                source,
                {
                    "_uploadBatchId": intent["_uploadBatchId"],
                    "_requestedReuse": intent.get("_requestedReuse", False),
                },
            )
            prepare(source, user, policy, lambda: None)
            return
        if answers:
            raise ComputeError("当前阶段请使用字段、计划或逐项批准卡片")
        if text.strip() in {
            "进度",
            "当前进度",
            "查看进度",
            "结果",
            "查看结果",
            "查看报告",
        }:
            return
        if workflow.status != "waiting_approval":
            raise ComputeError("任务正在运行或已结束，请查看当前进度", 409)
        phase = workflow.plan.get("phase")
        value = text.strip().rstrip("。！! ")
        if phase == "review_mapping" and value in {"确认字段", "确认字段含义"}:
            review = workflow.plan["fieldMappingReview"]
            mapping = {
                role["role"]: {
                    target["key"]: target.get("field") for target in role["targets"]
                }
                for role in review["roles"]
            }
            confirm_demo(
                workflow, user, policy, workflow.plan_hash, field_mapping=mapping
            )
        elif phase == "review_plan" and value in {
            "确认计划",
            "确认执行计划",
            "开始执行",
        }:
            confirm_demo(workflow, user, policy, workflow.plan_hash)
        elif phase == "review_modifications" and value == "只批准岩性类建议":
            suggestions = workflow.plan["modificationReview"]["suggestions"]
            selected = [
                item["id"]
                for item in suggestions
                if item.get("element") == "lithology"
                and item.get("status")
                not in {"exception", "review", "retained", "pending"}
            ]
            if not selected:
                raise ComputeError("当前没有可批准的岩性类建议，请使用逐项批准卡片")
            confirm_demo(
                workflow,
                user,
                policy,
                workflow.plan_hash,
                selected_suggestion_ids=selected,
            )
        else:
            raise ComputeError(
                "未能明确识别本阶段的确认要求，请使用对话中的确认卡片；尚未执行任何批准"
            )
        return
    questions = intent["questions"]
    role_answers = dict(intent["parameters"]["roleAnswers"])
    if answers:
        if set(answers) != {q["key"] for q in questions}:
            raise ComputeError("请核对所有资料角色后确认")
        role_answers = answers
    elif text.strip() in {"确认资料角色", "确认角色"}:
        pass
    else:
        matched = re.fullmatch(
            r"(?:把)?第([1-9]|1[0-2])份(?:资料)?改为(.+?)[。！!]?", text.strip()
        )
        names = {label: key for key, label in LABELS.items()}
        names.update({"不使用": "skip", "构造": "faults"})
        if not matched or int(matched[1]) > len(questions) or matched[2] not in names:
            raise ComputeError(
                "未能明确识别角色修改，请在卡片中核对后继续；尚未确认资料角色"
            )
        question = questions[int(matched[1]) - 1]
        role = names[matched[2]]
        if role not in {option["value"] for option in question["options"]}:
            raise ComputeError("资料类型或几何不符合此角色，请在卡片中选择")
        role_answers[question["key"]] = role
        intent["parameters"]["roleAnswers"] = role_answers
        intent["message"] = (
            "已更新角色建议，请核对后点击继续分析，或回复“确认资料角色”。"
        )
        intent["revision"] = _state_hash(
            {key: val for key, val in intent.items() if key != "revision"}
        )
        _save(source, intent)
        return
    inputs = {}
    for question in questions:
        role = role_answers.get(question["key"])
        if role not in {option["value"] for option in question["options"]}:
            raise ComputeError("请选择卡片中的有效角色")
        if role == "skip":
            continue
        if role in inputs:
            raise ComputeError("每种角色只能选择一份资料，请修改重复角色")
        inputs[role] = int(question["key"].removeprefix("upload_"))
    from .workflow_creation import create_workflow
    from .demo_workflow import _versions
    from .geology_multi import graph

    selection = {
        "algorithmSelectionMode": source.algorithm_selection_mode,
        "selectedAlgorithmVersionIds": source.algorithm_version_ids,
        **(
            {"algorithmVersionIds": source.algorithm_version_ids}
            if source.algorithm_selection_mode == "manual"
            else {}
        ),
    }
    segment = "all" if set(inputs) & {"faults", *MINERALS} else "lithology"
    versions = _versions(
        SimpleNamespace(plan={"chatExecution": selection}), graph(segment)
    )
    selection.update(
        algorithmVersionIds=[value["versionId"] for value in versions.values()],
        algorithmSnapshots={
            key: {"versionId": val["versionId"], "checksum": val["checksum"]}
            for key, val in versions.items()
        },
    )

    with transaction.atomic():
        if connection.vendor == "sqlite":
            AgentRun._base_manager.filter(pk=source.pk).update(
                idempotency_key=F("idempotency_key")
            )
        workflow = create_workflow(
            user,
            source.project_tag_id,
            {
                "workflowType": "geology_generic",
                "goal": intent["goal"],
                "model": source.model,
                "uploadBatchId": intent["_uploadBatchId"],
                "inputs": inputs,
                "resourceIds": [],
                "parameters": {},
                "knowledgeSelection": {
                    "mode": source.knowledge_selection.get("mode", "auto"),
                    "domains": source.knowledge_selection.get("domains", []),
                },
                "idempotencyKey": f"chat-research-{source.id}",
                "executeOperators": False,
                "importResults": True,
            },
            chat_execution={
                "originRunId": source.id,
                "requestRunId": source.id,
                "initialPlanAuthorized": False,
                **selection,
            },
        )
        intent.update(
            status="planning", inputs=inputs, questions=[], workflowId=str(workflow.id)
        )
        intent["parameters"] = {}
        intent["message"] = "资料角色已确认，正在判断字段含义；请等待字段确认卡片。"
        _save(source, intent, workflow)
    if intent.get("_reuseConfirmedConfiguration"):
        from .logic_configuration import matching_configuration

        uploads = validate_batch(
            user, source.conversation, intent["_uploadBatchId"], run=source
        )
        reusable = matching_configuration(source, uploads)
        if reusable:
            workflow.plan["reusedFieldMapping"] = reusable["fieldMapping"]
            workflow.save(update_fields=["plan", "updated_at"])
