"""Natural connected support regions, anchored by real geological evidence cores."""

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize, shapes
from scipy import ndimage
from shapely.geometry import shape
from shapely.ops import unary_union

from multi_io import dump
from prospect_boundaries import extract_regions, topology_report

CONNECTIVITY = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype="uint8")
METHOD = "continuous_support_regions_v1"
COLUMNS = [
    "zone_id",
    "priority_rank",
    "area_km2",
    "core_area_km2",
    "mean_support",
    "effective_support_km2",
    "explanation",
    "evidence_json",
    "lithology_json",
    "geometry",
]


def mask_geometry(mask, transform):
    return unary_union(
        [
            shape(raw)
            for raw, value in shapes(
                mask.astype("uint8"), mask=mask, transform=transform
            )
            if value
        ]
    )


def region_sources(geometry, lithology, active, units):
    rocks = {}
    for code, group in lithology.loc[lithology.geometry.intersects(geometry)].groupby(
        "geo_sym"
    ):
        rocks[code] = float(
            group.geometry.union_all().intersection(geometry).area / 1e6
        )
    faults = []
    if active is not None:
        for _, fault in active.iterrows():
            distance = float(fault.geometry.distance(geometry))
            if distance <= 2000:
                faults.append(
                    {
                        "line_id": str(fault.line_id),
                        "distance_m": round(distance, 2),
                        "weight": float(fault.get("weight", 1)),
                        "length_m": round(fault.geometry.length, 2),
                    }
                )
    faults.sort(
        key=lambda value: (value["distance_m"], -value["weight"], value["line_id"])
    )
    descriptions = {
        code: {"name": units.get(code, {}).get("name", code), "area_km2": value}
        for code, value in sorted(rocks.items(), key=lambda item: -item[1])
    }
    return rocks, faults, descriptions


def delineate(base, fields, profile, area, lithology, rules, units, config):
    resolution = config["grid_resolution_m"]
    transform = base["transform"]
    core = fields["core"] & (fields["score"] >= config["core_score_min"])
    labels, _ = ndimage.label(core, structure=CONNECTIVITY)
    keep = (
        np.bincount(labels.ravel()) * resolution**2 >= config["min_core_area_km2"] * 1e6
    )
    keep[0] = False
    core = keep[labels]
    core_geometry = mask_geometry(core, transform).intersection(area)
    bedrock = lithology.loc[
        lithology.geo_sym.map(
            lambda code: units.get(code, {}).get("category") in {"stratum", "intrusive"}
        )
    ].geometry.union_all()
    allowed = area.intersection(bedrock).intersection(
        mask_geometry(fields["domain"], transform)
    )
    geometries = (
        extract_regions(fields["margin"], transform, allowed) if core.any() else []
    )
    labels = (
        rasterize(
            [(geometry, index + 1) for index, geometry in enumerate(geometries)],
            out_shape=base["dimensions"],
            transform=transform,
            dtype="uint32",
        )
        if geometries
        else np.zeros(base["dimensions"], dtype="uint32")
    )
    regions = []
    excluded_small = excluded_core = 0
    for identity, geometry in enumerate(geometries, 1):
        area_km2 = float(geometry.area / 1e6)
        if area_km2 < config["min_zone_area_km2"]:
            excluded_small += 1
            continue
        core_area = float(core_geometry.intersection(geometry).area / 1e6)
        if core_area < config["min_core_area_km2"]:
            excluded_core += 1
            continue
        cells = labels == identity
        if not cells.any():
            continue
        scores = fields["score"][cells]
        regions.append(
            {
                "identity": identity,
                "geometry": geometry,
                "area_km2": area_km2,
                "core_area_km2": core_area,
                "mean_support": float(scores.mean()),
                "effective_support_km2": float(
                    np.clip(
                        (scores - profile["growth_threshold"])
                        / (1 - profile["growth_threshold"]),
                        0,
                        1,
                    ).mean()
                    * area_km2
                ),
            }
        )
    regions.sort(
        key=lambda item: (
            -item["effective_support_km2"],
            -item["core_area_km2"],
            -item["mean_support"],
            item["geometry"].bounds,
        )
    )
    eligible = len(regions)
    regions = regions[: profile["max_zone_count"]]
    checks = topology_report([item["geometry"] for item in regions])
    checks["support_smooth_m"] = config["support_smooth_m"]
    citations = [
        {
            "rule_id": key,
            "rule_version": rules[key]["version"],
            "knowledge_id": rules[key]["knowledge_id"],
            "knowledge_revision": rules[key]["knowledge_revision"],
            "use": "修复后构造、岩性、矿物组合规则；连续场外围由算子2.2.0计算",
        }
        for key in ("P-01", "P-02", "P-03")
    ]
    selected = np.zeros(base["dimensions"], dtype=bool)
    rows, records = [], []
    for rank, item in enumerate(regions, 1):
        geometry = item["geometry"]
        cells = labels == item["identity"]
        selected |= cells
        scores = fields["score"][cells]
        measured = {
            "core_area_km2": item["core_area_km2"],
            "core_fraction": item["core_area_km2"] / item["area_km2"],
            "min_support": float(scores.min()),
            "max_support": float(scores.max()),
            "mean_structure": float(fields["structure"][cells].mean()),
            "mean_alteration": float(fields["alteration"][cells].mean()),
            "favourable_fraction": float(base["masks"]["favourable"][cells].mean()),
            "mean_weighted_types": float(fields["broad_count"][cells].mean()),
            "mean_weighted_coverage": float(fields["density"][cells].mean()),
            "rank_basis": "有效支持面积、强核心面积、平均支持度",
            "grid_resolution_m": resolution,
            "direct_minerals": [
                name
                for name, values in base["evidence"].items()
                if (values["presence"][cells] > 0).any()
            ],
        }
        rocks, faults, descriptions = region_sources(
            geometry, lithology, base.get("active_faults"), units
        )
        basis = {
            "method": METHOD,
            "phase": "after",
            "profile": profile,
            "parameters": config,
            "measurements": measured,
            "source_knowledge": citations,
            "boundary_extraction": checks,
            "nearby_faults": faults,
            "lithology_areas_km2": rocks,
            "interpretation": "核心使用250米矿物组合和原构造条件；由连续支持场等值线直接圈区，连通区域整体保留；综合支持度未作矿点标定，不表示有矿概率",
        }
        row = {
            "zone_id": f"R{rank:02}",
            "priority_rank": rank,
            **{
                key: item[key]
                for key in [
                    "area_km2",
                    "core_area_km2",
                    "mean_support",
                    "effective_support_km2",
                ]
            },
            **measured,
            "explanation": f"R{rank:02}为自然连通的构造—蚀变支持带，面积{item['area_km2']:.2f}平方公里，含{item['core_area_km2']:.2f}平方公里强证据核心；平均构造支持{measured['mean_structure']:.2f}，平均蚀变支持{measured['mean_alteration']:.2f}，有利岩性覆盖{measured['favourable_fraction']:.0%}。",
            "evidence_json": dump(basis),
            "nearby_faults_json": dump(faults),
            "lithology_json": dump(descriptions),
        }
        rows.append(row)
        records.append(
            {
                **{key: row[key] for key in COLUMNS if key != "geometry"},
                "geometry": geometry,
            }
        )
    frame = gpd.GeoDataFrame(
        records, columns=COLUMNS, geometry="geometry", crs=lithology.crs
    )
    heat = np.where(selected, fields["score"], -9999).astype("float32")
    diagnostics = {
        **checks,
        "strong_core_cells": int(core.sum()),
        "growth_cells": int((fields["margin"] >= 0).sum()),
        "natural_component_count": len(geometries),
        "eligible_regions": eligible,
        "omitted_by_count": eligible - len(frame),
        "filtered_small_regions": excluded_small,
        "filtered_core_regions": excluded_core,
        "large_zone_notice_km2": profile["large_zone_notice_km2"],
        "large_zone_count": sum(
            item["area_km2"] > profile["large_zone_notice_km2"] for item in regions
        ),
        "zone_count": len(frame),
        "area_km2": float(frame.area_km2.sum()),
        "area_fraction": float(frame.area_km2.sum() * 1e6 / area.area),
    }
    return frame, rows, heat, diagnostics, core
