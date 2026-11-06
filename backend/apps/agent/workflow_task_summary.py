"""Lightweight facts from persisted, complete outputs; no IO or model interpretation."""

from collections import Counter
import math


def record(value):
    return value if isinstance(value, dict) else {}


def items(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def count(value):
    if type(value) is bool:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return (
        int(number)
        if math.isfinite(number) and number >= 0 and number.is_integer()
        else None
    )


def output(stage, key):
    return next(
        (
            r
            for r in items(stage.get("results"))
            if r.get("key") == key
            and r.get("scope") == "all"
            and isinstance(r.get("rows"), list)
        ),
        {},
    )


def full_rows(result):
    rows = items(result.get("rows"))
    return rows if count(result.get("rowCount")) == len(rows) else None


def task_summary(workflow):
    plan = record(workflow.plan)
    stages = {s.get("name"): s for s in items(plan.get("stages"))}
    initial = output(stages.get("check", {}), "issues")
    remaining = output(stages.get("recheck", {}), "issues")
    changes = output(stages.get("apply", {}), "changes")
    applied = full_rows(changes) if changes else None
    if applied is not None and any(
        not row.get("feature_id") or not row.get("rule_id") for row in applied
    ):
        applied = None
    if applied is not None:
        values = {str(row.get("actual_changed")).lower() for row in applied}
        if values - {"true", "false", "1", "0", "1.0", "0.0"}:
            applied = None
        else:
            applied = [
                row
                for row in applied
                if str(row.get("actual_changed")).lower() in {"true", "1", "1.0"}
            ]
    rows = full_rows(initial) if initial else None
    held = None
    if rows is not None:
        # Once apply was submitted, its actual changes are required to describe
        # what remains untouched; an approval alone does not prove execution.
        apply = stages.get("apply", {})
        if not apply.get("taskId") or applied is not None:
            edited = {
                (str(r.get("feature_id")), str(r.get("rule_id"))) for r in applied or []
            }
            held = Counter(
                r["status"]
                for r in rows
                if r.get("status") in {"review", "exception"}
                and (str(r.get("feature_id")), str(r.get("rule_id"))) not in edited
            )
    zones = None
    stats = output(stages.get("prospect", {}), "statistics")
    complete = full_rows(stats) if stats else None
    if complete is not None:
        grades = {r.get("grade"): r for r in complete}
        if len(complete) == len(grades) == 2 and set(grades) == {"A", "B"}:
            values = [count(r.get("after_count")) for r in grades.values()]
            if None not in values:
                zones = sum(values)
    calculations = [
        s
        for s in stages.values()
        if s.get("identifier") not in {None, "finish", "search_expert_knowledge"}
    ]
    sources = plan.get("uploadInputs")
    return {
        "sourceCount": len(sources) if isinstance(sources, dict) else None,
        "initialIssueCount": count(initial.get("rowCount"))
        if full_rows(initial) is not None
        else None,
        "remainingIssueCount": count(remaining.get("rowCount"))
        if full_rows(remaining) is not None
        else None,
        "executedDispositionCount": len(applied) if applied is not None else None,
        "retainedIssueCount": sum(held.values()) if held is not None else None,
        "reviewIssueCount": held.get("review", 0) if held is not None else None,
        "exceptionIssueCount": held.get("exception", 0) if held is not None else None,
        "prospectZoneCount": zones,
        "completedCalculations": sum(
            bool(s.get("taskId")) and s.get("status") == "completed"
            for s in calculations
        ),
        "totalCalculations": len(calculations),
    }
