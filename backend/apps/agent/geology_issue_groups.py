"""Deterministic, snapshot-bound groups; only suggested objects can expand."""

import json
from collections import defaultdict

from apps.compute.packages import ComputeError
from apps.knowledge.trial_rules import digest


def issue_groups(rows):
    grouped = defaultdict(list)
    for row in rows:
        key = tuple(
            str(row.get(name, ""))
            for name in (
                "element",
                "rule_id",
                "suggested_action",
                "target_code",
                "status",
                "snapshot_hash",
                "rule_version",
            )
        )
        if row.get("element") == "alteration" and str(
            row.get("feature_id", "")
        ).startswith("AG-"):
            key += (row["feature_id"],)
        grouped[key].append(row)
    return [
        (members[0]["feature_id"] if len(key) > 7 else digest(key)[:24], members)
        for key, members in sorted(grouped.items())
    ]


def group_summaries(rows):
    summaries = []
    for identity, members in issue_groups(rows):
        first = members[0]
        ranges = {}
        for row in members:
            for key, value in json.loads(row.get("measurements_json") or "{}").items():
                if type(value) in {float, int}:
                    current = ranges.setdefault(key, [value, value])
                    current[:] = [min(current[0], value), max(current[1], value)]
        summaries.append(
            {
                "group_id": identity,
                "count": len(members),
                **{
                    key: first.get(key, "")
                    for key in (
                        "element",
                        "rule_id",
                        "rule_version",
                        "suggested_action",
                        "target_code",
                        "status",
                        "conditions",
                        "exceptions",
                    )
                },
                "measurementRanges": ranges,
                "samples": [
                    {
                        key: row.get(key, "")
                        for key in (
                            "issue_id",
                            "feature_id",
                            "reason",
                            "measurements_json",
                        )
                    }
                    for row in members[:3]
                ],
            }
        )
    return summaries


def expand_groups(edits, rows):
    groups = dict(issue_groups(rows))
    expanded = []
    grouped_edits = {}
    seen_groups = set()
    for edit in edits:
        if not isinstance(edit, dict) or "group_id" not in edit:
            expanded.append(edit)
            continue
        if set(edit) != {"group_id", "disposition", "excluded_issue_ids", "reason"}:
            raise ComputeError(
                "分组建议须含group_id、disposition、excluded_issue_ids及reason"
            )
        if not isinstance(edit["group_id"], str):
            raise ComputeError("分组标识须为文本")
        if edit["group_id"] in seen_groups:
            raise ComputeError("同一分组只能给出一次处置")
        seen_groups.add(edit["group_id"])
        if (
            not isinstance(edit["reason"], str)
            or not 1 <= len(edit["reason"].strip()) <= 1000
        ):
            raise ComputeError("每组处置须说明实际证据、适用条件和必要例外")
        members = groups.get(edit["group_id"])
        excluded = edit["excluded_issue_ids"]
        if (
            members is None
            or not isinstance(excluded, list)
            or any(not isinstance(value, str) for value in excluded)
            or set(excluded) - {row["issue_id"] for row in members}
        ):
            raise ComputeError("分组或排除对象不属于本次检查快照")
        if edit["disposition"] not in ("suggested", "review"):
            raise ComputeError("整组处置只能采用建议或待裁定")
        if edit["disposition"] == "review":
            continue
        if any(row["status"] != "suggested" for row in members):
            raise ComputeError("待裁定或例外对象不得按整组建议纳入")
        for row in members:
            if row["issue_id"] in excluded:
                continue
            action = row["suggested_action"]
            grouped_edits[row["issue_id"]] = {
                "issue_id": row["issue_id"],
                "action": action,
                "target_code": row.get("target_code", "")
                if action in {"set_code", "merge", "reclassify"}
                else "",
                "weight": 0.5
                if action == "downweight"
                else 0
                if action == "exclude"
                else 1,
                "reason": edit["reason"],
            }
    seen = set()
    for row in rows:
        target = (row["element"], row["feature_id"])
        if row["issue_id"] in grouped_edits and target not in seen:
            expanded.append(grouped_edits[row["issue_id"]])
            seen.add(target)
    return expanded
