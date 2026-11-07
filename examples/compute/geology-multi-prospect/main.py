"""Delineate unified prospect targets exclusively from corrected observations."""

import math

from multi_io import (
    frame_identity,
    inputs,
    report,
    settings,
    vector,
    write_table,
    write_vector,
)
from multi_prospect import grid, zones
from multi_relations import FIELDS, reconstruct
from multi_raster import RasterAlterations
from multi_windows import create


def run(context):
    config = settings(context)
    for key, default, low, high in (
        ("max_zone_count", 5, 1, 20),
        ("max_zone_area_m2", 3000000, 1, 100000000),
    ):
        value = context.parameters.get(key, default)
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not low <= value <= high
            or (key == "max_zone_count" and int(value) != value)
        ):
            raise ValueError("远景目标数量或面积上限无效")
        config[key] = int(value) if key == "max_zone_count" else value
    if config["max_zone_area_m2"] < config["min_zone_area_m2"]:
        raise ValueError("远景区最大面积不能小于最小面积")
    lithology, faults, area, rules, units, _, snapshot = inputs(context, config)
    alterations = RasterAlterations(context, config, area)
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
    transform, dimensions = grid(area, config)
    targets, evidence, diagnostics, support = zones(
        lithology,
        faults,
        intersections,
        alterations,
        area,
        rules,
        units,
        config,
        transform,
        dimensions,
    )
    write_vector(
        context.output_path("after_zones.gpkg"),
        targets[
            [
                "zone_id",
                "priority_rank",
                "area_km2",
                "explanation",
                "evidence_json",
                "geometry",
            ]
        ],
        config["working_epsg"],
        "MultiPolygon",
    )
    write_table(
        context.output_path("evidence.csv"),
        evidence,
        [
            "schema_version",
            "phase",
            "zone_id",
            "priority_rank",
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
    with create(
        context.output_path("prospect_support.tif"),
        {
            "height": dimensions[0],
            "width": dimensions[1],
            "transform": transform,
            "crs": config["working_epsg"],
        },
        "float32",
    ) as target:
        target.nodata = -9999
        target.write(support, 1)
    area_km2 = float(targets.area_km2.sum())
    write_table(
        context.output_path("statistics.csv"),
        [
            {
                "schema_version": 2,
                "phase": "after",
                "zone_count": len(targets),
                "area_km2": area_km2,
            }
        ],
        ["schema_version", "phase", "zone_count", "area_km2"],
    )
    reason = (
        "未达到邻域蚀变组合门槛"
        if not diagnostics["alteration_cells"]
        else "蚀变组合、有效构造及已知基岩岩性未形成空间交集"
        if not diagnostics["candidate_cells"]
        else "候选连通区均未满足圈区面积上下限"
        if targets.empty
        else ""
    )
    report(
        context,
        {
            **diagnostics,
            "after_zone_count": len(targets),
            "after_area_km2": area_km2,
            "snapshot_hash": snapshot,
            "research_area_masked": True,
            "reference_used": False,
            "grid_resolution_m": config["grid_resolution_m"],
            "empty_reason": reason,
        },
        f"仅按修正后资料圈定{len(targets)}处优先核查远景区，共{area_km2:.3f}平方公里。"
        + (
            reason + "。"
            if reason
            else "每区保留邻域蚀变、构造与岩性的实际依据及相对置信度热力图。"
        ),
    )
