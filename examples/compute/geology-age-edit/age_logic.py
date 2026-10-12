"""Shared, narrow formation-age consistency checks; no reference-map access."""

import csv
import hashlib
import json
import math
import re

import geopandas as gpd
from pyproj import CRS
from shapely import set_precision
from shapely.geometry import box

FIELD = "geologic_age"
CHANGE_FIELDS = [
    "feature_id",
    "field",
    "old_value",
    "new_value",
    "evidence_id",
    "rule_id",
    "reason",
    "input_checksum",
]
ISSUE_FIELDS = CHANGE_FIELDS[:6] + ["status"] + CHANGE_FIELDS[6:]
RULE_FIELDS = {
    "rule_id",
    "field",
    "operation",
    "formation",
    "region",
    "expected_age",
    "evidence_id",
    "evidence_kind",
    "source",
    "source_url",
    "source_locator",
    "conditions",
    "exceptions",
    "region_bbox_wgs84",
}
CONTEXT_FIELDS = {
    "feature_id",
    "evidence_id",
    "evidence_kind",
    "source",
    "formation",
    "region",
    "area_m2",
    "nearest_structure_m",
    "mineral_positive_pixels",
    "age_evidence",
    "limitations",
}


def table(path, required):
    with open(path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not required <= set(reader.fieldnames or []):
            raise ValueError("CSV缺少字段：" + ",".join(sorted(required)))
        rows = list(reader)
    if len(rows) > 20000 or any(
        None in row or any(row[key] is None for key in required) for row in rows
    ):
        raise ValueError("CSV字段格式无效或超过20000条")
    return rows


def write_table(path, rows, fields):
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def working_frame(frame, working_epsg=32646):
    target = CRS.from_epsg(working_epsg)
    if not target.is_projected or any(
        abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in target.axis_info[:2]
    ):
        raise ValueError("工作投影须为米制投影")
    return frame.to_crs(target)


def map_checksum(frame, working_epsg=32646):
    canonical = working_frame(frame, working_epsg)
    records = []
    for _, row in canonical.iterrows():
        record = {
            key: str(row[key]) for key in sorted(set(frame.columns) - {"geometry"})
        }
        # One micrometre precision only canonicalizes projection round trips.
        # Output geometry always retains original coordinates and exact bytes.
        record["geometry"] = set_precision(row.geometry, 0.000001).normalize().wkb_hex
        records.append(record)
    payload = {
        "crs": canonical.crs.to_wkt(),
        "features": sorted(records, key=lambda row: row["feature_id"]),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def read_map(path, working_epsg=32646):
    frame = gpd.read_file(path, layer="data")
    required = {"feature_id", "formation", "region", FIELD, "class"}
    if frame.empty or frame.crs is None or not required <= set(frame):
        raise ValueError("地图需坐标系、稳定编号、class、地层名、地区和时代属性")
    if frame.feature_id.isna().any() or frame.feature_id.astype(str).duplicated().any():
        raise ValueError("稳定要素编号缺失或重复")
    if any(not str(value).strip() for value in frame.feature_id):
        raise ValueError("稳定要素编号不可为空")
    if (
        frame.geometry.isna().any()
        or frame.geometry.is_empty.any()
        or not frame.geometry.is_valid.all()
    ):
        raise ValueError("初图须有完整、有效面几何")
    if any(
        geometry.geom_type not in {"Polygon", "MultiPolygon"}
        for geometry in frame.geometry
    ):
        raise ValueError("只接受面地图")
    if not (frame.crs.is_projected or frame.crs.is_geographic):
        raise ValueError("初图坐标系须为地理或投影坐标系")
    working_frame(frame, working_epsg)
    return frame


def rules(path):
    result = {}
    for row in table(path, RULE_FIELDS):
        if (
            row["field"] != FIELD
            or row["operation"] != "set_attribute"
            or row["evidence_kind"] != "dictionary_definition"
            or not all(row[key].strip() for key in RULE_FIELDS)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,19}", row["expected_age"])
            or row["rule_id"] in result
        ):
            raise ValueError(
                "仅允许带来源、地区、条件及例外的辞书时代属性规则，规则编号不可重复"
            )
        values = [float(value) for value in row["region_bbox_wgs84"].split(",")]
        if (
            len(values) != 4
            or not all(math.isfinite(value) for value in values)
            or not -180 <= values[0] < values[2] <= 180
            or not -90 <= values[1] < values[3] <= 90
        ):
            raise ValueError("规则地区范围须为有效WGS84边界")
        result[row["rule_id"]] = {**row, "bounds": box(*values)}
    if not result:
        raise ValueError("需要至少一条辞书规则")
    return result


def contexts(path, frame, working_epsg=32646):
    result, identities = {}, set(frame.feature_id.astype(str))
    rows = table(path, CONTEXT_FIELDS)
    for row in rows:
        identity = row["feature_id"]
        if (
            identity not in identities
            or identity in result
            or row["evidence_kind"] != "spatial_context"
        ):
            raise ValueError("上下文须唯一绑定当前地图要素，且明确为spatial_context")
        if (
            not row["source"].strip()
            or not row["age_evidence"].strip()
            or not row["limitations"].strip()
        ):
            raise ValueError("上下文必须说明来源、时代证据状态和解释限制")
        area, distance = float(row["area_m2"]), float(row["nearest_structure_m"])
        if not all(math.isfinite(value) and value >= 0 for value in (area, distance)):
            raise ValueError("面积与构造距离须为非负有限数")
        hits = json.loads(row["mineral_positive_pixels"])
        if not isinstance(hits, dict) or any(
            type(value) is not int or value < 0 for value in hits.values()
        ):
            raise ValueError("蚀变命中仅可为非负像元数")
        result[identity] = row
    if len({row["evidence_id"] for row in rows}) != len(rows):
        raise ValueError("上下文证据编号须唯一")
    for _, feature in working_frame(frame, working_epsg).iterrows():
        if str(feature.feature_id) not in result:
            continue
        row = result[str(feature.feature_id)]
        if row["formation"] != str(feature.formation) or row["region"] != str(
            feature.region
        ):
            raise ValueError("上下文地层与地区不匹配当前地图")
        if not math.isclose(
            float(row["area_m2"]), feature.geometry.area, rel_tol=1e-7, abs_tol=0.05
        ):
            raise ValueError("上下文面积不匹配当前几何")
    return result


def matching_rules(feature, wgs84_geometry, rules_map):
    related = [
        row
        for row in rules_map.values()
        if row["formation"] == str(feature.formation)
        and row["region"] == str(feature.region)
    ]
    supported = [row for row in related if row["bounds"].covers(wgs84_geometry)]
    return related, supported


def reason(feature, rule, context, area_threshold):
    small = "小面积仅作为筛查提示；" if feature.geometry.area <= area_threshold else ""
    return (
        f"{small}地层标识为{feature.formation}，适用地区为{feature.region}；"
        f"{rule['source']}（{rule['source_locator']}）时代字段为{rule['expected_age']}，"
        f"当前属性为{feature[FIELD]}。仅修正时代字段，保留class、岩性和边界。"
        f"构造距离{float(context['nearest_structure_m']):.1f}米、蚀变命中已核对，仅作上下文；"
        f"{rule['conditions']}；例外：{rule['exceptions']}。"
    )


def inspect(frame, rules_map, context_map, threshold=200000, working_epsg=32646):
    checksum, issues = map_checksum(frame, working_epsg), []
    wgs = frame.to_crs(4326)
    for index, feature in working_frame(frame, working_epsg).iterrows():
        related, supported = matching_rules(
            feature, wgs.at[index, "geometry"], rules_map
        )
        if not related:
            continue
        ages = {row["expected_age"] for row in supported}
        if len(ages) == 1 and str(feature[FIELD]) in ages:
            continue
        available = str(feature.feature_id) in context_map
        status = (
            "repairable"
            if len(ages) == 1
            and available
            and str(feature[FIELD]) not in {"", "未赋值"}
            else "needs_review"
        )
        chosen = supported[0] if supported else related[0]
        explanation = (
            reason(feature, chosen, context_map[str(feature.feature_id)], threshold)
            if available
            else "缺少该对象的空间上下文，须先补资料。"
        )
        if status == "needs_review":
            explanation = (
                "时代缺失、规则冲突或超出适用地区；保留人工复核。" + explanation
            )
        issues.append(
            {
                "feature_id": str(feature.feature_id),
                "field": FIELD,
                "old_value": str(feature[FIELD]),
                "new_value": next(iter(ages)) if status == "repairable" else "",
                "evidence_id": chosen["evidence_id"],
                "rule_id": chosen["rule_id"],
                "status": status,
                "reason": explanation,
                "input_checksum": checksum,
            }
        )
    return issues


def parameters(context):
    threshold = context.parameters.get("screen_area_m2", 200000)
    maximum = context.parameters.get("max_changes", 5)
    epsg = context.parameters.get("working_epsg", 32646)
    if (
        type(threshold) not in (int, float)
        or not math.isfinite(threshold)
        or threshold < 0
    ):
        raise ValueError("筛查面积须为非负有限数，仅作提示")
    if type(maximum) is not int or not 1 <= maximum <= 10:
        raise ValueError("每轮修改上限须为1至10的整数")
    if type(epsg) is not int or not 1 <= epsg <= 999999:
        raise ValueError("工作投影EPSG须为有效整数")
    return threshold, maximum, epsg


def report(context, metrics, summary, facts_key):
    write_table(context.output_path("statistics.csv"), [metrics], list(metrics))
    value = {
        "version": 1,
        "status": "passed",
        "summary": summary,
        "metrics": metrics,
        "knowledgeFacts": {facts_key: metrics},
    }
    with open(context.output_path("quality.json"), "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
