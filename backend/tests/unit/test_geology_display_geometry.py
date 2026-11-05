from datetime import datetime, timedelta, timezone
import json
from time import perf_counter
from unittest.mock import patch

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from apps.catalog import display_geometry
from apps.catalog.models import DataResource
from apps.catalog.vector_store import DataQueryError, query_resource


def test_display_geometry_is_lighter_but_never_mutates_query_source():
    geometry = Polygon(
        [
            (90.000000123, 30.000000123),
            (90.00001, 30.000000124),
            (90.00002, 30.000000123),
            (90.01, 30.000000123),
            (90.01, 30.01),
            (90.000000123, 30.01),
        ]
    )
    frame = gpd.GeoDataFrame(
        {"name": ["单元"], "feature_id": ["F1"]}, geometry=[geometry], crs=4326
    )
    original = frame.copy()
    resource = DataResource(
        id=1, name="岩性", data_type="vector", storage_path="sample_layer"
    )
    with (
        patch("apps.catalog.vector_store.read_resource", return_value=frame),
        patch("apps.catalog.vector_store.geopackage_layer_exists", return_value=True),
        patch("apps.catalog.vector_store.geopackage_field_profiles", return_value=[]),
        patch("apps.catalog.vector_store._geopackage_filtered_count", return_value=1),
        patch(
            "apps.catalog.vector_store.runtime_query_result_limit", return_value=10000
        ),
    ):
        full = query_resource(resource, {"limit": 10000})
        display = query_resource(resource, {"limit": 10000, "displayGeometry": True})
    assert display["returnedCount"] == full["returnedCount"] == 1
    assert (
        display["geojson"]["features"][0]["properties"]
        == full["geojson"]["features"][0]["properties"]
    )
    assert len(display["geojson"]["features"][0]["geometry"]["coordinates"][0]) == len(
        full["geojson"]["features"][0]["geometry"]["coordinates"][0]
    )
    assert frame.geometry.iloc[0].equals_exact(original.geometry.iloc[0], 0)
    with pytest.raises(DataQueryError, match="布尔"):
        query_resource(resource, {"displayGeometry": "true"})


def test_prewarmed_display_result_skips_source_read_and_compaction_on_reopen(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        display_geometry, "app_path", lambda *parts: tmp_path.joinpath(*parts)
    )
    frame = gpd.GeoDataFrame(
        {"name": ["Q"], "feature_id": ["F1"]},
        geometry=[Polygon([(98, 35), (98.01, 35), (98.01, 35.01), (98, 35)])],
        crs=4326,
    )
    resource = DataResource(
        id=71,
        name="岩性",
        data_type="vector",
        storage_path="units",
        updated_at=datetime.now(timezone.utc),
    )
    with (
        patch("apps.catalog.vector_store.read_resource", return_value=frame) as read,
        patch("apps.catalog.vector_store.geopackage_layer_exists", return_value=True),
        patch("apps.catalog.vector_store.geopackage_field_profiles", return_value=[]),
        patch("apps.catalog.vector_store._geopackage_filtered_count", return_value=1),
        patch(
            "apps.catalog.vector_store.runtime_query_result_limit", return_value=10000
        ) as limit,
        patch.object(
            display_geometry,
            "compact_display_geojson",
            wraps=display_geometry.compact_display_geojson,
        ) as compact,
    ):
        started = perf_counter()
        display_geometry.prewarm_display_geometry(resource)
        cold = perf_counter() - started
        started = perf_counter()
        result = query_resource(
            resource,
            {
                "displayGeometry": True,
                "limit": 10000,
                "attributeFilters": [],
                "spatialFilter": None,
            },
        )
        warm = perf_counter() - started
        assert result["returnedCount"] == 1
        read.assert_called_once()
        compact.assert_called_once()
        resource.updated_at += timedelta(seconds=1)
        display_geometry.prewarm_display_geometry(resource)
        assert compact.call_count == read.call_count == 2
        limit.return_value = 5000
        display_geometry.prewarm_display_geometry(resource)
        assert compact.call_count == read.call_count == 3
        assert query_resource(resource, {"displayGeometry": False})[
            "geojson"
        ] == json.loads(frame.to_json())
        assert read.call_count == 4
        assert compact.call_count == 3
    print(f"display cold={cold:.6f}s warm={warm:.6f}s; warm read/compact calls=0")
