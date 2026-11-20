"""Explicit human review of held evidence, retaining previous calculation rounds."""

from copy import deepcopy
import json
import math

from django.core.exceptions import PermissionDenied

from apps.compute.packages import ComputeError
from apps.knowledge.trial_rules import digest
from .workflow_task_summary import full_rows, output


def _edited_pairs(plan, *, require_complete):
    apply = next((s for s in plan.get("stages", []) if s.get("name") == "apply"), {})
    if not apply.get("taskId"):
        return set()
    results = [r for r in apply.get("results", []) if r.get("key") == "changes"]
    if (
        len(results) != 1
        or results[0].get("scope") != "all"
        or results[0].get("rowCount") != len(results[0].get("rows", []))
    ):
        if require_complete:
            raise ComputeError("实际处置范围不完整，请先完成或核对计算结果", 409)
        return set()
    return {
        (str(row.get("feature_id")), str(row.get("rule_id")))
        for row in results[0]["rows"]
        if str(row.get("actual_changed")).lower() in {"true", "1", "1.0"}
    }


def _held_suggestions(plan, edited):
    review = plan.get("modificationReview") or {}
    identities = plan.get("retainedReview", {}).get("retainedSuggestionIds")
    scope = None if identities is None else set(identities)
    return [
        item
        for item in review.get("suggestions", [])
        if (scope is None or item["id"] in scope)
        and item.get("status") in {"review", "exception"}
        and (str(item.get("featureId")), str(item.get("ruleId"))) not in edited
    ]


def held_suggestions(plan):
    return _held_suggestions(plan, _edited_pairs(plan, require_complete=True))


def _json_record(value):
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def inspection_held_suggestions(plan):
    """Include located findings that never had an executable candidate.

    These rows are strictly for inspection. Keep the frozen approval hash, IDs,
    candidate actions and applied results unchanged, including while apply runs.
    """
    edited = _edited_pairs(plan, require_complete=False)
    held = _held_suggestions(plan, edited)
    apply = next((s for s in plan.get("stages", []) if s.get("name") == "apply"), {})
    if apply.get("unifiedIssueReview") is True:
        reviewed = {
            (str(row["feature_id"]), str(row["rule_id"]))
            for row in full_rows(output(apply, "changes")) or []
            if row.get("action") == "review"
            and row.get("feature_id")
            and row.get("rule_id")
            and str(row.get("actual_changed")).lower() in {"false", "0", "0.0"}
        }
        return [
            {**item, "suggestedState": "已复核，未修改"}
            if (str(item["featureId"]), str(item["ruleId"])) in reviewed
            else item
            for item in held
        ]
    # Keep prior frozen plans readable without creating new authorization IDs.
    review_scope = plan.get("retainedReview") or {}
    allowed = (
        set(review_scope["retainedSuggestionIds"])
        if review_scope.get("active") and "retainedSuggestionIds" in review_scope
        else None
    )
    seen = {(str(item["featureId"]), str(item["ruleId"])) for item in held} | edited
    check = next((s for s in plan.get("stages", []) if s.get("name") == "check"), {})
    for row in full_rows(output(check, "issues")) or []:
        feature = str(row.get("feature_id") or "")
        rule = str(row.get("rule_id") or "")
        identity = (feature, rule)
        if (
            row.get("status") not in {"review", "exception"}
            or not (feature and rule and row.get("issue_id"))
            or identity in seen
        ):
            continue
        identity_id = digest({"inspectionIssue": row["issue_id"]})[:24]
        if allowed is not None and identity_id not in allowed:
            continue
        measurements = _json_record(row.get("measurements_json"))
        try:
            area = float(row.get("area_m2") or measurements.get("area_m2") or 0)
        except (TypeError, ValueError, OverflowError):
            area = 0
        reason = str(row.get("reason") or "证据不足，保留核查。")
        held.append(
            {
                "id": identity_id,
                "kind": "multi_element",
                "element": row.get("element"),
                "featureId": feature,
                "ruleId": rule,
                "title": reason[:100],
                "currentState": row.get("current_state") or "当前识别结果",
                "suggestedState": "保留核查",
                "reason": reason,
                "action": "keep",
                "status": row["status"],
                "areaM2": area if math.isfinite(area) else 0,
                "observations": measurements,
                "knowledgeRefs": [],
                "preview": row.get("geometry_json"),
            }
        )
        seen.add(identity)
    return held


def open_initial_review(workflow, stage, automatic_ids):
    held = held_suggestions(workflow.plan)
    if not held:
        return False
    workflow.plan["retainedReview"] = {
        "automaticSuggestionIds": automatic_ids,
        "candidateIds": [item["id"] for item in held if item.get("candidateAction")],
        "retainedSuggestionIds": [item["id"] for item in held],
        "kind": "initial",
        "active": True,
    }
    workflow.plan.update(phase="review_modifications", reviewOutputs=[])
    workflow.status, workflow.current_step = "waiting_approval", "review_modifications"
    workflow.detail = (
        f"请确认{len(held)}项待核查疑点；确认后执行所选疑点的处理和{len(automatic_ids)}项已授权处置。"
        "未选疑点保持原样。"
    )
    stage["status"] = "needs_review"
    return True


def merge_selection(workflow, user, policy, selected):
    state = workflow.plan.get("retainedReview") or {}
    if not state.get("active"):
        return selected, {}
    from .rule_dispositions import automatic_authorized

    if state.get("kind") == "initial" and not automatic_authorized(
        workflow, user, policy
    ):
        raise PermissionDenied("本次自动处置授权已失效")
    candidates = set(state["candidateIds"])
    if set(selected) - candidates:
        raise ComputeError("只能选择本次冻结的待核查疑点", 409)
    automatic = state["automaticSuggestionIds"]
    if set(automatic) & candidates:
        raise ComputeError("自动处置与人工候选范围冲突", 409)
    return list(dict.fromkeys([*automatic, *selected])), {
        "mode": "reviewed_rules",
        "automaticSuggestionIds": automatic,
        "manualSuggestionIds": selected,
        "retainedReviewKind": state["kind"],
        "acknowledgedRetainedCount": len(state.get("retainedSuggestionIds", [])),
        "automaticAlterationActions": state.get("automaticAlterationActions", {}),
    }


def reopen(workflow, user, policy, expected):
    from .demo_workflow import authorize_demo, _save
    from .geology_multi_review import _fresh
    from .workflow import _authorize, _state_hash, checkpoint, step

    if workflow.owner_id != user.id or workflow.workflow_type not in {
        "geology_generic",
        "geology_multi_element_reasoning",
    }:
        raise PermissionDenied("只能核查本人的综合地质任务")
    if (
        workflow.plan.get("retainedReview", {}).get("active")
        and workflow.status == "waiting_approval"
        and expected == workflow.plan_hash
    ):
        return
    if (
        workflow.status != "succeeded"
        or expected != workflow.plan_hash
        or _state_hash(workflow.plan) != expected
    ):
        raise ComputeError("任务状态或计划已变化，请重新读取后核查", 409)
    fresh, policy = _authorize(workflow)
    authorize_demo(workflow, fresh, policy)
    stages = workflow.plan["stages"]
    index = next(i for i, stage in enumerate(stages) if stage.get("name") == "apply")
    apply = stages[index]
    review, _ = _fresh(workflow, fresh, policy, apply)
    candidates = held_suggestions(workflow.plan)
    candidate_ids = [item["id"] for item in candidates if item.get("candidateAction")]
    if not candidate_ids:
        raise ComputeError("当前没有可选择处置的保留对象", 409)
    changes = next(item for item in apply["results"] if item["key"] == "changes")
    changed = {
        (str(row.get("feature_id")), str(row.get("rule_id")), str(row.get("action")))
        for row in changes["rows"]
        if str(row.get("actual_changed")).lower() in {"true", "1", "1.0"}
    }
    approved = set(workflow.plan["modificationReview"].get("approvedSuggestionIds", []))
    prior_actions = apply.get("modificationsApproval", {}).get("alterationActions", {})
    automatic_ids = [
        item["id"]
        for item in review["suggestions"]
        if item["id"] in approved
        and (
            str(item.get("featureId")),
            str(item.get("ruleId")),
            str(prior_actions.get(item.get("featureId"), item.get("action"))),
        )
        in changed
    ]
    history = workflow.plan.setdefault("retainedReviewHistory", [])
    if len(history) >= 8:
        raise ComputeError("已保存8轮核查，请另建任务继续分析", 409)
    previous = {
        "planHash": expected,
        "stages": deepcopy(stages),
        "modificationReview": deepcopy(workflow.plan["modificationReview"]),
        "resultResourceIds": list(workflow.result_resource_ids),
        "resultIds": list(workflow.result_ids),
        "finalDecision": deepcopy(workflow.plan.get("finalDecision")),
        "reportInterpretationRevision": workflow.plan.get(
            "reportInterpretationRevision"
        ),
    }
    history.append(previous)
    if (
        workflow.operator_steps
        + sum(
            s.get("identifier") not in {"finish", "search_expert_knowledge"}
            for s in stages[index:]
        )
        > workflow.max_operator_steps
    ):
        raise ComputeError("剩余算子额度不足以完成核查，请另建任务", 409)
    keep = {"name", "identifier", "bindings", "parameters"}
    for i in range(index, len(stages)):
        old = stages[i]
        stages[i] = {
            key: value
            for key, value in old.items()
            if key in keep
            or i == index
            and key
            in {
                "decision",
                "edits",
                "proposedEdits",
                "executionMode",
                "ruleDispositionSummary",
                "unifiedIssueReview",
            }
        }
        stages[i]["status"] = "needs_review" if i == index else "pending"
    workflow.plan.pop("finalDecision", None)
    workflow.plan.pop("reportInterpretationRevision", None)
    workflow.plan.pop("model_changes", None)
    workflow.plan.pop("finalStage", None)
    workflow.plan.update(
        stageIndex=index,
        phase="review_modifications",
        reviewOutputs=[],
        retainedReview={
            "active": True,
            "kind": "followup",
            "automaticSuggestionIds": automatic_ids,
            "candidateIds": candidate_ids,
            "retainedSuggestionIds": [item["id"] for item in candidates],
            "sourcePlanHash": expected,
            "automaticAlterationActions": {
                feature: action
                for feature, action in prior_actions.items()
                if any(
                    item["featureId"] == feature and item["id"] in automatic_ids
                    for item in review["suggestions"]
                )
            },
        },
    )
    workflow.plan["modificationReview"]["approvedSuggestionIds"] = []
    workflow.status, workflow.current_step = "waiting_approval", "review_modifications"
    workflow.detail = f"请选择{len(candidates)}项待核查疑点中的处理范围；原成果已保存，确认后生成新一轮处置与复查"
    step(
        workflow,
        "retained_review_opened",
        message=workflow.detail,
        action={
            "sourcePlanHash": expected,
            "candidateIds": candidate_ids,
            "previousRound": len(history),
        },
    )
    checkpoint(workflow, "retained_review_opened", {"sourcePlanHash": expected})
    _save(workflow)


def retry_imports(workflow, user, policy, expected):
    from .workflow import _authorize, _state_hash, step
    from .demo_workflow import authorize_demo, _save, result_import_name
    from .compute_tools import authorized_task
    from .workflow_slots import require_compute_slot
    from apps.compute.models import ComputeImport
    from apps.compute.services import request_output_import
    from apps.catalog.models import DataResource, MapLayer

    if (
        workflow.cancel_requested
        or workflow.pause_requested
        or workflow.status != "failed"
        or workflow.plan.get("phase") != "waiting_compute"
        or workflow.plan_hash != expected
        or _state_hash(workflow.plan) != expected
    ):
        raise ComputeError("当前任务不是可恢复的入库失败状态，请重新读取", 409)
    fresh, policy = _authorize(workflow)
    authorize_demo(workflow, fresh, policy)
    stage = workflow.plan["stages"][workflow.plan["stageIndex"]]
    task = authorized_task(fresh, stage.get("taskId"), policy, workflow=workflow)
    records = list(
        ComputeImport.objects.filter(output__task=task).select_related(
            "output", "resource"
        )
    )
    if task.status != "succeeded" or not any(
        record.status == "failed" for record in records
    ):
        raise ComputeError("实际计算尚未完成或没有失败的入库记录", 409)
    if any(
        record.requested_by_id != user.id
        or record.request_source != f"workflow:{workflow.id}"
        for record in records
    ):
        raise PermissionDenied("入库记录不属于当前本人工作流")
    require_compute_slot(fresh, workflow.id)
    workflow.status = "waiting_compute"
    workflow.detail = "正在重试成果入库，复用已完成计算"
    _save(workflow)
    for record in records:
        name = result_import_name(workflow, stage, record.output)
        if record.status == "failed":
            request_output_import(
                fresh, record.output, name=name, request_source=record.request_source
            )
        elif (
            record.status == "ready"
            and record.resource_id
            and record.resource.name == record.name
        ):
            DataResource.objects.filter(pk=record.resource_id).update(name=name)
            MapLayer.objects.filter(
                data_resource_id=record.resource_id, name=record.name
            ).update(name=name)
            ComputeImport.objects.filter(pk=record.pk).update(name=name)
    step(
        workflow,
        "result_import_retry",
        message=workflow.detail,
        action={"taskId": str(task.id), "planHash": expected},
    )
