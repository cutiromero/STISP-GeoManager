"""Independent synthetic fixtures; never imported by normal workers or agents."""

from __future__ import annotations

import ast
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, nearest_points, substring, unary_union

GENERATOR_FUNCTIONS = {
    "unit_attr",
    "random_point_in",
    "blob",
    "largest_part",
    "simulate_lithology",
    "simulate_faults",
}
GENERATOR_CONSTANTS = {
    "LITHO_INJECTION",
    "N_ATTRIBUTE_ERRORS",
    "PATCH_RADIUS",
    "PLACEMENT_MODES",
    "CONF_TRUE",
    "CONF_INJECTED",
    "FAULT_INJECTION",
}
LITHOLOGY_FIELDS = ["feature_id", "name", "geo_sym", "conf", "confidence_kind"]
LABEL_FIELDS = {"inj_id", "inj_type", "fake_type", "truth", "expected_label"}
FAKE_RULES = {
    "valley": "S-01",
    "boundary": "S-02",
    "short": "S-03",
    "zigzag": "S-04",
    "plausible": "S-UNSUPPORTED",
}


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def pure_generators(path: Path) -> SimpleNamespace:
    """Select only reviewed definitions; original module top-level never runs."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    nodes = []
    constants = set()
    functions = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in GENERATOR_CONSTANTS:
                ast.literal_eval(node.value)  # Reject calls and executable expressions.
                nodes.append(node)
                constants.add(target.id)
        elif isinstance(node, ast.FunctionDef) and node.name in GENERATOR_FUNCTIONS:
            if node.decorator_list or node.args.defaults or node.args.kw_defaults:
                # random_point_in has a literal default, checked separately below.
                defaults = node.args.defaults + [
                    item for item in node.args.kw_defaults if item is not None
                ]
                if node.decorator_list:
                    raise ValueError("Generator decorators are not allowed")
                for value in defaults:
                    ast.literal_eval(value)
            nodes.append(node)
            functions.add(node.name)
    if constants != GENERATOR_CONSTANTS or functions != GENERATOR_FUNCTIONS:
        raise ValueError("Delivery generator shape changed; review before running")
    namespace = {
        "math": math,
        "np": np,
        "pd": pd,
        "gpd": gpd,
        "LineString": LineString,
        "Point": Point,
        "Polygon": Polygon,
        "unary_union": unary_union,
        "linemerge": linemerge,
        "substring": substring,
        "nearest_points": nearest_points,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return SimpleNamespace(**namespace)


def source_fingerprints(source: Path) -> dict[str, str]:
    result = {}
    for line in (source / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        expected, relative = line.split(None, 1)
        relative = relative.strip()
        path = (source / relative).resolve()
        if source not in path.parents or sha256(path) != expected:
            raise ValueError("Original delivery checksum mismatch: " + relative)
        result[relative] = expected
    return result


def reference_maps(source: Path) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, object]:
    lithology = gpd.read_file(source / "data/海德乌拉.shp").to_crs(32646)
    lithology = lithology[["name", "geo_sym", "geo_tex", "geo_unit", "geometry"]]
    area = unary_union(lithology.geometry)
    faults = gpd.read_file(source / "data/构造/示范区构造解译0404.shp").to_crs(32646)
    faults = gpd.clip(faults, area).explode(index_parts=False).reset_index(drop=True)
    faults = faults.loc[faults.geometry.length > 10, ["geometry"]].reset_index(
        drop=True
    )
    return lithology, faults, area


def neutral_ids(frame: gpd.GeoDataFrame, prefix: str) -> gpd.GeoDataFrame:
    order = sorted(
        range(len(frame)),
        key=lambda index: hashlib.sha256(frame.geometry.iloc[index].wkb).digest(),
    )
    result = frame.iloc[order].reset_index(drop=True)
    result["_neutral"] = [f"{prefix}-{index + 1:05d}" for index in range(len(result))]
    return result


def prepare_dataset(
    directory: Path,
    seed: int,
    generators: SimpleNamespace,
    reference: gpd.GeoDataFrame,
    faults: gpd.GeoDataFrame,
    units: dict,
) -> dict:
    """Labels and reference go only into private/, normal inputs into runtime/."""
    private, runtime = directory / "private", directory / "runtime"
    private.mkdir(parents=True)
    runtime.mkdir()
    rng = np.random.default_rng(seed)
    simulated, injected = generators.simulate_lithology(reference, faults, units, rng)
    simulated_faults = generators.simulate_faults(faults, reference, units, rng)
    simulated = neutral_ids(simulated, "G")
    simulated_faults = neutral_ids(simulated_faults, "F")
    labels = {
        "lithology": {
            row["_neutral"]: str(row.inj_type)
            for _, row in simulated.iterrows()
            if row.inj_type
        },
        "structure": {
            row["_neutral"]: FAKE_RULES[str(row.fake_type)]
            for _, row in simulated_faults.iterrows()
            if row.fake_type
        },
    }
    write_json(private / "labels.json", labels)
    simulated.drop(columns="geometry").to_json(
        private / "preparation-mapping.json", orient="records", force_ascii=False
    )
    simulated_faults.drop(columns="geometry").to_json(
        private / "structure-mapping.json", orient="records", force_ascii=False
    )
    reference.to_file(private / "reference.gpkg", layer="data", index=False)
    injected.to_file(private / "injected-locations.gpkg", layer="data", index=False)
    clean = simulated.rename(columns={"_neutral": "feature_id"})
    clean["confidence_kind"] = "模拟分类置信度"
    clean = clean[LITHOLOGY_FIELDS + ["geometry"]].copy()
    clean_faults = simulated_faults[["_neutral", "geometry"]].rename(
        columns={"_neutral": "line_id"}
    )
    if LABEL_FIELDS & (set(clean) | set(clean_faults)):
        raise ValueError("Evaluation labels leaked into normal inputs")
    clean.to_file(runtime / "lithology.gpkg", layer="data", index=False)
    clean_faults.to_file(runtime / "faults.gpkg", layer="data", index=False)
    coverage = gpd.GeoDataFrame(
        {"role": ["complete"]}, geometry=[unary_union(clean.geometry)], crs=32646
    )
    coverage.to_file(runtime / "coverage.gpkg", layer="data", index=False)
    manifest = {
        "seed": seed,
        "lithologyCount": len(clean),
        "faultCount": len(clean_faults),
        "lithologyFields": list(clean),
        "faultFields": list(clean_faults),
        "runtimeFiles": {
            name: sha256(runtime / name)
            for name in ("lithology.gpkg", "faults.gpkg", "coverage.gpkg")
        },
        "privateLabelsExcludedFromNormalInputs": True,
        "sharedRegionalBase": True,
        "scope": "同一示范区，不同随机种子的模拟错误；不是独立地区或野外验证。",
    }
    write_json(directory / "fixture-manifest.json", manifest)
    return manifest
