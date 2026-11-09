"""Version-bound output indexes shared by every task, algorithm and reader."""

from contextlib import closing, contextmanager, ExitStack
import csv
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

from apps.core.file_evidence import (
    artifact_lock,
    file_identity,
    read_receipt,
    write_receipt,
)
from apps.core.storage import app_path
from .packages import ComputeError, checksum

# Configuration: data paths come from TOML; indexes are disposable private cache.
CACHE_VERSION = 1
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
CHECKPOINT_ROWS = 256


def _identity(path):
    if path.is_symlink() or not path.is_file():
        raise ComputeError("结果文件不存在或类型已变化", 409)
    return list(file_identity(path.stat()))


def _source(path, digest, dependencies):
    return {
        "path": str(path.absolute()),
        "sha256": digest,
        "identity": _identity(path),
        "dependencies": {
            str(item): _identity(item) if item.exists() else None
            for item in dependencies
        },
    }


def _cached(directory, source, kind):
    manifest = read_receipt(
        directory / "manifest.json", "result-read-v1", max_bytes=MAX_MANIFEST_BYTES
    )
    if (
        not isinstance(manifest, dict)
        or manifest.get("source") != source
        or manifest.get("kind") != kind
    ):
        return None
    try:
        for name, identity in manifest["files"].items():
            if Path(name).name != name or _identity(directory / name) != identity:
                return None
        return manifest["metadata"]
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _checked_source(path, expected_checksum, dependencies=()):
    before = _identity(path)
    digest = checksum(path)
    source = _source(path, digest, dependencies)
    if source["identity"] != before or (
        expected_checksum and digest != expected_checksum
    ):
        raise ComputeError("结果文件内容已变化，请重新检查", 409)
    return source


@contextmanager
def _artifact(path, kind, builder, *, dependencies=(), expected_checksum=""):
    source = _checked_source(path, expected_checksum, dependencies)
    digest = source["sha256"]
    encoded = json.dumps(
        {"schema": CACHE_VERSION, "source": source, "kind": kind}, sort_keys=True
    ).encode()
    key = hashlib.sha256(encoded).hexdigest()
    base = app_path("cache", "result-reads")
    directory = base / key
    with artifact_lock(key):
        metadata = _cached(directory, source, kind)
        if metadata is None:
            base.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=".building-", dir=base
            ) as temporary:
                staging = Path(temporary)
                metadata = builder(staging)
                if _source(path, digest, dependencies) != source:
                    raise ComputeError("结果文件在读取期间发生变化，请重试", 409)
                files = {
                    item.name: _identity(item)
                    for item in staging.iterdir()
                    if item.is_file()
                }
                write_receipt(
                    staging / "manifest.json",
                    {
                        "schema": CACHE_VERSION,
                        "source": source,
                        "kind": kind,
                        "metadata": metadata,
                        "files": files,
                    },
                    "result-read-v1",
                )
                if directory.is_symlink():
                    directory.unlink()
                elif directory.exists():
                    shutil.rmtree(directory)
                staging.rename(directory)
        if _source(path, digest, dependencies) != source:
            raise ComputeError("结果文件在读取期间发生变化，请重试", 409)
        yield directory, metadata
        if _source(path, digest, dependencies) != source:
            raise ComputeError("结果文件在读取期间发生变化，请重试", 409)


def _index_table(path, directory):
    """Scan CSV records once, including quoted newlines, and index their ordinals."""
    with closing(sqlite3.connect(directory / "rows.sqlite3")) as db:
        db.execute("PRAGMA journal_mode=OFF")
        db.execute(
            "CREATE TABLE checkpoints (ordinal INTEGER PRIMARY KEY, position TEXT NOT NULL)"
        )
        with path.open(encoding="utf-8-sig", newline="") as stream:
            # readline keeps TextIOWrapper.tell() valid, including multiline CSV.
            reader = csv.DictReader(iter(stream.readline, ""))
            fields = reader.fieldnames or []
            batch, total = [], 0
            while True:
                position = stream.tell() if total % CHECKPOINT_ROWS == 0 else None
                try:
                    next(reader)
                except StopIteration:
                    break
                if position is not None:
                    batch.append((total, str(position)))
                total += 1
            if batch:
                db.executemany("INSERT INTO checkpoints VALUES (?,?)", batch)
            db.commit()
    return {"columns": fields, "total": total}


@contextmanager
def table_page(path, offset=0, limit=100, *, expected_checksum=""):
    """Read at most the requested records; never rescan CSV to count later pages."""
    if (
        type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= 1000
    ):
        raise ComputeError("分页位置或数量无效")
    with ExitStack() as stack:
        try:
            directory, metadata = stack.enter_context(
                _artifact(
                    path,
                    "csv-page-v1",
                    lambda directory: _index_table(path, directory),
                    expected_checksum=expected_checksum,
                )
            )
        except (OSError, sqlite3.Error):
            # Disposable cache failures retain the original correct read path.
            source = _checked_source(path, expected_checksum)
            rows, total = [], 0
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                fields = reader.fieldnames or []
                for total, row in enumerate(reader, 1):
                    if offset <= total - 1 < offset + limit:
                        rows.append(row)
            if _source(path, source["sha256"], ()) != source:
                raise ComputeError("结果文件在读取期间发生变化，请重试", 409)
            yield {"columns": fields, "total": total, "rows": iter(rows)}
            if _source(path, source["sha256"], ()) != source:
                raise ComputeError("结果文件在读取期间发生变化，请重试", 409)
            return
        uri = (directory / "rows.sqlite3").as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            checkpoint = db.execute(
                "SELECT ordinal, position FROM checkpoints WHERE ordinal <= ? ORDER BY ordinal DESC LIMIT 1",
                (offset,),
            ).fetchone()
        if checkpoint is None or offset >= metadata["total"]:
            yield {**metadata, "rows": iter(())}
        else:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                stream.seek(int(checkpoint[1]))
                reader = csv.DictReader(
                    iter(stream.readline, ""), fieldnames=metadata["columns"]
                )
                skip = offset - checkpoint[0]
                yield {**metadata, "rows": itertools.islice(reader, skip, skip + limit)}


def raster_statistics(path, *, expected_checksum=""):
    from apps.raster.services.gdal_ops import gdalinfo_json

    def build(directory):
        return gdalinfo_json(path, calculate_statistics=True)

    dependencies = [Path(str(path) + suffix) for suffix in (".aux.xml", ".msk", ".ovr")]
    with ExitStack() as stack:
        try:
            _, metadata = stack.enter_context(
                _artifact(
                    path,
                    "gdal-approximate-statistics-v1",
                    build,
                    dependencies=dependencies,
                    expected_checksum=expected_checksum,
                )
            )
        except OSError:
            source = _checked_source(path, expected_checksum, dependencies)
            metadata = build(None)
            if _source(path, source["sha256"], dependencies) != source:
                raise ComputeError("结果文件在读取期间发生变化，请重试", 409)
        return metadata


def clean_read_indexes(maximum_bytes, retention_days):
    root = app_path("cache", "result-reads")
    manifests = sorted(
        root.glob("*/manifest.json"), key=lambda path: path.stat().st_mtime
    )
    total = sum(
        item.stat().st_size
        for path in manifests
        for item in path.parent.iterdir()
        if item.is_file()
    )
    for path in manifests:
        if (
            total <= maximum_bytes
            and path.stat().st_mtime >= time.time() - retention_days * 86400
        ):
            continue
        try:
            with artifact_lock(path.parent.name, wait=False):
                size = sum(
                    item.stat().st_size
                    for item in path.parent.iterdir()
                    if item.is_file()
                )
                shutil.rmtree(path.parent)
                total -= size
        except OSError:
            continue
