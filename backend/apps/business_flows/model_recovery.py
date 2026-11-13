"""Shared model recovery checkpoints; guidance never grants execution authority."""

from copy import deepcopy

from django.core.exceptions import ValidationError

from apps.agent.business_flow_context import ContextReviewRequired
from .state import state

# Configuration: one current instruction, never an accumulating transcript.
MAX_GUIDANCE_CHARACTERS = 2000
MODEL_WAIT_KINDS = {
    "model_protocol_error",
    "model_response_error",
    "model_request_error",
    "review_rejected",
    "platform_error",
}


def model_wait(
    node_id, reason, *, actor="executor", kind="model_response_error", scope="node"
):
    return ContextReviewRequired(
        {
            "nodeId": node_id,
            "kind": kind,
            "actor": actor,
            "level": 0,
            "reason": str(reason)[:1000],
            "evidence": [],
            "requested": False,
            "diagnosticCode": kind.upper(),
            "requestScope": scope,
        }
    )


def save_guidance(workflow, node_id, value, recovery):
    feedback = value.get("feedback", "")
    if not isinstance(feedback, str) or len(feedback) > MAX_GUIDANCE_CHARACTERS:
        raise ValidationError("节点补充说明须为不超过2000字的文字")
    item = state(workflow)["nodes"][node_id]
    item["recoveryGuidance"] = {
        "instruction": feedback.strip(),
        "diagnostic": str(recovery.get("reason", ""))[:1000],
        "diagnosticCode": recovery.get("diagnosticCode", recovery.get("kind", "")),
        "actor": recovery.get(
            "actor",
            "reviewer"
            if recovery.get("kind") == "model_protocol_error"
            else "executor",
        ),
        "scope": recovery.get("requestScope", "node"),
    }
    if feedback.strip():
        values = state(workflow)
        identity = f"human-guidance-{node_id}-{values['revision'] + 1}"
        values.setdefault("recoveryNotes", {})[identity] = {
            "id": identity,
            "kind": "analysis",
            "title": "用户补充说明（不构成批准）",
            "result": {
                "text": feedback.strip(),
                "source": "explicit_user",
                "nodeId": node_id,
                "note": "用户说明不改变实际测量、资料权限或批准范围。",
            },
        }
        item["recoveryGuidance"]["evidenceId"] = identity
        if (
            item["recoveryGuidance"]["actor"] == "executor"
            and item["recoveryGuidance"]["scope"] == "node"
        ):
            item["userClarificationId"] = identity


def guidance_context(workflow, node_id, actor="executor", *, scope="node"):
    if not getattr(workflow, "parameters", {}).get("_businessFlow"):
        return None
    value = state(workflow)["nodes"].get(node_id, {}).get("recoveryGuidance")
    if not value or value.get("actor") != actor or value.get("scope", "node") != scope:
        return None
    return deepcopy(value)


def automatic_review_limit(item, node):
    return item.get("manualReviewBaseline", 0) + node["review"]["maxRevisions"] + 1


def clarification_evidence(workflow, node_id):
    if not getattr(workflow, "parameters", {}).get("_businessFlow"):
        return []
    values = state(workflow)
    item = values["nodes"].get(node_id, {})
    guidance = item.get("recoveryGuidance", {})
    identity = item.get("userClarificationId")
    if not identity or guidance.get("scope", "node") != "node":
        return []
    note = values.get("recoveryNotes", {}).get(identity)
    return [deepcopy(note)] if note else []


def archive_model_attempts(stage):
    attempts = stage.pop("modelAttempts", [])
    if attempts:
        stage.setdefault("modelBudgetHistory", []).append({"modelAttempts": attempts})


def prepare_revision(item, feedback, *, manual=False, preserve_computation=True):
    """Revise interpretation of retained outputs, preserving computation and budgets."""
    if manual:
        item["manualReviewBaseline"] = item["attempt"]
    item["revisionEvidence"] = deepcopy(item.get("outputs", {}).get("evidence", []))
    item.update(
        status="pending",
        feedback=feedback,
        reanalyzeExistingOutputs=True,
        executor={"status": "pending"},
        reviewer={"status": "pending"},
    )
    actual = item.get("computeTaskId") or item.get("toolLoop", {}).get(
        "successfulTaskId"
    )
    if not preserve_computation:
        item.pop("reanalyzeExistingOutputs", None)
        item.pop("computeTaskId", None)
    if not actual or not preserve_computation:
        item["outputs"] = {}
