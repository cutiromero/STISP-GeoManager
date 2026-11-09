"""Dataset-independent result paging/statistics, with actual invalidation."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import csv
import hashlib
import sqlite3
import subprocess
import sys
import json
from unittest.mock import patch

import pytest

from apps.compute import result_reads
from apps.compute.packages import ComputeError, checksum

pytestmark = pytest.mark.efficiency


@pytest.fixture
def root(settings, tmp_path):
    settings.SECRET_KEY = "unit-only-result-read-key"
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=tmp_path / "app",
        research_data_root=tmp_path / "research",
    )
    path = settings.PROJECT_CONFIG.app_data
    path.mkdir()
    return path


def page(path, offset=0, limit=50, **kwargs):
    with result_reads.table_page(path, offset, limit, **kwargs) as value:
        return {**value, "rows": list(value["rows"])}


@pytest.mark.parametrize(
    "fields", [["id", "说明"], ["矿物", "面积", "等级"], ["A", "B", "C", "D"]]
)
def test_other_datasets_fields_and_multiline_rows_use_same_paging(root, fields):
    path = root / "different.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        rows = [
            {field: f'{i}:中文,"引号"\n换行' for field in fields} for i in range(1000)
        ]
        writer.writerows(rows)
    original = path.read_bytes()
    expected = hashlib.sha256(original).hexdigest()
    with patch.object(
        result_reads, "_index_table", wraps=result_reads._index_table
    ) as build:
        first = page(path, 0, 50, expected_checksum=expected)
        second = page(path, 765, 50, expected_checksum=expected)
        last = page(path, 990, 50, expected_checksum=expected)
        empty = page(path, 1000, 50, expected_checksum=expected)
    assert build.call_count == 1
    assert first["columns"] == fields and first["total"] == 1000
    assert first["rows"] == rows[:50] and second["rows"] == rows[765:815]
    assert last["rows"] == rows[990:] and empty["rows"] == []
    assert path.read_bytes() == original


def test_source_change_does_not_reuse_old_expected_version(root):
    path = root / "data.csv"
    path.write_text("a\n1\n")
    old = checksum(path)
    page(path, expected_checksum=old)
    path.write_text("a\n2\n")
    with pytest.raises(ComputeError, match="内容已变化"):
        page(path, expected_checksum=old)
    assert page(path, expected_checksum=checksum(path))["rows"] == [{"a": "2"}]


def test_index_tampering_rebuilds_instead_of_using_wrong_offsets(root):
    path = root / "data.csv"
    path.write_text("a\n1\n2\n")
    expected = page(path)
    index = next((root / "cache/result-reads").glob("*/rows.sqlite3"))
    with sqlite3.connect(index) as db:
        db.execute("UPDATE checkpoints SET position='0'")
    with patch.object(
        result_reads, "_index_table", wraps=result_reads._index_table
    ) as build:
        assert page(path) == expected
    assert build.call_count == 1


def test_failed_build_and_source_change_leave_no_published_index(root):
    path = root / "data.csv"
    path.write_text("a\n1\n")
    original = result_reads._index_table

    def changed(source, directory):
        result = original(source, directory)
        source.write_text("a\n2\n")
        return result

    with patch.object(result_reads, "_index_table", changed):
        with pytest.raises(ComputeError, match="读取期间发生变化"):
            page(path)
    assert not list((root / "cache/result-reads").glob("*/manifest.json"))
    assert not list((root / "cache/result-reads").glob(".building-*"))
    assert page(path)["rows"] == [{"a": "2"}]


def test_source_change_while_consuming_a_page_is_rejected(root):
    path = root / "data.csv"
    path.write_text("a\n1\n")
    with pytest.raises(ComputeError, match="读取期间发生变化"):
        with result_reads.table_page(path) as result:
            assert list(result["rows"]) == [{"a": "1"}]
            path.write_text("a\n2\n")


def test_other_project_and_other_task_files_do_not_share_wrong_indexes(root):
    first, second = root / "project1-task1.csv", root / "project2-task2.csv"
    first.write_text("a\n1\n")
    second.write_text("different\n2\n")
    with patch.object(
        result_reads, "_index_table", wraps=result_reads._index_table
    ) as build:
        for _ in range(2):
            assert page(first)["rows"] == [{"a": "1"}]
            assert page(second)["rows"] == [{"different": "2"}]
    assert build.call_count == 2


def test_simultaneous_readers_build_one_index(root):
    path = root / "data.csv"
    path.write_text("a\n1\n2\n")
    with (
        patch.object(
            result_reads, "_index_table", wraps=result_reads._index_table
        ) as build,
        ThreadPoolExecutor(2) as pool,
    ):
        jobs = [pool.submit(page, path) for _ in range(2)]
        assert jobs[0].result() == jobs[1].result()
    assert build.call_count == 1


@pytest.mark.parametrize("suffix", [".aux.xml", ".msk", ".ovr"])
def test_raster_statistics_reuse_and_sidecar_changes_invalidate(root, suffix):
    path = root / "any-mineral.tif"
    path.write_bytes(b"raster-source")
    info = {
        "size": [7, 9],
        "bands": [{"band": 1, "minimum": 0, "maximum": 8, "mean": 4}],
    }
    with patch(
        "apps.raster.services.gdal_ops.gdalinfo_json", return_value=info
    ) as read:
        assert result_reads.raster_statistics(path) == info
        assert result_reads.raster_statistics(path) == info
        assert read.call_count == 1
        path.with_name(path.name + suffix).write_bytes(b"new-sidecar")
        assert result_reads.raster_statistics(path) == info
        assert read.call_count == 2
    assert path.read_bytes() == b"raster-source"


def test_cache_cleanup_keeps_active_readers_and_never_deletes_sources(root):
    path = root / "data.csv"
    path.write_text("a\n1\n")
    with result_reads.table_page(path) as result:
        result_reads.clean_read_indexes(0, 0)
        assert list(result["rows"]) == [{"a": "1"}]
    assert list((root / "cache/result-reads").glob("*/manifest.json"))
    result_reads.clean_read_indexes(0, 0)
    assert not list((root / "cache/result-reads").glob("*/manifest.json"))
    assert path.read_text() == "a\n1\n"


def test_late_page_consumes_bounded_records_instead_of_scanning_all_rows(root):
    path = root / "large.csv"
    path.write_text("a\n" + "".join(f"{i}\n" for i in range(10000)))
    page(path)
    original = csv.DictReader
    consumed = []

    class Counted:
        def __init__(self, *args, **kwargs):
            self.reader = original(*args, **kwargs)

        def __iter__(self):
            return self

        def __next__(self):
            consumed.append(1)
            return next(self.reader)

    with patch.object(result_reads.csv, "DictReader", Counted):
        assert page(path, 9765, 50)["rows"][0] == {"a": "9765"}
    assert len(consumed) <= result_reads.CHECKPOINT_ROWS + 50


def test_another_process_reuses_the_same_version_index(root):
    path = root / "any-task.csv"
    path.write_text("field\noriginal\n")
    page(path)
    source = """
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,sys
from django.conf import settings
settings.configure(SECRET_KEY='unit-only-result-read-key',PROJECT_CONFIG=SimpleNamespace(app_data=Path(sys.argv[1]),research_data_root=Path(sys.argv[1]).parent/'research'))
from apps.compute import result_reads
with patch.object(result_reads,'_index_table',side_effect=AssertionError('unnecessary rebuild')):
 with result_reads.table_page(Path(sys.argv[2])) as value:
  print(json.dumps(list(value['rows'])))
"""
    output = subprocess.check_output(
        [sys.executable, "-c", source, str(root), str(path)], text=True
    )
    assert json.loads(output) == [{"field": "original"}]


def test_unwritable_index_cache_falls_back_without_losing_rows(root):
    path = root / "data.csv"
    path.write_text("a\n1\n2\n3\n")
    with patch.object(result_reads, "_index_table", side_effect=OSError("cache full")):
        result = page(path, 1, 1)
    assert result["total"] == 3 and result["rows"] == [{"a": "2"}]
