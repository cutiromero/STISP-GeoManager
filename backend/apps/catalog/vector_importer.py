from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from django.contrib.auth.models import Group
from django.db import transaction

from apps.catalog.importer import (
    ImportDataError,
    duplicate_target_for_display_name,
    set_resource_access_groups,
    suggest_table_name,
    unique_import_table_name,
    validate_import_table_name,
    write_geopackage_field_metadata,
)
from apps.catalog.models import DataResource, MapLayer, VectorDataset
from apps.catalog.services import upsert_vector_catalog_record
from apps.catalog.taxonomy import TaxonomyError, resolve_data_category
from apps.catalog.vector_store import _json_value
from apps.catalog.vector_storage import (
    GEOPACKAGE_WRITE_LOCK,
    append_geopackage_layer,
)
from apps.core.runtime_config import RuntimeConfigError, runtime_upload_max_mb
from apps.core.storage import vector_geopackage_path, vector_original_path
from apps.standards.models import (
    DataDomainType,
    DataGranularity,
    ResourceDomain,
    SourceDataset,
    SpatialClass,
    StandardizationStatus,
)


SUPPORTED_VECTOR_SUFFIXES = {".zip", ".geojson", ".json", ".gpkg"}
SHAPEFILE_REQUIRED_SUFFIXES = {".shp", ".shx", ".dbf"}
SHAPEFILE_OPTIONAL_SUFFIXES = {".prj", ".cpg", ".qix"}
IGNORED_ARCHIVE_SUFFIXES = {".lock", ".sr.lock"}
ENCODING_CANDIDATES = ("UTF-8", "GB18030", "GBK", "CP936")
MAX_ARCHIVE_EXPANSION_RATIO = 8
# GeoPandas reads a complete vector layer into memory. Keep this independent
# ceiling even when disk-backed raster/result uploads use the 1 GiB platform cap.
MAX_VECTOR_UPLOAD_MB = 120


@dataclass(frozen=True)
class VectorLayerSource:
    source_format: str
    source_layer_name: str
    path: Path
    layer: str | None = None
    encoding: str | None = None


def preview_vector_import(
    uploaded_file, *, encoding: str | None = None
) -> dict[str, Any]:
    with staged_vector_upload(uploaded_file) as staged:
        layers = discover_vector_layers(staged, encoding=encoding)
        previews = [vector_layer_preview(source) for source in layers]
    return {
        "sourceFileName": Path(uploaded_file.name or "vector-data").name,
        "sourceFormat": previews[0]["sourceFormat"],
        "layers": [_public_layer_preview(item) for item in previews],
        "limitations": [
            "Shapefile 请以 ZIP 上传，并包含同名 .shp、.shx、.dbf；建议同时包含 .prj 和 .cpg。",
            "源数据会保留原始文件归档，地图用数据统一转换为 EPSG:4326 后写入 GeoPackage。",
            "当前版本支持 Shapefile ZIP、GeoJSON 和 GeoPackage；一个提交任务导入一个源图层。",
            "无效几何不会静默修改，必须在校验阶段明确选择修复或跳过。",
        ],
    }


def validate_vector_import(uploaded_file, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ImportDataError("请输入数据名称")
    source_layer_name = str(payload.get("sourceLayerName") or "").strip()
    if not source_layer_name:
        raise ImportDataError("请选择源矢量图层")
    table_name = validate_import_table_name(str(payload.get("tableName") or "").strip())
    encoding = _optional_text(payload.get("encoding"))
    source_crs = _optional_text(payload.get("sourceCrs"))
    repair_invalid = bool(payload.get("repairInvalidGeometries", False))
    skip_invalid = bool(payload.get("skipInvalidGeometries", False))

    with staged_vector_upload(uploaded_file) as staged:
        sources = discover_vector_layers(staged, encoding=encoding)
        source = _selected_source(sources, source_layer_name)
        gdf, resolved_encoding = read_vector_layer(source)
        gdf, issues = prepare_vector_frame(
            gdf,
            source_crs=source_crs,
            repair_invalid=repair_invalid,
            skip_invalid=skip_invalid,
            normalize_crs=False,
        )
        layer = vector_layer_preview(
            source,
            frame=gdf,
            resolved_encoding=resolved_encoding,
            suggested_table_name=table_name,
        )
    return {
        "layer": _public_layer_preview(layer),
        "validationIssues": issues,
        "duplicateTarget": duplicate_target_for_display_name(name),
    }


def commit_vector_import(
    uploaded_file, payload: dict[str, Any], user
) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ImportDataError("请输入数据名称")
    source_layer_name = str(payload.get("sourceLayerName") or "").strip()
    if not source_layer_name:
        raise ImportDataError("请选择源矢量图层")
    requested_table_name = validate_import_table_name(
        str(payload.get("tableName") or "").strip()
    )
    duplicate_confirmed = bool(payload.get("duplicateConfirmed", False))
    duplicate_target = duplicate_target_for_display_name(name)
    if duplicate_target and not duplicate_confirmed:
        raise ImportDataError(
            "数据名称已存在",
            [
                {
                    "code": "duplicate_target",
                    "message": f"数据名称已存在：{name}。请先确认同名数据后再提交。",
                    "blocking": True,
                    "targetType": "data_resource_name",
                    "targetName": name,
                }
            ],
        )
    domain_type = _domain_type(payload.get("domainType"))
    category = None
    category_code = str(payload.get("categoryCode") or "").strip()
    if category_code:
        try:
            category = resolve_data_category(category_code)
        except TaxonomyError as exc:
            raise ImportDataError(str(exc)) from exc
    access_group_ids = _access_group_ids(payload.get("accessGroupIds"))
    encoding = _optional_text(payload.get("encoding"))
    source_crs = _optional_text(payload.get("sourceCrs"))
    repair_invalid = bool(payload.get("repairInvalidGeometries", False))
    skip_invalid = bool(payload.get("skipInvalidGeometries", False))
    field_metadata = payload.get("fieldMetadata") or {}
    if not isinstance(field_metadata, dict):
        raise ImportDataError("fieldMetadata 必须是对象")

    table_name = unique_import_table_name(requested_table_name, "geographic")
    source_file_name = Path(uploaded_file.name or "vector-data").name
    source_size = int(getattr(uploaded_file, "size", 0) or 0)
    archive_relative = ""
    archive_path: Path | None = None
    resource: DataResource | None = None
    wrote_layer = False

    with staged_vector_upload(uploaded_file) as staged:
        sources = discover_vector_layers(staged, encoding=encoding)
        source = _selected_source(sources, source_layer_name)
        gdf, resolved_encoding = read_vector_layer(source)
        original_count = len(gdf)
        source_crs_text = gdf.crs.to_string() if gdf.crs else source_crs or ""
        source_epsg = gdf.crs.to_epsg() if gdf.crs else _epsg_from_text(source_crs)
        gdf, validation_issues = prepare_vector_frame(
            gdf,
            source_crs=source_crs,
            repair_invalid=repair_invalid,
            skip_invalid=skip_invalid,
            normalize_crs=True,
        )
        blocking = [issue for issue in validation_issues if issue.get("blocking")]
        if blocking:
            raise ImportDataError("矢量数据校验未通过", validation_issues)
        if len(gdf) == 0:
            raise ImportDataError("没有可导入的有效几何要素")

        stable_id_field = _stable_feature_id_field(gdf.columns)
        gdf.insert(0, stable_id_field, range(1, len(gdf) + 1))
        summary = frame_summary(gdf)
        gpkg_path = vector_geopackage_path()
        gpkg_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path, archive_relative, checksum = archive_uploaded_vector(
            uploaded_file
        )

        try:
            with GEOPACKAGE_WRITE_LOCK:
                append_geopackage_layer(gpkg_path, table_name, gdf)
                wrote_layer = True
                metadata = {
                    str(column): str(field_metadata.get(column) or "").strip()
                    for column in gdf.columns
                    if column != gdf.geometry.name
                }
                metadata[stable_id_field] = (
                    metadata.get(stable_id_field) or "平台稳定要素编号"
                )
                write_geopackage_field_metadata(gpkg_path, table_name, metadata)

            with transaction.atomic():
                resource = upsert_vector_catalog_record(gpkg_path, table_name)
                resource.name = name
                resource.data_type = DataResource.DataType.VECTOR
                resource.domain_type = domain_type
                if category is not None:
                    resource.category = category
                resource.source = "用户导入"
                resource.coordinate_system = "EPSG:4326"
                resource.file_format = "GPKG"
                resource.description = f"由 {source.source_format} 原始文件导入的矢量图层：{source_layer_name}"
                resource.quality_note = _quality_note(validation_issues, summary)
                resource.size_bytes = source_size
                resource.item_count = len(gdf)
                resource.maintainer = (
                    user if getattr(user, "is_authenticated", False) else None
                )
                resource.default_visualization = {
                    "layerName": name,
                    "defaultVisible": False,
                    "defaultOpacity": 85,
                    "symbolization": {},
                }
                resource.save()
                layer = resource.map_layers.order_by("id").first()
                if layer is None:
                    raise ImportDataError("矢量图层登记失败")
                layer.name = name
                layer.geometry_type = _map_geometry_type(summary["geometryType"])
                layer.bounds = summary["bounds"]
                layer.source_path = table_name
                layer.save()
                set_resource_access_groups(resource, access_group_ids, viewer=user)

                vector_dataset = VectorDataset.objects.create(
                    resource=resource,
                    source_file_name=source_file_name,
                    source_format=source.source_format,
                    source_archive_path=archive_relative,
                    source_layer_name=source_layer_name,
                    source_encoding=resolved_encoding or "",
                    source_crs=source_crs_text,
                    source_epsg=source_epsg,
                    normalized_epsg=4326,
                    geometry_type=summary["geometryType"],
                    feature_count=len(gdf),
                    vertex_count=summary["vertexCount"],
                    field_count=len(summary["fields"]),
                    valid_geometry_count=summary["quality"]["validCount"],
                    invalid_geometry_count=summary["quality"]["invalidCount"],
                    empty_geometry_count=summary["quality"]["emptyCount"],
                    null_geometry_count=summary["quality"]["nullCount"],
                    bounds=summary["bounds"],
                    checksum_sha256=checksum,
                    render_strategy=VectorDataset.RenderStrategy.GEOJSON,
                    import_summary={
                        "validationIssues": validation_issues,
                        "stableFeatureIdField": stable_id_field,
                        "skippedFeatures": original_count - len(gdf),
                    },
                )
                ResourceDomain.objects.update_or_create(
                    resource=resource,
                    defaults={
                        "domain_type": domain_type,
                        "spatial_class": SpatialClass.SPATIAL,
                        "granularity": _granularity(summary["geometryType"]),
                        "standardization_status": StandardizationStatus.STANDARDIZED,
                        "notes": "矢量文件导入后统一转换为 EPSG:4326 GeoPackage 图层。",
                    },
                )
                SourceDataset.objects.create(
                    resource=resource,
                    source_file_name=source_file_name,
                    file_hash=checksum,
                    source_type=source.source_format,
                )
        except Exception:
            if wrote_layer:
                _drop_geopackage_layer(gpkg_path, table_name)
            if archive_path is not None:
                archive_path.unlink(missing_ok=True)
            raise

    if resource is None:
        raise ImportDataError("矢量数据导入失败")
    layer = resource.map_layers.order_by("id").first()
    vector_dataset = resource.vector_dataset
    return {
        "mode": "vector",
        "resourceId": resource.id,
        "resourceName": resource.name,
        "vectorDatasetId": vector_dataset.id,
        "layerId": layer.id if layer else 0,
        "layerName": table_name,
        "sourceLayerName": source_layer_name,
        "importedFeatures": vector_dataset.feature_count,
        "skippedFeatures": original_count - vector_dataset.feature_count,
        "bounds": vector_dataset.bounds,
        "geometryType": vector_dataset.geometry_type,
        "coordinateSystem": "EPSG:4326",
        "sourceEncoding": vector_dataset.source_encoding or None,
        "validationIssues": validation_issues,
    }


@contextmanager
def staged_vector_upload(uploaded_file) -> Iterator[Path]:
    _validate_upload_size(uploaded_file)
    temp_root = Path(tempfile.mkdtemp(prefix="geomanager-vector-"))
    source_name = Path(uploaded_file.name or "vector-data").name
    if not source_name:
        source_name = "vector-data"
    staged = temp_root / source_name
    created_files: list[Path] = []
    try:
        uploaded_file.seek(0)
        with staged.open("wb") as output:
            for chunk in uploaded_file.chunks():
                output.write(chunk)
        created_files.append(staged)
        if staged.suffix.lower() == ".zip":
            created_files.extend(_extract_shapefile_archive(staged, temp_root))
        yield staged
    finally:
        for path in reversed(created_files):
            path.unlink(missing_ok=True)
        temp_root.rmdir()


def discover_vector_layers(
    staged: Path, *, encoding: str | None = None
) -> list[VectorLayerSource]:
    suffix = staged.suffix.lower()
    if suffix not in SUPPORTED_VECTOR_SUFFIXES:
        if suffix == ".shp":
            raise ImportDataError(
                "Shapefile 不能只上传 .shp，请将同名 .shp/.shx/.dbf/.prj 打包为 ZIP"
            )
        raise ImportDataError(f"不支持的矢量文件格式：{suffix or staged.name}")
    if suffix == ".zip":
        shapefiles = sorted(
            path
            for path in staged.parent.iterdir()
            if path.is_file() and path.suffix.lower() == ".shp"
        )
        if not shapefiles:
            raise ImportDataError("ZIP 中没有找到 Shapefile .shp 文件")
        return [
            VectorLayerSource(
                source_format=VectorDataset.SourceFormat.SHAPEFILE,
                source_layer_name=path.stem,
                path=path,
                encoding=encoding or _encoding_from_cpg(path),
            )
            for path in shapefiles
        ]
    if suffix == ".gpkg":
        import geopandas as gpd

        layers = gpd.list_layers(staged)
        result = [
            VectorLayerSource(
                source_format=VectorDataset.SourceFormat.GPKG,
                source_layer_name=str(row["name"]),
                path=staged,
                layer=str(row["name"]),
            )
            for _, row in layers.iterrows()
            if str(row.get("geometry_type") or "").strip()
        ]
        if not result:
            raise ImportDataError("GeoPackage 中没有可导入的矢量图层")
        return result
    return [
        VectorLayerSource(
            source_format=VectorDataset.SourceFormat.GEOJSON,
            source_layer_name=staged.stem,
            path=staged,
        )
    ]


def vector_layer_preview(
    source: VectorLayerSource,
    *,
    frame=None,
    resolved_encoding: str | None = None,
    suggested_table_name: str | None = None,
) -> dict[str, Any]:
    if frame is None:
        frame, resolved_encoding = read_vector_layer(source)
    summary = frame_summary(frame)
    return {
        **summary,
        "sourceFormat": source.source_format,
        "sourceLayerName": source.source_layer_name,
        "suggestedName": source.source_layer_name,
        "suggestedTableName": suggested_table_name
        or suggest_table_name(source.source_layer_name),
        "coordinateSystem": frame.crs.to_string() if frame.crs else None,
        "epsg": frame.crs.to_epsg() if frame.crs else None,
        "encoding": resolved_encoding,
    }


def read_vector_layer(source: VectorLayerSource):
    import geopandas as gpd

    if source.source_format != VectorDataset.SourceFormat.SHAPEFILE:
        try:
            return gpd.read_file(source.path, layer=source.layer), None
        except Exception as exc:
            raise ImportDataError(
                f"读取矢量图层失败：{source.source_layer_name}，{exc}"
            ) from exc
    candidates = [source.encoding] if source.encoding else list(ENCODING_CANDIDATES)
    last_error: Exception | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return gpd.read_file(source.path, encoding=candidate), candidate
        except UnicodeError as exc:
            last_error = exc
        except Exception as exc:
            last_error = exc
            if source.encoding:
                break
    raise ImportDataError(
        f"无法按可用中文编码读取 Shapefile 属性：{source.source_layer_name}，{last_error or '未知错误'}"
    )


def prepare_vector_frame(
    gdf,
    *,
    source_crs: str | None,
    repair_invalid: bool,
    skip_invalid: bool,
    normalize_crs: bool,
):
    issues: list[dict[str, Any]] = []
    working = gdf.copy()
    if working.crs is None:
        if source_crs:
            try:
                working = working.set_crs(source_crs)
            except Exception as exc:
                raise ImportDataError(f"人工指定的源坐标系无效：{exc}") from exc
        else:
            issues.append(
                _issue(
                    "missing_crs",
                    "源矢量图层缺少坐标系，请人工指定 EPSG 或 CRS。",
                    True,
                    len(working),
                )
            )

    null_mask = working.geometry.isna()
    empty_mask = (~null_mask) & working.geometry.is_empty
    invalid_mask = (~null_mask) & (~empty_mask) & (~working.geometry.is_valid)
    if int(null_mask.sum()):
        issues.append(
            _issue(
                "null_geometry",
                "存在 null 几何要素。",
                not skip_invalid,
                int(null_mask.sum()),
            )
        )
    if int(empty_mask.sum()):
        issues.append(
            _issue(
                "empty_geometry",
                "存在空几何要素。",
                not skip_invalid,
                int(empty_mask.sum()),
            )
        )
    if int(invalid_mask.sum()) and repair_invalid:
        working.loc[invalid_mask, working.geometry.name] = working.loc[
            invalid_mask
        ].geometry.make_valid()
        invalid_mask = (
            (~working.geometry.isna())
            & (~working.geometry.is_empty)
            & (~working.geometry.is_valid)
        )
    if int(invalid_mask.sum()):
        issues.append(
            _issue(
                "invalid_geometry",
                "存在无法直接入库的无效几何。",
                not skip_invalid,
                int(invalid_mask.sum()),
            )
        )

    if skip_invalid:
        keep = (
            (~working.geometry.isna())
            & (~working.geometry.is_empty)
            & working.geometry.is_valid
        )
        working = working.loc[keep].copy()

    geometry_type = _geometry_type(working)
    if geometry_type == "Mixed":
        issues.append(
            _issue(
                "mixed_geometry",
                "同一源图层包含点、线、面等混合基础几何类型。",
                True,
                len(working),
            )
        )
    if any(
        value == "GeometryCollection"
        for value in working.geometry.geom_type.dropna().astype(str)
    ):
        issues.append(
            _issue(
                "geometry_collection",
                "当前版本不支持 GeometryCollection。",
                True,
                len(working),
            )
        )
    if len(working) == 0:
        issues.append(
            _issue("no_valid_features", "没有可导入的有效几何要素。", True, 0)
        )

    if normalize_crs and working.crs is not None and working.crs.to_epsg() != 4326:
        try:
            working = working.to_crs(4326)
        except Exception as exc:
            raise ImportDataError(f"矢量图层转换为 EPSG:4326 失败：{exc}") from exc
    return working, issues


def frame_summary(gdf) -> dict[str, Any]:
    geometry_name = gdf.geometry.name
    fields = []
    for column in gdf.columns:
        if column == geometry_name:
            continue
        series = gdf[column]
        fields.append(
            {
                "name": str(column),
                "type": str(series.dtype),
                "nullable": bool(series.isna().any()),
                "sampleValues": [
                    _json_value(value) for value in series.dropna().head(5).tolist()
                ],
            }
        )
    preview_rows = []
    for record in gdf.drop(columns=geometry_name).head(5).to_dict("records"):
        preview_rows.append(
            {str(key): _json_value(value) for key, value in record.items()}
        )
    null_mask = gdf.geometry.isna()
    empty_mask = (~null_mask) & gdf.geometry.is_empty
    invalid_mask = (~null_mask) & (~empty_mask) & (~gdf.geometry.is_valid)
    valid_count = int((~null_mask & ~empty_mask & ~invalid_mask).sum())
    bounds = []
    valid_for_bounds = gdf.loc[~null_mask & ~empty_mask]
    if len(valid_for_bounds):
        bounds = [
            round(float(value), 8) for value in valid_for_bounds.total_bounds.tolist()
        ]
    return {
        "geometryType": _geometry_type(gdf),
        "featureCount": int(len(gdf)),
        "vertexCount": _vertex_count(gdf),
        "bounds": bounds,
        "fields": fields,
        "previewRows": preview_rows,
        "quality": {
            "validCount": valid_count,
            "invalidCount": int(invalid_mask.sum()),
            "emptyCount": int(empty_mask.sum()),
            "nullCount": int(null_mask.sum()),
            "mixedGeometry": _geometry_type(gdf) == "Mixed",
        },
    }


def archive_uploaded_vector(uploaded_file) -> tuple[Path, str, str]:
    suffix = Path(uploaded_file.name or "vector-data").suffix.lower()
    relative = f"uploaded/{uuid.uuid4().hex}{suffix}"
    target = vector_original_path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    uploaded_file.seek(0)
    with target.open("wb") as output:
        for chunk in uploaded_file.chunks():
            digest.update(chunk)
            output.write(chunk)
    return target, relative, digest.hexdigest()


def _extract_shapefile_archive(archive_path: Path, target_root: Path) -> list[Path]:
    created: list[Path] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            expanded_size = sum(item.file_size for item in members)
            if expanded_size > max(
                archive_path.stat().st_size * MAX_ARCHIVE_EXPANSION_RATIO,
                64 * 1024 * 1024,
            ):
                raise ImportDataError("ZIP 解压体积异常，已拒绝处理")
            normalized: dict[str, zipfile.ZipInfo] = {}
            for member in members:
                name = member.filename.replace("\\", "/")
                archive_name = PurePosixPath(name)
                if (
                    archive_name.is_absolute()
                    or ".." in archive_name.parts
                    or archive_name.name in {"", ".", ".."}
                ):
                    raise ImportDataError("Shapefile ZIP 包含非法文件路径")
                suffix = _compound_suffix(name)
                if suffix in IGNORED_ARCHIVE_SUFFIXES:
                    continue
                if (
                    Path(name).suffix.lower()
                    not in SHAPEFILE_REQUIRED_SUFFIXES | SHAPEFILE_OPTIONAL_SUFFIXES
                ):
                    continue
                normalized_name = archive_name.name.lower()
                if normalized_name in normalized:
                    raise ImportDataError(
                        f"Shapefile ZIP 中存在重复文件名：{archive_name.name}"
                    )
                normalized[normalized_name] = member
            shapefile_stems = {
                Path(item.filename).stem.lower()
                for item in normalized.values()
                if Path(item.filename).suffix.lower() == ".shp"
            }
            if not shapefile_stems:
                raise ImportDataError("ZIP 中没有找到 Shapefile .shp 文件")
            for stem in shapefile_stems:
                available = {
                    Path(item.filename).suffix.lower()
                    for item in normalized.values()
                    if Path(item.filename).stem.lower() == stem
                }
                missing = SHAPEFILE_REQUIRED_SUFFIXES - available
                if missing:
                    raise ImportDataError(
                        f"Shapefile {stem} 缺少必要组件：{', '.join(sorted(missing))}"
                    )
            for member in normalized.values():
                target = target_root / Path(member.filename).name
                with archive.open(member) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                created.append(target)
    except zipfile.BadZipFile as exc:
        raise ImportDataError("上传文件不是有效 ZIP") from exc
    return created


def _encoding_from_cpg(shapefile: Path) -> str | None:
    cpg = next(
        (
            path
            for path in shapefile.parent.iterdir()
            if path.is_file()
            and path.stem.lower() == shapefile.stem.lower()
            and path.suffix.lower() == ".cpg"
        ),
        None,
    )
    if cpg is None:
        return None
    value = cpg.read_text(encoding="ascii", errors="ignore").strip()
    return value or None


def _selected_source(
    sources: list[VectorLayerSource], source_layer_name: str
) -> VectorLayerSource:
    for source in sources:
        if source.source_layer_name == source_layer_name:
            return source
    raise ImportDataError(f"未找到源矢量图层：{source_layer_name}")


def _public_layer_preview(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "sourceFormat"}


def _validate_upload_size(uploaded_file) -> None:
    try:
        configured_max_mb = runtime_upload_max_mb()
    except RuntimeConfigError as exc:
        raise ImportDataError(str(exc)) from exc
    max_mb = min(configured_max_mb, MAX_VECTOR_UPLOAD_MB)
    if int(getattr(uploaded_file, "size", 0) or 0) > max_mb * 1024 * 1024:
        raise ImportDataError(f"矢量文件大小不能超过 {max_mb} MB（内存安全限制）")


def _geometry_type(gdf) -> str:
    values = [str(value) for value in gdf.geometry.geom_type.dropna().tolist()]
    if not values:
        return ""
    bases = {_base_geometry_type(value) for value in values}
    if len(bases) != 1:
        return "Mixed"
    return next(iter(bases))


def _base_geometry_type(value: str) -> str:
    if "Point" in value:
        return "Point"
    if "LineString" in value:
        return "LineString"
    if "Polygon" in value:
        return "Polygon"
    return value


def _vertex_count(gdf) -> int:
    try:
        from shapely import get_num_coordinates

        return int(get_num_coordinates(gdf.geometry.array).sum())
    except Exception:
        return 0


def _stable_feature_id_field(columns) -> str:
    existing = {str(column) for column in columns}
    candidate = "_gm_id"
    index = 2
    while candidate in existing:
        candidate = f"_gm_id_{index}"
        index += 1
    return candidate


def _map_geometry_type(value: str) -> str:
    if value == "Point":
        return MapLayer.GeometryType.POINT
    if value == "LineString":
        return MapLayer.GeometryType.LINE
    if value == "Polygon":
        return MapLayer.GeometryType.POLYGON
    return MapLayer.GeometryType.MIXED


def _granularity(value: str) -> str:
    if value == "Point":
        return DataGranularity.SITE
    if value == "Polygon":
        return DataGranularity.REGION
    return DataGranularity.OBSERVATION


def _issue(code: str, message: str, blocking: bool, count: int) -> dict[str, Any]:
    return {"code": code, "message": message, "blocking": blocking, "count": count}


def _quality_note(issues: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    quality = summary["quality"]
    return (
        f"矢量导入校验：有效 {quality['validCount']}，无效 {quality['invalidCount']}，"
        f"空几何 {quality['emptyCount']}，null 几何 {quality['nullCount']}，"
        f"顶点 {summary['vertexCount']}；确认问题 {len(issues)} 项。"
    )


def _domain_type(value: Any) -> str:
    domain_type = str(value or "").strip()
    if not domain_type:
        raise ImportDataError("请选择业务数据类型")
    if domain_type not in DataDomainType.values:
        raise ImportDataError("无效的数据业务类型")
    return domain_type


def _access_group_ids(value: Any) -> set[int]:
    if value in (None, ""):
        return set()
    if not isinstance(value, list):
        raise ImportDataError("accessGroupIds 必须是数组")
    try:
        ids = {int(item) for item in value}
    except (TypeError, ValueError) as exc:
        raise ImportDataError("accessGroupIds 必须是整数数组") from exc
    if Group.objects.filter(id__in=ids).count() != len(ids):
        raise ImportDataError("包含不存在或不可选择的角色")
    return ids


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _epsg_from_text(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value.upper().replace("EPSG:", "").strip()
    return int(normalized) if normalized.isdigit() else None


def _compound_suffix(name: str) -> str:
    lowered = name.lower()
    if lowered.endswith(".sr.lock"):
        return ".sr.lock"
    return Path(lowered).suffix


def _drop_geopackage_layer(path: Path, layer_name: str) -> None:
    if not path.exists():
        return
    with sqlite3.connect(path) as connection:
        quoted = layer_name.replace('"', '""')
        connection.execute(f'DROP TABLE IF EXISTS "{quoted}"')
        for table_name in (
            "gpkg_contents",
            "gpkg_geometry_columns",
            "gpkg_data_columns",
            "gpkg_extensions",
        ):
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
            if exists:
                connection.execute(
                    f"DELETE FROM {table_name} WHERE table_name = ?", (layer_name,)
                )
