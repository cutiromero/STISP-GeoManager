"""Durable chat-to-research bridge; calculations remain real workflow records."""

from __future__ import annotations

import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from .models import AgentRun, AgentWorkflow
from .policy import require_access
from .research_parser import interpret, plausible, validate
from .tools import resolve_resource
from .workflow import _authorize, _state_hash

PUBLIC_KEYS = (
    "originRunId",
    "revision",
    "scenario",
    "status",
    "goal",
    "message",
    "questions",
    "inputs",
    "parameters",
    "inputSummary",
    "workflowId",
)


def history_compatible(previous, current) -> bool:
    intent = previous.research_intent or {}
    if not intent.get("originRunId"):
        return True
    if current.resource_ids and not set(intent.get("inputs", {}).values()) <= set(
        current.resource_ids
    ):
        return False
    workflow = previous.research_workflow
    if workflow:
        if current.algorithm_selection_mode == "manual" and not {
            a["versionId"] for a in workflow.plan.get("algorithms", {}).values()
        } <= set(current.algorithm_version_ids):
            return False
        mode = current.knowledge_selection.get("mode", "auto")
        if mode == "none" and workflow.evidence:
            return False
        if mode == "manual" and not {
            item.get("domain") for item in workflow.evidence
        } <= set(current.knowledge_selection.get("domains", [])):
            return False
        if mode == "auto":
            from .selections import knowledge_domains

            if not {item.get("domain") for item in workflow.evidence} <= set(
                knowledge_domains(current)
            ):
                return False
    return True


def previous_run(run):
    identity = run.research_intent.get("_resumeSourceRunId")
    rows = (
        run.conversation.runs.filter(
            owner_id=run.owner_id,
            project_tag_id=run.project_tag_id,
            id__lt=run.id,
        )
        .exclude(research_intent={})
        .order_by("-id")
    )
    if identity:
        rows = rows.filter(pk=identity)
    return next((r for r in rows if r.research_intent.get("originRunId")), None)


def _auto_continuation_selection(previous, current):
    if (
        (current.knowledge_selection or {}).get("mode", "auto") != "auto"
        or previous.owner_id != current.owner_id
        or previous.project_tag_id != current.project_tag_id
        or previous.conversation_id != current.conversation_id
    ):
        return None
    intent = previous.research_intent
    if (
        intent.get("status") != "clarifying"
        and current.research_intent.get("_resumeSourceRunId") != previous.id
        and not re.search(
            r"接着|继续|补充|新增|更新|新证据|进度|跑完|完成|结果|报告|地图|确认|同意|取消|停止",
            current.prompt,
        )
    ):
        return None
    from apps.knowledge.domains import query_domains, validate_domains

    workflow = previous.research_workflow
    if workflow:
        from .demo_workflow import _domains

        inherited = set(_domains(workflow)) | {
            e["domain"] for e in workflow.evidence if e.get("domain")
        }
    else:
        inherited = set(query_domains(intent.get("goal", "") + " " + previous.prompt))
    topic = set(query_domains(current.prompt))
    if not inherited or (topic and not topic.intersection(inherited)):
        return None
    return {
        **current.knowledge_selection,
        "_resolvedDomains": validate_domains(sorted(inherited | topic)),
        "_researchSourceRunId": previous.id,
    }


def authorize_run(run, user, policy) -> None:
    intent = run.research_intent or {}
    if not intent.get("originRunId"):
        return
    if run.owner_id != user.id:
        raise PermissionDenied("科研对话不属于当前用户")
    require_access(user, "agent", run.model)
    for role, identity in intent.get("inputs", {}).items():
        resource = resolve_resource(user, policy, identity)
        revision = intent.get("_inputRevisions", {}).get(role)
        if resource.status != "active" or (
            revision and resource.updated_at.isoformat() != revision
        ):
            raise PermissionDenied("科研资料已变化或不可用，请重新解析任务")
    if run.research_workflow_id:
        workflow = AgentWorkflow.objects.filter(
            pk=run.research_workflow_id,
            owner_id=run.owner_id,
            project_tag_id=run.project_tag_id,
        ).first()
        if workflow is None:
            raise PermissionDenied("科研流程不属于当前会话项目")
        _authorize(workflow)
        if workflow.plan.get("scenarioVersion"):
            from .demo_workflow import authorize_demo

            authorize_demo(workflow, user, policy)


def serialize(run, user, policy):
    if not run.research_intent.get("originRunId"):
        return None
    authorize_run(run, user, policy)
    data = {key: run.research_intent[key] for key in PUBLIC_KEYS}
    if run.research_workflow_id:
        workflow = AgentWorkflow.objects.get(pk=run.research_workflow_id)
        data.update(
            workflowId=str(workflow.id),
            status={
                "queued": "planning",
                "waiting_compute": "running",
                "paused": "running",
                "interrupted": "failed",
            }.get(workflow.status, workflow.status),
            message=workflow.detail,
            revision=_state_hash(
                {
                    "intent": data["revision"],
                    "workflow": workflow.plan_hash,
                    "status": workflow.status,
                }
            ),
            questions=[],
        )
    return data


def _save(run, value, workflow=None):
    frozen = run.research_intent.get("_initialExecutionAuthorization")
    if frozen and "_initialExecutionAuthorization" not in value:
        value = {**value, "_initialExecutionAuthorization": frozen}
    run.research_intent = value
    if workflow is not None:
        run.research_workflow = workflow
    AgentRun.objects.filter(pk=run.pk).update(
        research_intent=value,
        research_workflow_id=run.research_workflow_id,
        updated_at=timezone.now(),
    )
    origin_id = value.get("originRunId")
    if origin_id and origin_id != run.pk:
        origin = AgentRun.objects.filter(
            pk=origin_id,
            owner_id=run.owner_id,
            conversation_id=run.conversation_id,
        ).first()
        if origin:
            merged = {
                **value,
                "_answerReceipts": origin.research_intent.get("_answerReceipts", []),
                **(
                    {
                        "_initialExecutionAuthorization": origin.research_intent[
                            "_initialExecutionAuthorization"
                        ]
                    }
                    if origin.research_intent.get("_initialExecutionAuthorization")
                    else {}
                ),
            }
            AgentRun.objects.filter(pk=origin.pk).update(
                research_intent=merged,
                research_workflow_id=run.research_workflow_id,
                updated_at=timezone.now(),
            )


def _workflow_summary(workflow):
    if workflow is None:
        return None
    final = workflow.plan.get("finalDecision")
    return {
        "scenario": workflow.workflow_type,
        "status": workflow.status,
        "phase": workflow.plan.get("phase"),
        "detail": workflow.detail,
        "operatorSteps": workflow.operator_steps,
        "resultCount": len(workflow.result_resource_ids),
        "finalDecision": final,
        "inputs": workflow.plan.get("inputs", {}),
        "parameters": workflow.parameters,
    }


def _execution_requested(run, previous) -> bool:
    if re.search(
        r"(?:不要|先不).{0,6}(?:执行|运行|计算|开始)|不执行|只是咨询|取消(?:任务|执行)?|停止(?:任务|执行|计算)?",
        run.prompt,
    ):
        return False
    if previous and previous.research_intent.get("_executionAuthorized"):
        return True
    return bool(
        re.search(
            r"分析|评估|检查|纠偏|纠正|修正|修复|执行|演示|开始|运行|请做|帮我|完成",
            run.prompt,
        )
    )


def process(run, user, policy, guard, event):
    previous = previous_run(run)
    selection_before = run.knowledge_selection
    if previous:
        continuation_selection = _auto_continuation_selection(previous, run)
        if continuation_selection:
            run.knowledge_selection = continuation_selection
    if previous and not history_compatible(previous, run):
        previous = None
        run.knowledge_selection = selection_before
    if not plausible(run, previous):
        return None
    if not policy.get("workflowEnabled", True) or not policy.get(
        "operatorEnabled", False
    ):
        raise PermissionDenied("科研工作流或智能体算法调用已关闭")
    if run.research_intent.get("originRunId") and run.research_workflow_id:
        return serialize(run, user, policy)["message"]
    workflow = None
    if previous:
        authorize_run(previous, user, policy)
        workflow = previous.research_workflow
        if run.knowledge_selection != selection_before:
            guard()
            AgentRun.objects.filter(pk=run.pk).update(
                knowledge_selection=run.knowledge_selection
            )
    from .research_presets import discover

    catalog = discover(user, policy, run=run)
    if not catalog["scenarios"]:
        raise ValidationError("当前项目尚未准备对应场景资料与已发布算法")
    prior = serialize(previous, user, policy) if previous else None

    # Persist the bounded request before networking; internal thinking is omitted.
    def on_request(audit):
        _save(run, {**run.research_intent, "_parserAudit": audit})

    def checked_value(value):
        if (
            isinstance(value, dict)
            and previous
            and previous.research_intent.get("status") == "clarifying"
            and value.get("scenario") == previous.research_intent.get("scenario")
            and isinstance(value.get("action"), str)
            and value.get("action") in {"start", "clarify"}
            and isinstance(value.get("inputs", {}), dict)
            and isinstance(value.get("parameters", {}), dict)
        ):
            # A clarification amends a saved plan instead of erasing known fields.
            value = {
                **value,
                "inputs": {
                    **previous.research_intent["inputs"],
                    **value.get("inputs", {}),
                },
                "parameters": {
                    **previous.research_intent["parameters"],
                    **value.get("parameters", {}),
                },
            }
        return validate(value, catalog, run)

    value, audit = interpret(
        run,
        user,
        policy,
        catalog,
        prior,
        _workflow_summary(workflow),
        guard,
        event,
        on_request,
        validator=checked_value,
    )
    on_request(audit)
    if not audit.get("attempts") or audit["attempts"][-1].get("status") != "accepted":
        value = checked_value(value)
    if value["action"] == "ordinary":
        if run.knowledge_selection != selection_before:
            run.knowledge_selection = selection_before
            AgentRun.objects.filter(pk=run.pk).update(
                knowledge_selection=run.knowledge_selection
            )
        return None
    scene = next(s for s in catalog["scenarios"] if s["scenario"] == value["scenario"])
    if value["action"] in {"status", "update"} and (
        workflow is None or workflow.workflow_type != value["scenario"]
    ):
        raise ValidationError("本会话没有可查询或更新的对应科研任务")
    if value["action"] == "update" and (
        workflow.workflow_type != "ecology_investigation"
        or workflow.status != "succeeded"
    ):
        raise ValidationError("请等本会话生态分析完成后再补充证据")
    if value["action"] == "status":
        value["inputs"], value["parameters"] = (
            dict(workflow.plan["inputs"]),
            dict(workflow.parameters),
        )
    input_summary, revisions = [], {}
    for role, identity in value["inputs"].items():
        resource = resolve_resource(user, policy, identity, run.resource_ids)
        if resource.status != "active":
            raise PermissionDenied("所选科研资料已停用")
        revisions[role] = resource.updated_at.isoformat()
        input_summary.append(
            {
                "role": role,
                "label": scene.get("roleLabels", {}).get(role, role),
                "resourceId": identity,
                "name": resource.name,
                "sourceNote": next(
                    (
                        i.get("sourceNote", "")
                        for i in scene["inputs"][role]
                        if i["id"] == identity
                    ),
                    "",
                ),
            }
        )
    authorized = _execution_requested(run, previous)
    intent = {
        "originRunId": previous.research_intent["originRunId"]
        if previous
        and (
            value["action"] == "status"
            or previous.research_intent.get("status") == "clarifying"
        )
        and value["action"] != "update"
        else run.id,
        "revision": "",
        "scenario": value["scenario"],
        "status": "clarifying" if value["action"] == "clarify" else "planning",
        "goal": value["goal"].strip(),
        "message": value["message"].strip(),
        "questions": value["questions"],
        "inputs": value["inputs"],
        "parameters": value["parameters"],
        "inputSummary": input_summary,
        "workflowId": None,
        "_inputRevisions": revisions,
        "_executionAuthorized": authorized,
        "_parserAudit": audit,
        "_demoScenario": run.research_intent.get("_demoScenario"),
    }
    intent["revision"] = _state_hash(
        {k: v for k, v in intent.items() if k != "revision"}
    )
    guard()
    if value["action"] == "status":
        intent["workflowId"] = str(workflow.id)
        _save(run, intent, workflow)
        return _status_text(workflow)
    if value["action"] == "clarify":
        _save(run, intent)
        return intent["message"]
    if not authorized:
        intent["status"] = "clarifying"
        intent["questions"] = [
            {
                "key": "execution",
                "label": "是否按以上目标开始分析？",
                "kind": "choice",
                "required": True,
                "options": [{"value": "开始执行", "label": "开始执行"}],
            }
        ]
        _save(run, intent)
        return intent["message"]
    if not scene.get("available", True):
        raise ValidationError("当前场景资料或算法尚未就绪")
    request = {
        "workflowType": value["scenario"],
        "goal": intent["goal"],
        "model": run.model,
        "resourceIds": sorted(set(value["inputs"].values())),
        "inputs": value["inputs"],
        "parameters": value["parameters"],
        "knowledgeSelection": {
            "mode": run.knowledge_selection.get("mode", "auto"),
            "domains": run.knowledge_selection.get("domains", []),
        },
        "idempotencyKey": "chat-research-" + str(intent["originRunId"]),
        "executeOperators": False,
        "importResults": True,
        **(
            {"previousWorkflowId": str(workflow.id)}
            if value["action"] == "update"
            else {}
        ),
    }
    chat_execution = {
        "originRunId": intent["originRunId"],
        "requestRunId": run.id,
        "revision": intent["revision"],
        "initialPlanAuthorized": True,
        "algorithmVersionIds": [a["versionId"] for a in scene["algorithms"]],
        "algorithmSnapshots": {
            a.get("identifier", str(a["versionId"])): {
                "versionId": a["versionId"],
                "checksum": a.get("checksum"),
            }
            for a in scene["algorithms"]
            if a.get("checksum")
        },
        "algorithmSelectionMode": run.algorithm_selection_mode,
        "selectedAlgorithmVersionIds": run.algorithm_version_ids,
    }
    intent["_initialExecutionAuthorization"] = {
        "revision": intent["revision"],
        "originRunId": intent["originRunId"],
        "requestRunId": run.id,
    }
    from .workflow_creation import create_workflow

    with transaction.atomic():
        if connection.vendor == "sqlite":
            # This outer transaction must own the writer before create_workflow
            # rechecks permissions; a nested atomic block is only a savepoint.
            AgentRun._base_manager.filter(pk=run.pk).update(
                idempotency_key=F("idempotency_key")
            )
        created = create_workflow(
            user, run.project_tag_id, request, chat_execution=chat_execution
        )
        if run.knowledge_selection.get("mode", "auto") == "auto":
            from .demo_workflow import _domains

            run.knowledge_selection = {
                **run.knowledge_selection,
                "_resolvedDomains": _domains(created),
            }
            AgentRun.objects.filter(pk=run.pk).update(
                knowledge_selection=run.knowledge_selection
            )
        intent["workflowId"] = str(created.id)
        _save(run, intent, created)
    return (
        intent["message"]
        + "\n\n已开始匹配资料和算法，下面将持续显示实际判断与计算进度。"
    )


def _status_text(workflow) -> str:
    if workflow.status != "succeeded":
        return workflow.detail + "。下方任务记录会继续更新真实进度。"
    decision = workflow.plan.get("finalDecision", {})
    lines = [decision.get("judgement") or workflow.detail]
    findings = decision.get("findings", [])
    if findings:
        lines.append("\n".join("- " + str(f) for f in findings))
    if decision.get("uncertainties"):
        lines.append("需要继续核实：" + "；".join(decision["uncertainties"]))
    lines.append("成果与报告已保存在此任务记录，可点击下方地图成果在地理工作台查看。")
    return "\n\n".join(lines)
