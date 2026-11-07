"""Corrected-only prospect targets with explicit, measured neighbourhood evidence."""

import math

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize, shapes
from rasterio.transform import from_origin
from shapely.geometry import shape
from shapely.ops import unary_union
from scipy.ndimage import gaussian_filter

from multi_io import dump
from multi_prospect_raster import METHOD, mineral_grids


def grid(area, config):
    resolution = config["grid_resolution_m"]
    x0, y0, x1, y1 = area.bounds
    width, height = math.ceil((x1 - x0) / resolution), math.ceil((y1 - y0) / resolution)
    if width * height > 4000000:
        raise ValueError("计算网格超过400万像元，请增大网格尺寸")
    return from_origin(x0, y1, resolution, resolution), (height, width)


def burn(geometries, transform, dimensions, values=None):
    entries = [
        (geometry, float(value))
        for geometry, value in zip(
            geometries, values if values is not None else [1] * len(geometries)
        )
        if not geometry.is_empty
    ]
    if not entries:
        return np.zeros(dimensions, dtype="float32")
    # Low weights first: overlapping high-quality evidence must not be overwritten.
    return rasterize(
        sorted(entries, key=lambda item: item[1]),
        out_shape=dimensions,
        transform=transform,
        fill=0,
        dtype="float32",
    )


def conditions(
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
):
    if not {"P-01", "P-02", "P-03"} <= set(rules):
        raise ValueError("远景区计算需要显式启用P-01、P-02和P-03")
    first, second = rules["P-01"]["params"], rules["P-02"]["params"]
    structure_geometries, structure_weights = [], []
    for _, row in faults.iterrows():
        if row.get("state", "keep") == "exclude":
            continue
        distance = (
            first.get("buffer_main_m", 500)
            if row.geometry.length >= first.get("main_fault_min_length_m", 10000)
            else first.get("buffer_secondary_m", 250)
        )
        structure_geometries.append(row.geometry.buffer(distance))
        structure_weights.append(float(row.get("weight", 1)))
    for _, row in intersections.iterrows():
        distance = (
            first.get("buffer_intersection_other_m", 500)
            if row["type"] == "次级×次级"
            else first.get("buffer_intersection_main_secondary_m", 1000)
        )
        structure_geometries.append(row.geometry.buffer(distance))
        structure_weights.append(float(row.get("weight", 1)))
    structure = (
        burn(structure_geometries, transform, dimensions, structure_weights) >= 1
    )
    minerals = mineral_grids(alterations, transform, dimensions, config, second)
    type_count = sum(minerals.values(), np.zeros(dimensions, dtype="float64"))
    alteration = type_count >= second.get("min_types", 2)
    favourable = (
        burn(
            list(
                lithology.loc[
                    lithology.geo_sym.map(
                        lambda code: bool(units.get(code, {}).get("favorable", False))
                    ),
                    "geometry",
                ]
            ),
            transform,
            dimensions,
        )
        > 0
    )
    bedrock = (
        burn(
            list(
                lithology.loc[
                    lithology.geo_sym.map(
                        lambda code: (
                            units.get(code, {}).get("category")
                            in {"stratum", "intrusive"}
                        )
                    ),
                    "geometry",
                ]
            ),
            transform,
            dimensions,
        )
        > 0
    )
    mask = burn([area], transform, dimensions) > 0
    candidates = mask & alteration & structure & bedrock
    return (
        candidates,
        structure,
        alteration,
        favourable,
        type_count,
        minerals,
        mask,
        bedrock,
    )


def zones(
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
):
    selected, structure, alteration, favourable, type_count, minerals, mask, bedrock = (
        conditions(
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
    )
    candidates, component_areas = [], []
    for raw, _ in shapes(
        selected.astype("uint8"), mask=selected, transform=transform, connectivity=4
    ):
        geometry = shape(raw).intersection(area)
        component_areas.append(geometry.area)
        if (
            config["min_zone_area_m2"] <= geometry.area <= config["max_zone_area_m2"]
            and not geometry.is_empty
        ):
            candidates.append(geometry)

    def priority(geometry):
        cells = (burn([geometry], transform, dimensions) > 0) & selected
        return (
            -float(type_count[cells].mean()),
            -float(favourable[cells].mean()),
            -geometry.area,
            geometry.bounds,
        )

    candidates.sort(key=priority)
    eligible_count = len(candidates)
    candidates = candidates[: config["max_zone_count"]]
    rows, evidence = [], []
    target_cells = np.zeros(dimensions, dtype=bool)
    first, second = rules["P-01"]["params"], rules["P-02"]["params"]
    citations = [
        {
            "rule_id": key,
            "rule_version": rules[key]["version"],
            "knowledge_id": rules[key]["knowledge_id"],
            "knowledge_revision": rules[key]["knowledge_revision"],
        }
        for key in ("P-01", "P-02", "P-03")
    ]
    for ordinal, geometry in enumerate(candidates, 1):
        zone_id = f"P{ordinal:03}"
        cells = (burn([geometry], transform, dimensions) > 0) & selected
        if not cells.any():
            continue
        target_cells |= cells
        measured = {
            "pixel_count": int(cells.sum()),
            "structure_supported_fraction": float(structure[cells].mean()),
            "alteration_supported_fraction": float(alteration[cells].mean()),
            "favourable_fraction": float(favourable[cells].mean()),
            "bedrock_supported_fraction": float(bedrock[cells].mean()),
            "mean_weighted_type_count": float(type_count[cells].mean()),
            "min_weighted_type_count": float(type_count[cells].min()),
            "min_types_required": second.get("min_types", 2),
            "rule_expression": "alteration AND structure AND mapped_bedrock",
            "evidence_method": METHOD,
            "search_m": second.get("search_m", 250),
            "mineral_presence": {
                name: {
                    "min_weight": float(values[cells].min()),
                    "max_weight": float(values[cells].max()),
                }
                for name, values in minerals.items()
                if (values[cells] > 0).any()
            },
            "grid_resolution_m": config["grid_resolution_m"],
            "selection_order": "mean_weighted_type_count DESC, favourable_fraction DESC, area DESC",
        }
        related_faults = []
        for _, fault in faults.iterrows():
            distance = (
                first.get("buffer_main_m", 500)
                if fault.geometry.length >= first.get("main_fault_min_length_m", 10000)
                else first.get("buffer_secondary_m", 250)
            )
            if fault.get("state", "keep") != "exclude" and fault.geometry.buffer(
                distance
            ).intersects(geometry):
                related_faults.append(
                    {
                        "line_id": fault.line_id,
                        "distance_m": float(fault.geometry.distance(geometry)),
                        "buffer_m": distance,
                        "weight": float(fault.get("weight", 1)),
                    }
                )
        related_intersections = []
        for _, point in intersections.iterrows():
            distance = (
                first.get("buffer_intersection_other_m", 500)
                if point["type"] == "次级×次级"
                else first.get("buffer_intersection_main_secondary_m", 1000)
            )
            if point.geometry.buffer(distance).intersects(geometry):
                related_intersections.append(
                    {
                        "point_id": point.point_id,
                        "inferred": bool(point.inferred),
                        "type": point["type"],
                        "buffer_m": distance,
                        "gap_m": float(point.gap_m),
                    }
                )
        mineral_types = [
            name for name, values in minerals.items() if (values[cells] > 0).any()
        ]
        rock_areas = {}
        for code, group in lithology.loc[
            lithology.geometry.intersects(geometry)
        ].groupby("geo_sym"):
            rock_areas[code] = float(
                unary_union(group.geometry).intersection(geometry).area
            )
        basis = {
            "schema_version": 2,
            "phase": "after",
            "conditions": measured,
            "knowledge": citations,
            "context": {
                "minerals": mineral_types,
                "faults": related_faults,
                "intersections": related_intersections,
                "lithology_areas_m2": rock_areas,
            },
            "interpretation": "修正后资料的多要素组合目标，表示优先调查线索；邻域出现不表示矿物同像元共存，也不表示矿化概率",
        }
        text = f"{zone_id}为修正后资料圈定的优先核查远景区，面积{geometry.area / 1e6:.3f}平方公里。{measured['search_m']}米邻域内加权矿物类型数最低{measured['min_weighted_type_count']:.2f}，门槛{measured['min_types_required']}；构造支持覆盖{measured['structure_supported_fraction']:.0%}，有利岩性覆盖{measured['favourable_fraction']:.0%}。邻域组合按{config['grid_resolution_m']}米分析网格近似，不代表同像元共存或已证实矿化。"
        record = {
            "zone_id": zone_id,
            "priority_rank": ordinal,
            "area_km2": float(geometry.area / 1e6),
            "explanation": text,
            "evidence_json": dump(basis),
        }
        rows.append({**record, "geometry": geometry})
        evidence.append(
            {
                **record,
                "schema_version": 2,
                "phase": "after",
                "alteration": "、".join(mineral_types),
                "faults": dump(related_faults),
                "intersections": dump(related_intersections),
                "lithology": dump(rock_areas),
                "conditions_json": dump(measured),
            }
        )
    frame = gpd.GeoDataFrame(
        rows,
        columns=[
            "zone_id",
            "priority_rank",
            "area_km2",
            "explanation",
            "evidence_json",
            "geometry",
        ],
        geometry="geometry",
        crs=lithology.crs,
    )
    raw_support = 0.7 * type_count / len(minerals) + 0.3 * favourable
    numerator = gaussian_filter(np.where(target_cells, raw_support, 0), sigma=1)
    denominator = gaussian_filter(target_cells.astype("float64"), sigma=1)
    smoothed = np.divide(
        numerator, denominator, out=np.zeros_like(numerator), where=denominator > 0
    )
    support = np.full(dimensions, -9999, dtype="float32")
    limits = (
        [float(smoothed[target_cells].min()), float(smoothed[target_cells].max())]
        if target_cells.any()
        else [0, 0]
    )
    if target_cells.any():
        support[target_cells] = (
            (smoothed[target_cells] - limits[0]) / (limits[1] - limits[0])
            if limits[1] - limits[0] > 1e-9
            else 0.5
        )
    diagnostics = {
        "support_raw_range": limits,
        "support_formula": "0.7 * weighted_mineral_types / allowed_mineral_count + 0.3 * favourable; structure and mapped bedrock required",
        "support_normalization": "relative_min_max_within_selected_targets_after_masked_gaussian_sigma_1_cell; uniform_support=0.5",
        "support_interpretation": "相对置信度（证据支持度），非矿化概率；仅在目标内部显示，不扩展圈区边界",
        "protocol": "after_only_v2",
        "research_cells": int(mask.sum()),
        "alteration_cells": int((mask & alteration).sum()),
        "structure_cells": int((mask & structure).sum()),
        "favourable_cells": int((mask & favourable).sum()),
        "candidate_cells": int(selected.sum()),
        "weighted_type_count_max": float(type_count[mask].max()) if mask.any() else 0,
        "candidate_component_count": len(component_areas),
        "max_component_area_m2": max(component_areas, default=0),
        "filtered_small_components": sum(
            value < config["min_zone_area_m2"] for value in component_areas
        ),
        "filtered_large_components": sum(
            value > config["max_zone_area_m2"] for value in component_areas
        ),
        "eligible_component_count": eligible_count,
        "not_selected_by_count_limit": max(0, eligible_count - len(frame)),
        "max_zone_area_m2": config["max_zone_area_m2"],
        "max_zone_count": config["max_zone_count"],
        "bedrock_cells": int((mask & bedrock).sum()),
        "min_zone_area_m2": config["min_zone_area_m2"],
        "search_m": second.get("search_m", 250),
        "min_types": second.get("min_types", 2),
        "evidence_method": METHOD,
    }
    return frame, evidence, diagnostics, support
