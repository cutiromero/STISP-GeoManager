"""Prepare a confirmed geology decision table from one inspectable result."""

import csv
import hashlib
import io
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.db import connection, transaction
from django.db.models import F

from apps.catalog.models import DataResource
from apps.compute.access import require_actor
from apps.compute.packages import ComputeError
from apps.core.storage import table_data_path

APPROVAL_SOURCE = "hermes-geology-approval:"
IDENTITY_FIELDS = ("issue_id", "feature_id", "rule_id", "rule_version", "snapshot_hash")
DECISION_FIELDS = (*IDENTITY_FIELDS, "action", "target_code", "weight", "reason")


def saved_decisions(session, user, task, selections, approval_digest=None):
    from .compute_result_tools import check_output_file

    require_actor(user, session.project_tag_id, "catalog.add_dataresource")
    if task.version.algorithm.identifier != "geology-multi-check":
        raise ComputeError("请选择本会话的地质一致性检查任务")
    output = task.outputs.filter(key="issues", kind="table").first()
    if output is None:
        raise ComputeError("请先读取检查任务的真实问题清单")
    path = check_output_file(output, task)
    wanted = {item["issueId"]: item for item in selections}
    if len(wanted) != len(selections):
        raise ComputeError("请为同一问题保留一项处置")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        selected = {
            row["issue_id"]: row
            for row in csv.DictReader(stream)
            if row.get("issue_id") in wanted
        }
    if selected.keys() != wanted.keys():
        raise ComputeError("请从实际问题清单选择处置对象")
    rows = []
    objects = set()
    for item in selections:
        row = selected[item["issueId"]]
        action = item["action"]
        if action not in json.loads(row["allowed_actions_json"]):
            raise ComputeError(f"请选择图斑 {row['feature_id']} 的可用处置")
        target = (
            row["target_code"] if action in {"set_code", "merge", "reclassify"} else ""
        )
        object_key = (row["element"], row["feature_id"])
        if object_key in objects:
            raise ComputeError(f"请为同一对象 {row['feature_id']} 选择一项处置")
        objects.add(object_key)
        weight = (
            item.get("weight", 0.5)
            if action == "downweight"
            else 0
            if action == "exclude"
            else 1
        )
        if action == "downweight" and not 0 < weight < 1:
            raise ComputeError(
                f"请为对象 {row['feature_id']} 选择大于 0 且小于 1 的权重"
            )
        reason = item.get("reason", "").strip() or "采用检查建议"
        if row["status"] in {"review", "exception"} and action not in {
            "keep",
            "review",
        }:
            if (
                action != row.get("candidate_action")
                and not (row["feature_id"].startswith("AG-") and action == "downweight")
            ) or target != row.get("candidate_target_code", ""):
                raise ComputeError(f"请查看对象 {row['feature_id']} 的候选动作与目标")
            reason = "用户裁定（规则为待裁定/例外）：" + reason
        else:
            reason = "用户裁定：" + reason
        rows.append(
            {
                **{key: row[key] for key in IDENTITY_FIELDS},
                "action": action,
                "target_code": target,
                "weight": weight,
                "reason": reason,
            }
        )
    raw = io.StringIO(newline="")
    writer = csv.DictWriter(raw, fieldnames=DECISION_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    data = raw.getvalue().encode()
    digest = hashlib.sha256(
        str(session.pk).encode() + output.checksum.encode() + data
    ).hexdigest()
    marker = f"{APPROVAL_SOURCE}{session.pk.hex}:{digest}"
    relative = f"hermes/geology/{session.pk.hex}/{digest}.csv"
    destination = table_data_path(relative)
    if approval_digest is None:
        existing = DataResource.objects.filter(
            source=marker, maintainer=user, status="active"
        ).first()
        if (
            existing is not None
            and destination.is_file()
            and destination.read_bytes() == data
        ):
            return {
                "resourceId": existing.pk,
                "checkTaskId": str(task.pk),
                "count": len(rows),
            }
        summary = "对工作副本应用 " + "；".join(
            f"{row['feature_id']} {row['action']}"
            + (f" → {row['target_code']}" if row["target_code"] else "")
            + (f" 权重 {row['weight']}" if row["action"] == "downweight" else "")
            + f"（{row['reason'].removeprefix('用户裁定：')}）"
            for row in rows
        )
        return {"approvalDigest": digest, "approvalSummary": summary}
    if approval_digest != digest:
        raise ComputeError("处置范围已更新，请查看当前内容并确认", 409)

    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file():
        with NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
            temporary.write(data)
            temporary_path = temporary.name
        tmp = Path(temporary_path)
        try:
            tmp.replace(destination)
        finally:
            tmp.unlink(missing_ok=True)
    if destination.read_bytes() != data:
        raise ComputeError("处置表校验未通过，请按当前检查结果重新确认", 409)

    with transaction.atomic():
        if connection.vendor == "sqlite":
            DataResource.objects.filter(code=f"hermes-decision-{digest[:40]}").update(
                size_bytes=F("size_bytes")
            )
        resource, _ = DataResource.objects.get_or_create(
            code=f"hermes-decision-{digest[:40]}",
            defaults={
                "name": f"地质处置表 {digest[:8]}",
                "data_type": "table",
                "file_format": "CSV",
                "storage_path": "table/" + relative,
                "source": marker,
                "owner_only": True,
                "maintainer": user,
                "item_count": len(rows),
                "size_bytes": len(data),
            },
        )
        if resource.source != marker or resource.maintainer_id != user.pk:
            raise ComputeError("请选择本会话的处置表", 409)
    return {"resourceId": resource.pk, "checkTaskId": str(task.pk), "count": len(rows)}
