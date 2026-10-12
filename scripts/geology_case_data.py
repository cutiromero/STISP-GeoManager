"""Prepare real map statistics and an explicitly seeded attribute demo.

Original materials remain read-only. Acceptance truth is written separately and
must never be registered as an agent, algorithm or retrieval input.
"""

import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import re
import shutil

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize, shapes
from shapely.geometry import box, shape


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def class_table(path):
    # TIFF XML stores the original UTF-8 even when a GDAL locale damages tags.
    raw = path.read_bytes()
    matched = re.search(rb'<Item name="CLASS_TABLE">(.*?)</Item>', raw, re.S)
    if not matched:
        raise ValueError("预测TIF缺少内置CLASS_TABLE，不能凭名称合并类别")
    text = matched.group(1).decode("utf-8")
    values = json.loads(html.unescape(html.unescape(text)))
    if len({row["label"] for row in values}) != len(values):
        raise ValueError("内置类别编号重复")
    return values


def formation(name):
    for value in ("八宝山组", "闹仓坚沟组"):
        if name.startswith(value):
            return value
    return ""


def normalized_clean(path, mapping):
    frame = gpd.read_file(path)
    frame["class"] = frame["class"].astype(int)
    for field in ("name", "code", "path"):
        frame[field] = frame["class"].map(lambda value: mapping[value][field])
    frame["feature_id"] = [f"manual-{i:05d}" for i in range(len(frame))]
    frame["area_m2"] = frame.geometry.area
    frame["source_kind"] = "人工精修：师弟在原始预测上手动修改"
    return frame


def prepare(materials, output):
    output.mkdir(parents=True, exist_ok=True)
    private = output.parent / "acceptance-only"
    private.mkdir(parents=True, exist_ok=True)
    base = materials / "解译结果/A左"
    source = base / "predict_202609281516.tif"
    clean_source = base / "predict_202609281516/精修/predict_202609281516_clean.shp"
    table = class_table(source)
    mapping = {row["label"]: row for row in table}
    write_json(output / "class_mapping.json", table)
    with rasterio.open(source) as dataset:
        array, mask = dataset.read(1), dataset.dataset_mask() > 0
        grid = {
            "transform": dataset.transform,
            "crs": dataset.crs,
            "shape": array.shape,
        }
        bounds = box(*dataset.bounds)
        records, geometries = [], []
        for index, (geometry, label) in enumerate(
            shapes(array, mask=mask, transform=dataset.transform)
        ):
            value = int(label)
            if value not in mapping:
                raise ValueError("像元类别不在内置类别表中")
            records.append(
                {
                    "feature_id": f"pred-{index:05d}",
                    "class": value,
                    **{key: mapping[value][key] for key in ("name", "code", "path")},
                    "source_kind": "原始预测TIF完整重建；原SHP保留",
                }
            )
            geometries.append(shape(geometry))
    initial = gpd.GeoDataFrame(records, geometry=geometries, crs=grid["crs"])
    initial["area_m2"] = initial.geometry.area
    initial.to_file(
        output / "prediction_rebuilt.gpkg", layer="data", driver="GPKG", index=False
    )
    if not initial.geometry.is_valid.all():
        raise ValueError("重建矢量含无效几何")
    reconstructed = rasterize(
        zip(initial.geometry, initial["class"]),
        out_shape=array.shape,
        transform=grid["transform"],
        fill=255,
        dtype="uint8",
    )
    if not np.array_equal(reconstructed[mask], array[mask]):
        raise ValueError("重建矢量未能逐像元回到原分类")
    clean = normalized_clean(clean_source, mapping)
    clean.to_file(
        private / "manual_refined.gpkg", layer="data", driver="GPKG", index=False
    )
    reference = rasterize(
        zip(clean.geometry, clean["class"]),
        out_shape=array.shape,
        transform=grid["transform"],
        fill=255,
        dtype="uint8",
    )
    comparable = mask & (reference != 255)
    initial_total = float(initial.area_m2.sum())
    clean_total = float(clean.area_m2.sum())
    pixel_area = abs(grid["transform"].a * grid["transform"].e)
    statistics = []
    for key, entry in sorted(mapping.items()):
        predicted_area = int(np.count_nonzero(mask & (array == key))) * pixel_area
        vector_area = float(initial.loc[initial["class"] == key, "area_m2"].sum())
        refined_area = float(clean.loc[clean["class"] == key, "area_m2"].sum())
        statistics.append(
            {
                "class_id": key,
                "name": entry["name"],
                "code": entry["code"],
                "prediction_area_m2": predicted_area,
                "rebuilt_vector_area_m2": vector_area,
                "manual_refined_area_m2": refined_area,
                "prediction_area_km2": predicted_area / 1e6,
                "manual_refined_area_km2": refined_area / 1e6,
                "prediction_pct": predicted_area / initial_total * 100,
                "manual_refined_pct": refined_area / clean_total * 100,
                "delta_m2": refined_area - predicted_area,
                "delta_pct_of_initial": (refined_area / predicted_area - 1) * 100
                if predicted_area
                else "",
            }
        )
    write_csv(output / "current_class_area.csv", statistics)
    structure_source = base / "构造/示范区构造解译0404.shp"
    faults = gpd.read_file(structure_source).to_crs(initial.crs)
    faults = faults.loc[faults.intersects(bounds)].copy()
    faults["structure_id"] = [f"structure-{i:04d}" for i in faults.index]
    faults["source_note"] = "真实构造解译线；性质、名称未提供"
    faults.geometry = faults.geometry.intersection(bounds)
    faults.to_file(output / "structures.gpkg", layer="data", driver="GPKG", index=False)
    minerals = {}
    for path in sorted((base / "蚀变").glob("*.tif")):
        with rasterio.open(path) as dataset:
            if (
                dataset.crs != grid["crs"]
                or dataset.transform != grid["transform"]
                or dataset.shape != array.shape
            ):
                raise ValueError("蚀变层网格不一致")
            minerals[path.stem] = dataset.read(1)
    candidates = initial.loc[initial["class"].isin([0, 5, 6, 7, 8])].copy()
    union = faults.geometry.union_all()
    candidates["distance"] = candidates.geometry.distance(union)
    candidates["score"] = (
        candidates.area_m2.clip(upper=100000) / 100000 + candidates["distance"] / 1000
    )
    # This selects a visible real locality, not a correction answer.
    seed = candidates.sort_values(["score", "feature_id"]).iloc[0]
    center = seed.geometry.representative_point()
    roi = box(center.x - 3000, center.y - 3000, center.x + 3000, center.y + 3000)
    local = initial.loc[initial.intersects(roi)].copy()
    local.geometry = local.geometry.intersection(roi)
    local = local.loc[~local.geometry.is_empty].copy().reset_index(drop=True)
    local["area_m2"] = local.geometry.area
    local["formation"] = local["name"].map(formation)
    # These two fields are added for the demonstration, not supplied measured
    # fields. Region is a dictionary-based applicability assumption, not an
    # independently surveyed boundary; age is a dictionary consistency value.
    local["region"] = "青海东昆仑南坡"
    local["geologic_age"] = local.formation.map(
        {"八宝山组": "T3", "闹仓坚沟组": "T2"}
    ).fillna("未赋值")
    local["source_kind"] = "真实预测图局部副本；预置少量时代录入演示错误"
    baseline = local.copy()
    editable = local.loc[
        (local.formation == "八宝山组") & local.area_m2.between(20000, 200000)
    ].sort_values(["area_m2", "feature_id"])
    if len(editable) < 3:
        raise ValueError("当前局部少于3个有可靠辞书时代的对象")
    chosen = editable.head(3).index
    injection = []
    for index in chosen:
        injection.append(
            {
                "feature_id": local.at[index, "feature_id"],
                "field": "geologic_age",
                "original_value": "T3",
                "seeded_value": "J3",
                "scope": "演示属性录入错误；不声明师弟原图有真实时代错误",
            }
        )
        local.at[index, "geologic_age"] = "J3"
    baseline.to_file(
        private / "roi_unseeded_reference.gpkg",
        layer="data",
        driver="GPKG",
        index=False,
    )
    local.to_file(
        output / "demo_initial.gpkg", layer="data", driver="GPKG", index=False
    )
    write_csv(private / "injected_errors.csv", injection)
    local_faults = faults.loc[faults.intersects(roi)].copy()
    local_faults.geometry = local_faults.geometry.intersection(roi)
    local_faults.to_file(
        output / "demo_structures.gpkg", layer="data", driver="GPKG", index=False
    )
    context = []
    context_candidates = editable.head(12)
    for _, row in context_candidates.iterrows():
        covered = (
            rasterize(
                [(row.geometry, 1)],
                out_shape=array.shape,
                transform=grid["transform"],
                dtype="uint8",
            )
            > 0
        )
        hits = {
            name: int(np.count_nonzero(covered & (values == 1)))
            for name, values in minerals.items()
        }
        context.append(
            {
                "feature_id": row.feature_id,
                "evidence_id": "context-" + row.feature_id,
                "evidence_kind": "spatial_context",
                "source": "师弟预测TIF、构造解译、蚀变指示TIF",
                "formation": row.formation,
                "region": row.region,
                "area_m2": float(row.area_m2),
                "nearest_structure_m": float(row.geometry.distance(union)),
                "mineral_positive_pixels": json.dumps(hits, ensure_ascii=False),
                "age_evidence": "无独立野外定年；构造与蚀变仅为上下文",
                "limitations": "蚀变仅统计值1；0被标NoData，不能当作确定未蚀变",
            }
        )
    write_csv(output / "demo_context.csv", context)
    terms = {}
    with (materials / "cgl_terms/cgl_terms.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("name") in {"八宝山组", "闹仓坚沟组"} and "时代" in row.get(
                "attributes", {}
            ):
                terms[row["name"]] = row
    rules = []
    study_wgs84 = gpd.GeoSeries([bounds], crs=initial.crs).to_crs(4326).iloc[0].bounds
    study_bbox = ",".join(
        str(value + (-0.00001 if index < 2 else 0.00001))
        for index, value in enumerate(study_wgs84)
    )
    for name, age in (("八宝山组", "T3"), ("闹仓坚沟组", "T2")):
        term = terms[name]
        if age not in term["attributes"]["时代"]:
            raise ValueError("辞书时代与规则不符")
        rules.append(
            {
                "rule_id": "age-" + term["id"],
                "field": "geologic_age",
                "operation": "set_attribute",
                "formation": name,
                "region": "青海东昆仑南坡",
                "expected_age": age,
                "evidence_id": "cgl-" + term["id"],
                "evidence_kind": "dictionary_definition",
                "source": "中国岩石地层名称辞典",
                "source_url": term["url"],
                "source_locator": "/".join(term["attributes"]["条目编码"])
                + "；时代字段",
                "conditions": "保留当前地层识别，只核对同名地层与时代属性的一致性；适用青海东昆仑南坡；bbox仅为本次真实图件研究范围筛查，不是辞书地层边界",
                "exceptions": "新的可靠测年、区域地层划分差异或地层名称误判应转人工复核",
                "region_bbox_wgs84": study_bbox,
            }
        )
    write_csv(output / "demo_age_rules.csv", rules)
    local_clean = clean.loc[clean.intersects(roi)].copy()
    local_clean.geometry = local_clean.geometry.intersection(roi)
    local_clean.to_file(
        private / "roi_manual_refined.gpkg", layer="data", driver="GPKG", index=False
    )
    summary = {
        "source_tif": str(source),
        "source_sha256": digest(source),
        "source_clean": str(clean_source),
        "crs": str(initial.crs),
        "grid": [29, 29],
        "classes": len(mapping),
        "unique_names": len({v["name"] for v in table}),
        "reconstructed_features": len(initial),
        "manual_refined_features": len(clean),
        "prediction_area_m2": initial_total,
        "manual_refined_area_m2": clean_total,
        "raster_roundtrip_equal": True,
        "comparable_pixels": int(comparable.sum()),
        "changed_class_pixels": int(
            np.count_nonzero(comparable & (array != reference))
        ),
        "roi_bounds_utm": list(roi.bounds),
        "roi_features": len(local),
        "seeded_attribute_errors": len(injection),
        "roi_structures": len(local_faults),
        "acceptance_only": str(private),
        "semantic_scope": "辞书条件下地层名—时代属性一致性；不修改岩性或边界",
        "original_files_preserved": True,
        "class_mapping_key": "class/label，不按name或code合并",
    }
    write_json(output / "preparation_summary.json", summary)
    # Copy only new derived outputs and positively identified original rasters.
    for path in sorted((base / "蚀变").glob("*.tif")):
        shutil.copy2(path, output / path.name)
    shutil.copy2(source, output / "prediction_original.tif")
    assets = []
    descriptions = {
        "prediction_original.tif": "师弟完整原始预测分类TIF；41个稳定类别编号",
        "prediction_rebuilt.gpkg": "由完整TIF四连通重建，12759面；原SHP不一致，不替换原件",
        "current_class_area.csv": "当前图件重新计算41类面积、占比、人工精修前后变化；class为稳定键",
        "structures.gpkg": "真实构造解译线按全图范围裁切；名称与性质未给出",
        "demo_initial.gpkg": "6公里真实地图副本，预置3个时代录入演示错误；不声明原图有时代错误",
        "demo_context.csv": "12个小面积筛查候选的真实空间上下文，构造与蚀变不承担定年",
        "demo_age_rules.csv": "八宝山组T3、闹仓坚沟组T2的来源和地区条件规则",
        "demo_structures.gpkg": "局部真实构造线，配合地图解释",
    }
    for path in sorted(output.iterdir()):
        if path.suffix.lower() not in {".tif", ".gpkg", ".csv"}:
            continue
        assets.append(
            {
                "file": path.name,
                "sha256": digest(path),
                "size": path.stat().st_size,
                "description": descriptions.get(
                    path.name, "真实蚀变指示TIF；仅值1作为命中，0为NoData"
                ),
                "algorithm_input": path.name
                in {"demo_initial.gpkg", "demo_context.csv", "demo_age_rules.csv"},
                "reference_only": False,
            }
        )
    for name in (
        "manual_refined.gpkg",
        "roi_manual_refined.gpkg",
        "roi_unseeded_reference.gpkg",
        "injected_errors.csv",
    ):
        path = private / name
        assets.append(
            {
                "file": "../acceptance-only/" + name,
                "sha256": digest(path),
                "size": path.stat().st_size,
                "description": "独立验收与成果对照；不进入模型、检索、检查或编辑算子输入",
                "algorithm_input": False,
                "reference_only": True,
            }
        )
    write_json(output / "assets_manifest.json", {"version": 1, "assets": assets})
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--materials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.materials, args.output)
