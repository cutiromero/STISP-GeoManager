"""All managed datasets share version evidence; external files remain strict."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from unittest.mock import patch

import pytest

from apps.compute import packages
from apps.core import file_evidence

pytestmark = pytest.mark.efficiency


@pytest.fixture
def managed(settings, tmp_path):
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=tmp_path / "app",
        research_data_root=tmp_path / "research",
    )
    settings.SECRET_KEY = "unit-only-file-evidence-key"
    root = settings.PROJECT_CONFIG.app_data
    root.mkdir()
    return root


@pytest.mark.parametrize(
    "name", ["different.csv", "structure.gpkg", "mineral.tif", "operator.zip"]
)
def test_every_file_type_reuses_verified_content_across_operations(managed, name):
    path = managed / name
    path.write_bytes(b"unmodified scientific bytes")
    with patch.object(
        packages.hashlib, "file_digest", wraps=hashlib.file_digest
    ) as read:
        with packages.checksum_scope() as first:
            expected = packages.checksum(path)
        with packages.checksum_scope() as second:
            assert packages.checksum(path) == expected
        assert packages.checksum(path) == expected
    assert read.call_count == 1
    assert first.reads == 1 and second.reads == 0 and second.version_reuses == 1
    assert path.read_bytes() == b"unmodified scientific bytes"


def test_same_size_edit_restored_mtime_replacement_and_mode_changes_invalidate(managed):
    path = managed / "data.csv"
    path.write_bytes(b"before")
    with patch.object(
        packages.hashlib, "file_digest", wraps=hashlib.file_digest
    ) as read:
        first = packages.checksum(path)
        original = path.stat()
        path.write_bytes(b"edited")
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        second = packages.checksum(path)
        replacement = managed / "replacement"
        replacement.write_bytes(b"third!")
        replacement.replace(path)
        third = packages.checksum(path)
        path.chmod(0o400)
        assert packages.checksum(path) == third
    assert len({first, second, third}) == 3 and read.call_count == 4


def test_corrupt_or_forged_receipt_rebuilds_instead_of_granting_trust(managed):
    path = managed / "data.csv"
    path.write_bytes(b"actual")
    expected = packages.checksum(path)
    receipt = next((managed / "cache/file-evidence").glob("*/*.json"))
    value = json.loads(receipt.read_text())
    value["value"]["sha256"] = "0" * 64
    receipt.write_text(json.dumps(value))
    with patch.object(
        packages.hashlib, "file_digest", wraps=hashlib.file_digest
    ) as read:
        assert packages.checksum(path) == expected
    assert read.call_count == 1


def test_force_verification_and_external_files_read_actual_content(managed, tmp_path):
    path = managed / "managed"
    path.write_bytes(b"content")
    external = tmp_path / "external"
    external.write_bytes(b"external")
    packages.checksum(path)
    with patch.object(
        packages.hashlib, "file_digest", wraps=hashlib.file_digest
    ) as read:
        packages.checksum(path, force=True)
        packages.checksum(external)
        packages.checksum(external)
    assert read.call_count == 3


def test_file_changed_during_hash_is_not_certified(managed, monkeypatch):
    path = managed / "data.csv"
    path.write_bytes(b"before")
    original = hashlib.file_digest

    def change(stream, algorithm):
        result = original(stream, algorithm)
        path.write_bytes(b"edited")
        return result

    monkeypatch.setattr(packages.hashlib, "file_digest", change)
    with pytest.raises(packages.ComputeError, match="校验过程中发生变化"):
        packages.checksum(path)
    assert not list((managed / "cache/file-evidence").glob("*/*.json"))


def test_concurrent_cold_requests_compute_one_file_digest(managed):
    path = managed / "large.tif"
    path.write_bytes(b"content" * 1000)
    barrier = threading.Barrier(3)
    original = hashlib.file_digest
    calls = []

    def observed(stream, algorithm):
        calls.append(1)
        time.sleep(0.05)
        return original(stream, algorithm)

    def request():
        barrier.wait(timeout=5)
        return packages.checksum(path)

    with (
        patch.object(packages.hashlib, "file_digest", observed),
        ThreadPoolExecutor(2) as pool,
    ):
        jobs = [pool.submit(request) for _ in range(2)]
        barrier.wait(timeout=5)
        assert jobs[0].result() == jobs[1].result()
    assert len(calls) == 1


def test_receipt_survives_process_exit_but_not_a_different_signing_key(managed):
    path = managed / "immutable.csv"
    path.write_bytes(b"bytes")
    packages.checksum(path)
    source = """
from pathlib import Path
from types import SimpleNamespace
import json,sys
from django.conf import settings
settings.configure(SECRET_KEY=sys.argv[3], PROJECT_CONFIG=SimpleNamespace(app_data=Path(sys.argv[1]), research_data_root=Path(sys.argv[1]).parent/'research'))
from apps.compute.packages import checksum,checksum_scope
with checksum_scope() as evidence:
 checksum(Path(sys.argv[2]))
 print(json.dumps({'reads':evidence.reads,'reuses':evidence.version_reuses}))
"""

    def child(key):
        output = subprocess.check_output(
            [sys.executable, "-c", source, str(managed), str(path), key], text=True
        )
        return json.loads(output)

    assert child("unit-only-file-evidence-key") == {"reads": 0, "reuses": 1}
    assert child("different-unit-key") == {"reads": 1, "reuses": 0}


def test_unavailable_receipt_storage_falls_back_to_actual_hash(managed):
    path = managed / "data.csv"
    path.write_bytes(b"actual")
    with patch.object(
        file_evidence, "write_receipt", side_effect=OSError("cache unavailable")
    ):
        assert packages.checksum(path) == hashlib.sha256(b"actual").hexdigest()
    assert not list((managed / "cache/file-evidence").glob("*/*.json"))


def test_symlink_does_not_reuse_target_receipt(managed):
    path = managed / "data.csv"
    path.write_bytes(b"actual")
    expected = packages.checksum(path)
    link = managed / "link.csv"
    link.symlink_to(path)
    with patch.object(
        packages.hashlib, "file_digest", wraps=hashlib.file_digest
    ) as read:
        assert packages.checksum(link) == expected
        assert packages.checksum(link) == expected
    assert read.call_count == 2
