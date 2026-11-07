"""Continuous corrected-data evidence fields; each mineral is read only once."""

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject
from scipy.ndimage import distance_transform_edt, gaussian_filter

from multi_io import RASTERS
from multi_prospect import burn, grid
from multi_prospect_raster import circular_maximum
from multi_raster import burn as raster_burn, open_weights, read_weights, window_profile
from multi_windows import GDAL_CACHE_MB, create, windows

PROFILES = {
    "focused": {
        "label": "收敛",
        "context_radius_m": 600,
        "fault_scale_factor": 1.6,
        "growth_threshold": 0.55,
        "max_zone_area_km2": 15,
        "max_zone_count": 8,
    },
    "balanced": {
        "label": "均衡",
        "context_radius_m": 800,
        "fault_scale_factor": 2.0,
        "growth_threshold": 0.49,
        "max_zone_area_km2": 20,
        "max_zone_count": 10,
    },
    "regional": {
        "label": "扩展",
        "context_radius_m": 1000,
        "fault_scale_factor": 2.4,
        "growth_threshold": 0.43,
        "max_zone_area_km2": 30,
        "max_zone_count": 12,
    },
}


def raster_evidence(context, area, config, transform, dimensions):
    """Independent support, area fraction and observation masks on one common grid."""
    result = {}
    with rasterio.Env(GDAL_CACHEMAX=GDAL_CACHE_MB * 1024**2):
        for key, name in RASTERS.items():
            with ExitStack() as stack:
                source = stack.enter_context(rasterio.open(context.input_path(key)))
                if source.crs is None or source.count != 1:
                    raise ValueError("矿物证据必须为有坐标系的单波段0/1栅格")
                weight = open_weights(context, key, source, stack)
                source_area = (
                    gpd.GeoSeries([area], crs=config["working_epsg"])
                    .to_crs(source.crs)
                    .iloc[0]
                )
                temporary = stack.enter_context(
                    TemporaryDirectory(
                        prefix=".region-evidence-",
                        dir=Path(context.output_path("evidence.csv")).parent,
                    )
                )
                path = Path(temporary) / "evidence.tif"
                with create(path, source.profile, "float64", count=2) as dst:
                    for window in windows(source.profile):
                        values = source.read(1, window=window, masked=True)
                        domain = (
                            raster_burn(
                                [(source_area, 1)],
                                window_profile(source, window),
                                dtype="uint8",
                            )
                            > 0
                        )
                        valid = ~np.ma.getmaskarray(values) & domain
                        if not np.isin(values.data[valid], [0, 1]).all():
                            raise ValueError("矿物识别数据必须为0/1")
                        weighted = ((values.data == 1) & valid) * read_weights(
                            weight, window, values.shape
                        )
                        dst.write(weighted, 1, window=window)
                        dst.write(valid.astype("float64"), 2, window=window)
                projected = {}
                with rasterio.open(path) as stream:
                    for field, band, method in [
                        ("presence", 1, Resampling.max),
                        ("fraction", 1, Resampling.average),
                        ("valid", 2, Resampling.average),
                    ]:
                        data = np.zeros(dimensions, dtype="float64")
                        reproject(
                            rasterio.band(stream, band),
                            data,
                            src_transform=stream.transform,
                            src_crs=stream.crs,
                            dst_transform=transform,
                            dst_crs=config["working_epsg"],
                            resampling=method,
                            warp_mem_limit=GDAL_CACHE_MB,
                        )
                        projected[field] = data
                result[name] = projected
    return result


def distance_support(geometries, weights, transform, dimensions, resolution, scale):
    support = np.zeros(dimensions, dtype="float64")
    if not geometries:
        return support
    for weight in sorted(set(weights)):
        if weight <= 0:
            continue
        active = [
            geometry for geometry, value in zip(geometries, weights) if value == weight
        ]
        cells = burn(active, transform, dimensions) > 0
        if not cells.any():
            continue
        distances = distance_transform_edt(~cells, sampling=resolution)
        np.maximum(
            support, weight * np.exp(-0.5 * (distances / scale) ** 2), out=support
        )
    return support


def base_fields(context, lithology, faults, intersections, area, rules, units, config):
    transform, dimensions = grid(area, config)
    resolution = config["grid_resolution_m"]
    masks = {}
    masks["area"] = burn([area], transform, dimensions) > 0
    for name, predicate in [
        ("bedrock", lambda unit: unit.get("category") in {"stratum", "intrusive"}),
        ("favourable", lambda unit: bool(unit.get("favorable", False))),
    ]:
        geometries = list(
            lithology.loc[
                lithology.geo_sym.map(lambda code: predicate(units.get(code, {}))),
                "geometry",
            ]
        )
        masks[name] = burn(geometries, transform, dimensions) > 0
    evidence = raster_evidence(context, area, config, transform, dimensions)
    observed = sum((item["valid"] >= 0.5).astype("uint8") for item in evidence.values())
    masks["observed"] = observed >= 2
    params = rules["P-01"]["params"]
    entries = {
        "main": ([], [], params.get("buffer_main_m", 500)),
        "secondary": ([], [], params.get("buffer_secondary_m", 250)),
    }
    structural_geometries = []
    structural_weights = []
    active = (
        faults.loc[faults.get("state", "keep") != "exclude"]
        if "state" in faults
        else faults
    )
    for _, row in active.iterrows():
        weight = float(row.get("weight", 1))
        if not np.isfinite(weight) or not 0 <= weight <= 1:
            raise ValueError("构造权重必须在0—1之间")
        key = (
            "main"
            if row.geometry.length >= params.get("main_fault_min_length_m", 10000)
            else "secondary"
        )
        entries[key][0].append(row.geometry)
        entries[key][1].append(weight)
        structural_geometries.append(row.geometry.buffer(entries[key][2]))
        structural_weights.append(weight)
    for _, point in intersections.iterrows():
        distance = (
            params.get("buffer_intersection_other_m", 500)
            if point["type"] == "次级×次级"
            else params.get("buffer_intersection_main_secondary_m", 1000)
        )
        structural_geometries.append(point.geometry.buffer(distance))
        structural_weights.append(float(point.get("weight", 1)))
    masks["core_structure"] = (
        burn(structural_geometries, transform, dimensions, structural_weights) >= 1
    )
    raw = sum(
        (item["fraction"] for item in evidence.values()),
        np.zeros(dimensions, dtype="float64"),
    )
    core_count = sum(
        (
            circular_maximum(
                item["presence"],
                rules["P-02"]["params"].get("search_m", 250),
                resolution,
            )
            for item in evidence.values()
        ),
        np.zeros(dimensions, dtype="float64"),
    )
    masks["core"] = (
        (core_count >= rules["P-02"]["params"].get("min_types", 2))
        & masks["core_structure"]
        & masks["area"]
        & masks["bedrock"]
        & masks["observed"]
    )
    return {
        "transform": transform,
        "dimensions": dimensions,
        "masks": masks,
        "evidence": evidence,
        "core_count": core_count,
        "raw_fraction": raw,
        "fault_entries": entries,
        "intersections": intersections,
        "active_faults": active,
    }


def profile_fields(base, profile, config):
    resolution = config["grid_resolution_m"]
    transform = base["transform"]
    dimensions = base["dimensions"]
    radius = profile["context_radius_m"]
    broad_count = sum(
        (
            circular_maximum(item["presence"], radius, resolution)
            for item in base["evidence"].values()
        ),
        np.zeros(dimensions, dtype="float64"),
    )
    density = gaussian_filter(
        base["raw_fraction"],
        sigma=max(0.5, radius / (2 * resolution)),
        mode="constant",
        truncate=2,
    )
    combination = np.clip((broad_count - 1) / 2, 0, 1)
    density_score = 1 - np.exp(-density / config["alteration_density_scale"])
    alteration = 0.65 * combination + 0.35 * density_score
    structure = np.zeros(dimensions, dtype="float64")
    for geometries, weights, distance in base["fault_entries"].values():
        np.maximum(
            structure,
            distance_support(
                geometries,
                weights,
                transform,
                dimensions,
                resolution,
                distance * profile["fault_scale_factor"],
            ),
            out=structure,
        )
    points = base["intersections"]
    if len(points):
        weights = [
            float(row.get("weight", 1))
            * (0.7 if bool(row.get("inferred", False)) else 1)
            for _, row in points.iterrows()
        ]
        intersection = distance_support(
            list(points.geometry), weights, transform, dimensions, resolution, radius
        )
        structure = np.clip(structure + 0.15 * intersection, 0, 1)
    lithology = np.where(base["masks"]["favourable"], 1.0, 0.45)
    score = gaussian_filter(
        0.45 * alteration + 0.40 * structure + 0.15 * lithology, sigma=1, mode="nearest"
    )
    domain = (
        base["masks"]["area"] & base["masks"]["bedrock"] & base["masks"]["observed"]
    )
    growth = (
        domain
        & (structure >= 0.25)
        & (broad_count >= config["peripheral_min_weighted_types"])
        & (density >= config["peripheral_min_density"])
        & (score >= profile["growth_threshold"])
    )
    return {
        "score": score,
        "structure": structure,
        "alteration": alteration,
        "broad_count": broad_count,
        "density": density,
        "growth": growth,
        "core": base["masks"]["core"] & growth,
    }
