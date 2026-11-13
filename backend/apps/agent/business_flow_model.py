"""One bounded model transport for isolated business-flow actor requests."""

from __future__ import annotations
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import re
import time
from uuid import uuid4
from django.core.exceptions import PermissionDenied
from apps.compute.packages import ComputeError
from . import provider
from .config import registry
from .context import prepare_context
from .business_flow_context import (
    CONTEXT_INSTRUCTION,
    SUMMARY_CHARACTERS,
    ContextReviewRequired,
    evidence_sizes,
    prepare_packet,
    prepare_projected_request,
    input_budget,
    TokenMeasurements,
    compact_work_context,
)
from .model_guard import ModelStreamGuard
from .models import AgentWorkflow
from .policy import fresh_user, require_access
from .workflow_controls import check_pause
from .workflow_model_policy import workflow_model_policy

# Configuration: limits constrain all actors without retaining cross-request state.
MAX_RESPONSE_BYTES = 64 * 1024
ACTIVE_STATUSES = {"queued", "running", "waiting_compute"}
LIMITS = ("maxOutputTokens", "maxContextTokens", "maxContextBytes", "maxRunSeconds")


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _structured_text(raw):
    """Remove one complete JSON presentation fence; never extract prose fragments."""
    text = raw.strip()
    fenced = re.fullmatch(
        r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```[ \t]*", text, re.DOTALL | re.IGNORECASE
    )
    return fenced.group(1).strip() if fenced else text


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ComputeError(f"业务流模型字段{field}无效")
    return value.strip()


def _evidence(items):
    if not isinstance(items, list) or not items:
        raise ComputeError("业务流节点模型必须提供有界的实际证据")
    result, identities = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {
            "id",
            "kind",
            "title",
            "summary",
            "result",
            "required",
            "sourceNodeId",
            "contextReduction",
        }:
            raise ComputeError("业务流节点模型证据结构无效")
        identity = _text(item.get("id"), "evidence.id", 160)
        if identity in identities:
            raise ComputeError("业务流节点模型证据编号重复")
        identities.add(identity)
        result.append(
            {
                **item,
                "id": identity,
                "kind": _text(item.get("kind"), "evidence.kind", 80),
                "title": _text(item.get("title"), "evidence.title", 300),
            }
        )
        if not item.get("summary") and ("result" not in item or item["result"] is None):
            raise ComputeError("业务流节点模型证据缺少实际结果或摘要")
    return result, identities


def context_state(workflow):
    if workflow.parameters.get("_businessFlow"):
        from apps.business_flows.state import state

        return state(workflow)
    return {}


def actual_context(workflow, node_id, *, preparation=False):
    values = context_state(workflow)
    identity = values.get("nodes", {}).get(node_id, {}).get("executionContextId")
    snapshot = values.get("contextSnapshots", {}).get(identity, {})
    expected = "data_preparation" if preparation else "node_execution"
    return (
        deepcopy(snapshot)
        if snapshot.get("purpose", "node_execution") == expected
        else {}
    )


def _citations(value, available):
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or item not in available for item in value)
        or len(value) != len(set(value))
    ):
        raise ComputeError("业务流节点模型引用了缺失、重复或未提供的证据")
    return value


def _live_policy(workflow, alias, ceiling, source_bindings):
    current = (
        AgentWorkflow.objects.only(
            "id",
            "owner_id",
            "project_tag_id",
            "workflow_type",
            "status",
            "cancel_requested",
            "pause_requested",
            "paused_from",
            "model",
        )
        .filter(pk=workflow.pk)
        .first()
    )
    if current is None:
        raise PermissionDenied("业务流已删除，业务流节点模型停止")
    check_pause(workflow)
    if (
        current.cancel_requested
        or current.status not in ACTIVE_STATUSES
        or current.owner_id != workflow.owner_id
        or current.project_tag_id != workflow.project_tag_id
        or current.model != workflow.model
        or current.workflow_type != workflow.workflow_type
    ):
        raise PermissionDenied("业务流已停止、正在等待人工或归属已变化")
    # Source bindings were frozen by the caller before this request. Recheck
    # their actual runs/policies without rereading the large mutable result plan.
    current.plan = {"chatExecution": source_bindings}
    current.parameters = {}
    user = fresh_user(current.owner_id)
    policy = workflow_model_policy(
        current, user, require_access(user, "agent", alias), model_alias=alias
    )
    for key in LIMITS:
        value = policy.get(key)
        if type(value) is not int or value <= 0:
            raise PermissionDenied("业务流当前模型预算无效")
        if ceiling is not None and value < ceiling[key]:
            raise PermissionDenied("业务流节点模型预算权限已收窄，请重新确认")
    if ceiling is not None and any(
        policy.get(key) != ceiling.get(key) for key in ("_thinking", "reasoningEffort")
    ):
        raise PermissionDenied("业务流思考设置已变化，请重新确认")
    return policy


def request_node_result(
    workflow,
    node,
    attempt,
    evidence,
    *,
    role,
    instruction,
    validate,
    caps,
    guard,
    model_alias=None,
    policy=None,
    feedback=None,
    context=None,
    human_required=False,
    on_progress=None,
    on_thinking=None,
    on_record=None,
    tools=None,
    required_evidence_ids=None,
):
    """Run a fresh request; persistence and all actual operations stay in the runtime."""
    if role not in {"executor", "reviewer"}:
        raise ComputeError("业务流模型角色无效")
    node_id = _text(node.get("id"), "node.id", 80)
    items, available = _evidence(evidence)
    alias = model_alias or workflow.model
    if not isinstance(alias, str) or alias not in registry():
        raise PermissionDenied("业务流节点模型模型已不可用")
    model = registry()[alias]
    guard()
    source_bindings = deepcopy(workflow.plan.get("chatExecution", {}))
    if not source_bindings and workflow.parameters.get("_businessFlow"):
        source_bindings = {
            "requestRunId": workflow.parameters["_businessFlow"].get("runId")
        }
    live = _live_policy(workflow, alias, None, source_bindings)
    effective = dict(live)
    for key in LIMITS:
        chosen = (policy or live).get(key, live[key])
        if type(chosen) is not int or chosen <= 0:
            raise ComputeError("业务流节点模型预算无效")
        ceiling = caps.get(key, live[key])
        if type(ceiling) is not int or ceiling <= 0:
            raise ComputeError("业务流节点模型预算无效")
        effective[key] = min(live[key], chosen, ceiling)
    # Each role receives a separate bounded context, never a prior actor conversation.
    packet = {
        "node": {
            key: node.get(key, "")
            for key in ("id", "title", "description", "kind", "instruction")
        },
        "attempt": attempt,
        "humanApprovalRequired": human_required,
        "evidence": items,
    }
    if required_evidence_ids is not None:
        packet["requiredEvidenceIds"] = required_evidence_ids
    if feedback is not None:
        packet["revisionFeedback"] = feedback
    if context is not None:
        packet["nodeContext"] = context
    from apps.business_flows.model_recovery import guidance_context

    recovery_guidance = guidance_context(
        workflow, node_id, role, scope=(context or {}).get("executionScope", "node")
    )
    if recovery_guidance:
        if recovery_guidance.get("evidenceId") in available:
            recovery_guidance.pop("instruction", None)
        packet["recoveryGuidance"] = recovery_guidance
        instruction += "\nrecoveryGuidance是本节点的人工补充与真实诊断；据此纠错，不能改变权限、科学规则或人工批准。"
    from apps.business_flows.execution_session import guidance, request_context

    guidance_node = (
        "_main" if context and context.get("executionScope") == "workflow" else node_id
    )
    execution = request_context(workflow, guidance_node, role)
    if execution:
        packet["executionSession"] = execution
        instruction += guidance(workflow, guidance_node, role)
    try:
        payload = _json(packet)
    except (ValueError, TypeError) as error:
        raise ComputeError("业务流节点模型证据不是有效JSON") from error
    managed = workflow.workflow_type == "business_flow"
    bound = bool(workflow.parameters.get("_businessFlow"))
    professional = bound and not managed
    values = context_state(workflow)
    entry = values.get("nodes", {}).get(node_id, {})
    if role == "executor" and entry.get("reviewContextBudget"):
        for key in ("maxContextTokens", "maxContextBytes"):
            effective[key] = min(effective[key], entry["reviewContextBudget"][key])
    snapshot = (
        actual_context(
            workflow,
            node_id,
            preparation=any(row["id"] == "preparation-script" for row in items),
        )
        if role == "reviewer"
        else {}
    )
    if managed:
        from apps.business_flows.ledger import current_ledger

        packet["ledger"] = (
            snapshot.get("ledger", current_ledger(workflow))
            if values
            else {"goal": workflow.goal, "entries": [], "unresolved": []}
        )
        packet["contextNotice"] = deepcopy(snapshot.get("contextNotice", []))
        if snapshot:
            supplied = {row["id"] for row in snapshot["evidence"]}
            packet["evidence"] = [
                *snapshot["evidence"],
                *[row for row in items if row["id"] not in supplied],
            ]
        options = entry.get("contextOptions", {})
        skipped = set(options.get("skipEvidenceIds", []))
        if not snapshot:
            packet["evidence"] = [
                row for row in packet["evidence"] if row["id"] not in skipped
            ]
        for row in items:
            if row["id"] in skipped and not snapshot:
                packet["contextNotice"].append(
                    {
                        "evidenceId": row["id"],
                        "action": "user_skip",
                        "originalBytes": len(_json(row).encode()),
                        "retainedBytes": 0,
                    }
                )
        if options.get("scope"):
            packet["scopeLimit"] = options["scope"]
        if options.get("contextScope"):
            packet["contextScope"] = options["contextScope"]
        instruction += CONTEXT_INSTRUCTION
        payload = _json(packet)
    elif (
        not professional and len(payload.encode("utf-8")) > effective["maxContextBytes"]
    ):
        raise ComputeError("业务流节点模型证据超过预算，未发送请求；请缩小节点结果范围")
    messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": payload},
    ]
    started = time.monotonic()

    def authorize():
        guard()
        _live_policy(workflow, alias, effective, source_bindings)
        if registry().get(alias) != model:
            raise PermissionDenied("业务流模型配置已变化")

    checked = ModelStreamGuard(authorize, started + effective["maxRunSeconds"])
    record = {
        "requestId": uuid4().hex,
        "role": role,
        "nodeId": node_id,
        "attempt": attempt,
        "modelAlias": alias,
        "modelId": model.model_id,
        "modelName": model.name,
        "requested": False,
        "status": "preparing",
        "requestSha256": _digest(_json(messages)),
        "usage": {},
        "humanApprovalRequired": human_required,
        "thinkingEnabled": effective["_thinking"],
        "reasoningEffort": effective["reasoningEffort"],
        "outputLimit": effective["maxOutputTokens"],
        "timeLimitSeconds": effective["maxRunSeconds"],
        **({"executionSession": execution} if execution else {}),
    }
    activity = None

    def publish(status, **values):
        nonlocal activity
        if status == "requesting" and (managed or professional):
            from apps.business_flows.model_requests import admit

            admit(
                workflow,
                record["requestId"],
                node_scoped=not (
                    context and context.get("executionScope") == "workflow"
                ),
            )
        if status == "requesting":
            from .model_activity import WorkflowModelActivity

            activity = WorkflowModelActivity(
                workflow,
                node.get("title") or node_id,
                model,
                effective,
                checked,
                node_id="_main"
                if context and context.get("executionScope") == "workflow"
                else node_id,
                actor=role,
                request_id=record["requestId"],
            )
            activity.progress({"status": "requesting", "attempt": attempt})
        elif activity is not None:
            if status in {"validating", "completed", "accepted", "changes_requested"}:
                activity.progress(
                    {"status": "validating" if status == "validating" else "complete"}
                )
            elif status in {"failed", "context_waiting"}:
                activity.fail()
        record.update(
            status=status,
            durationMs=round((time.monotonic() - started) * 1000),
            **values,
        )
        if on_record:
            on_record(deepcopy(record))
        if on_progress:
            on_progress(
                {
                    key: record[key]
                    for key in (
                        "requestId",
                        "role",
                        "nodeId",
                        "attempt",
                        "modelAlias",
                        "status",
                    )
                }
            )

    def usage_received(value):
        if isinstance(value, dict):
            record["usage"].update(
                {
                    key: value[key]
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if type(value.get(key)) is int and value[key] >= 0
                }
            )

    def thinking_received(text):
        checked()
        if activity is not None:
            activity.thinking(text)
        if on_thinking:
            on_thinking(text)

    raw = ""
    try:
        checked.poll()
        window = provider.model_window(model)
        checked.poll()
        if professional:
            from .decision_budget import _deduplicate, dumps, REFERENCE_NOTE
            from apps.business_flows.ledger import professional_ledger
            from . import context as context_budget

            packet["ledger"] = professional_ledger(workflow)
            packet["contextNotice"] = [
                "科学统计覆盖完整已读取数据；逐对象样本仅限明确展示范围，原件按输出引用保留。"
            ]

            def project(level):
                value = compact_work_context(packet) if level else deepcopy(packet)
                if level >= 2:
                    value = _deduplicate(value)
                return [
                    {
                        "role": "system",
                        "content": instruction + CONTEXT_INSTRUCTION + REFERENCE_NOTE,
                    },
                    {"role": "user", "content": dumps(value)},
                ]

            messages, management = prepare_projected_request(
                project,
                model,
                effective,
                window,
                node_id=node_id,
                checked=checked.poll,
                levels=range(3),
                notices=[
                    *packet["contextNotice"],
                    "超出窗口时自动压缩近期行动，完整统计、规则条件、批准范围和成果引用保留。",
                ],
                measurements=TokenMeasurements(
                    model,
                    thinking=effective["_thinking"],
                    effort=effective["reasoningEffort"],
                    counter=(
                        lambda model, messages, thinking, effort: provider.count_tokens(
                            model, messages, thinking, effort, tools=tools
                        )
                    )
                    if tools
                    else context_budget.count_tokens,
                ),
            )
            record.update(
                contextManagement=management, requestSha256=_digest(_json(messages))
            )
            tokens = management["afterTokens"]
            entry["contextManagement"] = deepcopy(management)
        elif managed:

            def summarize(batch_messages, rows, batch_tokens, management):
                nonlocal record
                management = {
                    **management,
                    "evidenceIds": [row["id"] for row in rows],
                    "noticeSummary": [
                        "本批归纳证据：" + "、".join(row["id"] for row in rows)
                    ],
                }
                parent = record
                record = deepcopy(parent)
                record.update(
                    requestId=uuid4().hex,
                    parentRequestId=parent["requestId"],
                    purpose="context_summary",
                    requested=False,
                    usage={},
                    inputTokens=batch_tokens,
                    contextWindowTokens=window,
                    contextManagement=management,
                    requestSha256=_digest(_json(batch_messages)),
                    outputLimit=effective["maxOutputTokens"],
                )
                cache_key = _digest(
                    _json(
                        {
                            "messages": batch_messages,
                            "model": model.model_id,
                            "alias": alias,
                            "baseUrl": model.base_url,
                            "budget": management["inputBudgetTokens"],
                            "outputLimit": record["outputLimit"],
                            "thinking": effective["_thinking"],
                            "effort": effective["reasoningEffort"],
                        }
                    )
                )
                try:
                    checked.poll()
                    cached = values.get("contextSummaryCache", {}).get(cache_key)
                    if cached is not None:
                        publish(
                            "completed",
                            purpose="context_summary_cache",
                            cacheReused=True,
                        )
                        return deepcopy(cached)
                    publish("requesting", requested=True)
                    chunks, response_size = [], 0
                    with closing(
                        provider.stream(
                            model,
                            batch_messages,
                            record["outputLimit"],
                            checked,
                            structured=True,
                            thinking=effective["_thinking"],
                            temperature=0,
                            top_p=live["topP"],
                            reasoning_effort=effective["reasoningEffort"],
                            on_usage=usage_received,
                            on_thinking=thinking_received,
                            monitor_guard=checked.poll,
                        )
                    ) as response:
                        for chunk in response:
                            if activity is not None:
                                activity.response(chunk)
                            response_size += len(chunk.encode())
                            if response_size > MAX_RESPONSE_BYTES:
                                raise ComputeError("上下文归纳响应超过安全上限")
                            chunks.append(chunk)
                            checked()
                    answer = "".join(chunks)
                    try:
                        response_value = json.loads(_structured_text(answer))
                        summaries = response_value["evidence"]
                        if set(response_value) != {"evidence"} or not isinstance(
                            summaries, list
                        ):
                            raise ValueError
                        result = {
                            row["id"]: _text(
                                row["summary"], "summary", SUMMARY_CHARACTERS
                            )
                            for row in summaries
                            if set(row) == {"id", "summary"}
                        }
                        if len(result) != len(summaries) or set(result) != {
                            row["id"] for row in rows
                        }:
                            raise ValueError
                    except (ValueError, TypeError, KeyError, ComputeError) as error:
                        raise ContextReviewRequired(
                            {
                                **management,
                                "evidence": evidence_sizes(items, node, direct_ids),
                                "reason": "分批归纳未提供有效的完整编号与受限摘要",
                            }
                        ) from error
                    checked.poll()
                    if values:
                        values.setdefault("contextSummaryCache", {})[cache_key] = (
                            deepcopy(result)
                        )
                    publish(
                        "completed",
                        responseSha256=_digest(answer),
                        responseFormat="json_fence"
                        if _structured_text(answer) != answer.strip()
                        else "json",
                        responseBytes=response_size,
                    )
                    return result
                except Exception as error:
                    if isinstance(error, ComputeError) or (
                        isinstance(error, provider.ModelError)
                        and "达到本步时限" in str(error)
                    ):
                        waiting = ContextReviewRequired(
                            {
                                **management,
                                "evidence": evidence_sizes(items, node, direct_ids),
                                "reason": str(error),
                            }
                        )
                        publish("context_waiting", error=str(waiting))
                        raise waiting from error
                    publish(
                        "context_waiting"
                        if isinstance(error, ContextReviewRequired)
                        else "failed",
                        error=str(error)[:500],
                    )
                    raise
                finally:
                    record = parent

            direct_ids = (
                {
                    row["id"]
                    for dependency in node.get("dependsOn", [])
                    for row in values.get("nodes", {})
                    .get(dependency, {})
                    .get("outputs", {})
                    .get("evidence", [])
                }
                | {"node-" + identity for identity in node.get("dependsOn", [])}
                | set(snapshot.get("requiredEvidenceIds", []))
            )
            packet, messages, management = prepare_packet(
                packet,
                instruction,
                model,
                effective,
                window,
                direct_ids=direct_ids,
                summarize=summarize,
                checked=checked.poll,
                locked=bool(snapshot),
                measurements=TokenMeasurements(
                    model,
                    thinking=effective["_thinking"],
                    effort=effective["reasoningEffort"],
                    counter=lambda model, messages, thinking, effort: (
                        provider.count_tokens(
                            model, messages, thinking, effort, tools=tools
                        )
                    ),
                )
                if tools
                else None,
            )
            if snapshot:
                management["level"] = snapshot.get("contextManagement", {}).get(
                    "level", management["level"]
                )
            available = {row["id"] for row in packet["evidence"]}
            record.update(
                contextManagement=management, requestSha256=_digest(_json(messages))
            )
            tokens = management["afterTokens"]
            if (
                entry
                and role == "executor"
                and (
                    not context
                    or context.get("purpose") in {"data_preparation", "node_tools"}
                )
            ):
                previous_snapshot = entry.get("executionContextId")
                values.setdefault("contextSnapshots", {})[record["requestId"]] = {
                    key: deepcopy(packet[key])
                    for key in ("evidence", "contextNotice", "ledger")
                }
                values["contextSnapshots"][record["requestId"]]["contextManagement"] = (
                    deepcopy(management)
                )
                values["contextSnapshots"][record["requestId"]]["purpose"] = (
                    context or {}
                ).get("purpose", "node_execution")
                values["contextSnapshots"][record["requestId"]][
                    "requiredEvidenceIds"
                ] = [
                    row["id"]
                    for row in evidence_sizes(items, node, direct_ids)
                    if row["required"]
                ]
                if context and context.get("purpose") == "node_tools":
                    saved = values["contextSnapshots"][record["requestId"]]
                    saved.update(purpose="node_execution", toolLoop=True)
                    observation = packet.get("nodeContext", {}).get("observation")
                    if observation:
                        for row in saved["evidence"]:
                            if row["id"] == observation["evidenceId"]:
                                row.pop("summary", None)
                                row["result"] = deepcopy(observation["result"])
                    if (
                        values["contextSnapshots"]
                        .get(previous_snapshot, {})
                        .get("toolLoop")
                    ):
                        values["contextSnapshots"].pop(previous_snapshot)
                entry["executionContextId"] = record["requestId"]
            if entry:
                entry["contextManagement"] = deepcopy(management)
                if management["level"]:
                    from apps.business_flows.state import emit

                    emit(
                        workflow,
                        role,
                        node_id,
                        "context_compacted",
                        f"本节点输入已整理 · 第{management['level']}档（{management['beforeTokens']} → {tokens} token）",
                    )
        else:
            tokens, truncated = prepare_context(
                messages, messages[1], model, effective, window, effective["_thinking"]
            )
            if truncated:
                raise ComputeError("业务流节点模型不能丢弃实际证据，未发送请求")
        record.update(
            inputTokens=tokens,
            contextWindowTokens=window,
            inputLimit=input_budget(effective, window),
        )
        checked.poll()
        publish("requesting", requested=True)
        chunks, size = [], 0
        with closing(
            provider.stream(
                model,
                messages,
                effective["maxOutputTokens"],
                checked,
                structured=True,
                thinking=effective["_thinking"],
                temperature=min(live["temperature"], 0.1),
                top_p=live["topP"],
                reasoning_effort=effective["reasoningEffort"],
                on_usage=usage_received,
                on_thinking=thinking_received,
                monitor_guard=checked.poll,
                **({"tools": tools} if tools else {}),
            )
        ) as response:
            for chunk in response:
                size += len(chunk.encode("utf-8"))
                if size > MAX_RESPONSE_BYTES:
                    raise provider.ModelError(
                        "业务流节点模型响应超过安全上限，未予通过"
                    )
                chunks.append(chunk)
                if activity is not None:
                    activity.response(chunk)
                checked()
        raw = "".join(chunks)
        if activity is not None:
            activity.response(raw, append=False)
        checked.poll()
        normalized = _structured_text(raw)
        publish(
            "validating",
            responseSha256=_digest(raw),
            responseBytes=size,
            responseFormat="json_fence" if normalized != raw.strip() else "json",
        )
        try:
            result = validate(normalized, available)
        except ComputeError as error:
            if (
                managed
                and bound
                and role == "executor"
                and not tools
                and not (context or {}).get("executionScope")
                and "contract" not in (context or {})
            ):
                from apps.business_flows.model_recovery import model_wait

                raise model_wait(node_id, error) from error
            raise
        if managed and packet.get("contextNotice") and "limitations" in result:
            result["limitations"] = [
                *result["limitations"],
                "本节点仅使用实际发送的资料；输入整理和用户跳过范围见contextNotice（"
                + "、".join(sorted({row["action"] for row in packet["contextNotice"]}))
                + "），未读取被省略内容。",
            ]
        checked.poll()
        publish(
            ("accepted" if result["decision"] == "accept" else "changes_requested")
            if role == "reviewer"
            else "completed"
        )
        return {
            **result,
            "audit": deepcopy(record),
        }
    except ContextReviewRequired as error:
        if snapshot and managed and "inputBudgetTokens" in error.details:
            sent_tokens = snapshot.get("contextManagement", {}).get("afterTokens", 0)
            overhead = max(0, error.details["afterTokens"] - sent_tokens)
            supplied_ids = {row["id"] for row in snapshot["evidence"]}
            result_bytes = len(
                _json([row for row in items if row["id"] not in supplied_ids]).encode()
            )
            error.details.update(
                requiresExecutionRepack=True,
                reviewContextBudget={
                    "maxContextTokens": max(
                        1, error.details["inputBudgetTokens"] - overhead - 256
                    ),
                    "maxContextBytes": max(
                        1, effective["maxContextBytes"] - result_bytes - 1024
                    ),
                },
            )
        record["contextManagement"] = {
            key: value for key, value in error.details.items() if key != "evidence"
        }
        publish("context_waiting", error=str(error))
        raise
    except Exception as error:
        from apps.business_flows.model_requests import ModelCallBudgetExceeded

        if (managed or professional) and isinstance(error, ModelCallBudgetExceeded):
            details = record.get("contextManagement", {"nodeId": node_id, "level": 0})
            details = {
                **details,
                "reason": str(error),
                "kind": "model_call_limit",
                "budgetScope": error.scope,
                **({"usedRequests": error.used} if error.used is not None else {}),
                **({"limit": error.limit} if error.limit is not None else {}),
                "requested": False,
                "evidence": evidence_sizes(items, node, set()),
                "requestScope": (context or {}).get("executionScope", "node"),
            }
            publish("context_waiting", error=str(error), requested=False)
            raise ContextReviewRequired(details) from error
        # No raw prompt, partial private text or model-issued human approval leaks.
        publish(
            "failed", responseSha256=_digest(raw) if raw else "", error=str(error)[:500]
        )
        if bound and isinstance(error, provider.ModelError):
            error.recovery_scope = (context or {}).get("executionScope", "node")
        if (
            bound
            and isinstance(error, provider.ModelError)
            and "contract" not in (context or {})
        ):
            guard()
            from apps.business_flows.model_recovery import model_wait

            raise model_wait(
                node_id,
                error,
                actor=role,
                kind="model_request_error",
                scope=(context or {}).get("executionScope", "node"),
            ) from error
        raise
