"""Adapt measured continuous regions to the platform's corrected-only protocol."""

import json
from rasterio.features import geometry_mask
from multi_io import dump


def platform_evidence(targets, rows, base, fields, heat, profile, config):
    result = []
    for geometry, original in zip(targets.geometry, rows):
        row = dict(original)
        cells = geometry_mask(
            [geometry],
            out_shape=base["dimensions"],
            transform=base["transform"],
            invert=True,
        ) & (heat != -9999)
        basis = json.loads(row["evidence_json"])
        measured = {
            **basis["measurements"],
            "structure_supported_fraction": float(
                (fields["structure"][cells] >= 0.25).mean()
            ),
            "alteration_supported_fraction": float(
                (
                    (
                        fields["broad_count"][cells]
                        >= config["peripheral_min_weighted_types"]
                    )
                    & (fields["density"][cells] >= config["peripheral_min_density"])
                ).mean()
            ),
            "bedrock_supported_fraction": float(base["masks"]["bedrock"][cells].mean()),
            "min_weighted_type_count": float(fields["broad_count"][cells].min()),
            "mean_weighted_type_count": float(fields["broad_count"][cells].mean()),
            "rule_expression": "strong_core AND connected_smoothed_support AND mapped_bedrock AND observed",
            "core_rule_expression": "weighted_types_250m >= 2 AND original_structure AND mapped_bedrock",
            "evidence_method": "continuous_support_regions_v1",
            "support_smooth_m": config["support_smooth_m"],
        }
        points = []
        for _, point in base["intersections"].iterrows():
            distance = float(point.geometry.distance(geometry))
            if distance <= profile["context_radius_m"]:
                points.append(
                    {
                        "point_id": str(point.point_id),
                        "type": str(point["type"]),
                        "distance_m": distance,
                        "weight": float(point.get("weight", 1)),
                    }
                )
        context = {
            "minerals": row["direct_minerals"],
            "faults": json.loads(row["nearby_faults_json"]),
            "intersections": points,
            "lithology": json.loads(row["lithology_json"]),
        }
        basis.update(
            schema_version=2,
            phase="after",
            conditions=measured,
            context=context,
            knowledge=basis["source_knowledge"],
        )
        row.update(
            schema_version=2,
            phase="after",
            evidence_json=dump(basis),
            alteration=dump(context["minerals"]),
            faults=dump(context["faults"]),
            intersections=dump(points),
            lithology=row["lithology_json"],
            conditions_json=dump(measured),
        )
        result.append(row)
    if result:
        targets = targets.copy()
        targets["evidence_json"] = [row["evidence_json"] for row in result]
    return targets, result
