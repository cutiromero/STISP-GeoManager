"""Reinspect current evidence, validate approvals and produce new versioned layers."""

from multi_apply import apply, approved, final_layer, modification_maps, statistics
from multi_checks import inspect
from multi_io import (
    CHANGE_FIELDS,
    inputs,
    load_alterations,
    report,
    settings,
    write_table,
    write_vector,
)


def run(context):
    config = settings(context)
    lithology, faults, area, rules, units, aliases, snapshot = inputs(context, config)
    alterations, snapshot = load_alterations(context, config, area, snapshot)
    findings, alterations = inspect(
        lithology, faults, alterations, area, rules, units, aliases, snapshot, config
    )
    operations = approved(context, findings, snapshot)
    corrected, final_faults, final_alterations, actual = apply(
        lithology, faults, alterations, operations
    )
    # Approval validation completes before any output is written.
    for filename, frame, geometry_type in [
        ("lithology.gpkg", final_layer(corrected, "lithology"), "MultiPolygon"),
        ("faults.gpkg", final_faults, "MultiLineString"),
        ("alterations.gpkg", final_alterations, "MultiPolygon"),
        (
            "final_faults.gpkg",
            final_layer(final_faults, "structure"),
            "MultiLineString",
        ),
        (
            "final_alterations.gpkg",
            final_layer(final_alterations, "alteration"),
            "MultiPolygon",
        ),
    ]:
        write_vector(
            context.output_path(filename), frame, config["working_epsg"], geometry_type
        )
    rows = statistics(lithology, corrected)
    write_table(
        context.output_path("statistics.csv"),
        rows,
        [
            "geo_sym",
            "before_count",
            "after_count",
            "before_area_m2",
            "after_area_m2",
            "delta_area_m2",
        ],
    )
    write_table(
        context.output_path("changes.csv"),
        actual,
        CHANGE_FIELDS
        + [
            "element",
            "knowledge_id",
            "knowledge_revision",
            "old_code",
            "new_code",
            "host_feature_id",
            "absorbed_ids",
            "actual_changed",
            "area_m2",
            "involved_area_m2",
            "geometry_change_area_m2",
            "class_change_area_m2",
            "attribute_change_area_m2",
            "removed_internal_boundary_m",
            "length_m",
            "measurements_json",
        ],
    )
    modification_maps(context, actual, config)
    metrics = {
        "approved_count": len(actual),
        "actual_change_count": sum(row["actual_changed"] for row in actual),
        "retained_count": sum(row["action"] in {"keep", "review"} for row in actual),
        "downweighted_count": sum(row["action"] == "downweight" for row in actual),
        "excluded_count": sum(row["action"] == "exclude" for row in actual),
        "lithology_count": len(corrected),
        "fault_count": len(final_faults),
        "active_fault_count": int((final_faults.state != "exclude").sum()),
        "alteration_count": len(final_alterations),
        "active_alteration_count": int((final_alterations.state != "exclude").sum()),
        "snapshot_hash": snapshot,
        "reference_used": False,
        "approved_scope_verified": True,
        "working_epsg": config["working_epsg"],
    }
    report(
        context,
        metrics,
        f"核验后执行{metrics['actual_change_count']}项获批变更；保留或待裁定{metrics['retained_count']}项。降权与剔除状态分别保存。",
    )
