"""Execute only operations bound to an unchanged inspection and explicit approval."""

import json
import math

from shapely.ops import unary_union

from multi_io import CHANGE_FIELDS, ISSUE_FIELDS, scalar, table


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
        if action == "set_code":
            if operation["element"] != "lithology":
                raise ValueError("代号更新只用于岩性资料")
            frame.at[index, "geo_sym"] = operation["target_code"]
            if "code" in frame:
                frame.at[index, "code"] = operation["target_code"]
        elif action in {"reclassify", "merge"}:
            hosts = frame.loc[
                (frame.geo_sym == operation["target_code"])
                & (frame.feature_id != operation["feature_id"])
                & frame.geometry.intersects(geometry.buffer(0.5))
            ]
            if hosts.empty:
                raise ValueError("当前地图中没有获批的相邻目标单元")
            host_index = max(
                hosts.index,
                key=lambda key: (
                    frame.at[key, "geometry"]
                    .boundary.intersection(geometry.buffer(0.5))
                    .length
                ),
            )
            host_id = str(frame.at[host_index, "feature_id"])
            if action == "merge":
                frame.at[host_index, "geometry"] = frame.at[
                    host_index, "geometry"
                ].union(geometry)
                results[operation["element"]] = frame.drop(index=index)
            else:
                for key in (
                    "name",
                    "geo_sym",
                    "geo_tex",
                    "geo_unit",
                    "class",
                    "code",
                    "path",
                    "fill_color",
                ):
                    if key in frame:
                        frame.at[index, key] = frame.at[host_index, key]
        elif operation["element"] in {"structure", "alteration"}:
            frame.at[index, "state"] = action
            frame.at[index, "weight"] = operation["weight"]
        elif action not in {"keep", "review"}:
            raise ValueError("此资料不支持该动作")
        modifications.append(
            {
                **operation,
                "old_code": old_code,
                "new_code": operation["target_code"]
                if action in {"set_code", "reclassify", "merge"}
                else old_code,
                "host_feature_id": host_id,
                "actual_changed": actual_changed,
                "area_m2": float(geometry.area),
                "length_m": float(geometry.length)
                if operation["element"] == "structure"
                else 0.0,
            }
        )
    corrected = results["lithology"]
    if (
        not corrected.geometry.is_valid.all()
        or abs(
            unary_union(lithology.geometry)
            .symmetric_difference(unary_union(corrected.geometry))
            .area
        )
        > 0.01
    ):
        raise ValueError("修改超出获批覆盖范围或造成无效几何")
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
