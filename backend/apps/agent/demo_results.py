"""Bounded, authorized Demo result reading and validated edit proposals."""

from __future__ import annotations

import csv
import io
import re

from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.catalog.models import DataResource
from apps.compute.packages import ComputeError, checksum
from apps.compute.access import require_actor
from apps.core.storage import app_path, table_data_path
from .compute_tools import authorized_task
from .tools import resolve_resource, frame

EDIT_FIELDS = (
    "feature_id",
    "field",
    "old_value",
    "new_value",
    "evidence_id",
    "rule_id",
)


def read_output(workflow, user, policy, output) -> dict:
    task = authorized_task(user, output.task_id, policy)
    if (
        task.owner_id != workflow.owner_id
        or not workflow.steps.filter(compute_task_id=task.id).exists()
    ):
        raise PermissionDenied("结果不属于当前分析流程")
    path = app_path(output.path)
    if task.status != "succeeded" or output.expired or not path.is_file():
        raise ComputeError("结果尚未成功或已过期")
    if path.is_symlink() or checksum(path) != output.checksum:
        raise ComputeError("结果文件内容已变化，已停止后续分析")
    result = {
        "outputId": output.id,
        "taskId": str(task.id),
        "key": output.key,
        "kind": output.kind,
        "checksum": output.checksum,
        "metadata": output.metadata,
        "rows": [],
    }
    if output.kind == "table":
        if path.stat().st_size > 64 * 1024:
            raise ComputeError("Demo统计表超过64 KiB，请先整理所需统计")
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or len(reader.fieldnames) > 64:
                raise ComputeError("Demo统计表列数无效")
            rows = list(reader)
        if len(rows) > 100 or any(
            len(str(value)) > 2000 for row in rows for value in row.values()
        ):
            raise ComputeError("Demo统计表超过100行或单元格读取上限")
        result.update(
            columns=reader.fieldnames, rows=rows, rowCount=len(rows), scope="all"
        )
    return result


def read_results(workflow, user, policy, task) -> list[dict]:
    outputs = list(task.outputs.order_by("id"))
    if not outputs:
        raise ComputeError("任务没有可读取的实际输出")
    return [read_output(workflow, user, policy, output) for output in outputs]


def validate_edits(edits, results) -> list[dict]:
    if not isinstance(edits, list) or len(edits) > 30:
        raise ComputeError("修改计划最多包含30项有依据的操作")
    issues = [
        row for item in results for row in item.get("rows", []) if "feature_id" in row
    ]
    allowed = {
        tuple(str(row.get(key, "")) for key in EDIT_FIELDS): row
        for row in issues
        if row.get("status") == "repairable" and row.get("field") != "geometry"
    }
    if not edits and allowed:
        raise ComputeError("仍有可修复属性，请提出修改计划或请求人工复核")
    accepted, targets = [], set()
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) - {*EDIT_FIELDS, "reason"}:
            raise ComputeError("修改计划包含未允许字段")
        values = {key: str(edit.get(key, "")) for key in EDIT_FIELDS}
        if any(
            (not value and key != "old_value") or len(value) > 500
            for key, value in values.items()
        ):
            raise ComputeError("修改计划的对象、原值、新值或证据不完整")
        issue = allowed.get(tuple(values[key] for key in EDIT_FIELDS))
        if issue is None:
            raise ComputeError("修改计划不能对应实际检查中的可修复问题")
        signature = issue.get("input_checksum", "")
        if not isinstance(signature, str) or not re.fullmatch(
            r"[a-f0-9]{64}", signature
        ):
            raise ComputeError("实际问题清单缺少稳定输入内容签名")
        target = (values["feature_id"], values["field"])
        if target in targets:
            raise ComputeError("同一对象字段存在重复修改")
        targets.add(target)
        reason = edit.get("reason", "")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ComputeError("每项修改需要简短、明确的依据")
        accepted.append({**values, "reason": reason, "input_checksum": signature})
    return accepted


def create_changes(workflow, user, policy, edits, results) -> DataResource:
    """One private, stable CSV per confirmed workflow edit stage."""
    rows = validate_edits(edits, results)
    require_actor(user, workflow.project_tag_id, "catalog.add_dataresource")
    source = f"demo-changes:{workflow.id}"
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=[*EDIT_FIELDS, "reason", "input_checksum"]
    )
    writer.writeheader()
    writer.writerows(rows)
    raw = buffer.getvalue().encode("utf-8")
    relative = f"demo/workflows/{workflow.id}/changes.csv"
    path = table_data_path(relative)
    with transaction.atomic():
        # Reserve the SQLite writer before inspecting the stable resource marker.
        from .models import AgentWorkflow

        AgentWorkflow.objects.filter(pk=workflow.id).update(
            detail="正在固定受约束修改计划"
        )
        existing = DataResource.objects.filter(source=source).first()
        if existing:
            resolve_resource(user, policy, existing.id)
            if path.read_bytes() != raw:
                raise ComputeError("已固定的修改表与当前计划不一致")
            return existing
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ComputeError("修改计划文件已有不同内容")
        path.write_bytes(raw)
        return DataResource.objects.create(
            name="模型提出的受约束修改表",
            code=f"demo-changes-{workflow.id.hex[:24]}",
            data_type="table",
            file_format="CSV",
            storage_path="table/" + relative,
            source=source,
            description="依据本次实际问题清单和允许规则生成，供编辑算子逐项再校验。",
            maintainer=user,
            owner_only=True,
            size_bytes=len(raw),
            item_count=len(rows),
        )


def resource_context(workflow, user, policy) -> list[dict]:
    """Expose actual evidence tables and role metadata; never reference truth files."""
    items = []
    for role, identity in workflow.plan["inputs"].items():
        resource = resolve_resource(user, policy, identity, workflow.resource_ids)
        item = {
            "role": role,
            "resourceId": identity,
            "title": resource.name,
            "revision": resource.updated_at.isoformat(),
            "description": resource.description[:1200],
        }
        if resource.data_type == "table":
            data, info = frame(resource)
            if len(data) > 100 or info.get("scope") == "prefix_sample":
                raise ComputeError("Demo依据表超过完整读取范围，请整理成100行以内")
            from .tools import clean

            item.update(rows=clean(data.to_dict(orient="records")), scope="all")
        items.append(item)
    return items
