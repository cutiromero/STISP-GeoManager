"""Short public map-review reports backed by actual task files and approvals."""

from __future__ import annotations

import csv
import html
import math

from apps.compute.packages import ComputeError, checksum
from apps.core.storage import app_path

PUBLIC_TERMS = {
    "师弟": "资料提供者",
    "精修图": "地质成果",
    "人工设错": "演示案例",
    "参考真值": "独立验收资料",
}


def text(value, maximum=1500):
    result = str(value)[:maximum]
    for internal, public in PUBLIC_TERMS.items():
        result = result.replace(internal, public)
    return html.escape(result, quote=False).replace("\r", "").replace("|", "\\|")


def number(value):
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ComputeError("检查报告缺少有效实际面积统计", 409) from exc
    if not math.isfinite(result):
        raise ComputeError("检查报告面积统计无效", 409)
    return result


def actual_table(task, key):
    output = task.outputs.filter(key=key, kind="table").first()
    if output is None:
        raise ComputeError("检查报告缺少实际计算表：" + key, 409)
    path = app_path(output.path)
    if (
        output.expired
        or not path.is_file()
        or path.is_symlink()
        or path.stat().st_size > 256 * 1024
    ):
        raise ComputeError("检查报告对应结果已过期或超过读取范围", 409)
    if checksum(path) != output.checksum:
        raise ComputeError("检查报告实际结果文件内容已变化", 409)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames) > 64:
            raise ComputeError("检查报告实际统计字段无效", 409)
        rows = list(reader)
    if len(rows) > 100 or any(None in row for row in rows):
        raise ComputeError("检查报告实际统计行无效或超过读取范围", 409)
    return rows


def actual_tasks(workflow, tasks):
    by_id = {str(task.id): task for task in tasks}
    result = {}
    for stage in workflow.plan.get("stages", []):
        if stage.get("name") not in {"check", "edit", "recheck"}:
            continue
        task = by_id.get(stage.get("taskId"))
        if task is None:
            raise ComputeError("检查报告缺少本次真实检查、修正或复核任务", 409)
        result[stage["name"]] = task
    if set(result) != {"check", "edit", "recheck"}:
        raise ComputeError("检查、修正和复核全部完成后才能生成检查报告", 409)
    for task in result.values():
        for output in task.outputs.all():
            path = app_path(output.path)
            if (
                output.expired
                or not path.is_file()
                or path.is_symlink()
                or checksum(path) != output.checksum
            ):
                raise ComputeError("检查报告引用的实际地图或结果文件已变化", 409)
    return result


def approved_suggestions(workflow, changes):
    review = workflow.plan.get("modificationReview", {})
    approved = review.get("approvedSuggestionIds", [])
    suggestions = [
        item for item in review.get("suggestions", []) if item.get("id") in approved
    ]
    if (
        not approved
        or len(set(approved)) != len(approved)
        or len(suggestions) != len(approved)
    ):
        raise ComputeError("检查报告缺少有效的用户批准范围", 409)
    approval_step = (
        workflow.steps.filter(kind="modifications_approved", status="succeeded")
        .order_by("sequence")
        .last()
    )
    if (
        approval_step is None
        or approval_step.action.get("proposalHash") != review.get("proposalHash")
        or approval_step.action.get("selectedSuggestionIds") != approved
    ):
        raise ComputeError("检查报告的修改范围未对应保存的批准记录", 409)
    if len(changes) != len(suggestions):
        raise ComputeError("检查报告中的实际操作数量与用户批准不一致", 409)
    for row in changes:
        matching = [
            item
            for item in suggestions
            if str(item.get("featureId")) == row.get("feature_id")
            and item.get("kind") == row.get("kind")
            and item.get("ruleId") == row.get("rule_id")
        ]
        if len(matching) != 1 or row.get("status") != "applied":
            raise ComputeError("检查报告中的实际修改不能对应获批操作", 409)
    return suggestions


def knowledge_lines(evidence, suggestions):
    refs = {
        (str(ref["id"]), ref["revision"])
        for item in suggestions
        for ref in item.get("knowledgeRefs", [])
    }
    chosen = [
        item for item in evidence if (str(item.get("id")), item.get("revision")) in refs
    ]
    if (
        not refs
        or {(str(item.get("id")), item.get("revision")) for item in chosen} != refs
    ):
        raise ComputeError("检查报告缺少批准方案对应的专家知识引用", 409)
    lines = []
    for item in chosen:
        lines.extend(
            [
                f"**{text(item.get('title', '专家知识'))}**",
                "",
                text(item.get("statement", "")),
                "",
            ]
        )
        for label, key in (("适用条件", "conditions"), ("例外", "exceptions")):
            values = item.get(key, [])
            if values:
                lines.extend(
                    [
                        label
                        + "："
                        + "；".join(text(value, 400) for value in values[:4]),
                        "",
                    ]
                )
        for source in item.get("sources", [])[:3]:
            if isinstance(source, dict):
                title = source.get("title", "知识来源")
                locator = source.get("locator", "")
                lines.append(
                    "- 来源："
                    + text(title, 500)
                    + ("；" + text(locator, 200) if locator else "")
                )
        lines.append("")
    return lines


def render_geology_report(workflow, tasks):
    if (
        not isinstance(workflow.plan.get("finalDecision"), dict)
        or not workflow.plan["finalDecision"]
    ):
        raise ComputeError("模型读取实际结果并完成复核后才能生成检查报告", 409)
    actual = actual_tasks(workflow, tasks)
    issues = actual_table(actual["check"], "issues")
    changes = actual_table(actual["edit"], "changes")
    stats = actual_table(actual["edit"], "statistics")
    remaining = actual_table(actual["recheck"], "issues")
    suggestions = approved_suggestions(workflow, changes)
    knowledge = knowledge_lines(workflow.evidence, suggestions)
    lines = [
        "# 检查报告",
        "",
        "演示案例",
        "",
        f"项目：{text(workflow.project_tag.name)}",
        "",
        f"任务：{text(workflow.goal)}",
        "",
        "## 发现的问题",
        "",
        f"本次检查发现 {len(issues)} 处疑点。",
        "",
    ]
    for row in issues:
        lines.append(
            f"- 图斑 {text(row.get('feature_id', ''))}：{text(row.get('reason', ''), 700)}"
        )
    lines.extend(
        ["", "## 专家知识提供的依据", "", *knowledge, "## 用户批准的建议修改", ""]
    )
    for item in suggestions:
        lines.append(
            f"- 图斑 {text(item['featureId'])}：{text(item.get('title', '建议修改'))}；{text(item.get('currentState', ''))} → {text(item.get('suggestedState', ''))}。"
        )
        lines.append("  理由：" + text(item.get("reason", ""), 700))
    changed_ids = {row["feature_id"] for row in changes}
    filled = sum(number(row["area_m2"]) for row in changes if row["kind"] == "fill_gap")
    age_count = sum(row["kind"] == "set_age" for row in changes)
    area_delta = sum(number(row["delta_area_m2"]) for row in stats)
    if not math.isclose(area_delta, filled, abs_tol=0.01, rel_tol=1e-8):
        raise ComputeError("实际地图面积变化与填补记录不一致，请核对结果", 409)
    lines.extend(
        [
            "",
            "## 算法实际修改了什么",
            "",
            f"完成 {len(changes)} 项获批操作，涉及 {len(changed_ids)} 个图斑；填补内部漏填 {filled:,.1f} 平方米，更新 {age_count} 个时代属性。",
            "",
        ]
    )
    for row in changes:
        label = "填补内部漏填" if row["kind"] == "fill_gap" else "更新地层时代"
        lines.append(
            f"- 图斑 {text(row['feature_id'])}：{label}；{text(row.get('current_label') or row['old_value'])} → {text(row.get('suggested_label') or row['new_value'])}。"
        )
    lines.extend(
        [
            "",
            "### 修改前后面积",
            "",
            "| 地质类别 | 编号 | 修改前（平方米） | 修改后（平方米） | 变化（平方米） |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for row in stats:
        lines.append(
            f"| {text(row.get('name', ''))}（{text(row.get('code', ''))}） | {text(row.get('class', ''))} | {number(row['before_area_m2']):,.1f} | {number(row['after_area_m2']):,.1f} | {number(row['delta_area_m2']):+,.1f} |"
        )
    lines.extend(
        [
            "",
            "## 复核结果与下一步",
            "",
            f"修正后重新检查，剩余 {len(remaining)} 处疑点。",
            "",
        ]
    )
    for row in remaining:
        lines.append("- " + text(row.get("reason", ""), 700))
    final = workflow.plan.get("finalDecision", {})
    for key in ("resultSummary", "judgement", "uncertainties"):
        value = final.get(key)
        if isinstance(value, str) and value:
            lines.extend([text(value), ""])
        elif isinstance(value, list):
            lines.extend("- " + text(item, 700) for item in value[:4])
            lines.append("")
    lines.extend(
        [
            "## 生成的文件",
            "",
            "修正后地质图、修改范围和统计表可在本次任务的结果文件中预览、下载，或在地理工作台查看。",
            "",
        ]
    )
    for stage, label in (("check", "检查"), ("edit", "修正"), ("recheck", "复核")):
        task = actual[stage]
        lines.append(
            f"- {label}算法：{text(task.version.algorithm.name)} {text(task.version.version)}。"
        )
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")
