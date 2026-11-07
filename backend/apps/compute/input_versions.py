"""Private, source-bound input versions and independent copy-on-write task files."""

from contextlib import contextmanager, closing
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import time

from django.utils.crypto import constant_time_compare, salted_hmac

from apps.core.storage import (
    app_path,
    raster_source_path,
    table_data_path,
    vector_geopackage_path,
)
from apps.raster.models import RasterDataset
from .packages import ComputeError, _file_identity

SCHEMA = 1
MINERALS = {"hematite", "chlorite", "hydromica", "calcite", "dolomite"}


def _stat(path):
    if not path.is_file() or path.is_symlink():
        raise ComputeError("输入版本文件不存在或类型已变化")
    return list(_file_identity(path.stat()))


def _source(resource):
    if resource.data_type == "raster":
        dataset = RasterDataset.objects.get(data_resource=resource, status="ready")
        return raster_source_path(dataset.source_relative_path), None
    if resource.data_type == "vector":
        return vector_geopackage_path(), resource.storage_path
    if resource.file_format.upper() == "SQLITE":
        return table_data_path("data.sqlite"), resource.storage_path
    from apps.catalog.nongeo import _resource_file_path

    return _resource_file_path(resource), None


def _source_identity(path, dependencies=()):
    identity = {"path": str(path), "file": _stat(path)}
    for suffix in ("-wal", "-journal"):
        journal = Path(str(path) + suffix)
        identity[suffix] = _stat(journal) if journal.exists() else None
    identity["dependencies"] = {
        str(other): _stat(other) if other.exists() else None for other in dependencies
    }
    return identity


def _table_digest(path, table, vector):
    quoted = '"' + table.replace('"', '""') + '"'
    digest = hashlib.sha256()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        schema = db.execute(f"PRAGMA table_info({quoted})").fetchall()
        if not schema:
            raise ComputeError("输入数据表已不存在")
        digest.update(json.dumps(schema).encode())
        if vector:
            spatial = db.execute(
                "SELECT g.column_name,g.geometry_type_name,g.z,g.m,s.* FROM gpkg_geometry_columns g JOIN gpkg_spatial_ref_sys s ON g.srs_id=s.srs_id WHERE g.table_name=?",
                (table,),
            ).fetchall()
            digest.update(json.dumps(spatial).encode())
        for row in db.execute(f"SELECT * FROM {quoted} ORDER BY rowid"):
            for value in row:
                raw = (
                    value
                    if isinstance(value, bytes)
                    else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
                )
                digest.update(
                    ("bytes" if isinstance(value, bytes) else "json").encode()
                )
                digest.update(len(raw).to_bytes(8, "big"))
                digest.update(raw)
    return digest.hexdigest()


@contextmanager
def version_lock(directory, *, wait=True):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(
                stream.fileno(), msvcrt.LK_LOCK if wait else msvcrt.LK_NBLCK, 1
            )
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _clone(source, destination):
    """Never hard-link: a task can change only its own independent inode."""
    if sys.platform == "linux":
        import fcntl

        try:
            with source.open("rb") as src, destination.open("xb") as dst:
                fcntl.ioctl(dst.fileno(), 0x40049409, src.fileno())
            return "copy_on_write"
        except OSError:
            destination.unlink(missing_ok=True)
    elif sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.clonefile(os.fsencode(source), os.fsencode(destination), 0) == 0:
            return "copy_on_write"
    shutil.copyfile(source, destination)
    return "file_copy"


def _raster_evidence(path):
    import numpy as np
    import rasterio

    with rasterio.open(path) as src:
        if src.count != 1 or src.crs is None:
            return None
        pixels = hashlib.sha256()
        row_step = max(1, 262144 // src.width)
        for mask in (False, True):
            for row in range(0, src.height, row_step):
                for col in range(0, src.width, 262144):
                    window = rasterio.windows.Window(
                        col,
                        row,
                        min(262144, src.width - col),
                        min(row_step, src.height - row),
                    )
                    values = src.read(1, window=window, masked=True)
                    pixels.update(
                        np.ma.getmaskarray(values).tobytes()
                        if mask
                        else values.filled(0).tobytes()
                    )
        return {
            "crs": src.crs.to_wkt(),
            "transform": list(src.transform),
            "shape": list(src.shape),
            "pixels": pixels.hexdigest(),
        }


def _read_manifest(directory):
    path = directory / "current.json"
    if not path.exists():
        return None
    try:
        if path.is_symlink():
            raise ValueError("manifest link")
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or not isinstance(
            value.get("authentication"), str
        ):
            raise ValueError("snapshot manifest")
        required = {
            "schema",
            "file",
            "checksum",
            "identity",
            "version",
            "source",
            "logical",
            "authentication",
        }
        if not required <= value.keys() or not constant_time_compare(
            value["authentication"], _manifest_authentication(value)
        ):
            raise ValueError("snapshot authentication")
        if value["schema"] != SCHEMA or not re.fullmatch(
            r"[a-f0-9]{64}\.(?:tif|gpkg|csv)", value["file"]
        ):
            raise ValueError("snapshot manifest")
        if _stat(directory / value["file"]) != value["identity"]:
            raise ValueError("snapshot identity")
        if value["checksum"] != value["file"].split(".")[0]:
            raise ValueError("snapshot hash")
        return value
    except (OSError, ValueError, KeyError, TypeError, ComputeError) as exc:
        path.unlink(missing_ok=True)
        raise ComputeError("输入版本缓存已变化，已停止复用；请重试以重新准备") from exc


def _manifest_authentication(metadata):
    payload = json.dumps(
        {key: value for key, value in metadata.items() if key != "authentication"},
        sort_keys=True,
        separators=(",", ":"),
    )
    return salted_hmac(
        "compute-input-version-v1", payload, algorithm="sha256"
    ).hexdigest()


def _write_manifest(directory, metadata):
    temporary = directory / "current.tmp"
    metadata["authentication"] = _manifest_authentication(metadata)
    temporary.write_text(json.dumps(metadata, ensure_ascii=False))
    temporary.chmod(0o600)
    temporary.replace(directory / "current.json")


def stage_version(resource, key, destination, materialize, expected_checksum=""):
    if destination.exists() or destination.is_symlink():
        raise ComputeError("任务输入目标已存在，请使用新的执行目录")
    source, table = _source(resource)
    directory = app_path(
        "cache",
        "compute-input-versions",
        str(resource.project_tag_id),
        str(resource.id),
    )
    dependencies = []
    if resource.data_type == "raster":
        import rasterio

        with rasterio.open(source) as stream:
            dependencies = [
                Path(value).resolve()
                for value in stream.files
                if Path(value).resolve() != source.resolve()
            ]
        dependencies += [
            Path(str(source) + suffix) for suffix in (".aux.xml", ".msk", ".ovr")
        ]
        dependencies += [
            source.with_suffix(suffix) for suffix in (".tfw", ".wld", ".prj")
        ]
        dependencies = sorted(set(dependencies))
    version = {
        "resource": resource.id,
        "project": resource.project_tag_id,
        "revision": resource.updated_at.isoformat(),
        "kind": resource.data_type,
        "format": resource.file_format,
        "storage": resource.storage_path,
    }
    evidence_requested = (
        resource.data_type == "raster" and key.removeprefix("before_") in MINERALS
    )
    with version_lock(directory):
        before = _source_identity(source, dependencies)
        previous = _read_manifest(directory)
        logical = None
        reused = bool(
            previous and previous["version"] == version and previous["source"] == before
        )
        if previous and previous["version"] == version and not reused and table:
            logical = _table_digest(source, table, resource.data_type == "vector")
            reused = logical == previous.get("logical")
        if reused:
            metadata = dict(previous)
            metadata["source"] = before
            canonical = directory / metadata["file"]
        else:
            with tempfile.TemporaryDirectory(
                prefix="build-", dir=directory
            ) as temporary:
                path = Path(temporary) / ("input" + destination.suffix)
                materialize(path)
                with path.open("rb") as stream:
                    checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                if expected_checksum and checksum != expected_checksum:
                    raise ComputeError("输入内容已变化，不能在原任务中自动重做")
                if table and logical is None:
                    logical = _table_digest(
                        source, table, resource.data_type == "vector"
                    )
                if _source_identity(source, dependencies) != before:
                    raise ComputeError("输入文件在准备期间发生变化，请重试")
                canonical = directory / (checksum + destination.suffix)
                if not (
                    previous
                    and previous["file"] == canonical.name
                    and canonical.exists()
                    and _stat(canonical) == previous["identity"]
                ):
                    path.chmod(0o400)
                    path.replace(canonical)
                metadata = {
                    "schema": SCHEMA,
                    "version": version,
                    "source": before,
                    "logical": logical,
                    "checksum": checksum,
                    "file": canonical.name,
                    "identity": _stat(canonical),
                }
        if expected_checksum and metadata["checksum"] != expected_checksum:
            raise ComputeError("输入内容已变化，不能在原任务中自动重做")
        if evidence_requested and "rasterEvidence" not in metadata:
            metadata["rasterEvidence"] = _raster_evidence(canonical)
        if _source_identity(source, dependencies) != before:
            raise ComputeError("输入文件在准备期间发生变化，请重试")
        method = _clone(canonical, destination)
        destination.chmod(0o444)
        if (
            _stat(canonical) != metadata["identity"]
            or destination.stat().st_size != canonical.stat().st_size
        ):
            destination.unlink(missing_ok=True)
            raise ComputeError("输入版本在传递期间变化，请重新准备")
        _write_manifest(directory, metadata)
        for old in directory.iterdir():
            if (
                old.name not in {canonical.name, "current.json", ".lock"}
                and old.is_file()
                and not old.is_symlink()
            ):
                old.unlink(missing_ok=True)
        identity = destination.stat()
        return {
            "sha256": metadata["checksum"],
            "verifiedEvidence": {
                "schemaVersion": 1,
                "fileIdentity": [
                    identity.st_ino,
                    identity.st_size,
                    identity.st_mtime_ns,
                    identity.st_ctime_ns,
                    identity.st_mode,
                ],
                "raster": metadata.get("rasterEvidence"),
            },
            "preparation": {"reused": reused, "copyMethod": method},
        }


def clean_versions(maximum_bytes, retention_days):
    root = app_path("cache", "compute-input-versions")
    manifests = sorted(
        root.glob("*/*/current.json"), key=lambda path: path.stat().st_mtime
    )
    sizes = {}
    for path in manifests:
        sizes[path] = sum(
            item.stat().st_size
            for item in path.parent.iterdir()
            if item.is_file() and item.name != ".lock"
        )
    total = sum(sizes.values())
    for path in manifests:
        if (
            total <= maximum_bytes
            and path.stat().st_mtime >= time.time() - retention_days * 86400
        ):
            continue
        try:
            with version_lock(path.parent, wait=False):
                for item in path.parent.iterdir():
                    if item.is_file() and item.name != ".lock":
                        item.unlink(missing_ok=True)
            total -= sizes[path]
        except (OSError, BlockingIOError):
            continue
