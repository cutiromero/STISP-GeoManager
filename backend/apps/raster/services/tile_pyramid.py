from __future__ import annotations

import io
import math
import os
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from apps.raster.services.constants import (
    DEFAULT_TILE_SIZE,
    WEB_MERCATOR_HALF_WORLD,
)
from apps.raster.services.exceptions import RasterRenderError


MIN_STATIC_ZOOM = 0
MAX_STATIC_ZOOM = 22
MAX_STATIC_TILE_COUNT = 50_000
PROGRESS_UPDATE_TILE_INTERVAL = 25
_WEB_MERCATOR_SPAN = WEB_MERCATOR_HALF_WORLD * 2
_BASE_PIXEL_SIZE = _WEB_MERCATOR_SPAN / DEFAULT_TILE_SIZE


@dataclass(frozen=True)
class TilePyramidSpec:
    min_zoom: int
    max_zoom: int
    total_tiles: int


@dataclass(frozen=True)
class TilePyramidBuildResult:
    path: Path
    min_zoom: int
    max_zoom: int
    total_tiles: int
    reused: bool


def native_web_mercator_max_zoom(metadata: dict[str, Any]) -> int:
    """Return the last XYZ level that carries native raster detail."""

    resolution = _pixel_size_from_metadata(metadata)
    if not math.isfinite(resolution) or resolution <= 0:
        return MAX_STATIC_ZOOM
    zoom = math.ceil(math.log2(_BASE_PIXEL_SIZE / resolution))
    return min(MAX_STATIC_ZOOM, max(MIN_STATIC_ZOOM, zoom))


def tile_range_for_bounds(
    bounds: list[float] | tuple[float, float, float, float], z: int
) -> tuple[int, int, int, int] | None:
    if z < 0 or len(bounds) < 4:
        return None
    left, bottom, right, top = [float(value) for value in bounds[:4]]
    left = max(-WEB_MERCATOR_HALF_WORLD, left)
    bottom = max(-WEB_MERCATOR_HALF_WORLD, bottom)
    right = min(WEB_MERCATOR_HALF_WORLD, right)
    top = min(WEB_MERCATOR_HALF_WORLD, top)
    if right <= left or top <= bottom:
        return None

    tile_count = 2**z
    tile_span = _WEB_MERCATOR_SPAN / tile_count
    min_x = math.floor((left + WEB_MERCATOR_HALF_WORLD) / tile_span)
    max_x = math.ceil((right + WEB_MERCATOR_HALF_WORLD) / tile_span) - 1
    min_y = math.floor((WEB_MERCATOR_HALF_WORLD - top) / tile_span)
    max_y = math.ceil((WEB_MERCATOR_HALF_WORLD - bottom) / tile_span) - 1
    min_x = min(tile_count - 1, max(0, min_x))
    max_x = min(tile_count - 1, max(0, max_x))
    min_y = min(tile_count - 1, max(0, min_y))
    max_y = min(tile_count - 1, max(0, max_y))
    if max_x < min_x or max_y < min_y:
        return None
    return min_x, max_x, min_y, max_y


def tile_pyramid_spec(
    bounds: list[float] | tuple[float, float, float, float],
    metadata: dict[str, Any],
) -> TilePyramidSpec:
    max_zoom = native_web_mercator_max_zoom(metadata)
    total_tiles = 0
    for z in range(MIN_STATIC_ZOOM, max_zoom + 1):
        tile_range = tile_range_for_bounds(bounds, z)
        if tile_range is None:
            continue
        min_x, max_x, min_y, max_y = tile_range
        total_tiles += (max_x - min_x + 1) * (max_y - min_y + 1)
    if total_tiles <= 0:
        raise RasterRenderError("栅格范围没有可生成的 Web Mercator 瓦片")
    if total_tiles > MAX_STATIC_TILE_COUNT:
        raise RasterRenderError(
            f"分类栅格静态瓦片数量 {total_tiles} 超过安全上限 {MAX_STATIC_TILE_COUNT}"
        )
    return TilePyramidSpec(MIN_STATIC_ZOOM, max_zoom, total_tiles)


def build_atomic_mbtiles_pyramid(
    target_path: Path,
    *,
    style_hash: str,
    bounds: list[float] | tuple[float, float, float, float],
    metadata: dict[str, Any],
    render_native_tile: Callable[[int, int, int], bytes],
    progress: Callable[[int, int, int], None] | None = None,
) -> TilePyramidBuildResult:
    """Build a complete categorical pyramid before exposing one atomic file."""

    spec = tile_pyramid_spec(bounds, metadata)
    if _is_complete_pyramid(target_path, style_hash, spec):
        return TilePyramidBuildResult(
            target_path,
            spec.min_zoom,
            spec.max_zoom,
            spec.total_tiles,
            True,
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(
        f".{target_path.name}.{uuid.uuid4().hex}.tmp"
    )
    completed = 0
    connection: sqlite3.Connection | None = None

    def report_build_progress(zoom: int, *, force: bool = False) -> None:
        if progress is None:
            return
        if (
            force
            or completed == 1
            or completed % PROGRESS_UPDATE_TILE_INTERVAL == 0
        ):
            progress(completed, spec.total_tiles, zoom)

    try:
        connection = sqlite3.connect(temporary_path)
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.executescript(
            """
            CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE tiles (
                zoom_level INTEGER NOT NULL,
                tile_column INTEGER NOT NULL,
                tile_row INTEGER NOT NULL,
                tile_data BLOB NOT NULL,
                PRIMARY KEY (zoom_level, tile_column, tile_row)
            ) WITHOUT ROWID;
            """
        )
        connection.executemany(
            "INSERT INTO metadata(name, value) VALUES (?, ?)",
            (
                ("name", style_hash),
                ("format", "png"),
                ("minzoom", str(spec.min_zoom)),
                ("maxzoom", str(spec.max_zoom)),
                ("tile_count", str(spec.total_tiles)),
                ("bounds3857", ",".join(str(float(value)) for value in bounds[:4])),
                ("style_hash", style_hash),
                ("complete", "0"),
            ),
        )

        native_range = tile_range_for_bounds(bounds, spec.max_zoom)
        if native_range is None:
            raise RasterRenderError("分类栅格原生级别没有可生成瓦片")
        for x, y in _iter_tile_range(native_range):
            _insert_tile(
                connection,
                spec.max_zoom,
                x,
                y,
                render_native_tile(spec.max_zoom, x, y),
            )
            completed += 1
            report_build_progress(spec.max_zoom)
        connection.commit()
        report_build_progress(spec.max_zoom, force=True)

        for z in range(spec.max_zoom - 1, spec.min_zoom - 1, -1):
            parent_range = tile_range_for_bounds(bounds, z)
            if parent_range is None:
                continue
            for x, y in _iter_tile_range(parent_range):
                _insert_tile(
                    connection,
                    z,
                    x,
                    y,
                    _parent_tile_from_children(connection, z, x, y),
                )
                completed += 1
                report_build_progress(z)
            connection.commit()
            report_build_progress(z, force=True)

        if completed != spec.total_tiles:
            raise RasterRenderError(
                f"分类栅格静态瓦片不完整：{completed}/{spec.total_tiles}"
            )
        connection.execute("UPDATE metadata SET value = '1' WHERE name = 'complete'")
        connection.commit()
        connection.close()
        connection = None

        # The style hash is immutable. A concurrent completed builder wins and
        # this temporary file can be discarded without replacing live readers.
        if _is_complete_pyramid(target_path, style_hash, spec):
            temporary_path.unlink(missing_ok=True)
        else:
            os.replace(temporary_path, target_path)
        return TilePyramidBuildResult(
            target_path,
            spec.min_zoom,
            spec.max_zoom,
            spec.total_tiles,
            False,
        )
    finally:
        if connection is not None:
            connection.close()
        temporary_path.unlink(missing_ok=True)


def read_mbtiles_tile(path: Path, z: int, x: int, y: int) -> bytes | None:
    if not path.is_file() or z < 0 or x < 0 or y < 0 or x >= 2**z or y >= 2**z:
        return None
    tile_row = (2**z - 1) - y
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            row = connection.execute(
                """
                SELECT tile_data FROM tiles
                WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?
                """,
                (z, x, tile_row),
            ).fetchone()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return None
    return bytes(row[0]) if row else None


def read_mbtiles_metadata(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            rows = connection.execute("SELECT name, value FROM metadata").fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return {}
    return {str(name): str(value) for name, value in rows}


def _pixel_size_from_metadata(metadata: dict[str, Any]) -> float:
    transform = metadata.get("geoTransform") or []
    if isinstance(transform, list | tuple) and len(transform) >= 6:
        column_size = math.hypot(float(transform[1]), float(transform[4]))
        row_size = math.hypot(float(transform[2]), float(transform[5]))
        candidates = [value for value in (column_size, row_size) if value > 0]
        if candidates:
            return max(candidates)

    size = metadata.get("size") or []
    corners = metadata.get("cornerCoordinates") or {}
    upper_left = corners.get("upperLeft") or []
    lower_right = corners.get("lowerRight") or []
    if len(size) >= 2 and len(upper_left) >= 2 and len(lower_right) >= 2:
        width = max(1, int(size[0]))
        height = max(1, int(size[1]))
        return max(
            abs(float(lower_right[0]) - float(upper_left[0])) / width,
            abs(float(upper_left[1]) - float(lower_right[1])) / height,
        )
    return float("nan")


def _iter_tile_range(tile_range: tuple[int, int, int, int]):
    min_x, max_x, min_y, max_y = tile_range
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            yield x, y


def _insert_tile(
    connection: sqlite3.Connection, z: int, x: int, y: int, data: bytes
) -> None:
    connection.execute(
        """
        INSERT INTO tiles(zoom_level, tile_column, tile_row, tile_data)
        VALUES (?, ?, ?, ?)
        """,
        (z, x, (2**z - 1) - y, sqlite3.Binary(data)),
    )


def _read_connection_tile(
    connection: sqlite3.Connection, z: int, x: int, y: int
) -> bytes | None:
    row = connection.execute(
        """
        SELECT tile_data FROM tiles
        WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?
        """,
        (z, x, (2**z - 1) - y),
    ).fetchone()
    return bytes(row[0]) if row else None


def _parent_tile_from_children(
    connection: sqlite3.Connection, z: int, x: int, y: int
) -> bytes:
    mosaic = Image.new("RGBA", (DEFAULT_TILE_SIZE * 2, DEFAULT_TILE_SIZE * 2))
    child_zoom = z + 1
    for offset_x in range(2):
        for offset_y in range(2):
            child = _read_connection_tile(
                connection,
                child_zoom,
                x * 2 + offset_x,
                y * 2 + offset_y,
            )
            if child is None:
                continue
            with Image.open(io.BytesIO(child)) as image:
                mosaic.paste(
                    image.convert("RGBA"),
                    (offset_x * DEFAULT_TILE_SIZE, offset_y * DEFAULT_TILE_SIZE),
                )
    parent = mosaic.resize(
        (DEFAULT_TILE_SIZE, DEFAULT_TILE_SIZE), Image.Resampling.NEAREST
    )
    output = io.BytesIO()
    parent.save(output, format="PNG")
    return output.getvalue()


def _is_complete_pyramid(path: Path, style_hash: str, spec: TilePyramidSpec) -> bool:
    metadata = read_mbtiles_metadata(path)
    return (
        metadata.get("complete") == "1"
        and metadata.get("style_hash") == style_hash
        and metadata.get("minzoom") == str(spec.min_zoom)
        and metadata.get("maxzoom") == str(spec.max_zoom)
        and metadata.get("tile_count") == str(spec.total_tiles)
    )
