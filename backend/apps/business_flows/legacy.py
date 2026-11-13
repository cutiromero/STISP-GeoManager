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


def _saved_request_stage(stage):
    from apps.agent.demo_decisions import can_revalidate_saved_response

    attempts = stage.get("modelAttempts", [])
    payload = stage.get("modelRequestPayload")
    if not (
        isinstance(attempts, list)
        and attempts
        and isinstance(attempts[-1], dict)
        and (
            attempts[-1].get("accepted") is True or can_revalidate_saved_response(stage)
        )
        and isinstance(attempts[-1].get("response"), str)
        and attempts[-1]["response"].strip()
        and isinstance(payload, dict)
        and isinstance(payload.get("executionState"), dict)
    ):
        return None
    original = payload["executionState"].get("currentStage")
    return original if isinstance(original, dict) and "planStatus" in original else None


def _resume_stage_status(stage):
    original = _saved_request_stage(stage)
    if original is None:
        stage["status"] = "pending"
    elif original["planStatus"] is None:
        stage.pop("status", None)
    else:
        stage["status"] = original["planStatus"]


def _review_recovery(workflow, stage):
    current = stage.get("contextBudgetReview")
    if current:
        return current
    if workflow.status == "failed":
        from apps.agent.demo_decisions import can_revalidate_saved_response

        if can_revalidate_saved_response(stage):
            return {
                "kind": "model_protocol_error",
                "level": 0,
                "evidence": [],
                "reason": "已保存报告需重新核对完整引用；前序计算与批准记录保留。",
            }
        for row in reversed(stage.get("modelBudgetHistory", [])):
            recovery = row.get("contextBudgetReview", {})
            if recovery:
                return (
                    recovery if recovery.get("kind") == "model_protocol_error" else {}
                )
    return {}


def _retryable_failed_review(workflow, stage, recovery=None):
    return (
        workflow.status == "failed"
        and not getattr(workflow, "cancel_requested", False)
        and workflow.current_step == stage.get("name")
        and not stage.get("decision")
        and (recovery or _review_recovery(workflow, stage)).get("kind")
        == "model_protocol_error"
        and _saved_request_stage(stage) is not None
    )


def _context_stage(workflow, node_id):
    stages = workflow.plan.get("stages", [])
    names = {node_id, "final_analysis" if node_id == "finish" else node_id}
    stage = next((row for row in stages if row["name"] in names), None)
    if node_id != "finish":
        return stage
    final = workflow.plan.get("finalStage") or stage
    if final is None:
        return None
    index = workflow.plan.get("stageIndex", len(stages))
    tail = stages[index:]
    # Older waits duplicated finalStage into the calculation list. Only merge
    # an exact copy of this saved request, preserving every calculation stage.
    if tail:
        if not all(
            row.get("name") == final.get("name")
            and row.get("identifier") == final.get("identifier") == "finish"
            and row.get("modelRequestPayload") == final.get("modelRequestPayload")
            and row.get("modelRequestInstruction")
            == final.get("modelRequestInstruction")
            and row.get("modelAttempts") == final.get("modelAttempts")
            for row in tail
        ):
            raise ComputeError("最终分析的保存请求不一致，不能自动合并恢复", 409)
        for row in tail:
            for history in row.get("modelBudgetHistory", []):
                if history not in final.setdefault("modelBudgetHistory", []):
                    final["modelBudgetHistory"].append(deepcopy(history))
        workflow.plan["stages"] = stages[:index]
    workflow.plan["finalStage"] = final
    return final


def projected_state(workflow):
    value = deepcopy(state(workflow))
    plan = workflow.plan

    def stage_node_id(item):
        return "finish" if item.get("identifier") == "finish" else item["name"]

    stages = {stage_node_id(item): item for item in plan.get("stages", [])}
    if isinstance(plan.get("finalStage"), dict):
        stages["finish"] = plan["finalStage"]
    index = plan.get("stageIndex", 0)
    completed = {stage_node_id(item) for item in plan.get("stages", [])[:index]}
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
        recovery = _review_recovery(workflow, stage)
        if recovery and (
            workflow.status == "waiting_approval"
            or _retryable_failed_review(workflow, stage)
        ):
            item["status"] = "waiting_context"
            item["contextRecovery"] = deepcopy(recovery)
            item["contextRecovery"].setdefault("nodeId", identity)
            item["contextRecovery"].setdefault("level", 0)
            item["contextRecovery"].setdefault("evidence", [])
            for key in (
                "beforeTokens",
                "afterTokens",
                "inputBudgetTokens",
                "measurementCount",
            ):
                if item["contextRecovery"].get(key) is None:
                    item["contextRecovery"].pop(key, None)
            item["contextManagement"] = deepcopy(stage.get("contextManagement", {}))
            item["contextManagement"].setdefault("nodeId", identity)
            item["contextManagement"].setdefault("level", 0)
            for key in (
                "beforeTokens",
                "afterTokens",
                "inputBudgetTokens",
                "measurementCount",
            ):
                if item["contextManagement"].get(key) is None:
                    item["contextManagement"].pop(key, None)
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
    for item in value["nodes"].values():
        if item.get("contextRecovery") and workflow.status == "waiting_approval":
            item["status"] = "waiting_context"
        if item.get("recovery") and workflow.status == "waiting_approval":
            item["status"] = "waiting_recovery"
    return value


def synchronize(workflow_id):
    workflow = AgentWorkflow.objects.get(pk=workflow_id)
    if (
        not workflow.parameters.get("_businessFlow")
        or workflow.workflow_type == "business_flow"
    ):
        return
    if workflow.status == "failed":
        from apps.compute.models import ComputeTask
        from .runtime import canonical_current_node
        from .node_loop import wait_recovery

        stages = workflow.plan.get("stages", [])
        index = workflow.plan.get("stageIndex", 0)
        stage = stages[index] if index < len(stages) else {}
        task = (
            ComputeTask._base_manager.filter(
                pk=stage["taskId"],
                owner_id=workflow.owner_id,
                project_tag_id=workflow.project_tag_id,
            ).first()
            if stage.get("taskId")
            else None
        )
        if task and task.status in {"failed", "cancelled"}:
            node_id = canonical_current_node(workflow)
            node = next(
                row
                for row in binding(workflow)["definitionSnapshot"]["nodes"]
                if row["id"] == node_id
            )
            wait_recovery(
                workflow,
                node,
                state(workflow)["nodes"][node_id],
                {
                    **(task.failure or {}),
                    "message": workflow.detail,
                    "taskId": str(task.pk),
                },
            )
            state(workflow)["nodes"][node_id]["recovery"]["taskId"] = str(task.pk)
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
    from .model_recovery import automatic_review_limit, model_wait

    limit = automatic_review_limit(item, node)
    if previous.get("decision") == "request_changes":
        if item.get("attempt", 0) >= limit:
            raise model_wait(
                node_id, previous.get("reason", "审核需要返修"), kind="review_rejected"
            )
        if item.get("candidateDigest") == candidate:
            current = producer()
        begin = item.get("attempt", 0) + 1
    # The persisted attempt survives worker restarts; no extra repair is invented.
    for attempt in range(begin, limit + 1):
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
        stage["businessFlowFeedback"] = {
            key: result[key] for key in ("reason", "issues", "repairInstructions")
        }
        if attempt >= limit:
            raise model_wait(node_id, result["reason"], kind="review_rejected")
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
        live_policy = authorize(user, current)
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
            current.status not in {"waiting_approval", "failed"}
            or not item.get("contextRecovery")
            or value.get("nodeId") != node_id
            or str(value.get("revision")) != str(values["revision"])
        ):
            raise ComputeError("上下文等待对象或版本已变化，请刷新", 409)
        if (
            current.plan.get("phase") == "budget_exhausted"
            or item["contextRecovery"].get("kind") == "model_call_limit"
        ):
            from .model_requests import renew_task_budget

            renew_task_budget(current, live_policy, item["contextRecovery"])
        from .model_requests import renew_operator_budget

        renew_operator_budget(current, live_policy, item["contextRecovery"])
        require_compute_slot(user, current.pk)
        stage = _context_stage(current, node_id)
        if (
            stage is None
            and node_id != "inputs"
            and not item["contextRecovery"].get("resumeCheckpoint")
        ):
            raise ComputeError("当前等待阶段已变化，请刷新后重试", 409)
        if current.status == "failed" and (
            stage is None
            or not _retryable_failed_review(current, stage, item["contextRecovery"])
        ):
            raise ComputeError("该失败没有可复用的已接受分析响应，不能重试审核", 409)
        from .model_recovery import (
            MODEL_WAIT_KINDS,
            save_guidance,
            archive_model_attempts,
        )

        recovery = item["contextRecovery"]
        from .failure_handoff import restore_checkpoint

        restored = restore_checkpoint(current, recovery)
        if recovery.get("kind") in MODEL_WAIT_KINDS:
            reuse_platform_response = (
                recovery.get("kind") == "platform_error"
                and not value.get("feedback", "").strip()
            )
            if not reuse_platform_response:
                save_guidance(current, node_id, value, recovery)
            if (
                (
                    recovery.get("actor") == "executor"
                    or recovery.get("kind") == "review_rejected"
                )
                and not reuse_platform_response
                and not restored
            ):
                if stage is not None:
                    archive_model_attempts(stage)
                    stage.pop("decision", None)
                if recovery.get("kind") == "review_rejected":
                    target = values["nodes"][node_id]
                    target["manualReviewBaseline"] = target["attempt"]
                    target["reviewer"] = {"status": "pending"}
                    target["attempt"] += 1
        history = (
            {
                "contextBudgetReview": stage.pop(
                    "contextBudgetReview", deepcopy(item["contextRecovery"])
                )
            }
            if stage is not None
            else None
        )
        candidates = [stage] if stage is not None and not restored else []
        batches = stage.get("modelBatches", {}) if stage is not None else {}
        candidates.extend(
            row["stage"]
            for row in batches.get("batches", [])
            if row.get("stage") and row.get("status") != "complete" and not restored
        )
        for candidate in candidates:
            from apps.agent.demo_decisions import can_revalidate_saved_response

            attempts = candidate.get("modelAttempts", [])
            if (
                attempts
                and not attempts[-1].get("accepted")
                and not can_revalidate_saved_response(candidate)
            ):
                candidate.setdefault("modelBudgetHistory", []).append(
                    {"modelAttempts": candidate.pop("modelAttempts")}
                )
        if stage is not None and not restored:
            stage.setdefault("modelBudgetHistory", []).append(history)
            # A scheduler wait must not change the identity of a saved model
            # request. All scientific facts are still freshly checked on replay.
            _resume_stage_status(stage)
        values["nodes"][node_id].pop("contextRecovery", None)
        values["nodes"][node_id]["status"] = values["nodes"][node_id].pop(
            "contextResumeStatus", "executing"
        )
        receipts[key] = fingerprint
        if stage is not None and not restored:
            current.plan["phase"] = "decide"
        current.plan_hash = _state_hash(current.plan)
        current.status, current.detail = (
            "queued",
            "将重试本次审核，保留执行结果与模型计数；未批准科研结果"
            if item["contextRecovery"].get("kind") == "model_protocol_error"
            else "将按当前说明继续本节点分析与审核；保留前序成果、模型计数和原批准记录"
            if item["contextRecovery"].get("kind") in MODEL_WAIT_KINDS
            else "将重新核对本节点输入预算；未批准科研结果、未重置模型计数",
        )
        current.policy_snapshot["businessFlowControlEpoch"] = (
            current.policy_snapshot.get("businessFlowControlEpoch", 0) + 1
        )
        current.save(
            update_fields=[
                "plan",
                "plan_hash",
                "parameters",
                "current_step",
                "status",
                "detail",
                "policy_snapshot",
                "max_iterations",
                "max_operator_steps",
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
