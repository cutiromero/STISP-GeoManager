"""Bounded map integrity and formation-age checks, using runtime inputs only."""

import csv
import hashlib
import json
import math

import geopandas as gpd
from pyproj import CRS
from shapely import set_precision
from shapely.geometry import box, mapping
from shapely.ops import unary_union

EDIT_FIELDS = [
    "feature_id",
    "field",
    "old_value",
    "new_value",
    "evidence_id",
    "rule_id",
    "reason",
]
CHANGE_FIELDS = EDIT_FIELDS + ["issue_id", "kind", "input_checksum"]
ISSUE_FIELDS = EDIT_FIELDS + [
    "issue_id",
    "kind",
    "status",
    "input_checksum",
    "area_m2",
    "geometry_json",
    "bounds_json",
    "knowledge_seed",
    "knowledge_id",
    "knowledge_revision",
    "coverage_id",
    "current_label",
    "suggested_label",
]
CLASS_FIELDS = ["class", "name", "code", "path"]
MAP_FIELDS = {"feature_id", "formation", "region", "geologic_age", *CLASS_FIELDS}
COVERAGE_FIELDS = {
    "coverage_id",
    "role",
    "complete_coverage",
    "no_water",
    "no_uninvestigated",
    "region",
    "source",
    "source_locator",
}
RULE_FIELDS = {
    "rule_id",
    "kind",
    "name",
    "scope",
    "conditions",
    "exceptions",
    "evidence_id",
    "evidence_kind",
    "source",
    "source_locator",
    "region",
    "region_bbox_wgs84",
    "formation",
    "expected_age",
    "knowledge_seed",
}


def scalar(value):
    if value is None:
        return ""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value)


def table(path, required):
    with open(path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not required <= set(reader.fieldnames or []):
            raise ValueError("CSV缺少字段：" + ",".join(sorted(required)))
        rows = list(reader)
    if len(rows) > 20000 or any(
        None in row or any(row[key] is None for key in required) for row in rows
    ):
        raise ValueError("CSV字段无效或超过20000条")
    return rows


def write_table(path, rows, fields):
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parameters(context):
    result = {
        "working_epsg": context.parameters.get("working_epsg", 32646),
        "max_changes": context.parameters.get("max_changes", 2),
        "max_gap_area_m2": context.parameters.get("max_gap_area_m2", 300000),
        "geometry_tolerance_m": context.parameters.get("geometry_tolerance_m", 0.01),
    }
    if (
        type(result["working_epsg"]) is not int
        or not 1 <= result["working_epsg"] <= 999999
    ):
        raise ValueError("工作投影EPSG须为有效整数")
    if type(result["max_changes"]) is not int or not 1 <= result["max_changes"] <= 10:
        raise ValueError("每轮修改上限须为1至10的整数")
    for key, maximum in (("max_gap_area_m2", 10000000), ("geometry_tolerance_m", 0.1)):
        value = result[key]
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not 0 < value <= maximum
        ):
            raise ValueError("面积筛查上限或几何容差无效")
    target = CRS.from_epsg(result["working_epsg"])
    if not target.is_projected or any(
        abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in target.axis_info[:2]
    ):
        raise ValueError("面积核对需要米制投影")
    return result


def vector(path, required, identity):
    frame = gpd.read_file(path)
    if frame.empty or frame.crs is None or not required <= set(frame):
        raise ValueError("面数据缺少坐标系或必要字段：" + ",".join(sorted(required)))
    if (
        frame[identity].isna().any()
        or frame[identity].astype(str).duplicated().any()
        or any(not scalar(value).strip() for value in frame[identity])
    ):
        raise ValueError("稳定编号缺失或重复")
    if (
        frame.geometry.isna().any()
        or frame.geometry.is_empty.any()
        or not frame.geometry.is_valid.all()
        or any(
            geom.geom_type not in {"Polygon", "MultiPolygon"} for geom in frame.geometry
        )
    ):
        raise ValueError("只接受完整有效的面几何")
    for field in required:
        if (
            field not in {"complete_coverage", "no_water", "no_uninvestigated"}
            and frame[field].isna().any()
        ):
            raise ValueError("必要字段不可为空值：" + field)
    frame[identity] = frame[identity].map(scalar)
    return frame


def read_inputs(context, settings):
    frame = vector(context.input_path("features"), MAP_FIELDS, "feature_id")
    for _, group in frame.groupby(frame["class"].map(scalar)):
        if any(group[key].map(scalar).nunique() != 1 for key in CLASS_FIELDS[1:]):
            raise ValueError("同一class的name/code/path须一致；同名不同class保持独立")
    coverage = vector(context.input_path("coverage"), COVERAGE_FIELDS, "coverage_id")
    if not set(coverage.role) <= {"coverage", "exclusion"} or not any(
        coverage.role == "coverage"
    ):
        raise ValueError("覆盖资料需要coverage范围，例外范围使用exclusion")
    if any(
        not scalar(value).strip()
        for field in ("region", "source", "source_locator")
        for value in coverage[field]
    ):
        raise ValueError("覆盖资料须明确地区、来源和定位")
    rules = table(context.input_path("rules"), RULE_FIELDS)
    seen = set()
    for rule in rules:
        required = RULE_FIELDS - {"formation", "expected_age"}
        if rule["rule_id"] in seen or not all(rule[key].strip() for key in required):
            raise ValueError("规则编号不可重复，来源、前提与例外不可缺失")
        seen.add(rule["rule_id"])
        expected_kind = {"fill_gap": "project_rule", "set_age": "dictionary_definition"}
        if (
            rule["kind"] not in expected_kind
            or rule["evidence_kind"] != expected_kind[rule["kind"]]
        ):
            raise ValueError("仅接受项目整理的漏填规则和辞书时代定义")
        if rule["kind"] == "set_age" and (
            not rule["formation"].strip() or not rule["expected_age"].strip()
        ):
            raise ValueError("时代规则须明确地层与时代")
        bounds = [float(value) for value in rule["region_bbox_wgs84"].split(",")]
        if (
            len(bounds) != 4
            or not all(math.isfinite(value) for value in bounds)
            or not -180 <= bounds[0] < bounds[2] <= 180
            or not -90 <= bounds[1] < bounds[3] <= 90
        ):
            raise ValueError("规则范围须为有效WGS84边界")
    if not rules:
        raise ValueError("至少需要一条有来源规则")
    epsg = settings["working_epsg"]
    working, working_coverage = frame.to_crs(epsg), coverage.to_crs(epsg)
    overlap = float(working.geometry.area.sum() - unary_union(working.geometry).area)
    if overlap > max(
        settings["geometry_tolerance_m"] ** 2, working.geometry.area.sum() * 1e-10
    ):
        raise ValueError("输入图斑有面重叠，须先复核制图完整性")
    areas = working_coverage.loc[working_coverage.role == "coverage", "geometry"]
    if (
        float(areas.area.sum() - unary_union(areas).area)
        > settings["geometry_tolerance_m"] ** 2
    ):
        raise ValueError("完整覆盖范围不可相互重叠")
    return frame, coverage, rules


def geometry_digest(geometry):
    return hashlib.sha256(set_precision(geometry, 0.000001).normalize().wkb).hexdigest()


def map_records(frame, epsg, identity):
    working = frame.to_crs(epsg)
    records = []
    for _, row in working.iterrows():
        record = {
            key: scalar(row[key]) for key in sorted(set(frame) - {frame.geometry.name})
        }
        record["geometry"] = geometry_digest(row.geometry)
        records.append(record)
    return sorted(records, key=lambda row: row[identity])


def input_checksum(frame, coverage, rules, epsg):
    payload = {
        "working_epsg": epsg,
        "features": map_records(frame, epsg, "feature_id"),
        "coverage": map_records(coverage, epsg, "coverage_id"),
        "rules": sorted(rules, key=lambda row: row["rule_id"]),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def truth(value):
    return scalar(value).strip().lower() in {"true", "1", "yes"}


def applicable(rule, region, geometry, epsg):
    if rule["region"] != region:
        return False
    wgs = gpd.GeoSeries([geometry], crs=epsg).to_crs(4326).iloc[0]
    return box(
        *[float(value) for value in rule["region_bbox_wgs84"].split(",")]
    ).covers(wgs)


def issue(
    row, rule, geometry, epsg, checksum, kind, old, new, status, reason, coverage_id=""
):
    wgs = gpd.GeoSeries([geometry], crs=epsg).to_crs(4326).iloc[0]
    return {
        "feature_id": scalar(row["feature_id"]),
        "field": "class" if kind == "fill_gap" else "geologic_age",
        "old_value": old,
        "new_value": new,
        "evidence_id": rule["evidence_id"],
        "rule_id": rule["rule_id"],
        "reason": reason,
        "issue_id": kind + "-" + geometry_digest(geometry)[:20],
        "kind": kind,
        "status": status,
        "input_checksum": checksum,
        "area_m2": float(geometry.area),
        "geometry_json": json.dumps(
            mapping(wgs), ensure_ascii=False, separators=(",", ":")
        ),
        "bounds_json": json.dumps(list(wgs.bounds)),
        "knowledge_seed": rule["knowledge_seed"],
        "knowledge_id": rule.get("knowledge_id", ""),
        "knowledge_revision": rule.get("knowledge_revision", rule.get("revision", "")),
        "coverage_id": coverage_id,
        "current_label": "未分类空白"
        if kind == "fill_gap"
        else json.loads(rule.get("age_labels_json") or "{}").get(old, old),
        "suggested_label": (
            f"{scalar(row['name'])}（{scalar(row['code'])}）"
            if status == "repairable"
            else ""
        )
        if kind == "fill_gap"
        else rule.get("expected_age_label") or new,
        "_geometry": geometry,
    }


def parts(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [part for child in geometry.geoms for part in parts(child)]
    return []


def inspect(frame, coverage, rules, settings):
    epsg, tolerance = settings["working_epsg"], settings["geometry_tolerance_m"]
    checksum = input_checksum(frame, coverage, rules, epsg)
    working, boundaries = frame.to_crs(epsg), coverage.to_crs(epsg)
    present = unary_union(working.geometry)
    excluded = unary_union(boundaries.loc[boundaries.role == "exclusion", "geometry"])
    issues = []
    for _, area in boundaries.loc[boundaries.role == "coverage"].iterrows():
        for gap in parts(area.geometry.difference(present)):
            if gap.area <= tolerance**2:
                continue
            nearby = working.loc[working.geometry.distance(gap) <= tolerance]
            rules_here = [
                rule
                for rule in rules
                if rule["kind"] == "fill_gap"
                and applicable(rule, scalar(area.region), gap, epsg)
            ]
            if not rules_here:
                continue
            host = (
                nearby.iloc[0]
                if len(nearby) == 1
                else {"feature_id": "gap-" + geometry_digest(gap)[:16]}
            )
            failures = []
            if not all(
                truth(area[field])
                for field in ("complete_coverage", "no_water", "no_uninvestigated")
            ):
                failures.append("完整覆盖、非水体和非未调查区的前提尚未全部确认")
            if area.geometry.boundary.distance(gap) <= tolerance:
                failures.append("空白连到制图边界，不能按内部漏填处理")
            if not excluded.is_empty and excluded.distance(gap) <= tolerance:
                failures.append("空白与明确例外范围相交")
            if (
                len(nearby) != 1
                or len(nearby) == 1
                and not nearby.iloc[0]
                .geometry.boundary.buffer(tolerance)
                .covers(gap.boundary)
            ):
                failures.append("空白没有被唯一图斑完整包围")
            if len(nearby) == 1 and scalar(host.region) != scalar(area.region):
                failures.append("图斑与覆盖资料的适用地区不一致")
            if len(rules_here) != 1:
                failures.append("存在多个适用规则，需要复核")
            if gap.area > settings["max_gap_area_m2"]:
                failures.append("超过本轮小范围处理上限，需要复核")
            rule = rules_here[0]
            status = "needs_review" if failures else "repairable"
            target = scalar(host["class"]) if not failures else ""
            reason = (
                "；".join(failures)
                if failures
                else f"发现{gap.area:.1f}平方米内部空白；覆盖资料确认本范围完整、无水体和未调查区，空白由图斑{host.feature_id}（类别{target}，{host['name']}）单独包围。依据{rule['name']}，建议填补遗漏并保留该图斑分类和其他边界。"
            )
            issues.append(
                issue(
                    host,
                    rule,
                    gap,
                    epsg,
                    checksum,
                    "fill_gap",
                    "未分类",
                    target,
                    status,
                    reason,
                    scalar(area.coverage_id),
                )
            )
    for _, feature in working.iterrows():
        matching = [
            rule
            for rule in rules
            if rule["kind"] == "set_age"
            and rule["formation"] == scalar(feature.formation)
            and applicable(rule, scalar(feature.region), feature.geometry, epsg)
        ]
        if not matching or all(
            scalar(feature.geologic_age) == rule["expected_age"] for rule in matching
        ):
            continue
        ages = {rule["expected_age"] for rule in matching}
        repairable = len(ages) == 1 and bool(scalar(feature.geologic_age).strip())
        rule = matching[0]
        reason = f"图斑{feature.feature_id}记录为{feature.formation}，时代字段为{feature.geologic_age}；{rule['source']}（{rule['source_locator']}）在适用范围内给出{rule['expected_age']}。建议仅更新时代属性，保留岩性类别和边界。"
        if not repairable:
            reason = "时代记录缺失或知识互相冲突，保留复核。" + reason
        issues.append(
            issue(
                feature,
                rule,
                feature.geometry,
                epsg,
                checksum,
                "set_age",
                scalar(feature.geologic_age),
                next(iter(ages)) if repairable else "",
                "repairable" if repairable else "needs_review",
                reason,
            )
        )
    return sorted(issues, key=lambda row: (row["kind"], row["issue_id"]))


def statistics(before, after, epsg):
    rows = []
    frames = [before.to_crs(epsg), after.to_crs(epsg)]
    totals = [float(frame.geometry.area.sum()) for frame in frames]
    keys = sorted(set(before["class"].map(scalar)) | set(after["class"].map(scalar)))
    for key in keys:
        groups = [frame.loc[frame["class"].map(scalar) == key] for frame in frames]
        label = groups[0].iloc[0] if len(groups[0]) else groups[1].iloc[0]
        areas = [float(group.geometry.area.sum()) for group in groups]
        rows.append(
            {
                "class": key,
                "name": scalar(label["name"]),
                "code": scalar(label["code"]),
                "path": scalar(label["path"]),
                "before_count": len(groups[0]),
                "after_count": len(groups[1]),
                "before_area_m2": areas[0],
                "after_area_m2": areas[1],
                "delta_area_m2": areas[1] - areas[0],
                "before_percentage": 100 * areas[0] / totals[0],
                "after_percentage": 100 * areas[1] / totals[1],
            }
        )
    return rows


def write_geojson(path, rows, epsg, properties=None):
    features = []
    for row in rows:
        geometry = gpd.GeoSeries([row["_geometry"]], crs=epsg).to_crs(4326).iloc[0]
        values = {
            key: row.get(key, "")
            for key in ISSUE_FIELDS
            if key not in {"geometry_json", "bounds_json"}
        }
        if properties:
            values.update(properties(row))
        features.append(
            {"type": "Feature", "geometry": mapping(geometry), "properties": values}
        )
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(
            {"type": "FeatureCollection", "features": features},
            stream,
            ensure_ascii=False,
            allow_nan=False,
        )


def write_locations(path, rows, epsg, properties=None):
    if not rows:
        return
    records, geometries = [], []
    for row in rows:
        values = {
            key: row.get(key, "")
            for key in ISSUE_FIELDS
            if key not in {"geometry_json", "bounds_json"}
        }
        if properties:
            values.update(properties(row))
        records.append(values)
        geometries.append(row["_geometry"])
    gpd.GeoDataFrame(records, geometry=geometries, crs=epsg).to_crs(4326).to_file(
        path, layer="data", driver="GPKG", index=False
    )


def quality(context, metrics, summary, key, needs_review=False):
    value = {
        "version": 1,
        "status": "needs_review" if needs_review else "passed",
        "summary": summary,
        "metrics": metrics,
        "knowledgeFacts": {key: metrics},
    }
    with open(context.output_path("quality.json"), "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)


def validated_plan(context, frame, coverage, rules, settings):
    submitted = table(context.input_path("changes"), set(CHANGE_FIELDS))
    if not submitted or len(submitted) > settings["max_changes"]:
        raise ValueError("获批操作须为非空且不超过本轮上限")
    eligible = {
        row["issue_id"]: row
        for row in inspect(frame, coverage, rules, settings)
        if row["status"] == "repairable"
    }
    seen, accepted = set(), []
    for change in submitted:
        verified = eligible.get(change["issue_id"])
        if verified is None or change["issue_id"] in seen:
            raise ValueError("操作重复或问题不满足当前证据条件")
        seen.add(change["issue_id"])
        for key in set(CHANGE_FIELDS) - {"reason"}:
            if change[key] != scalar(verified[key]):
                raise ValueError(
                    "修改对象、范围、原值、目标、规则、引用或内容校验和不匹配：" + key
                )
        if not change["reason"].strip():
            raise ValueError("获批修改理由不可为空")
        if change.get("geometry_json") and json.loads(
            change["geometry_json"]
        ) != json.loads(verified["geometry_json"]):
            raise ValueError("提交的空间范围与实际问题不一致")
        accepted.append(
            {
                **verified,
                "verified_reason": verified["reason"],
                "reason": change["reason"],
            }
        )
    return accepted


def corrected(frame, accepted, settings):
    result = frame.copy()
    before = frame.to_crs(settings["working_epsg"])
    for item in accepted:
        index = result.index[result.feature_id == item["feature_id"]][0]
        if item["kind"] == "set_age":
            result.at[index, "geologic_age"] = item["new_value"]
        elif item["kind"] == "fill_gap":
            if scalar(result.at[index, "class"]) != item["new_value"]:
                raise ValueError("填补目标与宿主类别不一致")
            geometry = (
                gpd.GeoSeries([item["_geometry"]], crs=settings["working_epsg"])
                .to_crs(frame.crs)
                .iloc[0]
            )
            result.at[index, "geometry"] = result.at[index, "geometry"].union(geometry)
    after = result.to_crs(settings["working_epsg"])
    changed_ids = {item["feature_id"] for item in accepted}
    for index, row in result.iterrows():
        old = frame.loc[index]
        if not row.geometry.is_valid or any(
            scalar(row[key]) != scalar(old[key]) for key in CLASS_FIELDS
        ):
            raise ValueError("修正造成无效几何或改变分类映射")
        if scalar(row.feature_id) not in changed_ids and not row.geometry.equals_exact(
            old.geometry, 0
        ):
            raise ValueError("未获批对象发生几何变化")
        additions = [
            item["_geometry"]
            for item in accepted
            if item["feature_id"] == row.feature_id and item["kind"] == "fill_gap"
        ]
        actual = before.at[index, "geometry"].symmetric_difference(
            after.at[index, "geometry"]
        )
        planned = unary_union(additions)
        if actual.symmetric_difference(planned).area > max(0.001, planned.area * 1e-9):
            raise ValueError("实际地图变化超出获批范围")
    return result
