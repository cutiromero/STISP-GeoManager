"""Numerical checks for trusted, repository-owned examples, not uploaded packages."""

import runpy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[3] / "examples" / "compute"


class ExampleContext:
    def __init__(self, root, source, parameters):
        self.root = root
        self.source = source
        self.parameters = parameters

    def input_path(self, key):
        return self.source

    def output_path(self, name):
        return self.root / name


def test_raster_transform_preserves_nodata_coordinates(tmp_path):
    source = tmp_path / "input.tif"
    transform = from_origin(80, 40, 0.1, 0.1)
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999,
    ) as dst:
        dst.write(np.array([[1, 2], [3, -9999]], dtype="float32"), 1)
    runpy.run_path(ROOT / "raster-linear/main.py")["run"](
        ExampleContext(tmp_path, source, {"band": 1, "scale": 2, "offset": 1})
    )
    with rasterio.open(tmp_path / "transformed.tif") as result:
        assert result.crs.to_epsg() == 4326
        assert result.transform == transform
        np.testing.assert_allclose(result.read(1), [[3, 5], [7, -9999]])


def test_ndvi_scales_offsets_zero_denominator_and_mask(tmp_path):
    source = tmp_path / "image.tif"
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=3,
        height=1,
        count=2,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(80, 40, 0.1, 0.1),
        nodata=-9999,
    ) as dst:
        dst.write(np.array([[[1, 0, -9999]], [[3, 0, 9]]], dtype="float32"))
        dst.scales = (0.1, 0.1)
    runpy.run_path(ROOT / "raster-ndvi/main.py")["run"](
        ExampleContext(tmp_path, source, {"red": 1, "nir": 2})
    )
    with rasterio.open(tmp_path / "ndvi.tif") as result:
        values = result.read(1, masked=True)
        assert float(values[0, 0]) == pytest.approx(0.5)
        assert values.mask[0, 1] and values.mask[0, 2]


def test_table_summary_numeric_and_grouping(tmp_path):
    source = tmp_path / "table.csv"
    source.write_text("group,value\nA,2\nA,4\nB,8\n", encoding="utf-8")
    runpy.run_path(ROOT / "table-group-summary/main.py")["run"](
        ExampleContext(
            tmp_path, source, {"group": "group", "value": "value", "method": "mean"}
        )
    )
    frame = pd.read_csv(tmp_path / "summary.csv")
    assert frame.to_dict("records") == [
        {"group": "A", "value": 3},
        {"group": "B", "value": 8},
    ]


def test_vector_buffer_uses_metres(tmp_path):
    import geopandas as gpd
    from shapely.geometry import Point

    source = tmp_path / "vector.gpkg"
    frame = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(80, 40)], crs=4326)
    frame.to_file(source, layer="data", driver="GPKG")
    runpy.run_path(ROOT / "vector-buffer/main.py")["run"](
        ExampleContext(tmp_path, source, {"distance": 100})
    )
    result = gpd.read_file(tmp_path / "buffer.gpkg").to_crs(frame.estimate_utm_crs())
    assert result.area.iloc[0] == pytest.approx(np.pi * 100**2, rel=0.005)


def test_ndwi_and_invalid_pixels(tmp_path):
    source = tmp_path / "image.tif"
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=3,
        height=1,
        count=2,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(80, 40, 0.1, 0.1),
        nodata=-9999,
    ) as dst:
        dst.write(np.array([[[6, 0, -9999]], [[2, 0, 3]]], dtype="float32"))
        dst.scales = (0.1, 0.1)
    run = runpy.run_path(ROOT / "raster-ndwi/main.py")["run"]
    run(ExampleContext(tmp_path, source, {"green": 1, "nir": 2}))
    with rasterio.open(tmp_path / "ndwi.tif") as output:
        values = output.read(1, masked=True)
        assert values[0, 0] == pytest.approx(0.5)
        assert values.mask[0, 1] and values.mask[0, 2]
        assert output.crs.to_epsg() == 4326
    with pytest.raises(ValueError, match="不能相同"):
        run(ExampleContext(tmp_path, source, {"green": 1, "nir": 1}))


def test_polygon_metrics_preserve_attributes_holes_and_crs(tmp_path):
    import geopandas as gpd
    from shapely.geometry import Polygon

    source = tmp_path / "faces.gpkg"
    square = [
        (500000, 4000000),
        (500100, 4000000),
        (500100, 4000100),
        (500000, 4000100),
    ]
    hole = [(500025, 4000025), (500075, 4000025), (500075, 4000075), (500025, 4000075)]
    frame = gpd.GeoDataFrame(
        {"name": ["test"]}, geometry=[Polygon(square, [hole])], crs=32644
    )
    frame.to_file(source, layer="data", driver="GPKG")
    runpy.run_path(ROOT / "vector-metrics/main.py")["run"](
        ExampleContext(tmp_path, source, {})
    )
    result = gpd.read_file(tmp_path / "metrics.gpkg")
    assert result.crs == frame.crs and result["name"].tolist() == ["test"]
    assert result.area_m2.iloc[0] == pytest.approx(7500, rel=0.002)
    assert result.perimeter_m.iloc[0] == pytest.approx(600, rel=0.002)
