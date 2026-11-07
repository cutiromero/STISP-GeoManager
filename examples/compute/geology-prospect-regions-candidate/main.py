"""Candidate-only corrected-data regional delineation; never modifies inputs."""

from pathlib import Path
import math

from multi_io import inputs, dump, settings, vector, write_table, write_vector
from multi_relations import FIELDS, reconstruct
from multi_windows import create
from region_fields import PROFILES, base_fields, profile_fields
from region_zones import delineate
from region_boundaries import apply_boundaries

# ==================== CONFIGURATION ====================
DEFAULTS = {
    "profile": "focused",
    "working_epsg": 32646,
    "segment": "all",
    "grid_resolution_m": 50,
    "min_zone_area_km2": 1.0,
    "min_core_area_km2": 0.05,
    "core_score_min": 0.62,
    "region_seed_spacing_m": 2500,
    "max_geodesic_reach_m": 3500,
    "alteration_density_scale": 0.08,
    "peripheral_min_weighted_types": 1.5,
    "peripheral_min_density": 0.002,
    "boundary_smooth_m": 100,
    "between_zone_gap_m": 50,
}
LIMITS = {
    "grid_resolution_m": (25, 200),
    "min_zone_area_km2": (0.01, 30),
    "min_core_area_km2": (0.001, 5),
    "core_score_min": (0, 1),
    "region_seed_spacing_m": (250, 10000),
    "max_geodesic_reach_m": (500, 10000),
    "alteration_density_scale": (0.001, 1),
    "peripheral_min_weighted_types": (1, 5),
    "peripheral_min_density": (0, 1),
    "boundary_smooth_m": (0, 250),
    "between_zone_gap_m": (0, 200),
}
# =======================================================


def configuration(context):
    if set(context.parameters) - set(DEFAULTS):
        raise ValueError("候选方案包含未声明参数")
    config = {**DEFAULTS, **context.parameters}
    if config["profile"] not in PROFILES:
        raise ValueError("候选圈区尺度无效")
    for key, (low, high) in LIMITS.items():
        value = config[key]
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            raise ValueError("候选参数超出有效范围：" + key)
    config["min_zone_area_m2"] = config["min_zone_area_km2"] * 1e6
    settings(type("SettingsContext", (), {"parameters": config})())
    if config["min_zone_area_km2"] > PROFILES[config["profile"]]["max_zone_area_km2"]:
        raise ValueError("最小圈区面积大于当前尺度上限")
    return config


def current_intersections(context, faults, area, rules, epsg):
    try:
        path = context.input_path("intersections")
    except KeyError:
        path = None
    if path is None:
        return reconstruct(faults, area, rules)
    points = vector(
        path, epsg, {"Point", "MultiPoint"}, "point_id", set(FIELDS), allow_empty=True
    )
    active = {
        str(row.line_id): row
        for _, row in faults.iterrows()
        if row.get("state", "keep") != "exclude" and float(row.get("weight", 1)) > 0
    }
    for _, point in points.iterrows():
        ids = [str(point.f1), str(point.f2)]
        if ids[0] == ids[1] or not set(ids) <= set(active):
            raise ValueError("交汇点不属于当前有效构造")
        tolerance = max(0, float(point.gap_m)) + 0.05
        if any(
            point.geometry.distance(active[key].geometry) > tolerance for key in ids
        ):
            raise ValueError("交汇点与当前构造位置不一致")
        if not area.buffer(0.05).covers(point.geometry):
            raise ValueError("交汇点超出研究区")
    return points


def run(context):
    config = configuration(context)
    lithology, faults, area, rules, units, _, snapshot = inputs(context, config)
    if not {"P-01", "P-02", "P-03"} <= set(rules):
        raise ValueError("候选圈区需要当前构造、矿物组合与岩性依据")
    points = current_intersections(context, faults, area, rules, config["working_epsg"])
    base = base_fields(context, lithology, faults, points, area, rules, units, config)
    profile = PROFILES[config["profile"]]
    fields = profile_fields(base, profile, config)
    targets, rows, heat, diagnostics, core = delineate(
        base, fields, profile, area, lithology, rules, units, config
    )
    if not targets.empty and (
        config["boundary_smooth_m"] or config["between_zone_gap_m"]
    ):
        targets, rows, heat, boundary_report = apply_boundaries(
            targets,
            rows,
            base,
            fields,
            core,
            area,
            lithology,
            units,
            {**config, "growth_threshold": profile["growth_threshold"]},
        )
        diagnostics.update(boundary_report)
        diagnostics.update(
            area_km2=float(targets.area_km2.sum()),
            area_fraction=float(targets.area_km2.sum() * 1e6 / area.area),
        )
    write_vector(
        context.output_path("after_zones.gpkg"),
        targets,
        config["working_epsg"],
        "MultiPolygon",
    )
    write_table(
        context.output_path("evidence.csv"),
        rows,
        list(rows[0]) if rows else ["zone_id", "area_km2"],
    )
    for name, data in [
        ("prospect_support", heat),
        ("strong_core", (core & (heat != -9999)).astype("uint8")),
    ]:
        with create(
            context.output_path(name + ".tif"),
            {
                "height": base["dimensions"][0],
                "width": base["dimensions"][1],
                "transform": base["transform"],
                "crs": config["working_epsg"],
            },
            str(data.dtype),
        ) as dst:
            if name == "prospect_support":
                dst.nodata = -9999
            dst.write(data, 1)
    write_table(
        context.output_path("statistics.csv"),
        [
            {
                "method": "core_context_regions_candidate_v1",
                "phase": "after",
                "profile": config["profile"],
                "zone_count": len(targets),
                "area_km2": float(targets.area_km2.sum()),
            }
        ],
        ["method", "phase", "profile", "zone_count", "area_km2"],
    )
    report = {
        "version": 1,
        "status": "needs_review",
        "summary": f"候选{profile['label']}尺度圈定{len(targets)}处，共{targets.area_km2.sum():.2f}平方公里，等待方案选择。",
        "metrics": {
            **diagnostics,
            "snapshot_hash": snapshot,
            "grid_resolution_m": config["grid_resolution_m"],
        },
        "knowledgeFacts": {
            "candidateRegions": {
                "candidate": True,
                "profile": profile,
                "parameters": config,
                "weights": {"alteration": 0.45, "structure": 0.40, "lithology": 0.15},
                "confidence": "未作矿点标定的综合支持度，不表示有矿概率",
            }
        },
    }
    Path(context.output_path("quality.json")).write_text(dump(report), encoding="utf-8")
