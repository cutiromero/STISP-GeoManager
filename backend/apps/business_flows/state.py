"""Small durable node state over the platform's existing workflow records."""

from copy import deepcopy
import hashlib
import json

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.agent.models import AgentRun, RunEvent
from apps.agent.workflow_controls import save_workflow_state, locked_workflow

# Configuration: bounded public history; full node results stay on the workflow.
MAX_EVENTS = 120
MAX_EVENT_TEXT = 1000
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


class WorkflowControlChanged(Exception):
    """A newer explicit control owns the state; a late model cannot overwrite it."""


def binding(workflow):
    value = workflow.parameters.get("_businessFlow")
    if not isinstance(value, dict) or not isinstance(
        value.get("definitionSnapshot"), dict
    ):
        raise PermissionDenied("业务流缺少服务器冻结的发布版本")
    return value


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def initial_state(definition):
    return {
        "revision": 0,
        "events": [],
        "nodes": {
            node["id"]: {
                "nodeId": node["id"],
                "status": "pending",
                "attempt": 0,
                "executor": {"status": "pending"},
                "reviewer": {
                    "status": "pending" if node["review"]["ai"] else "not_required"
                },
                "outputs": {},
                "attempts": [],
                "human": {
                    "required": bool(
                        node["review"]["human"] or node["kind"] == "human"
                    ),
                    "status": "pending"
                    if node["review"]["human"] or node["kind"] == "human"
                    else "not_required",
                    "reason": "",
                },
            }
            for node in definition["nodes"]
        },
    }


def state(workflow):
    if workflow.workflow_type != "business_flow":
        return binding(workflow).setdefault(
            "state", initial_state(binding(workflow)["definitionSnapshot"])
        )
    return workflow.plan.setdefault(
        "businessFlow", initial_state(binding(workflow)["definitionSnapshot"])
    )


def parent_run(workflow):
    identity = binding(workflow).get("runId")
    return AgentRun._base_manager.select_related("conversation").get(
        pk=identity,
        owner_id=workflow.owner_id,
        project_tag_id=workflow.project_tag_id,
        research_workflow_id=workflow.id,
    )


def parent_status(workflow):
    if workflow.status in TERMINAL:
        return workflow.status
    if workflow.status == "waiting_approval":
        return "waiting_review"
    if workflow.status == "paused":
        return "waiting_input"
    # The workflow queue owns this run; the ordinary agent queue must not claim it.
    return "waiting_compute"


def interrupt_actor_audits(workflow, action):
    if action not in {"pause", "cancel"}:
        return
    for item in state(workflow)["nodes"].values():
        for actor in ("executor", "reviewer"):
            value = item.get(actor, {})
            if value.get("status") in {
                "preparing",
                "running",
                "requesting",
                "responding",
                "validating",
            }:
                value["status"] = "paused" if action == "pause" else "cancelled"
                value["reason"] = "用户已暂停或停止本次请求"
        for attempt in item.get("attempts", []):
            if attempt.get("status") in {
                "preparing",
                "requesting",
                "responding",
                "validating",
            }:
                attempt.update(
                    status="interrupted" if action == "pause" else "cancelled",
                    controlAction=action,
                )


def emit(workflow, actor, node_id, kind, message, *, status=None, data=None, save=True):
    if workflow.workflow_type != "business_flow" and node_id:
        from .runtime import canonical_current_node

        if node_id not in state(workflow)["nodes"]:
            node_id = canonical_current_node(workflow)
    value = state(workflow)
    value["revision"] += 1
    record = {
        "id": value["revision"],
        "nodeId": node_id,
        "actor": actor,
        "kind": kind,
        "status": status or workflow.status,
        "message": str(message)[:MAX_EVENT_TEXT],
        "createdAt": timezone.now().isoformat(),
    }
    if data:
        record["data"] = deepcopy(data)
    value["events"] = [*value["events"], record][-MAX_EVENTS:]
    workflow.parameters["_businessFlow"]["revision"] = value["revision"]
    if save:
        persist(workflow, event=record)
    return record


def persist(workflow, *, event=None):
    with transaction.atomic():
        current = locked_workflow(workflow.pk)
        if current.policy_snapshot.get(
            "businessFlowControlEpoch", 0
        ) != workflow.policy_snapshot.get("businessFlowControlEpoch", 0):
            raise WorkflowControlChanged("业务流已有更新的暂停、恢复或停止决定")
        save_workflow_state(workflow, acknowledge_pause=True)
        bind = binding(workflow)
        updates = {
            "status": parent_status(workflow),
            "detail": workflow.detail[:300],
            "heartbeat": timezone.now(),
            "updated_at": timezone.now(),
        }
        if workflow.status == "succeeded":
            updates["answer"] = state(workflow).get("answer", workflow.detail)
        AgentRun._base_manager.filter(
            pk=bind["runId"],
            owner_id=workflow.owner_id,
            project_tag_id=workflow.project_tag_id,
            research_workflow_id=workflow.id,
        ).update(**updates)
        if event:
            RunEvent.objects.create(
                run_id=bind["runId"],
                kind="business_flow_state",
                text=json.dumps(event, ensure_ascii=False),
            )
