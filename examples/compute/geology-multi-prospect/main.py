"""Delineate smooth connected prospect regions from corrected observations."""

import math

from multi_io import inputs, settings, vector, write_table, write_vector, report
from multi_relations import FIELDS, reconstruct
from multi_windows import create
from prospect_fields import PROFILES, base_fields, profile_fields
from prospect_zones import delineate
from prospect_evidence import platform_evidence
from multi_stack import raster_inputs

# ==================== CONFIGURATION ====================
DEFAULTS = {
    "profile": "focused",
    "working_epsg": 32646,
    "segment": "all",
    "prospect_grid_resolution_m": 50,
    "min_zone_area_km2": 1.0,
    "min_core_area_km2": 0.05,
    "core_score_min": 0.62,
    "alteration_density_scale": 0.08,
    "peripheral_min_weighted_types": 1.5,
    "peripheral_min_density": 0.002,
    "support_smooth_m": 100,
}
LIMITS = {
    "prospect_grid_resolution_m": (25, 200),
    "min_zone_area_km2": (0.01, 30),
    "min_core_area_km2": (0.001, 5),
    "core_score_min": (0, 1),
    "alteration_density_scale": (0.001, 1),
    "peripheral_min_weighted_types": (1, 5),
    "peripheral_min_density": (0, 1),
    "support_smooth_m": (25, 250),
}
# =======================================================


def configuration(context):
    if set(context.parameters) - set(DEFAULTS):
        raise ValueError("远景区分析包含未声明参数")
    config = {**DEFAULTS, **context.parameters}
    if config["profile"] not in PROFILES:
        raise ValueError("远景区分析尺度无效")
    for key, (low, high) in LIMITS.items():
        value = config[key]
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            raise ValueError("远景区参数超出有效范围：" + key)
    config["grid_resolution_m"] = config.pop("prospect_grid_resolution_m")
    config["min_zone_area_m2"] = config["min_zone_area_km2"] * 1e6
    settings(type("SettingsContext", (), {"parameters": config})())
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


@raster_inputs("prospect")
def run(context):
    config = configuration(context)
    lithology, faults, area, rules, units, _, snapshot = inputs(context, config)
    if not {"P-01", "P-02", "P-03"} <= set(rules):
        raise ValueError("远景区圈定需要当前构造、矿物组合与岩性依据")
    if (
        rules["P-02"]["params"].get("evidence_method")
        != "weighted_neighborhood_presence_v2"
    ):
        raise ValueError("找矿分析需要显式绑定邻域矿物组合规则")
    points = current_intersections(context, faults, area, rules, config["working_epsg"])
    base = base_fields(context, lithology, faults, points, area, rules, units, config)
    profile = PROFILES[config["profile"]]
    fields = profile_fields(base, profile, config)
    targets, rows, heat, diagnostics, core = delineate(
        base, fields, profile, area, lithology, rules, units, config
    )
    targets, rows = platform_evidence(
        targets, rows, base, fields, heat, profile, config
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
        list(rows[0])
        if rows
        else ["schema_version", "phase", "zone_id", "area_km2", "evidence_json"],
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
                "schema_version": 2,
                "method": "continuous_support_regions_v1",
                "phase": "after",
                "profile": config["profile"],
                "zone_count": len(targets),
                "area_km2": float(targets.area_km2.sum()),
            }
        ],
        ["schema_version", "method", "phase", "profile", "zone_count", "area_km2"],
    )
    report(
        context,
        {
            **diagnostics,
            "after_zone_count": len(targets),
            "after_area_km2": float(targets.area_km2.sum()),
            "snapshot_hash": snapshot,
            "research_area_masked": True,
            "reference_used": False,
            "grid_resolution_m": config["grid_resolution_m"],
            "profile": config["profile"],
            "method": "continuous_support_regions_v1",
            "weights": {"alteration": 0.45, "structure": 0.40, "lithology": 0.15},
            "empty_reason": ""
            if len(targets)
            else "未形成满足强核心与连续支持条件的远景区",
        },
        f"按修正后岩性、构造与蚀变资料圈定{len(targets)}处优先核查远景区，共{targets.area_km2.sum():.2f}平方公里；"
        "边界由连续支持场提取，同一连通支持带合并，区间无重叠。热力图表示综合证据支持度。",
    )
