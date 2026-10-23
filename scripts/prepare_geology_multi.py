"""Prepare local runtime copies; never execute or modify the delivery pipeline."""

import argparse
import colorsys
import csv
import hashlib
import json
from pathlib import Path
import shutil

import geopandas as gpd
from shapely.ops import unary_union
import yaml

SCENARIO = "geology_multi_element_reasoning"
RASTERS = {
    "hematite": ("chitiekuang", "赤铁矿"),
    "chlorite": ("lvnishi", "绿泥石"),
    "hydromica": ("shuiyunmu", "水云母"),
    "calcite": ("fangjieshi", "方解石"),
    "dolomite": ("baiyunshi", "白云石"),
}


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def color_table(path):
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    layer = next(
        item for item in document["layerDefinitions"] if item.get("name") == "海德乌拉"
    )
    colors = {}
    for group in layer["renderer"]["groups"]:
        for item in group["classes"]:
            layers = item["symbol"]["symbol"]["symbolLayers"]
            fill = next(
                value["color"] for value in layers if value["type"] == "CIMSolidFill"
            )
            values = fill["values"]
            if fill["type"] == "CIMHSVColor":
                rgb = colorsys.hsv_to_rgb(
                    values[0] / 360, values[1] / 100, values[2] / 100
                )
                values = [round(component * 255) for component in rgb]
            elif fill["type"] != "CIMRGBColor":
                raise ValueError("Unsupported source color")
            color = "#" + "".join(f"{round(component):02x}" for component in values[:3])
            for value in item["values"]:
                colors[value["fieldValues"][0]] = color
    return colors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    source, output = arguments.source.resolve(), arguments.output.resolve()
    if output == source or source in output.parents:
        raise ValueError("Output must be independent of source")
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in [*manifest["resources"], *manifest["artifacts"]]:
            if sha(output / item["file"]) != item["sha256"]:
                raise ValueError(
                    "Existing prepared material changed; use a new output directory"
                )
        print("Prepared inputs already verified:", manifest_path)
        return
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty output directory")
    verified = {}
    for line in (source / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        expected, relative = line.split(None, 1)
        path = (source / relative.strip()).resolve()
        if source not in path.parents or sha(path) != expected:
            raise ValueError("Delivery checksum mismatch: " + relative)
        verified[relative] = expected
    output.mkdir(parents=True, exist_ok=True)
    runtime, evaluation, references = (
        output / name for name in ("inputs", "evaluation", "references")
    )
    for directory in (runtime, evaluation, references):
        directory.mkdir()
    colors = color_table(source / "data/ExportedFiles.lyrx")
    lithology = gpd.read_file(source / "results/01_模拟识别岩性图.gpkg").to_crs(32646)
    # Stable pseudorandom ordering mixes all objects; ID shape reveals no injection type.
    order = sorted(
        range(len(lithology)),
        key=lambda index: hashlib.sha256(lithology.geometry.iloc[index].wkb).digest(),
    )
    lithology = lithology.iloc[order].reset_index(drop=True)
    lithology["feature_id"] = [f"G-{index + 1:05d}" for index in range(len(lithology))]
    dump(
        evaluation / "lithology_mapping.json",
        lithology.drop(columns="geometry").to_dict("records"),
    )
    clean = lithology[["feature_id", "name", "geo_sym", "conf", "geometry"]].copy()
    clean["confidence_kind"] = "模拟分类置信度"
    clean["fill_color"] = clean["name"].map(colors).fillna("#cbd5e1")
    clean.to_file(runtime / "lithology.gpkg", layer="data", driver="GPKG", index=False)
    area = unary_union(clean.geometry)
    coverage = gpd.GeoDataFrame(
        {"coverage_id": ["coverage"], "role": ["complete"]}, geometry=[area], crs=32646
    )
    coverage.to_file(
        runtime / "coverage.gpkg", layer="data", driver="GPKG", index=False
    )
    faults = gpd.read_file(source / "results/01_模拟构造图.gpkg").to_crs(32646)
    faults.geometry = faults.geometry.intersection(area)
    faults = faults.loc[~faults.geometry.is_empty & (faults.geometry.length > 0)].copy()
    faults = faults.iloc[
        sorted(
            range(len(faults)),
            key=lambda index: hashlib.sha256(faults.geometry.iloc[index].wkb).digest(),
        )
    ].reset_index(drop=True)
    faults["neutral_id"] = [f"F-{index + 1:05d}" for index in range(len(faults))]
    dump(
        evaluation / "fault_mapping.json",
        faults.drop(columns="geometry").to_dict("records"),
    )
    faults = faults[["neutral_id", "geometry"]].rename(
        columns={"neutral_id": "line_id"}
    )
    faults.to_file(runtime / "faults.gpkg", layer="data", driver="GPKG", index=False)
    rules = yaml.safe_load(
        (source / "knowledge/rules.yaml").read_text(encoding="utf-8")
    )
    units = yaml.safe_load(
        (source / "knowledge/strat_units.yaml").read_text(encoding="utf-8")
    )
    with (source / "knowledge/legend_units.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        aliases = {row["name"]: row["geo_sym"] for row in csv.DictReader(stream)}
    if len(rules["rules"]) != 17 or len(units["units"]) != 34 or len(aliases) != 38:
        raise ValueError("Delivery knowledge inventory changed")
    dump(
        output / "trial_knowledge.json",
        {
            "scenario": SCENARIO,
            "version": rules["meta"]["version"],
            "rules": rules["rules"],
            "units": units["units"],
            "aliases": aliases,
            "unitMeta": units["meta"],
        },
    )
    resources = []

    def resource(role, kind, name, description):
        path = runtime / (role + (".tif" if kind == "raster" else ".gpkg"))
        resources.append(
            {
                "role": role,
                "file": path.relative_to(output).as_posix(),
                "sha256": sha(path),
                "kind": kind,
                "code": "geology-multi-" + role.replace("_", "-"),
                "layer": "data",
                "name": name,
                "description": description,
            }
        )

    resource(
        "lithology",
        "vector",
        "海德乌拉模拟识别岩性图（演示）",
        "模拟识别输入（演示）。conf为模拟分类置信度。米制副本用于检查，地图沿用原图例配色。",
    )
    resource(
        "faults",
        "vector",
        "海德乌拉模拟构造图（演示）",
        "模拟识别输入（演示）。仅使用研究区内构造线，采用中性编号。",
    )
    resource(
        "coverage",
        "vector",
        "海德乌拉制图范围",
        "由当次输入岩性图覆盖范围生成；范围内计算，范围外不参与远景区圈定。",
    )
    for role, (stem, label) in RASTERS.items():
        shutil.copyfile(
            source / "data/海德乌拉蚀变" / (stem + "_rasterized.tif"),
            runtime / (role + ".tif"),
        )
        resource(
            role,
            "raster",
            "海德乌拉" + label + "识别结果",
            "遥感矿物识别结果（演示案例）；矿物识别与野外确认的蚀变分开解释。",
        )
    artifacts = []
    for filename, name in [
        ("图1_三要素总览.png", "海德乌拉三要素总览（交付参考结果）"),
        ("图5_蚀变找矿远景区.png", "海德乌拉远景区（交付参考结果）"),
    ]:
        path = references / filename
        shutil.copyfile(source / "figures" / filename, path)
        artifacts.append(
            {
                "file": path.relative_to(output).as_posix(),
                "sha256": sha(path),
                "name": name,
                "description": "交付参考结果，仅用于说明案例设计；当前运行地图、统计及报告以当次任务输出为准。",
                "resultType": "image",
                "resources": ["geology-multi-lithology", "geology-multi-faults"],
            }
        )
    for relative in [
        "data/海德乌拉.shp",
        "data/海德乌拉.shx",
        "data/海德乌拉.dbf",
        "data/海德乌拉.prj",
        "data/海德乌拉.cpg",
        "results/01_岩性注入错误真值.gpkg",
        "results/stats.json",
    ]:
        path = evaluation / Path(relative).name
        shutil.copyfile(source / relative, path)
    dump(evaluation / "source_checksums.json", verified)
    dump(output / "legend_colors.json", colors)
    dump(
        manifest_path,
        {
            "schemaVersion": 1,
            "scenario": SCENARIO,
            "resources": resources,
            "artifacts": artifacts,
            "counts": {
                "lithology": len(clean),
                "faults": len(faults),
                "areaKm2": area.area / 1e6,
                "rules": 17,
                "units": 34,
                "aliases": 38,
            },
            "sourceChecksums": len(verified),
        },
    )
    print(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "counts": json.loads(manifest_path.read_text(encoding="utf-8"))[
                    "counts"
                ],
                "verifiedFiles": len(verified),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
