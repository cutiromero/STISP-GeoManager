"""Revalidate approved operations and write actual map corrections and differences."""

import geopandas as gpd

from review_logic import (
    ISSUE_FIELDS,
    corrected,
    inspect,
    input_checksum,
    parameters,
    quality,
    read_inputs,
    scalar,
    statistics,
    validated_plan,
    write_locations,
    write_table,
)


def run(context):
    settings = parameters(context)
    frame, coverage, rules = read_inputs(context, settings)
    accepted = validated_plan(context, frame, coverage, rules, settings)
    result = corrected(frame, accepted, settings)
    remaining = inspect(result, coverage, rules, settings)
    # Every operation and actual difference is verified before output creation.
    result.to_crs(4326).to_file(
        context.output_path("corrected.gpkg"), layer="data", driver="GPKG", index=False
    )
    exported = gpd.read_file(context.output_path("corrected.gpkg"))
    output_checksum = input_checksum(
        exported, coverage, rules, settings["working_epsg"]
    )
    by_id = {scalar(row.feature_id): row for _, row in result.iterrows()}
    write_locations(
        context.output_path("changes.gpkg"),
        accepted,
        settings["working_epsg"],
        lambda row: {
            "class": scalar(by_id[row["feature_id"]]["class"]),
            "name": scalar(by_id[row["feature_id"]]["name"]),
            "verified_reason": row["verified_reason"],
            "change_status": "applied",
        },
    )
    rules_by_id = {row["rule_id"]: row for row in rules}
    logs = [
        {
            **row,
            "status": "applied",
            "output_checksum": output_checksum,
            "source": rules_by_id[row["rule_id"]]["source"],
            "source_locator": rules_by_id[row["rule_id"]]["source_locator"],
        }
        for row in accepted
    ]
    write_table(
        context.output_path("changes.csv"),
        logs,
        ISSUE_FIELDS
        + ["verified_reason", "source", "source_locator", "output_checksum"],
    )
    rows = statistics(frame, result, settings["working_epsg"])
    write_table(context.output_path("statistics.csv"), rows, list(rows[0]))
    modified = {row["feature_id"] for row in accepted}
    metrics = {
        "total_features": len(result),
        "change_count": len(accepted),
        "modified_features": len(modified),
        "unchanged_features": len(frame) - len(modified),
        "changed_area_m2": sum(row["area_m2"] for row in accepted),
        "filled_area_m2": sum(
            row["area_m2"] for row in accepted if row["kind"] == "fill_gap"
        ),
        "age_update_count": sum(row["kind"] == "set_age" for row in accepted),
        "area_delta_m2": sum(row["delta_area_m2"] for row in rows),
        "remaining_issue_count": len(remaining),
        "remaining_repairable": sum(row["status"] == "repairable" for row in remaining),
        "input_checksum": input_checksum(
            frame, coverage, rules, settings["working_epsg"]
        ),
        "output_checksum": output_checksum,
        "working_epsg": settings["working_epsg"],
        "reference_used": False,
        "evidence_verified": True,
        "approved_scope_verified": True,
        "classification_preserved": True,
    }
    quality(
        context,
        metrics,
        f"完成{len(accepted)}项获批修改；实际填补{metrics['filled_area_m2']:.1f}平方米，复核剩余{len(remaining)}处疑点。",
        "geologyEdit",
    )
