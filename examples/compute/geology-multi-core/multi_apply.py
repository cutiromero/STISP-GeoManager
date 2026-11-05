"""Execute only operations bound to an unchanged inspection and explicit approval."""

import json
import math

from shapely.ops import unary_union

from multi_io import CHANGE_FIELDS, ISSUE_FIELDS, scalar, table, dump
from multi_lithology_merge import approved_host, same_unit


def consolidate(frame, modifications):
    """Dissolve only same-unit components reached from approved changes."""
    changed = {
        item["feature_id"]
        for item in modifications
        if item["element"] == "lithology"
        and item["action"] in {"set_code", "reclassify", "merge"}
    }
    visited = set()
    for seed in list(frame.index):
        if seed in visited or str(frame.at[seed, "feature_id"]) not in changed:
            continue
        component, pending = set(), [seed]
        while pending:
            index = pending.pop()
            if index in component:
                continue
            component.add(index)
            row = frame.loc[index]
            nearby = frame.iloc[
                frame.sindex.query(row.geometry, predicate="intersects")
            ]
            for candidate, other in nearby.iterrows():
                if (
                    candidate not in component
                    and same_unit(row, other)
                    and (
                        row.geometry.boundary.intersection(
                            other.geometry.boundary
                        ).length
                        > 0
                    )
                ):
                    pending.append(candidate)
        visited.update(component)
        if len(component) < 2:
            for item in modifications:
                if item["element"] == "lithology" and item["feature_id"] == str(
                    frame.at[seed, "feature_id"]
                ):
                    item["host_feature_id"] = ""
            continue
        preferred = {
            item["host_feature_id"]
            for item in modifications
            if item["element"] == "lithology"
            and item["feature_id"]
            in {str(frame.at[index, "feature_id"]) for index in component}
        }
        host = min(
            component,
            key=lambda index: (
                str(frame.at[index, "feature_id"]) in changed,
                str(frame.at[index, "feature_id"]) not in preferred,
                -frame.at[index, "geometry"].area,
                str(frame.at[index, "feature_id"]),
            ),
        )
        geometries = frame.loc[sorted(component)].geometry
        merged = unary_union(geometries)
        identities = [str(frame.at[index, "feature_id"]) for index in component]
        removed = max(
            0, (sum(geometry.length for geometry in geometries) - merged.length) / 2
        )
        records = [
            item
            for item in modifications
            if item["element"] == "lithology" and item["feature_id"] in identities
        ]
        for position, item in enumerate(records):
            item.update(
                host_feature_id=str(frame.at[host, "feature_id"]),
                absorbed_ids=dump(
                    [
                        identity
                        for identity in identities
                        if identity != str(frame.at[host, "feature_id"])
                    ]
                ),
                involved_area_m2=float(merged.area),
                removed_internal_boundary_m=float(removed) if position == 0 else 0.0,
            )
        frame.at[host, "geometry"] = merged
        frame = frame.drop(index=sorted(component - {host}))
    return frame


def approved(context, findings, snapshot):
    inspected = table(context.input_path("issues"))
    changes = table(context.input_path("approved_changes"))
    expected = {row["issue_id"]: row for row in findings}
    supplied = {row["issue_id"]: row for row in inspected}
    if len(supplied) != len(inspected) or set(supplied) != set(expected):
        raise ValueError("检查清单不完整、重复或与当前资料不符，请重新检查")
    # Catalog ingestion strips surrounding whitespace from display text. The
    # immutable snapshot and every executable/measurement field stay exact.
    display_fields = {"conditions", "exceptions", "reason"}

    def comparable(row, key):
        value = str(row.get(key, ""))
        return value.strip() if key in display_fields else value

    for identifier, row in supplied.items():
        if any(
            comparable(row, key) != comparable(expected[identifier], key)
            for key in ISSUE_FIELDS
        ):
            raise ValueError("检查结论或范围已经改变，请重新生成并批准方案")
    seen, objects, accepted = set(), set(), []
    for change in changes:
        if not set(CHANGE_FIELDS) <= set(change):
            raise ValueError("批准记录缺少必要字段")
        row = expected.get(change["issue_id"])
        if (
            row is None
            or change["issue_id"] in seen
            or (row["element"], row["feature_id"]) in objects
        ):
            raise ValueError("批准对象未知或同一对象存在多个相冲突操作")
        seen.add(change["issue_id"])
        objects.add((row["element"], row["feature_id"]))
        for key in ("feature_id", "rule_id", "rule_version", "snapshot_hash"):
            if change[key] != str(row[key]) or change["snapshot_hash"] != snapshot:
                raise ValueError("批准记录与当前输入、知识版本或修改范围不一致：" + key)
        action = change["action"]
        if row["status"] in {"review", "exception"} and action not in {
            "keep",
            "review",
        }:
            if (
                (
                    action != row.get("candidate_action")
                    and not (
                        row["feature_id"].startswith("AG-") and action == "downweight"
                    )
                )
                or change["target_code"] != row.get("candidate_target_code", "")
                or not change["reason"].startswith("用户裁定（规则为待裁定/例外）")
            ):
                raise ValueError("待裁定/例外仅接受用户明确批准的冻结候选动作与目标")
        if action not in json.loads(row["allowed_actions_json"]):
            raise ValueError("动作不在本项允许范围内")
        if not change["reason"].strip():
            raise ValueError("批准理由不可为空")
        if action in {"reclassify", "merge"} and not row["target_code"]:
            raise ValueError("重分类或融合缺少实测相邻目标")
        if (
            action in {"set_code", "reclassify", "merge"}
            and change["target_code"] != row["target_code"]
            or action not in {"set_code", "reclassify", "merge"}
            and change["target_code"]
        ):
            raise ValueError("类别操作须匹配获批目标，其他操作不接受类别修改")
        weight = float(
            change["weight"]
            or (0.5 if action == "downweight" else 0 if action == "exclude" else 1)
        )
        if (
            not math.isfinite(weight)
            or not 0 <= weight <= 1
            or action == "downweight"
            and not 0 < weight < 1
            or action == "exclude"
            and weight != 0
            or action in {"keep", "review", "set_code", "reclassify", "merge"}
            and weight != 1
        ):
            raise ValueError("保留/待裁定权重为1，降权须在0与1之间，剔除须为0")
        accepted.append({**row, **change, "weight": weight})
    return accepted


def apply(lithology, faults, alterations, operations):
    results = {
        "lithology": lithology.copy(),
        "structure": faults.copy(),
        "alteration": alterations.copy(),
    }
    for element in ("structure", "alteration"):
        for key, default in (("state", "keep"), ("weight", 1.0)):
            if key not in results[element]:
                results[element][key] = default
    modifications = []
    assignments = {}
    for operation in operations:
        if operation["element"] != "lithology" or operation["action"] not in {
            "reclassify",
            "merge",
        }:
            continue
        original = lithology.loc[lithology.feature_id == operation["feature_id"]].iloc[
            0
        ]
        hosts = lithology.loc[
            (lithology.geo_sym == operation["target_code"])
            & (lithology.feature_id != operation["feature_id"])
            & lithology.geometry.intersects(original.geometry)
        ]
        hosts = hosts.loc[
            hosts.geometry.map(
                lambda candidate: (
                    candidate.boundary.intersection(original.geometry.boundary).length
                    > 0
                )
            )
        ]
        if hosts.empty:
            raise ValueError("当前地图中没有获批的相邻目标单元")
        host = (
            approved_host(lithology, operation, original.geometry)
            if operation["rule_id"] == "L-05"
            else min(
                hosts.index,
                key=lambda index: (
                    -hosts.at[index, "geometry"]
                    .boundary.intersection(original.geometry.boundary)
                    .length,
                    str(hosts.at[index, "feature_id"]),
                ),
            )
        )
        assignments[operation["feature_id"]] = lithology.loc[host]
    for operation in operations:
        frame = results[operation["element"]]
        identity = "line_id" if operation["element"] == "structure" else "feature_id"
        matches = frame.index[frame[identity] == operation["feature_id"]]
        if len(matches) != 1:
            raise ValueError("获批对象不存在或已被其他操作改变")
        index, action = matches[0], operation["action"]
        geometry = frame.at[index, "geometry"]
        old_code = scalar(frame.at[index, "geo_sym"]) if "geo_sym" in frame else ""
        actual_changed = action not in {"keep", "review"}
        host_id = ""
        involved_geometry = geometry
        removed_boundary = 0.0
        if action == "set_code":
            if operation["element"] != "lithology":
                raise ValueError("代号更新只用于岩性资料")
            frame.at[index, "geo_sym"] = operation["target_code"]
            if "code" in frame:
                frame.at[index, "code"] = operation["target_code"]
        absorbed = []
        if action in {"set_code", "reclassify", "merge"}:
            if operation["feature_id"] in assignments:
                host = assignments[operation["feature_id"]]
                host_id = str(host.feature_id)
                for field in (
                    "name",
                    "geo_sym",
                    "class",
                    "code",
                    "path",
                    "geo_unit",
                    "geo_tex",
                ):
                    if field in frame:
                        frame.at[index, field] = host[field]
        elif operation["element"] in {"structure", "alteration"}:
            actual_changed = action not in {"keep", "review"} and (
                frame.at[index, "state"] != action
                or float(frame.at[index, "weight"]) != operation["weight"]
            )
            frame.at[index, "state"] = action
            frame.at[index, "weight"] = operation["weight"]
        elif action not in {"keep", "review"}:
            raise ValueError("此资料不支持该动作")
        if (
            action == "set_code"
            and old_code == operation["target_code"]
            and not host_id
        ):
            actual_changed = False
        modifications.append(
            {
                **operation,
                "old_code": old_code,
                "new_code": operation["target_code"]
                if action in {"set_code", "reclassify", "merge"}
                else old_code,
                "host_feature_id": host_id,
                "_geometry": geometry,
                "absorbed_ids": dump(absorbed),
                "actual_changed": actual_changed,
                "area_m2": float(geometry.area),
                "involved_area_m2": float(involved_geometry.area),
                "geometry_change_area_m2": 0.0,
                "class_change_area_m2": float(geometry.area)
                if action in {"reclassify", "merge"}
                and old_code != operation["target_code"]
                else 0.0,
                "attribute_change_area_m2": float(geometry.area)
                if action == "set_code"
                else 0.0,
                "removed_internal_boundary_m": float(removed_boundary),
                "length_m": float(geometry.length)
                if operation["element"] == "structure"
                else 0.0,
            }
        )
    corrected = consolidate(results["lithology"], modifications)
    results["lithology"] = corrected
    if not corrected.geometry.is_valid.all():
        raise ValueError("修改超出获批覆盖范围或造成无效几何")
    original_coverage = unary_union(lithology.geometry)
    corrected_coverage = unary_union(corrected.geometry)
    if (
        original_coverage.symmetric_difference(corrected_coverage).area > 0.01
        or corrected.geometry.area.sum() - corrected_coverage.area > 0.01
    ):
        raise ValueError("修正后覆盖范围变化或存在重叠，不能交付最终岩性图")
    touched = {
        item["feature_id"] for item in modifications if item["element"] == "lithology"
    } | {item["host_feature_id"] for item in modifications}
    originals = lithology.set_index("feature_id", drop=False)
    for _, row in corrected.iterrows():
        if row.feature_id not in touched:
            old = originals.loc[row.feature_id]
            if not row.geometry.equals_exact(old.geometry, 0) or any(
                scalar(row[key]) != scalar(old[key])
                for key in lithology.columns
                if key != "geometry"
            ):
                raise ValueError("未获批图斑被修改")
    return (
        corrected.reset_index(drop=True),
        results["structure"].reset_index(drop=True),
        results["alteration"].reset_index(drop=True),
        modifications,
    )


def statistics(before, after):
    rows = []
    for code in sorted(set(before.geo_sym) | set(after.geo_sym)):
        old, new = before.loc[before.geo_sym == code], after.loc[after.geo_sym == code]
        a, b = float(old.geometry.area.sum()), float(new.geometry.area.sum())
        rows.append(
            {
                "geo_sym": code,
                "before_count": len(old),
                "after_count": len(new),
                "before_area_m2": a,
                "after_area_m2": b,
                "delta_area_m2": b - a,
            }
        )
    return rows


def final_layer(frame, element):
    processing = {
        "state",
        "weight",
        "status",
        "rule",
        "rule_id",
        "rule_version",
        "modified",
        "action",
        "fill_color",
        "issue_id",
        "reason",
        "snapshot_hash",
        "knowledge_id",
        "knowledge_revision",
        "measurements_json",
        "conditions",
        "exceptions",
        "suggested_action",
        "target_code",
        "allowed_actions_json",
        "geometry_json",
        "old_code",
        "new_code",
        "host_feature_id",
        "absorbed_ids",
        "actual_changed",
        "is_modified",
    }
    fields = (
        {"feature_id", "alt"}
        if element == "alteration"
        else {
            key
            for key in frame.columns
            if str(key).lower() not in processing
            and not str(key)
            .lower()
            .startswith(
                ("rule_", "change_", "modified_", "processing_", "knowledge_", "_")
            )
        }
    )
    active = (
        frame.loc[frame.state != "exclude"]
        if element != "lithology" and "state" in frame
        else frame
    )
    return active[
        [key for key in active.columns if key in fields or key == "geometry"]
    ].copy()


def modification_maps(context, modifications, config):
    import geopandas as gpd

    from multi_io import ISSUE_FIELDS, write_vector

    fields = list(
        dict.fromkeys(
            ISSUE_FIELDS
            + [
                "action",
                "old_code",
                "new_code",
                "host_feature_id",
                "reason",
                "absorbed_ids",
            ]
        )
    )
    for element, filename, geometry_type in [
        ("lithology", "lithology_issues.gpkg", "MultiPolygon"),
        ("structure", "fault_issues.gpkg", "MultiLineString"),
        ("alteration", "alteration_issues.gpkg", "MultiPolygon"),
    ]:
        rows = [
            {
                **{key: row.get(key, "") for key in fields},
                "geometry": row["_geometry"],
            }
            for row in modifications
            if row["element"] == element
            and row["actual_changed"]
            and not row["feature_id"].startswith("AG-")
        ]
        frame = gpd.GeoDataFrame(
            rows,
            columns=fields + ["geometry"],
            geometry="geometry",
            crs=config["working_epsg"],
        )
        write_vector(
            context.output_path("changes_" + filename),
            frame,
            config["working_epsg"],
            geometry_type,
        )
