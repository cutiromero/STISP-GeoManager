"""Version a runtime demonstration copy, retaining original sources and rule revisions."""

import argparse
import json
from pathlib import Path
import shutil

import geopandas as gpd

from prepare_geology_multi import SCENARIO, dump, sha


def prepare(prepared: Path, lithology: Path, output: Path):
    prepared, lithology, output = (
        prepared.resolve(),
        lithology.resolve(),
        output.resolve(),
    )
    if output == prepared or prepared in output.parents:
        raise ValueError("Use a separate prepared directory")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty output directory")
    manifest = json.loads((prepared / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads((prepared / "trial_knowledge.json").read_text(encoding="utf-8"))
    if manifest["scenario"] != SCENARIO or len(bundle["rules"]) != 17:
        raise ValueError("Expected the verified original trial bundle")
    resources = manifest["resources"]
    for item in resources:
        source = (prepared / item["file"]).resolve()
        if prepared not in source.parents or sha(source) != item["sha256"]:
            raise ValueError("Prepared input changed")
    output.mkdir(parents=True)
    for item in resources:
        source = lithology if item["role"] == "lithology" else prepared / item["file"]
        destination = output / item["file"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if item["role"] == "lithology":
            item.update(
                code="geology-multi-lithology-complete-20261025",
                name="海德乌拉待检查岩性图（演示整理副本）",
                description="演示整理副本；同一单元内部划分用于验证经批准图斑融合，地质类别沿用输入。conf为模拟分类置信度。原始资料与独立参照另存。",
                sha256=sha(destination),
            )
    # The original 17 rules retain their exact version and body.
    bundle["rules"].append(
        {
            "id": "L-05",
            "version": "2026-10-25-project-trial",
            "name": "相同单元相邻图斑整理",
            "element": "岩性",
            "applies_to": "海德乌拉演示整理副本的同单元制图整理",
            "relation": "相邻图斑属性一致性与内部边界整理",
            "condition": "本轮以地质单元为粒度整理地图。两个图斑名称、规范代号及现有分类字段一致，具有真实共享线边界；共享边界100米内没有构造线，也无须保留的内部细分资料。用户确认后可融合，保留外部覆盖和分类面积。",
            "action": "提议融合，批准后仅移除同单元内部边界",
            "params": {
                "unit_level_consolidation": True,
                "min_shared_boundary_m": 1,
                "fault_buffer_m": 100,
            },
            "basis": {
                "type": "项目整理规则",
                "statement": "将相邻且属性相同的同一单元图斑按本案例制图粒度合并；空间测量与属性一致性支持操作，类别不变。由项目整理并用于演示，不作为国家规范或论文原文结论。",
                "gap": "存在内部构造、有效细分单元、不同稳定类别编号、重叠或仅点接触时保留；缺少边界用途资料时交由用户审核，不能据小面积或时代排序重分类。",
                "refs": [
                    {
                        "citation": "STISP海德乌拉演示案例制图整理说明",
                        "verification": "项目整理规则 L-05，2026-10-25，试用",
                    }
                ],
            },
        }
    )
    manifest.update(artifacts=[], rulesCode="geology-multi-rules-complete-20261025")
    manifest["counts"].update(lithology=len(gpd.read_file(lithology)), rules=18)
    shutil.copyfile(prepared / "legend_colors.json", output / "legend_colors.json")
    dump(output / "trial_knowledge.json", bundle)
    dump(output / "manifest.json", manifest)
    return {"manifest": str(output / "manifest.json"), "rules": len(bundle["rules"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--lithology", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(args.prepared, args.lithology, args.output), ensure_ascii=False
        )
    )
