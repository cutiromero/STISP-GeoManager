"""Read each corrected mineral once; retain weighted neighbourhood presence grids."""

from contextlib import ExitStack
import math
from pathlib import Path
from tempfile import TemporaryDirectory

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject
from scipy.ndimage import maximum_filter1d

from multi_io import RASTERS
from multi_raster import open_weights, read_raw, read_weights
from multi_windows import GDAL_CACHE_MB, create, windows

METHOD = "weighted_neighborhood_presence_v2"


def circular_maximum(values, distance, resolution):
    """Circular grid-centre neighbourhood, with O(radius * cells) work."""
    radius = min(math.floor(distance / resolution), max(values.shape) - 1)
    result = np.zeros_like(values)
    for dy in range(
        -min(radius, values.shape[0] - 1), min(radius, values.shape[0] - 1) + 1
    ):
        dx = min(
            math.floor(
                math.sqrt(max(0, distance**2 - (dy * resolution) ** 2)) / resolution
            ),
            values.shape[1] - 1,
        )
        horizontal = maximum_filter1d(
            values, size=2 * dx + 1, axis=1, mode="constant", cval=0
        )
        if dy < 0:
            result[:dy] = np.maximum(result[:dy], horizontal[-dy:])
        elif dy > 0:
            result[dy:] = np.maximum(result[dy:], horizontal[:-dy])
        else:
            np.maximum(result, horizontal, out=result)
    return result


def mineral_grids(alterations, transform, dimensions, config, parameters):
    allowed = parameters.get("alteration_types", list(RASTERS.values()))
    minimum, distance = parameters.get("min_types", 2), parameters.get("search_m", 250)
    if parameters.get("evidence_method") != METHOD:
        raise ValueError("远景区2.0需要显式绑定邻域矿物组合规则P-02，请更新项目规则")
    if (
        not isinstance(allowed, list)
        or not allowed
        or len(set(allowed)) != len(allowed)
        or not set(allowed) <= set(RASTERS.values())
        or type(minimum) not in (int, float)
        or not math.isfinite(minimum)
        or not 0 < minimum <= len(allowed)
        or type(distance) not in (int, float)
        or not math.isfinite(distance)
        or not 0 <= distance <= 5000
    ):
        raise ValueError("P-02矿物清单、加权类型数或搜索距离无效")
    result = {}
    with rasterio.Env(GDAL_CACHEMAX=GDAL_CACHE_MB * 1024 * 1024):
        for mineral, name in RASTERS.items():
            if name not in allowed:
                continue
            with ExitStack() as stack:
                source = stack.enter_context(
                    rasterio.open(alterations.context.input_path(mineral))
                )
                weights = open_weights(alterations.context, mineral, source, stack)
                area = (
                    gpd.GeoSeries([alterations.area], crs=config["working_epsg"])
                    .to_crs(source.crs)
                    .iloc[0]
                )
                directory = stack.enter_context(
                    TemporaryDirectory(
                        prefix=".prospect-",
                        dir=Path(
                            alterations.context.output_path("evidence.csv")
                        ).parent,
                    )
                )
                path = Path(directory) / "weighted.tif"
                with create(path, source.profile, "float64") as target:
                    for window in windows(source.profile):
                        raw = read_raw(source, window, area)
                        target.write(
                            raw * read_weights(weights, window, raw.shape),
                            1,
                            window=window,
                        )
                presence = np.zeros(dimensions, dtype="float64")
                with rasterio.open(path) as evidence:
                    reproject(
                        rasterio.band(evidence, 1),
                        presence,
                        src_transform=source.transform,
                        src_crs=source.crs,
                        dst_transform=transform,
                        dst_crs=config["working_epsg"],
                        resampling=Resampling.max,
                        warp_mem_limit=GDAL_CACHE_MB,
                    )
                result[name] = circular_maximum(
                    presence, distance, config["grid_resolution_m"]
                )
    return result
