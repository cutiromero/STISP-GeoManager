"""Offline display pyramids. Request handling only reads authorized cache data."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from apps.catalog.geojson_validation import GeometryValidationAccumulator
from apps.catalog.models import DataResource
from apps.core.api import api_login_required
from apps.core.permissions import feature_denied_response, has_feature_perm
from apps.core.storage import (
    app_path,
    validate_vector_layer_name,
    vector_geopackage_path,
)
from apps.projects.context import selected_project_id

MAX_ZOOM = 10
MERCATOR_LATITUDE = 85.0511287798066
CACHE_VERSION = 1


def preview_revision(resource):
    path = vector_geopackage_path()
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
        row = db.execute(
            "SELECT last_change FROM gpkg_contents WHERE table_name=?",
            (validate_vector_layer_name(resource.storage_path),),
        ).fetchone()
    if row is None:
        raise ValueError("矢量图层不存在")
    identity = [
        CACHE_VERSION,
        str(path.resolve()),
        selected_project_id(),
        resource.id,
        resource.storage_path,
        resource.updated_at.isoformat(),
        row[0],
    ]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]


def preview_directory(resource, revision):
    if not re.fullmatch(r"[a-f0-9]{24}", revision):
        raise ValueError("显示版本不合法")
    return app_path(
        "cache",
        "vector-tiles",
        "v1",
        str(selected_project_id()),
        str(resource.id),
        revision,
    )


def vector_tile_preview(resource):
    if resource.data_type != "vector" or not resource.storage_path:
        return None
    try:
        revision = preview_revision(resource)
        directory = preview_directory(resource, revision)
        metadata = json.loads((directory / "preview.json").read_text(encoding="utf-8"))
        if (
            metadata["revision"] != revision
            or not (directory / "tiles.mbtiles").is_file()
            or (metadata["clustered"] and not (directory / "raw.mbtiles").is_file())
        ):
            return None
        return metadata
    except (OSError, ValueError, KeyError, sqlite3.Error):
        return None


def point_zoom_features(features, zoom):
    """Deterministic 64px global cells. Every source point contributes once."""
    if zoom >= MAX_ZOOM:
        return features
    groups = {}
    cells = 8 * 2**zoom  # Mapbox vector tiles use a 512px display tile.
    for feature in features:
        lon, lat = feature["geometry"]["coordinates"][:2]
        lat = max(-MERCATOR_LATITUDE, min(MERCATOR_LATITUDE, lat))
        x = (lon + 180) / 360
        y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2
        key = (
            min(cells - 1, max(0, int(x * cells))),
            min(cells - 1, max(0, int(y * cells))),
        )
        groups.setdefault(key, []).append((feature, x, y))
    result = []
    for index, members in enumerate(groups.values()):
        if len(members) == 1:
            result.append(members[0][0])
            continue
        count = len(members)
        x = sum(m[1] for m in members) / count
        y = sum(m[2] for m in members) / count
        result.append(
            {
                "type": "Feature",
                "id": 2**40 + index,
                "properties": {
                    "point_count": count,
                    "point_count_abbreviated": str(count),
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        x * 360 - 180,
                        math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y)))),
                    ],
                },
            }
        )
    return result


def _write_features(path, features):
    path.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": features},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def _generate_mvt(input_path, output, minimum, maximum, clustered):
    from apps.raster.services.gdal_ops import run_gdal_command

    run_gdal_command(
        [
            "ogr2ogr",
            "-f",
            "MVT",
            str(output),
            str(input_path),
            "-nln",
            "features",
            "-preserve_fid",
            "-dsco",
            "FORMAT=MBTILES",
            "-dsco",
            f"MINZOOM={minimum}",
            "-dsco",
            f"MAXZOOM={maximum}",
            "-dsco",
            "MAX_SIZE=20000000",
            "-dsco",
            "MAX_FEATURES=1000000",
            "-dsco",
            "SIMPLIFICATION=1",
            "-dsco",
            "SIMPLIFICATION_MAX_ZOOM=0",
            "-dsco",
            f"BUFFER={0 if clustered else 80}",
            "-dsco",
            "COMPRESS=YES",
        ],
        timeout_seconds=600,
    )


def prepare_vector_tiles(resource, progress=lambda text: None):
    """Read a consistent source snapshot, prepare all zooms, atomically publish."""
    import geopandas as gpd
    from shapely.geometry import box

    if resource.data_type != "vector":
        raise ValueError("仅支持矢量资源")
    ready = vector_tile_preview(resource)
    if ready:
        return ready
    revision = preview_revision(resource)
    destination = preview_directory(resource, revision)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="prepare-", dir=destination.parent
    ) as temporary:
        work = Path(temporary)
        snapshot = work / "source.gpkg"
        with (
            closing(
                sqlite3.connect(
                    f"{vector_geopackage_path().as_uri()}?mode=ro", uri=True
                )
            ) as source,
            closing(sqlite3.connect(snapshot)) as target,
        ):
            source.backup(target)
        frame = gpd.read_file(
            snapshot,
            layer=validate_vector_layer_name(resource.storage_path),
            fid_as_index=True,
        )
        if frame.crs is None:
            raise ValueError("原始数据缺少坐标参考系统")
        frame = frame.to_crs(4326)
        frame = GeometryValidationAccumulator(estimate_uncertainty=False).filter(frame)
        kinds = set(frame.geometry.geom_type)
        clustered = bool(kinds) and kinds <= {"Point"}
        if not clustered and not kinds <= {"LineString", "MultiLineString"}:
            raise ValueError("显示瓦片只支持纯点或纯线资源")
        # Projection clipping affects this disposable display copy only.
        frame = frame.copy()
        frame.geometry = frame.geometry.intersection(
            box(-180, -MERCATOR_LATITUDE, 180, MERCATOR_LATITUDE)
        )
        frame = frame[~frame.geometry.is_empty]
        if frame.empty:
            raise ValueError("资源没有WebMercator范围内的有效要素")
        collection = json.loads(frame.to_json())
        for feature in collection["features"]:
            feature["id"] = int(feature["id"])
        publish = work / "publish"
        publish.mkdir()
        output = publish / "tiles.mbtiles"
        if clustered:
            if any("point_count" in f["properties"] for f in collection["features"]):
                raise ValueError("原数据point_count字段与显示聚合保留字段冲突")
            for zoom in range(MAX_ZOOM + 1):
                progress(f"{resource.id}: point zoom {zoom}")
                data = work / "points.geojson"
                _write_features(data, point_zoom_features(collection["features"], zoom))
                part = work / f"zoom-{zoom}.mbtiles"
                _generate_mvt(data, part, zoom, zoom, True)
                if zoom == 0:
                    os.replace(part, output)
                else:
                    with closing(sqlite3.connect(output)) as db:
                        db.execute("ATTACH DATABASE ? AS part", (str(part),))
                        db.execute("INSERT INTO tiles SELECT * FROM part.tiles")
                        db.commit()
                    part.unlink()
            _write_features(data, collection["features"])
            progress(f"{resource.id}: raw point pyramid")
            _generate_mvt(data, publish / "raw.mbtiles", 0, MAX_ZOOM, True)
        else:
            data = work / "lines.geojson"
            _write_features(data, collection["features"])
            progress(f"{resource.id}: line pyramid 0-{MAX_ZOOM}")
            _generate_mvt(data, output, 0, MAX_ZOOM, False)
        with closing(sqlite3.connect(output)) as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            count = db.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
            if not count:
                raise ValueError("瓦片生成结果为空")
        resource.refresh_from_db()
        if preview_revision(resource) != revision:
            raise ValueError("生成期间资源已更新，请重新准备")
        bounds = [float(v) for v in frame.total_bounds]
        metadata = {
            "revision": revision,
            "tileUrl": f"/api/catalog/resources/{resource.id}/vector-tiles/{revision}/{{z}}/{{x}}/{{y}}.pbf",
            "sourceLayer": "features",
            "minZoom": 0,
            "maxZoom": MAX_ZOOM,
            "bounds": bounds,
            "clustered": clustered,
            "featureCount": len(frame),
        }
        if clustered:
            metadata["rawTileUrl"] = metadata["tileUrl"] + "?aggregate=0"
        (publish / "preview.json").write_text(json.dumps(metadata), encoding="utf-8")
        # Never replace an already published revision during concurrent preparation.
        if not destination.exists():
            try:
                os.rename(publish, destination)
            except FileExistsError:
                if not vector_tile_preview(resource):
                    raise
        return vector_tile_preview(resource)


@require_GET
@api_login_required
def resource_vector_tile(request, pk, revision, z, x, y):
    from apps.catalog.permissions import user_can_access

    if not all(
        has_feature_perm(request.user, p)
        for p in ("core.query_data", "core.load_vector_layer")
    ):
        return feature_denied_response(request.user)
    resource = get_object_or_404(DataResource, pk=pk, status=DataResource.Status.ACTIVE)
    if not user_can_access(resource, request.user):
        return JsonResponse({"detail": "无权访问该数据资源"}, status=403)
    if not 0 <= z <= MAX_ZOOM or not 0 <= x < 2**z or not 0 <= y < 2**z:
        return JsonResponse({"detail": "瓦片坐标不合法"}, status=400)
    preview = vector_tile_preview(resource)
    if not preview or preview["revision"] != revision:
        return JsonResponse({"detail": "显示瓦片未准备或版本已失效"}, status=404)
    aggregate = request.GET.get("aggregate", "1")
    if aggregate not in {"0", "1"}:
        return JsonResponse({"detail": "aggregate必须为0或1"}, status=400)
    path = preview_directory(resource, revision) / (
        "raw.mbtiles" if aggregate == "0" and preview["clustered"] else "tiles.mbtiles"
    )
    try:
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
            row = db.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, x, 2**z - 1 - y),
            ).fetchone()
    except sqlite3.Error:
        return JsonResponse({"detail": "显示瓦片不可用，请重新准备"}, status=404)
    if row is None:
        response = HttpResponse(status=204)
    else:
        body = bytes(row[0])
        etag = '"' + hashlib.sha256(body).hexdigest() + '"'
        if request.headers.get("If-None-Match") == etag:
            response = HttpResponse(status=304)
        else:
            response = HttpResponse(
                body, content_type="application/vnd.mapbox-vector-tile"
            )
            response["Content-Encoding"] = "gzip"
        response["ETag"] = etag
    response["Cache-Control"] = "private, no-cache"
    response["Vary"] = "Cookie, X-Project-Id, X-Page-Session"
    return response
