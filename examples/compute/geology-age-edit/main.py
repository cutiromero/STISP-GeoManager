"""Apply a bounded dictionary-backed age plan, preserving all map geometry."""

from age_logic import (
    CHANGE_FIELDS,
    contexts,
    inspect,
    map_checksum,
    parameters,
    read_map,
    report,
    rules,
    table,
    write_table,
    working_frame,
)


def run(context):
    threshold, maximum, epsg = parameters(context)
    original = read_map(context.input_path("features"), epsg)
    rule_map = rules(context.input_path("rules"))
    context_map = contexts(context.input_path("surveys"), original, epsg)
    submitted = table(context.input_path("changes"), set(CHANGE_FIELDS))
    if len(submitted) > maximum:
        raise ValueError("修改对象超过本轮允许上限")
    checksum = map_checksum(original, epsg)
    eligible = {
        (row["feature_id"], row["field"]): row
        for row in inspect(original, rule_map, context_map, threshold, epsg)
        if row["status"] == "repairable"
    }
    seen, accepted = set(), []
    for change in submitted:
        identity = (change["feature_id"], change["field"])
        verified = eligible.get(identity)
        if identity in seen or verified is None:
            raise ValueError("修改对象重复、字段不允许或不满足当前证据条件")
        seen.add(identity)
        if change["input_checksum"] != checksum:
            raise ValueError("地图内容校验和已变化，须重新检查")
        for key in ("old_value", "new_value", "rule_id", "evidence_id"):
            if change[key] != verified[key]:
                raise ValueError("修改原值、新值、规则或证据不匹配实际检查")
        if not change["reason"].strip():
            raise ValueError("模型修改理由不可为空")
        accepted.append({**verified, "model_reason": change["reason"]})
    # Validate every row before changing data or creating any output file.
    result = original.copy()
    for row in accepted:
        index = result.index[result.feature_id == row["feature_id"]][0]
        result.at[index, "geologic_age"] = row["new_value"]
    by_feature = {row["feature_id"]: row for row in accepted}
    result["check_status"] = [
        "corrected" if str(identity) in by_feature else "unchanged"
        for identity in result.feature_id
    ]
    for target, source in (
        ("change_reason", "reason"),
        ("change_evidence", "evidence_id"),
        ("change_rule", "rule_id"),
        ("change_old", "old_value"),
        ("change_new", "new_value"),
    ):
        result[target] = [
            by_feature[str(identity)][source] if str(identity) in by_feature else ""
            for identity in result.feature_id
        ]
    output_checksum = map_checksum(result, epsg)
    log = [
        {
            **{key: row[key] for key in CHANGE_FIELDS},
            "model_reason": row["model_reason"],
            "status": "applied",
            "verified_source": rule_map[row["rule_id"]]["source"],
            "source_locator": rule_map[row["rule_id"]]["source_locator"],
            "source_url": rule_map[row["rule_id"]]["source_url"],
            "output_checksum": output_checksum,
        }
        for row in accepted
    ]
    result.to_file(
        context.output_path("corrected.gpkg"), layer="data", driver="GPKG", index=False
    )
    write_table(
        context.output_path("changes.csv"),
        log,
        CHANGE_FIELDS
        + [
            "model_reason",
            "status",
            "verified_source",
            "source_locator",
            "source_url",
            "output_checksum",
        ],
    )
    actual_checksum = map_checksum(result, epsg)
    metrics = {
        "total_features": len(original),
        "change_count": len(accepted),
        "modified_features": len(accepted),
        "unchanged_features": len(original) - len(accepted),
        "invalid_geometry": 0,
        "input_checksum": checksum,
        "output_checksum": actual_checksum,
        "reference_used": False,
        "evidence_verified": True,
        "geometry_preserved": True,
        "classification_preserved": True,
        "area_delta_m2": float(
            working_frame(result, epsg).geometry.area.sum()
            - working_frame(original, epsg).geometry.area.sum()
        ),
        "editable_field": "geologic_age",
        "max_changes": maximum,
        "working_epsg": epsg,
        "remaining_repairable": sum(
            row["status"] == "repairable"
            for row in inspect(result, rule_map, context_map, threshold, epsg)
        ),
    }
    report(
        context,
        metrics,
        f"依据辞书适用条件完成{len(accepted)}个时代属性修改；岩性分类和边界保持，下一步重新检查。",
        "geologyEdit",
    )
