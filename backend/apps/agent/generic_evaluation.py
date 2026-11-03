"""Recall and precision of a geology check against labelled simulated inputs.

Evaluation reads the labels from the user's original upload (injected-patch and
fake-line labels) and compares them with the check stage's issue table. Working
copies number features in upload order (F00001 is row 1, S00001 is line 1), which
is what links the two. Results are registered as an independent evaluation and
never enter the plan, the model or the operators.
"""

from __future__ import annotations

import csv
import json

from apps.compute.packages import ComputeError

RELATIONS = {
    "L-01": "地层接触",
    "L-02": "地层接触",
    "L-03": "地层接触",
    "L-04": "岩性共生",
    "S-01": "构造切割",
    "S-02": "构造切割",
    "S-03": "构造切割",
    "S-04": "构造切割",
}
# Fake-line labels in the simulated fault map and the rule meant to catch each.
FAKE_LINES = {"valley": "S-01", "boundary": "S-02", "short": "S-03", "zigzag": "S-04"}
RELATION_KEYS = {
    "地层接触": "contact",
    "岩性共生": "assemblage",
    "构造切割": "structure",
}
CONFIDENCE_RULES = {"L-01", "L-02", "L-04"}
TARGET = {"recall": 0.85, "precision": 0.80}


def neutral_id(prefix: str, index: int) -> str:
    return f"{prefix}{index + 1:05d}"


def lithology_truth(frame) -> dict[str, str]:
    if "inj_type" not in frame:
        raise ComputeError("岩性资料没有注入错误标签（inj_type），无法评价")
    return {
        neutral_id("F", index): str(value or "")
        for index, value in enumerate(frame["inj_type"])
    }


def fault_truth(frame) -> dict[str, str]:
    if "fake_type" not in frame:
        return {}
    return {
        neutral_id("S", index): str(value or "")
        for index, value in enumerate(frame["fake_type"])
    }


def read_issues(path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as stream:
        return [row for row in csv.DictReader(stream) if row["rule_id"] in RELATIONS]


def _confidence(row) -> float | None:
    try:
        value = json.loads(row.get("measurements_json") or "{}").get(
            "simulation_confidence"
        )
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def reported(issues, threshold=None) -> list[dict]:
    """Exception candidates are browsed, not reported; a threshold re-decides that."""
    result = []
    for row in issues:
        if threshold is not None and row["rule_id"] in CONFIDENCE_RULES:
            confidence = _confidence(row)
            if confidence is not None and confidence >= threshold:
                continue
        elif row["status"] == "exception":
            continue
        result.append(row)
    return result


def _score(truth: set, found: set) -> dict:
    tp, fp, fn = len(truth & found), len(found - truth), len(truth - found)
    return {
        "truth": len(truth),
        "reported": len(found),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
    }


def _truth_rule(element: str, label: str) -> str:
    return FAKE_LINES.get(label, "") if element == "structure" else label


def metrics(issues, lith: dict[str, str], faults: dict[str, str]):
    """Per-rule and per-relation scores for one set of reported issues."""
    labels = {("lithology", key): value for key, value in lith.items()}
    labels.update({("structure", key): value for key, value in faults.items()})
    found_by_rule: dict[str, set] = {}
    for row in issues:
        found_by_rule.setdefault(row["rule_id"], set()).add(
            (row["element"], row["feature_id"])
        )
    by_rule = []
    for rule in sorted(RELATIONS):
        truth = {
            key for key, value in labels.items() if _truth_rule(key[0], value) == rule
        }
        by_rule.append(
            {"rule": rule, "relation": RELATIONS[rule]}
            | _score(truth, found_by_rule.get(rule, set()))
        )
    by_relation = []
    for relation in sorted(set(RELATIONS.values())):
        rules = {rule for rule, name in RELATIONS.items() if name == relation}
        truth = {
            key
            for key, value in labels.items()
            if _truth_rule(key[0], value) in rules
            # Shape-normal fake lines are real conflicts no rule is meant to catch.
            or (
                relation == "构造切割"
                and key[0] == "structure"
                and value == "plausible"
            )
        }
        found = set().union(*(found_by_rule.get(rule, set()) for rule in rules))
        by_relation.append({"relation": relation} | _score(truth, found))
    return by_rule, by_relation


def sweep(issues, lith, faults, low=0.70, high=0.96, step=0.01):
    """Threshold scan for report_conf_max on the lithology confidence rules."""
    rows, value = [], low
    while value <= high + 1e-9:
        threshold = round(value, 2)
        _, relations = metrics(reported(issues, threshold), lith, faults)
        lithology = [r for r in relations if r["relation"] != "构造切割"]
        meets = all(
            (r["recall"] or 0) >= TARGET["recall"]
            and (r["precision"] or 0) >= TARGET["precision"]
            for r in lithology
        )
        f1 = [
            2 * r["recall"] * r["precision"] / (r["recall"] + r["precision"])
            for r in lithology
            if r["recall"] and r["precision"]
        ]
        rows.append(
            {
                "threshold": threshold,
                "meets_target": meets,
                "mean_f1": round(sum(f1) / len(f1), 4) if f1 else None,
                **{
                    f"{RELATION_KEYS[r['relation']]}_recall": r["recall"]
                    for r in lithology
                },
                **{
                    f"{RELATION_KEYS[r['relation']]}_precision": r["precision"]
                    for r in lithology
                },
            }
        )
        value += step
    chosen = max(
        rows,
        key=lambda row: (row["meets_target"], row["mean_f1"] or 0, -row["threshold"]),
    )
    return rows, chosen
