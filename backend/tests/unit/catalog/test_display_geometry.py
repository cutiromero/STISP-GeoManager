import gzip
import json
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import geopandas as gpd
from shapely import set_precision
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import unary_union

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
    for original_geometry, feature in zip(polygons, compact["features"], strict=True):
        quantized = shape(feature["geometry"])
        assert set(quantized.exterior.coords) == {
            (round(longitude, 5), round(latitude, 5))
            for longitude, latitude in original_geometry.exterior.coords
        }
    assert frame.geometry.to_wkb().tolist() == original
    size = len(gzip.compress(json.dumps(compact).encode()))
    assert size < 280 * 1024
    assert not warnings
    print(f"synthetic lithology: gzip {size} bytes")


def test_quantization_preserves_shared_zigzag_boundary_without_simplification():
    shared = [
        (98.01 + (index % 2) * 0.00002, 35 + index * 0.0001) for index in range(101)
    ]
    polygons = [
        Polygon([(98, 35), *shared, (98, 35.01)]),
        Polygon([*reversed(shared), (98.02, 35), (98.02, 35.01)]),
    ]
    frame = gpd.GeoDataFrame(geometry=polygons, crs=4326)
    result, _ = compact_display_geojson(frame)
    left, right = [shape(feature["geometry"]) for feature in result["features"]]
    boundary = left.boundary.intersection(right.boundary)
    assert boundary.length > 0.01
    assert left.intersection(right).area == 0
    assert (
        unary_union([left, right]).symmetric_difference(unary_union(polygons)).area
        < 1e-12
    )
    for original, quantized in zip(polygons, [left, right], strict=True):
        assert len(quantized.exterior.coords) == len(original.exterior.coords)
        assert set(quantized.exterior.coords) == {
            (round(longitude, 5), round(latitude, 5))
            for longitude, latitude in original.exterior.coords
        }


def test_quantization_removes_only_duplicate_vertices_and_collapsed_rings():
    polygon = Polygon(
        [(0, 0), (0.000001, 0), (0.5, 0), (1, 0), (1, 1), (0, 1)],
        holes=[[(0.1, 0.1), (0.100001, 0.1), (0.1, 0.100001)]],
    )
    collapsed = Polygon([(2, 0), (2.000001, 0), (2, 0.000001)])
    frame = gpd.GeoDataFrame(geometry=[MultiPolygon([polygon, collapsed])], crs=4326)
    result, _ = compact_display_geojson(frame)
    geometry = shape(result["features"][0]["geometry"])
    assert geometry.is_valid
    assert len(geometry.geoms) == 1
    geometry = geometry.geoms[0]
    assert len(geometry.interiors) == 0
    assert len(geometry.exterior.coords) == 6
    assert (0.5, 0) in geometry.exterior.coords
    empty, _ = compact_display_geojson(gpd.GeoDataFrame(geometry=[collapsed], crs=4326))
    assert shape(empty["features"][0]["geometry"]).is_empty


def test_shared_edges_with_different_segmentation_are_quantized_once():
    left = Polygon([(0, 0), (0.001, 0), (0.00103, 0.00007), (0, 0.00007)])
    right = Polygon(
        [
            (0.001, 0),
            (0.002, 0),
            (0.002, 0.00007),
            (0.00103, 0.00007),
            (0.001015, 0.000035),
        ]
    )
    frame = gpd.GeoDataFrame(geometry=[left, right], crs=4326)
    result, _ = compact_display_geojson(frame)
    processed = [shape(feature["geometry"]) for feature in result["features"]]
    assert processed[0].intersection(processed[1]).area == 0
    merged = unary_union(processed)
    expected = set_precision(unary_union([left, right]), display_geometry.DISPLAY_GRID)
    assert merged.symmetric_difference(expected).area < 1e-15
    assert processed[0].boundary.intersection(processed[1].boundary).length > 0
    for original, quantized in zip([left, right], processed, strict=True):
        retained = set(
            set_precision(original, display_geometry.DISPLAY_GRID).exterior.coords
        )
        assert retained <= set(quantized.exterior.coords)
    assert merged.symmetric_difference(unary_union([left, right])).area <= (
        merged.length * display_geometry.DISPLAY_GRID
    )


def test_exceeding_budget_never_increases_grid_or_removes_vertices(monkeypatch):
    monkeypatch.setattr(display_geometry, "DISPLAY_BUDGET_BYTES", 1)
    polygon = Polygon([(0, 0), (0.5, 0), (1, 0), (1, 1), (0, 1)])
    result, warnings = compact_display_geojson(
        gpd.GeoDataFrame(geometry=[polygon], crs=4326)
    )
    geometry = shape(result["features"][0]["geometry"])
    assert len(geometry.exterior.coords) == len(polygon.exterior.coords)
    assert geometry.equals_exact(
        set_precision(polygon, display_geometry.DISPLAY_GRID), 0
    )
    assert warnings and "未做形状简化" in warnings[0]


def test_quantization_does_not_remove_intentional_input_overlap():
    polygons = [
        Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),
        Polygon([(1, 0), (3, 0), (3, 2), (1, 2)]),
    ]
    result, _ = compact_display_geojson(gpd.GeoDataFrame(geometry=polygons, crs=4326))
    processed = [shape(feature["geometry"]) for feature in result["features"]]
    for original, quantized in zip(polygons, processed, strict=True):
        assert original.equals(quantized)
    assert processed[0].intersection(processed[1]).area == 2


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


def test_old_simplification_cache_is_invalidated(tmp_path, monkeypatch):
    monkeypatch.setattr(
        display_geometry, "app_path", lambda *parts: tmp_path.joinpath(*parts)
    )
    resource = SimpleNamespace(
        id=7,
        data_type="vector",
        storage_path="units",
        updated_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
    )
    payload = {"displayGeometry": True}
    with monkeypatch.context() as previous:
        previous.setattr(display_geometry, "DISPLAY_CACHE_VERSION", 1)
        display_geometry.cached_display_query(resource, payload, lambda: {"old": True})
    compute = Mock(return_value={"quantized": True})
    assert display_geometry.cached_display_query(resource, payload, compute) == {
        "quantized": True
    }
    display_geometry.cached_display_query(resource, payload, compute)
    compute.assert_called_once()


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
