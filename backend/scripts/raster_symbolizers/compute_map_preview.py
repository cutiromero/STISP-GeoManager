#!/usr/bin/env python
"""Fixed, bounded WGS84 first-band rendering; JSON on stdin and stdout."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys

os.environ["GDAL_PAM_ENABLED"] = "NO"

import numpy as np
from PIL import Image
import rasterio
from rasterio.enums import ColorInterp, Resampling
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform, transform, transform_bounds


MAX_SIDE = 1024
MAX_MAP_LATITUDE = 85.051129
BLUE_PALETTE = np.array([[219, 237, 247], [79, 149, 205], [17, 64, 124]])


class PreviewError(ValueError):
    pass


def geographic_bounds(src) -> tuple[float, float, float, float]:
    if src.crs is None:
        raise PreviewError("计算结果缺少有效坐标系，无法定位到地图")
    raw = src.bounds
    if not all(math.isfinite(value) for value in raw) or not (
        raw.left < raw.right and raw.bottom < raw.top
    ):
        raise PreviewError("计算结果空间范围无效，无法定位到地图")
    # Densify every edge to detect wraparound instead of displaying it globally.
    xs, ys = [], []
    for fraction in np.linspace(0, 1, 23):
        x = raw.left + (raw.right - raw.left) * fraction
        y = raw.bottom + (raw.top - raw.bottom) * fraction
        xs.extend([x, x, raw.left, raw.right])
        ys.extend([raw.bottom, raw.top, y, y])
    try:
        longitudes, latitudes = transform(src.crs, "EPSG:4326", xs, ys)
        bounds = transform_bounds(src.crs, "EPSG:4326", *raw, densify_pts=21)
    except Exception as exc:
        raise PreviewError("计算结果坐标系无法转换到地图坐标") from exc
    if not all(math.isfinite(value) for value in [*bounds, *longitudes, *latitudes]):
        raise PreviewError("计算结果坐标系无法转换到地图坐标")
    west, south, east, north = bounds
    if (
        not -180 <= west < east <= 180
        or east - west > 180
        or min(longitudes) < -180
        or max(longitudes) > 180
        or max(longitudes) - min(longitudes) > 180
    ):
        raise PreviewError("跨越日期变更线或超过半球的结果暂不支持地图预览")
    if not (
        -MAX_MAP_LATITUDE <= south < north <= MAX_MAP_LATITUDE
        and all(-MAX_MAP_LATITUDE <= value <= MAX_MAP_LATITUDE for value in latitudes)
    ):
        raise PreviewError("该结果超出地图支持的纬度范围，暂不能预览")
    return bounds


def colorize(data, fixed_range=None) -> np.ndarray:
    masked = np.ma.masked_invalid(data.astype(np.float32))
    valid = ~np.ma.getmaskarray(masked)
    image = np.zeros((*masked.shape, 4), dtype=np.uint8)
    if not valid.any():
        return image
    values = masked.filled(0)
    if fixed_range is None:
        minimum, maximum = np.percentile(masked.compressed(), [2, 98])
    else:
        minimum, maximum = fixed_range
    scaled = (
        np.zeros_like(values)
        if maximum <= minimum
        else np.clip((values - minimum) / (maximum - minimum), 0, 1)
    )
    for channel in range(3):
        image[..., channel] = np.interp(
            scaled,
            [0, 0.5, 1],
            BLUE_PALETTE[:, channel],
        ).astype(np.uint8)
    image[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
    return image


def render(payload: dict) -> dict:
    maximum = payload["size"]["max_side"]
    if (
        isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or not 1 <= maximum <= MAX_SIDE
    ):
        raise PreviewError("地图预览尺寸无效")
    rules = payload.get("rules") or {}
    if rules.get("band") != 1 or rules.get("palette") != "blue":
        raise PreviewError("地图预览渲染规则无效")
    fixed_range = rules.get("range")
    if fixed_range not in (None, [-1, 1]):
        raise PreviewError("地图预览渲染范围无效")
    with rasterio.Env(GDAL_PAM_ENABLED="NO", GDAL_CACHEMAX=64 * 1024**2):
        with rasterio.open(Path(payload["raster_path"])) as src:
            if src.driver != "GTiff" or src.count < 1:
                raise PreviewError("该计算结果暂不支持地图预览")
            bounds = geographic_bounds(src)
            _, native_width, native_height = calculate_default_transform(
                src.crs,
                "EPSG:4326",
                src.width,
                src.height,
                *src.bounds,
            )
            if native_width < 1 or native_height < 1:
                raise PreviewError("计算结果空间范围无效，无法定位到地图")
            scale = min(1, maximum / max(native_width, native_height))
            width = max(1, int(native_width * scale))
            height = max(1, int(native_height * scale))
            with WarpedVRT(
                src,
                crs="EPSG:4326",
                transform=from_bounds(*bounds, width, height),
                width=width,
                height=height,
                add_alpha=ColorInterp.alpha not in src.colorinterp,
                resampling=Resampling.bilinear,
                warp_mem_limit=64,
                warp_extras={"NUM_THREADS": "1"},
            ) as vrt:
                values = vrt.read(1, masked=True)
                # GDAL does not expose a floating alpha band as read_masks(1).
                # Read it explicitly so source NoData and warped margins stay clear.
                if ColorInterp.alpha in vrt.colorinterp:
                    alpha_band = vrt.colorinterp.index(ColorInterp.alpha) + 1
                    values = np.ma.masked_where(vrt.read(alpha_band) <= 0, values)
            rgba = colorize(values, fixed_range)
    path = Path(payload["output_png_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba).save(path, format="PNG")
    return {
        "status": "ok",
        "bounds4326": list(bounds),
        "width": width,
        "height": height,
    }


def main() -> int:
    try:
        result = render(json.loads(sys.stdin.read()))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except PreviewError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
    except Exception:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": "计算结果暂不能生成地图预览，请检查结果文件与坐标系",
                },
                ensure_ascii=False,
            )
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
