"""Run isolated synthetic geology evaluation with frozen calibration and real GIS.

This script runs normal check operator entry points. It never starts a workflow,
logs into a server, changes a catalog resource, or executes the delivery main().
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time

import geopandas as gpd
import yaml

from geology_multi_evaluation_data import (
    prepare_dataset,
    pure_generators,
    reference_maps,
    sha256,
    source_fingerprints,
    write_json,
)
from geology_multi_evaluation_metrics import (
    area_agreement,
    calibrate,
    read_csv,
    score_relations,
    score_rules,
    structure_overall,
    write_csv,
)
from geology_multi_evaluation_relations import (
    contact_comparison,
    independent_controls,
    structure_measurement_rows,
)

RASTER_FILES = {
    "hematite": "chitiekuang",
    "chlorite": "lvnishi",
    "hydromica": "shuiyunmu",
    "calcite": "fangjieshi",
    "dolomite": "baiyunshi",
}


class OperatorContext:
    def __init__(self, directory: Path, inputs: dict[str, Path]) -> None:
        self.directory, self.inputs = directory.resolve(), inputs
        self.parameters = {
            "working_epsg": 32646,
            "segment": "all",
            "grid_resolution_m": 100,
            "min_zone_area_m2": 200000,
        }
        self.directory.mkdir(parents=True)
        if any("private" in path.parts for path in inputs.values()):
            raise ValueError("Independent reference must never enter an operator")

    def input_path(self, key: str) -> Path:
        return self.inputs[key]

    def output_path(self, name: str) -> Path:
        path = (self.directory / name).resolve()
        if path.parent != self.directory:
            raise ValueError("Operator output must remain task-local")
        return path


def snapshot_operators(repository: Path, destination: Path) -> dict:
    destination.mkdir()
    hashes = {}
    for path in sorted(
        (repository / "examples/compute/geology-multi-core").glob("multi_*.py")
    ):
        shutil.copyfile(path, destination / path.name)
        hashes["core/" + path.name] = sha256(path)
    for suffix in ("check", "apply", "relations", "prospect"):
        directory = repository / f"examples/compute/geology-multi-{suffix}"
        for filename in ("main.py", "operator.yaml"):
            source = directory / filename
            target = destination / f"{suffix}-{filename}"
            shutil.copyfile(source, target)
            hashes[f"{suffix}/{filename}"] = sha256(source)
    return hashes


def run_check(snapshot: Path, output: Path, inputs: dict[str, Path]) -> list[dict]:
    sys.path.insert(0, str(snapshot))
    spec = importlib.util.spec_from_file_location(
        "independent_geology_check", snapshot / "check-main.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    started = time.monotonic()
    context = OperatorContext(output, inputs)
    module.run(context)
    manifest = {
        "operator": "geology-multi-check",
        "entryPoint": "run(context)",
        "elapsedSeconds": time.monotonic() - started,
        "inputs": {
            key: {"file": path.name, "sha256": sha256(path)}
            for key, path in inputs.items()
        },
        "parameters": context.parameters,
        "privateReferenceUsed": False,
        "outputs": {
            path.name: sha256(path) for path in output.iterdir() if path.is_file()
        },
    }
    write_json(output / "execution.json", manifest)
    print(
        f"Executed normal check: {output.name} ({manifest['elapsedSeconds']:.1f}s)",
        flush=True,
    )
    return read_csv(output / "issues.csv")


def threshold_rules(source: Path, target: Path, threshold: float) -> None:
    rows = read_csv(source)
    for row in rows:
        if row["rule_id"] in {"L-01", "L-02", "L-04"}:
            parameters = json.loads(row["params_json"])
            parameters["report_conf_max"] = threshold
            row["params_json"] = json.dumps(
                parameters, ensure_ascii=False, sort_keys=True
            )
    write_csv(target, rows)


def hypothesis_faults(source: Path, target: Path, findings: list[dict]) -> dict:
    """Evaluation control only: reported lines excluded, geometry kept.

    This is not a real user's approval and does not become a production result.
    It isolates how structure evidence changes the lithology recheck.
    """
    frame = gpd.read_file(source)
    identifiers = {
        row["feature_id"] for row in findings if row["rule_id"].startswith("S-")
    }
    frame["state"] = frame.line_id.map(
        lambda identifier: "exclude" if identifier in identifiers else "keep"
    )
    frame["weight"] = frame.state.map(lambda state: 0.0 if state == "exclude" else 1.0)
    frame.to_file(target, layer="data", index=False)
    return {
        "excludedCount": len(identifiers),
        "allLineGeometriesRetained": True,
        "policy": "独立对照：假设采用本轮全部构造复核建议，研究复检差异；不是正式案例批准或实际处置记录。",
    }


def dataset_inputs(directory: Path, shared: Path, rules: Path) -> dict[str, Path]:
    runtime = directory / "runtime"
    return {
        **{
            role: runtime / f"{role}.gpkg"
            for role in ("lithology", "faults", "coverage")
        },
        "rules": rules,
        **{role: shared / f"{role}.tif" for role in RASTER_FILES},
    }


def copy_fixture(previous: Path, directory: Path, seed: int) -> dict:
    """Replay reviewed fixtures against a newer operator snapshot."""
    manifest = json.loads(
        (previous / "fixture-manifest.json").read_text(encoding="utf-8")
    )
    if manifest["seed"] != seed:
        raise ValueError("Replayed fixture seed differs from requested split")
    for name, expected in manifest["runtimeFiles"].items():
        if sha256(previous / "runtime" / name) != expected:
            raise ValueError("Replayed runtime fixture changed: " + name)
    directory.mkdir()
    (directory / "runtime").mkdir()
    for name in manifest["runtimeFiles"]:
        shutil.copyfile(previous / "runtime" / name, directory / "runtime" / name)
    shutil.copytree(previous / "private", directory / "private")
    write_json(directory / "fixture-manifest.json", manifest)
    return manifest


def evaluate(
    source: Path,
    prepared_inputs: Path,
    output: Path,
    calibration_seed: int,
    test_seed: int,
    fixtures_from: Path | None = None,
) -> dict:
    repository = Path(__file__).resolve().parents[1]
    source, prepared_inputs, output = (
        source.resolve(),
        prepared_inputs.resolve(),
        output.resolve(),
    )
    if calibration_seed == test_seed:
        raise ValueError("Calibration and test seeds must be different")
    if (
        source == output
        or source in output.parents
        or output == prepared_inputs
        or prepared_inputs in output.parents
    ):
        raise ValueError(
            "Evaluation output must remain independent of original and runtime inputs"
        )
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new output directory; previous evidence is immutable")
    output.mkdir(parents=True, exist_ok=True)
    original_hashes = source_fingerprints(source)
    snapshot = output / "operator-snapshot"
    operator_hashes = snapshot_operators(repository, snapshot)
    shared = output / "shared-runtime"
    shared.mkdir()
    for role, stem in RASTER_FILES.items():
        shutil.copyfile(
            source / f"data/海德乌拉蚀变/{stem}_rasterized.tif", shared / f"{role}.tif"
        )
    reference, reference_faults, _ = reference_maps(source)
    units = yaml.safe_load(
        (source / "knowledge/strat_units.yaml").read_text(encoding="utf-8")
    )["units"]
    generators = pure_generators(source / "scripts/demo_pipeline.py")
    calibration = output / "calibration"
    calibration_fixture = (
        copy_fixture(fixtures_from / "calibration", calibration, calibration_seed)
        if fixtures_from
        else prepare_dataset(
            calibration,
            calibration_seed,
            generators,
            reference,
            reference_faults,
            units,
        )
    )
    calibration_rules = calibration / "runtime/rules-measurement-only.csv"
    threshold_rules(prepared_inputs / "rules.csv", calibration_rules, 1.01)
    inputs = dataset_inputs(calibration, shared, calibration_rules)
    first = run_check(snapshot, calibration / "first-measured", inputs)
    controlled_faults = calibration / "runtime/faults-hypothesis.gpkg"
    calibration_control = hypothesis_faults(inputs["faults"], controlled_faults, first)
    second = run_check(
        snapshot,
        calibration / "recheck-measured",
        {**inputs, "faults": controlled_faults},
    )
    labels = json.loads(
        (calibration / "private/labels.json").read_text(encoding="utf-8")
    )
    threshold, scan, objective = calibrate(second, labels)
    write_csv(output / "confidence-calibration.csv", scan)
    freeze = {
        "threshold": threshold,
        "calibrationSeed": calibration_seed,
        "frozenBeforeTestGeneration": fixtures_from is None,
        "frozenBeforeTestFixtureRead": True,
        "fixtureReplay": fixtures_from is not None,
        "frozenAt": datetime.now(timezone.utc).isoformat(),
        "calibrationLabelsSha256": sha256(calibration / "private/labels.json"),
        **objective,
    }
    write_json(output / "frozen-calibration.json", freeze)
    # Test labels and test geometry have not even been generated when threshold freezes.
    test = output / "test"
    test_fixture = (
        copy_fixture(fixtures_from / "test", test, test_seed)
        if fixtures_from
        else prepare_dataset(
            test, test_seed, generators, reference, reference_faults, units
        )
    )
    test_rules = test / "runtime/rules-frozen.csv"
    threshold_rules(prepared_inputs / "rules.csv", test_rules, threshold)
    inputs = dataset_inputs(test, shared, test_rules)
    first = run_check(snapshot, test / "first-frozen", inputs)
    test_faults = test / "runtime/faults-hypothesis.gpkg"
    test_control = hypothesis_faults(inputs["faults"], test_faults, first)
    recheck = run_check(
        snapshot, test / "recheck-frozen", {**inputs, "faults": test_faults}
    )
    rules_only = test / "runtime/rules-confidence-disabled.csv"
    threshold_rules(test_rules, rules_only, 1.01)
    only_rules = run_check(
        snapshot,
        test / "recheck-rules-only",
        {**inputs, "faults": test_faults, "rules": rules_only},
    )
    labels = json.loads((test / "private/labels.json").read_text(encoding="utf-8"))
    stages = {"first": first, "recheck": recheck, "rules-only": only_rules}
    by_rule, by_relation, overall = [], [], []
    for stage, findings in stages.items():
        by_rule.extend({"stage": stage, **row} for row in score_rules(findings, labels))
        by_relation.extend(
            {"stage": stage, **row} for row in score_relations(findings, labels)
        )
        if stage == "first":
            overall = structure_overall(findings, labels)
    write_csv(output / "metrics-by-rule.csv", by_rule)
    write_csv(output / "metrics-by-relation.csv", by_relation)
    write_csv(output / "structure-all-vs-covered.csv", overall)
    contact_graph = contact_comparison(
        gpd.read_file(inputs["lithology"]),
        reference,
        units,
        output / "measured-contact-pairs.csv",
    )
    from multi_checks import lithology_findings
    from multi_io import rules as load_normal_rules

    control_rules, _, _ = load_normal_rules(test_rules)
    geometric_controls = independent_controls(lithology_findings, control_rules["L-04"])
    write_json(output / "independent-geometry-controls.json", geometric_controls)
    write_csv(
        output / "structure-measured-items.csv",
        structure_measurement_rows(first, labels),
    )
    label_agreement = area_agreement(gpd.read_file(inputs["lithology"]), reference)
    minerals = gpd.read_file(test / "first-frozen/alterations.gpkg")
    mineral_findings = [row for row in first if row["element"] == "alteration"]
    # Relation labels are deliberately narrower than the original package grouping.
    summary = {
        "schemaVersion": 1,
        "status": "completed",
        "executionStatus": "passed",
        "scope": "模拟数据独立评价",
        "calibration": freeze,
        "fixtures": {"calibration": calibration_fixture, "test": test_fixture},
        "ruleMetrics": by_rule,
        "relationMetrics": by_relation,
        "structureMetrics": overall,
        "measuredSpatialRelations": {
            "contactGraph": contact_graph,
            "independentControls": geometric_controls,
        },
        "lithologyAreaAgreementBefore": label_agreement,
        "controls": {"calibration": calibration_control, "test": test_control},
        "mineral": {
            "count": len(minerals),
            "ruleHitCount": len(mineral_findings),
            "accuracy": None,
            "reason": "矿物识别无独立标注真值，只统计规则命中，不计算准确率。",
        },
        "limits": [
            "同一示范区的不同随机种子，不是独立地区验证。",
            "L-03单列属性一致性，不冒充完整地层接触验证。",
            "构造项覆盖线形、覆盖层与边界复核，不验证全部构造切割时序。",
            "规则建议排除后的复检是独立对照，不冒充正式批准。",
            "检出为复核候选，不等同于地质判错或实际修复。",
        ],
        "isolation": {
            "privateInputsSentToOperator": False,
            "testReadBeforeThresholdFreeze": False,
            "originalDeliveryUnchanged": original_hashes == source_fingerprints(source),
        },
        "operatorFingerprints": operator_hashes,
        "sections": [
            {"title": "规则与具体检查项目", "file": "metrics-by-rule.csv"},
            {"title": "关系范围与独立指标", "file": "metrics-by-relation.csv"},
            {"title": "置信度标定（仅标定集）", "file": "confidence-calibration.csv"},
            {
                "title": "构造全部异常与规则覆盖子集",
                "file": "structure-all-vs-covered.csv",
            },
            {"title": "实际共享线接触与独立参照", "file": "measured-contact-pairs.csv"},
            {
                "title": "构造逐线实测与独立异常类型",
                "file": "structure-measured-items.csv",
            },
            {"title": "小型独立几何控制", "file": "independent-geometry-controls.json"},
        ],
    }
    write_json(output / "evaluation-summary.json", summary)
    write_report(output / "evaluation-report.md", summary)
    return summary


def percent(value: float | None) -> str:
    return "无可计分项" if value is None else f"{value:.1%}"


def write_report(path: Path, summary: dict) -> None:
    lines = [
        "# 海德乌拉模拟数据独立评价",
        "",
        "本次重新调用平台检查算法，原包结果未作为新成绩。",
        "",
        f"标定阈值：{summary['calibration']['threshold']:.2f}。先冻结，再读取本次测试副本。",
        "标定目标全部满足："
        + (
            "是。"
            if summary["calibration"]["allTargetsMet"]
            else "否，以下保留实测结果。"
        ),
        "",
        "| 对照 | 检查项 | 查全率 | 查准率 |",
        "| --- | --- | --- | --- |",
    ]
    for row in summary["ruleMetrics"]:
        if row["rule"].startswith("L-"):
            lines.append(
                f"| {row['stage']} | {row['rule']} {row['test_item']} | {percent(row['recall'])} | {percent(row['precision'])} |"
            )
    lines.extend(["", "构造检测："])
    for row in summary["structureMetrics"]:
        lines.append(
            f"- {row['scope']}：{row['tp']}/{row['expected']}，查全率{percent(row['recall'])}、查准率{percent(row['precision'])}。"
        )
    lines.extend(
        [
            "",
            "解释范围：",
            *[f"- {item}" for item in summary["limits"]],
            "- 矿物没有独立真值，本次不计算其识别准确率。",
            "",
            "正式案例的批准范围、实际改图、矿物权重及调查建议另按当次任务结果核对。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--prepared-inputs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--calibration-seed", default=20261024, type=int)
    parser.add_argument("--test-seed", default=20261025, type=int)
    parser.add_argument(
        "--fixtures-from",
        type=Path,
        help="Reuse previous isolated fixtures; recalibrate with current source before reading test fixture",
    )
    arguments = parser.parse_args()
    summary = evaluate(
        arguments.source,
        arguments.prepared_inputs,
        arguments.output,
        arguments.calibration_seed,
        arguments.test_seed,
        arguments.fixtures_from.resolve() if arguments.fixtures_from else None,
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "threshold": summary["calibration"]["threshold"],
                "structure": summary["structureMetrics"],
                "isolation": summary["isolation"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
