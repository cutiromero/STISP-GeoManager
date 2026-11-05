"""Version a runtime demonstration copy, retaining original sources and rule revisions."""

import argparse
import json
from pathlib import Path
import shutil

import geopandas as gpd

from prepare_geology_multi import SCENARIO, dump, sha


def alluvium_shape_rule():
    return {
        "id": "L-06",
        "version": "2026-11-05-project-trial",
        "name": "全新世冲积物形态异常",
        "element": "岩性",
        "applies_to": "海德乌拉演示案例；需区域地质专家复核后另行推广",
        "relation": "沉积地貌与图斑空间形态一致性",
        "condition": "全新世冲积物紧凑度不低于0.6且最小外接矩形长宽比小于1.5，呈团块状，邻接较老堆积单元。以形状为主，包围比例及同类连通关系为辅；候选为共享边界最长的较老堆积单元，批准后与宿主融合。分类置信度不低于0.88或缺失时待裁定，其余给出建议。",
        "action": "建议重分类；待裁定默认保留，由用户选择冻结候选",
        "params": {
            "source_codes": ["Qhᵃˡ"],
            "host_categories": ["cover"],
            "compactness_min": 0.6,
            "aspect_ratio_max": 1.5,
            "conf_review_min": 0.88,
        },
        "basis": {
            "type": "本演示案例地貌形态试用判据",
            "statement": "按本案例用户提出的现代河道冲积物条带分布假设测量异常；参数由本案例验证，不是地质规范，不宣称适用于全部冲积物。",
            "gap": "冲积扇、河道交汇处宽阔冲积平原可能较圆润，应结合影像、河网及接触关系复核。边界裁切、制图概化与天然孤立露头也可能造成形态异常。未提供真实河网，不能据形状证明地质类别错误。",
            "refs": [
                {
                    "citation": "STISP海德乌拉演示案例用户确认的地貌形态假设及输入图斑实测",
                    "verification": "L-06，2026-11-05，本案例试用，非规范；独立参照仅用于事后评价，不输入算子",
                }
            ],
        },
    }


def enclave_continuity_rule():
    return {
        "id": "L-07",
        "version": "2026-11-05-project-trial",
        "name": "孤立早期单元连续性疑点",
        "element": "岩性",
        "applies_to": "海德乌拉演示案例地层与侵入岩；非规范",
        "relation": "同类分布连续性及局部接触形态",
        "condition": "面积不超过3平方公里、紧凑度不低于0.3、最小外接矩形长宽比小于1.5、分类置信度小于0.6，且不与同单元相接的较早地层或侵入岩。至少60%外边界邻接同类别的较年轻单元；记录同类最近距离及构造距离。只补充其他规则尚未发现的对象，始终待裁定。",
        "action": "提供共享边界最长单元为重分类候选，默认保留；用户明确选择才融合",
        "params": {
            "categories": ["stratum", "intrusive"],
            "max_area_km2": 3,
            "compactness_min": 0.3,
            "aspect_ratio_max": 1.5,
            "conf_max": 0.6,
            "dominant_boundary_min": 0.6,
        },
        "basis": {
            "type": "本演示案例空间连续性试用假设",
            "statement": "低置信度孤立近等轴斑块与周围同类别单元的连续性不协调，只构成复核线索；本案例测量验证不替代地质解释。",
            "gap": "早期岩体可为捕虏体、残留顶盖；地层可为构造窗、背斜核或剥蚀露头。真实产状、接触性质、区域构造和影像未齐全，构造附近也只报待裁定，不提升为可执行建议。",
            "refs": [
                {
                    "citation": "STISP海德乌拉演示案例用户确认的空间连续性核查需求与图斑实测",
                    "verification": "L-07，2026-11-05，本案例试用，非规范；独立标准答案仅用于事后评价",
                }
            ],
        },
    }


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
    bundle["rules"].append(alluvium_shape_rule())
    bundle["rules"].append(enclave_continuity_rule())
    manifest.update(artifacts=[], rulesCode="geology-multi-rules-complete-20261105")
    manifest["counts"].update(
        lithology=len(gpd.read_file(lithology)), rules=len(bundle["rules"])
    )
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
