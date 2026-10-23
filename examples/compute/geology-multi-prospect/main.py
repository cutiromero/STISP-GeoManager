"""Compare prospect evidence with identical masks, grid and knowledge parameters."""

from multi_io import (
    alterations,
    digest,
    frame_identity,
    inputs,
    load_alterations,
    report,
    settings,
    vector,
    write_table,
    write_vector,
)
from multi_prospect import grid, zones
from multi_relations import FIELDS, reconstruct


def run(context):
    config = settings(context)
    lithology, faults, area, rules, units, _, snapshot = inputs(context, config)
    final_alterations, snapshot = load_alterations(context, config, area, snapshot)
    before_lithology = vector(
        context.input_path("before_lithology"),
        config["working_epsg"],
        {"Polygon", "MultiPolygon"},
        "feature_id",
        {"name", "geo_sym"},
    )
    before_faults = vector(
        context.input_path("before_faults"),
        config["working_epsg"],
        {"LineString", "MultiLineString"},
        "line_id",
        allow_empty=True,
    )
    expected = reconstruct(faults, area, rules)
    try:
        intersections_path = context.input_path("intersections")
    except KeyError:
        intersections_path = None
    if intersections_path:
        intersections = vector(
            intersections_path,
            config["working_epsg"],
            {"Point", "MultiPoint"},
            "point_id",
            set(FIELDS),
            allow_empty=True,
        )
    elif expected.empty:
        intersections = expected
    else:
        raise ValueError("当前构造存在交汇关系但未提供对应成果，请先重建关系")
    if frame_identity(intersections[FIELDS + ["geometry"]]) != frame_identity(
        expected[FIELDS + ["geometry"]]
    ):
        raise ValueError("交汇成果与当前构造及规则不一致，请重新重建关系")
    before_intersections = reconstruct(before_faults, area, rules)
    original_alterations = alterations(context, config, area)
    transform, dimensions = grid(area, config)
    before, old_evidence = zones(
        before_lithology,
        before_faults,
        before_intersections,
        original_alterations,
        area,
        rules,
        units,
        config,
        transform,
        dimensions,
        "before",
    )
    after, new_evidence = zones(
        lithology,
        faults,
        intersections,
        final_alterations,
        area,
        rules,
        units,
        config,
        transform,
        dimensions,
        "after",
    )
    write_vector(
        context.output_path("before_zones.gpkg"),
        before,
        config["working_epsg"],
        "MultiPolygon",
    )
    write_vector(
        context.output_path("after_zones.gpkg"),
        after,
        config["working_epsg"],
        "MultiPolygon",
    )
    write_table(
        context.output_path("evidence.csv"),
        old_evidence + new_evidence,
        [
            "phase",
            "zone_id",
            "grade",
            "area_km2",
            "explanation",
            "evidence_json",
            "alteration",
            "faults",
            "intersections",
            "lithology",
            "conditions_json",
        ],
    )
    rows = [
        {
            "grade": label,
            "before_count": int((before.grade == label).sum()),
            "after_count": int((after.grade == label).sum()),
            "before_area_km2": float(
                before.loc[before.grade == label, "area_km2"].sum()
            ),
            "after_area_km2": float(after.loc[after.grade == label, "area_km2"].sum()),
        }
        for label in ("A", "B")
    ]
    write_table(
        context.output_path("statistics.csv"),
        rows,
        ["grade", "before_count", "after_count", "before_area_km2", "after_area_km2"],
    )
    report(
        context,
        {
            "before_zone_count": len(before),
            "after_zone_count": len(after),
            "before_area_km2": float(before.area_km2.sum()),
            "after_area_km2": float(after.area_km2.sum()),
            "snapshot_hash": digest(
                {
                    "after": snapshot,
                    "before_lithology": frame_identity(before_lithology),
                    "before_faults": frame_identity(before_faults),
                }
            ),
            "comparison_parameters_identical": True,
            "research_area_masked": True,
            "reference_used": False,
            "grid_resolution_m": config["grid_resolution_m"],
        },
        f"以同一规则和网格重算，修改前{len(before)}处、修改后{len(after)}处优先核查远景区；每区保留实际分级依据。",
    )
