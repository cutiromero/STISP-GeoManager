from concurrent.futures import ThreadPoolExecutor
import os

import pytest

from apps.compute import packages

pytestmark = pytest.mark.efficiency


def test_unchanged_content_is_hashed_once_per_operation_and_nested_scope(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"scientific data")
    with packages.checksum_scope() as first:
        expected = packages.checksum(path)
        with packages.checksum_scope() as nested:
            assert nested is first and packages.checksum(path) == expected
        assert (first.reads, first.reuses, first.bytes_read) == (
            1,
            1,
            path.stat().st_size,
        )
    with packages.checksum_scope() as second:
        assert packages.checksum(path) == expected
        assert second is not first and second.reads == 1 and second.reuses == 0


def test_same_size_edit_with_restored_mtime_and_file_replacement_rehashes(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"before")
    with packages.checksum_scope() as scope:
        first = packages.checksum(path)
        original = path.stat()
        path.write_bytes(b"edited")
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        second = packages.checksum(path)
        replacement = tmp_path / "replacement.bin"
        replacement.write_bytes(b"third!")
        replacement.replace(path)
        third = packages.checksum(path)
        assert len({first, second, third}) == 3 and scope.reads == 3


def test_changed_file_during_hash_is_rejected_and_never_cached(tmp_path, monkeypatch):
    path = tmp_path / "data.bin"
    path.write_bytes(b"before")
    original = packages.hashlib.file_digest

    def change(stream, algorithm):
        result = original(stream, algorithm)
        path.write_bytes(b"edited")
        return result

    monkeypatch.setattr(packages.hashlib, "file_digest", change)
    with (
        packages.checksum_scope() as scope,
        pytest.raises(packages.ComputeError, match="校验过程中发生变化"),
    ):
        packages.checksum(path)
    assert not scope.cache


def test_worker_threads_do_not_share_checksum_scopes(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"content")
    with packages.checksum_scope() as parent:
        packages.checksum(path)

        def worker():
            with packages.checksum_scope() as child:
                packages.checksum(path)
                return child

        with ThreadPoolExecutor(max_workers=1) as pool:
            child = pool.submit(worker).result()
        assert child is not parent and child.reads == parent.reads == 1


def test_scope_is_discarded_after_failure_and_no_scope_remains_strict(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"original")
    with pytest.raises(RuntimeError), packages.checksum_scope():
        packages.checksum(path)
        raise RuntimeError("stop")
    assert packages._CHECKSUM_VERIFICATION.get() is None
    path.write_bytes(b"different")
    assert packages.checksum(path) == packages.hashlib.sha256(b"different").hexdigest()
