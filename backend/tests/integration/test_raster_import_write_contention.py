"""Exercise both raster registration transactions against a competing writer."""

from contextlib import closing
import sqlite3

from django.db import connections
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from apps.raster.models import RasterDataset
from apps.raster.services.importer import import_raster_file


@pytest.mark.django_db(transaction=True)
def test_raster_import_keeps_catalog_and_bands_consistent_during_concurrent_write(
    tmp_path,
):
    # Use a file-backed WAL database, like the worker. A shared in-memory DB
    # does not permit another connection to commit while a read snapshot is held.
    original = connections["default"]
    original.ensure_connection()
    path = tmp_path / "writer-race.db"
    with closing(sqlite3.connect(path)) as clone:
        original.connection.backup(clone)
    current = original.__class__(
        {**original.settings_dict, "NAME": str(path)}, "default"
    )
    source = tmp_path / "registration.tif"
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=1,
        dtype="uint8",
        crs="EPSG:32646",
        transform=from_origin(450_000, 4_000_000, 30, 30),
    ) as raster:
        raster.write(np.ones((16, 16), dtype="uint8"), 1)

    reads, blocked = set(), set()
    try:
        connections["default"] = current
        with closing(sqlite3.connect(path, timeout=0)) as writer:
            assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
            with writer:
                writer.execute("CREATE TABLE concurrent_probe (n INTEGER)")
                writer.execute("INSERT INTO concurrent_probe VALUES (0)")
            current.ensure_connection()

            def interleave(execute, sql, params, many, context):
                result = execute(sql, params, many, context)
                if (
                    sql.lstrip().upper().startswith("SELECT")
                    and current.in_atomic_block
                ):
                    for table in ("raster_rasterdataset", "catalog_dataresource"):
                        if f'FROM "{table}"' not in sql or table in reads:
                            continue
                        reads.add(table)
                        try:
                            with writer:
                                writer.execute("UPDATE concurrent_probe SET n=n+1")
                        except sqlite3.OperationalError as exc:
                            assert exc.sqlite_errorcode == sqlite3.SQLITE_BUSY
                            blocked.add(table)
                        break
                return result

            with current.execute_wrapper(interleave):
                imported = import_raster_file(source, name="并发登记验收")

            with writer:
                writer.execute("UPDATE concurrent_probe SET n=n+1")
            assert writer.execute("SELECT n FROM concurrent_probe").fetchone() == (1,)
            assert blocked == reads == {"raster_rasterdataset", "catalog_dataresource"}
            imported.refresh_from_db()
            assert imported.status == RasterDataset.Status.READY
            assert imported.band_count == 1 and imported.band_records.count() == 1
            assert imported.data_resource_id == imported.map_layer.data_resource_id
    finally:
        current.close()
        connections["default"] = original
