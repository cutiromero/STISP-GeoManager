"""Real GeoPackage exports preserve retry hashes without hiding data changes."""

import sqlite3
from contextlib import closing

import geopandas as gpd
import pytest
from shapely.geometry import Point

from apps.catalog.models import DataResource
from apps.compute.data import freeze_input
from apps.compute.models import ComputeInput, ComputeTask
from apps.compute.packages import ComputeError, checksum
from apps.core.storage import vector_geopackage_path
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_compute import setup_compute  # noqa: F401


@pytest.fixture
def vector_input(setup_compute):  # noqa: F811
    env = setup_compute
    scope = ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    with project_scope(scope):
        source = vector_geopackage_path()
        source.parent.mkdir(parents=True, exist_ok=True)
        gpd.GeoDataFrame(
            {
                "feature_id": ["F01", "F02"],
                "label": ["调查点", None],
                "value": [1.5, 2],
            },
            geometry=[Point(88, 40), Point(88.1, 40.1)],
            crs=4326,
        ).to_file(source, layer="survey_points", driver="GPKG")
        resource = DataResource.objects.create(
            name="恢复计算的矢量资料",
            code="freeze-vector",
            data_type="vector",
            file_format="GPKG",
            storage_path="survey_points",
            size_bytes=source.stat().st_size,
            maintainer=env["owner"],
        )
        task = ComputeTask.objects.create(
            name="输入冻结检查",
            owner=env["owner"],
            version=env["version"],
            idempotency_key="vector-freeze",
            request_hash="a" * 64,
        )
        record = ComputeInput.objects.create(
            task=task,
            resource=resource,
            key="features",
            snapshot={"updatedAt": resource.updated_at.isoformat()},
        )
        yield record, source, env["tmp"]


def export_to(record, root, name):
    destination = root / name
    destination.mkdir()
    return freeze_input(record, destination), destination / "features.gpkg"


@pytest.mark.parametrize("force_timestamps", [False, True])
def test_reexport_same_vector_has_identical_real_file_hash(
    vector_input, monkeypatch, force_timestamps
):
    record, source, root = vector_input
    source_digest = checksum(source)
    original_export = gpd.GeoDataFrame.to_file
    export_times = iter(("2026-10-10T00:00:00.000Z", "2026-10-10T01:00:00.000Z"))

    def export_at_different_times(frame, filename, *args, **kwargs):
        original_export(frame, filename, *args, **kwargs)
        # Exercise real file bytes across different driver creation timestamps.
        with closing(sqlite3.connect(filename)) as connection:
            connection.execute(
                "UPDATE gpkg_contents SET last_change = ?", (next(export_times),)
            )
            connection.commit()

    if force_timestamps:
        monkeypatch.setattr(gpd.GeoDataFrame, "to_file", export_at_different_times)
    first, first_path = export_to(record, root, "first-attempt")
    record.refresh_from_db()
    second, second_path = export_to(record, root, "recovered-attempt")
    record.refresh_from_db()
    assert first["sha256"] == second["sha256"] == record.checksum
    assert checksum(first_path) == checksum(second_path) == record.checksum
    assert first_path.read_bytes() == second_path.read_bytes()
    assert checksum(source) == source_digest
    with closing(sqlite3.connect(first_path)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            connection.execute("SELECT last_change FROM gpkg_contents").fetchone()[0]
            == "1970-01-01T00:00:00.000Z"
        )
    assert gpd.read_file(first_path, layer="data").equals(
        gpd.read_file(source, layer="survey_points")
    )


@pytest.mark.parametrize("change", ["attribute", "geometry"])
def test_reexport_changed_vector_still_refuses_original_task(vector_input, change):
    record, source, root = vector_input
    first, _ = export_to(record, root, "first-attempt")
    original_revision = record.snapshot["updatedAt"]
    frame = gpd.read_file(source, layer="survey_points")
    if change == "attribute":
        frame.loc[0, "label"] = "已改动的调查点"
    else:
        frame.loc[0, "geometry"] = Point(89, 41)
    frame.to_file(source, layer="survey_points", driver="GPKG")
    record.refresh_from_db()
    with pytest.raises(ComputeError, match="输入内容已变化"):
        export_to(record, root, "recovered-attempt")
    record.refresh_from_db()
    record.resource.refresh_from_db()
    assert record.checksum == first["sha256"]
    assert record.resource.updated_at.isoformat() == original_revision
    assert checksum(root / "recovered-attempt/features.gpkg") != record.checksum
