"""Read-only map previews for retained computation outputs, before import."""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections import OrderedDict
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from PIL import Image

from apps.core.cli import cli_environment, popen_cli
from apps.core.runtime_config import (
    runtime_max_raster_side_pixels,
    runtime_symbolizer_timeout_seconds,
)
from apps.core.storage import StoragePathError, app_path
from .packages import ComputeError, checksum


RENDER_VERSION = 2
MAX_PREVIEW_SIDE = 1024
MAX_MEMORY_CACHE_ENTRIES = 8
MAX_MAP_LATITUDE = 85.051129
SYMBOLIZER = (
    Path(__file__).resolve().parents[2]
    / "scripts/raster_symbolizers/compute_map_preview.py"
)
_CACHE: OrderedDict[str, tuple[bytes, dict]] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _rules(output) -> dict:
    mineral, _, kind = output.key.rpartition("_")
    if mineral in {
        "hematite",
        "chlorite",
        "hydromica",
        "calcite",
        "dolomite",
    } and kind in {"before", "corrected", "changes", "hits"}:
        return {
            "band": 1,
            "palette": "alteration-changes"
            if kind in {"changes", "hits"}
            else "alteration",
            "range": None,
        }
    return {
        "band": 1,
        "palette": "blue",
        "range": [-1, 1] if output.key.lower() in {"ndvi", "ndwi"} else None,
    }


def _source(output) -> Path:
    if output.expired:
        raise ComputeError("计算结果已过期，无法预览", 404)
    if output.task.status != "succeeded":
        raise ComputeError("计算尚未成功完成，暂不能预览")
    if output.kind != "raster":
        raise ComputeError("当前仅支持栅格计算结果的地图预览")
    try:
        source = app_path(output.path)
        if not source.is_file():
            raise ComputeError("计算结果文件已不存在", 404)
        if checksum(source) != output.checksum:
            raise ComputeError("计算结果文件与登记内容不一致，请重新计算", 409)
        return source
    except (StoragePathError, OSError) as exc:
        raise ComputeError("计算结果文件路径无效", 404) from exc


def _fingerprint(output, source: Path, side: int, rules: dict) -> str:
    stat = source.stat()
    identity = {
        "project": output.task.project_tag_id,
        "task": str(output.task_id),
        "output": output.id,
        "checksum": output.checksum,
        "path": str(source),
        "mtime": stat.st_mtime_ns,
        "size": stat.st_size,
        "side": side,
        "rules": rules,
        "renderer": RENDER_VERSION,
        "script": hashlib.sha256(SYMBOLIZER.read_bytes()).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _metadata(value: dict) -> dict:
    """Validate the fixed symbolizer response and derive its map quadrilateral."""
    bounds = value.get("bounds4326")
    if (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(item)
            for item in bounds
        )
    ):
        raise ValueError("invalid preview bounds")
    west, south, east, north = bounds
    if not (
        -180 <= west < east <= 180
        and east - west <= 180
        and -MAX_MAP_LATITUDE <= south < north <= MAX_MAP_LATITUDE
    ):
        raise ValueError("unsupported preview bounds")
    width, height = value.get("width"), value.get("height")
    if any(
        isinstance(side, bool)
        or not isinstance(side, int)
        or not 1 <= side <= MAX_PREVIEW_SIDE
        for side in (width, height)
    ):
        raise ValueError("invalid preview dimensions")
    return {
        "bounds4326": bounds,
        "imageCoordinates": [
            [west, north],
            [east, north],
            [east, south],
            [west, south],
        ],
        "width": width,
        "height": height,
    }


def _cached(fingerprint: str) -> tuple[bytes, dict] | None:
    with _CACHE_LOCK:
        cached = _CACHE.pop(fingerprint, None)
        if cached is not None:
            _CACHE[fingerprint] = cached
        return cached


def _remember(fingerprint: str, png: bytes, metadata: dict) -> None:
    with _CACHE_LOCK:
        _CACHE.pop(fingerprint, None)
        _CACHE[fingerprint] = png, metadata
        while len(_CACHE) > MAX_MEMORY_CACHE_ENTRIES:
            _CACHE.popitem(last=False)


def clear_preview_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _render(source: Path, png: Path, side: int, rules: dict) -> dict:
    environment = {**cli_environment(), "GDAL_PAM_ENABLED": "NO", "PYTHONUTF8": "1"}
    process = popen_cli(
        [sys.executable, str(SYMBOLIZER)],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, _ = process.communicate(
            json.dumps(
                {
                    "raster_path": str(source),
                    "output_png_path": str(png),
                    "size": {"max_side": side},
                    "rules": rules,
                }
            ),
            timeout=min(runtime_symbolizer_timeout_seconds(), 30),
        )
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise ComputeError("地图预览生成超时，请稍后重试", 503) from exc
    try:
        result = json.loads(stdout)
        if process.returncode or result.get("status") != "ok":
            raise ComputeError(result.get("error") or "计算结果暂不能生成地图预览")
        return _metadata(result)
    except (ValueError, TypeError, AttributeError) as exc:
        if isinstance(exc, ComputeError):
            raise
        raise ComputeError("地图预览返回的空间信息无效") from exc


def ensure_map_preview(output) -> tuple[bytes, dict]:
    """Caller must authorize the task and current source resources on each request."""
    source = _source(output)
    side = min(MAX_PREVIEW_SIDE, runtime_max_raster_side_pixels())
    rules = _rules(output)
    try:
        fingerprint = _fingerprint(output, source, side, rules)
        directory = app_path(
            "cache",
            "compute-map-preview",
            str(output.task.project_tag_id),
            str(output.task_id),
            str(output.id),
        )
        cached = _cached(fingerprint)
        if cached is None:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="render-", dir=directory
            ) as temporary:
                temporary_png = Path(temporary) / "preview.png"
                metadata = _render(source, temporary_png, side, rules)
                if _fingerprint(output, source, side, rules) != fingerprint:
                    raise ComputeError("计算结果文件已更新，请重新预览", 409)
                if checksum(source) != output.checksum:
                    raise ComputeError("计算结果文件与登记内容不一致，请重新计算", 409)
                png = temporary_png.read_bytes()
                with Image.open(io.BytesIO(png)) as image:
                    if (
                        image.format != "PNG"
                        or image.mode != "RGBA"
                        or image.size != (metadata["width"], metadata["height"])
                    ):
                        raise ComputeError("地图预览图像无效")
                    image.verify()
            _remember(fingerprint, png, metadata)
        else:
            png, metadata = cached
        return png, {"outputId": output.id, "label": output.label, **metadata}
    except (OSError, StoragePathError) as exc:
        raise ComputeError("地图预览文件暂不可用，请稍后重试", 503) from exc
