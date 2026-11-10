"""Read actual code on demand; clarification never approves a scientific node."""

import hashlib

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.agent.workflow_controls import locked_workflow
from apps.agent.workflow_resources import resolve_workflow_resource
from apps.compute.packages import ComputeError
from .state import state, emit, digest
from .runtime import authorize


def entry_for(workflow, role):
    if not isinstance(role, str) or not 1 <= len(role) <= 128:
        raise ValidationError("资料衔接键无效")
    entry = next(
        (
            row
            for row in workflow.plan.get("inputAdaptations", [])
            if row["role"] == role
        ),
        None,
    )
    if entry is None:
        raise ComputeError("本次任务没有对应的资料衔接记录", 404)
    return entry


def detail(user, workflow, role, attempt=None):
    current_policy = authorize(user, workflow, history=True)
    entry = entry_for(workflow, role)
    source_rows = entry.get("sources") or [{"id": entry["sourceId"]}]
    for source in source_rows:
        resolve_workflow_resource(
            user, current_policy, source["id"], workflow, history=True
        )
    scripts = [*entry.get("scriptHistory", []), entry.get("scriptCurrent", {})]
    scripts = [row for row in scripts if row.get("code")]
    if attempt is not None:
        if type(attempt) is not int or not 1 <= attempt <= 3:
            raise ValidationError("脚本尝试序号无效")
        scripts = [row for row in scripts if row["attempt"] == attempt]
    if not scripts:
        raise ComputeError("尚未生成对应的实际适配脚本", 409)
    script = max(scripts, key=lambda row: row["attempt"])
    if hashlib.sha256(script["code"].encode()).hexdigest() != script["sha256"]:
        raise ComputeError("脚本审计记录与实际内容不一致", 409)
    diagnostics = [
        value
        for value in [script.get("error"), script.get("review", {}).get("reason")]
        if value
    ]
    return {
        "role": role,
        "attempt": script["attempt"],
        "language": "python",
        "code": script["code"],
        "sha256": script["sha256"],
        "summary": script["summary"],
        "status": script["status"],
        "targetType": script["targetType"],
        "sourceIds": [row["id"] for row in source_rows],
        "diagnostics": diagnostics[:8],
    }


def clarify(user, workflow, value):
    authorize(user, workflow)
    role, feedback, key = (
        value.get(name) for name in ("role", "feedback", "idempotencyKey")
    )
    if (
        not isinstance(feedback, str)
        or not 1 <= len(feedback.strip()) <= 4000
        or not isinstance(key, str)
        or not 8 <= len(key) <= 80
    ):
        raise ValidationError("请填写本次资料说明并使用有效幂等键")
    with transaction.atomic():
        current = locked_workflow(workflow.pk)
        authorize(user, current)
        data = state(current)
        receipts = data.setdefault("inputClarificationReceipts", {})
        fingerprint = digest(
            {name: value.get(name) for name in ("role", "feedback", "revision")}
        )
        if key in receipts:
            if receipts[key] != fingerprint:
                raise ComputeError("资料说明幂等键冲突", 409)
            return current
        entry = entry_for(current, role)
        if (
            current.status != "waiting_approval"
            or entry["status"] != "needs_clarification"
            or str(value.get("revision")) != str(data["revision"])
        ):
            raise ComputeError("当前待说明项或任务修订已变化，请刷新查看", 409)
        previous = entry.setdefault("scriptClarifications", [])
        if len(previous) >= 3:
            raise ComputeError(
                "资料说明仍不足以完成衔接，请保留记录并调整输入后重新开始"
            )
        previous.append(
            {
                "question": entry.get("scriptQuestion", ""),
                "feedback": feedback.strip(),
                "userId": user.pk,
                "createdAt": timezone.now().isoformat(),
            }
        )
        entry["scriptFeedback"] = feedback.strip()
        entry.pop("scriptQuestion", None)
        entry.update(status="needs_script", scriptStatus="planned")
        current.status = "queued"
        current.policy_snapshot["businessFlowControlEpoch"] = (
            current.policy_snapshot.get("businessFlowControlEpoch", 0) + 1
        )
        receipts[key] = fingerprint
        current.save(update_fields=["policy_snapshot", "updated_at"])
        nodes = current.parameters["_businessFlow"]["definitionSnapshot"]["nodes"]
        emit(
            current,
            "user",
            entry.get("nodeId", nodes[0]["id"]),
            "input_clarified",
            "已补充资料说明，智能体将继续衔接；科研批准状态保持原记录",
        )
        return current
