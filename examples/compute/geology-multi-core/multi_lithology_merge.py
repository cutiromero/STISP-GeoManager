"""Conditional cartographic consolidation, independent of evaluation references."""

import json

from shapely.ops import unary_union

from multi_io import scalar


def same_unit(first, second):
    keys = ("name", "geo_sym", "class", "code", "path", "geo_unit")
    return all(
        scalar(first[key]) == scalar(second[key])
        for key in keys
        if key in first.index and key in second.index
    )


def candidates(lithology, faults, aliases, rule):
    """One measured pair per object; a point contact never qualifies."""
    params = rule["params"]
    if params.get("unit_level_consolidation") is not True:
        return []
    fault_union = unary_union(faults.geometry)
    used, result = set(), []
    ordered = lithology.sort_values("feature_id")
    for index, row in ordered.iterrows():
        identity = str(row.feature_id)
        if identity in used or aliases.get(row["name"]) != row.geo_sym:
            continue
        nearby = lithology.iloc[
            lithology.sindex.query(row.geometry, predicate="intersects")
        ].sort_values("feature_id")
        for other_index, other in nearby.iterrows():
            host_id = str(other.feature_id)
            if host_id <= identity or host_id in used or not same_unit(row, other):
                continue
            shared = row.geometry.boundary.intersection(other.geometry.boundary)
            overlap = row.geometry.intersection(other.geometry).area
            if (
                shared.length <= params.get("min_shared_boundary_m", 1)
                or overlap > 0.01
            ):
                continue
            distance = None if fault_union.is_empty else shared.distance(fault_union)
            if distance is not None and distance <= params.get("fault_buffer_m", 100):
                continue
            combined = row.geometry.union(other.geometry)
            if not combined.is_valid or combined.geom_type != "Polygon":
                continue
            result.append(
                (
                    index,
                    other_index,
                    {
                        "name": row["name"],
                        "observed_code": row.geo_sym,
                        "host_feature_id": host_id,
                        "host_code": other.geo_sym,
                        "shared_boundary_m": float(shared.length),
                        "fault_distance_m": distance,
                        "area_m2": float(row.geometry.area),
                        "host_area_m2": float(other.geometry.area),
                        "involved_area_m2": float(combined.area),
                        "coverage_change_area_m2": 0.0,
                        "unit_level_consolidation": True,
                    },
                )
            )
            used.update((identity, host_id))
            break
    return result


def approved_host(frame, operation, geometry):
    """Bind the exact measured host; never choose a new one after approval."""
    measurement = json.loads(operation["measurements_json"])
    host_id = measurement.get("host_feature_id")
    matches = frame.index[frame.feature_id == host_id]
    if len(matches) != 1:
        raise ValueError("获批融合的目标图斑已变化，请重新检查")
    host_index = matches[0]
    source = frame.loc[frame.feature_id == operation["feature_id"]].iloc[0]
    host = frame.loc[host_index]
    shared = geometry.boundary.intersection(host.geometry.boundary).length
    if (
        not same_unit(source, host)
        or abs(shared - measurement["shared_boundary_m"]) > 0.001
        or geometry.intersection(host.geometry).area > 0.01
        or measurement.get("unit_level_consolidation") is not True
    ):
        raise ValueError("同单元融合条件或共享边界已经改变，请重新批准")
    return host_index
