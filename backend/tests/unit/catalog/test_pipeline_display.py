import gzip
import json
import math
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import geopandas as gpd
import pytest
from apps.catalog import display_geometry, vector_store, views
from apps.catalog.geojson_validation import GeometryValidationAccumulator
from django.test import RequestFactory
from shapely import get_num_coordinates
from shapely.geometry import LineString, MultiLineString, Point, Polygon, shape


@pytest.mark.parametrize(
    "value", [True, None, "0.01", -1, 0.11, math.nan, math.inf, 10**1000]
)
def test_bad_line_tolerance_is_rejected_before_io(value):
    with pytest.raises(vector_store.DataQueryError):
        vector_store.query_resource(
            None, {"displayGeometry": True, "lineSimplifyTolerance": value}
        )
    with pytest.raises(vector_store.DataQueryError):
        vector_store.query_resource(None, {"lineSimplifyTolerance": 0.01})


def test_line_preview_reduces_vertices_preserves_endpoints_ids_attributes_and_source():
    line = LineString([(i / 1000, math.sin(i / 100) / 100) for i in range(1001)])
    polygon = Polygon([(2, 0), (3, 0), (3, 1), (2, 1)])
    frame = gpd.GeoDataFrame(
        {"name": ["天然气", "石油", "点", "面"]},
        geometry=[line, MultiLineString([line]), Point(2, 2), polygon],
        index=[17, 25, 30, 40],
        crs=4326,
    )
    source = frame.geometry.to_wkb().tolist()
    default, _ = display_geometry.compact_display_geojson(frame)
    preview, warnings = display_geometry.compact_display_geojson(
        frame, line_tolerance=0.001
    )
    assert frame.geometry.to_wkb().tolist() == source
    assert len(preview["features"]) == 4
    for index, feature in enumerate(preview["features"]):
        assert feature["id"] == default["features"][index]["id"]
        assert feature["properties"] == default["features"][index]["properties"]
        if index >= 2:
            assert feature["geometry"] == default["features"][index]["geometry"]
    reduced = shape(preview["features"][0]["geometry"])
    assert get_num_coordinates(reduced) < get_num_coordinates(line) / 10
    assert reduced.coords[0] == (0, 0)
    assert list(reduced.coords)[-1] == (1, round(line.coords[-1][1], 5))
    assert reduced.hausdorff_distance(line) <= 0.00101
    assert warnings


def test_fast_preview_validation_checks_all_original_vertices_without_precision_scan():
    frame = gpd.GeoDataFrame(
        geometry=[
            LineString([(0, 0), (181, 0), (1, 0)]),
            LineString([(0, 0), (1, 91)]),
            Point(0, 0),
            None,
            LineString(),
        ],
        crs=4326,
        index=[11, 12, 13, 14, 15],
    )
    original = GeometryValidationAccumulator()
    fast = GeometryValidationAccumulator(estimate_uncertainty=False)
    assert (
        original.filter(frame).index.tolist()
        == fast.filter(frame).index.tolist()
        == [13]
    )
    for name in [
        "missing_geometry_count",
        "invalid_longitude_count",
        "invalid_latitude_count",
    ]:
        assert getattr(original, name) == getattr(fast, name)
    assert fast.filter(frame.iloc[:0]).empty


def test_viewport_cache_is_parameter_scoped_bounded_and_revision_aware(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        display_geometry, "app_path", lambda *parts: tmp_path.joinpath(*parts)
    )
    resource = SimpleNamespace(
        id=7,
        data_type="vector",
        storage_path="lines",
        updated_at=datetime.now(UTC),
    )
    compute = Mock(return_value={"elapsedMs": 10, "geojson": {"features": []}})
    payload = {
        "displayGeometry": True,
        "spatialFilter": {"bbox": [0, 0, 1, 1]},
        "lineSimplifyTolerance": 0.01,
    }
    for _ in range(2):
        display_geometry.cached_display_query(resource, payload, compute)
    assert compute.call_count == 1
    display_geometry.cached_display_query(
        resource, {**payload, "lineSimplifyTolerance": 0.001}, compute
    )
    assert compute.call_count == 2
    resource.updated_at += timedelta(seconds=1)
    display_geometry.cached_display_query(resource, payload, compute)
    assert compute.call_count == 3
    for index in range(40):
        display_geometry.cached_display_query(
            resource, {**payload, "limit": index}, compute
        )
    assert len(list(tmp_path.rglob("*.json"))) == 32


def test_query_response_negotiates_gzip_and_still_checks_permissions():
    result = {"returnedCount": 1, "data": "pipeline" * 1000}
    resource = SimpleNamespace(id=7, name="管线", code="line")
    request = RequestFactory().post(
        "/api/catalog/resources/7/query/",
        data="{}",
        content_type="application/json",
        HTTP_ACCEPT_ENCODING="gzip",
    )
    request.user = SimpleNamespace(is_authenticated=True)
    with (
        patch.object(views, "has_feature_perm", return_value=True),
        patch.object(views, "user_can_access", return_value=True) as access,
        patch.object(views, "get_object_or_404", return_value=resource),
        patch.object(views, "query_data_resource", return_value=result) as query,
        patch.object(views, "log_operation"),
    ):
        response = views.resource_query(request, 7)
        assert response.status_code == 200
        assert response["Content-Encoding"] == "gzip"
        assert json.loads(gzip.decompress(response.content)) == result
        assert len(response.content) < 1000
        request.META.pop("HTTP_ACCEPT_ENCODING")
        plain = views.resource_query(request, 7)
        assert "Content-Encoding" not in plain
        assert json.loads(plain.content) == result
        access.return_value = False
        denied = views.resource_query(request, 7)
        assert denied.status_code == 403
        assert query.call_count == 2


def test_real_geopackage_preview_keeps_original_hits_and_exact_query(
    tmp_path, monkeypatch
):
    path = tmp_path / "lines.gpkg"
    line = LineString([(i / 1000, math.sin(i / 100) / 100) for i in range(1001)])
    frame = gpd.GeoDataFrame(
        {"name": ["inside", "outside"]},
        geometry=[line, LineString([(50, 50), (51, 51)])],
        crs=4326,
    )
    frame.to_file(path, layer="pipelines", driver="GPKG")
    resource = vector_store.DataResource(
        id=7, name="lines", data_type="vector", storage_path="pipelines"
    )
    monkeypatch.setattr(vector_store, "vector_geopackage_path", lambda: path)
    monkeypatch.setattr(vector_store, "runtime_query_result_limit", lambda: 10000)
    payload = {
        "attributeFilters": [],
        "spatialFilter": {
            "mode": "rectangle",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-1, -1], [2, -1], [2, 2], [-1, 2], [-1, -1]]],
            },
        },
        "limit": 10000,
    }
    exact = vector_store.query_resource(resource, payload)
    preview = vector_store.query_resource(
        resource, {**payload, "displayGeometry": True, "lineSimplifyTolerance": 0.001}
    )
    assert exact["totalCount"] == preview["totalCount"] == 1
    assert exact["returnedCount"] == preview["returnedCount"] == 1
    assert (
        exact["geojson"]["features"][0]["properties"]
        == preview["geojson"]["features"][0]["properties"]
    )
    assert len(exact["geojson"]["features"][0]["geometry"]["coordinates"]) == 1001
    assert len(preview["geojson"]["features"][0]["geometry"]["coordinates"]) < 100
    assert (
        gpd.read_file(path, layer="pipelines").geometry.to_wkb().tolist()
        == frame.geometry.to_wkb().tolist()
    )
