"""Real source identities, full type inference and fresh admission checks."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sqlite3
import threading
from unittest.mock import patch

import pytest

from apps.compute import data, services
from apps.compute.packages import ComputeError
from apps.core.storage import app_path, table_data_path
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_compute import setup_compute  # noqa: F401

# ruff: noqa: F811
pytestmark = pytest.mark.efficiency


def scope(env):
    return project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    )


def test_preflight_and_submit_read_unchanged_metadata_once(setup_compute, monkeypatch):
    env = setup_compute
    reads = []
    original = data._read_candidate

    def read(resource, **options):
        reads.append(resource.pk)
        return original(resource, **options)

    monkeypatch.setattr(data, "_read_candidate", read)
    with scope(env):
        services.validate_submission(env["owner"], env["body"])
        task = services.submit(env["owner"], env["body"])
        again = services.validate_submission(env["owner"], env["body"])
    assert reads == [env["resource"].pk]
    assert task.parameters == again["parameters"]
    assert (
        task.input_records.get().snapshot["fields"]
        == again["resources"][0][2]["fields"]
    )


@pytest.mark.parametrize("change", ["revision", "file", "wal", "receipt"])
def test_changed_or_untrusted_metadata_is_read_again(
    setup_compute, monkeypatch, change
):
    env = setup_compute
    reads = []
    original = data._read_candidate

    def read(resource, **options):
        reads.append(resource.pk)
        return original(resource, **options)

    monkeypatch.setattr(data, "_read_candidate", read)
    with scope(env):
        data.candidate(env["resource"], semantic_metadata=True)
        if change == "revision":
            env["resource"].save(update_fields=["updated_at"])
        elif change in {"file", "wal"}:
            connection = sqlite3.connect(table_data_path("data.sqlite"))
            try:
                if change == "wal":
                    connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("ALTER TABLE samples ADD COLUMN extra REAL")
                connection.commit()
                actual = data.candidate(env["resource"], semantic_metadata=True)
                assert "extra" in actual["fields"]
            finally:
                connection.close()
        else:
            receipt = next(app_path("cache", "input-metadata").rglob("*.json"))
            envelope = json.loads(receipt.read_text())
            envelope["value"]["metadata"]["fields"] = ["forged"]
            receipt.write_text(json.dumps(envelope))
        if change not in {"file", "wal"}:
            actual = data.candidate(env["resource"], semantic_metadata=True)
        assert "forged" not in actual["fields"]
        assert len(reads) == 2


def test_csv_cache_preserves_full_column_types_and_detects_restored_mtime(
    setup_compute, monkeypatch
):
    env = setup_compute
    resource = deepcopy(env["resource"])
    resource.file_format, resource.storage_path = "CSV", "input-types.csv"
    from apps.catalog import nongeo

    with (
        scope(env),
        patch.object(
            nongeo, "_resource_dataframe", wraps=nongeo._resource_dataframe
        ) as reads,
    ):
        path = table_data_path("input-types.csv")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("name,value\na,1\nb,not-a-number\n")
        first = data.candidate(resource, semantic_metadata=True)
        assert first["fieldTypes"]["value"] == "string"
        assert data.candidate(resource, semantic_metadata=True) == first
        assert reads.call_count == 1
        previous = path.stat()
        path.write_text("name,value\na,1\nb,2\n")
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        assert (
            data.candidate(resource, semantic_metadata=True)["fieldTypes"]["value"]
            == "integer"
        )
        assert reads.call_count == 2


def test_warm_metadata_does_not_cache_resource_access(setup_compute, monkeypatch):
    env = setup_compute
    with scope(env):
        services.validate_submission(env["owner"], env["body"])
        env["resource"].owner_only = True
        env["resource"].maintainer = env["outsider"]
        env["resource"].save(update_fields=["owner_only", "maintainer", "updated_at"])
        monkeypatch.setattr(
            data, "candidate", lambda *_a, **_k: pytest.fail("no read after revocation")
        )
        with pytest.raises(ComputeError, match="无权访问"):
            services.validate_submission(env["owner"], env["body"])


def test_failed_or_changing_read_is_not_published(setup_compute, monkeypatch):
    env = setup_compute
    original = data._read_candidate

    def changing(resource, **options):
        result = original(resource, **options)
        with sqlite3.connect(table_data_path("data.sqlite")) as connection:
            connection.execute("ALTER TABLE samples ADD COLUMN extra REAL")
        return result

    with scope(env):
        monkeypatch.setattr(data, "_read_candidate", changing)
        with pytest.raises(ComputeError, match="预检期间变化"):
            data.candidate(env["resource"])
        assert not list(app_path("cache", "input-metadata").rglob("*.json"))
        monkeypatch.setattr(data, "_read_candidate", original)
        assert "extra" in data.candidate(env["resource"])["fields"]


def test_cache_write_failure_keeps_strict_read_path(setup_compute, monkeypatch):
    from apps.compute import input_metadata

    env = setup_compute
    monkeypatch.setattr(
        input_metadata,
        "write_receipt",
        lambda *_: (_ for _ in ()).throw(OSError("full")),
    )
    with scope(env):
        assert (
            data.candidate(env["resource"])["fields"]
            == data.candidate(env["resource"])["fields"]
        )


def test_concurrent_preflight_shares_one_metadata_read(setup_compute, monkeypatch):
    env = setup_compute
    original = data._read_candidate
    started, release = threading.Event(), threading.Event()
    reads = []

    def read(resource, **options):
        reads.append(resource.pk)
        started.set()
        assert release.wait(5)
        return original(resource, **options)

    def candidate():
        with scope(env):
            return data.candidate(env["resource"], semantic_metadata=True)

    monkeypatch.setattr(data, "_read_candidate", read)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(candidate)
        assert started.wait(5)
        second = pool.submit(candidate)
        release.set()
        assert first.result(timeout=10) == second.result(timeout=10)
    assert reads == [env["resource"].pk]
