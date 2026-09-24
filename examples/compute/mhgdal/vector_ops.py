"""Vector adaptations of MHGDAL, with explicit coordinate-unit parameters."""

import csv

import numpy as np
from osgeo import ogr
from shapely import from_wkb, to_wkb
from shapely.geometry import Polygon, MultiPolygon, box
from raster_ops import vector, bounds


def write_features(context, filename, source, rows):
    if not rows:
        return
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(
        str(context.output_path(filename))
    )
    layer = ds.CreateLayer("data", srs=source.GetSpatialRef(), geom_type=ogr.wkbUnknown)
    definition = source.GetLayerDefn()
    for i in range(definition.GetFieldCount()):
        field = definition.GetFieldDefn(i)
        # GPKG reserves fid; preserve source attributes with an unambiguous name.
        copied = ogr.FieldDefn(
            "source_fid" if field.GetName().lower() == "fid" else field.GetName(),
            field.GetType(),
        )
        layer.CreateField(copied)
    for feature, geometry in rows:
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError("结果几何为空或无效，请检查输入与参数")
        out = ogr.Feature(layer.GetLayerDefn())
        for i in range(definition.GetFieldCount()):
            value = feature.GetField(i)
            if value is not None:
                out.SetField(i, value)
        out.SetGeometry(ogr.CreateGeometryFromWkb(to_wkb(geometry)))
        layer.CreateFeature(out)
    ds = None


def vector_operation(context, operation):
    src = vector(context)
    layer = src.GetLayer(0)
    p = context.parameters
    if layer.GetSpatialRef() is None:
        raise ValueError("矢量数据需要坐标参考系")
    features = [f.Clone() for f in layer]
    geometries = []
    for f in features:
        raw = f.GetGeometryRef()
        if raw is None:
            raise ValueError("输入包含空几何")
        geom = from_wkb(bytes(raw.ExportToWkb()))
        if geom.is_empty or not geom.is_valid:
            raise ValueError("输入包含无效几何")
        geometries.append(geom)
    rows = []
    if operation == "small-polygons":
        large = []
        small = []
        for f, g in zip(features, geometries):
            if g.geom_type not in {"Polygon", "MultiPolygon"}:
                raise ValueError("请输入面数据")
            (large if g.area > p["area"] else small).append(
                (f, g if g.area > p["area"] else g.centroid)
            )
        write_features(context, "polygons.gpkg", layer, large)
        write_features(context, "points.gpkg", layer, small)
        return
    if operation == "topology":
        # Same exterior-vertex relationship as the source; include every neighbor.
        vertices = []
        for geom in geometries:
            if geom.geom_type not in {"Polygon", "MultiPolygon"}:
                raise ValueError("请输入面数据")
            parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
            vertices.append(
                np.array([xy[:2] for part in parts for xy in part.exterior.coords])
            )
        with context.output_path("result.csv").open(
            "w", newline="", encoding="utf-8"
        ) as stream:
            writer = csv.writer(stream)
            writer.writerow(["source_index", "neighbor_index"])
            for i, left in enumerate(vertices):
                neighbors = []
                for j, right in enumerate(vertices):
                    if i != j and any(
                        np.any(np.all(np.abs(right - point) < 1e-8, axis=1))
                        for point in left
                    ):
                        neighbors.append(j)
                for j in neighbors:
                    writer.writerow([i, j])
                if not neighbors:
                    writer.writerow([i, ""])
        return
    extent = (
        bounds(context, layer.GetSpatialRef().ExportToWkt())
        if operation == "vector-subset"
        else None
    )
    for f, g in zip(features, geometries):
        if operation == "simplify":
            g = g.simplify(p["tolerance"], preserve_topology=True)
        elif operation == "polygon-line":
            if g.geom_type not in {"Polygon", "MultiPolygon"}:
                raise ValueError("请输入面数据")
            g = g.boundary
        elif operation == "line-polygon":
            parts = list(g.geoms) if g.geom_type == "MultiLineString" else [g]
            if any(
                part.geom_type != "LineString" or not part.is_ring for part in parts
            ):
                raise ValueError("线转面要求有效闭合线环")
            polys = [Polygon(part) for part in parts]
            g = polys[0] if len(polys) == 1 else MultiPolygon(polys)
        elif operation == "vector-subset":
            if extent and not g.intersects(box(*extent)):
                continue
        elif operation == "buffer":
            distance = p["distance"]
            if not distance:
                if not p["field"] or f.GetFieldIndex(p["field"]) < 0:
                    raise ValueError("请提供距离或有效距离字段")
                distance = float(f.GetField(p["field"]))
            if not np.isfinite(distance):
                raise ValueError("距离须为有限数值")
            g = g.buffer(
                distance, quad_segs={"低": 8, "中": 30, "高": 60}[p["accuracy"]]
            )
        else:
            raise ValueError("未知矢量操作")
        rows.append((f, g))
    if not rows:
        raise ValueError("当前范围内没有要素")
    write_features(context, "result.gpkg", layer, rows)
