from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils.text import slugify
from shapely.geometry import Point

from apps.catalog.models import DataResource, DictionaryItem
from apps.catalog.services import stable_catalog_code
from apps.catalog.taxonomy import TaxonomyError, resolve_data_category
from apps.catalog.vector_store import geopackage_layer_exists
from apps.catalog.vector_storage import append_geopackage_layer
from apps.core.initialization import ensure_superadmin_defaults
from apps.core.principal_visibility import selectable_access_groups_for
from apps.core.runtime_config import RuntimeConfigError, runtime_upload_max_mb
from apps.core.storage import table_data_path, vector_geopackage_path
from apps.standards.models import DataDomainType


class ImportDataError(ValueError):
    pass


MAX_PREVIEW_ROWS = 8
MAX_TABLE_NAME_LENGTH = 63
MAX_TABLE_PARSE_UPLOAD_MB = 16
MAX_XLSX_EXPANDED_BYTES = 128 * 1024 * 1024
COORDINATE_UNCERTAINTY_RATIO_THRESHOLD = 200
TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
LATITUDE_ALIASES = {
    "lat",
    "latitude",
    "纬度",
    "北纬",
    "纬度坐标",
    "y",
    "decimal_latitude",
    "lat_deg",
    "lat_dd",
}
LONGITUDE_ALIASES = {
    "lon",
    "lng",
    "long",
    "longitude",
    "经度",
    "东经",
    "经度坐标",
    "x",
    "decimal_longitude",
    "lon_deg",
    "lon_dd",
}
NORMALIZED_LATITUDE_ALIASES = {
    re.sub(r"[\s\-_()（）]+", "", alias.strip().lower()) for alias in LATITUDE_ALIASES
}
NORMALIZED_LONGITUDE_ALIASES = {
    re.sub(r"[\s\-_()（）]+", "", alias.strip().lower()) for alias in LONGITUDE_ALIASES
}


@dataclass(frozen=True)
class CoordinateStats:
    total_rows: int
    valid_rows: int
    missing_rows: int
    error_min_meters: float | None
    error_max_meters: float | None


@dataclass(frozen=True)
class ImportValidationIssue:
    code: str
    message: str
    count: int | None = None
    blocking: bool = True
    min_meters: float | None = None
    max_meters: float | None = None
    ratio: float | None = None
    target_type: str | None = None
    target_name: str | None = None


@dataclass(frozen=True)
class WorkbookSheetSummary:
    name: str
    row_count: int
    column_count: int
    is_geographic: bool
    longitude_column: str | None
    latitude_column: str | None


def preview_uploaded_table(
    uploaded_file, sheet_name: str | None = None
) -> dict[str, Any]:
    filename = str(uploaded_file.name or "")
    source = _uploaded_table_source(uploaded_file, filename)
    sheets = workbook_sheet_summaries(source, filename)
    active_sheet = _selected_sheet_name(sheets, sheet_name)
    _rewind_table_source(source)
    df = read_table_source(source, filename, sheet_name=active_sheet)
    columns = list(df.columns)
    longitude_column, latitude_column = infer_coordinate_columns(df)
    suggested_name = _suggested_display_name(Path(filename).stem, active_sheet, sheets)
    suggested_table_name = suggest_table_name(suggested_name)
    return {
        "columns": columns,
        "rows": _preview_rows(df),
        "rowCount": int(len(df)),
        "suggestedTableName": suggested_table_name,
        "suggestedName": suggested_name,
        "activeSheetName": active_sheet,
        "sheets": [_serialize_workbook_sheet(sheet) for sheet in sheets],
        "duplicateTarget": duplicate_target_for_display_name(suggested_name),
        "detected": {
            "isGeographic": bool(longitude_column and latitude_column),
            "longitudeColumn": longitude_column,
            "latitudeColumn": latitude_column,
            "coordinateStats": None,
            "validationIssues": [],
        },
        "limitations": [
            "支持 Excel 或 CSV 文件；Excel 会自动识别所有工作表，每个工作表可作为独立表格单独导入。",
            "导入时所有字段按文本读取，以保留经纬度记录的小数位数。",
            "经纬度支持十进制度、度分秒符号格式和 79480913 / 40212444 这类紧凑度分秒格式，导入时统一转换为 EPSG:4326 十进制度。",
            "字段元数据可留空，但建议填写中文名称、单位、计算方式和数据来源。",
        ],
    }


def validate_uploaded_table(uploaded_file, payload: dict[str, Any]) -> dict[str, Any]:
    df = read_uploaded_table(uploaded_file, sheet_name=_payload_sheet_name(payload))
    import_mode = str(payload.get("importMode") or "").strip()
    table_name = str(payload.get("tableName") or "").strip()
    display_name = str(payload.get("name") or "").strip()
    longitude_column = str(payload.get("longitudeColumn") or "").strip()
    latitude_column = str(payload.get("latitudeColumn") or "").strip()

    if import_mode not in {"geographic", "table"}:
        raise ImportDataError("导入方式必须是 geographic 或 table")
    duplicate_target = (
        duplicate_target_for_display_name(display_name) if display_name else None
    )
    if table_name:
        table_name = validate_import_table_name(table_name)
    if import_mode == "table":
        return {
            "coordinateStats": None,
            "validationIssues": [],
            "duplicateTarget": duplicate_target,
        }
    if longitude_column not in df.columns or latitude_column not in df.columns:
        raise ImportDataError("地理数据必须指定有效的经度列和纬度列")

    stats = coordinate_stats_for(df, longitude_column, latitude_column)
    issues = validate_coordinate_columns(df, longitude_column, latitude_column)
    return {
        "coordinateStats": _serialize_coordinate_stats(stats),
        "validationIssues": _serialize_validation_issues(issues),
        "duplicateTarget": duplicate_target,
    }


@transaction.atomic
def import_uploaded_table(
    uploaded_file, payload: dict[str, Any], user
) -> dict[str, Any]:
    df = read_uploaded_table(uploaded_file, sheet_name=_payload_sheet_name(payload))
    name = _required_text(payload.get("name"), "数据名称")
    requested_table_name = validate_import_table_name(
        _required_text(payload.get("tableName"), "后台存储标识")
    )
    import_mode = str(payload.get("importMode") or "").strip()
    longitude_column = str(payload.get("longitudeColumn") or "").strip()
    latitude_column = str(payload.get("latitudeColumn") or "").strip()
    ignore_coordinate_uncertainty = bool(
        payload.get("ignoreCoordinateUncertainty", False)
    )
    duplicate_confirmed = bool(payload.get("duplicateConfirmed", False))
    file_size = int(getattr(uploaded_file, "size", 0) or 0)
    access_group_ids = _access_group_ids(payload.get("accessGroupIds"))
    domain_type = _domain_type(payload.get("domainType"))
    category = _optional_data_category(payload.get("categoryCode"))

    if import_mode not in {"geographic", "table"}:
        raise ImportDataError("导入方式必须是 geographic 或 table")
    _ensure_display_name_can_be_imported(name, duplicate_confirmed)
    table_name = unique_import_table_name(requested_table_name, import_mode)

    if import_mode == "geographic":
        if longitude_column not in df.columns or latitude_column not in df.columns:
            raise ImportDataError("地理数据必须指定有效的经度列和纬度列")
        included_columns = _included_columns(
            payload.get("includedColumns"),
            df.columns,
            required_columns={longitude_column, latitude_column},
        )
        df = df[included_columns].copy()
        metadata = _metadata_map(payload.get("fieldMetadata"), set(included_columns))
        return import_geographic_table(
            df=df,
            name=name,
            table_name=table_name,
            longitude_column=longitude_column,
            latitude_column=latitude_column,
            metadata=metadata,
            ignore_coordinate_uncertainty=ignore_coordinate_uncertainty,
            source_size_bytes=file_size,
            user=user,
            access_group_ids=access_group_ids,
            domain_type=domain_type,
            category=category,
        )

    included_columns = _included_columns(payload.get("includedColumns"), df.columns)
    df = df[included_columns].copy()
    metadata = _metadata_map(payload.get("fieldMetadata"), set(included_columns))
    return import_plain_table(
        df=df,
        name=name,
        table_name=table_name,
        metadata=metadata,
        source_size_bytes=file_size,
        user=user,
        access_group_ids=access_group_ids,
        domain_type=domain_type,
        category=category,
    )


def import_geographic_table(
    *,
    df: pd.DataFrame,
    name: str,
    table_name: str,
    longitude_column: str,
    latitude_column: str,
    metadata: dict[str, str],
    ignore_coordinate_uncertainty: bool,
    source_size_bytes: int,
    user,
    access_group_ids: set[int],
    domain_type: str,
    category: DictionaryItem | None,
) -> dict[str, Any]:
    stats = coordinate_stats_for(df, longitude_column, latitude_column)
    validation_issues = validate_coordinate_columns(
        df, longitude_column, latitude_column
    )
    blocking_issues = [
        issue
        for issue in validation_issues
        if issue.blocking
        or (
            issue.code == "coordinate_uncertainty" and not ignore_coordinate_uncertainty
        )
    ]
    if blocking_issues:
        raise ImportDataError(
            "数据校验未通过", _serialize_validation_issues(validation_issues)
        )

    import geopandas as gpd

    working = df.copy()
    valid_mask = _valid_coordinate_mask(working, longitude_column, latitude_column)

    geometries = []
    for index, row in working.iterrows():
        if not bool(valid_mask.loc[index]):
            continue
        longitude = _coordinate_decimal(row[longitude_column], is_longitude=True)
        latitude = _coordinate_decimal(row[latitude_column], is_longitude=False)
        if longitude is None or latitude is None:
            continue
        geometries.append(
            Point(float(longitude), float(latitude))
        )

    working = working[valid_mask].copy()
    working = normalize_coordinate_columns(
        working, longitude_column=longitude_column, latitude_column=latitude_column
    )

    gdf = gpd.GeoDataFrame(working, geometry=geometries, crs="EPSG:4326")
    path = vector_geopackage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_table_can_be_written(path, table_name, geographic=True)
    _write_geopackage_layer(path, table_name, gdf)
    write_geopackage_field_metadata(path, table_name, metadata)

    bounds = (
        [
            round(float(value), 6)
            for value in gdf[gdf.geometry.notna()].total_bounds.tolist()
        ]
        if stats.valid_rows
        else []
    )
    resource = _upsert_geographic_resource(
        name=name,
        table_name=table_name,
        bounds=bounds,
        stats=stats,
        ignore_coordinate_uncertainty=ignore_coordinate_uncertainty,
        source_size_bytes=source_size_bytes,
        user=user,
        domain_type=domain_type,
        category=category,
    )
    set_resource_access_groups(resource, access_group_ids, viewer=user)
    return {
        "mode": "geographic",
        "resourceId": resource.id,
        "resourceName": resource.name,
        "layerName": table_name,
        "tableName": table_name,
        "importedRows": int(len(gdf)),
        "skippedRows": 0,
        "bounds": bounds,
        "coordinateStats": _serialize_coordinate_stats(stats),
        "validationIssues": _serialize_validation_issues(validation_issues),
    }


def import_plain_table(
    *,
    df: pd.DataFrame,
    name: str,
    table_name: str,
    metadata: dict[str, str],
    source_size_bytes: int,
    user,
    access_group_ids: set[int],
    domain_type: str,
    category: DictionaryItem | None,
) -> dict[str, Any]:
    path = table_data_path("data.sqlite")
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_table_can_be_written(path, table_name, geographic=False)
    with sqlite3.connect(path) as connection:
        df.to_sql(table_name, connection, if_exists="fail", index=False)
        write_sqlite_field_metadata(connection, table_name, metadata)

    code = _unique_resource_code(stable_catalog_code("table", table_name))
    resource = DataResource.objects.create(
        code=code,
        name=name,
        data_type=DataResource.DataType.TABLE,
        domain_type=domain_type,
        category=category,
        source="用户导入",
        provider="",
        spatial_extent="",
        coordinate_system="",
        file_format="SQLITE",
        storage_path=table_name,
        description=f"由 Excel/CSV 导入的非地理表：{table_name}",
        quality_note="",
        maintainer=user if getattr(user, "is_authenticated", False) else None,
        size_bytes=source_size_bytes,
        item_count=int(len(df)),
        status=DataResource.Status.ACTIVE,
    )
    set_resource_access_groups(resource, access_group_ids, viewer=user)
    return {
        "mode": "table",
        "resourceId": resource.id,
        "resourceName": resource.name,
        "layerId": None,
        "tableName": table_name,
        "importedRows": int(len(df)),
        "skippedRows": 0,
        "coordinateStats": None,
        "validationIssues": [],
    }


def read_uploaded_table(uploaded_file, sheet_name: str | None = None) -> pd.DataFrame:
    filename = str(uploaded_file.name or "")
    source = _uploaded_table_source(uploaded_file, filename)
    return read_table_source(source, filename, sheet_name=sheet_name)


def read_table_bytes(
    raw: bytes, filename: str, *, sheet_name: str | None = None
) -> pd.DataFrame:
    return read_table_source(BytesIO(raw), filename, sheet_name=sheet_name)


def read_table_source(
    source, filename: str, *, sheet_name: str | None = None
) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    if _table_source_is_empty(source):
        raise ImportDataError("上传文件为空")

    try:
        if suffix == ".csv":
            df = _read_csv_source(source)
        elif suffix in {".xls", ".xlsx"}:
            _rewind_table_source(source)
            df = pd.read_excel(
                source,
                sheet_name=sheet_name or 0,
                dtype=str,
                keep_default_na=False,
                na_filter=False,
            )
        else:
            raise ImportDataError("仅支持 .csv、.xls、.xlsx 文件")
    except ImportDataError:
        raise
    except ImportError as exc:
        raise ImportDataError(f"缺少读取该文件格式所需的 Python 依赖：{exc}") from exc
    except Exception as exc:
        raise ImportDataError(f"读取上传表格失败：{exc}") from exc

    if df.empty and not list(df.columns):
        raise ImportDataError("表格没有可导入的字段")
    return normalize_dataframe(df)


def workbook_sheet_summaries(source, filename: str) -> list[WorkbookSheetSummary]:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".xls", ".xlsx"}:
        return []
    if _table_source_is_empty(source):
        raise ImportDataError("上传文件为空")
    try:
        _rewind_table_source(source)
        workbook = pd.ExcelFile(source)
    except Exception as exc:
        raise ImportDataError(f"读取上传表格失败：{exc}") from exc

    summaries: list[WorkbookSheetSummary] = []
    try:
        for sheet in workbook.sheet_names:
            df = pd.read_excel(
                workbook,
                sheet_name=sheet,
                dtype=str,
                keep_default_na=False,
                na_filter=False,
            )
            normalized = normalize_dataframe(df)
            longitude_column, latitude_column = infer_coordinate_columns(normalized)
            summaries.append(
                WorkbookSheetSummary(
                    name=str(sheet),
                    row_count=int(len(normalized)),
                    column_count=len(normalized.columns),
                    is_geographic=bool(longitude_column and latitude_column),
                    longitude_column=longitude_column,
                    latitude_column=latitude_column,
                )
            )
    finally:
        workbook.close()
    return summaries


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = _unique_column_names(normalized.columns)
    normalized = normalized.fillna("")
    for column in normalized.columns:
        normalized[column] = normalized[column].map(
            lambda value: "" if pd.isna(value) else str(value).strip()
        )
    return normalized


def infer_coordinate_columns(df: pd.DataFrame) -> tuple[str | None, str | None]:
    longitude = _best_coordinate_column(df, is_longitude=True)
    latitude = _best_coordinate_column(df, is_longitude=False)
    if longitude and latitude and longitude != latitude:
        return longitude, latitude
    return None, None


def coordinate_stats_for(
    df: pd.DataFrame, longitude_column: str, latitude_column: str
) -> CoordinateStats:
    valid_mask = _valid_coordinate_mask(df, longitude_column, latitude_column)
    minimum_error: float | None = None
    maximum_error: float | None = None
    for _, row in df[valid_mask].iterrows():
        lon_text = str(row[longitude_column]).strip()
        lat_text = str(row[latitude_column]).strip()
        error = _position_error_meters(lon_text, lat_text)
        minimum_error = error if minimum_error is None else min(minimum_error, error)
        maximum_error = error if maximum_error is None else max(maximum_error, error)
    return CoordinateStats(
        total_rows=int(len(df)),
        valid_rows=int(valid_mask.sum()),
        missing_rows=int(len(df) - valid_mask.sum()),
        error_min_meters=round(minimum_error, 6) if minimum_error is not None else None,
        error_max_meters=round(maximum_error, 6) if maximum_error is not None else None,
    )


def validate_coordinate_columns(
    df: pd.DataFrame, longitude_column: str, latitude_column: str
) -> list[ImportValidationIssue]:
    issues: list[ImportValidationIssue] = []
    missing_count = 0
    invalid_format_count = 0
    invalid_longitude_count = 0
    invalid_latitude_count = 0
    minimum_positive_error: float | None = None
    maximum_positive_error: float | None = None

    for _, row in df.iterrows():
        lon_text = str(row[longitude_column]).strip()
        lat_text = str(row[latitude_column]).strip()
        if not lon_text or not lat_text:
            missing_count += 1
            continue
        longitude = _coordinate_decimal(lon_text, is_longitude=True)
        latitude = _coordinate_decimal(lat_text, is_longitude=False)
        if longitude is None or latitude is None:
            invalid_format_count += 1
            continue

        row_has_range_error = False
        if longitude < -180 or longitude > 180:
            invalid_longitude_count += 1
            row_has_range_error = True
        if latitude < -90 or latitude > 90:
            invalid_latitude_count += 1
            row_has_range_error = True
        if not row_has_range_error:
            error = _position_error_meters(lon_text, lat_text)
            if error > 0:
                minimum_positive_error = (
                    error
                    if minimum_positive_error is None
                    else min(minimum_positive_error, error)
                )
                maximum_positive_error = (
                    error
                    if maximum_positive_error is None
                    else max(maximum_positive_error, error)
                )

    if missing_count:
        issues.append(
            ImportValidationIssue(
                code="missing_geometry",
                count=missing_count,
                message=f"存在 {missing_count} 行缺少经度或纬度，无法导入。",
            )
        )
    if invalid_format_count:
        issues.append(
            ImportValidationIssue(
                code="invalid_coordinate_format",
                count=invalid_format_count,
                message=f"存在 {invalid_format_count} 行经纬度格式无法识别；支持十进制度、度分秒和紧凑度分秒格式。",
            )
        )
    if invalid_longitude_count:
        issues.append(
            ImportValidationIssue(
                code="invalid_longitude",
                count=invalid_longitude_count,
                message=f"存在 {invalid_longitude_count} 行经度不在 -180 到 180 范围内，无法导入。",
            )
        )
    if invalid_latitude_count:
        issues.append(
            ImportValidationIssue(
                code="invalid_latitude",
                count=invalid_latitude_count,
                message=f"存在 {invalid_latitude_count} 行纬度不在 -90 到 90 范围内，无法导入。",
            )
        )

    if minimum_positive_error is not None and maximum_positive_error is not None:
        ratio = maximum_positive_error / minimum_positive_error
        if ratio > COORDINATE_UNCERTAINTY_RATIO_THRESHOLD:
            issues.append(
                ImportValidationIssue(
                    code="coordinate_uncertainty",
                    blocking=False,
                    min_meters=round(minimum_positive_error, 6),
                    max_meters=round(maximum_positive_error, 6),
                    ratio=round(ratio, 2),
                    message=(
                        "坐标不确定性差距超过 "
                        f"{COORDINATE_UNCERTAINTY_RATIO_THRESHOLD} 倍："
                        f"最小约 {minimum_positive_error:.6f} 米，"
                        f"最大约 {maximum_positive_error:.6f} 米。"
                    ),
                )
            )
    return issues


def position_error_meters(lon_text: str, lat_text: str) -> float:
    return _position_error_meters(lon_text, lat_text)


def normalize_coordinate_columns(
    df: pd.DataFrame, *, longitude_column: str, latitude_column: str
) -> pd.DataFrame:
    normalized = df.copy()
    normalized[longitude_column] = normalized[longitude_column].map(
        lambda value: _normalized_coordinate_text(value, is_longitude=True)
    )
    normalized[latitude_column] = normalized[latitude_column].map(
        lambda value: _normalized_coordinate_text(value, is_longitude=False)
    )
    return normalized


def validate_import_table_name(table_name: str) -> str:
    table_name = table_name.strip()
    if not TABLE_NAME_PATTERN.fullmatch(table_name):
        raise ImportDataError(
            "入库表名只能使用英文字母、数字和下划线，且必须以字母或下划线开头，最长 63 个字符"
        )
    return table_name


def duplicate_target_for_display_name(display_name: str) -> dict[str, str] | None:
    display_name = str(display_name or "").strip()
    if not display_name:
        return None
    if not DataResource.objects.filter(name=display_name).exists():
        return None
    return {
        "targetType": "data_resource_name",
        "targetName": display_name,
        "message": f"数据名称已存在：{display_name}",
    }


def _ensure_display_name_can_be_imported(
    display_name: str, duplicate_confirmed: bool
) -> None:
    duplicate_target = duplicate_target_for_display_name(display_name)
    if not duplicate_target or duplicate_confirmed:
        return
    raise ImportDataError(
        "数据名称已存在",
        [
            {
                "code": "duplicate_target",
                "message": f"数据名称已存在：{display_name}。如需继续导入，请在数据校验阶段确认重复数据名称。",
                "blocking": True,
                "targetType": "data_resource_name",
                "targetName": display_name,
            }
        ],
    )


def unique_import_table_name(table_name: str, import_mode: str) -> str:
    table_name = validate_import_table_name(table_name)
    if not _storage_target_exists(table_name, import_mode):
        return table_name
    for _ in range(100):
        suffix = uuid.uuid4().hex[:8]
        candidate = f"{table_name[: MAX_TABLE_NAME_LENGTH - 9]}_{suffix}"
        if not _storage_target_exists(candidate, import_mode):
            return candidate
    raise ImportDataError("无法生成唯一后台存储标识")


def _storage_target_exists(table_name: str, import_mode: str) -> bool:
    if DataResource.objects.filter(storage_path=table_name).exists():
        return True
    geographic = import_mode == "geographic"
    path = vector_geopackage_path() if geographic else table_data_path("data.sqlite")
    if not path.exists():
        return False
    if geographic:
        return geopackage_layer_exists(path, table_name)
    with sqlite3.connect(path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
    return bool(exists)


def suggest_table_name(source_name: str) -> str:
    stem = slugify(source_name, allow_unicode=False).replace("-", "_")
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_").lower()
    if not stem or not re.match(r"^[A-Za-z_]", stem):
        stem = "import_data"
    digest = uuid.uuid4().hex[:12]
    candidate = f"{stem}_{digest}"
    return candidate[:MAX_TABLE_NAME_LENGTH]


def write_geopackage_field_metadata(
    path: Path, table_name: str, metadata: dict[str, str]
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gpkg_data_columns (
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                name TEXT,
                title TEXT,
                description TEXT,
                mime_type TEXT,
                constraint_name TEXT,
                CONSTRAINT pk_gpkg_data_columns PRIMARY KEY (table_name, column_name)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gpkg_extensions (
                table_name TEXT,
                column_name TEXT,
                extension_name TEXT NOT NULL,
                definition TEXT NOT NULL,
                scope TEXT NOT NULL,
                CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name)
            )
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO gpkg_extensions
                (table_name, column_name, extension_name, definition, scope)
            VALUES
                (?, NULL, 'gpkg_schema', 'http://www.geopackage.org/spec/#extension_schema', 'read-write')
            """,
            (table_name,),
        )
        _replace_field_metadata(connection, "gpkg_data_columns", table_name, metadata)


def write_sqlite_field_metadata(
    connection: sqlite3.Connection, table_name: str, metadata: dict[str, str]
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS data_columns (
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            CONSTRAINT pk_data_columns PRIMARY KEY (table_name, column_name)
        )
        """
    )
    connection.execute("DELETE FROM data_columns WHERE table_name = ?", (table_name,))
    connection.executemany(
        "INSERT INTO data_columns (table_name, column_name, description) VALUES (?, ?, ?)",
        [
            (table_name, column_name, description)
            for column_name, description in metadata.items()
        ],
    )


def _read_csv_source(source) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            _rewind_table_source(source)
            return pd.read_csv(
                source,
                dtype=str,
                keep_default_na=False,
                na_filter=False,
                encoding=encoding,
            )
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ImportDataError(f"CSV 编码无法识别：{last_error}")


def _uploaded_table_source(uploaded_file, filename: str):
    try:
        configured_max_mb = runtime_upload_max_mb()
    except RuntimeConfigError as exc:
        raise ImportDataError(str(exc)) from exc
    safe_max_mb = min(configured_max_mb, MAX_TABLE_PARSE_UPLOAD_MB)
    max_size_bytes = safe_max_mb * 1024 * 1024
    upload_size = int(getattr(uploaded_file, "size", 0) or 0)
    if upload_size > max_size_bytes:
        raise ImportDataError("上传表格超过平台上传大小限制")
    if upload_size <= 0:
        raise ImportDataError("上传文件为空")

    temporary_path = getattr(uploaded_file, "temporary_file_path", None)
    source = Path(temporary_path()) if callable(temporary_path) else uploaded_file
    _rewind_table_source(source)
    if Path(filename).suffix.lower() == ".xlsx":
        _validate_xlsx_expanded_size(source)
        _rewind_table_source(source)
    return source


def _validate_xlsx_expanded_size(source) -> None:
    try:
        with zipfile.ZipFile(source) as archive:
            expanded_size = sum(item.file_size for item in archive.infolist())
    except (OSError, zipfile.BadZipFile) as exc:
        raise ImportDataError(f"读取上传表格失败：{exc}") from exc
    if expanded_size > MAX_XLSX_EXPANDED_BYTES:
        raise ImportDataError("XLSX 解压后超过 128 MB 在线解析安全限制")


def _rewind_table_source(source) -> None:
    seek = getattr(source, "seek", None)
    if callable(seek):
        seek(0)


def _table_source_is_empty(source) -> bool:
    if isinstance(source, (str, Path)):
        try:
            return Path(source).stat().st_size == 0
        except OSError:
            return True
    getbuffer = getattr(source, "getbuffer", None)
    if callable(getbuffer):
        return len(getbuffer()) == 0
    return False


def _payload_sheet_name(payload: dict[str, Any]) -> str | None:
    value = str(payload.get("sheetName") or "").strip()
    return value or None


def _selected_sheet_name(
    sheets: list[WorkbookSheetSummary], sheet_name: str | None
) -> str | None:
    if not sheets:
        return None
    if sheet_name is None:
        return sheets[0].name
    if any(sheet.name == sheet_name for sheet in sheets):
        return sheet_name
    raise ImportDataError(f"工作表不存在：{sheet_name}")


def _suggested_display_name(
    file_stem: str, sheet_name: str | None, sheets: list[WorkbookSheetSummary]
) -> str:
    if not sheet_name or len(sheets) <= 1:
        return file_stem
    return f"{file_stem} - {sheet_name}"


def _serialize_workbook_sheet(sheet: WorkbookSheetSummary) -> dict[str, Any]:
    return {
        "name": sheet.name,
        "rowCount": sheet.row_count,
        "columnCount": sheet.column_count,
        "isGeographic": sheet.is_geographic,
        "longitudeColumn": sheet.longitude_column,
        "latitudeColumn": sheet.latitude_column,
        "suggestedName": sheet.name,
    }


def _replace_field_metadata(
    connection: sqlite3.Connection,
    table_name: str,
    data_table: str,
    metadata: dict[str, str],
) -> None:
    connection.execute(f"DELETE FROM {table_name} WHERE table_name = ?", (data_table,))
    connection.executemany(
        f"INSERT INTO {table_name} (table_name, column_name, name, title, description, mime_type, constraint_name) VALUES (?, ?, NULL, NULL, ?, NULL, NULL)",
        [
            (data_table, column_name, description)
            for column_name, description in metadata.items()
        ],
    )


def _metadata_map(raw: Any, columns: set[str]) -> dict[str, str]:
    if raw in (None, ""):
        return {column: "" for column in columns}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ImportDataError("字段元数据不是有效 JSON") from exc
    if not isinstance(raw, dict):
        raise ImportDataError("字段元数据必须是对象")
    metadata = {column: str(raw.get(column) or "").strip() for column in columns}
    return metadata


def set_resource_access_groups(
    resource: DataResource, group_ids: set[int], *, viewer=None
) -> None:
    requested_groups = list(Group.objects.filter(id__in=group_ids))
    if len(requested_groups) != len(group_ids):
        raise ImportDataError("包含不存在或不可选择的角色")
    if viewer is not None:
        visible_requested_ids = set(
            selectable_access_groups_for(
                Group.objects.filter(id__in=group_ids).only("id", "name"), viewer
            ).values_list("id", flat=True)
        )
        if visible_requested_ids != group_ids:
            raise ImportDataError("包含不存在或不可选择的角色")

    normalized_group_ids = normalized_access_group_ids(group_ids)
    groups = list(Group.objects.filter(id__in=normalized_group_ids))
    if len(groups) != len(normalized_group_ids):
        raise ImportDataError("包含不存在或不可选择的角色")
    resource.access_groups.set(groups)
    for layer in resource.map_layers.all():
        layer.access_groups.set(groups)


def normalized_access_group_ids(group_ids: set[int]) -> set[int]:
    _, superadmin_group = ensure_superadmin_defaults(
        create_account=False, attach_existing_superusers=False
    )
    return set(group_ids) | {superadmin_group.id}


def _access_group_ids(raw: Any) -> set[int]:
    if raw in (None, ""):
        return set()
    if not isinstance(raw, list):
        raise ImportDataError("accessGroupIds 必须是数组")
    try:
        return {int(group_id) for group_id in raw}
    except (TypeError, ValueError) as exc:
        raise ImportDataError("accessGroupIds 必须是整数数组") from exc


def _included_columns(
    raw: Any,
    available_columns,
    *,
    required_columns: set[str] | None = None,
) -> list[str]:
    available = list(available_columns)
    required = required_columns or set()
    if raw in (None, ""):
        selected = available
    else:
        if not isinstance(raw, list):
            raise ImportDataError("上传字段列表必须是数组")
        selected = []
        seen = set()
        for item in raw:
            column = str(item or "").strip()
            if column in seen:
                continue
            if column not in available:
                raise ImportDataError(f"上传字段不存在：{column}")
            selected.append(column)
            seen.add(column)

    for column in available:
        if column in required and column not in selected:
            selected.append(column)
    if not selected:
        raise ImportDataError("至少需要选择一个上传字段")
    return selected


def _valid_coordinate_mask(
    df: pd.DataFrame, longitude_column: str, latitude_column: str
) -> pd.Series:
    lon = df[longitude_column].map(
        lambda value: _coordinate_decimal(value, is_longitude=True)
    )
    lat = df[latitude_column].map(
        lambda value: _coordinate_decimal(value, is_longitude=False)
    )
    return lon.map(lambda value: value is not None and -180 <= value <= 180) & lat.map(
        lambda value: value is not None and -90 <= value <= 90
    )


def _position_error_meters(lon_text: str, lat_text: str) -> float:
    lon_error_degrees = float(_half_unit_degree(lon_text))
    lat_error_degrees = float(_half_unit_degree(lat_text))
    latitude_decimal = _coordinate_decimal(lat_text, is_longitude=False)
    latitude = float(latitude_decimal) if latitude_decimal is not None else 0.0
    lat_meters = lat_error_degrees * 111_320
    lon_meters = lon_error_degrees * 111_320 * abs(math.cos(math.radians(latitude)))
    return math.hypot(lat_meters, lon_meters)


def _half_unit_degree(value: str) -> Decimal:
    text = value.strip()
    match = re.match(r"^[+-]?\d+(?:\.(\d+))?$", _strip_coordinate_direction(text))
    if match:
        decimals = len(match.group(1) or "")
        return Decimal("0.5") * (Decimal(10) ** Decimal(-decimals))
    compact = _compact_dms_parts(text, is_longitude=True) or _compact_dms_parts(
        text, is_longitude=False
    )
    if compact is not None:
        _, _, seconds, _ = compact
        decimals = max(-seconds.as_tuple().exponent, 0)
        return Decimal("0.5") * (Decimal(10) ** Decimal(-decimals)) / Decimal(3600)
    dms = _symbolic_dms_parts(text)
    if dms is not None:
        _, _, seconds, _ = dms
        decimals = max(-seconds.as_tuple().exponent, 0)
        return Decimal("0.5") * (Decimal(10) ** Decimal(-decimals)) / Decimal(3600)
    try:
        decimal = Decimal(text)
    except InvalidOperation:
        return Decimal("0")
    decimals = max(-decimal.as_tuple().exponent, 0)
    return Decimal("0.5") * (Decimal(10) ** Decimal(-decimals))


def _coordinate_decimal(value: Any, *, is_longitude: bool) -> Decimal | None:
    text = str(value).strip()
    if not text:
        return None
    decimal = _decimal_degree(text)
    max_degrees = 180 if is_longitude else 90
    if decimal is not None and -max_degrees <= decimal <= max_degrees:
        return decimal
    compact = _compact_dms_parts(text, is_longitude=is_longitude)
    if compact is not None:
        return _dms_to_decimal(*compact)
    symbolic = _symbolic_dms_parts(text)
    if symbolic is not None:
        return _dms_to_decimal(*symbolic)
    return decimal


def _normalized_coordinate_text(value: Any, *, is_longitude: bool) -> str:
    decimal = _coordinate_decimal(value, is_longitude=is_longitude)
    if decimal is None:
        return str(value).strip()
    return f"{float(decimal):.8f}".rstrip("0").rstrip(".")


def _decimal_degree(text: str) -> Decimal | None:
    stripped = _strip_coordinate_direction(text)
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", stripped):
        return None
    try:
        decimal = Decimal(stripped)
    except InvalidOperation:
        return None
    direction = _coordinate_direction_sign(text)
    return decimal.copy_abs() * direction if direction != 1 else decimal


def _compact_dms_parts(
    text: str, *, is_longitude: bool
) -> tuple[Decimal, Decimal, Decimal, int] | None:
    stripped = _strip_coordinate_direction(text)
    sign = -1 if stripped.startswith("-") else 1
    digits = stripped.lstrip("+-")
    if not digits.isdigit() or len(digits) < 6:
        return None
    direction = _coordinate_direction_sign(text)
    sign = sign * direction
    max_degrees = 180 if is_longitude else 90
    for degree_width in (3, 2):
        if len(digits) < degree_width + 4:
            continue
        degree_text = digits[:degree_width]
        minute_text = digits[degree_width : degree_width + 2]
        second_text = digits[degree_width + 2 : degree_width + 4]
        second_fraction = digits[degree_width + 4 :]
        seconds = Decimal(second_text)
        if second_fraction:
            seconds += Decimal(second_fraction) / (Decimal(10) ** len(second_fraction))
        degrees = Decimal(degree_text)
        minutes = Decimal(minute_text)
        if degrees > max_degrees or minutes >= 60 or seconds >= 60:
            continue
        return degrees, minutes, seconds, sign
    return None


def _symbolic_dms_parts(text: str) -> tuple[Decimal, Decimal, Decimal, int] | None:
    prepared = text.strip()
    sign = _coordinate_direction_sign(prepared)
    prepared = _strip_coordinate_direction(prepared).replace(",", " ")
    prepared = re.sub(r"[°º度dD]", " ", prepared)
    prepared = re.sub(r"[′'’分mM]", " ", prepared)
    prepared = re.sub(r"[″\"秒sS]", " ", prepared)
    parts = [part for part in re.split(r"\s+", prepared.strip()) if part]
    if len(parts) not in {2, 3}:
        return None
    try:
        degrees = Decimal(parts[0])
        minutes = Decimal(parts[1])
        seconds = Decimal(parts[2]) if len(parts) == 3 else Decimal("0")
    except InvalidOperation:
        return None
    if minutes >= 60 or seconds >= 60:
        return None
    number_sign = -1 if degrees < 0 else 1
    return abs(degrees), minutes, seconds, sign * number_sign


def _dms_to_decimal(
    degrees: Decimal, minutes: Decimal, seconds: Decimal, sign: int
) -> Decimal:
    return (degrees + minutes / Decimal(60) + seconds / Decimal(3600)) * sign


def _strip_coordinate_direction(text: str) -> str:
    stripped = re.sub(r"[东西南北][经纬]", "", text)
    return re.sub(r"(?i)[NSEW东南西北]", "", stripped).strip()


def _coordinate_direction_sign(text: str) -> int:
    if re.search(r"(?:^|[^A-Za-z])[SW](?:$|[^A-Za-z])", text) or re.search(
        r"[西南]", text
    ):
        return -1
    return 1


def _best_coordinate_column(df: pd.DataFrame, *, is_longitude: bool) -> str | None:
    normalized_aliases = (
        NORMALIZED_LONGITUDE_ALIASES if is_longitude else NORMALIZED_LATITUDE_ALIASES
    )
    candidates: list[tuple[float, str]] = []
    for column in df.columns:
        normalized = _normalize_column_name(column)
        score = 0.0
        if normalized in normalized_aliases:
            score += 8.0
        elif any(alias in normalized for alias in normalized_aliases if len(alias) > 1):
            score += 5.0
        elif normalized in {"x", "y"}:
            score += 2.0
        if score <= 0:
            continue
        values = df[column].map(
            lambda value: _coordinate_decimal(value, is_longitude=is_longitude)
        )
        min_value, max_value = (-180, 180) if is_longitude else (-90, 90)
        in_range = values.map(
            lambda value: value is not None and min_value <= value <= max_value
        )
        valid_ratio = float(in_range.sum()) / max(len(df), 1)
        if valid_ratio <= 0:
            continue
        candidates.append((score + valid_ratio, column))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-item[0], item[1]))[0][1]


def _normalize_column_name(column: str) -> str:
    return re.sub(r"[\s\-_()（）]+", "", str(column).strip().lower())


def _unique_column_names(columns) -> list[str]:
    seen: dict[str, int] = {}
    names = []
    for index, column in enumerate(columns):
        base = str(column).strip() or f"column_{index + 1}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        names.append(base if count == 0 else f"{base}_{count + 1}")
    return names


def _preview_rows(df: pd.DataFrame) -> list[dict[str, str]]:
    return df.head(MAX_PREVIEW_ROWS).to_dict(orient="records")


def _serialize_coordinate_stats(stats: CoordinateStats | None) -> dict[str, Any] | None:
    if stats is None:
        return None
    return {
        "totalRows": stats.total_rows,
        "validRows": stats.valid_rows,
        "missingRows": stats.missing_rows,
        "quantizationErrorMeters": {
            "min": stats.error_min_meters,
            "max": stats.error_max_meters,
        },
    }


def _serialize_validation_issues(
    issues: list[ImportValidationIssue],
) -> list[dict[str, Any]]:
    serialized = []
    for issue in issues:
        item: dict[str, Any] = {
            "code": issue.code,
            "message": issue.message,
            "blocking": issue.blocking,
        }
        if issue.count is not None:
            item["count"] = issue.count
        if issue.min_meters is not None:
            item["minMeters"] = issue.min_meters
        if issue.max_meters is not None:
            item["maxMeters"] = issue.max_meters
        if issue.ratio is not None:
            item["ratio"] = issue.ratio
        if issue.target_type is not None:
            item["targetType"] = issue.target_type
        if issue.target_name is not None:
            item["targetName"] = issue.target_name
        serialized.append(item)
    return serialized


def _ensure_table_can_be_written(
    path: Path, table_name: str, *, geographic: bool
) -> None:
    if not path.exists():
        return
    if geographic:
        if geopackage_layer_exists(path, table_name):
            raise ImportDataError("后台存储标识已存在，请重新预检后导入")
        return
    with sqlite3.connect(path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
    if exists:
        raise ImportDataError("后台存储标识已存在，请重新预检后导入")


def _write_geopackage_layer(path: Path, table_name: str, gdf) -> None:
    append_geopackage_layer(path, table_name, gdf)


def _upsert_geographic_resource(
    *,
    name: str,
    table_name: str,
    bounds: list[float],
    stats: CoordinateStats,
    ignore_coordinate_uncertainty: bool,
    source_size_bytes: int,
    user,
    domain_type: str,
    category: DictionaryItem | None,
) -> DataResource:
    code = _unique_resource_code(stable_catalog_code("vector", table_name))
    spatial_extent = ",".join(f"{value:.6f}" for value in bounds) if bounds else ""
    resource = DataResource.objects.create(
        code=code,
        name=name,
        data_type=DataResource.DataType.VECTOR,
        domain_type=domain_type,
        category=category,
        source="用户导入",
        provider="",
        spatial_extent=spatial_extent,
        coordinate_system="EPSG:4326",
        file_format="GPKG",
        storage_path=table_name,
        description=f"由 Excel/CSV 导入的地理表：{table_name}",
        quality_note=_quality_note(stats, ignore_coordinate_uncertainty),
        maintainer=user if getattr(user, "is_authenticated", False) else None,
        size_bytes=source_size_bytes,
        item_count=int(stats.valid_rows),
        status=DataResource.Status.ACTIVE,
    )
    return resource


def _domain_type(value: Any) -> str:
    domain_type = str(value or "").strip()
    if not domain_type:
        raise ImportDataError("请选择业务数据类型")
    if domain_type not in DataDomainType.values:
        raise ImportDataError("无效的数据业务类型")
    return domain_type


def _optional_data_category(value: Any) -> DictionaryItem | None:
    category_code = str(value or "").strip()
    if not category_code:
        return None
    try:
        return resolve_data_category(category_code)
    except TaxonomyError as exc:
        raise ImportDataError(str(exc)) from exc


def _unique_resource_code(base_code: str) -> str:
    if not DataResource.objects.filter(code=base_code).exists():
        return base_code
    for _ in range(100):
        candidate = f"{base_code[:67]}-{uuid.uuid4().hex[:12]}"
        if not DataResource.objects.filter(code=candidate).exists():
            return candidate
    raise ImportDataError("无法生成唯一数据资源编号")


def _quality_note(stats: CoordinateStats, ignore_coordinate_uncertainty: bool) -> str:
    error_range = ""
    if stats.error_min_meters is not None and stats.error_max_meters is not None:
        error_range = f"坐标量化误差范围约 {stats.error_min_meters:.6f} - {stats.error_max_meters:.6f} 米。"
    uncertainty_note = (
        "坐标不确定性差距已由用户确认忽略。" if ignore_coordinate_uncertainty else ""
    )
    missing_note = f"坐标有效 {stats.valid_rows}/{stats.total_rows} 行。"
    return f"{missing_note}{error_range}{uncertainty_note}"


def _required_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ImportDataError(f"{label}不能为空")
    return text
