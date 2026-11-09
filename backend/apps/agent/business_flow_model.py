"""One bounded model transport for isolated business-flow actor requests."""

from __future__ import annotations
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import time
from uuid import uuid4
from django.core.exceptions import PermissionDenied
from apps.compute.packages import ComputeError
from . import provider
from .config import registry
from .context import prepare_context
from .model_guard import ModelStreamGuard
from .models import AgentWorkflow
from .policy import fresh_user, require_access
from .workflow_controls import check_pause
from .workflow_model_policy import workflow_model_policy

# Configuration: limits constrain all actors without retaining cross-request state.
MAX_EVIDENCE_ITEMS = 100
MAX_RESPONSE_BYTES = 64 * 1024
ACTIVE_STATUSES = {"queued", "running", "waiting_compute"}
LIMITS = ("maxOutputTokens", "maxContextTokens", "maxContextBytes", "maxRunSeconds")


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ComputeError(f"业务流模型字段{field}无效")
    return value.strip()


def _evidence(items):
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_EVIDENCE_ITEMS:
        raise ComputeError("业务流节点模型必须提供有界的实际证据")
    result, identities = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {
            "id",
            "kind",
            "title",
            "summary",
            "result",
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
    user = fresh_user(current.owner_id)
    policy = workflow_model_policy(current, user, require_access(user, "agent", alias))
    for key in LIMITS:
        value = policy.get(key)
        if type(value) is not int or value <= 0:
            raise PermissionDenied("业务流当前模型预算无效")
        if ceiling is not None and value < ceiling[key]:
            raise PermissionDenied("业务流节点模型预算权限已收窄，请重新确认")
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
    live = _live_policy(workflow, alias, None, source_bindings)
    effective = dict(live)
    for key in LIMITS:
        chosen = (policy or live).get(key, live[key])
        if type(chosen) is not int or chosen <= 0:
            raise ComputeError("业务流节点模型预算无效")
        effective[key] = min(live[key], chosen, caps[key])
    # Each role receives a separate bounded context, never a prior actor conversation.
    effective.update(_thinking=False, reasoningEffort="low")
    packet = {
        "node": {
            key: node.get(key, "")
            for key in ("id", "title", "description", "kind", "instruction")
        },
        "attempt": attempt,
        "humanApprovalRequired": human_required,
        "evidence": items,
    }
    if feedback is not None:
        packet["revisionFeedback"] = feedback
    if context is not None:
        packet["nodeContext"] = context
    try:
        payload = _json(packet)
    except (ValueError, TypeError) as error:
        raise ComputeError("业务流节点模型证据不是有效JSON") from error
    if len(payload.encode("utf-8")) > effective["maxContextBytes"]:
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
        "thinkingEnabled": False,
        "reasoningEffort": "low",
        "outputLimit": effective["maxOutputTokens"],
    }

    def publish(status, **values):
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
        if on_thinking:
            on_thinking(text)

    raw = ""
    try:
        checked.poll()
        window = provider.model_window(model)
        checked.poll()
        tokens, truncated = prepare_context(
            messages, messages[1], model, effective, window, False
        )
        if truncated:
            raise ComputeError("业务流节点模型不能丢弃实际证据，未发送请求")
        record.update(inputTokens=tokens, contextWindowTokens=window)
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
                thinking=False,
                temperature=min(live["temperature"], 0.1),
                top_p=live["topP"],
                reasoning_effort="low",
                on_usage=usage_received,
                on_thinking=thinking_received,
                monitor_guard=checked.poll,
            )
        ) as response:
            for chunk in response:
                size += len(chunk.encode("utf-8"))
                if size > MAX_RESPONSE_BYTES:
                    raise provider.ModelError(
                        "业务流节点模型响应超过安全上限，未予通过"
                    )
                chunks.append(chunk)
                checked()
        raw = "".join(chunks)
        checked.poll()
        publish("validating", responseSha256=_digest(raw), responseBytes=size)
        result = validate(raw, available)
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
    except Exception as error:
        # No raw prompt, partial private text or model-issued human approval leaks.
        publish(
            "failed", responseSha256=_digest(raw) if raw else "", error=str(error)[:500]
        )
        raise
