"""Case-specific alluvium morphology measurements, never reference-map labels."""

import math

from shapely.geometry import LineString
from shapely.ops import unary_union


def shape_candidates(lithology, units, rule):
    params = rule["params"]
    sources = params.get("source_codes", ["Qhᵃˡ"])
    for index, row in lithology.iterrows():
        if row.geo_sym not in sources:
            continue
        geometry = row.geometry
        compactness = 4 * math.pi * geometry.area / geometry.length**2
        rectangle = geometry.minimum_rotated_rectangle
        coordinates = list(rectangle.exterior.coords)
        lengths = [
            LineString([coordinates[position], coordinates[position + 1]]).length
            for position in range(4)
        ]
        aspect = max(lengths) / min(lengths)
        if compactness < params.get("compactness_min", 0.6) or aspect >= params.get(
            "aspect_ratio_max", 1.5
        ):
            continue
        neighbours = lithology.iloc[
            lithology.sindex.query(geometry.buffer(0.5), predicate="intersects")
        ]
        neighbours = neighbours.loc[neighbours.feature_id != row.feature_id]
        age = units.get(row.geo_sym, {}).get("age_ma")
        older = neighbours.loc[
            neighbours.geo_sym.map(
                lambda code: (
                    age is not None
                    and units.get(code, {}).get("age_ma", -1) > age
                    and units.get(code, {}).get("category")
                    in params.get("host_categories", ["cover"])
                )
            )
        ]
        shares = {
            code: geometry.boundary.intersection(
                unary_union(group.geometry).buffer(0.5)
            ).length
            for code, group in older.groupby("geo_sym")
        }
        if not shares:
            continue
        host = max(shares, key=lambda code: (shares[code], code))
        if shares[host] <= 0:
            continue
        yield (
            index,
            host,
            {
                "area_m2": float(geometry.area),
                "compactness": float(compactness),
                "aspect_ratio": float(aspect),
                "shared_boundary_ratio": min(
                    1.0, float(shares[host] / geometry.length)
                ),
                "host_code": host,
                "host_feature_ids": sorted(
                    older.loc[older.geo_sym == host, "feature_id"].tolist()
                ),
                "same_unit_neighbour_count": int(
                    sum(neighbours.geo_sym == row.geo_sym)
                ),
            },
        )


def continuity_candidates(lithology, units, rule):
    params = rule["params"]
    for index, row in lithology.iterrows():
        unit = units.get(row.geo_sym, {})
        if unit.get("category") not in params.get(
            "categories", ["stratum", "intrusive"]
        ):
            continue
        confidence = row.get("conf")
        if (
            confidence is None
            or not math.isfinite(float(confidence))
            or float(confidence) >= params.get("conf_max", 0.6)
        ):
            continue
        geometry = row.geometry
        if geometry.area > params.get("max_area_km2", 3) * 1e6:
            continue
        compactness = 4 * math.pi * geometry.area / geometry.length**2
        coords = list(geometry.minimum_rotated_rectangle.exterior.coords)
        sides = [
            LineString(coords[position : position + 2]).length for position in range(4)
        ]
        aspect = max(sides) / min(sides)
        if compactness < params.get("compactness_min", 0.3) or aspect >= params.get(
            "aspect_ratio_max", 1.5
        ):
            continue
        neighbours = lithology.iloc[
            lithology.sindex.query(geometry.buffer(0.5), predicate="intersects")
        ]
        neighbours = neighbours.loc[neighbours.feature_id != row.feature_id]
        if any(neighbours.geo_sym == row.geo_sym):
            continue
        exterior = unary_union(
            [
                LineString(part.exterior.coords)
                for part in getattr(geometry, "geoms", [geometry])
            ]
        )
        shares = {
            code: exterior.intersection(unary_union(group.geometry).buffer(0.5)).length
            for code, group in neighbours.groupby("geo_sym")
        }
        if not shares:
            continue
        host = max(shares, key=lambda code: (shares[code], code))
        host_unit = units.get(host, {})
        ratio = min(1.0, shares[host] / exterior.length)
        if (
            host_unit.get("category") != unit["category"]
            or unit.get("age_ma") is None
            or host_unit.get("age_ma") is None
            or unit["age_ma"] <= host_unit["age_ma"]
            or ratio < params.get("dominant_boundary_min", 0.6)
        ):
            continue
        same = lithology.loc[
            (lithology.geo_sym == row.geo_sym)
            & (lithology.feature_id != row.feature_id)
        ]
        yield (
            index,
            host,
            {
                "area_m2": float(geometry.area),
                "compactness": compactness,
                "aspect_ratio": aspect,
                "shared_boundary_ratio": ratio,
                "same_unit_neighbour_count": 0,
                "nearest_same_unit_m": float(same.distance(geometry).min())
                if len(same)
                else None,
                "host_code": host,
                "age_ma": unit["age_ma"],
                "host_age_ma": host_unit["age_ma"],
                "simulation_confidence": float(confidence),
            },
        )
