"""Survey consistency and polygon checks; no access to acceptance truth."""

import csv
import hashlib
import json
import math

import geopandas as gpd
from shapely.geometry import Point
from shapely.validation import explain_validity

FIELDS = [
    "feature_id",
    "field",
    "old_value",
    "new_value",
    "evidence_id",
    "rule_id",
    "status",
    "reason",
    "input_checksum",
]
EDITABLE = {"contact_type", "lithology"}


def map_checksum(frame):
    records = []
    for _, row in frame.iterrows():
        records.append(
            {
                "feature_id": str(row.feature_id),
                "geometry": row.geometry.normalize().wkb_hex,
                **{field: str(row.get(field, "")) for field in sorted(EDITABLE)},
            }
        )
    payload = {
        "crs": frame.crs.to_wkt(),
        "features": sorted(records, key=lambda row: row["feature_id"]),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def table(path):
    with open(path, encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def rule_map(rows):
    result = {}
    for row in rows:
        field = row.get("field")
        identity = row.get("rule_id")
        confidence = float(row.get("min_confidence", "0.8"))
        if (
            field not in EDITABLE
            or not identity
            or identity in result
            or row.get("operation") != "set_attribute"
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("结构化规则字段、操作、置信度或编号无效")
        values = set(row.get("allowed_values", "").split("|")) - {""}
        if not values:
            raise ValueError("规则需要明确列出允许的新值")
        result[identity] = {**row, "values": values, "minimum": confidence}
    return result


def validate_frame(frame):
    if frame.empty or frame.crs is None or "feature_id" not in frame:
        raise ValueError("地图需坐标系、稳定feature_id和至少一个要素")
    if frame.feature_id.isna().any() or frame.feature_id.astype(str).duplicated().any():
        raise ValueError("feature_id不可缺失或重复")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError("本次检查不接受缺失或空几何")
    if any(
        geom.geom_type not in {"Polygon", "MultiPolygon"} for geom in frame.geometry
    ):
        raise ValueError("本次检查接受面或多面地图")


def survey_applies(survey, feature, rule, tolerance):
    if str(survey.get("feature_id")) != str(feature.feature_id):
        return False
    if (
        survey.get("field") != rule["field"]
        or survey.get("value") not in rule["values"]
    ):
        return False
    try:
        confidence = float(survey["confidence"])
        x, y = float(survey["x"]), float(survey["y"])
    except (ValueError, KeyError):
        return False
    return (
        math.isfinite(confidence)
        and rule["minimum"] <= confidence <= 1
        and math.isfinite(x)
        and math.isfinite(y)
        and feature.geometry.distance(Point(x, y)) <= tolerance
        and bool(survey.get("source"))
        and bool(survey.get("evidence_id"))
    )


def run(context):
    frame = gpd.read_file(context.input_path("features"), layer="data")
    validate_frame(frame)
    working_epsg = int(context.parameters.get("working_epsg", 32645))
    frame = frame.to_crs(epsg=working_epsg)
    if not frame.crs.is_projected or any(
        abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in frame.crs.axis_info[:2]
    ):
        raise ValueError("本次检查需要米制投影地图，以明确空间容差")
    rules = rule_map(table(context.input_path("rules")))
    surveys = table(context.input_path("surveys"))
    evidence_ids = [row.get("evidence_id", "") for row in surveys]
    if any(not value for value in evidence_ids) or len(set(evidence_ids)) != len(
        evidence_ids
    ):
        raise ValueError("调查证据编号不可缺失或重复")
    tolerance = float(context.parameters.get("tolerance_m", 1))
    overlap_limit = float(context.parameters.get("overlap_area_m2", 1))
    if not all(
        math.isfinite(value) and value >= 0 for value in (tolerance, overlap_limit)
    ):
        raise ValueError("空间容差须为非负有限数值")
    checksum = map_checksum(frame)
    issues, positions = [], []

    def add(feature, field, old, new, evidence, rule, status, reason):
        issues.append(
            dict(
                zip(
                    FIELDS,
                    [
                        str(feature.feature_id),
                        field,
                        old,
                        new,
                        evidence,
                        rule,
                        status,
                        reason,
                        checksum,
                    ],
                )
            )
        )
        positions.append(feature.geometry.representative_point())

    for _, feature in frame.iterrows():
        if not feature.geometry.is_valid:
            add(
                feature,
                "geometry",
                "invalid",
                "",
                "",
                "geometry-validity",
                "repairable",
                "几何无效：" + explain_validity(feature.geometry),
            )
        for rule_id, rule in rules.items():
            field = rule["field"]
            if field not in frame:
                raise ValueError("地图缺少规则核对字段：" + field)
            related = [
                row
                for row in surveys
                if str(row.get("feature_id")) == str(feature.feature_id)
                and row.get("field") == field
            ]
            supported = [
                row for row in related if survey_applies(row, feature, rule, tolerance)
            ]
            proposed = {row["value"] for row in supported}
            old = str(feature[field])
            if len(proposed) > 1:
                add(
                    feature,
                    field,
                    old,
                    "",
                    "|".join(row["evidence_id"] for row in supported),
                    rule_id,
                    "needs_review",
                    "同一对象有互相冲突的高置信调查记录",
                )
            elif proposed and old not in proposed:
                evidence = supported[0]
                add(
                    feature,
                    field,
                    old,
                    evidence["value"],
                    evidence["evidence_id"],
                    rule_id,
                    "repairable",
                    "编号、空间位置、允许值和置信度均满足调查一致性规则",
                )
            elif not supported and any(row.get("value") != old for row in related):
                add(
                    feature,
                    field,
                    old,
                    "",
                    "|".join(row["evidence_id"] for row in related),
                    rule_id,
                    "needs_review",
                    "记录与初图不同，但位置、置信度或允许值尚不满足修改条件",
                )
    valid = frame[frame.geometry.is_valid]
    pairs = 0
    for i, left in valid.iterrows():
        for j, right in valid.iterrows():
            if j <= i:
                continue
            area = left.geometry.intersection(right.geometry).area
            if area > overlap_limit:
                pairs += 1
                add(
                    left,
                    "geometry",
                    "overlap",
                    "",
                    str(right.feature_id),
                    "polygon-overlap",
                    "needs_review",
                    f"与{right.feature_id}重叠{area:.3f}平方米，需要边界资料复核",
                )
    with open(
        context.output_path("issues.csv"), "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(issues)
    if issues:
        gpd.GeoDataFrame(issues, geometry=positions, crs=frame.crs).to_file(
            context.output_path("issues.gpkg"),
            layer="issues",
            driver="GPKG",
            index=False,
        )
    metrics = {
        "total_features": len(frame),
        "invalid_geometry": int((~frame.geometry.is_valid).sum()),
        "issue_count": len(issues),
        "repairable": sum(row["status"] == "repairable" for row in issues),
        "needs_review": sum(row["status"] == "needs_review" for row in issues),
        "overlap_pairs": pairs,
        "input_checksum": checksum,
        "working_epsg": working_epsg,
        "gap_check": "未提供调查边界，未判定缝隙",
        "reference_used": False,
    }
    with open(
        context.output_path("statistics.csv"), "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(metrics))
        writer.writeheader()
        writer.writerow(metrics)
    with open(context.output_path("quality.json"), "w", encoding="utf-8") as stream:
        json.dump(
            {
                "version": 1,
                "status": "passed",
                "summary": "检查产物有效；问题状态逐项记录，不等同于地图无误",
                "metrics": metrics,
                "knowledgeFacts": {"geologyCheck": metrics},
            },
            stream,
            ensure_ascii=False,
        )
