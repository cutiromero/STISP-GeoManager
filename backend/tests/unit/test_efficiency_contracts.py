"""Operation-count regressions: reuse computation, never authorization or identity."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from apps.catalog import display_geometry as display
from apps.compute.input_versions import _raster_evidence
from apps.compute import input_versions
from apps.core.storage_locks import storage_lock, StorageLockTimeout

pytestmark = pytest.mark.efficiency


def test_concurrent_display_miss_computes_once_and_cache_hits_use_no_slot(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(display, "app_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(
        display, "vector_geopackage_path", lambda: tmp_path / "source.gpkg"
    )
    resource = SimpleNamespace(
        id=585,
        data_type="vector",
        storage_path="base",
        updated_at=datetime.now(timezone.utc),
    )
    payload = {"displayGeometry": True, "limit": 100}
    release = threading.Event()
    second_lock = threading.Event()
    computing = threading.Event()
    lock_count = []
    real_lock = display.storage_lock

    @contextmanager
    def observed_lock(*args, **kwargs):
        lock_count.append(1)
        if len(lock_count) == 2:
            second_lock.set()
        with real_lock(*args, **kwargs):
            yield

    monkeypatch.setattr(display, "storage_lock", observed_lock)
    calls = Mock()

    def compute():
        calls()
        computing.set()
        assert release.wait(5)
        return {"elapsedMs": 1, "value": "actual display"}

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(display.cached_display_query, resource, payload, compute)
        second = pool.submit(display.cached_display_query, resource, payload, compute)
        try:
            assert second_lock.wait(5)
            assert computing.wait(5)
            assert calls.call_count == 1
        finally:
            release.set()
        assert first.result()["value"] == second.result()["value"]
    assert calls.call_count == 1
    assert (
        display.cached_display_query(
            resource, payload, Mock(side_effect=AssertionError("unexpected compute"))
        )["value"]
        == "actual display"
    )


def test_failed_display_work_releases_the_lock_and_does_not_cache_failure(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(display, "app_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(
        display, "vector_geopackage_path", lambda: tmp_path / "source.gpkg"
    )
    resource = SimpleNamespace(
        id=1,
        data_type="vector",
        storage_path="base",
        updated_at=datetime.now(timezone.utc),
    )
    with pytest.raises(RuntimeError):
        display.cached_display_query(
            resource,
            {"displayGeometry": True},
            Mock(side_effect=RuntimeError("failed")),
        )
    assert display.cached_display_query(
        resource, {"displayGeometry": True}, lambda: {"ok": True}
    )["ok"]


def test_new_revision_is_not_overwritten_by_an_older_pending_computation(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(display, "app_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(
        display, "vector_geopackage_path", lambda: tmp_path / "source.gpkg"
    )
    old = SimpleNamespace(
        id=1,
        data_type="vector",
        storage_path="base",
        updated_at=datetime.now(timezone.utc),
    )
    current = SimpleNamespace(
        **{**vars(old), "updated_at": old.updated_at + timedelta(seconds=1)}
    )
    payload = {"displayGeometry": True}
    started = threading.Event()
    release = threading.Event()
    second = threading.Event()
    attempts = []
    real_lock = display.storage_lock

    @contextmanager
    def observed(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 2:
            second.set()
        with real_lock(*args, **kwargs):
            yield

    monkeypatch.setattr(display, "storage_lock", observed)

    def older():
        started.set()
        assert release.wait(5)
        return {"value": "old"}

    newer = Mock(return_value={"value": "new"})
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(display.cached_display_query, old, payload, older)
        assert started.wait(5)
        next_result = pool.submit(display.cached_display_query, current, payload, newer)
        try:
            assert second.wait(5)
            assert newer.call_count == 0
        finally:
            release.set()
        assert (
            first.result()["value"] == "old" and next_result.result()["value"] == "new"
        )
    assert (
        display.cached_display_query(
            current,
            payload,
            Mock(side_effect=AssertionError("new revision recomputed")),
        )["value"]
        == "new"
    )


def test_storage_lock_coordinates_processes_and_recovers_after_process_exit(tmp_path):
    path = tmp_path / "shared.lock"
    source = "from pathlib import Path; from apps.core.storage_locks import storage_lock; import sys\nwith storage_lock(Path(sys.argv[1])):\n print('ready',flush=True)\n sys.stdin.readline()\n"
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", source, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        with pytest.raises(StorageLockTimeout), storage_lock(path, timeout=0.02):
            pass
        process.terminate()
        process.wait(timeout=5)
        with storage_lock(path, timeout=0.1):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.parametrize("mask_kind", ["valid", "nodata", "dataset_mask"])
def test_raster_evidence_preserves_digest_and_never_decodes_pixels_for_mask_pass(
    tmp_path, monkeypatch, mask_kind
):
    path = tmp_path / "input.tif"
    values = np.arange(262160, dtype="float32").reshape(1, -1)
    if mask_kind == "nodata":
        values[0, 0] = np.nan
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=1,
        width=values.shape[1],
        count=1,
        dtype="float32",
        crs=4326,
        transform=from_origin(95, 36, 0.000001, 0.000001),
        nodata=np.nan if mask_kind == "nodata" else None,
    ) as out:
        out.write(values, 1)
        if mask_kind == "dataset_mask":
            mask = np.full(values.shape, 255, dtype="uint8")
            mask[0, 1] = 0
            out.write_mask(mask)
    before = path.read_bytes()
    expected = hashlib.sha256()
    real_open = rasterio.open
    with real_open(path) as src:
        for mask in [False, True]:
            for col in range(0, src.width, 262144):
                window = rasterio.windows.Window(
                    col, 0, min(262144, src.width - col), 1
                )
                data = src.read(1, window=window, masked=True)
                expected.update(
                    np.ma.getmaskarray(data).tobytes()
                    if mask
                    else data.filled(0).tobytes()
                )
    reads = Mock()
    mask_reads = Mock()
    spools = []
    real_spool = input_versions.tempfile.SpooledTemporaryFile

    def tracked_spool(*args, **kwargs):
        stream = real_spool(*args, **kwargs)
        spools.append(stream)
        return stream

    monkeypatch.setattr(input_versions, "MASK_SPOOL_MEMORY_BYTES", 1024)
    monkeypatch.setattr(input_versions.tempfile, "SpooledTemporaryFile", tracked_spool)

    class Reader:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.inner.close()

        def read(self, *args, **kwargs):
            reads()
            return self.inner.read(*args, **kwargs)

        def read_masks(self, *args, **kwargs):
            mask_reads()
            return self.inner.read_masks(*args, **kwargs)

    monkeypatch.setattr(
        rasterio, "open", lambda *args, **kwargs: Reader(real_open(*args, **kwargs))
    )
    evidence = _raster_evidence(path)
    assert evidence["pixels"] == expected.hexdigest()
    assert reads.call_count == 2 and mask_reads.call_count == 0
    assert spools and all(stream.closed and stream._rolled for stream in spools)
    assert path.read_bytes() == before
