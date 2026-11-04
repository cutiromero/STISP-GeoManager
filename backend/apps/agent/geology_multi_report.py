"""Concise audience report; complete approvals and evidence remain downloadable."""

from collections import Counter

from apps.compute.packages import ComputeError

ACTIONS = {
    "set_code": "修正代号",
    "reclassify": "更新类别",
    "merge": "融合相邻图斑",
    "exclude": "暂不参与分析",
    "downweight": "降低证据权重",
    "keep": "保留",
    "review": "保留待核查",
}


def render_report(workflow, tasks):
    from .workflow_reports import _cell, _text, _decision
    from .geology_review_report import actual_table

    by_id = {str(task.id): task for task in tasks}
    stages = {
        stage["name"]: by_id[stage["taskId"]]
        for stage in workflow.plan["stages"]
        if stage.get("taskId") in by_id
    }
    review = workflow.plan.get("modificationReview", {})
    approved_ids = set(review.get("approvedSuggestionIds", []))
    suggestions = review.get("suggestions", [])
    approved = [item for item in suggestions if item["id"] in approved_ids]
    if len(approved) != len(approved_ids):
        raise ComputeError("报告批准范围与保存建议不一致", 409)
    changes = actual_table(stages["apply"], "changes") if "apply" in stages else []
    actual = {(row["feature_id"], row["rule_id"]): row for row in changes}
    approved_edits = {
        (row["feature_id"], row["rule_id"]): row
        for stage in workflow.plan["stages"]
        if stage.get("name") == "apply"
        for row in stage.get("approvedEdits", [])
    }
    if len(actual) != len(changes) or len(actual) != len(approved):
        raise ComputeError("报告实际处置数量与批准对象不一致", 409)
    for item in approved:
        row = actual.get((item["featureId"], item["ruleId"]))
        if row is None or row["action"] != item["action"]:
            raise ComputeError("报告实际处置不能对应获批对象及动作", 409)
        edit = approved_edits.get((item["featureId"], item["ruleId"]))
        if (
            edit is None
            or row.get("target_code") != edit["target_code"]
            or float(row.get("weight", -1)) != float(edit["weight"])
            or edit["target_code"]
            and row.get("new_code") != edit["target_code"]
        ):
            raise ComputeError("报告实际类别或权重与获批参数不一致", 409)

    modes = {s.get("decision", {}).get("modelMode") for s in workflow.plan["stages"]}
    lines = [
        "# 海德乌拉综合检查报告",
        "",
        "演示案例",
        "",
        f"项目：{_text(workflow.project_tag.name)}",
        "",
        f"分析目标：{_text(workflow.goal)}",
        "",
        "## 结论",
        "",
    ]
    final = workflow.plan.get("finalDecision", {})
    _decision(
        lines,
        {
            key: final.get(key)
            for key in ("judgement", "resultSummary", "uncertainties")
            if not (key == "resultSummary" and "mock" in modes)
        },
    )
    if "mock" in modes:
        actions = Counter(
            ACTIONS.get(item["action"], item["action"]) for item in approved
        )
        lines.extend(
            [
                "实际处置："
                + (
                    "；".join(f"{action}{count}项" for action, count in actions.items())
                    or "保留全部原数据"
                )
                + "。下方统计来自实际任务文件。",
                "",
            ]
        )
    lines.extend(
        [
            f"本轮展示{len(suggestions)}项代表建议，用户批准{len(approved)}项，其余{len(suggestions) - len(approved)}项保持原样。完整问题数量见实际检查清单。",
            "",
            "模型验证："
            + (
                "模拟分析配合真实计算；真实模型判断尚未验证。"
                if "mock" in modes
                else "按当次模型调用记录保存。"
            ),
            "",
            "## 获批操作与实际结果",
            "",
        ]
    )
    for index, item in enumerate(approved, 1):
        row = actual[(item["featureId"], item["ruleId"])]
        action = ACTIONS.get(item["action"], item["action"])
        result = (
            "已执行"
            if row.get("actual_changed", "").casefold() == "true"
            else "保留原状"
        )
        target = action + (" " + row["new_code"] if row.get("target_code") else "")
        scope = "本对象"
        if row.get("host_feature_id") and item["action"] == "merge":
            scope += "及相邻承接图斑 " + str(row["host_feature_id"])
        lines.extend(
            [
                f"### {index}. {_text(action)}，对象 {_text(item['featureId'])}",
                "",
                f"{_text(item['currentState'])} → {_text(target)}。用户已批准，实际结果：{result}。",
                "",
                "理由：" + _text(item["reason"], 500),
                "",
                "实际观测：" + _observations(item.get("observations", {}), _text),
                "",
                f"依据：[{_text(item['ruleId'])} 本案例试用](#规则来源)。实际处置范围为{_text(scope)}。",
                "",
            ]
        )
    retained = Counter(
        (item["ruleId"], ACTIONS.get(item["action"], item["action"]))
        for item in suggestions
        if item["id"] not in approved_ids
    )
    if retained:
        lines.extend(
            [
                "### 未批准及待核查概览",
                "",
                "| 规则 | 原建议 | 数量 | 本轮处理 |",
                "| --- | --- | ---: | --- |",
            ]
        )
        lines.extend(
            f"| {_cell(rule)} | {_cell(action)} | {count} | 保留原数据 |"
            for (rule, action), count in sorted(retained.items())
        )
        lines.append("")

    lines.extend(["## 实际统计", ""])
    for name, label in (("check", "初次检查"), ("recheck", "修正后复核")):
        if name in stages:
            rows = actual_table(stages[name], "statistics")
            lines.extend(
                [
                    f"{label}：{sum(int(row['issue_count']) for row in rows)}条规则命中记录；同一对象可能命中多条规则，命中不等于已证实错误。",
                    "",
                ]
            )
    if "relations" in stages:
        counts = {
            row["kind"]: row["count"]
            for row in actual_table(stages["relations"], "statistics")
        }
        lines.extend(
            [
                f"关系重建：几何相交{counts.get('geometric', '0')}处，推测交汇{counts.get('inferred', '0')}处。",
                "",
            ]
        )
        for row in actual_table(stages["relations"], "statistics"):
            if row.get("before_count") not in {None, ""}:
                kind = "几何相交" if row["kind"] == "geometric" else "推测交汇"
                lines.extend(
                    [
                        f"{kind}：处理前{row['before_count']}处 → 处理后{row['after_count']}处。",
                        "",
                    ]
                )
    merges = [
        row for row in changes if row["action"] == "merge" or row.get("host_feature_id")
    ]
    if merges:
        involved = sum(
            float(row.get("involved_area_m2") or row["area_m2"]) for row in merges
        )
        removed = sum(
            float(row.get("removed_internal_boundary_m") or 0) for row in merges
        )
        lines.extend(
            [
                f"岩性整理：融合{len(merges)}组，涉及对象面积{involved / 1e6:.4f}km²，移除内部边界{removed:.2f}米。",
                "",
                "涉及对象面积表示被整理图斑的完整范围。实际覆盖几何变化面积为0，外部范围保持；同类别融合的类别面积也保持。",
                "",
            ]
        )
    if "prospect" in stages:
        rows = actual_table(stages["prospect"], "statistics")
        lines.extend(
            [
                "| 优先核查等级 | 修改前数量 | 修改后数量 | 修改前面积（km²） | 修改后面积（km²） |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in rows:
            lines.append(
                f"| {_cell(row['grade'])} | {_cell(row['before_count'])} | {_cell(row['after_count'])} | {float(row['before_area_km2']):.4f} | {float(row['after_area_km2']):.4f} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 规则来源",
            "",
            "每项沿用当次冻结的知识修订、条件及例外；完整参数保存在本次冻结规则资料中。",
            "",
            "| 规则与版本 | 知识修订 | 适用条件与例外 | 来源 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for entry in workflow.evidence:
        binding = entry.get("trialBinding")
        if not binding:
            continue
        conditions = "；".join(entry.get("conditions", []))
        exceptions = "；".join(entry.get("exceptions", [])) or "以本条规则条件为准"
        sources = "；".join(
            str(source.get("title", "")) + " " + str(source.get("locator", ""))
            for source in entry.get("sources", [])
        )
        lines.append(
            f"| {_cell(binding['ruleId'])} {_cell(binding['ruleVersion'])} | 修订 {_cell(entry['revision'])} | {_cell(conditions)}；例外：{_cell(exceptions)} | {_cell(sources)} |"
        )

    lines.extend(
        ["", "## 输入、算法版本与下载", "", "| 输入资料 | 当次修订 |", "| --- | --- |"]
    )
    for role, version in workflow.plan.get("upstreamVersions", {}).items():
        lines.append(
            f"| {_cell(workflow.plan['inputNames'].get(role, role))} | {_cell(version['revision'])} |"
        )
    lines.extend(
        [
            "",
            "| 实际任务 | 算法版本 | 实际参数 | 结果文件 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for task in tasks:
        manifest = getattr(task.version, "manifest", {})
        calculation_only = (
            {"faults", "alterations"}
            if any(
                item["key"] == "final_faults" for item in manifest.get("outputs", [])
            )
            else set()
        )
        links = "、".join(
            f"[{_cell(output.label)}](/api/compute/outputs/{output.id}/file/?projectTagId={workflow.project_tag_id})"
            for output in task.outputs.order_by("id")
            if getattr(output, "key", "") not in calculation_only
        )
        lines.append(
            f"| {_cell(task.name)} | {_cell(task.version.algorithm.name)} {_cell(task.version.version)} | {_cell(task.parameters)} | {links} |"
        )
    frozen = workflow.plan.get("frozen_rules")
    if frozen:
        lines.extend(
            [
                "",
                f"完整规则与知识修订：[本次冻结规则资料信息](/api/catalog/resources/{frozen}/profile/?projectTagId={workflow.project_tag_id})",
                "",
            ]
        )
    lines.extend(
        [
            "",
            "完整问题清单、获批变化CSV、地图、统计表及质量记录保留在上述真实任务文件中。文件校验与任务记录由平台保存。",
            "",
            "## 后续核查",
            "",
            "A/B表示本案例规则的证据组合等级；区域数量或面积变化反映获批处置影响，找矿效果需要矿点资料验证。碳酸盐背景仍可能叠加热液作用，模拟置信度仅用于演示；待核查项结合接触关系、基岩资料和实地证据继续判断。",
            "",
        ]
    )
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _observations(values, text):
    labels = {
        "name": "名称",
        "observed_code": "原代号",
        "expected_code": "对应代号",
        "area_m2": "面积（m²）",
        "involved_area_m2": "涉及对象面积（m²）",
        "shared_boundary_m": "共享边界（m）",
        "fault_distance_m": "距构造（m）",
        "length_m": "长度（m）",
        "cover_ratio": "覆盖层内比例",
        "boundary_ratio": "沿界比例",
        "sinuosity": "曲折系数",
        "turn_count": "急转数",
        "dominant_code": "主要背景单元",
        "mineral": "矿物",
        "group_ratios": "各岩石背景占比",
    }
    values = dict(values)
    if isinstance(values.get("group_ratios"), dict):
        groups = {"carbonate": "碳酸盐岩", "carbonate_interbed": "碳酸盐夹层"}
        values["group_ratios"] = "、".join(
            f"{groups.get(key, key)}{float(value):.1%}"
            for key, value in values["group_ratios"].items()
        )
    shown = [
        f"{label}={values[key]:.4f}"
        if type(values[key]) is float
        else f"{label}={values[key]}"
        for key, label in labels.items()
        if key in values
    ]
    return text("；".join(shown) or "完整观测保留在本次检查清单", 1200)
