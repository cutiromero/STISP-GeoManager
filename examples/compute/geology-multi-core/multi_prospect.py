"""One evidence expression drives both the grid grades and the audience report."""

import math

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize, shapes
from rasterio.transform import from_origin
from shapely.geometry import shape
from shapely.ops import unary_union

from multi_io import dump


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
    type_count = np.zeros(dimensions, dtype="float32")
    allowed_types = second.get("alteration_types", sorted(alterations.alt.unique()))
    for name, group in alterations.groupby("alt"):
        if name not in allowed_types:
            continue
        active = (
            group.loc[group.get("state", "keep") != "exclude"]
            if "state" in group
            else group
        )
        geometries = list(active.geometry.buffer(second.get("search_m", 250)))
        weights = active.weight.tolist() if "weight" in active else [1] * len(active)
        type_count += burn(geometries, transform, dimensions, weights)
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
    mask = burn([area], transform, dimensions) > 0
    grade = np.zeros(dimensions, dtype="uint8")
    grade[mask & alteration & (structure | favourable)] = 2
    grade[mask & alteration & structure & favourable] = 3
    return grade, structure, alteration, favourable, type_count


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
    phase,
):
    grade, structure, alteration, favourable, type_count = conditions(
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
    candidates = []
    for raw, level in shapes(
        grade, mask=grade > 0, transform=transform, connectivity=4
    ):
        geometry = shape(raw).intersection(area)
        if geometry.area >= config["min_zone_area_m2"] and not geometry.is_empty:
            candidates.append((int(level), geometry))
    candidates.sort(key=lambda item: (-item[0], -item[1].area, item[1].bounds))
    rows, evidence, counts = [], [], {"A": 0, "B": 0}
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
    for level, geometry in candidates:
        label = "A" if level == 3 else "B"
        counts[label] += 1
        zone_id = f"{label}{counts[label]:03}"
        cells = (burn([geometry], transform, dimensions) > 0) & (grade == level)
        if not cells.any():
            continue
        measured = {
            "pixel_count": int(cells.sum()),
            "structure_supported_fraction": float(structure[cells].mean()),
            "alteration_supported_fraction": float(alteration[cells].mean()),
            "favourable_fraction": float(favourable[cells].mean()),
            "min_weighted_type_count": float(type_count[cells].min()),
            "min_types_required": second.get("min_types", 2),
            "rule_expression": "alteration AND structure AND favourable"
            if label == "A"
            else "alteration AND (structure OR favourable) AND NOT all_three",
            "grid_resolution_m": config["grid_resolution_m"],
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
        active = (
            alterations.loc[alterations.get("state", "keep") != "exclude"]
            if "state" in alterations
            else alterations
        )
        near_alt = active.iloc[
            active.sindex.query(
                geometry.buffer(second.get("search_m", 250)), predicate="intersects"
            )
        ]
        mineral_types = sorted(
            set(near_alt.alt)
            & set(second.get("alteration_types", near_alt.alt.unique()))
        )
        rock_areas = {}
        for code, group in lithology.loc[
            lithology.geometry.intersects(geometry)
        ].groupby("geo_sym"):
            rock_areas[code] = float(
                unary_union(group.geometry).intersection(geometry).area
            )
        basis = {
            "phase": phase,
            "grade_conditions": measured,
            "knowledge": citations,
            "context": {
                "minerals": mineral_types,
                "faults": related_faults,
                "intersections": related_intersections,
                "lithology_areas_m2": rock_areas,
            },
            "interpretation": "本案例规则的证据组合等级，代表优先核查方向",
        }
        text = f"{zone_id}为{label}类优先核查远景区，面积{geometry.area / 1e6:.3f}平方公里。网格内加权蚀变种类数最低{measured['min_weighted_type_count']:.2f}，要求不少于{measured['min_types_required']}；构造条件覆盖{measured['structure_supported_fraction']:.0%}，有利岩性覆盖{measured['favourable_fraction']:.0%}。交汇资料中推测{sum(item['inferred'] for item in related_intersections)}处、几何相交{sum(not item['inferred'] for item in related_intersections)}处。"
        record = {
            "zone_id": zone_id,
            "grade": label,
            "area_km2": float(geometry.area / 1e6),
            "explanation": text,
            "evidence_json": dump(basis),
        }
        rows.append({**record, "geometry": geometry})
        evidence.append(
            {
                **record,
                "phase": phase,
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
            "grade",
            "area_km2",
            "explanation",
            "evidence_json",
            "geometry",
        ],
        geometry="geometry",
        crs=lithology.crs,
    )
    return frame, evidence
