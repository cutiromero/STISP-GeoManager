"""Score only after normal operators return; private labels never enter workers."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import geopandas as gpd

PROJECTS = {
    "L-01": (
        "地层接触",
        "地层局部包围关系疑点",
        "只检验合成包围异常，不判定真实地层接触正确性",
    ),
    "L-02": (
        "地层接触",
        "早期岩体局部包围关系疑点",
        "含真实残留体例外，检出仅表示复核候选",
    ),
    "L-03": ("属性一致性", "名称代号一致性", "属性校验，不计作地层接触关系完整验证"),
    "L-04": ("岩性共生", "局部岩石组合异常候选", "只覆盖本模拟火山岩与高变质背景组合"),
    "S-01": ("构造切割", "覆盖层内线性体及端点", "形态与覆盖证据，不证明断层不存在"),
    "S-02": ("构造切割", "沿岩性界线比例与弯曲度", "不等于真实构造切割时序验证"),
    "S-03": ("构造切割", "孤立短线复核", "短且孤立为复核提示"),
    "S-04": ("构造切割", "急折返线形复核", "线形异常为复核提示"),
}


def read_csv(path: Path) -> list[dict]:
    csv.field_size_limit(20 * 1024 * 1024)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError("Evaluation table must have explicit rows")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def counts(expected: set, predicted: set) -> dict:
    true_positive = len(expected & predicted)
    false_positive, false_negative = (
        len(predicted - expected),
        len(expected - predicted),
    )
    recall = true_positive / len(expected) if expected else None
    precision = true_positive / len(predicted) if predicted else None
    f1 = (
        2 * true_positive / (2 * true_positive + false_positive + false_negative)
        if expected or predicted
        else None
    )
    return {
        "expected": len(expected),
        "reported": len(predicted),
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "recall": recall,
        "precision": precision,
        "f1": f1,
    }


def selected(findings: list[dict], threshold: float | None = None) -> list[dict]:
    result = []
    for row in findings:
        if row["rule_id"] in {"L-01", "L-02", "L-04"} and threshold is not None:
            confidence = json.loads(row["measurements_json"]).get(
                "simulation_confidence"
            )
            if confidence is not None and float(confidence) >= threshold:
                continue
        elif row["status"] == "exception":
            continue
        result.append(row)
    return result


def score_rules(
    findings: list[dict], labels: dict, threshold: float | None = None
) -> list[dict]:
    reported = selected(findings, threshold)
    result = []
    for rule, (relation, project, scope) in PROJECTS.items():
        element = "lithology" if rule.startswith("L-") else "structure"
        expected = {
            identifier for identifier, value in labels[element].items() if value == rule
        }
        predicted = {row["feature_id"] for row in reported if row["rule_id"] == rule}
        result.append(
            {
                "rule": rule,
                "relation": relation,
                "test_item": project,
                "scope": scope,
                **counts(expected, predicted),
            }
        )
    return result


def score_relations(findings: list[dict], labels: dict) -> list[dict]:
    reported = selected(findings)
    result = []
    for relation in ("地层接触", "岩性共生", "构造切割", "属性一致性"):
        rules = {rule for rule, data in PROJECTS.items() if data[0] == relation}
        element = "structure" if relation == "构造切割" else "lithology"
        expected = {
            identifier
            for identifier, value in labels[element].items()
            if value in rules
        }
        predicted = {row["feature_id"] for row in reported if row["rule_id"] in rules}
        result.append(
            {
                "relation": relation,
                "rules": ",".join(sorted(rules)),
                "scope": "；".join(PROJECTS[rule][1] for rule in sorted(rules)),
                "complete_geological_relation_validation": False,
                **counts(expected, predicted),
            }
        )
    return result


def structure_overall(findings: list[dict], labels: dict) -> list[dict]:
    predicted = {
        row["feature_id"]
        for row in selected(findings)
        if row["rule_id"] in {"S-01", "S-02", "S-03", "S-04"}
    }
    all_expected = set(labels["structure"])
    rule_expected = {
        identifier
        for identifier, value in labels["structure"].items()
        if value != "S-UNSUPPORTED"
    }
    return [
        {"scope": "全部模拟异常线（含无对应规则）", **counts(all_expected, predicted)},
        {"scope": "存在对应规则的模拟异常线", **counts(rule_expected, predicted)},
    ]


def calibrate(findings: list[dict], labels: dict) -> tuple[float, list[dict], dict]:
    scan = []
    candidates = []
    for step in range(50, 99, 2):
        threshold = step / 100
        rows = score_rules(findings, labels, threshold)
        spatial = [row for row in rows if row["rule"] in {"L-01", "L-02", "L-04"}]
        f1 = sum(row["f1"] or 0 for row in spatial) / len(spatial)
        meets = all(
            (row["recall"] or 0) >= 0.85 and (row["precision"] or 0) >= 0.8
            for row in spatial
        )
        scan.extend(
            {"threshold": threshold, **row}
            for row in rows
            if row["rule"].startswith("L-")
        )
        candidates.append((meets, f1, -threshold, threshold))
    meets, f1, _, threshold = max(candidates)
    return (
        threshold,
        scan,
        {
            "objective": "仅标定集：先满足各空间检查项查全率≥0.85且查准率≥0.80，再最大化宏平均F1；未全部满足时仍如实记录。",
            "allTargetsMet": meets,
            "macroF1": f1,
            "selectionReadTestLabels": False,
        },
    )


def area_agreement(actual: gpd.GeoDataFrame, reference: gpd.GeoDataFrame) -> dict:
    actual = actual.to_crs(32646)
    reference = reference.to_crs(32646)
    intersection = gpd.overlay(
        actual[["geo_sym", "geometry"]].rename(columns={"geo_sym": "actual"}),
        reference[["geo_sym", "geometry"]].rename(columns={"geo_sym": "reference"}),
        how="intersection",
        keep_geom_type=False,
    )
    matched = float(
        intersection.loc[intersection.actual == intersection.reference].area.sum()
    )
    total = float(reference.area.sum())
    return {
        "matchingAreaM2": matched,
        "referenceAreaM2": total,
        "areaLabelAgreement": matched / total if total else None,
    }
