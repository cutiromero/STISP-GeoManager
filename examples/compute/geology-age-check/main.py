"""Real-map formation-age consistency screening, without acceptance inputs."""

import geopandas as gpd

from age_logic import (
    contexts,
    inspect,
    map_checksum,
    parameters,
    read_map,
    report,
    rules,
    write_table,
    ISSUE_FIELDS,
)


def run(context):
    threshold, _, epsg = parameters(context)
    frame = read_map(context.input_path("features"), epsg)
    rule_map = rules(context.input_path("rules"))
    context_map = contexts(context.input_path("surveys"), frame, epsg)
    issues = inspect(frame, rule_map, context_map, threshold, epsg)
    write_table(context.output_path("issues.csv"), issues, ISSUE_FIELDS)
    if issues:
        geometry = [
            frame.loc[frame.feature_id == row["feature_id"]].geometry.iloc[0]
            for row in issues
        ]
        gpd.GeoDataFrame(issues, geometry=geometry, crs=frame.crs).to_file(
            context.output_path("issues.gpkg"),
            layer="issues",
            driver="GPKG",
            index=False,
        )
    metrics = {
        "total_features": len(frame),
        "issue_count": len(issues),
        "repairable": sum(row["status"] == "repairable" for row in issues),
        "needs_review": sum(row["status"] == "needs_review" for row in issues),
        "invalid_geometry": 0,
        "input_checksum": map_checksum(frame, epsg),
        "working_epsg": epsg,
        "reference_used": False,
        "evidence_kind": "dictionary_definition",
        "spatial_context_verified": True,
        "screen_area_m2": threshold,
        "editable_field": "geologic_age",
        "class_and_geometry_edit_allowed": False,
    }
    report(
        context,
        metrics,
        "按地区和地层标识发现时代属性一致性问题；构造与蚀变只作上下文。",
        "geologyCheck",
    )
