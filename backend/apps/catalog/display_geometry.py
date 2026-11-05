from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import tempfile
from time import perf_counter

from shapely import STRtree, set_precision, union_all
from shapely.geometry import Polygon, mapping
from shapely.ops import polygonize

from apps.core.storage import app_path, vector_geopackage_path


DISPLAY_BUDGET_BYTES = 280 * 1024
DISPLAY_GRID = 0.00001
DISPLAY_CACHE_VERSION = 2
logger = logging.getLogger(__name__)


def cached_display_query(resource, payload, compute):
    if (
        payload.get("displayGeometry") is not True
        or payload.get("spatialFilter")
        or payload.get("attributeFilters")
        or resource.data_type != "vector"
        or not getattr(resource, "updated_at", None)
    ):
        return compute()
    started = perf_counter()
    identity = json.dumps(
        [str(vector_geopackage_path()), resource.id, payload], sort_keys=True
    )
    key = hashlib.sha256(identity.encode()).hexdigest()
    revision = json.dumps(
        [DISPLAY_CACHE_VERSION, resource.updated_at.isoformat(), resource.storage_path]
    )
    path = app_path("cache", "vector-display", f"{key}.json")
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached["revision"] == revision:
            result = cached["result"]
            result["elapsedMs"] = max(0, round((perf_counter() - started) * 1000))
            return result
    except (OSError, ValueError, KeyError, TypeError):
        pass
    result = compute()
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = stream.name
            json.dump(
                {"revision": revision, "result": result},
                stream,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        os.replace(temporary, path)
    except OSError:
        logger.warning("无法保存矢量显示缓存 resource=%s", resource.id, exc_info=True)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return result


def prewarm_display_geometry(resource):
    from .vector_store import query_resource

    if resource.data_type != "vector":
        return
    try:
        query_resource(
            resource,
            {
                "displayGeometry": True,
                "limit": 10000,
                "attributeFilters": [],
                "spatialFilter": None,
            },
        )
    except Exception:
        logger.warning("矢量显示缓存预热失败 resource=%s", resource.id, exc_info=True)


def compact_display_geojson(frame):
    features = json.loads(frame.to_json())
    geometries = [
        set_precision(geometry, DISPLAY_GRID, mode="valid_output")
        if geometry is not None
        else None
        for geometry in frame.geometry
    ]
    polygon_indices = [
        index
        for index, geometry in enumerate(frame.geometry)
        if geometry is not None
        and not geometry.is_empty
        and geometry.geom_type in {"Polygon", "MultiPolygon"}
    ]
    if len(polygon_indices) > 1:
        polygons = [geometries[index] for index in polygon_indices]
        tree = STRtree(polygons)
        original_tree = STRtree(
            [frame.geometry.iloc[index] for index in polygon_indices]
        )
        boundaries = union_all(
            [frame.geometry.iloc[index].boundary for index in polygon_indices],
            grid_size=DISPLAY_GRID,
        )
        groups = [[] for _ in polygons]
        for face in polygonize(boundaries):
            candidates = tree.query(face, predicate="intersects")
            area, owner = max(
                (
                    (face.intersection(polygons[index]).area, int(index))
                    for index in candidates
                ),
                default=(0, -1),
            )
            if area > 0:
                original_owners = original_tree.query(
                    face.representative_point(), predicate="covered_by"
                )
                owners = original_owners if len(original_owners) > 1 else [owner]
                for index in owners:
                    groups[index].append(face)
        for index, group in zip(polygon_indices, groups, strict=True):
            geometries[index] = union_all(group) if group else Polygon()
    for feature, geometry in zip(features["features"], geometries, strict=True):
        if geometry is None or geometry.is_empty:
            if geometry is not None:
                feature["geometry"] = mapping(geometry)
            continue
        feature["geometry"] = json.loads(
            json.dumps(mapping(geometry)),
            parse_float=lambda value: round(float(value), 5),
        )
    encoded = json.dumps(features).encode()
    if len(gzip.compress(encoded, compresslevel=6, mtime=0)) <= DISPLAY_BUDGET_BYTES:
        return features, []
    return features, [
        "显示几何仅按统一网格量化，未做形状简化；传输体积超过目标，精确编辑与计算使用原始数据。"
    ]
