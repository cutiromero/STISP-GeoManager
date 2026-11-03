"""Bounded-size cached thumbnails for result and thematic-map cards.

A thumbnail is derived from the original once and stored under the business-data
cache, keyed by the source's size and modification time, so a replaced file gets a
new thumbnail and an unchanged one is never re-encoded.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from django.http import FileResponse
from PIL import Image

from apps.core.storage import app_path

THUMBNAIL_EDGE = 640
THUMBNAIL_EXTENSIONS = {".png", ".jpg", ".jpeg"}
# Applies to public anonymous reads; the project middleware keeps every signed-in
# or private-project response no-store so revoked access takes effect at once.
# Result thumbnail URLs carry the artifact's update time, so a replaced file gets
# a new URL instead of a day-old cached image.
CACHE_CONTROL = "private, max-age=86400"


def thumbnail_path(source: Path, key: str) -> Path:
    stat = source.stat()
    target = app_path(
        "cache", "thumbnails", f"{key}-{stat.st_size}-{stat.st_mtime_ns}.webp"
    )
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    # Concurrent first requests each encode into their own file; replace is atomic.
    temporary = target.with_name(f"{target.stem}-{uuid.uuid4().hex}.tmp")
    with Image.open(source) as image:
        image.thumbnail((THUMBNAIL_EDGE, THUMBNAIL_EDGE))
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        try:
            image.save(temporary, "WEBP", quality=80, method=4)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    temporary.replace(target)
    return target


def thumbnail_response(source: Path, key: str) -> FileResponse:
    response = FileResponse(
        thumbnail_path(source, key).open("rb"), content_type="image/webp"
    )
    response["Cache-Control"] = CACHE_CONTROL
    response["X-Content-Type-Options"] = "nosniff"
    return response
