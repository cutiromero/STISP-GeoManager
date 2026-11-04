from unittest.mock import patch

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

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
    assert len(display["geojson"]["features"][0]["geometry"]["coordinates"][0]) < len(
        full["geojson"]["features"][0]["geometry"]["coordinates"][0]
    )
    assert frame.geometry.iloc[0].equals_exact(original.geometry.iloc[0], 0)
    with pytest.raises(DataQueryError, match="布尔"):
        query_resource(resource, {"displayGeometry": "true"})
