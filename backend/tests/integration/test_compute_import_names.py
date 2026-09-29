"""Repeated calculations must produce independently importable result names."""

import pytest

from apps.catalog.models import DataResource
from apps.compute.models import ComputeImport, ComputeOutput
from apps.compute.data import inspect_output
from apps.compute.packages import checksum
from apps.compute.services import request_output_import
from apps.compute.worker import process_import, task_scope
from apps.core.storage import app_path
from . import test_compute as shared
from .test_compute_recovery import make_output

setup_compute = shared.setup_compute
pytestmark = pytest.mark.django_db


def test_repeated_goal_vector_outputs_import_with_distinct_stable_names(setup_compute):
    import geopandas as gpd
    from shapely.geometry import Point

    env = setup_compute
    records = []
    initial_resources = DataResource.objects.count()
    for index in range(2):
        env["body"]["idempotencyKey"] = f"repeated-vector-{index}"
        task, path = make_output(env, "vector", "buffer.gpkg")
        task.refresh_from_db()
        gpd.GeoDataFrame({"value": [1]}, geometry=[Point(80, 40)], crs=4326).to_file(
            path, layer="result", driver="GPKG"
        )
        output = ComputeOutput.objects.create(
            task=task,
            key="result",
            label="缓冲区结果",
            kind="vector",
            file_name=path.name,
            path=path.relative_to(app_path()).as_posix(),
            size_bytes=path.stat().st_size,
            checksum=checksum(path),
            metadata=inspect_output(path, "vector"),
        )
        with task_scope(task):
            record = request_output_import(env["owner"], output)
            repeated = request_output_import(env["owner"], output)
            assert repeated.id == record.id
            assert repeated.name == record.name
            process_import(record)
            record.refresh_from_db()
            assert record.status == "ready", record.error
            assert request_output_import(env["owner"], output).name == record.name
        records.append(record)
    assert records[0].name != records[1].name
    assert records[0].resource_id != records[1].resource_id
    assert DataResource.objects.count() == initial_resources + 2
    assert ComputeImport.objects.count() == 2


def test_default_name_is_bounded_and_explicit_name_is_preserved(setup_compute):
    env = setup_compute
    task, _ = make_output(env, "table", "result.csv")
    task.refresh_from_db()
    task.name = "长任务名称" * 32
    task.save(update_fields=["name"])
    output = ComputeOutput.objects.create(
        task=task,
        key="result",
        label="长结果名称" * 32,
        kind="table",
        file_name="result.csv",
        path="unused.csv",
        size_bytes=0,
        checksum="a" * 64,
    )
    with task_scope(task):
        record = request_output_import(env["owner"], output)
        assert len(record.name) <= 160
        assert record.name.endswith(f"[{task.id.hex[:8]}/{output.id}]")
        explicit = request_output_import(env["owner"], output, "用户指定名称")
        assert explicit.name == "用户指定名称"
        assert request_output_import(env["owner"], output).name == "用户指定名称"


def test_default_retry_upgrades_failed_legacy_name_without_new_record(setup_compute):
    env = setup_compute
    task, _ = make_output(env, "table", "result.csv")
    task.refresh_from_db()
    output = ComputeOutput.objects.create(
        task=task,
        key="result",
        label="结果",
        kind="table",
        file_name="result.csv",
        path="unused.csv",
        size_bytes=0,
        checksum="a" * 64,
    )
    legacy_name = task.name + " · " + output.label
    record = ComputeImport.objects.create(
        output=output,
        requested_by=env["owner"],
        name=legacy_name,
        status="failed",
        error="数据名称已存在",
    )
    with task_scope(task):
        retried = request_output_import(env["owner"], output)
    assert retried.id == record.id
    assert retried.status == "queued"
    assert retried.error == ""
    assert retried.name != legacy_name
    assert retried.name.endswith(f"[{task.id.hex[:8]}/{output.id}]")
