"""Bounded representative readings, with complete file identity and measured totals."""

import csv
import json
import math
from collections import Counter

from apps.compute.packages import ComputeError


def table_rows(path, key):
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ComputeError("综合检查结果表超过64 MiB，请缩小本次检查范围")
    groups, rows, count, counts = {}, [], 0, Counter()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames) > 80:
            raise ComputeError("综合检查结果表字段无效")
        for row in reader:
            count += 1
            if count > 100000:
                raise ComputeError("综合检查结果超过十万项，请缩小检查范围")
            if any(value is None or len(value) > 160000 for value in row.values()):
                raise ComputeError("综合检查结果包含异常单元格")
            group = row.get("rule_id", "statistics")
            counts[group] += 1
            if key == "issues":
                representatives = groups.setdefault(group, [])
                representatives.append(row)
                representatives.sort(key=_measured_size, reverse=True)
                del representatives[2:]
            elif len(rows) < 40:
                rows.append(row)
    if key == "issues":
        rows = [row for representatives in groups.values() for row in representatives]
    return {
        "columns": reader.fieldnames,
        "rows": rows,
        "rowCount": count,
        "scope": "all" if count == len(rows) else "representative_sample",
        "samplingNote": "每条规则选取实际面积或长度较大的两个代表对象，未进入建议的对象保持原样；完整结果可下载",
        "countsByRule": dict(counts),
    }


def _measured_size(row):
    try:
        measurements = json.loads(row.get("measurements_json") or "{}")
        area = float(row.get("area_m2") or measurements.get("area_m2") or 0)
        length = float(row.get("length_m") or measurements.get("length_m") or 0)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ComputeError("代表对象的实际面积或长度格式无效") from exc
    if not all(math.isfinite(value) and value >= 0 for value in (area, length)):
        raise ComputeError("代表对象的实际面积或长度无效")
    return area or length, row.get("issue_id", "")


def model_results(results):
    """Geometry is available to the map; narrative decisions use actual measurements."""
    return [
        {
            **item,
            "rows": [
                {key: value for key, value in row.items() if key != "geometry_json"}
                for row in item.get("rows", [])
            ],
        }
        for item in results
    ]


def edit_task(workflow, results):
    if not results:
        return None
    check = next(item for item in workflow.plan["stages"] if item["name"] == "check")
    issues = [
        item
        for item in results
        if item["key"] == "issues" and item["taskId"] == check.get("taskId")
    ]
    return {
        "issuesOutputIds": [item["outputId"] for item in issues],
        "requiredFields": ["issue_id", "action", "target_code", "weight", "reason"],
        "changesInputState": "requires_model_proposal",
        "limit": 30,
        "unselectedPolicy": "retain_original",
        "issueRuleKnowledge": [
            {
                "id": item["id"],
                "revision": item["revision"],
                "ruleId": item["ruleId"],
                "ruleVersion": item["ruleVersion"],
            }
            for item in workflow.plan["trialRuleBindings"]
        ],
    }
