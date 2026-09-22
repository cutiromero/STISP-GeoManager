"""Add WGS84 ellipsoidal area and boundary length, retaining source CRS."""

import geopandas as gpd
from pyproj import Geod
from shapely.ops import orient


def run(context):
    frame = gpd.read_file(context.input_path("features"), layer="data")
    if frame.crs is None:
        raise ValueError("输入矢量需要已知坐标系")
    if {"area_m2", "perimeter_m"} & set(frame.columns):
        raise ValueError("输入已有area_m2或perimeter_m字段，请先重命名以保留原数据")
    geod = Geod(ellps="WGS84")
    areas, lengths = [], []
    for geometry in frame.to_crs(4326).geometry:
        if geometry is None or geometry.is_empty:
            areas.append(None)
            lengths.append(None)
            continue
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError("面积周长统计仅接受面或多面矢量")
        if not geometry.is_valid:
            raise ValueError("输入包含无效面几何，请修复后重试")
        geometry = orient(geometry, sign=1.0)
        parts = geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]
        area, length = 0.0, 0.0
        for polygon in parts:
            value, _ = geod.geometry_area_perimeter(polygon)
            area += abs(value)
            length += geod.geometry_length(polygon.exterior)
            length += sum(geod.geometry_length(ring) for ring in polygon.interiors)
        areas.append(area)
        lengths.append(length)
    frame["area_m2"] = areas
    frame["perimeter_m"] = lengths
    frame.to_file(context.output_path("metrics.gpkg"), layer="metrics", driver="GPKG")
