"""Prepare a same-unit cartographic split using runtime data only.

The retained parent and preparation mapping are private evaluation material.
No geological class or field-observation evidence is manufactured.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString
from shapely.ops import split, unary_union

from geology_multi_evaluation_data import sha256, write_json


def candidate_split(geometry: object, vertical: bool) -> tuple | None:
    x0, y0, x1, y1 = geometry.bounds
    width, height = x1 - x0, y1 - y0
    step = min(60.0, max(width, height) / 24)
    coordinates = []
    for index in range(33):
        fraction = (index - 4) / 24
        offset = (1 if index % 4 < 2 else -1) * step
        if vertical:
            point = ((x0 + x1) / 2 + offset, y0 + height * fraction)
        else:
            point = (x0 + width * fraction, (y0 + y1) / 2 + offset)
        coordinates.append(point)
    parts = list(split(geometry, LineString(coordinates)).geoms)
    if len(parts) != 2 or any(
        part.geom_type != "Polygon" or not part.is_valid for part in parts
    ):
        return None
    if min(part.area for part in parts) < geometry.area * 0.25:
        return None
    shared = parts[0].boundary.intersection(parts[1].boundary)
    if shared.length <= 100:
        return None
    combined = unary_union(parts)
    if combined.symmetric_difference(geometry).area > 0.00001:
        return None
    return parts[0], parts[1], shared


def prepare(inputs: Path, output: Path) -> dict:
    inputs, output = inputs.resolve(), output.resolve()
    if output == inputs or inputs in output.parents:
        raise ValueError("Prepared case must be separate from existing runtime inputs")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty output directory")
    lithology = gpd.read_file(inputs / "lithology.gpkg").to_crs(32646)
    faults = gpd.read_file(inputs / "faults.gpkg").to_crs(32646)
    if not {"feature_id", "name", "geo_sym", "conf"} <= set(lithology):
        raise ValueError("Runtime lithology fields are incomplete")
    # Frozen aliases are already a normal knowledge input, never an answer key.
    import sys

    core = Path(__file__).resolve().parents[1] / "examples/compute/geology-multi-core"
    sys.path.insert(0, str(core))
    from multi_io import rules

    _, _, aliases = rules(inputs / "rules.csv")
    fault_union = unary_union(faults.geometry)
    candidates = []
    for index, row in lithology.iterrows():
        geometry = row.geometry
        if geometry.geom_type == "MultiPolygon" and len(geometry.geoms) == 1:
            geometry = geometry.geoms[0]
        if (
            geometry.geom_type != "Polygon"
            or not geometry.is_valid
            or not 0.5e6 <= geometry.area <= 8e6
            or float(row.conf) < 0.9
            or aliases.get(row["name"]) != row.geo_sym
        ):
            continue
        for vertical in (True, False):
            parts = candidate_split(geometry, vertical)
            if parts is None:
                continue
            first, second, shared = parts
            distance = shared.distance(fault_union)
            if not fault_union.is_empty and distance <= 100:
                continue
            candidates.append(
                (
                    abs(geometry.area - 2e6),
                    row.feature_id,
                    index,
                    first,
                    second,
                    shared,
                    distance,
                )
            )
    if not candidates:
        raise ValueError(
            "No suitable self-consistent runtime polygon can be split safely"
        )
    _, _, index, first, second, shared, distance = min(
        candidates, key=lambda row: row[:2]
    )
    selected = lithology.loc[index]
    output.mkdir(parents=True, exist_ok=True)
    runtime, private = output / "runtime", output / "private"
    runtime.mkdir()
    private.mkdir()
    lithology.to_file(
        private / "input-before-cartographic-preparation.gpkg",
        layer="data",
        index=False,
    )
    lithology.loc[[index]].to_file(
        private / "retained-parent.gpkg", layer="data", index=False
    )
    existing = set(lithology.feature_id.astype(str))
    identifiers = []
    for part_index in range(2):
        number = len(lithology) + part_index + 1
        while f"G-{number:05d}" in existing:
            number += 1
        identifier = f"G-{number:05d}"
        existing.add(identifier)
        identifiers.append(identifier)
    replacements = []
    for identifier, geometry in zip(identifiers, (first, second), strict=True):
        replacement = selected.copy()
        replacement["feature_id"], replacement["geometry"] = identifier, geometry
        replacements.append(replacement)
    import pandas as pd

    prepared = gpd.GeoDataFrame(
        pd.concat(
            [
                lithology.drop(index=index),
                gpd.GeoDataFrame(replacements, crs=lithology.crs),
            ],
            ignore_index=True,
        ),
        geometry="geometry",
        crs=lithology.crs,
    )
    if set(prepared) != set(lithology):
        raise AssertionError("Preparation added a hidden runtime label")
    if not prepared.geometry.is_valid.all():
        raise AssertionError("Preparation produced invalid geometry")
    prepared.to_file(runtime / "lithology.gpkg", layer="data", index=False)
    coverage_error = (
        unary_union(lithology.geometry)
        .symmetric_difference(unary_union(prepared.geometry))
        .area
    )
    if coverage_error > 0.01:
        raise AssertionError("Prepared case changed the outer coverage")
    manifest = {
        "schemaVersion": 1,
        "caseLabel": "演示整理副本",
        "description": "将一个现有同类图斑分成属性一致的相邻两面，用于演示经批准去除冗余内部边界。地质类别保持。",
        "selectionInputs": [
            "runtime/lithology.gpkg",
            "runtime/faults.gpkg",
            "runtime/rules.csv",
        ],
        "selectionUsedIndependentReference": False,
        "runtimeFile": "runtime/lithology.gpkg",
        "runtimeSha256": sha256(runtime / "lithology.gpkg"),
        "runtimeFields": list(prepared),
        "sourceCount": len(lithology),
        "preparedCount": len(prepared),
        "sourceParentId": str(selected.feature_id),
        "preparedIds": identifiers,
        "unitName": str(selected["name"]),
        "unitCode": str(selected.geo_sym),
        "simulationConfidence": float(selected.conf),
        "parentAreaM2": float(selected.geometry.area),
        "partAreasM2": [float(first.area), float(second.area)],
        "sharedBoundaryM": float(shared.length),
        "sharedBoundaryFaultDistanceM": float(distance),
        "coverageSymmetricDifferenceM2": float(coverage_error),
        "sourceFingerprints": {
            path.name: sha256(path)
            for path in sorted(inputs.iterdir())
            if path.is_file()
        },
        "sourceParentGeometrySha256": __import__("hashlib")
        .sha256(selected.geometry.wkb)
        .hexdigest(),
        "privateReference": "private/input-before-cartographic-preparation.gpkg",
        "privateReferencePurpose": "准备与独立验收，不登记运行资源、不传给模型、知识检索或正常算法。",
    }
    write_json(private / "preparation-manifest.json", manifest)
    # No parent ID or inverse mapping in the normal input manifest.
    public = {
        key: value
        for key, value in manifest.items()
        if key
        not in {
            "sourceParentId",
            "preparedIds",
            "sourceParentGeometrySha256",
            "privateReference",
        }
    }
    write_json(output / "runtime-manifest.json", public)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    manifest = prepare(arguments.inputs, arguments.output)
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "caseLabel",
                    "runtimeFile",
                    "sourceCount",
                    "preparedCount",
                    "preparedIds",
                    "unitName",
                    "unitCode",
                    "parentAreaM2",
                    "partAreasM2",
                    "sharedBoundaryM",
                    "sharedBoundaryFaultDistanceM",
                    "coverageSymmetricDifferenceM2",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
