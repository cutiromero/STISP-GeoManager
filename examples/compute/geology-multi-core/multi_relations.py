"""Reconstruct measured crossings and explicitly inferred end-point connections."""

import math

import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from shapely.ops import nearest_points

from multi_checks import line_parts
from multi_io import digest

FIELDS = [
    "point_id",
    "f1",
    "f2",
    "type",
    "inferred",
    "gap_m",
    "angle_deg",
    "rule_id",
    "rule_version",
    "weight",
]


def reconstruct(faults, area, rules):
    active = (
        faults.loc[
            (faults.get("state", "keep") != "exclude") & (faults.get("weight", 1) > 0)
        ]
        if "state" in faults
        else faults
    )
    active = active.reset_index(drop=True)
    main_length = (
        rules.get("P-01", {}).get("params", {}).get("main_fault_min_length_m", 10000)
    )
    rows, seen = [], set()

    def add(first, second, point, inferred=False, gap=0.0, angle=0.0):
        ids = sorted(
            [str(active.at[first, "line_id"]), str(active.at[second, "line_id"])]
        )
        identity = digest([ids, round(point.x, 3), round(point.y, 3), inferred])[:24]
        if identity in seen or not area.covers(point):
            return
        seen.add(identity)
        main_count = sum(
            active.geometry[index].length >= main_length for index in (first, second)
        )
        kind = {2: "主干×主干", 1: "主干×次级", 0: "次级×次级"}[main_count]
        source = rules.get("S-05", {}) if inferred else rules.get("P-01", {})
        weight = min(
            float(active.iloc[index].get("weight", 1)) for index in (first, second)
        )
        rows.append(
            {
                "point_id": "X-" + identity,
                "f1": ids[0],
                "f2": ids[1],
                "type": kind,
                "inferred": inferred,
                "gap_m": float(gap),
                "angle_deg": float(angle),
                "rule_id": source.get("id", ""),
                "rule_version": source.get("version", ""),
                "weight": weight,
                "geometry": point,
            }
        )

    for first, row in active.iterrows():
        for second in active.sindex.query(row.geometry, predicate="intersects"):
            if first >= second:
                continue
            geometry = row.geometry.intersection(active.geometry[second])
            for point in getattr(geometry, "geoms", [geometry]):
                if point.geom_type == "Point":
                    add(first, second, point)
    if "S-05" in rules:
        params = rules["S-05"]["params"]
        for first, row in active.iterrows():
            for line in line_parts(row.geometry):
                coords = list(line.coords)
                for end in (0, -1):
                    point, previous = (
                        Point(coords[end]),
                        Point(coords[1 if end == 0 else -2]),
                    )
                    if point.distance(area.boundary) < 50:
                        continue
                    candidates = [
                        index
                        for index in active.sindex.query(
                            point.buffer(params.get("snap_dist_m", 300)),
                            predicate="intersects",
                        )
                        if index != first
                    ]
                    if any(
                        active.geometry[index].distance(point) < 0.01
                        for index in candidates
                    ):
                        continue
                    best = None
                    for second in candidates:
                        target = nearest_points(point, active.geometry[second])[1]
                        direction, extension = (
                            np.array([point.x - previous.x, point.y - previous.y]),
                            np.array([target.x - point.x, target.y - point.y]),
                        )
                        denominator = np.linalg.norm(direction) * np.linalg.norm(
                            extension
                        )
                        if denominator == 0:
                            continue
                        angle = math.degrees(
                            math.acos(
                                float(
                                    np.clip(direction @ extension / denominator, -1, 1)
                                )
                            )
                        )
                        distance = point.distance(target)
                        if (
                            distance <= params.get("snap_dist_m", 300)
                            and angle <= params.get("max_angle", 45)
                            and (best is None or distance < best[0])
                        ):
                            best = distance, second, target, angle
                    if best:
                        gap, second, target, angle = best
                        add(first, second, target, True, gap, angle)
    return gpd.GeoDataFrame(
        rows, columns=FIELDS + ["geometry"], geometry="geometry", crs=faults.crs
    )
