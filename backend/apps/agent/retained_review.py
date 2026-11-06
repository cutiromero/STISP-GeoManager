"""Explicit human review of held evidence, retaining previous calculation rounds."""

from copy import deepcopy
from django.core.exceptions import PermissionDenied
from apps.compute.packages import ComputeError


def held_suggestions(plan):
    review = plan.get("modificationReview") or {}
    stages = plan.get("stages", [])
    apply = next((stage for stage in stages if stage.get("name") == "apply"), {})
    results = [r for r in apply.get("results", []) if r.get("key") == "changes"]
    edited = set()
    if apply.get("taskId"):
        if (
            len(results) != 1
            or results[0].get("scope") != "all"
            or results[0].get("rowCount") != len(results[0].get("rows", []))
        ):
            raise ComputeError("实际处置范围不完整，请先完成或核对计算结果", 409)
        edited = {
            (str(row.get("feature_id")), str(row.get("rule_id")))
            for row in results[0]["rows"]
            if str(row.get("actual_changed")).lower() in {"true", "1", "1.0"}
        }
    scope = plan.get("retainedReview", {}).get("retainedSuggestionIds")
    return [
        item
        for item in review.get("suggestions", [])
        if (scope is None or item["id"] in scope)
        and item.get("status") in {"review", "exception"}
        and (str(item.get("featureId")), str(item.get("ruleId"))) not in edited
    ]


def open_initial_review(workflow, stage, automatic_ids):
    candidates = held_suggestions(workflow.plan)
    if not candidates:
        return False
    workflow.plan["retainedReview"] = {
        "automaticSuggestionIds": automatic_ids,
        "candidateIds": [
            item["id"] for item in candidates if item.get("candidateAction")
        ],
        "retainedSuggestionIds": [item["id"] for item in candidates],
        "kind": "initial",
        "active": True,
    }
    workflow.plan.update(phase="review_modifications", reviewOutputs=[])
    workflow.status, workflow.current_step = "waiting_approval", "review_modifications"
    workflow.detail = f"{len(automatic_ids)}项规则处置按原授权执行；请核查{len(candidates)}条待裁定与例外，未选对象保留"
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
        raise ComputeError("只能选择本次保留对象的明确候选处置", 409)
    automatic = state["automaticSuggestionIds"]
    if set(automatic) & candidates:
        raise ComputeError("自动处置与人工候选范围冲突", 409)
    return list(dict.fromkeys([*automatic, *selected])), {
        "mode": "reviewed_rules",
        "automaticSuggestionIds": automatic,
        "manualSuggestionIds": selected,
        "retainedReviewKind": state["kind"],
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
            }
        }
        stages[i]["status"] = "needs_review" if i == index else "pending"
    workflow.plan.pop("finalDecision", None)
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
    workflow.detail = (
        f"请核查{len(candidates)}条保留对象；原成果已保存，确认后生成新一轮处置与复查"
    )
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
