"""Inspect actual map attributes and internal gaps under explicit knowledge rules."""

from review_logic import (
    ISSUE_FIELDS,
    inspect,
    input_checksum,
    parameters,
    quality,
    read_inputs,
    statistics,
    write_locations,
    write_table,
)


def run(context):
    settings = parameters(context)
    frame, coverage, rules = read_inputs(context, settings)
    issues = inspect(frame, coverage, rules, settings)
    write_table(context.output_path("issues.csv"), issues, ISSUE_FIELDS)
    write_locations(
        context.output_path("issues.gpkg"), issues, settings["working_epsg"]
    )
    rows = statistics(frame, frame, settings["working_epsg"])
    write_table(context.output_path("statistics.csv"), rows, list(rows[0]))
    metrics = {
        "total_features": len(frame),
        "class_count": len(rows),
        "issue_count": len(issues),
        "repairable": sum(row["status"] == "repairable" for row in issues),
        "needs_review": sum(row["status"] == "needs_review" for row in issues),
        "fill_gap_count": sum(row["kind"] == "fill_gap" for row in issues),
        "set_age_count": sum(row["kind"] == "set_age" for row in issues),
        "missing_area_m2": sum(
            row["area_m2"] for row in issues if row["kind"] == "fill_gap"
        ),
        "mapped_area_m2": float(
            frame.to_crs(settings["working_epsg"]).geometry.area.sum()
        ),
        "input_checksum": input_checksum(
            frame, coverage, rules, settings["working_epsg"]
        ),
        "working_epsg": settings["working_epsg"],
        "reference_used": False,
        "map_modified": False,
    }
    quality(
        context,
        metrics,
        f"检查{len(frame)}个图斑，发现{len(issues)}处疑点；修改建议需用户批准。",
        "geologyCheck",
    )
