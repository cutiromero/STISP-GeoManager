"""Adapt the established geology executor without moving its approval boundary."""

from copy import deepcopy

from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.agent.models import AgentWorkflow
from apps.agent.workflow_controls import (
    locked_workflow,
    save_workflow_state,
)
from apps.compute.packages import ComputeError
from .state import binding, state, emit, persist, TERMINAL, digest


def projected_state(workflow):
    value = deepcopy(state(workflow))
    plan = workflow.plan
    stages = {item["name"]: item for item in plan.get("stages", [])}
    index = plan.get("stageIndex", 0)
    completed = {item["name"] for item in plan.get("stages", [])[:index]}
    inputs = value["nodes"]["inputs"]
    ready = bool(
        plan.get("confirmedMapping")
        or plan.get("fieldMappingReview", {}).get("confirmed")
    )
    inputs["status"] = (
        "succeeded"
        if ready
        else "waiting_human"
        if workflow.status == "waiting_approval"
        else "executing"
    )
    inputs["human"].update(
        status="approved" if ready else "pending",
        reason="资料与字段使用原有专业确认记录",
    )
    if plan.get("fieldMappingReview"):
        inputs["executor"].update(
            status="succeeded",
            answer="已沿用您确认的字段对应。"
            if plan.get("reusedConfiguration")
            else "已依据实际资料整理字段对应建议，需由您确认后继续。",
        )
        if plan["fieldMappingReview"].get("modelMode") not in {"mock", "reused", None}:
            inputs["executor"]["model"] = workflow.model
    for identity, item in value["nodes"].items():
        if identity == "inputs":
            continue
        stage = stages.get(identity, {})
        if identity in completed or workflow.status == "succeeded":
            item["status"] = "succeeded"
        elif workflow.current_step in {
            identity,
            "final_analysis" if identity == "finish" else identity,
        }:
            item["status"] = (
                "waiting_human"
                if workflow.status == "waiting_approval"
                else "paused"
                if workflow.status == "paused"
                else "failed"
                if workflow.status in {"failed", "interrupted"}
                else "executing"
            )
        if stage.get("decision"):
            item["executor"].update(
                status="succeeded",
                model=workflow.model,
                answer=stage["decision"].get("judgement", ""),
                summary=stage["decision"].get("resultSummary", ""),
            )
        elif stage.get("taskId"):
            item["executor"].update(
                status="succeeded" if identity in completed else "running",
                model=workflow.model,
                reason="计算中心执行实际登记算子",
                taskId=stage["taskId"],
            )
        if stage.get("contextBudgetReview") and workflow.status == "waiting_approval":
            item["status"] = "waiting_context"
            item["contextRecovery"] = deepcopy(stage["contextBudgetReview"])
            item["contextManagement"] = deepcopy(stage.get("contextManagement", {}))
        if identity == "apply":
            approved = bool(stage.get("modificationsApproval"))
            item["human"].update(
                status="approved" if approved else "pending",
                reason="仅采用您在原专业流程中批准的对象与动作；审核智能体不写入批准记录",
            )
            if (
                workflow.status == "waiting_approval"
                and plan.get("phase") == "review_modifications"
            ):
                item["status"] = "waiting_human"
    if plan.get("finalDecision"):
        value["nodes"]["finish"]["executor"].update(
            status="succeeded",
            model=workflow.model,
            answer=plan["finalDecision"].get("judgement", ""),
            summary=plan["finalDecision"].get("resultSummary", ""),
        )
    return value


def synchronize(workflow_id):
    workflow = AgentWorkflow.objects.get(pk=workflow_id)
    if (
        not workflow.parameters.get("_businessFlow")
        or workflow.workflow_type == "business_flow"
    ):
        return
    if workflow.current_step in {"review_mapping", "review_plan", "build_inputs"}:
        # UI uses canonical input node, while the original executor keeps its phase.
        pass
    value = state(workflow)
    projected = projected_state(workflow)
    changed = (
        value["nodes"] != projected["nodes"]
        or value.get("workflowStatus") != workflow.status
    )
    value["nodes"] = projected["nodes"]
    value["workflowStatus"] = workflow.status
    if workflow.status == "succeeded":
        final = workflow.plan.get("finalDecision", {})
        value["answer"] = (
            final.get("resultSummary") or final.get("judgement") or workflow.detail
        )
    if changed:
        emit(
            workflow,
            "system",
            workflow.current_step,
            "professional_progress",
            workflow.detail,
        )
    else:
        persist(workflow)


def compact_review_packet(
    decision, edits, results, *, workflow=None, node_id=None, candidate_digest=None
):
    """Keep actual checksums, complete counts and grouped rules; omit bulky geometry."""
    if node_id == "finish":
        from .report_review import report_review_packet

        return report_review_packet(workflow, decision, results, candidate_digest)
    from collections import Counter
    from apps.agent.geology_multi_results import _model_metadata

    def row_summary(rows):
        groups = Counter(
            (
                str(row.get("element", "")),
                str(row.get("rule_id", row.get("ruleId", ""))),
                str(row.get("status", row.get("action", ""))),
            )
            for row in rows
            if isinstance(row, dict)
        )
        samples = [
            {
                key: value
                for key, value in row.items()
                if key.lower()
                not in {
                    "geometry",
                    "geometry_json",
                    "geometry_wkt",
                    "geometry_wkb",
                    "wkt",
                    "coordinates",
                    "geom",
                }
            }
            for row in rows[:12]
            if isinstance(row, dict)
        ]
        return {
            "rowCount": len(rows),
            "rowsDigest": digest(rows),
            "groups": [
                {"element": key[0], "rule": key[1], "status": key[2], "count": count}
                for key, count in groups.items()
            ],
            "sampleRows": samples,
            "sampleComplete": len(rows) <= 12,
            "geometryStoredInOriginal": any(
                any(
                    key.lower()
                    in {
                        "geometry",
                        "geometry_json",
                        "geometry_wkt",
                        "geometry_wkb",
                        "wkt",
                        "coordinates",
                        "geom",
                    }
                    for key in row
                )
                for row in rows[:12]
                if isinstance(row, dict)
            ),
        }

    actual, shared_metadata = [], {}
    for result in results:
        item = {
            key: value
            for key, value in result.items()
            if key not in {"rows", "features", "geometries"}
        }
        if isinstance(result.get("rows"), list):
            item["rows"] = row_summary(result["rows"])
        if isinstance(result.get("metadata"), dict):
            item["metadata"] = _model_metadata(
                result, shared_metadata, columns=result.get("columns")
            )
        actual.append(item)
    return {
        "decision": decision,
        "proposal": row_summary(edits),
        "actualResults": actual,
        "scope": "依据真实统计、完整数量、规则分组和有界样本核对节点结论；具体待裁定对象仍由原专业审核交给用户决定。",
    }


def review_decision(
    workflow, user, policy, stage, actual_results, initial, guard, producer
):
    """Review a real proposal; only the original executor can produce its repair."""
    if not workflow.parameters.get("_businessFlow"):
        return initial
    node_id = (
        "finish"
        if stage.get("identifier") == "finish"
        or stage.get("name") in {"finish", "final_analysis"}
        else stage.get("name")
    )
    node = next(
        (
            item
            for item in binding(workflow)["definitionSnapshot"]["nodes"]
            if item["id"] == node_id
        ),
        None,
    )
    if not node or not node["review"]["ai"]:
        return initial
    from apps.agent.business_flow_review import review_node
    from .engine import _callbacks

    item = state(workflow)["nodes"][node_id]
    current = initial
    candidate = digest(
        {"decision": initial[0], "edits": initial[1], "evidence": actual_results}
    )
    previous = item.get("reviewer", {})
    if (
        previous.get("decision") == "accept"
        and item.get("candidateDigest") == candidate
    ):
        return initial
    begin = max(1, item.get("attempt", 0))
    if previous.get("decision") == "request_changes":
        if item.get("attempt", 0) > node["review"]["maxRevisions"]:
            raise ComputeError("独立审核已达到该节点返修上限")
        if item.get("candidateDigest") == candidate:
            current = producer()
        begin = item.get("attempt", 0) + 1
    # The persisted attempt survives worker restarts; no extra repair is invented.
    for attempt in range(begin, node["review"]["maxRevisions"] + 2):
        guard()
        decision, edits = current
        item.update(
            attempt=attempt,
            status="reviewing",
            executor={
                "status": "succeeded",
                "model": workflow.model,
                "answer": decision.get("judgement", ""),
                "summary": decision.get("resultSummary", ""),
                "decision": deepcopy(decision),
            },
        )
        item["candidateDigest"] = digest(
            {"decision": decision, "edits": edits, "evidence": actual_results}
        )
        item["reviewer"] = {"status": "running"}
        workflow.detail = "独立审核智能体正在核对" + node["title"]
        packet = {
            "id": "node-result",
            "kind": "analysis",
            "title": node["title"],
            "result": {
                **compact_review_packet(
                    decision,
                    edits,
                    actual_results,
                    workflow=workflow,
                    node_id=node_id,
                    candidate_digest=item["candidateDigest"],
                ),
                "humanDecisionBoundary": "人工处置仅由原审核接口保存；本次审核不构成批准。",
            },
        }
        emit(workflow, "reviewer", node_id, "review_started", workflow.detail)
        alias = node["review"].get("model") or binding(workflow)["reviewerModel"]
        result = review_node(
            workflow,
            node,
            attempt,
            [packet],
            guard=guard,
            model_alias=alias,
            policy=policy,
            **_callbacks(workflow, node, "reviewer"),
        )
        item["reviewer"].update(
            result,
            status="passed" if result["decision"] == "accept" else "rejected",
            model=alias,
            feedback=result.get("repairInstructions", ""),
        )
        emit(
            workflow,
            "reviewer",
            node_id,
            "review_accepted" if result["decision"] == "accept" else "review_rejected",
            result["reason"],
        )
        if result["decision"] == "accept":
            return current
        if attempt > node["review"]["maxRevisions"]:
            raise ComputeError("独立审核未通过并达到返修上限：" + result["reason"])
        stage["businessFlowFeedback"] = {
            key: result[key] for key in ("reason", "issues", "repairInstructions")
        }
        # Preserve original immutable audit steps; discard only this generation's replay cache.
        stage.setdefault("businessFlowPreviousRequests", []).extend(
            {key: row.get(key) for key in ("requestSha256", "status", "accepted")}
            for row in stage.pop("modelAttempts", [])
        )
        stage.pop("modelBatches", None)
        item["status"] = "revising"
        emit(
            workflow,
            "executor",
            node_id,
            "revision_requested",
            result["repairInstructions"],
        )
        current = producer()
    raise ComputeError("独立审核未形成可接受结论")


def retry_context(user, workflow, value):
    from django.core.exceptions import ValidationError
    from .runtime import authorize, canonical_current_node
    from apps.agent.workflow import _state_hash
    from apps.agent.workflow_slots import require_compute_slot

    key = value.get("idempotencyKey")
    if not isinstance(key, str) or not 8 <= len(key) <= 80:
        raise ValidationError("上下文重试幂等键无效")
    if value.get("skipEvidenceIds") or value.get("contextScope"):
        raise ComputeError(
            "专业节点的完整科学统计与批准范围不能跳过；请调整实际资料范围或生成预留后重试",
            409,
        )
    with transaction.atomic():
        current = locked_workflow(workflow.pk)
        authorize(user, current)
        values = state(current)
        receipts = values.setdefault("decisions", {})
        fingerprint = digest(value)
        if key in receipts:
            if receipts[key] != fingerprint:
                raise ComputeError("上下文重试幂等键冲突", 409)
            return current
        node_id = canonical_current_node(current)
        item = projected_state(current)["nodes"].get(node_id, {})
        if (
            current.status != "waiting_approval"
            or not item.get("contextRecovery")
            or value.get("nodeId") != node_id
            or str(value.get("revision")) != str(values["revision"])
        ):
            raise ComputeError("上下文等待对象或版本已变化，请刷新", 409)
        if (
            current.plan.get("phase") == "budget_exhausted"
            or item["contextRecovery"].get("kind") == "model_call_limit"
        ):
            raise ComputeError(
                "模型请求额度已用完，请缩小任务范围后重新发起；不能通过重试重置计数",
                409,
            )
        require_compute_slot(user, current.pk)
        stage = next(
            row
            for row in current.plan["stages"]
            if row["name"]
            in {node_id, "final_analysis" if node_id == "finish" else node_id}
        )
        history = {"contextBudgetReview": stage.pop("contextBudgetReview")}
        candidates = [stage]
        batches = stage.get("modelBatches", {})
        candidates.extend(
            row["stage"]
            for row in batches.get("batches", [])
            if row.get("stage") and row.get("status") != "complete"
        )
        for candidate in candidates:
            attempts = candidate.get("modelAttempts", [])
            if attempts and not attempts[-1].get("accepted"):
                candidate.setdefault("modelBudgetHistory", []).append(
                    {"modelAttempts": candidate.pop("modelAttempts")}
                )
        stage.setdefault("modelBudgetHistory", []).append(history)
        stage["status"] = "pending"
        values["nodes"][node_id].pop("contextRecovery", None)
        values["nodes"][node_id]["status"] = "executing"
        receipts[key] = fingerprint
        current.plan["phase"] = "decide"
        current.plan_hash = _state_hash(current.plan)
        current.status, current.detail = (
            "queued",
            "将重新核对本节点输入预算；未批准科研结果、未重置模型计数",
        )
        current.policy_snapshot["businessFlowControlEpoch"] = (
            current.policy_snapshot.get("businessFlowControlEpoch", 0) + 1
        )
        current.save(
            update_fields=[
                "plan",
                "plan_hash",
                "parameters",
                "status",
                "detail",
                "policy_snapshot",
                "updated_at",
            ]
        )
        emit(current, "human", node_id, "context_retry", current.detail)
    return current


def legacy_control(user, workflow, action):
    from apps.agent.workflow_slots import require_compute_slot

    with transaction.atomic():
        current = locked_workflow(workflow.pk)
        if current.owner_id != user.pk:
            raise PermissionDenied("科研流程归属不一致")
        if (
            current.status in TERMINAL
            or action == "pause"
            and current.status == "paused"
        ):
            return current
        if action == "cancel":
            current.cancel_requested = True
            current.pause_requested = False
            current.status = "cancelled"
            current.detail = "已停止业务流，专业后续步骤不再启动"
        elif action == "pause":
            current.paused_from = current.status
            current.pause_requested = True
            current.status = "paused"
            current.detail = "专业业务流已暂停，保留实际计算与批准记录"
        else:
            if current.status != "paused":
                raise ComputeError("只有暂停的业务流可以恢复", 409)
            require_compute_slot(user, current.pk)
            current.status = (
                current.paused_from
                if current.paused_from in {"waiting_approval", "waiting_compute"}
                else "queued"
            )
            current.pause_requested = False
            current.paused_from = ""
            current.detail = "专业业务流已恢复"
        from .state import interrupt_actor_audits

        interrupt_actor_audits(current, action)
        current.policy_snapshot["businessFlowControlEpoch"] = (
            current.policy_snapshot.get("businessFlowControlEpoch", 0) + 1
        )
        current.save(
            update_fields=[
                "status",
                "detail",
                "cancel_requested",
                "pause_requested",
                "paused_from",
                "policy_snapshot",
                "plan",
                "parameters",
                "updated_at",
            ]
        )
        emit(current, "human", current.current_step, action, current.detail)
    if action == "cancel":
        from .engine import cancel_tasks

        cancel_tasks(user, current)
    return current


def review_rule_proposal(workflow, user, policy, stage, initial):
    """The original rule proposal is real evidence; repairs use the original model protocol."""
    if not workflow.parameters.get("_businessFlow"):
        return initial
    from apps.agent.demo_results import read_results
    from apps.agent.compute_tools import authorized_task
    from apps.agent.demo_decisions import decide
    from apps.agent.model_guard import ModelStreamGuard
    from .engine import live_guard
    import time

    results = []
    for previous in workflow.plan.get("stages", [])[
        : workflow.plan.get("stageIndex", 0)
    ]:
        if previous.get("taskId"):
            task = authorized_task(user, previous["taskId"], policy, workflow=workflow)
            results.extend(read_results(workflow, user, policy, task))
    guard = ModelStreamGuard(
        live_guard(workflow), time.monotonic() + policy["maxRunSeconds"]
    )

    def record(attempt):
        if attempt.get("status") == "requesting":
            calls = workflow.plan.get("actualModelCallCount", 0)
            reviews = len(state(workflow).get("requestedIds", []))
            if calls + reviews >= workflow.max_iterations:
                from apps.agent.business_flow_context import ContextReviewRequired

                raise ContextReviewRequired(
                    {
                        "nodeId": stage["name"],
                        "level": 0,
                        "evidence": [],
                        "kind": "model_call_limit",
                        "requested": False,
                        "reason": "业务流实际模型请求已达到额度，已保留结果",
                    }
                )
            workflow.plan["actualModelCallCount"] = calls + 1
        save_workflow_state(workflow)

    def produce():
        stage["executionMode"] = "model_reviewed"
        return decide(workflow, user, policy, stage, results, guard, record)

    return review_decision(
        workflow, user, policy, stage, results, initial, guard, produce
    )
