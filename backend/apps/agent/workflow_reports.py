"""Immutable, evidence-bound Markdown reports for completed research workflows."""

from __future__ import annotations

import csv
import hashlib
import html
import json
from pathlib import Path

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F

from apps.audit.service import log_operation
from apps.catalog.models import DataResource
from apps.catalog.permissions import filter_accessible
from apps.compute.access import permission, require_actor
from apps.compute.models import ComputeImport, ComputeOutput
from apps.compute.packages import ComputeError, checksum
from apps.core.storage import app_path, table_data_path
from .compute_tools import authorized_task
from .models import AgentWorkflow
from .tools import resolve_resource

CONTENT_TYPE = "text/markdown"
PREVIEW_LIMIT = 200_000
MAX_REPORT_BYTES = 2 * 1024 * 1024
REPORT_NAMES = {
    "geology_map_review": "检查报告",
    "ecology_investigation": "生态风险分析报告",
    "geology_correction": "地质纠偏分析报告",
    "geology_age_correction": "地质年代纠偏分析报告",
}
DECISION_FIELDS = (
    ("problem", "分析问题"),
    ("findings", "发现了什么"),
    ("judgement", "当前判断"),
    ("algorithmReason", "算法选择依据"),
    ("resultSummary", "实际结果"),
    ("uncertainties", "待补证据"),
    ("nextAction", "下一步"),
)
ACTION_NAMES = {
    "finish": "分析完成",
    "request_review": "请求复核",
    "execute_operator": "继续计算",
}


def _text(value: object, maximum: int = 6000) -> str:
    return html.escape(str(value)[:maximum], quote=False).replace("\r", "")


def _cell(value: object) -> str:
    return _text(value, 1000).replace("|", "\\|").replace("\n", " ")


def _paths(workflow: AgentWorkflow) -> tuple[Path, Path, str]:
    relative = f"workflow-reports/{workflow.id}/report.md"
    return (
        table_data_path(relative),
        table_data_path(f"workflow-reports/{workflow.id}/metadata.json"),
        relative,
    )


def _resource(user, identity: int) -> DataResource:
    value = filter_accessible(
        DataResource.objects.filter(pk=identity, status="active"), user
    ).first()
    if value is None:
        raise PermissionDenied("报告引用的数据权限已撤回或资源已停用")
    return value


def authorize_context(workflow: AgentWorkflow, user, policy: dict) -> list:
    """Recheck real task inputs and all imported outputs before exposing a report."""
    if workflow.status != "succeeded":
        raise ComputeError("MH-workflow完成后才能生成或读取报告", 409)
    ids = list(
        dict.fromkeys(
            workflow.steps.exclude(compute_task_id=None).values_list(
                "compute_task_id", flat=True
            )
        )
    )
    tasks = []
    for identity in ids:
        task = authorized_task(user, identity, policy)
        if task.owner_id != workflow.owner_id or task.status != "succeeded":
            raise PermissionDenied("报告计算记录不属于本次已完成流程")
        tasks.append(task)
    outputs = list(ComputeOutput.objects.filter(task__in=tasks).order_by("id"))
    output_ids = {output.id for output in outputs}
    if set(workflow.result_ids) - output_ids:
        raise PermissionDenied("报告结果不能对应本次真实计算记录")
    for record in ComputeImport.objects.filter(output__in=outputs):
        if record.resource_id:
            _resource(user, record.resource_id)
    for identity in workflow.result_resource_ids:
        _resource(user, identity)
    return tasks


def _decision(lines: list[str], value: dict) -> None:
    if not isinstance(value, dict):
        return
    for key, label in DECISION_FIELDS:
        item = value.get(key)
        if not item:
            continue
        lines.extend([f"**{label}**", ""])
        if isinstance(item, list):
            lines.extend(f"- {_text(text, 2000)}" for text in item[:30])
        elif isinstance(item, str):
            lines.append(_text(ACTION_NAMES.get(item, item)))
        lines.append("")


def _table_rows(output: ComputeOutput) -> list[str]:
    """Only read a bounded, checksummed actual CSV; never raw plan/result metadata."""
    if output.kind != "table" or not output.file_name.lower().endswith(".csv"):
        return []
    path = app_path(output.path)
    if output.expired or not path.is_file() or path.stat().st_size > 64 * 1024:
        return ["完整统计表见对应结果文件。", ""]
    if checksum(path) != output.checksum:
        raise ComputeError("实际统计结果文件内容已变化，请核对计算记录", 409)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        if not columns or len(columns) > 24:
            return ["完整统计表见对应结果文件。", ""]
        rows = []
        for index, row in enumerate(reader):
            if index == 40:
                break
            rows.append(row)
    lines = [
        "| " + " | ".join(_cell(col) for col in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_cell(row.get(col, "")) for col in columns) + " |"
        for row in rows
    )
    lines.extend(["", "报告展示前 40 行以内；完整数据保留在原统计表中。", ""])
    return lines


def render_report(workflow: AgentWorkflow, user, policy: dict, tasks: list) -> bytes:
    if workflow.workflow_type == "geology_map_review":
        from .geology_review_report import render_geology_report

        return render_geology_report(workflow, tasks)

    from .demo_workflow import stage_title
    from .research_presets import ROLE_LABELS

    title = REPORT_NAMES.get(workflow.workflow_type, "MH-workflow报告")
    lines = [
        f"# {title}",
        "",
        f"项目：{_text(workflow.project_tag.name)}",
        "",
        f"分析目标：{_text(workflow.goal)}",
        "",
        f"完成时间：{workflow.updated_at.isoformat()}",
        "",
        f"使用模型：{_text(workflow.model)}",
        "",
        "## 结论与建议",
        "",
    ]
    final = workflow.plan.get("finalDecision")
    if isinstance(final, dict):
        _decision(lines, final)
    else:
        lines.extend([_text(workflow.detail or "本次计算已完成"), ""])
    lines.extend(["## 输入资料与参数", ""])
    inputs = workflow.plan.get("inputs", {})
    if isinstance(inputs, dict):
        for role, identity in inputs.items():
            if type(identity) is int:
                resource = resolve_resource(user, policy, identity)
                lines.append(
                    f"- {_text(ROLE_LABELS.get(role, role))}：{_text(resource.name)}"
                )
    lines.append("")
    for task in tasks:
        lines.extend(
            [
                f"### {_text(task.name)}",
                "",
                f"算法：{_text(task.version.algorithm.name)} {task.version.version}",
                "",
                "| 参数 | 实际取值 |",
                "| --- | --- |",
            ]
        )
        parameter_labels = {
            spec["key"]: spec.get("label", spec["key"])
            for spec in task.version.manifest.get("parameters", [])
            if isinstance(spec, dict) and "key" in spec
        }
        for key, value in task.parameters.items():
            lines.append(
                f"| {_cell(parameter_labels.get(key, key))} | {_cell(value)} |"
            )
        lines.append("")
    lines.extend(["## 证据与判断过程", ""])
    for index, stage in enumerate(workflow.plan.get("stages", []), 1):
        decision = stage.get("decision") if isinstance(stage, dict) else None
        if not isinstance(decision, dict):
            continue
        stage_label = stage_title(workflow, stage) if stage.get("name") else "分析判断"
        lines.extend(
            [
                f"### 第 {index} 步：{_text(stage.get('title') or stage_label)}",
                "",
            ]
        )
        _decision(lines, decision)
    lines.extend(["## 引用知识", ""])
    for evidence in workflow.evidence:
        lines.extend(
            [
                f"### {_text(evidence.get('title', '知识依据'))}（修订 {evidence.get('revision', '')}）",
                "",
                _text(evidence.get("statement", "")),
                "",
            ]
        )
        for label, key in (("适用条件", "conditions"), ("例外", "exceptions")):
            values = evidence.get(key, [])
            if values:
                lines.extend(
                    [f"{label}：" + "；".join(_text(v, 2000) for v in values[:20]), ""]
                )
        for source in evidence.get("sources", [])[:20]:
            if isinstance(source, dict):
                parts = [
                    source.get(key)
                    for key in ("title", "locator", "url", "excerpt")
                    if source.get(key)
                ]
                lines.append(
                    "- 来源：" + "；".join(_text(part, 2000) for part in parts)
                )
        lines.append("")
    if not workflow.evidence:
        lines.extend(["本次流程未登记知识引用。", ""])
    lines.extend(["## 生成文件与实际统计", ""])
    for task in tasks:
        for output in task.outputs.order_by("id"):
            record = ComputeImport.objects.filter(output=output).first()
            location = "保留于计算任务结果，可在任务中预览或下载"
            if record and record.resource_id and record.status == "ready":
                resource = _resource(user, record.resource_id)
                location = f"{workflow.project_tag.name} / 数据资源 / 计算结果 / {resource.name}"
            lines.extend(
                [
                    f"### {_text(output.label)}",
                    "",
                    f"文件：{_text(output.file_name)}（{output.size_bytes:,} 字节）",
                    "",
                    f"计算来源：{_text(task.name)}；算法版本 {task.version.version}；计算已成功。",
                    "",
                    f"保存位置：{_text(location)}",
                    "",
                    f"文件校验：{output.checksum}",
                    "",
                ]
            )
            lines.extend(_table_rows(output))
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def load_report(workflow: AgentWorkflow, user) -> tuple[dict, Path]:
    path, metadata_path, _ = _paths(workflow)
    if not path.is_file() or not metadata_path.is_file():
        raise ComputeError("尚未生成报告，请先生成", 404)
    if metadata_path.stat().st_size > 4096 or path.stat().st_size > MAX_REPORT_BYTES:
        raise ComputeError("报告文件大小异常", 409)
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ComputeError("报告登记文件损坏", 409) from exc
    keys = {"schemaVersion", "fileName", "label", "sizeBytes", "checksum", "resourceId"}
    if not isinstance(data, dict) or set(data) != keys or data["schemaVersion"] != 1:
        raise ComputeError("报告登记格式无效", 409)
    if path.stat().st_size != data["sizeBytes"] or checksum(path) != data["checksum"]:
        raise ComputeError("报告内容与登记校验不一致", 409)
    if data["resourceId"] is not None:
        resource = _resource(user, data["resourceId"])
        if resource.source != f"workflow-report:{workflow.id}":
            raise PermissionDenied("报告入库关联无效")
    return data, path


def _write_metadata(path: Path, data: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def generate_report(workflow: AgentWorkflow, user, policy: dict, request=None) -> dict:
    with transaction.atomic():
        # SQLite ignores select_for_update: obtain its writer lock without changing state.
        AgentWorkflow.objects.filter(pk=workflow.id).update(detail=F("detail"))
        workflow = AgentWorkflow.objects.select_for_update().get(pk=workflow.id)
        tasks = authorize_context(workflow, user, policy)
        path, metadata_path, _ = _paths(workflow)
        if metadata_path.is_file():
            return load_report(workflow, user)[0]
        raw = render_report(workflow, user, policy, tasks)
        if len(raw) > MAX_REPORT_BYTES:
            raise ComputeError("本次报告超过大小上限，请先减少流程输出", 409)
        label = REPORT_NAMES.get(workflow.workflow_type, "MH-workflow报告")
        data = {
            "schemaVersion": 1,
            "fileName": label + ".md",
            "label": label,
            "sizeBytes": len(raw),
            "checksum": hashlib.sha256(raw).hexdigest(),
            "resourceId": None,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(raw)
        temporary.replace(path)
        _write_metadata(metadata_path, data)
        log_operation(
            user,
            "智能体",
            "生成分析报告",
            "success",
            label,
            request,
            event_code="agent.workflow_report.generate",
            target_code=str(workflow.id),
        )
        return data


def import_report(workflow: AgentWorkflow, user, policy: dict, request=None) -> dict:
    require_actor(user, workflow.project_tag_id, "catalog.add_dataresource")
    with transaction.atomic():
        AgentWorkflow.objects.filter(pk=workflow.id).update(detail=F("detail"))
        data, _ = load_report(workflow, user)
        if data["resourceId"] is not None:
            return data
        _, metadata_path, relative = _paths(workflow)
        source = f"workflow-report:{workflow.id}"
        resource = DataResource.objects.filter(source=source).first()
        if resource:
            _resource(user, resource.id)
        else:
            resource = DataResource.objects.create(
                project_tag_id=workflow.project_tag_id,
                name=data["label"],
                code=f"wf-report-{workflow.id.hex}",
                data_type="document",
                file_format="MD",
                storage_path="table/" + relative,
                source=source,
                owner_only=True,
                maintainer=user,
                is_compute_result=True,
                size_bytes=data["sizeBytes"],
                description="依据本次已完成MH-workflow的公开判断、知识引用与真实计算结果生成。",
                quality_note=f"SHA256: {data['checksum']}",
            )
            log_operation(
                user,
                "智能体",
                "报告入库",
                "success",
                resource.name,
                request,
                event_code="agent.workflow_report.import",
                target_type="DataResource",
                target_id=resource.id,
                target_code=str(workflow.id),
                target_name=resource.name,
            )
        data["resourceId"] = resource.id
        _write_metadata(metadata_path, data)
        return data


def report_json(workflow: AgentWorkflow, user, data: dict) -> dict:
    resource = _resource(user, data["resourceId"]) if data["resourceId"] else None
    base = f"/api/agent/workflows/{workflow.id}/report/"
    return {
        "fileName": data["fileName"],
        "label": data["label"],
        "contentType": CONTENT_TYPE,
        "sizeBytes": data["sizeBytes"],
        "checksum": data["checksum"],
        "previewUrl": base + "preview/",
        "downloadUrl": base + "download/",
        "resourceId": resource.id if resource else None,
        "resourceName": resource.name if resource else "",
        "resourceLocation": f"{workflow.project_tag.name} / 数据资源 / 计算结果 / {resource.name}"
        if resource
        else "",
        "canDownload": permission(user, "catalog.export_dataresource"),
        "canImport": permission(user, "catalog.add_dataresource"),
    }
