"""Cartographic smoothing with explicit spacing and remeasured polygon evidence."""

import json

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize, shapes
from shapely import make_valid, set_precision
from shapely.geometry import GeometryCollection, shape
from shapely.ops import unary_union

from multi_io import dump


def polygonal(geometry):
    geometry = make_valid(geometry)
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    return unary_union(
        [
            part
            for part in geometry.geoms
            if part.geom_type in {"Polygon", "MultiPolygon"}
        ]
    )


def smooth_nonoverlapping(geometries, area, radius, gap):
    if radius < 0 or gap < 0:
        raise ValueError("平滑半径和区间间隔不能为负")
    output = []
    occupied = GeometryCollection()
    for original in geometries:
        geometry = polygonal(original)
        if radius:
            geometry = geometry.buffer(radius, quad_segs=16).buffer(
                -radius, quad_segs=16
            )
            geometry = geometry.buffer(-radius / 2, quad_segs=16).buffer(
                radius / 2, quad_segs=16
            )
            geometry = geometry.simplify(radius * 0.1, preserve_topology=True)
        geometry = polygonal(geometry.intersection(area))
        if not occupied.is_empty:
            geometry = polygonal(
                geometry.difference(
                    occupied.buffer(gap + 0.05, quad_segs=32) if gap else occupied
                )
            )
        geometry = polygonal(set_precision(geometry, 0.01))
        if geometry.is_empty:
            raise ValueError("平滑或间隔导致区域消失，请减小概化尺度")
        output.append(geometry)
        occupied = unary_union([occupied, geometry])
    overlaps = []
    distances = []
    for index, first in enumerate(output):
        for second in output[index + 1 :]:
            overlaps.append(float(first.intersection(second).area))
            distances.append(float(first.distance(second)))
    maximum = max(overlaps, default=0)
    minimum = min(distances, default=None)
    if maximum > 1e-6:
        raise ValueError("边界处理后存在重叠")
    if gap and minimum is not None and minimum < gap - 0.05:
        raise ValueError("边界处理后未达到最小间隔")
    return output, {
        "smoothing_radius_m": radius,
        "minimum_gap_m": gap,
        "actual_minimum_distance_m": minimum,
        "maximum_overlap_m2": maximum,
        "pair_count": len(overlaps),
    }


def apply_boundaries(frame, rows, base, fields, core, area, lithology, units, config):
    radius = config.get("boundary_smooth_m", 0)
    gap = config.get("between_zone_gap_m", 0)
    if frame.empty or (not radius and not gap):
        return (
            frame,
            rows,
            np.where(np.zeros(base["dimensions"], dtype=bool), 0, -9999).astype(
                "float32"
            ),
            {"boundary_processing": False},
        )
    geometries, check = smooth_nonoverlapping(list(frame.geometry), area, radius, gap)
    transform = base["transform"]
    dimensions = base["dimensions"]
    labels = rasterize(
        [(geometry, index + 1) for index, geometry in enumerate(geometries)],
        out_shape=dimensions,
        transform=transform,
        dtype="uint16",
    )
    core_shapes = [
        shape(raw).intersection(area)
        for raw, value in shapes(core.astype("uint8"), mask=core, transform=transform)
        if value
    ]
    core_geometry = unary_union(core_shapes)
    records = []
    for index, (original_row, geometry) in enumerate(zip(rows, geometries), 1):
        row = dict(original_row)
        cells = labels == index
        if not cells.any():
            raise ValueError("平滑区域小于当前格网尺度")
        before = row["area_km2"]
        area_km2 = geometry.area / 1e6
        scores = fields["score"][cells]
        core_km2 = core_geometry.intersection(geometry).area / 1e6
        if core_km2 < config["min_core_area_km2"]:
            raise ValueError("边界概化后强证据核心不足")
        row.update(
            area_before_smoothing_km2=before,
            area_km2=float(area_km2),
            core_area_km2=float(core_km2),
            core_fraction=float(core_km2 / area_km2),
            mean_support=float(scores.mean()),
            min_support=float(scores.min()),
            max_support=float(scores.max()),
            mean_structure=float(fields["structure"][cells].mean()),
            mean_alteration=float(fields["alteration"][cells].mean()),
            favourable_fraction=float(base["masks"]["favourable"][cells].mean()),
            mean_weighted_types=float(fields["broad_count"][cells].mean()),
            mean_weighted_coverage=float(fields["density"][cells].mean()),
            effective_support_km2=float(
                np.clip(
                    (scores - config["growth_threshold"])
                    / (1 - config["growth_threshold"]),
                    0,
                    1,
                ).mean()
                * area_km2
            ),
            smoothing_radius_m=radius,
            minimum_gap_m=gap,
        )
        row["direct_minerals"] = [
            name
            for name, values in base["evidence"].items()
            if (values["presence"][cells] > 0).any()
        ]
        row["explanation"] = (
            f"{row['zone_id']}平滑后面积{area_km2:.2f}平方公里，含{core_km2:.2f}平方公里强证据核心；采用{radius:g}米边界概化，区域间保留至少{gap:g}米间隔。平均构造支持{row['mean_structure']:.2f}，平均蚀变支持{row['mean_alteration']:.2f}，有利岩性覆盖{row['favourable_fraction']:.0%}。"
        )
        rocks = {}
        for code, group in lithology.loc[
            lithology.geometry.intersects(geometry)
        ].groupby("geo_sym"):
            rocks[code] = float(
                group.geometry.union_all().intersection(geometry).area / 1e6
            )
        row["lithology_json"] = dump(
            {
                code: {"name": units.get(code, {}).get("name", code), "area_km2": value}
                for code, value in sorted(rocks.items(), key=lambda item: -item[1])
            }
        )
        faults = []
        active = base.get("active_faults")
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
        row["nearby_faults_json"] = dump(faults)
        basis = json.loads(row["evidence_json"])
        basis.update(
            boundary_processing=check, nearby_faults=faults, lithology_areas_km2=rocks
        )
        basis["measurements"].update(
            {
                key: value
                for key, value in row.items()
                if key
                not in {
                    "zone_id",
                    "evidence_json",
                    "lithology_json",
                    "nearby_faults_json",
                    "direct_minerals",
                    "explanation",
                }
            }
        )
        basis["interpretation"] += (
            "；边界为100米制图概化，支持统计按50米格网近似，优先级较高区域优先保留共享概化范围"
        )
        row["evidence_json"] = dump(basis)
        rows[index - 1] = row
        record = {key: row[key] for key in frame.columns if key != "geometry"}
        records.append(
            {
                **record,
                "area_before_smoothing_km2": before,
                "smoothing_radius_m": radius,
                "minimum_gap_m": gap,
                "geometry": geometry,
            }
        )
    result = gpd.GeoDataFrame(records, geometry="geometry", crs=frame.crs)
    heat = np.where(labels > 0, fields["score"], -9999).astype("float32")
    check.update(
        boundary_processing=True,
        total_area_before_km2=float(frame.area_km2.sum()),
        total_area_after_km2=float(result.area_km2.sum()),
    )
    return result, rows, heat, check
