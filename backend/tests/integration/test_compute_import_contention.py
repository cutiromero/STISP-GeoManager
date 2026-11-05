"""Transient SQLite contention preserves completed imports and their identity."""

import hashlib
import sqlite3
from unittest.mock import patch

import pytest
from django.db import OperationalError

from apps.catalog.models import DataResource, DictionaryItem, VectorDataset
from apps.compute.data import inspect_output
from apps.compute.models import ComputeImport, ComputeOutput, ComputeTask
from apps.compute.packages import ComputeError, checksum
from apps.compute.worker import process_import, task_scope
from apps.core.storage import app_path, vector_geopackage_path
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_compute_recovery import make_output


def sqlite_error(code):
    underlying = sqlite3.OperationalError("database is locked")
    underlying.sqlite_errorcode = code
    error = OperationalError("database is locked")
    error.__cause__ = underlying
    return error


def make_import(env, kind="table"):
    task, path = make_output(
        env, kind, "result.gpkg" if kind == "vector" else "result.csv"
    )
    if kind == "vector":
        import geopandas as gpd
        from shapely.geometry import Polygon

        gpd.GeoDataFrame(
            {"label": ["source"], "value": [7]},
            geometry=[Polygon([(80, 40), (80.01, 40), (80.01, 40.01), (80, 40)])],
            crs=4326,
        ).to_file(path, layer="result", driver="GPKG", index=False)
    else:
        path.write_text("label,value\nsource,7\n", encoding="utf-8")
    output = ComputeOutput.objects.create(
        task=task,
        key="result",
        label="结果",
        kind=kind,
        file_name=path.name,
        path=path.relative_to(app_path()).as_posix(),
        size_bytes=path.stat().st_size,
        checksum=checksum(path),
        metadata=inspect_output(path, kind),
    )
    record = ComputeImport.objects.create(
        output=output, requested_by=env["owner"], name="锁竞争恢复结果"
    )
    return task, record


@pytest.mark.django_db(transaction=True)
def test_busy_after_vector_commit_reuses_resource_and_physical_layer(setup_compute):  # noqa: F811
    env = setup_compute
    # Do not depend on migration seed data surviving prior transactional tests.
    DictionaryItem.objects.update_or_create(
        dict_type=DictionaryItem.DictType.DATA_CATEGORY,
        code="compute_results",
        defaults={"name": "计算结果", "is_active": True, "is_selectable": False},
    )
    task, record = make_import(env, "vector")
    table_name = f"compute_{record.storage_key.hex}"
    saved = DataResource.save
    partial, requeued = [], []
    before_tasks = ComputeTask.objects.count()

    def block_first_finalization(resource, *args, **kwargs):
        if {"source", "description", "status"} <= set(
            kwargs.get("update_fields") or []
        ) and not partial:
            row = DataResource.objects.get(pk=resource.pk)
            assert row.source == "用户导入"
            assert row.storage_path == table_name
            with sqlite3.connect(vector_geopackage_path()) as db:
                geometry = db.execute(f'SELECT geom FROM "{table_name}"').fetchone()[0]
            partial.append((row.pk, hashlib.sha256(geometry).hexdigest()))
            raise sqlite_error(sqlite3.SQLITE_BUSY_SNAPSHOT)
        return saved(resource, *args, **kwargs)

    def observe_requeue(seconds):
        current = ComputeImport.objects.get(pk=record.pk)
        assert current.status == "queued" and current.resource_id is None
        assert DataResource.objects.filter(storage_path=table_name).count() == 1
        requeued.append(seconds)

    with (
        task_scope(task),
        patch.object(DataResource, "save", block_first_finalization),
        patch("apps.compute.worker.time.sleep", side_effect=observe_requeue),
    ):
        process_import(record)
        record.refresh_from_db()
        assert record.status == "ready", record.error
        assert record.resource_id == partial[0][0]
        assert record.resource.source == f"compute-output:{record.storage_key}"
        assert record.resource.is_compute_result
        assert record.resource.category.code == "compute_results"
        assert (
            DataResource.objects.filter(storage_path__startswith=table_name).count()
            == 1
        )
        assert VectorDataset.objects.filter(resource=record.resource).count() == 1
        assert record.resource.map_layers.count() == 1
        with sqlite3.connect(vector_geopackage_path()) as db:
            layers = db.execute(
                "SELECT table_name FROM gpkg_contents WHERE table_name LIKE ?",
                (table_name + "%",),
            ).fetchall()
            geometry = db.execute(f'SELECT geom FROM "{table_name}"').fetchone()[0]
        assert layers == [(table_name,)]
        assert hashlib.sha256(geometry).hexdigest() == partial[0][1]
    assert requeued == [0.2]
    assert ComputeTask.objects.count() == before_tasks
    assert task.attempts.count() == 0  # Retry only imported the existing output.
    assert checksum(app_path(record.output.path)) == record.output.checksum


def test_busy_retry_limit_is_finite(setup_compute):  # noqa: F811
    task, record = make_import(setup_compute)
    with (
        task_scope(task),
        patch(
            "apps.compute.worker.import_output",
            side_effect=sqlite_error(sqlite3.SQLITE_BUSY),
        ) as importer,
        patch("apps.compute.worker.time.sleep") as sleep,
    ):
        process_import(record)
    record.refresh_from_db()
    assert record.status == "failed"
    assert "自动重试已用完" in record.error
    assert importer.call_count == 4
    assert [call.args[0] for call in sleep.call_args_list] == [0.2, 0.5, 1.0]


def test_locked_retry_can_complete(setup_compute):  # noqa: F811
    env = setup_compute
    task, record = make_import(env)
    with (
        task_scope(task),
        patch(
            "apps.compute.worker.import_output",
            side_effect=[sqlite_error(sqlite3.SQLITE_LOCKED), env["resource"]],
        ) as importer,
        patch("apps.compute.worker.time.sleep") as sleep,
    ):
        process_import(record)
    record.refresh_from_db()
    assert record.status == "ready" and record.resource_id == env["resource"].pk
    assert importer.call_count == 2 and sleep.call_count == 1


@pytest.mark.parametrize(
    "error",
    [
        ComputeError("输入格式无效"),
        OperationalError("database is locked"),  # Wording alone is not a SQLite code.
        sqlite_error(sqlite3.SQLITE_IOERR),
    ],
)
def test_other_failures_are_not_retried(setup_compute, error):  # noqa: F811
    task, record = make_import(setup_compute)
    with (
        task_scope(task),
        patch("apps.compute.worker.import_output", side_effect=error) as importer,
        patch("apps.compute.worker.time.sleep") as sleep,
    ):
        process_import(record)
    record.refresh_from_db()
    assert record.status == "failed"
    importer.assert_called_once()
    sleep.assert_not_called()


def test_retry_refreshes_actor_permissions(setup_compute):  # noqa: F811
    env = setup_compute
    task, record = make_import(env)

    def deactivate(_seconds):
        type(env["owner"]).objects.filter(pk=env["owner"].pk).update(is_active=False)

    with (
        task_scope(task),
        patch(
            "apps.compute.worker.import_output",
            side_effect=sqlite_error(sqlite3.SQLITE_BUSY),
        ) as importer,
        patch("apps.compute.worker.time.sleep", side_effect=deactivate),
    ):
        process_import(record)
    record.refresh_from_db()
    assert record.status == "failed" and "账号可能已停用" in record.error
    importer.assert_called_once()


def test_retry_rechecks_automatic_intent(setup_compute):  # noqa: F811
    task, record = make_import(setup_compute)
    with (
        task_scope(task),
        patch(
            "apps.agent.compute_tools.validate_import_intent",
            side_effect=[None, ComputeError("自动入库意图已失效")],
        ) as validate,
        patch(
            "apps.compute.worker.import_output",
            side_effect=sqlite_error(sqlite3.SQLITE_BUSY),
        ) as importer,
        patch("apps.compute.worker.time.sleep"),
    ):
        process_import(record)
    record.refresh_from_db()
    assert record.status == "failed" and "自动入库意图已失效" in record.error
    assert validate.call_count == 2
    importer.assert_called_once()
