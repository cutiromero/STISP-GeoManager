from __future__ import annotations

import json
from math import isfinite
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from contextlib import closing
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd
from shapely.geometry import box, shape

from apps.catalog.models import DataResource
from apps.core.runtime_config import runtime_query_result_limit
from apps.core.storage import (
    StoragePathError,
    validate_vector_layer_name,
    vector_geopackage_path,
)


class DataQueryError(ValueError):
    pass


MAX_RTREE_WHERE_IDS = 5000
SPATIAL_QUERY_CHUNK_SIZE = 512
FIELD_PROFILE_SAMPLE_SIZE = 256
COORDINATE_FIELD_NAMES = {
    "longitude",
    "latitude",
    "lon",
    "lat",
    "lng",
    "经度",
    "纬度",
}


@dataclass(frozen=True)
class ResourceProfile:
    fields: list[dict[str, Any]]
    feature_count: int | None
    geometry_type: str
    bounds: list[float]
    raster: dict[str, Any] | None = None


@dataclass(frozen=True)
class GeopackageLayerMetadata:
    name: str
    feature_count: int
    geometry_type: str
    bounds: list[float]
    coordinate_system: str


def geopackage_layer_names(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            """
            SELECT table_name
            FROM gpkg_contents
            WHERE data_type = 'features'
            ORDER BY table_name
            """
        ).fetchall()
    return [str(row[0]) for row in rows]


def geopackage_layer_exists(path: Path, layer_name: str) -> bool:
    if not path.exists():
        return False
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            "SELECT 1 FROM gpkg_contents WHERE data_type = 'features' AND table_name = ?",
            (layer_name,),
        ).fetchone()
    return bool(row)


def geopackage_layer_metadata(path: Path, layer_name: str) -> GeopackageLayerMetadata:
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            """
            SELECT
              c.min_x,
              c.min_y,
              c.max_x,
              c.max_y,
              g.geometry_type_name,
              s.organization,
              s.organization_coordsys_id,
              g.srs_id
            FROM gpkg_contents AS c
            LEFT JOIN gpkg_geometry_columns AS g
              ON g.table_name = c.table_name
            LEFT JOIN gpkg_spatial_ref_sys AS s
              ON s.srs_id = g.srs_id
            WHERE c.data_type = 'features' AND c.table_name = ?
            """,
            (layer_name,),
        ).fetchone()
        if row is None:
            raise DataQueryError(f"GeoPackage 图层不存在：{layer_name}")
        feature_count = connection.execute(
            f"SELECT COUNT(*) FROM {_quote_sql_identifier(layer_name)}"
        ).fetchone()[0]
    min_x, min_y, max_x, max_y, geom_type, org, org_code, srs_id = row
    bounds = (
        [
            round(float(min_x), 6),
            round(float(min_y), 6),
            round(float(max_x), 6),
            round(float(max_y), 6),
        ]
        if None not in (min_x, min_y, max_x, max_y)
        else []
    )
    return GeopackageLayerMetadata(
        name=layer_name,
        feature_count=int(feature_count),
        geometry_type=str(geom_type or ""),
        bounds=bounds,
        coordinate_system=_coordinate_system_label(org, org_code, srs_id),
    )


def geopackage_layer_epsg(path: Path, layer_name: str) -> int | None:
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            """
            SELECT s.organization, s.organization_coordsys_id, g.srs_id
            FROM gpkg_geometry_columns AS g
            LEFT JOIN gpkg_spatial_ref_sys AS s
              ON s.srs_id = g.srs_id
            WHERE g.table_name = ?
            """,
            (layer_name,),
        ).fetchone()
    if row is None:
        return None
    org, org_code, srs_id = row
    if str(org or "").upper() == "EPSG" and org_code:
        return int(org_code)
    if srs_id and int(srs_id) > 0:
        return int(srs_id)
    return None


def _coordinate_system_label(org, org_code, srs_id) -> str:
    if org and org_code:
        return f"{org}:{org_code}"
    if srs_id:
        return f"SRS:{srs_id}"
    return ""


def _quote_sql_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def resource_profile(resource: DataResource) -> ResourceProfile:
    if resource.data_type != DataResource.DataType.VECTOR or not resource.storage_path:
        return ResourceProfile(
            fields=[], feature_count=None, geometry_type="", bounds=[]
        )
    try:
        layer_name = validate_vector_layer_name(resource.storage_path)
        path = vector_geopackage_path()
    except StoragePathError as exc:
        raise DataQueryError(str(exc)) from exc
    if not geopackage_layer_exists(path, layer_name):
        # Preserve the existing archive-recovery behavior without decoding the
        # complete layer merely to populate the profile panel.
        read_resource(resource, rows=slice(0, 1))
    metadata = geopackage_layer_metadata(path, layer_name)
    return ResourceProfile(
        fields=geopackage_field_profiles(path, layer_name),
        feature_count=metadata.feature_count,
        geometry_type=_api_geometry_type(metadata.geometry_type),
        bounds=_layer_bounds_to_4326(path, layer_name, metadata.bounds),
    )


def query_resource(resource: DataResource, payload: dict[str, Any]) -> dict[str, Any]:
    from apps.catalog.geojson_validation import validate_geojson_geometries

    started_at = perf_counter()
    if resource.data_type != DataResource.DataType.VECTOR:
        raise DataQueryError("当前只支持矢量 GeoPackage 查询")

    spatial_filter = payload.get("spatialFilter")
    attribute_filters = payload.get("attributeFilters") or []
    query_geometry = spatial_filter_geometry(spatial_filter)
    limit = _limit(payload.get("limit"))
    layer_name = validate_vector_layer_name(resource.storage_path or "")
    path = vector_geopackage_path()
    if not geopackage_layer_exists(path, layer_name):
        read_resource(resource, rows=slice(0, 1))
    fields = geopackage_field_profiles(path, layer_name)

    where = _attribute_filter_where(fields, attribute_filters)
    if query_geometry is None:
        total_count = _geopackage_filtered_count(path, layer_name, where)
        gdf = read_resource(resource, where=where, rows=slice(0, limit))
        valid_gdf, warnings = validate_geojson_geometries(gdf)
        returned = valid_gdf.head(limit)
    else:
        returned, total_count, warnings = _query_spatial_resource_in_chunks(
            resource,
            spatial_filter=spatial_filter,
            query_geometry=query_geometry,
            where=where,
            limit=limit,
        )

    bounds = _returned_bounds(returned)
    returned = normalize_for_geojson(returned)

    return {
        "resourceId": resource.id,
        "resourceName": resource.name,
        "totalCount": total_count,
        "returnedCount": len(returned),
        "limit": limit,
        "limitExceeded": total_count > limit,
        "bounds": bounds,
        "elapsedMs": max(0, round((perf_counter() - started_at) * 1000)),
        "fields": fields,
        "geojson": json.loads(returned.to_json()),
        "warnings": warnings,
    }


def _query_spatial_resource_in_chunks(
    resource: DataResource,
    *,
    spatial_filter: dict[str, Any] | None,
    query_geometry,
    where: str | None,
    limit: int,
):
    from apps.catalog.geojson_validation import GeometryValidationAccumulator

    empty = read_resource(resource, where=where, rows=slice(0, 0))
    if query_geometry.is_empty:
        return empty, 0, []

    accumulator = GeometryValidationAccumulator()
    returned_chunks = []
    returned_count = 0
    total_count = 0
    bbox = _spatial_prefilter_bbox(query_geometry)

    for chunk in _iter_resource_chunks(
        resource,
        bbox=bbox,
        where=where,
        chunk_size=SPATIAL_QUERY_CHUNK_SIZE,
    ):
        filtered = apply_spatial_filter(
            chunk, spatial_filter, query_geometry=query_geometry
        )
        total_count += len(filtered)
        valid = accumulator.filter(filtered)
        remaining = limit - returned_count
        if remaining > 0 and len(valid):
            selected = valid.head(remaining)
            returned_chunks.append(selected)
            returned_count += len(selected)

    returned = _combine_geodataframe_chunks(returned_chunks, empty)
    return returned, total_count, accumulator.warnings()


def _iter_resource_chunks(
    resource: DataResource,
    *,
    bbox: tuple[float, float, float, float] | None,
    where: str | None,
    chunk_size: int,
):
    offset = 0
    while True:
        chunk = read_resource(
            resource,
            bbox=bbox,
            where=where,
            rows=slice(offset, offset + chunk_size),
        )
        if len(chunk) == 0:
            return
        yield chunk
        offset += chunk_size


def _combine_geodataframe_chunks(chunks: list[Any], empty):
    if not chunks:
        return empty
    if len(chunks) == 1:
        return chunks[0]

    import geopandas as gpd

    first = chunks[0]
    combined = pd.concat(chunks, ignore_index=True)
    return gpd.GeoDataFrame(
        combined,
        geometry=first.geometry.name,
        crs=first.crs,
    )


def read_resource(
    resource: DataResource,
    bbox: tuple[float, float, float, float] | None = None,
    *,
    where: str | None = None,
    rows: slice | int | None = None,
):
    if not resource.storage_path:
        raise DataQueryError("数据资源未配置 GeoPackage 图层名")
    try:
        layer_name = validate_vector_layer_name(resource.storage_path)
        path = vector_geopackage_path()
    except StoragePathError as exc:
        raise DataQueryError(str(exc)) from exc
    if not geopackage_layer_exists(path, layer_name):
        from apps.catalog.vector_recovery import recover_vector_layer_from_archive

        if not recover_vector_layer_from_archive(resource):
            raise DataQueryError(
                "原始矢量图层已缺失且没有可用归档，请重新导入该数据后再加载工程"
            )
    return _read_layer_from_path(path, layer_name, bbox=bbox, where=where, rows=rows)


def _read_layer_from_path(
    path: Path,
    layer_name: str,
    *,
    bbox: tuple[float, float, float, float] | None,
    where: str | None = None,
    rows: slice | int | None = None,
):
    if not path.exists():
        raise DataQueryError(f"统一 GeoPackage 文件不存在：{path}")

    try:
        import geopandas as gpd

        gdf = _read_geopackage_layer(
            gpd, path, layer_name, bbox=bbox, where=where, rows=rows
        )
    except Exception as exc:
        raise DataQueryError(f"读取 GeoPackage 图层失败：{layer_name}，{exc}") from exc

    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    return gdf


def _read_geopackage_layer(
    gpd, path: Path, layer_name: str, *, bbox=None, where=None, rows=None
):
    read_options = {}
    if where:
        read_options["where"] = where
    if rows is not None:
        read_options["rows"] = rows
    if bbox is None:
        return gpd.read_file(path, layer=layer_name, **read_options)

    read_bbox = _bbox_for_layer_crs(gpd, path, layer_name, bbox)
    if read_bbox is None:
        return gpd.read_file(path, layer=layer_name, **read_options)
    candidate_ids = _rtree_candidate_feature_ids(path, layer_name, read_bbox)
    if candidate_ids == []:
        empty_options = {key: value for key, value in read_options.items() if key != "rows"}
        return gpd.read_file(path, layer=layer_name, rows=0, **empty_options)
    if candidate_ids is not None and len(candidate_ids) <= MAX_RTREE_WHERE_IDS:
        where_clause = _feature_id_where_clause(path, layer_name, candidate_ids)
        if where_clause:
            try:
                combined_where = _combine_where_clauses(where_clause, where)
                return gpd.read_file(
                    path, layer=layer_name, where=combined_where, **({"rows": rows} if rows is not None else {})
                )
            except Exception:
                pass
    return gpd.read_file(path, layer=layer_name, bbox=read_bbox, **read_options)


def _combine_where_clauses(first: str | None, second: str | None) -> str | None:
    clauses = [clause for clause in (first, second) if clause]
    return " AND ".join(f"({clause})" for clause in clauses) or None


def _bbox_for_layer_crs(
    gpd, path: Path, layer_name: str, bbox: tuple[float, float, float, float]
):
    epsg = geopackage_layer_epsg(path, layer_name)
    if epsg is None:
        return None
    if epsg == 4326:
        return bbox
    projected = gpd.GeoSeries([box(*bbox)], crs="EPSG:4326").to_crs(f"EPSG:{epsg}")
    return tuple(float(value) for value in projected.total_bounds.tolist())


def _rtree_candidate_feature_ids(
    path: Path,
    layer_name: str,
    bbox: tuple[float, float, float, float],
) -> list[int] | None:
    minx, miny, maxx, maxy = bbox
    with closing(sqlite3.connect(path)) as connection:
        geometry_column = _geometry_column_name(connection, layer_name)
        if geometry_column is None:
            return None
        rtree_name = f"rtree_{layer_name}_{geometry_column}"
        if not _sqlite_table_exists(connection, rtree_name):
            return None
        rows = connection.execute(
            f"""
            SELECT id
            FROM {_quote_sql_identifier(rtree_name)}
            WHERE maxx >= ? AND minx <= ? AND maxy >= ? AND miny <= ?
            LIMIT ?
            """,
            (minx, maxx, miny, maxy, MAX_RTREE_WHERE_IDS + 1),
        ).fetchall()
    if len(rows) > MAX_RTREE_WHERE_IDS:
        return None
    return [int(row[0]) for row in rows]


def _feature_id_where_clause(
    path: Path,
    layer_name: str,
    feature_ids: list[int],
) -> str:
    if not feature_ids:
        return ""
    with closing(sqlite3.connect(path)) as connection:
        fid_column = _primary_key_column_name(connection, layer_name)
    if fid_column is None:
        return ""
    joined_ids = ",".join(str(feature_id) for feature_id in feature_ids)
    return f"{_quote_sql_identifier(fid_column)} IN ({joined_ids})"


def _geometry_column_name(
    connection: sqlite3.Connection, layer_name: str
) -> str | None:
    row = connection.execute(
        "SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?",
        (layer_name,),
    ).fetchone()
    return str(row[0]) if row else None


def _primary_key_column_name(
    connection: sqlite3.Connection, table_name: str
) -> str | None:
    rows = connection.execute(
        f"PRAGMA table_info({_quote_sql_identifier(table_name)})"
    ).fetchall()
    for row in rows:
        if int(row[5]) > 0:
            return str(row[1])
    return None


def _sqlite_table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def read_field_metadata(path: Path, table_name: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    try:
        with closing(sqlite3.connect(path)) as connection:
            cursor = connection.execute(
                "SELECT column_name, description FROM gpkg_data_columns WHERE table_name = ?",
                (table_name,),
            )
            for column_name, description in cursor.fetchall():
                if description:
                    metadata[column_name] = description
    except sqlite3.OperationalError as exc:
        if "no such table: gpkg_data_columns" in str(exc):
            return metadata
        raise DataQueryError(f"读取 GeoPackage 字段元数据失败：{table_name}") from exc
    return metadata


def field_metadata_for_layer(layer_name: str) -> dict[str, str]:
    try:
        validated_name = validate_vector_layer_name(layer_name)
        path = vector_geopackage_path()
    except StoragePathError as exc:
        raise DataQueryError(str(exc)) from exc
    if not path.exists():
        return {}
    return read_field_metadata(path, validated_name)


def geopackage_field_profiles(
    path: Path, layer_name: str, *, sample_size: int = FIELD_PROFILE_SAMPLE_SIZE
) -> list[dict[str, Any]]:
    metadata = read_field_metadata(path, layer_name)
    with closing(sqlite3.connect(path)) as connection:
        columns = connection.execute(
            f"PRAGMA table_info({_quote_sql_identifier(layer_name)})"
        ).fetchall()
        geometry_column = _geometry_column_name(connection, layer_name)
        attribute_columns = [
            row
            for row in columns
            if str(row[1]) != geometry_column and int(row[5]) == 0
        ]
        names = [str(row[1]) for row in attribute_columns]
        if names:
            selected = ", ".join(_quote_sql_identifier(name) for name in names)
            samples = connection.execute(
                f"SELECT {selected} FROM {_quote_sql_identifier(layer_name)} LIMIT ?",
                (max(1, sample_size),),
            ).fetchall()
        else:
            samples = []

    frame = pd.DataFrame(samples, columns=names)
    profiles = []
    for row in attribute_columns:
        name = str(row[1])
        declared_type = str(row[2] or "")
        not_null = bool(row[3])
        series = frame[name] if name in frame else pd.Series(dtype="object")
        profiles.append(
            {
                "name": name,
                "type": _declared_or_sample_field_type(declared_type, series),
                "nullable": not not_null or bool(series.isna().any()),
                "sampleValues": [
                    _json_value(value) for value in series.dropna().head(8).tolist()
                ],
                "description": metadata.get(name, ""),
            }
        )
    return profiles


def _declared_or_sample_field_type(declared_type: str, series) -> str:
    normalized = declared_type.upper()
    if "BOOL" in normalized:
        return "boolean"
    if "DATE" in normalized or "TIME" in normalized:
        return "datetime"
    if any(
        token in normalized
        for token in ("INT", "REAL", "FLOA", "DOUB", "NUM", "DEC")
    ):
        return "number"
    return _field_type(series)


def _layer_bounds_to_4326(
    path: Path, layer_name: str, bounds: list[float]
) -> list[float]:
    if len(bounds) != 4:
        return []
    epsg = geopackage_layer_epsg(path, layer_name)
    if epsg in (None, 4326):
        return bounds
    try:
        import geopandas as gpd

        projected = gpd.GeoSeries([box(*bounds)], crs=f"EPSG:{epsg}").to_crs(
            "EPSG:4326"
        )
        return [round(float(value), 6) for value in projected.total_bounds.tolist()]
    except Exception as exc:
        raise DataQueryError(f"转换 GeoPackage 图层范围失败：{layer_name}：{exc}") from exc


def _api_geometry_type(value: str) -> str:
    normalized = value.strip().upper().replace(" ", "")
    return {
        "POINT": "Point",
        "LINESTRING": "LineString",
        "POLYGON": "Polygon",
        "MULTIPOINT": "MultiPoint",
        "MULTILINESTRING": "MultiLineString",
        "MULTIPOLYGON": "MultiPolygon",
        "GEOMETRYCOLLECTION": "GeometryCollection",
    }.get(normalized, value)


def _attribute_filter_where(
    fields: list[dict[str, Any]], filters: list[dict[str, Any]]
) -> str | None:
    field_types = {field["name"]: field["type"] for field in fields}
    clauses = []
    for filter_item in filters:
        field = str(filter_item.get("field", "")).strip()
        operator = str(filter_item.get("operator", "contains")).strip()
        if field not in field_types:
            raise DataQueryError(f"属性字段不存在：{field}")
        column = _quote_sql_identifier(field)
        numeric = field_types[field] == "number"
        expression = (
            f"CAST(REPLACE(TRIM(CAST({column} AS TEXT)), ',', '') AS REAL)"
            if numeric
            else column
        )
        value = filter_item.get("value")
        if operator == "contains":
            escaped = (
                str(value or "")
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            clauses.append(
                f"CAST({column} AS TEXT) LIKE {_sql_literal('%' + escaped + '%')} ESCAPE '\\' COLLATE NOCASE"
            )
        elif operator in {"eq", "ne", "gt", "gte", "lt", "lte"}:
            symbols = {
                "eq": "=",
                "ne": "!=",
                "gt": ">",
                "gte": ">=",
                "lt": "<",
                "lte": "<=",
            }
            clauses.append(
                f"{expression} {symbols[operator]} {_filter_sql_literal(value, numeric)}"
            )
        elif operator == "between":
            clauses.append(
                f"{expression} BETWEEN {_filter_sql_literal(value, numeric)} "
                f"AND {_filter_sql_literal(filter_item.get('valueTo'), numeric)}"
            )
        else:
            raise DataQueryError(f"不支持的属性操作符：{operator}")
    return " AND ".join(f"({clause})" for clause in clauses) or None


def _filter_sql_literal(value: Any, numeric: bool) -> str:
    if not numeric:
        return _sql_literal(str(value))
    try:
        parsed = float(_clean_numeric_text(value))
    except (TypeError, ValueError) as exc:
        raise DataQueryError(f"数值查询条件无效：{value}") from exc
    if not isfinite(parsed):
        raise DataQueryError(f"数值查询条件无效：{value}")
    return repr(parsed)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _geopackage_filtered_count(
    path: Path, layer_name: str, where: str | None
) -> int:
    statement = f"SELECT COUNT(*) FROM {_quote_sql_identifier(layer_name)}"
    if where:
        statement += f" WHERE {where}"
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(statement).fetchone()
    return int(row[0] if row else 0)


def field_profiles(
    gdf, field_metadata: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    geometry_name = (
        gdf.geometry.name if getattr(gdf, "geometry", None) is not None else "geometry"
    )
    fields = []
    for column in gdf.columns:
        if column == geometry_name:
            continue
        series = gdf[column]
        samples = []
        for value in series.dropna().head(8).tolist():
            samples.append(_json_value(value))
        description = (field_metadata or {}).get(column, "")
        fields.append(
            {
                "name": column,
                "type": _field_type(series),
                "nullable": bool(series.isna().any()),
                "sampleValues": samples,
                "description": description,
            }
        )
    return fields


def geometry_type(gdf) -> str:
    if len(gdf) == 0:
        return ""
    values = sorted(set(gdf.geometry.geom_type.dropna().astype(str).tolist()))
    if len(values) == 1:
        return values[0]
    return "Mixed"


def spatial_filter_geometry(spatial_filter: dict[str, Any] | None):
    if not spatial_filter:
        return None
    geometry = spatial_filter.get("geometry")
    if not geometry:
        return None
    try:
        query_geometry = shape(geometry)
    except Exception as exc:
        raise DataQueryError(f"空间查询图形无效：{exc}") from exc
    if query_geometry.is_empty:
        return query_geometry
    return query_geometry


def _spatial_prefilter_bbox(query_geometry) -> tuple[float, float, float, float] | None:
    if query_geometry is None:
        return None
    if query_geometry.is_empty:
        return None
    minx, miny, maxx, maxy = query_geometry.bounds
    return float(minx), float(miny), float(maxx), float(maxy)


def apply_spatial_filter(
    gdf, spatial_filter: dict[str, Any] | None, *, query_geometry=None
):
    if not spatial_filter:
        return gdf
    if query_geometry is None:
        query_geometry = spatial_filter_geometry(spatial_filter)
    if query_geometry is None:
        return gdf
    if query_geometry.is_empty:
        return gdf.iloc[0:0]
    return gdf[gdf.geometry.intersects(query_geometry)]


def apply_attribute_filters(gdf, filters: list[dict[str, Any]]):
    geometry = getattr(gdf, "geometry", None)
    geometry_name = getattr(geometry, "name", None)
    for filter_item in filters:
        field = str(filter_item.get("field", "")).strip()
        operator = str(filter_item.get("operator", "contains")).strip()
        if field not in gdf.columns or field == geometry_name:
            raise DataQueryError(f"属性字段不存在：{field}")

        series = gdf[field]
        value = filter_item.get("value")
        if operator == "contains":
            mask = series.astype(str).str.contains(
                str(value or ""), case=False, na=False
            )
        elif operator == "eq":
            comparison_series = _comparison_series(series)
            mask = comparison_series == _coerce_value(comparison_series, value)
        elif operator == "ne":
            comparison_series = _comparison_series(series)
            mask = comparison_series != _coerce_value(comparison_series, value)
        elif operator in {"gt", "gte", "lt", "lte"}:
            comparison_series = _comparison_series(series)
            typed_value = _coerce_value(comparison_series, value)
            if operator == "gt":
                mask = comparison_series > typed_value
            elif operator == "gte":
                mask = comparison_series >= typed_value
            elif operator == "lt":
                mask = comparison_series < typed_value
            else:
                mask = comparison_series <= typed_value
        elif operator == "between":
            comparison_series = _comparison_series(series)
            low = _coerce_value(comparison_series, value)
            high = _coerce_value(comparison_series, filter_item.get("valueTo"))
            mask = comparison_series.between(low, high)
        else:
            raise DataQueryError(f"不支持的属性操作符：{operator}")
        gdf = gdf[mask.fillna(False)]
    return gdf


def normalize_for_geojson(gdf):
    normalized = gdf.copy()
    for column in normalized.columns:
        if column == normalized.geometry.name:
            continue
        series = normalized[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            normalized[column] = series.dt.strftime("%Y-%m-%d")
        elif _normalized_field_name(column) in COORDINATE_FIELD_NAMES:
            numeric = _numeric_series(series)
            normalized[column] = (
                numeric.map(_json_value) if numeric is not None else series.map(_json_value)
            )
        else:
            normalized[column] = series.map(_json_value)
    return normalized


def _returned_bounds(gdf) -> list[float]:
    if len(gdf) == 0:
        return []
    bounds = [float(value) for value in gdf.total_bounds.tolist()]
    if len(bounds) != 4 or not all(isfinite(value) for value in bounds):
        return []
    return [round(value, 6) for value in bounds]


def _limit(value: Any) -> int:
    max_limit = runtime_query_result_limit()
    try:
        limit = int(value or max_limit)
    except (TypeError, ValueError):
        limit = max_limit
    return min(max(limit, 1), max_limit)


def _coerce_value(series, value: Any):
    if pd.api.types.is_numeric_dtype(series):
        try:
            return pd.to_numeric(_clean_numeric_text(value))
        except (TypeError, ValueError) as exc:
            raise DataQueryError(f"数值查询条件无效：{value}") from exc
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(value)
    return str(value)


def _field_type(series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if _numeric_series(series) is not None:
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "string"


def _comparison_series(series):
    numeric = _numeric_series(series)
    return numeric if numeric is not None else series


def _numeric_series(series):
    if pd.api.types.is_bool_dtype(series):
        return None
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    if pd.api.types.is_datetime64_any_dtype(series):
        return None
    non_null = series.dropna()
    if non_null.empty:
        return None
    cleaned = non_null.map(_clean_numeric_text)
    non_empty = cleaned[cleaned != ""]
    if non_empty.empty:
        return None
    converted = pd.to_numeric(non_empty, errors="coerce")
    if not converted.notna().all():
        return None
    return pd.to_numeric(series.map(_clean_numeric_text), errors="coerce")


def _clean_numeric_text(value: Any) -> str:
    return str(value).strip().replace(",", "")


def _normalized_field_name(value: Any) -> str:
    return str(value).strip().lower().replace("_", "").replace("-", "")


def _json_value(value: Any):
    if pd.isna(value):
        return None
    if isinstance(value, datetime | date):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value
