from __future__ import annotations

import hashlib
import io
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from apps.raster.services.constants import DEFAULT_TILE_SIZE, WEB_MERCATOR_HALF_WORLD


def bounds_from_gdalinfo(metadata: dict[str, Any]) -> list[float]:
    corners = metadata.get("cornerCoordinates") or {}
    points = [
        corners.get(key)
        for key in ("upperLeft", "lowerLeft", "lowerRight", "upperRight")
    ]
    points = [point for point in points if isinstance(point, list) and len(point) >= 2]
    if not points:
        return []
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def bounds_4326_from_gdalinfo(metadata: dict[str, Any]) -> list[float]:
    ring = (((metadata.get("wgs84Extent") or {}).get("coordinates") or [[]])[0]) or []
    points = [point for point in ring if isinstance(point, list) and len(point) >= 2]
    if not points:
        return []
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def image_coordinates_from_gdalinfo(metadata: dict[str, Any]) -> list[list[float]]:
    ring = (((metadata.get("wgs84Extent") or {}).get("coordinates") or [[]])[0]) or []
    if len(ring) >= 4:
        upper_left = ring[0]
        lower_left = ring[1]
        lower_right = ring[2]
        upper_right = ring[3]
        return [upper_left, upper_right, lower_right, lower_left]
    bounds = bounds_4326_from_gdalinfo(metadata)
    if not bounds:
        return []
    west, south, east, north = bounds
    return [[west, north], [east, north], [east, south], [west, south]]


def style_hash_for(raster_path: Path, rules: dict[str, Any]) -> str:
    stat = raster_path.stat()
    payload = {
        "raster_path": str(raster_path.resolve()),
        "raster_mtime": stat.st_mtime_ns,
        "raster_size": stat.st_size,
        "rules": rules,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    tile_count = 2**z
    tile_span = (WEB_MERCATOR_HALF_WORLD * 2) / tile_count
    minx = -WEB_MERCATOR_HALF_WORLD + x * tile_span
    maxx = minx + tile_span
    maxy = WEB_MERCATOR_HALF_WORLD - y * tile_span
    miny = maxy - tile_span
    return minx, miny, maxx, maxy


def intersects_bounds(
    bounds: tuple[float, float, float, float], dataset_bounds: Any
) -> bool:
    minx, miny, maxx, maxy = bounds
    if isinstance(dataset_bounds, (list, tuple)) and len(dataset_bounds) >= 4:
        left, bottom, right, top = [float(value) for value in dataset_bounds[:4]]
    else:
        left = float(dataset_bounds.left)
        right = float(dataset_bounds.right)
        bottom = float(dataset_bounds.bottom)
        top = float(dataset_bounds.top)
    return not (maxx <= left or minx >= right or maxy <= bottom or miny >= top)


@lru_cache(maxsize=1)
def transparent_png() -> bytes:
    output = np.zeros((DEFAULT_TILE_SIZE, DEFAULT_TILE_SIZE, 4), dtype=np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(output, mode="RGBA").save(buffer, format="PNG")
    return buffer.getvalue()
