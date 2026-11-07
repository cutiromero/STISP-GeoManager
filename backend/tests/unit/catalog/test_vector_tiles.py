import gzip
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import geopandas as gpd
import pytest
from django.test import RequestFactory
from shapely.geometry import LineString, Point

from apps.catalog import vector_tiles as tiles


def feature(index, lon, lat):
    return {
        "type": "Feature",
        "id": index,
        "properties": {"name": f"P{index}"},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


@pytest.mark.parametrize("zoom", range(11))
def test_cluster_counts_conserve_all_points_and_uncluster_at_maxzoom(zoom):
    features = [feature(i, 87 + i / 100000, 42) for i in range(100)]
    features += [feature(100, -179.99, -80), feature(101, 179.99, 80)]
    original = json.dumps(features)
    grouped = tiles.point_zoom_features(features, zoom)
    assert sum(f["properties"].get("point_count", 1) for f in grouped) == 102
    assert json.dumps(features) == original
    if zoom == 10:
        assert grouped == features
    else:
        assert len(grouped) < len(features)
        assert any(f["properties"].get("point_count", 0) == 100 for f in grouped)
    assert len({f["id"] for f in grouped}) == len(grouped)


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    path = tmp_path / "source.gpkg"
    gpd.GeoDataFrame(
        {"name": ["A", "B"]},
        crs=4326,
        geometry=[LineString([(80, 40), (90, 43)]), LineString([(100, 10), (110, 20)])],
    ).to_file(path, layer="lines")
    resource = SimpleNamespace(
        id=7,
        data_type="vector",
        storage_path="lines",
        updated_at=datetime.now(UTC),
        refresh_from_db=Mock(),
    )
    monkeypatch.setattr(tiles, "vector_geopackage_path", lambda: path)
    monkeypatch.setattr(tiles, "app_path", lambda *p: tmp_path.joinpath(*p))
    monkeypatch.setattr(tiles, "selected_project_id", lambda: 2)

    def generate(data, output, minimum, maximum, clustered):
        content = gzip.compress(data.read_bytes())
        with closing(sqlite3.connect(output)) as db:
            db.execute(
                "CREATE TABLE tiles(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
            )
            db.executemany(
                "INSERT INTO tiles VALUES (?,0,0,?)",
                [(z, content) for z in range(minimum, maximum + 1)],
            )
            db.commit()

    monkeypatch.setattr(tiles, "_generate_mvt", generate)
    return path, resource


def test_prepare_is_readonly_atomic_and_revision_scoped(prepared, monkeypatch):
    path, resource = prepared
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert tiles.vector_tile_preview(resource) is None
    preview = tiles.prepare_vector_tiles(resource)
    assert preview["featureCount"] == 2 and not preview["clustered"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert tiles.prepare_vector_tiles(resource) == preview
    resource.updated_at += timedelta(seconds=1)
    assert tiles.vector_tile_preview(resource) is None
    resource.updated_at -= timedelta(seconds=1)
    monkeypatch.setattr(tiles, "selected_project_id", lambda: 3)
    assert tiles.vector_tile_preview(resource) is None


def test_failure_does_not_publish_partial_cache(prepared, monkeypatch):
    _, resource = prepared
    monkeypatch.setattr(
        tiles, "_generate_mvt", Mock(side_effect=ValueError("GDAL failed"))
    )
    with pytest.raises(ValueError, match="GDAL failed"):
        tiles.prepare_vector_tiles(resource)
    assert tiles.vector_tile_preview(resource) is None


def test_mid_build_revision_change_does_not_publish(prepared):
    _, resource = prepared
    resource.refresh_from_db.side_effect = lambda: setattr(
        resource, "updated_at", datetime.now(UTC)
    )
    with pytest.raises(ValueError, match="资源已更新"):
        tiles.prepare_vector_tiles(resource)
    assert tiles.vector_tile_preview(resource) is None


def test_point_preparation_has_aggregated_and_raw_pyramids(prepared):
    path, resource = prepared
    gpd.GeoDataFrame(
        {"name": ["A", "B", "C"]},
        crs=4326,
        geometry=[Point(87, 42), Point(87.000001, 42), Point(-80, 30)],
    ).to_file(path, layer="points")
    resource.storage_path = "points"
    preview = tiles.prepare_vector_tiles(resource)
    assert preview["clustered"] and "aggregate=0" in preview["rawTileUrl"]
    directory = tiles.preview_directory(resource, preview["revision"])
    with closing(sqlite3.connect(directory / "tiles.mbtiles")) as db:
        for z, blob in db.execute("SELECT zoom_level,tile_data FROM tiles"):
            features = json.loads(gzip.decompress(blob))["features"]
            assert sum(f["properties"].get("point_count", 1) for f in features) == 3
            if z == 10:
                assert all("point_count" not in f["properties"] for f in features)
    with closing(sqlite3.connect(directory / "raw.mbtiles")) as db:
        assert (
            len(
                json.loads(
                    gzip.decompress(
                        db.execute("SELECT tile_data FROM tiles LIMIT 1").fetchone()[0]
                    )
                )["features"]
            )
            == 3
        )


def test_tile_xyz_tms_etag_and_access_before_cache(prepared, monkeypatch):
    _, resource = prepared
    preview = tiles.prepare_vector_tiles(resource)
    monkeypatch.setattr(tiles, "get_object_or_404", lambda *a, **kw: resource)
    permission = Mock(return_value=True)
    access = Mock(return_value=True)
    monkeypatch.setattr(tiles, "has_feature_perm", permission)
    monkeypatch.setattr("apps.catalog.permissions.user_can_access", access)
    request = RequestFactory().get("/api/tile")
    request.user = SimpleNamespace(is_authenticated=True)
    read = lambda z, x, y: tiles.resource_vector_tile(
        request, 7, preview["revision"], z, x, y
    )
    response = read(1, 0, 1)  # XYZ y=1 is MBTiles TMS row=0.
    assert response.status_code == 200 and response["Content-Encoding"] == "gzip"
    assert "private" in response["Cache-Control"]
    assert read(1, 0, 0).status_code == 204
    request = RequestFactory().get("/api/tile", HTTP_IF_NONE_MATCH=response["ETag"])
    request.user = SimpleNamespace(is_authenticated=True)
    assert read(1, 0, 1).status_code == 304
    access.return_value = False
    assert read(1, 0, 1).status_code == 403
    access.return_value = True
    permission.return_value = False
    monkeypatch.setattr(
        tiles,
        "feature_denied_response",
        lambda user: tiles.JsonResponse({"detail": "无权加载"}, status=403),
    )
    assert read(1, 0, 1).status_code == 403


def test_raw_queries_can_return_source_fids_without_changing_default(
    prepared, monkeypatch
):
    path, resource = prepared
    from apps.catalog import vector_store

    monkeypatch.setattr(vector_store, "vector_geopackage_path", lambda: path)
    monkeypatch.setattr(vector_store, "runtime_query_result_limit", lambda: 10000)
    resource.name = "lines"
    payload = {"attributeFilters": [], "spatialFilter": None, "limit": 10000}
    default = vector_store.query_resource(resource, payload)
    stable = vector_store.query_resource(
        resource, {**payload, "sourceFeatureIds": True}
    )
    assert [f["id"] for f in default["geojson"]["features"]] == ["0", "1"]
    assert [f["id"] for f in stable["geojson"]["features"]] == ["1", "2"]
    assert [f["geometry"] for f in stable["geojson"]["features"]] == [
        f["geometry"] for f in default["geojson"]["features"]
    ]
    with pytest.raises(ValueError, match="sourceFeatureIds"):
        vector_store.query_resource(resource, {**payload, "sourceFeatureIds": "true"})


def test_corrupt_cache_returns_structured_not_ready(prepared, monkeypatch):
    _, resource = prepared
    preview = tiles.prepare_vector_tiles(resource)
    monkeypatch.setattr(tiles, "get_object_or_404", lambda *a, **kw: resource)
    monkeypatch.setattr(tiles, "has_feature_perm", lambda *a: True)
    monkeypatch.setattr("apps.catalog.permissions.user_can_access", lambda *a: True)
    path = tiles.preview_directory(resource, preview["revision"]) / "tiles.mbtiles"
    path.write_bytes(b"corrupt")
    request = RequestFactory().get("/api/tile")
    request.user = SimpleNamespace(is_authenticated=True)
    response = tiles.resource_vector_tile(request, 7, preview["revision"], 0, 0, 0)
    assert response.status_code == 404
    assert "detail" in json.loads(response.content)


@pytest.mark.parametrize("z,x,y", [(11, 0, 0), (1, 2, 0), (1, 0, 2), (-1, 0, 0)])
def test_tile_rejects_invalid_xyz_before_cache(prepared, monkeypatch, z, x, y):
    _, resource = prepared
    monkeypatch.setattr(tiles, "get_object_or_404", lambda *a, **kw: resource)
    monkeypatch.setattr(tiles, "has_feature_perm", lambda *a: True)
    monkeypatch.setattr("apps.catalog.permissions.user_can_access", lambda *a: True)
    request = RequestFactory().get("/api/tile")
    request.user = SimpleNamespace(is_authenticated=True)
    assert tiles.resource_vector_tile(request, 7, "0" * 24, z, x, y).status_code == 400
