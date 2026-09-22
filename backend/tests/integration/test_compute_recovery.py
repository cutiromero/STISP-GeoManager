from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
import pytest

from apps.catalog.models import DataResource
from apps.compute.models import (
    ComputeTask,
    ComputeAttempt,
    ComputeOutput,
    ComputeImport,
)
from apps.compute.worker import (
    recover,
    clean_expired,
    run_task,
    task_scope,
    process_import,
)
from apps.compute.data import inspect_output
from apps.compute.packages import checksum
from apps.core.storage import app_path
from . import test_compute as shared

setup_compute = shared.setup_compute
post = shared.post


def make_output(env, kind, name):
    task = ComputeTask.objects.get(pk=post(env, "tasks/").json()["id"])
    ComputeTask.objects.filter(pk=task.pk).update(status="succeeded")
    path = app_path(
        "projects", str(task.project_tag_id), "compute", "outputs", str(task.id), name
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return task, path


def test_recovery_stops_old_container_and_only_restarts_once(setup_compute):
    env = setup_compute
    task = ComputeTask.objects.get(pk=post(env, "tasks/").json()["id"])
    ComputeTask.objects.filter(pk=task.pk).update(
        status="running", attempt_token="a" * 32
    )
    for token in ["a", "b"]:
        ComputeAttempt.objects.create(
            task=task,
            token=token * 32,
            container_name="gm-compute-" + token * 32,
            runtime_digest=task.version.runtime_digest,
        )
        with patch("apps.compute.worker.stop_container") as stop:
            recover()
        stop.assert_called_once()
        task.refresh_from_db()
        assert task.status == ("queued" if token == "a" else "interrupted")
        if token == "a":
            ComputeTask.objects.filter(pk=task.pk).update(status="running")
    assert task.attempts.count() == 2


def test_expiration_preserves_resource_and_refuses_download(setup_compute):
    env = setup_compute
    task, path = make_output(env, "table", "result.csv")
    path.write_text("value\n1\n", encoding="utf-8")
    output = ComputeOutput.objects.create(
        task=task,
        key="result",
        label="结果",
        kind="table",
        file_name=path.name,
        path=path.relative_to(app_path()).as_posix(),
        size_bytes=path.stat().st_size,
        checksum=checksum(path),
        metadata={"fields": ["value"], "rows": 1},
    )
    ComputeOutput.objects.filter(pk=output.pk).update(
        created_at=timezone.now() - timedelta(days=8)
    )
    ComputeImport.objects.create(
        output=output,
        requested_by=env["owner"],
        name="已入库",
        resource=env["resource"],
        status="ready",
    )
    clean_expired(force=True)
    output.refresh_from_db()
    assert output.expired and not path.exists()
    assert DataResource.objects.filter(pk=env["resource"].id).exists()
    assert (
        env["client"]
        .get(
            f"/api/compute/outputs/{output.id}/file/",
            HTTP_X_PROJECT_ID=str(env["project"].id),
        )
        .status_code
        == 404
    )


def test_invalid_output_is_not_a_success(setup_compute):
    env = setup_compute
    task = ComputeTask.objects.get(pk=post(env, "tasks/").json()["id"])

    def invalid(attempt, package, inputs, results, manifest, heartbeat):
        (results / "summary.csv").write_text("a,b\n1,2,3\n", encoding="utf-8")

    with task_scope(task), patch("apps.compute.worker.execute", invalid):
        run_task(task)
    task.refresh_from_db()
    assert task.status == "failed"
    assert not task.outputs.exists()


@pytest.mark.parametrize(
    "kind,filename", [("vector", "buffer.gpkg"), ("raster", "computed.tif")]
)
def test_spatial_results_import_in_original_project(setup_compute, kind, filename):
    env = setup_compute
    task, path = make_output(env, kind, filename)
    if kind == "vector":
        import geopandas as gpd
        from shapely.geometry import Point

        gpd.GeoDataFrame({"value": [1]}, geometry=[Point(80, 40)], crs=4326).to_file(
            path, layer="result", driver="GPKG"
        )
    else:
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin

        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=2,
            height=2,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(80, 40, 0.01, 0.01),
            nodata=-9999,
        ) as dst:
            dst.write(np.array([[1, 2], [3, 4]], dtype="float32"), 1)
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
        output=output, requested_by=env["owner"], name="空间计算结果"
    )
    with task_scope(task):
        process_import(record)
    record.refresh_from_db()
    assert record.status == "ready", record.error
    assert record.resource.project_tag_id == task.project_tag_id
    assert record.resource.data_type == kind
    assert record.resource.coordinate_system
