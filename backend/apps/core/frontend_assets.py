"""Bounded history of public build assets, independent of business data."""

from functools import lru_cache
import hashlib
import mimetypes
import os
from pathlib import Path, PurePosixPath
import shutil
import time

from django.http import FileResponse, Http404
from django.views.decorators.http import require_safe

from .client_build import EntryParser
from .file_evidence import file_identity, read_receipt, write_receipt
from .storage import app_path
from .storage_locks import storage_lock

# Configuration: whole build dependency sets are retained within these bounds.
RETENTION_DAYS = 14
MAXIMUM_BYTES = 512 * 1024**2
MAXIMUM_BUILDS = 64
INDEX_LIMIT = 16 * 1024**2


def history_root():
    return app_path("cache", "frontend-asset-history")


def _safe(name):
    path = PurePosixPath(name)
    return bool(
        name
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in name
        and "\x00" not in name
    )


def _index(root):
    value = read_receipt(
        root / "index.json", "frontend-assets-v1", max_bytes=INDEX_LIMIT
    )
    if not isinstance(value, dict) or value.get("schema") != 1:
        return {"schema": 1, "builds": [], "files": {}}
    return value


def archive_assets(source, *, now=None):
    source = Path(source).resolve()
    now = time.time() if now is None else now
    parser = EntryParser()
    document = (source / "index.html").read_bytes()
    parser.feed(document.decode())
    if not parser.entry or not parser.entry.startswith("/static/"):
        raise ValueError("Source is not a production frontend build")
    build = hashlib.sha256(document).hexdigest()
    root = history_root()
    with storage_lock(root / ".lock"):
        index = _index(root)
        files = index["files"]
        names = []
        for path in sorted((source / "assets").rglob("*")):
            if path.is_symlink():
                raise ValueError("Public asset history does not accept symlinks")
            if not path.is_file() or path.suffix in {".gz", ".br"}:
                continue
            name = path.relative_to(source / "assets").as_posix()
            if not _safe(name):
                raise ValueError("Invalid public asset name")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            target = root / "files" / name
            previous = files.get(name)
            valid = bool(
                previous
                and previous.get("sha256") == digest
                and target.is_file()
                and not target.is_symlink()
                and list(file_identity(target.stat())) == previous.get("identity")
            )
            if previous and previous.get("sha256") != digest:
                raise ValueError(
                    "Public asset filename collision; history was not overwritten"
                )
            if not valid:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + ".copying")
                try:
                    shutil.copyfile(path, temporary)
                    temporary.chmod(0o444)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            files[name] = {
                "sha256": digest,
                "size": target.stat().st_size,
                "identity": list(file_identity(target.stat())),
            }
            names.append(name)
        builds = [row for row in index["builds"] if row["id"] != build]
        builds.append(
            {"id": build, "entry": parser.entry, "lastSeen": now, "files": names}
        )
        builds.sort(key=lambda row: row["lastSeen"])
        while len(builds) > 1:
            retained = set(name for row in builds for name in row["files"])
            size = sum(files[name]["size"] for name in retained)
            if (
                len(builds) <= MAXIMUM_BUILDS
                and size <= MAXIMUM_BYTES
                and builds[0]["lastSeen"] >= now - RETENTION_DAYS * 86400
            ):
                break
            builds.pop(0)
        retained = set(name for row in builds for name in row["files"])
        if sum(files[name]["size"] for name in retained) > MAXIMUM_BYTES:
            raise ValueError("One frontend build exceeds the asset history budget")
        stale = set(files) - retained
        # Publish the new index before deleting only unreferenced public cache files.
        value = {
            "schema": 1,
            "builds": builds,
            "files": {name: files[name] for name in sorted(retained)},
        }
        write_receipt(root / "index.json", value, "frontend-assets-v1")
        for name in stale:
            if _safe(name):
                (root / "files" / name).unlink(missing_ok=True)
        return {
            "build": build,
            "builds": len(builds),
            "assets": len(retained),
            "bytes": sum(row["size"] for row in value["files"].values()),
        }


@lru_cache(maxsize=2)
def _cached_index(root, identity):
    return _index(Path(root))


@require_safe
def historical_asset(request, asset_path):
    if not _safe(asset_path):
        raise Http404("Public asset not found")
    root = history_root()
    manifest = root / "index.json"
    try:
        index = _cached_index(str(root), file_identity(manifest.stat()))
        record = index["files"].get(asset_path)
        path = root / "files" / asset_path
        if (
            not record
            or path.is_symlink()
            or not path.resolve().is_relative_to((root / "files").resolve())
            or list(file_identity(path.stat())) != record["identity"]
        ):
            raise Http404("Public asset not found")
        stream = path.open("rb")
        if list(file_identity(os.fstat(stream.fileno()))) != record["identity"]:
            stream.close()
            raise Http404("Public asset changed")
    except (OSError, ValueError, KeyError):
        raise Http404("Public asset not found") from None
    content_type = (
        "application/javascript"
        if path.suffix == ".js"
        else mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    )
    response = FileResponse(stream, content_type=content_type)
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["ETag"] = '"' + record["sha256"] + '"'
    response["X-STISP-Asset-History"] = "1"
    response["X-Content-Type-Options"] = "nosniff"
    return response
