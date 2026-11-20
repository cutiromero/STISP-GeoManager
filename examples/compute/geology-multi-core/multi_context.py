"""Opt-in regional context review; no reference map or preparation labels."""

from collections import defaultdict
import math

from shapely.geometry import LineString
from shapely.ops import unary_union


def buffered_group(group, cache, distance=0.5):
    """Reuse a single neighbour's unchanged buffer within one inspection."""
    if len(group) == 1:
        key = str(group.iloc[0].feature_id), distance
        if key not in cache:
            cache[key] = group.geometry.iloc[0].buffer(distance)
        return cache[key]
    return unary_union(group.geometry).buffer(distance)


def relation(current, host):
    if current.get("group") == "volcanic" and (
        host.get("group") == "metamorphic_high"
        or host.get("group") == "carbonate_interbed"
        and (host.get("age_ma") or 0) > 1000
    ):
        return "L-04"
    category = current.get("category")
    if category != host.get("category") or category not in {"stratum", "intrusive"}:
        return None
    age, host_age = current.get("age_ma"), host.get("age_ma")
    if age is None or host_age is None or age <= host_age:
        return None
    return "L-02" if category == "intrusive" else "L-01"


def candidates(lithology, faults, area, units, parameters, represented=()):
    """Measure dominant-neighbour and same-unit continuity with scale limits.

    An older island may be a valid window or enclave. This measurement only
    supports a review candidate; it never proves an island geologically wrong.
    A nearby line is recorded separately rather than hiding all other evidence.
    """
    represented = set(represented)
    fault_union = unary_union(faults.geometry)
    same_units = {code: group for code, group in lithology.groupby("geo_sym")}
    neighbour_buffers = {}
    for _, row in lithology.iterrows():
        geometry = row.geometry
        if (
            row.feature_id in represented
            or geometry.area > parameters.get("max_area_km2", 12) * 1e6
        ):
            continue
        exterior = unary_union(
            [
                LineString(part.exterior.coords)
                for part in getattr(geometry, "geoms", [geometry])
            ]
        )
        if (
            not exterior.length
            or exterior.intersection(area.boundary.buffer(0.5)).length
            > 0.01 * exterior.length
        ):
            continue
        neighbours = lithology.iloc[
            lithology.sindex.query(geometry.buffer(0.5), predicate="intersects")
        ]
        neighbours = neighbours.loc[neighbours.feature_id != row.feature_id]
        if neighbours.empty:
            continue
        shares = {
            code: exterior.intersection(buffered_group(group, neighbour_buffers)).length
            for code, group in neighbours.groupby("geo_sym")
        }
        host = max(shares, key=shares.get)
        ratio = min(1.0, shares[host] / exterior.length)
        if ratio < parameters.get("dominant_boundary_min", 0.90) or host == row.geo_sym:
            continue
        kind = relation(units.get(row.geo_sym, {}), units.get(host, {}))
        if kind is None:
            continue
        host_rows = neighbours.loc[neighbours.geo_sym == host]
        host_area = float(host_rows.geometry.area.sum())
        fraction = geometry.area / max(geometry.area + host_area, 1)
        if fraction > parameters.get("max_local_area_fraction", 0.30):
            continue
        same = same_units[row.geo_sym]
        same = same.loc[same.feature_id != row.feature_id]
        nearest = float(same.geometry.distance(geometry).min()) if len(same) else None
        if nearest is not None and nearest < parameters.get("same_unit_support_m", 100):
            continue
        yield (
            row,
            host,
            {
                "context_relation": kind,
                "area_m2": float(geometry.area),
                "shared_boundary_ratio": ratio,
                "host_code": host,
                "host_feature_ids": sorted(host_rows.feature_id.tolist()),
                "local_host_area_m2": host_area,
                "local_area_fraction": fraction,
                "nearest_same_unit_m": nearest,
                "fault_distance_m": float(geometry.distance(fault_union))
                if not fault_union.is_empty
                else None,
                "fault_crosses_interior": bool(
                    geometry.buffer(-1).intersects(fault_union)
                ),
                "geological_exception_review_required": True,
            },
        )


WHOLE_FEATURE_STRATEGY = "whole-feature-shape-v2"
WHOLE_FEATURE_PARAMETERS = {
    "max_area_km2": 12,
    "dominant_boundary_min": 0.98,
    "max_local_area_fraction": 0.50,
    "same_unit_support_m": 100,
    "same_unit_support_radius_ratio": 0.80,
    "min_hull_fill_ratio": 0.76,
    "min_compactness": 0.24,
    "shape_simplify_radius_ratio": 0.035,
    "strong_contact_min": 0.995,
    "strong_hull_fill_min": 0.85,
    "strong_compactness_min": 0.50,
    "fault_contact_radius_ratio": 0.05,
    "max_aligned_fault_contact_ratio": 0.25,
    "study_edge_tolerance_m": 0.5,
    "max_study_edge_contact_ratio": 0.01,
}


def whole_feature_parameters(parameters):
    limits = WHOLE_FEATURE_PARAMETERS | {
        key: parameters[key] for key in WHOLE_FEATURE_PARAMETERS if key in parameters
    }
    for key, value in limits.items():
        upper = (
            math.inf
            if key in {"max_area_km2", "same_unit_support_m", "study_edge_tolerance_m"}
            else 1.0
        )
        if (
            type(value) not in {float, int}
            or not math.isfinite(value)
            or not 0 < value <= upper
        ):
            raise ValueError(f"L-08 的空间判读参数不合法：{key}")
    if any(
        limits[strong] < limits[baseline]
        for strong, baseline in (
            ("strong_contact_min", "dominant_boundary_min"),
            ("strong_hull_fill_min", "min_hull_fill_ratio"),
            ("strong_compactness_min", "min_compactness"),
        )
    ):
        raise ValueError("L-08 的强形态证据阈值不能低于基本阈值")
    return limits


def dominant_shared_host(lithology, row, exterior):
    """Return a uniquely dominant actual contact, not a point or buffered overlap."""
    contacts, neighbours = defaultdict(list), defaultdict(list)
    for _, other in lithology.iloc[
        lithology.sindex.query(row.geometry, predicate="intersects")
    ].iterrows():
        if other.feature_id == row.feature_id:
            continue
        if row.geometry.intersection(other.geometry).area > 0.01:
            return None
        if not isinstance(other.geo_sym, str) or not other.geo_sym.strip():
            continue
        shared = exterior.intersection(other.geometry.boundary)
        if shared.length > 0:
            contacts[other.geo_sym].append(shared)
            neighbours[other.geo_sym].append(other)
    shares = sorted(
        ((unary_union(parts).length, code) for code, parts in contacts.items()),
        reverse=True,
    )
    if not shares or (len(shares) > 1 and math.isclose(shares[0][0], shares[1][0])):
        return None
    shared, code = shares[0]
    return code, min(1.0, shared / exterior.length), neighbours[code]


def whole_feature_candidates(
    lithology, faults, area, units, parameters, represented=()
):
    """One whole-feature review candidate per enclosed polygon with convergent evidence.

    A nearby separated occurrence is weaker evidence of continuity than an actual
    shared edge. It can be outweighed by a nearly closed contact and compact shape,
    but the mandatory same-unit support distance and mapped fault screen still hold.
    Simplification is used to measure shape only; it never edits or clips a geometry.
    """
    limits = whole_feature_parameters(parameters)
    represented = set(represented)
    study_edge = area.boundary.buffer(limits["study_edge_tolerance_m"])
    fault_union = unary_union(faults.geometry)
    same_units = {code: group for code, group in lithology.groupby("geo_sym")}
    for _, row in lithology.iterrows():
        geometry = row.geometry
        if (
            row.feature_id in represented
            or not isinstance(row.geo_sym, str)
            or not row.geo_sym.strip()
            or not 0 < geometry.area <= limits["max_area_km2"] * 1e6
        ):
            continue
        parts = list(getattr(geometry, "geoms", [geometry]))
        if len(parts) != 1 or parts[0].geom_type != "Polygon":
            continue
        exterior = parts[0].exterior
        if exterior.intersection(study_edge).length > (
            limits["max_study_edge_contact_ratio"] * exterior.length
        ):
            continue
        contact = dominant_shared_host(lithology, row, exterior)
        if not contact:
            continue
        host, ratio, host_rows = contact
        if host == row.geo_sym or ratio < limits["dominant_boundary_min"]:
            continue
        host_area = sum(other.geometry.area for other in host_rows)
        fraction = geometry.area / (geometry.area + host_area)
        if fraction > limits["max_local_area_fraction"]:
            continue
        hull_fill = geometry.area / geometry.convex_hull.area
        if hull_fill < limits["min_hull_fill_ratio"]:
            continue
        radius = math.sqrt(geometry.area / math.pi)
        measured_shape = geometry.simplify(
            limits["shape_simplify_radius_ratio"] * radius, preserve_topology=True
        )
        compactness = 4 * math.pi * measured_shape.area / measured_shape.length**2
        if compactness < limits["min_compactness"]:
            continue
        same = same_units[row.geo_sym]
        peers = same.loc[same.feature_id != row.feature_id]
        nearest = float(peers.geometry.distance(geometry).min()) if len(peers) else None
        if nearest is not None and nearest < limits["same_unit_support_m"]:
            continue
        if (
            nearest is None
            or nearest >= limits["same_unit_support_radius_ratio"] * radius
        ):
            evidence = "isolated_same_unit"
        elif (
            ratio >= limits["strong_contact_min"]
            and hull_fill >= limits["strong_hull_fill_min"]
            and compactness >= limits["strong_compactness_min"]
        ):
            evidence = "closed_compact_contact"
        else:
            continue
        fault_distance = (
            None if fault_union.is_empty else geometry.distance(fault_union)
        )
        fault_buffer = limits["fault_contact_radius_ratio"] * radius
        aligned = (
            exterior.intersection(fault_union.buffer(fault_buffer)).length
            / exterior.length
            if fault_distance is not None and fault_distance < fault_buffer
            else 0.0
        )
        if aligned >= limits["max_aligned_fault_contact_ratio"]:
            continue
        yield (
            row,
            host,
            {
                "context_strategy": WHOLE_FEATURE_STRATEGY,
                "context_evidence": evidence,
                "context_relation": relation(
                    units.get(row.geo_sym, {}), units.get(host, {})
                ),
                "observed_code": row.geo_sym,
                "host_code": host,
                "host_feature_ids": sorted(other.feature_id for other in host_rows),
                "area_m2": float(geometry.area),
                "shared_boundary_ratio": ratio,
                "local_host_area_m2": host_area,
                "local_area_fraction": fraction,
                "hull_fill_ratio": hull_fill,
                "compactness": compactness,
                "nearest_same_unit_m": nearest,
                "equivalent_radius_m": radius,
                "fault_distance_m": fault_distance,
                "aligned_fault_contact_ratio": aligned,
                "fault_crosses_interior": bool(
                    geometry.buffer(-1).intersects(fault_union)
                ),
                "geological_exception_review_required": True,
            },
        )
