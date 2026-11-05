import gzip
import json
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import geopandas as gpd
from shapely.geometry import Polygon, shape

from apps.catalog import display_geometry
from apps.catalog.display_geometry import compact_display_geojson


def test_display_budget_keeps_features_valid_and_does_not_change_originals():
    polygons = []
    for index in range(60):
        points = [
            (
                98 + index * 0.01 + 0.004 * math.cos(angle / 100),
                35 + 0.004 * math.sin(angle / 100),
            )
            for angle in range(629)
        ]
        polygons.append(Polygon(points))
    frame = gpd.GeoDataFrame(
        {"name": [f"单元{index}" for index in range(60)]}, geometry=polygons, crs=4326
    )
    original = frame.geometry.to_wkb().tolist()
    compact, warnings = compact_display_geojson(frame)
    assert len(compact["features"]) == len(frame)
    assert all(shape(item["geometry"]).is_valid for item in compact["features"])
    assert frame.geometry.to_wkb().tolist() == original
    size = len(gzip.compress(json.dumps(compact).encode()))
    assert size < 280 * 1024
    assert not warnings
    print(f"synthetic lithology: gzip {size} bytes")


def test_display_query_cache_reuses_result_and_invalidates_resource_revision(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        display_geometry, "app_path", lambda *parts: tmp_path.joinpath(*parts)
    )
    resource = SimpleNamespace(
        id=7,
        data_type="vector",
        storage_path="units",
        updated_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
    )
    payload = {"displayGeometry": True, "limit": 10000}
    compute = Mock(return_value={"geojson": {"features": []}, "elapsedMs": 3500})
    display_geometry.cached_display_query(resource, payload, compute)
    assert display_geometry.cached_display_query(resource, payload, compute)[
        "geojson"
    ] == {"features": []}
    compute.assert_called_once()
    resource.updated_at += timedelta(seconds=1)
    display_geometry.cached_display_query(resource, payload, compute)
    assert compute.call_count == 2
    display_geometry.cached_display_query(resource, {**payload, "limit": 1}, compute)
    assert compute.call_count == 3
    resource.id = 8
    display_geometry.cached_display_query(resource, payload, compute)
    assert compute.call_count == 4
    display_geometry.cached_display_query(
        resource, {**payload, "displayGeometry": False}, compute
    )
    assert compute.call_count == 5


def test_filtered_queries_do_not_reuse_unfiltered_display_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(
        display_geometry, "app_path", lambda *parts: tmp_path.joinpath(*parts)
    )
    resource = SimpleNamespace(
        id=7,
        data_type="vector",
        storage_path="units",
        updated_at=datetime.now(timezone.utc),
    )
    compute = Mock(return_value={"elapsedMs": 0})
    for _ in range(2):
        display_geometry.cached_display_query(
            resource,
            {
                "displayGeometry": True,
                "attributeFilters": [{"field": "name", "value": "Q"}],
            },
            compute,
        )
    assert compute.call_count == 2


def test_prewarm_uses_map_display_query_and_survives_cache_failure(monkeypatch):
    from apps.catalog import vector_store

    query = Mock(side_effect=OSError("cache unavailable"))
    monkeypatch.setattr(vector_store, "query_resource", query)
    display_geometry.prewarm_display_geometry(SimpleNamespace(id=7, data_type="vector"))
    assert query.call_args.args[1] == {
        "displayGeometry": True,
        "limit": 10000,
        "attributeFilters": [],
        "spatialFilter": None,
    }
