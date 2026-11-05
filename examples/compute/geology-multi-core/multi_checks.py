"""Measured trial-rule findings. Inspection never edits an input feature."""

import math

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from multi_io import ISSUE_FIELDS, digest, dump, geojson_geometry, scalar
from multi_lithology_merge import candidates as merge_candidates


def issue(
    element,
    feature_id,
    geometry,
    rule,
    snapshot,
    config,
    measurements,
    reason,
    action="review",
    target="",
    status="review",
    actions=None,
):
    allowed = actions or ["keep", "review", "downweight", "exclude"]
    return {
        "issue_id": "I-"
        + digest([element, str(feature_id), rule["id"], rule["version"]])[:24],
        "element": element,
        "feature_id": str(feature_id),
        "rule_id": rule["id"],
        "rule_version": rule["version"],
        "knowledge_id": rule["knowledge_id"],
        "knowledge_revision": rule["knowledge_revision"],
        "status": status,
        "suggested_action": action,
        "allowed_actions_json": dump(allowed),
        "target_code": target,
        "measurements_json": dump(measurements),
        "conditions": rule.get("condition", ""),
        "exceptions": rule.get("basis", {}).get("gap", ""),
        "reason": reason,
        "snapshot_hash": snapshot,
        "geometry_json": geojson_geometry(geometry, config["working_epsg"]),
        "_geometry": geometry,
    }


def lithology_findings(
    lithology, faults, area, rules, units, aliases, snapshot, config
):
    result = []
    fault_union = unary_union(faults.geometry)
    if "L-05" in rules:
        for index, host_index, measured in merge_candidates(
            lithology, faults, aliases, rules["L-05"]
        ):
            row = lithology.loc[index]
            result.append(
                issue(
                    "lithology",
                    row.feature_id,
                    row.geometry.union(lithology.at[host_index, "geometry"]),
                    rules["L-05"],
                    snapshot,
                    config,
                    measured,
                    f"两块图斑名称和代号一致，共享{measured['shared_boundary_m']:.1f}米边界，边界附近未发现构造线。本轮按同一单元整理，可批准去掉内部划分，外部范围和类别面积保持。",
                    "merge",
                    row.geo_sym,
                    "suggested",
                    ["merge", "keep", "review"],
                )
            )
    for _, row in lithology.iterrows():
        expected = aliases.get(row["name"])
        if "L-03" in rules and expected and expected != row.geo_sym:
            result.append(
                issue(
                    "lithology",
                    row.feature_id,
                    row.geometry,
                    rules["L-03"],
                    snapshot,
                    config,
                    {
                        "name": row["name"],
                        "observed_code": row.geo_sym,
                        "expected_code": expected,
                    },
                    f"名称对应冻结代号{expected}，当前记录为{row.geo_sym}；建议只修正代号。",
                    "set_code",
                    expected,
                    "suggested",
                    ["set_code", "keep", "review"],
                )
            )
            continue
        geometry = row.geometry
        exteriors = unary_union(
            [
                LineString(part.exterior.coords)
                for part in getattr(geometry, "geoms", [geometry])
            ]
        )
        perimeter = exteriors.length
        if (
            not perimeter
            or exteriors.intersection(area.boundary.buffer(0.5)).length
            > perimeter * 0.01
        ):
            continue
        neighbours = lithology.iloc[
            lithology.sindex.query(geometry.buffer(0.5), predicate="intersects")
        ]
        neighbours = neighbours.loc[neighbours.feature_id != row.feature_id]
        if neighbours.empty:
            continue
        shares = {
            code: exteriors.intersection(unary_union(group.geometry).buffer(0.5)).length
            for code, group in neighbours.groupby("geo_sym")
        }
        host, shared = max(shares.items(), key=lambda pair: pair[1])
        ratio = min(1.0, shared / perimeter)
        current, surrounding = units.get(row.geo_sym, {}), units.get(host, {})
        age, host_age = current.get("age_ma"), surrounding.get("age_ma")
        candidates = []
        if (
            current.get("category") == surrounding.get("category") == "stratum"
            and age is not None
            and host_age is not None
            and age > host_age
        ):
            candidates.append("L-01")
        if (
            current.get("category") == surrounding.get("category") == "intrusive"
            and age is not None
            and host_age is not None
            and age > host_age
        ):
            candidates.append("L-02")
        if current.get("group") == "volcanic" and (
            surrounding.get("group") == "metamorphic_high"
            or surrounding.get("group") == "carbonate_interbed"
            and (host_age or 0) > 1000
        ):
            candidates.append("L-04")
        for identifier in candidates:
            if identifier not in rules:
                continue
            rule, params = rules[identifier], rules[identifier]["params"]
            distance = (
                geometry.distance(fault_union) if not fault_union.is_empty else None
            )
            if (
                ratio < params.get("enclose_ratio", 0.95)
                or geometry.area > params.get("max_area_km2", 3) * 1e6
                or distance is not None
                and distance <= params.get("fault_buffer_m", 100)
            ):
                continue
            confidence = scalar(row.get("conf"))
            # Three tiers: a confident classification is an exception candidate,
            # a weak one is a reclassification suggestion, the rest need a geologist.
            if confidence is not None and float(confidence) >= params.get(
                "report_conf_max", 0.8
            ):
                status, action = "exception", "review"
                reason = f"{row.geo_sym}图斑的{ratio:.1%}外边界由{host}单元包围，但分类置信度{float(confidence):.2f}较高，列为规则例外候选，供专家浏览，不作为冲突报出。"
            elif confidence is not None and float(confidence) < params.get(
                "conf_auto", 0.6
            ):
                status, action = "suggested", "reclassify"
                reason = f"{row.geo_sym}图斑的{ratio:.1%}外边界由{host}单元包围，分类置信度仅{float(confidence):.2f}，建议重分类为围岩{host}；批准后才修改。"
            else:
                status, action = "review", "review"
                reason = f"{row.geo_sym}图斑的{ratio:.1%}外边界由{host}单元包围；这是需要解释的关系，尚不能仅凭面积或新老排序判错。保留当前分类，待核查接触关系、残留体或构造例外。"
            measurement = {
                "area_m2": float(geometry.area),
                "shared_boundary_ratio": ratio,
                "host_code": host,
                "fault_distance_m": distance,
                "simulation_confidence": confidence,
                "classification_confidence_kind": row.get(
                    "confidence_kind", "模拟分类置信度"
                ),
                "host_feature_ids": sorted(
                    neighbours.loc[neighbours.geo_sym == host, "feature_id"].tolist()
                ),
                "age_ma": age,
                "host_age_ma": host_age,
            }
            result.append(
                issue(
                    "lithology",
                    row.feature_id,
                    geometry,
                    rule,
                    snapshot,
                    config,
                    measurement,
                    reason,
                    action,
                    host,
                    status,
                    ["keep", "review", "reclassify", "merge"],
                )
            )
    return result


def line_parts(geometry):
    return [geometry] if geometry.geom_type == "LineString" else list(geometry.geoms)


def line_metrics(geometry, turn_angle):
    chord, turns = 0.0, 0
    for line in line_parts(geometry):
        coords = np.asarray(line.coords)
        chord += float(np.linalg.norm(coords[-1] - coords[0]))
        for index in range(1, len(coords) - 1):
            first, second = (
                coords[index] - coords[index - 1],
                coords[index + 1] - coords[index],
            )
            length = np.linalg.norm(first) * np.linalg.norm(second)
            if length > 0:
                angle = math.degrees(
                    math.acos(float(np.clip(first @ second / length, -1, 1)))
                )
                turns += angle > turn_angle
    return geometry.length / max(chord, 1e-9), int(turns)


def structure_findings(faults, lithology, rules, units, snapshot, config):
    result = []
    if "S-01" in rules:
        codes = rules["S-01"]["params"].get(
            "cover_units",
            [code for code, unit in units.items() if unit.get("group") == "loose"],
        )
        cover = unary_union(lithology.loc[lithology.geo_sym.isin(codes), "geometry"])
    for index, row in faults.iterrows():
        line, measurements, hits = (
            row.geometry,
            {"length_m": float(row.geometry.length)},
            [],
        )
        if not line.length:
            continue
        if "S-01" in rules:
            params = rules["S-01"]["params"]
            fraction = float(line.intersection(cover).length / line.length)
            endpoints = [
                Point(part.coords[end]) for part in line_parts(line) for end in (0, -1)
            ]
            endpoints_cover = all(cover.covers(point) for point in endpoints)
            measurements.update(
                cover_ratio=fraction, endpoints_in_cover=endpoints_cover
            )
            if fraction >= params.get("cover_ratio", 0.8) and endpoints_cover:
                hits.append(
                    (
                        "S-01",
                        "exclude",
                        "构造线主要位于松散覆盖层内，两端缺少基岩延伸证据；可能是地貌线，也可能是隐伏断裂，建议批准前复核。",
                    )
                )
        if "S-02" in rules:
            params = rules["S-02"]["params"]
            # Correct direction: the measured object is the line, not duplicated boundaries.
            distance = params.get("boundary_buffer_m", 30)
            corridor = line.buffer(distance + 0.01)
            local = lithology.iloc[
                lithology.sindex.query(corridor, predicate="intersects")
            ]
            boundaries = unary_union(
                [
                    unary_union(group.geometry).boundary.intersection(corridor)
                    for _, group in local.groupby("geo_sym")
                ]
            )
            measured_boundary = boundaries.buffer(distance) if distance else boundaries
            fraction = min(
                1.0, float(line.intersection(measured_boundary).length / line.length)
            )
            sinuosity, _ = line_metrics(line, 100)
            measurements.update(boundary_ratio=fraction, sinuosity=sinuosity)
            if fraction >= params.get(
                "boundary_ratio", 0.8
            ) and sinuosity >= params.get("min_sinuosity", 1.15):
                hits.append(
                    (
                        "S-02",
                        "exclude",
                        "构造线大部分沿岩性界线且弯曲较大；建议核查是否重复描绘了岩性接触线，断裂沿界发育仍是例外。",
                    )
                )
        if "S-03" in rules:
            params = rules["S-03"]["params"]
            nearby = [
                other
                for other in faults.sindex.query(
                    line.buffer(params.get("isolation_m", 1000)), predicate="intersects"
                )
                if other != index
            ]
            measurements["neighbour_count"] = len(nearby)
            if line.length < params.get("max_length_m", 800) and not nearby:
                hits.append(
                    (
                        "S-03",
                        "review",
                        "这是一条孤立短线，延伸性资料不足；保留并建议补充影像检查。",
                    )
                )
        if "S-04" in rules:
            params = rules["S-04"]["params"]
            _, turns = line_metrics(line, params.get("turn_angle", 100))
            measurements["turn_count"] = turns
            if turns >= params.get("min_turns", 2):
                hits.append(
                    (
                        "S-04",
                        "exclude",
                        "构造线存在多次急折返，建议核对解译和影像；确认后可从本轮构造推理中剔除。",
                    )
                )
        for identifier, action, reason in hits:
            result.append(
                issue(
                    "structure",
                    row.line_id,
                    line,
                    rules[identifier],
                    snapshot,
                    config,
                    measurements,
                    reason,
                    action,
                    status="suggested" if action == "exclude" else "review",
                )
            )
    return result


def alteration_findings(alterations, lithology, rules, units, snapshot, config):
    if alterations.empty:
        return [], alterations
    # Aggregate every intersected fragment of the same unit, and separately each rock group.
    overlay = gpd.overlay(
        alterations[["feature_id", "geometry"]],
        lithology[["geo_sym", "geometry"]],
        how="intersection",
        keep_geom_type=False,
    )
    overlay["area_m2"] = overlay.geometry.area
    overlay["group"] = overlay.geo_sym.map(
        lambda code: units.get(code, {}).get("group", "unknown")
    )
    unit_areas = overlay.groupby(["feature_id", "geo_sym"])["area_m2"].sum()
    group_areas = overlay.groupby(["feature_id", "group"])["area_m2"].sum()
    result, annotated = [], alterations.copy()
    annotations = {}
    for _, row in alterations.iterrows():
        area = float(row.geometry.area)
        groups = dict(group_areas.get(row.feature_id, {}))
        codes = dict(unit_areas.get(row.feature_id, {}))
        dominant_code = max(codes, key=codes.get) if len(codes) else ""
        measurement = {
            "area_m2": area,
            "dominant_code": dominant_code,
            "unit_areas_m2": dict(codes),
            "group_areas_m2": dict(groups),
            "group_ratios": {
                key: min(1.0, float(value / area))
                for key, value in dict(groups).items()
            },
            "mineral": row.alt,
        }
        hits = []
        if "A-05" in rules and area < rules["A-05"]["params"].get("min_area_m2", 2600):
            hits.append(
                (
                    "A-05",
                    "exclude",
                    "矿物识别范围小于本案例碎斑阈值，建议核查识别噪声；用户批准后从修正后成果删除，原始识别资料保留。",
                )
            )
        for identifier, group, minerals, action, reason in [
            (
                "A-01",
                "carbonate",
                {"方解石化", "白云石化"},
                "exclude",
                "碳酸盐岩背景上的碳酸盐矿物首先反映原岩，建议从修正后蚀变成果删除；仍不能排除热液叠加，原始识别资料保留。",
            ),
            (
                "A-02",
                "carbonate_interbed",
                {"方解石化", "白云石化"},
                "review",
                "含碳酸盐夹层背景与识别结果重叠，现有资料无法区分夹层和蚀变，保留待查。",
            ),
            (
                "A-03",
                "red_clastic",
                {"赤铁矿化"},
                "downweight",
                "红层背景也可能产生赤铁矿光谱，建议降低其强蚀变证据权重，并核查热液叠加。",
            ),
            (
                "A-04",
                "loose",
                set(),
                "exclude",
                "矿物识别主要落在松散覆盖层上，可能为搬运物或结壳，建议剔除（从修正后成果删除）；原始识别资料保留，可补充基岩资料后复核。",
            ),
        ]:
            if (
                identifier in rules
                and (not minerals or row.alt in minerals)
                and measurement["group_ratios"].get(group, 0)
                >= rules[identifier]["params"].get("dominant_ratio", 0.5)
            ):
                hits.append((identifier, action, reason))
        annotations[row.feature_id] = {
            "dominant_code": dominant_code,
            "dominant_ratio": max(dict(groups).values(), default=0) / area,
            "rule_ids": ",".join(hit[0] for hit in hits),
            "measurements_json": dump(measurement),
        }
        for identifier, action, reason in hits:
            result.append(
                issue(
                    "alteration",
                    row.feature_id,
                    row.geometry,
                    rules[identifier],
                    snapshot,
                    config,
                    measurement,
                    reason,
                    action,
                    status="suggested" if action != "review" else "review",
                )
            )
    for key in ("dominant_code", "dominant_ratio", "rule_ids", "measurements_json"):
        annotated[key] = annotated.feature_id.map(
            lambda identifier: annotations[identifier][key]
        )
    return result, annotated


def inspect(
    lithology, faults, alterations, area, rules, units, aliases, snapshot, config
):
    findings, segment = [], config["segment"]
    if "state" in faults:
        faults = faults.loc[faults.state != "exclude"].reset_index(drop=True)
    if segment in {"all", "lithology"}:
        findings.extend(
            lithology_findings(
                lithology, faults, area, rules, units, aliases, snapshot, config
            )
        )
    if segment in {"all", "structure"}:
        findings.extend(
            structure_findings(faults, lithology, rules, units, snapshot, config)
        )
    if segment in {"all", "alteration"}:
        extra, alterations = alteration_findings(
            alterations, lithology, rules, units, snapshot, config
        )
        findings.extend(extra)

    # Representative sampling downstream should start with visible, measured objects.
    def ordering(row):
        import json

        measured = json.loads(row["measurements_json"])
        return (
            row["rule_id"],
            -float(measured.get("area_m2", measured.get("length_m", 0))),
            row["issue_id"],
        )

    return sorted(findings, key=ordering), alterations


def issue_maps(context, findings, config, prefix=""):
    from multi_io import write_vector

    for element, filename, geometry_type in [
        ("lithology", "lithology_issues.gpkg", "MultiPolygon"),
        ("structure", "fault_issues.gpkg", "MultiLineString"),
        ("alteration", "alteration_issues.gpkg", "MultiPolygon"),
    ]:
        subset = [item for item in findings if item["element"] == element]
        frame = gpd.GeoDataFrame(
            [
                {
                    **{key: item[key] for key in ISSUE_FIELDS},
                    "geometry": item["_geometry"],
                }
                for item in subset
            ],
            columns=ISSUE_FIELDS + ["geometry"],
            geometry="geometry",
            crs=config["working_epsg"],
        )
        write_vector(
            context.output_path(prefix + filename),
            frame,
            config["working_epsg"],
            geometry_type,
        )
