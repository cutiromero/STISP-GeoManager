"""Build the small publish DTO from completed independent evaluation artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re

LABELS = {
    "stage": "对照阶段",
    "rule": "规则",
    "relation": "相关关系",
    "test_item": "具体检查项目",
    "scope": "评价范围",
    "rules": "涉及规则",
    "expected": "独立异常数",
    "reported": "候选数",
    "tp": "正确检出",
    "fp": "误报",
    "fn": "漏检",
    "recall": "查全率",
    "precision": "查准率",
    "f1": "F1",
    "threshold": "模拟置信度阈值",
    "complete_geological_relation_validation": "完整专业关系验证",
    "first_code": "单元一",
    "second_code": "单元二",
    "first_category": "单元一类别",
    "second_category": "单元二类别",
    "reference_shared_line_m": "参照共享线（米）",
    "observed_shared_line_m": "运行共享线（米）",
    "same_pair_reference_covered_m": "参照线被覆盖（米）",
    "same_pair_observed_supported_m": "运行线与参照对应（米）",
    "line_id": "构造对象",
    "independent_simulation_type": "独立模拟类型",
    "actual_reported_rules": "实际检出规则",
    "length_m": "长度（米）",
    "cover_ratio": "覆盖层比例",
    "endpoints_in_cover": "端点在覆盖层内",
    "boundary_ratio": "沿界比例",
    "sinuosity": "弯曲度",
    "neighbour_count": "邻线数量",
    "turn_count": "急折返数",
}
STAGES = {"first": "第一轮", "recheck": "构造建议对照复检", "rules-only": "仅规则对照"}
CONTROLS = {
    "pointContactIsNotLineContact": "点接触不计作线接触",
    "sharedLineDetected": "真实共享线接触被检出",
    "alongBoundaryIsNotCrossCut": "沿界线不计为穿越两侧内部",
    "crossingHasTwoInteriors": "实际穿越两侧内部被区分",
    "coexistenceExceptionRetained": "高置信度岩性共生例外保持复核",
}


def scalar(value: str) -> str | float | int | bool | None:
    if not value:
        return None
    if value in {"True", "False"}:
        return value == "True"
    if re.fullmatch(r"-?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?", value, re.I):
        number = float(value)
        if math.isfinite(number):
            return int(number) if number.is_integer() else number
    return value


def csv_section(
    directory: Path, key: str, filename: str, title: str, summary: str
) -> dict:
    with (directory / filename).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = [{name: scalar(value) for name, value in row.items()} for row in reader]
    for row in rows:
        if "stage" in row:
            row["stage"] = STAGES.get(row["stage"], row["stage"])
        for name in ("recall", "precision", "f1"):
            if name in row and row[name] is not None:
                row[name] = f"{float(row[name]):.2%}"
    return {
        "key": key,
        "title": title,
        "summary": summary,
        "columns": [{"key": name, "label": LABELS.get(name, name)} for name in fields],
        "rows": rows,
    }


def publish_dto(directory: Path) -> dict:
    result = json.loads(
        (directory / "evaluation-summary.json").read_text(encoding="utf-8")
    )
    calibration = result["calibration"]
    contacts = result["measuredSpatialRelations"]["contactGraph"]
    controls = result["measuredSpatialRelations"]["independentControls"]
    overall, covered = result["structureMetrics"]
    algorithm_version = json.loads(
        (directory / "operator-snapshot/check-operator.yaml").read_text(
            encoding="utf-8"
        )
    )["version"]
    if result["executionStatus"] != "passed" or not all(controls["checks"].values()):
        raise ValueError("Evaluation execution did not finish successfully")
    sections = [
        csv_section(
            directory,
            "rules",
            "metrics-by-rule.csv",
            "逐规则与具体检查项目",
            "检出表示需要复核的候选，和批准或实际修复分别记录；L-03单列属性一致性。",
        ),
        csv_section(
            directory,
            "relations",
            "metrics-by-relation.csv",
            "限定范围的关系评价",
            "逐项列明实际检查内容，不将规则分组名称解释成完整地层接触、共生或构造时序验证。",
        ),
        csv_section(
            directory,
            "calibration",
            "confidence-calibration.csv",
            "标定与独立测试分离",
            f"仅用标定种子{calibration['calibrationSeed']}选定阈值{calibration['threshold']:.2f}后读取测试副本。各项标定目标"
            + (
                "全部满足。"
                if calibration["allTargetsMet"]
                else "未全部满足，保留实际成绩。"
            )
            + "本表是标定集，非测试成绩。",
        ),
        csv_section(
            directory,
            "structures",
            "structure-all-vs-covered.csv",
            "构造全部异常与规则覆盖子集",
            "全部异常包含形态正常而规则无法识别的模拟线；子集成绩不替代整体查全率。",
        ),
        csv_section(
            directory,
            "contacts",
            "measured-contact-pairs.csv",
            "共享线接触与独立参照",
            f"参照{contacts['contactPairMetrics']['expected']}对，运行{contacts['contactPairMetrics']['reported']}对；点接触不计为线接触。"
            + "按实际几何与规范单元代号量算，不判断接触性质或真实地质年代关系。",
        ),
        csv_section(
            directory,
            "structure_measurements",
            "structure-measured-items.csv",
            "构造逐线测量与模拟类型",
            "正常算法返回的覆盖、沿界、弯曲与折返等测量和独立模拟类型对照。空值表示该对象未返回异常测量，非零值。",
        ),
        {
            "key": "geometry_controls",
            "title": "独立小型几何控制",
            "summary": controls["scope"],
            "columns": [
                {"key": "test", "label": "具体检查"},
                {"key": "passed", "label": "本次实测通过"},
            ],
            "rows": [
                {"test": CONTROLS[key], "passed": value}
                for key, value in controls["checks"].items()
            ],
        },
    ]
    return {
        "scope": "同一海德乌拉示范区、不同随机种子的模拟独立评价；几何控制与原始地质图参照均只用于评价，未进入智能体或正常处理输入。",
        "summary": f"重新运行{algorithm_version}正常检查算子，比较第一轮、复检及仅规则对照。"
        + f"标定阈值{calibration['threshold']:.2f}，"
        + (
            "预设标定目标全部满足。"
            if calibration["allTargetsMet"]
            else "预设标定目标未全部满足。"
        )
        + f"构造整体检出{overall['tp']}/{overall['expected']}，有规则子集{covered['tp']}/{covered['expected']}；"
        + "这些是模拟候选检测结果。矿物无独立标注真值，不计算准确率。",
        "sections": sections,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise ValueError("Publish DTO must not overwrite existing evidence")
    value = publish_dto(arguments.evaluation)
    arguments.output.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "sections": len(value["sections"]),
                "output": str(arguments.output),
                "rows": sum(len(section["rows"]) for section in value["sections"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
