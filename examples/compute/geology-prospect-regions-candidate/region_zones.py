"""Core-and-context delineation with evidence-ranked, bounded regional footprints."""

import heapq
import json
import geopandas as gpd
import numpy as np
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import shape
from shapely import make_valid

from multi_io import dump

CONNECTIVITY = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype="uint8")


def seed_peaks(cells, score, separation_cells):
    positions = np.argwhere(cells)
    if not len(positions):
        return []
    values = score[cells]
    order = np.lexsort((positions[:, 1], positions[:, 0], -values))
    selected = []
    for index in order:
        row, col = positions[index]
        if all(
            (row - y) ** 2 + (col - x) ** 2 >= separation_cells**2 for y, x in selected
        ):
            selected.append((int(row), int(col)))
    return selected


def split_large(component, core, score, maximum_cells, config):
    if int(component.sum()) <= maximum_cells:
        return [component]
    peaks = seed_peaks(
        component & core,
        score,
        config["region_seed_spacing_m"] / config["grid_resolution_m"],
    )
    if not peaks:
        return []
    labels = np.zeros(component.shape, dtype="int32")
    distances = np.full(component.shape, np.inf)
    queue = []
    for identity, (row, col) in enumerate(peaks, 1):
        distances[row, col] = 0
        labels[row, col] = identity
        heapq.heappush(queue, (0.0, identity, row, col))
    height, width = component.shape
    limit = config["max_geodesic_reach_m"]
    resolution = config["grid_resolution_m"]
    while queue:
        cost, identity, row, col = heapq.heappop(queue)
        if cost != distances[row, col] or identity != labels[row, col]:
            continue
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            y, x = row + dy, col + dx
            if not (0 <= y < height and 0 <= x < width and component[y, x]):
                continue
            candidate = cost + resolution * (
                1 + 1.5 * (1 - (score[row, col] + score[y, x]) / 2)
            )
            if candidate <= limit and candidate < distances[y, x]:
                distances[y, x] = candidate
                labels[y, x] = identity
                heapq.heappush(queue, (candidate, identity, y, x))
    parts = []
    for identity in range(1, len(peaks) + 1):
        part = component & (labels == identity)
        if not part.any():
            continue
        if part.sum() > maximum_cells:
            coordinates = np.argwhere(part)
            order = np.argsort(distances[part], kind="stable")[: int(maximum_cells)]
            part = np.zeros_like(component)
            kept = coordinates[order]
            part[kept[:, 0], kept[:, 1]] = True
        parts.append(part)
    return parts


def delineate(base, fields, profile, area, lithology, rules, units, config):
    resolution = config["grid_resolution_m"]
    pixel_area = resolution**2
    transform = base["transform"]
    core = fields["core"] & (fields["score"] >= config["core_score_min"])
    labels, count = ndimage.label(core, structure=CONNECTIVITY)
    counts = np.bincount(labels.ravel())
    keep = counts * pixel_area >= config["min_core_area_km2"] * 1e6
    keep[0] = False
    core = keep[labels]
    grown = ndimage.binary_propagation(
        core, structure=CONNECTIVITY, mask=fields["growth"]
    )
    components, component_count = ndimage.label(grown, structure=CONNECTIVITY)
    regions = []
    excluded_small = excluded_large = 0
    for index, window in enumerate(ndimage.find_objects(components), 1):
        if window is None:
            continue
        selected = components[window] == index
        for part in split_large(
            selected,
            core[window],
            fields["score"][window],
            profile["max_zone_area_km2"] * 1e6 / pixel_area,
            config,
        ):
            area_km2 = float(part.sum() * pixel_area / 1e6)
            if area_km2 < config["min_zone_area_km2"]:
                excluded_small += 1
                continue
            if area_km2 > profile["max_zone_area_km2"]:
                excluded_large += 1
                continue
            core_area = float((core[window] & part).sum() * pixel_area / 1e6)
            if core_area < config["min_core_area_km2"]:
                continue
            scores = fields["score"][window][part]
            effective = float(
                np.clip(
                    (scores - profile["growth_threshold"])
                    / (1 - profile["growth_threshold"]),
                    0,
                    1,
                ).sum()
                * pixel_area
                / 1e6
            )
            regions.append(
                {
                    "window": window,
                    "cells": part,
                    "area_km2": area_km2,
                    "core_area_km2": core_area,
                    "mean_support": float(scores.mean()),
                    "effective_support_km2": effective,
                }
            )
    regions.sort(
        key=lambda item: (
            -item["effective_support_km2"],
            -item["core_area_km2"],
            -item["mean_support"],
            item["window"][0].start,
            item["window"][1].start,
        )
    )
    eligible = len(regions)
    regions = regions[: profile["max_zone_count"]]
    selected = np.zeros(base["dimensions"], dtype="uint16")
    rows = []
    citations = [
        {
            "rule_id": key,
            "rule_version": rules[key]["version"],
            "knowledge_id": rules[key]["knowledge_id"],
            "knowledge_revision": rules[key]["knowledge_revision"],
            "use": "修复后资料与构造、岩性、矿物组合背景；候选外围规则尚未正式发布",
        }
        for key in ("P-01", "P-02", "P-03")
    ]
    for rank, item in enumerate(regions, 1):
        window = item["window"]
        cells = item["cells"]
        selected[window][cells] = rank
        measured = {
            "core_area_km2": item["core_area_km2"],
            "core_fraction": float((core[window] & cells).mean())
            if cells.all()
            else float((core[window] & cells).sum() / cells.sum()),
            "min_support": float(fields["score"][window][cells].min()),
            "max_support": float(fields["score"][window][cells].max()),
            "mean_structure": float(fields["structure"][window][cells].mean()),
            "mean_alteration": float(fields["alteration"][window][cells].mean()),
            "favourable_fraction": float(
                base["masks"]["favourable"][window][cells].mean()
            ),
            "mean_weighted_types": float(fields["broad_count"][window][cells].mean()),
            "mean_weighted_coverage": float(fields["density"][window][cells].mean()),
            "rank_basis": "有效支持面积、强核心面积、平均支持度",
            "grid_resolution_m": resolution,
        }
        minerals = [
            name
            for name, values in base["evidence"].items()
            if (values["presence"][window][cells] > 0).any()
        ]
        measured["direct_minerals"] = minerals
        basis = {
            "method": "core_context_regions_candidate_v1",
            "candidate": True,
            "phase": "after",
            "profile": profile,
            "parameters": config,
            "measurements": measured,
            "source_knowledge": citations,
            "interpretation": "核心使用250米矿物组合和原构造条件，外围为相连的中等支持区域；综合支持度未作矿点标定，不表示有矿概率",
        }
        rows.append(
            {
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
                "explanation": f"R{rank:02}包括{item['core_area_km2']:.2f}平方公里强证据核心及相连外围，总面积{item['area_km2']:.2f}平方公里；平均构造支持{measured['mean_structure']:.2f}，平均蚀变支持{measured['mean_alteration']:.2f}，有利岩性覆盖{measured['favourable_fraction']:.0%}。",
                "evidence_json": dump(basis),
            }
        )
    geometries = {}
    for raw, value in shapes(
        selected, mask=selected > 0, transform=transform, connectivity=4
    ):
        identity = int(value)
        geometry = make_valid(shape(raw).intersection(area))
        if identity in geometries:
            geometries[identity] = geometries[identity].union(geometry)
        else:
            geometries[identity] = geometry
    core_areas = {}
    core_labels = np.where(core, selected, 0).astype("uint16")
    for raw, value in shapes(
        core_labels, mask=core_labels > 0, transform=transform, connectivity=4
    ):
        identity = int(value)
        core_areas[identity] = (
            core_areas.get(identity, 0)
            + make_valid(shape(raw).intersection(area)).area / 1e6
        )
    records = []
    for rank, row in enumerate(rows, 1):
        geometry = geometries[rank]
        nominal = row["area_km2"]
        row["area_km2"] = float(geometry.area / 1e6)
        row["core_area_km2"] = float(core_areas.get(rank, 0))
        row["core_fraction"] = row["core_area_km2"] / row["area_km2"]
        row["effective_support_km2"] *= row["area_km2"] / nominal
        row["explanation"] = (
            f"{row['zone_id']}包括{row['core_area_km2']:.2f}平方公里强证据核心及相连外围，总面积{row['area_km2']:.2f}平方公里；平均构造支持{row['mean_structure']:.2f}，平均蚀变支持{row['mean_alteration']:.2f}，有利岩性覆盖{row['favourable_fraction']:.0%}。"
        )
        basis = json.loads(row["evidence_json"])
        basis["measurements"].update(
            core_area_km2=row["core_area_km2"],
            core_fraction=row["core_fraction"],
            footprint_area_km2=row["area_km2"],
            effective_support_km2=row["effective_support_km2"],
        )
        row["evidence_json"] = dump(basis)
        rock_areas = {}
        for code, group in lithology.loc[
            lithology.geometry.intersects(geometry)
        ].groupby("geo_sym"):
            rock_areas[code] = float(
                group.geometry.union_all().intersection(geometry).area / 1e6
            )
        faults = base.get("active_faults")
        associated = []
        if faults is not None:
            for _, fault in faults.iterrows():
                distance = float(fault.geometry.distance(geometry))
                if distance <= 2000:
                    associated.append(
                        {
                            "line_id": str(fault.line_id),
                            "distance_m": round(distance, 2),
                            "weight": float(fault.get("weight", 1)),
                            "length_m": round(fault.geometry.length, 2),
                        }
                    )
        associated.sort(
            key=lambda item: (item["distance_m"], -item["weight"], item["line_id"])
        )
        basis = json.loads(row["evidence_json"])
        basis["nearby_faults"] = associated
        basis["lithology_areas_km2"] = rock_areas
        row["evidence_json"] = dump(basis)
        row["nearby_faults_json"] = dump(associated)
        row["lithology_json"] = dump(
            {
                code: {"name": units.get(code, {}).get("name", code), "area_km2": value}
                for code, value in sorted(rock_areas.items(), key=lambda pair: -pair[1])
            }
        )
        records.append(
            {
                **{
                    key: row[key]
                    for key in [
                        "zone_id",
                        "priority_rank",
                        "area_km2",
                        "core_area_km2",
                        "mean_support",
                        "effective_support_km2",
                        "explanation",
                        "evidence_json",
                        "lithology_json",
                    ]
                },
                "geometry": geometry,
            }
        )
    frame = gpd.GeoDataFrame(
        records,
        columns=[
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
        ],
        geometry="geometry",
        crs=lithology.crs,
    )
    heat = np.where(selected > 0, fields["score"], -9999).astype("float32")
    diagnostics = {
        "strong_core_cells": int(core.sum()),
        "growth_cells": int(grown.sum()),
        "grown_component_count": component_count,
        "eligible_regions": eligible,
        "omitted_by_count": eligible - len(frame),
        "filtered_small_regions": excluded_small,
        "filtered_large_regions": excluded_large,
        "zone_count": len(frame),
        "area_km2": float(frame.area_km2.sum()),
        "area_fraction": float(frame.area_km2.sum() * 1e6 / area.area),
    }
    return frame, rows, heat, diagnostics, core
