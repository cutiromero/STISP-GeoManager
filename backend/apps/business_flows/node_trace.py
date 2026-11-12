"""Read one authorized node's actual model activity and tool actions on demand."""

from copy import deepcopy
import json

from django.core.exceptions import ValidationError

from apps.agent.decision_audit import response_artifact
from apps.agent.model_activity import ACTIVITY_KIND
from .runtime import authorize
from .state import TERMINAL, binding, state

# Configuration: reading a trace never changes task budgets or execution state.
PAGE_SIZE = 5
MAX_OFFSET = 1000
THINKING_LIMIT = 12000


def _safe(value):
    return json.loads(
        response_artifact(json.dumps(value, ensure_ascii=False))["content"]
    )


def _record(record):
    activity = record.output_refs.get("modelActivity", {})
    response = record.output_refs.get("modelResponse")
    return {
        "id": str(record.pk),
        "role": record.action.get("actor", "executor"),
        "attempt": activity.get("attempt", record.action.get("attempt", 1)),
        "status": "failed"
        if record.status == "failed"
        else activity.get("status", record.status),
        "model": activity.get("modelName", ""),
        "thinkingEnabled": bool(activity.get("thinkingEnabled")),
        "reasoningEffort": activity.get("reasoningEffort", "medium"),
        "thinkingText": response_artifact(activity.get("thinkingText", ""))["content"],
        "thinkingChars": activity.get(
            "thinkingChars", len(activity.get("thinkingText", ""))
        ),
        "thinkingTruncated": bool(activity.get("truncated")),
        "response": response_artifact(response["content"])
        if isinstance(response, dict) and isinstance(response.get("content"), str)
        else None,
        "startedAt": record.started_at.isoformat(),
        "finishedAt": record.finished_at.isoformat() if record.finished_at else None,
    }


def _historical(item):
    """Older node state has bounded thinking and validated results, not raw replies."""
    result = []
    for role in ("reviewer", "executor"):
        actor = item.get(role, {})
        thinking = actor.get("thinking", "")
        if not thinking and actor.get("status") in {None, "pending", "not_required"}:
            continue
        audit = actor.get("audit", {})
        result.append(
            {
                "id": "historical-" + role,
                "role": role,
                "attempt": item.get("attempt", 0),
                "status": actor.get("status", "pending"),
                "model": audit.get("modelName", actor.get("model", "")),
                "thinkingEnabled": bool(audit.get("thinkingEnabled", bool(thinking))),
                "reasoningEffort": audit.get("reasoningEffort", "medium"),
                "thinkingText": response_artifact(thinking[-THINKING_LIMIT:])[
                    "content"
                ],
                "thinkingChars": len(thinking),
                "thinkingTruncated": len(thinking) > THINKING_LIMIT,
                "response": None,
                "startedAt": None,
                "finishedAt": None,
                "structuredResult": _safe(
                    {
                        key: actor[key]
                        for key in (
                            "answer",
                            "summary",
                            "findings",
                            "limitations",
                            "reason",
                            "feedback",
                            "decision",
                        )
                        if key in actor
                    }
                ),
            }
        )
    return result


def node_trace(user, workflow, node_id, *, offset=0):
    authorize(user, workflow, history=workflow.status in TERMINAL)
    nodes = {
        node["id"]: node for node in binding(workflow)["definitionSnapshot"]["nodes"]
    }
    if node_id not in nodes or type(offset) is not int or not 0 <= offset <= MAX_OFFSET:
        raise ValidationError("节点或记录分页无效")
    item = state(workflow)["nodes"][node_id]
    records = list(
        workflow.steps.filter(kind=ACTIVITY_KIND, action__nodeId=node_id).order_by(
            "-sequence", "-id"
        )[offset : offset + PAGE_SIZE + 1]
    )
    historical = not records and offset == 0
    requests = (
        _historical(item)
        if historical
        else [_record(row) for row in records[:PAGE_SIZE]]
    )
    actions = deepcopy(item.get("toolLoop", {}).get("history", []))
    evidence = item.get("toolLoop", {}).get("evidence", {})
    for action in actions:
        result = evidence.get(action.get("evidenceId"), {}).get("result")
        if result is not None:
            action["resultPreview"] = response_artifact(
                json.dumps(result, ensure_ascii=False)
            )["content"][:2000]
    return {
        "nodeId": node_id,
        "title": nodes[node_id]["title"],
        "requests": requests,
        "actions": _safe(actions),
        "historical": historical,
        "nextOffset": offset + PAGE_SIZE if len(records) > PAGE_SIZE else None,
    }
