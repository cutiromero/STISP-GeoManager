from __future__ import annotations

import io
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

from django.utils import timezone
from PIL import Image
from rasterio.enums import Resampling
from rasterio.windows import from_bounds

from apps.core.storage import raster_processed_path, raster_tile_pyramid_path
from apps.raster.models import RasterDataset, RasterStyle
from apps.raster.services.color_mapping import array_to_rgba
from apps.raster.services.constants import DEFAULT_TILE_SIZE
from apps.raster.services.exceptions import RasterRenderError, RasterTileOutsideExtent
from apps.raster.services.geo_utils import (
    intersects_bounds,
    style_hash_for,
    tile_bounds_3857,
)
from apps.raster.services.rules_engine import normalize_rules, read_source_bands
from apps.raster.services.tile_pyramid import (
    TilePyramidBuildResult,
    build_atomic_mbtiles_pyramid,
    native_web_mercator_max_zoom,
    read_mbtiles_tile,
)


@dataclass
class _TileStyleCacheEntry:
    style: dict[str, Any]
    last_accessed_at: float


_TILE_STYLES: OrderedDict[tuple[int, str], _TileStyleCacheEntry] = OrderedDict()
_TILE_STYLES_LOCK = threading.RLock()
TILE_STYLE_CACHE_MAX_ENTRIES = 256
TILE_STYLE_CACHE_TTL_SECONDS = 60 * 60
RASTER_RENDERER_VERSION = 4


def _prune_tile_styles_locked(*, now: float) -> None:
    while _TILE_STYLES:
        _, oldest = next(iter(_TILE_STYLES.items()))
        if now - oldest.last_accessed_at < TILE_STYLE_CACHE_TTL_SECONDS:
            break
        _TILE_STYLES.popitem(last=False)
    while len(_TILE_STYLES) > TILE_STYLE_CACHE_MAX_ENTRIES:
        _TILE_STYLES.popitem(last=False)


def _remember_tile_style(
    key: tuple[int, str],
    style: dict[str, Any],
    *,
    now: float | None = None,
) -> None:
    accessed_at = time.monotonic() if now is None else now
    with _TILE_STYLES_LOCK:
        _prune_tile_styles_locked(now=accessed_at)
        _TILE_STYLES.pop(key, None)
        _TILE_STYLES[key] = _TileStyleCacheEntry(style, accessed_at)
        _prune_tile_styles_locked(now=accessed_at)


def _get_tile_style(
    key: tuple[int, str], *, now: float | None = None
) -> dict[str, Any] | None:
    accessed_at = time.monotonic() if now is None else now
    with _TILE_STYLES_LOCK:
        _prune_tile_styles_locked(now=accessed_at)
        entry = _TILE_STYLES.pop(key, None)
        if entry is None:
            return None
        entry.last_accessed_at = accessed_at
        _TILE_STYLES[key] = entry
        return entry.style


def register_tile_style(
    dataset: RasterDataset, rules: dict[str, Any] | None
) -> dict[str, Any]:
    if dataset.status != RasterDataset.Status.READY:
        raise RasterRenderError("栅格数据集尚未完成预处理")
    raster_path = raster_processed_path(dataset.processed_relative_path)
    normalized_rules = normalize_rules(
        rules or dataset.default_rules, dataset.processed_gdalinfo
    )
    sh = _style_hash_for_rules(raster_path, normalized_rules)

    _remember_tile_style(
        (dataset.id, sh),
        {
            "dataset_id": dataset.id,
            "rules": normalized_rules,
            "created_at": timezone.now().isoformat(),
        },
    )
    RasterStyle.objects.update_or_create(
        dataset=dataset,
        style_hash=sh,
        defaults={"rules": normalized_rules},
    )
    return {
        "delivery": "xyz",
        "datasetId": dataset.id,
        "layerId": dataset.map_layer_id,
        "styleHash": sh,
        "tileUrl": (
            f"/api/raster/tiles/{dataset.id}/{sh}/{{z}}/{{x}}/{{y}}.png"
            f"?rv={RASTER_RENDERER_VERSION}"
        ),
        "minZoom": 0,
        "maxZoom": native_web_mercator_max_zoom(dataset.processed_gdalinfo),
        "tileSampling": (
            "nearest"
            if dataset.raster_kind == RasterDataset.RasterKind.CATEGORICAL
            else "linear"
        ),
        "bounds3857": dataset.bounds_3857,
        "bounds4326": dataset.bounds_4326,
        "imageCoordinates": dataset.image_coordinates,
        "rules": normalized_rules,
        "status": "ready",
    }


def render_xyz_tile(dataset_id: int, style_hash: str, z: int, x: int, y: int) -> bytes:
    _validate_tile_coordinates(z, x, y)
    dataset = RasterDataset.objects.get(
        pk=dataset_id, status=RasterDataset.Status.READY
    )
    raster_path = raster_processed_path(dataset.processed_relative_path)
    _validated_tile_style(dataset, raster_path, style_hash)

    if dataset.raster_kind == RasterDataset.RasterKind.CATEGORICAL:
        max_zoom = native_web_mercator_max_zoom(dataset.processed_gdalinfo)
        if z > max_zoom:
            raise RasterTileOutsideExtent("瓦片级别超过分类栅格原生最大级别")
        pyramid_path = raster_tile_pyramid_path(
            dataset_id, style_hash, RASTER_RENDERER_VERSION
        )
        static_tile = read_mbtiles_tile(pyramid_path, z, x, y)
        if static_tile is not None:
            return static_tile
        raise RasterRenderError("分类栅格静态瓦片尚未完整发布，请重新渲染图层")

    fingerprint = raster_path.stat()
    return _render_xyz_tile_cached(
        dataset_id,
        style_hash,
        z,
        x,
        y,
        fingerprint.st_mtime_ns,
        fingerprint.st_size,
    )


@lru_cache(maxsize=128)
def _render_xyz_tile_cached(
    dataset_id: int,
    style_hash: str,
    z: int,
    x: int,
    y: int,
    raster_mtime_ns: int,
    raster_size: int,
) -> bytes:
    _validate_tile_coordinates(z, x, y)
    dataset = RasterDataset.objects.get(
        pk=dataset_id, status=RasterDataset.Status.READY
    )
    raster_path = raster_processed_path(dataset.processed_relative_path)
    fingerprint = raster_path.stat()
    if fingerprint.st_mtime_ns != raster_mtime_ns or fingerprint.st_size != raster_size:
        raise RasterRenderError("栅格预处理文件已更新，请重新加载图层")
    style = _validated_tile_style(dataset, raster_path, style_hash)
    bounds = tile_bounds_3857(z, x, y)
    if dataset.bounds_3857 and not intersects_bounds(bounds, dataset.bounds_3857):
        raise RasterTileOutsideExtent("瓦片不在栅格空间范围内")

    import rasterio

    with rasterio.open(raster_path) as src:
        return _render_open_raster_tile(src, dataset, style["rules"], z, x, y)


def build_static_xyz_tile_pyramid(
    dataset: RasterDataset,
    style_hash: str,
    *,
    progress: Callable[[int, int, int], None] | None = None,
) -> TilePyramidBuildResult | None:
    """Pre-render one complete LUCC style before the frontend switches to it."""

    if dataset.status != RasterDataset.Status.READY:
        raise RasterRenderError("栅格数据集尚未完成预处理")
    if dataset.raster_kind != RasterDataset.RasterKind.CATEGORICAL:
        return None

    raster_path = raster_processed_path(dataset.processed_relative_path)
    style = _validated_tile_style(dataset, raster_path, style_hash)
    target_path = raster_tile_pyramid_path(
        dataset.id, style_hash, RASTER_RENDERER_VERSION
    )

    import rasterio

    with rasterio.open(raster_path) as src:

        def render_native_tile(z: int, x: int, y: int) -> bytes:
            return _render_open_raster_tile(src, dataset, style["rules"], z, x, y)

        return build_atomic_mbtiles_pyramid(
            target_path,
            style_hash=style_hash,
            bounds=dataset.bounds_3857,
            metadata=dataset.processed_gdalinfo,
            render_native_tile=render_native_tile,
            progress=progress,
        )


def _render_open_raster_tile(
    src,
    dataset: RasterDataset,
    rules: dict[str, Any],
    z: int,
    x: int,
    y: int,
) -> bytes:
    bounds = tile_bounds_3857(z, x, y)
    if not intersects_bounds(bounds, src.bounds):
        raise RasterTileOutsideExtent("瓦片不在栅格空间范围内")
    indexes = read_source_bands(rules)
    window = from_bounds(*bounds, transform=src.transform)
    data = src.read(
        indexes=indexes,
        window=window,
        out_shape=(len(indexes), DEFAULT_TILE_SIZE, DEFAULT_TILE_SIZE),
        boundless=True,
        masked=True,
        # This is deliberately hard-coded: categorical identifiers and the
        # native level of a static pyramid must never be interpolated.
        resampling=Resampling.nearest,
    )
    rgba = array_to_rgba(data, rules, dataset.processed_gdalinfo)
    buffer = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buffer, format="PNG")
    return buffer.getvalue()


def _validated_tile_style(
    dataset: RasterDataset, raster_path, style_hash: str
) -> dict[str, Any]:
    style_key = (dataset.id, style_hash)
    style = _get_tile_style(style_key)
    if not style:
        persisted = RasterStyle.objects.filter(
            dataset_id=dataset.id, style_hash=style_hash
        ).first()
        if persisted:
            style = {
                "dataset_id": dataset.id,
                "rules": persisted.rules,
                "created_at": persisted.created_at.isoformat(),
            }
            _remember_tile_style(style_key, style)
        else:
            raise RasterRenderError("符号化瓦片样式不存在或已过期")

    expected_hash = _style_hash_for_rules(raster_path, style["rules"])
    if expected_hash != style_hash:
        raise RasterRenderError("栅格文件或渲染器已更新，请重新加载图层")
    return style


def _style_hash_for_rules(raster_path, rules: dict[str, Any]) -> str:
    return style_hash_for(
        raster_path,
        {
            "rendererVersion": RASTER_RENDERER_VERSION,
            "rules": rules,
        },
    )


def _validate_tile_coordinates(z: int, x: int, y: int) -> None:
    if z < 0 or x < 0 or y < 0 or x >= 2**z or y >= 2**z:
        raise RasterTileOutsideExtent("瓦片坐标超出有效范围")


def _clear_renderer_caches() -> None:
    with _TILE_STYLES_LOCK:
        _TILE_STYLES.clear()
    _render_xyz_tile_cached.cache_clear()
