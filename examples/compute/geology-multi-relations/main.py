"""Build actual and inferred intersections without changing a structure line."""

from shapely.ops import unary_union

from multi_io import (
    frame_identity,
    digest,
    report,
    rules,
    settings,
    vector,
    write_table,
    write_vector,
)
from multi_relations import reconstruct


def run(context):
    config = settings(context)
    faults = vector(
        context.input_path("faults"),
        config["working_epsg"],
        {"LineString", "MultiLineString"},
        "line_id",
        allow_empty=True,
    )
    coverage = vector(
        context.input_path("coverage"),
        config["working_epsg"],
        {"Polygon", "MultiPolygon"},
    )
    knowledge, _, _ = rules(context.input_path("rules"))
    area = (
        unary_union(coverage.loc[coverage.role != "exclusion", "geometry"])
        if "role" in coverage
        else unary_union(coverage.geometry)
    )
    if "role" in coverage:
        area = area.difference(
            unary_union(coverage.loc[coverage.role == "exclusion", "geometry"])
        )
    points = reconstruct(faults, area, knowledge)
    try:
        before_path = context.input_path("before_faults")
    except KeyError:
        before_path = None
    before = None
    if before_path:
        before_faults = vector(
            before_path,
            config["working_epsg"],
            {"LineString", "MultiLineString"},
            "line_id",
            allow_empty=True,
        )
        before = reconstruct(before_faults, area, knowledge)
        write_vector(
            context.output_path("before_intersections.gpkg"),
            before,
            config["working_epsg"],
            "Point",
        )
    write_vector(
        context.output_path("intersections.gpkg"),
        points,
        config["working_epsg"],
        "Point",
    )
    rows = [
        {"kind": "geometric", "count": int((~points.inferred.astype(bool)).sum())},
        {"kind": "inferred", "count": int(points.inferred.astype(bool).sum())},
    ]
    for row in rows:
        row["after_count"] = row["count"]
        row["before_count"] = (
            int((before.inferred.astype(bool) == (row["kind"] == "inferred")).sum())
            if before is not None
            else ""
        )
        row["delta_count"] = (
            row["count"] - row["before_count"] if before is not None else ""
        )
    write_table(
        context.output_path("statistics.csv"),
        rows,
        ["kind", "count", "before_count", "after_count", "delta_count"],
    )
    report(
        context,
        {
            "geometric_count": rows[0]["count"],
            "inferred_count": rows[1]["count"],
            "snapshot_hash": digest(
                {
                    "faults": frame_identity(faults),
                    "coverage": frame_identity(coverage),
                    "rules": knowledge,
                }
            ),
            "map_modified": False,
            "reference_used": False,
        },
        f"重建{rows[0]['count']}处几何相交和{rows[1]['count']}处推测交汇；两类分别展示，构造线保持原形。",
    )
