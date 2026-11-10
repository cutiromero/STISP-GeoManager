"""全站卡片小图：写入时生成，读取只打开缓存文件。"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import io
import logging
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import uuid

from django.http import FileResponse, HttpResponse
from PIL import Image, ImageOps

from apps.core.storage import app_path
from apps.core.storage_locks import storage_lock

THUMBNAIL_EDGE = 640
THUMBNAIL_SCHEMA_VERSION = 1
THUMBNAIL_MAX_BYTES = 48 * 1024
THUMBNAIL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}
CACHE_CONTROL = "private, no-cache, max-age=31536000, must-revalidate"
REPAIR_QUEUE_LIMIT = 64
REPAIR_RETRY_SECONDS = 60
PDF_TIMEOUT_SECONDS = 30
GENERATION_ERRORS = (
    OSError,
    ValueError,
    Image.DecompressionBombError,
    subprocess.SubprocessError,
)
PLACEHOLDER_WEBP = base64.b64decode(
    "UklGRjgAAABXRUJQVlA4ICwAAAAQAwCdASogABQAPrVWpE0nJKOiKAgA4BaJaQDA3BanFAAA/vJB236jwpgAAA=="
)

logger = logging.getLogger(__name__)
_repair_queue = queue.Queue(maxsize=REPAIR_QUEUE_LIMIT)
_repair_lock = threading.Lock()
_repair_pending: set[Path] = set()
_repair_failed: dict[Path, float] = {}
_repair_worker: threading.Thread | None = None


@dataclass(frozen=True)
class ThumbnailSource:
    path: Path
    key: str
    version: str

    @property
    def target(self) -> Path:
        return app_path("cache", "thumbnails", f"{self.key}-{self.version}.webp")


def source_for(instance) -> ThumbnailSource:
    label = instance._meta.label_lower
    if label == "catalog.resultartifact":
        relative = instance.file_path
        identity = (relative, instance.size_bytes, instance.updated_at.isoformat())
        key = f"result-{instance.pk}"
    elif label == "content.asset":
        relative = instance.path
        identity = (relative, instance.checksum)
        key = f"asset-{instance.pk}"
    elif label == "catalog.mapcompositionversion":
        relative = instance.preview_path
        identity = (
            relative,
            instance.snapshot_checksum,
            instance.created_at.isoformat(),
        )
        key = f"composition-version-{instance.pk}"
    else:
        raise ValueError(f"不支持的缩略图来源：{label}")
    version = hashlib.sha256(
        repr((THUMBNAIL_SCHEMA_VERSION, identity)).encode()
    ).hexdigest()[:24]
    return ThumbnailSource(app_path(relative), key, version)


def encode_thumbnail(source: Path, *, edge: int = THUMBNAIL_EDGE) -> bytes:
    if source.suffix.lower() not in THUMBNAIL_EXTENSIONS:
        return PLACEHOLDER_WEBP
    if source.suffix.lower() == ".pdf":
        with tempfile.TemporaryDirectory(prefix="card-pdf-") as directory:
            prefix = Path(directory) / "page"
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    "1",
                    "-l",
                    "1",
                    "-singlefile",
                    "-scale-to",
                    str(edge),
                    "-png",
                    str(source),
                    str(prefix),
                ],
                check=True,
                capture_output=True,
                timeout=PDF_TIMEOUT_SECONDS,
            )
            return encode_thumbnail(prefix.with_suffix(".png"), edge=edge)
    with Image.open(source) as original:
        original.thumbnail((edge, edge))
        image = ImageOps.exif_transpose(original).convert(
            "RGBA" if "A" in original.getbands() else "RGB"
        )
        while True:
            for quality in (76, 64, 52, 40):
                output = io.BytesIO()
                image.save(output, "WEBP", quality=quality, method=4)
                if output.tell() <= THUMBNAIL_MAX_BYTES:
                    return output.getvalue()
            image.thumbnail(
                (max(1, image.width * 3 // 4), max(1, image.height * 3 // 4))
            )


def generate_thumbnail(source: ThumbnailSource, *, target: Path | None = None) -> bool:
    target = target or source.target
    if target.is_file():
        return False
    with storage_lock(target.with_suffix(".lock"), timeout=PDF_TIMEOUT_SECONDS + 10):
        if target.is_file():
            return False
        content = encode_thumbnail(source.path)
        temporary = target.with_name(f".{target.name}-{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return True


def prepare_instance_thumbnail(instance) -> bool:
    source = source_for(instance)
    try:
        return generate_thumbnail(source)
    except GENERATION_ERRORS:
        logger.exception("卡片缩略图生成失败：%s", source.key)
        return False


def _repair_loop() -> None:
    while True:
        source, target = _repair_queue.get()
        try:
            generate_thumbnail(source, target=target)
        except GENERATION_ERRORS:
            logger.exception("卡片缩略图后台补生成失败：%s", source.key)
            with _repair_lock:
                if len(_repair_failed) >= REPAIR_QUEUE_LIMIT:
                    _repair_failed.clear()
                _repair_failed[target] = time.monotonic()
        finally:
            with _repair_lock:
                _repair_pending.discard(target)
            _repair_queue.task_done()


def enqueue_thumbnail(source: ThumbnailSource) -> bool:
    global _repair_worker
    target = source.target
    with _repair_lock:
        if target in _repair_pending or (
            time.monotonic() - _repair_failed.get(target, float("-inf"))
            < REPAIR_RETRY_SECONDS
        ):
            return False
        try:
            _repair_queue.put_nowait((source, target))
        except queue.Full:
            return False
        _repair_pending.add(target)
        if _repair_worker is None or not _repair_worker.is_alive():
            _repair_worker = threading.Thread(
                target=_repair_loop, name="card-thumbnail-repair", daemon=True
            )
            _repair_worker.start()
    return True


def thumbnail_response(source: ThumbnailSource, *, request=None):
    if request is not None and request.GET.get("v", source.version) != source.version:
        return HttpResponse(status=404)
    try:
        stream = source.target.open("rb")
    except OSError:
        enqueue_thumbnail(source)
        response = HttpResponse(PLACEHOLDER_WEBP, content_type="image/webp")
        response["Cache-Control"] = "private, no-store"
        response["X-Thumbnail-Status"] = "pending"
    else:
        etag = f'"{source.version}"'
        if request is not None and request.headers.get("If-None-Match") == etag:
            stream.close()
            response = HttpResponse(status=304)
        else:
            response = FileResponse(stream, content_type="image/webp")
        response["ETag"] = etag
        response["Cache-Control"] = CACHE_CONTROL
        response["X-Thumbnail-Status"] = "ready"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def register_thumbnail_writes() -> None:
    from django.db.models.signals import post_save

    for label in (
        "catalog.ResultArtifact",
        "catalog.MapCompositionVersion",
        "content.Asset",
    ):
        post_save.connect(
            _prepare_on_save,
            sender=label,
            weak=False,
            dispatch_uid=f"card-thumbnail:{label}",
        )
    post_save.connect(
        _prepare_cover_on_save,
        sender="content.Article",
        weak=False,
        dispatch_uid="card-thumbnail:content.Article",
    )


def _prepare_on_save(sender, instance, raw=False, **kwargs) -> None:
    if not raw:
        prepare_instance_thumbnail(instance)


def _prepare_cover_on_save(sender, instance, raw=False, **kwargs) -> None:
    if not raw and instance.cover_asset_id:
        prepare_instance_thumbnail(instance.cover_asset)
