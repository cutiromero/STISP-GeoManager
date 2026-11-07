"""Input reuse never reuses permissions or gives algorithms shared writable data."""

# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import patch

import geopandas as gpd
import pytest

from apps.compute.data import freeze_input
from apps.compute.input_versions import stage_version, clean_versions
from apps.compute.models import ComputeInput
from apps.compute.packages import ComputeError, checksum
from apps.core.storage import app_path
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_compute_vector_freeze import vector_input, export_to  # noqa: F401

pytestmark = pytest.mark.django_db


def test_warm_version_is_not_reexported_and_task_files_are_independent(vector_input):
    record, _, root = vector_input
    first, first_path = export_to(record, root, "first")
    with patch(
        "apps.compute.data._materialize_input",
        side_effect=AssertionError("Repeated export"),
    ):
        second, second_path = export_to(record, root, "second")
    assert not first["preparation"]["reused"] and second["preparation"]["reused"]
    assert first_path.stat().st_ino != second_path.stat().st_ino
    assert second_path.stat().st_mode & 0o222 == 0
    second_path.chmod(0o644)
    second_path.write_bytes(b"algorithm changed its own input")
    third, third_path = export_to(record, root, "third")
    assert (
        third["preparation"]["reused"]
        and third_path.read_bytes() == first_path.read_bytes()
    )
    assert checksum(third_path) == first["sha256"]


def test_unrelated_geopackage_changes_reuse_only_the_selected_layer(vector_input):
    record, source, root = vector_input
    first, _ = export_to(record, root, "first")
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE unrelated (private_text TEXT)")
        db.execute("INSERT INTO unrelated VALUES ('never delivered')")
    with patch(
        "apps.compute.data._materialize_input",
        side_effect=AssertionError("Repeated export"),
    ):
        second, path = export_to(record, root, "second")
    assert second["preparation"]["reused"] and second["sha256"] == first["sha256"]
    with sqlite3.connect(path) as db:
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='unrelated'"
        ).fetchall()


def test_cache_hit_still_rechecks_owner_only_access(vector_input):
    record, _, root = vector_input
    export_to(record, root, "first")
    resource = record.resource
    resource.owner_only = True
    resource.maintainer = None
    resource.save(update_fields=["owner_only", "maintainer"])
    with pytest.raises(ComputeError, match="权限"):
        export_to(record, root, "denied")
    assert not (root / "denied/features.gpkg").exists()


def test_changed_contents_require_a_new_input_binding(vector_input):
    record, source, root = vector_input
    first, first_path = export_to(record, root, "first")
    frame = gpd.read_file(source, layer="survey_points")
    frame.loc[0, "label"] = "changed content"
    frame.to_file(source, layer="survey_points", driver="GPKG")
    with pytest.raises(ComputeError, match="输入内容已变化"):
        export_to(record, root, "denied")
    fresh = ComputeInput.objects.create(
        task=record.task,
        resource=record.resource,
        key="rebound",
        snapshot={"updatedAt": record.resource.updated_at.isoformat()},
    )
    directory = root / "fresh"
    directory.mkdir()
    rebound = freeze_input(fresh, directory)
    assert rebound["sha256"] != first["sha256"]
    assert checksum(first_path) == first["sha256"]


def test_tampered_cached_inode_is_rejected_then_rebuilt(vector_input):
    record, _, root = vector_input
    first, _ = export_to(record, root, "first")
    manifest = app_path(
        "cache",
        "compute-input-versions",
        str(record.task.project_tag_id),
        str(record.resource_id),
        "current.json",
    )
    metadata = json.loads(manifest.read_text())
    path = manifest.parent / metadata["file"]
    path.chmod(0o600)
    path.write_bytes(b"tampered")
    with pytest.raises(ComputeError, match="缓存已变化"):
        export_to(record, root, "denied")
    rebuilt, _ = export_to(record, root, "rebuilt")
    assert not rebuilt["preparation"]["reused"] and rebuilt["sha256"] == first["sha256"]


def test_eviction_does_not_remove_active_task_inputs(vector_input):
    record, _, root = vector_input
    first, path = export_to(record, root, "first")
    clean_versions(0, 7)
    assert checksum(path) == first["sha256"]
    again, _ = export_to(record, root, "again")
    assert not again["preparation"]["reused"] and again["sha256"] == first["sha256"]


def test_concurrent_staging_materializes_once(setup_compute, monkeypatch):
    root = setup_compute["tmp"]
    source = root / "concurrent.csv"
    source.write_text("value\n42\n")
    resource = SimpleNamespace(
        id=9001,
        project_tag_id=setup_compute["project"].pk,
        updated_at=SimpleNamespace(isoformat=lambda: "fixed"),
        data_type="table",
        file_format="CSV",
        storage_path="concurrent.csv",
    )
    monkeypatch.setattr("apps.compute.input_versions._source", lambda _: (source, None))
    copies = []

    def materialize(target):
        copies.append(target)
        time.sleep(0.05)
        target.write_bytes(source.read_bytes())

    def prepare(index):
        destination = root / f"task-{index}.csv"
        return stage_version(resource, "data", destination, materialize)

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(prepare, range(2)))
    assert len(copies) == 1 and sum(v["preparation"]["reused"] for v in values) == 1
    assert values[0]["sha256"] == values[1]["sha256"]
    assert os.stat(root / "task-0.csv").st_ino != os.stat(root / "task-1.csv").st_ino


def raster_record(env, width=9, external_mask=False):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from apps.catalog.models import DataResource
    from apps.raster.models import RasterDataset
    from apps.core.storage import raster_source_path
    from apps.compute.models import ComputeTask

    source = raster_source_path("version-source.tif")
    source.parent.mkdir(parents=True, exist_ok=True)
    values = np.random.default_rng(42).integers(
        0, 2, size=(7 if width < 1000 else 1, width), dtype="int16"
    )
    values[0, 0] = -9
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=not external_mask):
        with rasterio.open(
            source,
            "w",
            driver="GTiff",
            width=width,
            height=values.shape[0],
            count=1,
            dtype="int16",
            nodata=-9,
            crs=32646,
            transform=from_origin(300000, 4001000, 10, 10),
        ) as dst:
            dst.write(values, 1)
            if external_mask:
                mask = np.ones(values.shape, dtype="uint8") * 255
                mask[0, :3] = 0
                dst.write_mask(mask)
    resource = DataResource.objects.create(
        name="矿物版本",
        code="raster-version",
        data_type="raster",
        file_format="GTiff",
        storage_path="version-source.tif",
        size_bytes=source.stat().st_size,
        maintainer=env["owner"],
    )
    RasterDataset.objects.create(
        name=resource.name,
        code=resource.code,
        source_relative_path="version-source.tif",
        status="ready",
        data_resource=resource,
    )
    task = ComputeTask.objects.create(
        name="栅格输入",
        owner=env["owner"],
        version=env["version"],
        idempotency_key="raster-version",
        request_hash="b" * 64,
    )
    record = ComputeInput.objects.create(
        task=task,
        resource=resource,
        key="calcite",
        snapshot={"updatedAt": resource.updated_at.isoformat()},
    )
    return record, source


@pytest.mark.parametrize("width", [9, 262145])
def test_verified_raster_evidence_matches_independent_full_read(setup_compute, width):
    import hashlib
    import runpy
    import numpy as np
    import rasterio

    env = setup_compute
    record, source = raster_record(env, width)
    directory = env["tmp"] / "raster-inputs"
    directory.mkdir()
    prepared = freeze_input(record, directory)
    path = directory / "calcite.tif"
    with rasterio.open(path) as stream:
        values = stream.read(1, masked=True)
        expected = hashlib.sha256(
            values.filled(0).tobytes() + np.ma.getmaskarray(values).tobytes()
        ).hexdigest()
    assert prepared["verifiedEvidence"]["raster"]["pixels"] == expected
    runner = Path(__file__).resolve().parents[3] / "deploy/compute/runner.py"
    context = runpy.run_path(str(runner))["Context"](
        {"inputs": {"calcite": prepared}, "parameters": {}}, directory, env["tmp"]
    )
    assert context.input_evidence("calcite")["raster"]["pixels"] == expected
    path.chmod(0o644)
    with pytest.raises(ValueError, match="Input changed"):
        context.input_evidence("calcite")
    with rasterio.open(source) as original, rasterio.open(path) as frozen:
        np.testing.assert_array_equal(
            original.read(1, masked=True).mask, frozen.read(1, masked=True).mask
        )


def test_external_raster_mask_is_materialized_and_mask_change_invalidates_cache(
    setup_compute,
):
    import numpy as np
    import rasterio

    env = setup_compute
    record, source = raster_record(env, external_mask=True)
    first = env["tmp"] / "mask-first"
    first.mkdir()
    prepared = freeze_input(record, first)
    with (
        rasterio.open(source) as original,
        rasterio.open(first / "calcite.tif") as frozen,
    ):
        np.testing.assert_array_equal(
            original.read(1, masked=True).mask, frozen.read(1, masked=True).mask
        )
        assert frozen.files == [str(first / "calcite.tif")]
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(source, "r+") as dst:
            dst.write_mask(np.full(dst.shape, 255, dtype="uint8"))
    next_dir = env["tmp"] / "mask-changed"
    next_dir.mkdir()
    with pytest.raises(ComputeError, match="输入内容已变化"):
        freeze_input(record, next_dir)
    assert prepared["verifiedEvidence"]["raster"] is not None


def test_running_task_rechecks_source_acl_after_staging(vector_input):
    from apps.compute.services import check_live_task

    record, _, root = vector_input
    export_to(record, root, "staged")
    resource = record.resource
    resource.owner_only = True
    resource.maintainer = None
    resource.save(update_fields=["owner_only", "maintainer"])
    with pytest.raises(ComputeError, match="访问权限变化"):
        check_live_task(record.task)


def test_signed_manifest_rejects_changed_evidence_without_rescanning_source(
    vector_input,
):
    record, _, root = vector_input
    export_to(record, root, "first")
    manifest = app_path(
        "cache",
        "compute-input-versions",
        str(record.task.project_tag_id),
        str(record.resource_id),
        "current.json",
    )
    metadata = json.loads(manifest.read_text())
    metadata["checksum"] = "f" * 64
    manifest.write_text(json.dumps(metadata))
    with pytest.raises(ComputeError, match="缓存已变化"):
        export_to(record, root, "rejected")
    assert not (root / "rejected/features.gpkg").exists()


def test_sqlite_without_rowid_can_reuse_selected_table(setup_compute):
    from apps.catalog.models import DataResource
    from apps.compute.models import ComputeTask
    from apps.core.storage import table_data_path

    env = setup_compute
    source = table_data_path("data.sqlite")
    with sqlite3.connect(source) as db:
        db.execute(
            "CREATE TABLE no_rowid (code TEXT PRIMARY KEY,value REAL) WITHOUT ROWID"
        )
        db.executemany("INSERT INTO no_rowid VALUES (?,?)", [("b", 2), ("a", 1)])
    resource = DataResource.objects.create(
        name="显式主键资料",
        code="without-rowid",
        data_type="table",
        file_format="SQLITE",
        storage_path="no_rowid",
        maintainer=env["owner"],
    )
    task = ComputeTask.objects.create(
        name="无隐式行号输入",
        owner=env["owner"],
        version=env["version"],
        idempotency_key="without-rowid",
        request_hash="c" * 64,
    )
    record = ComputeInput.objects.create(
        task=task,
        resource=resource,
        key="table",
        snapshot={"updatedAt": resource.updated_at.isoformat()},
    )
    a = env["tmp"] / "without-first"
    a.mkdir()
    first = freeze_input(record, a)
    with sqlite3.connect(source) as db:
        db.execute("INSERT INTO samples VALUES ('unrelated',99)")
    b = env["tmp"] / "without-second"
    b.mkdir()
    second = freeze_input(record, b)
    assert first["sha256"] == second["sha256"] and second["preparation"]["reused"]
