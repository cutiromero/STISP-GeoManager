"""Input snapshots and output adapters reuse the existing catalog services."""

import csv
import json
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import PurePosixPath

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import DataResource
from apps.catalog.permissions import user_can_access
from apps.core.storage import (
    app_path,
    raster_source_path,
    table_data_path,
    vector_geopackage_path,
    validate_vector_layer_name,
)
from apps.raster.models import RasterDataset
from .config import config
from .models import ComputeImport
from .packages import ComputeError, checksum


def _candidate_record(resource: DataResource) -> dict:
    return {
        "id": resource.id,
        "name": resource.name,
        "kind": resource.data_type,
        "fileFormat": resource.file_format,
        "projectTagId": resource.project_tag_id,
        "fields": [],
        "bands": 0,
        "crs": resource.coordinate_system,
        "geometryTypes": [],
        "sizeBytes": resource.size_bytes,
    }


def list_candidate(resource: DataResource) -> dict:
    """Read selector metadata without loading rows, pixels or feature geometries.

    This is advisory catalog information. Submission still calls candidate(),
    and execution fixes and validates the actual input file independently.
    """
    result = _candidate_record(resource)
    try:
        if resource.data_type == "raster":
            datasets = getattr(resource, "_compute_ready_rasters", None)
            dataset = datasets[0] if datasets else None
            if datasets is None:
                dataset = RasterDataset.objects.filter(
                    data_resource=resource, status="ready"
                ).first()
            if not dataset:
                raise ComputeError("栅格尚未处理完成")
            source = raster_source_path(dataset.source_relative_path)
            if not source.is_file():
                raise ComputeError("输入栅格源文件不存在，请重新导入数据")
            # The display COG may have another CRS or additional alpha bands.
            # Use the saved original-file metadata, never its display metadata.
            metadata = dataset.source_gdalinfo or {}
            bands = metadata.get("bands")
            if not isinstance(bands, list) or not bands:
                return candidate(resource)
            coordinate = metadata.get("coordinateSystem") or {}
            wkt = coordinate.get("wkt") if isinstance(coordinate, dict) else None
            crs = ""
            if wkt:
                from rasterio.crs import CRS

                crs = str(CRS.from_wkt(wkt))
            elif (metadata.get("stac") or {}).get("proj:epsg"):
                crs = "EPSG:" + str(metadata["stac"]["proj:epsg"])
            result.update(bands=len(bands), crs=crs)
        elif resource.data_type == "vector":
            result.update(_vector_candidate_schema(resource))
        elif resource.data_type == "table":
            result["fields"] = _table_candidate_fields(resource)
        elif resource.data_type in {"gene", "document", "image"}:
            from apps.catalog.nongeo import _resource_file_path

            result["sizeBytes"] = (
                _resource_file_path(resource, analysis_limit=False).stat().st_size
            )
        else:
            raise ComputeError("该资源暂不支持计算")
    except ComputeError:
        raise
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise ComputeError(
            f"无法读取计算数据“{resource.name}”的字段或元数据，请检查源文件"
        ) from exc
    return result


def _vector_candidate_schema(resource: DataResource) -> dict:
    from rasterio.crs import CRS

    path = vector_geopackage_path()
    layer = validate_vector_layer_name(resource.storage_path)
    quoted = '"' + layer.replace('"', '""') + '"'
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as connection:
        info = connection.execute(
            "SELECT g.column_name, g.geometry_type_name, g.z, "
            "s.organization, s.organization_coordsys_id, s.definition "
            "FROM gpkg_geometry_columns g LEFT JOIN gpkg_spatial_ref_sys s "
            "ON s.srs_id = g.srs_id WHERE g.table_name = ?",
            (layer,),
        ).fetchone()
        if not info:
            raise ComputeError("矢量图层不存在，请重新导入数据")
        columns = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
    geometry_column, geometry_name, z, organization, authority_id, definition = info
    geometry_types = {
        "POINT": "Point",
        "LINESTRING": "LineString",
        "POLYGON": "Polygon",
        "MULTIPOINT": "MultiPoint",
        "MULTILINESTRING": "MultiLineString",
        "MULTIPOLYGON": "MultiPolygon",
        "GEOMETRYCOLLECTION": "GeometryCollection",
        "GEOMETRY": "Unknown",
    }
    geometry_type = geometry_types.get(str(geometry_name).upper())
    if geometry_type is None:
        # Preserve GDAL's exact names for uncommon curved geometry schemas.
        actual = candidate(resource)
        return {key: actual[key] for key in ("fields", "crs", "geometryTypes")}
    if z == 1:
        geometry_type += " Z"
    if organization and authority_id and int(authority_id) > 0:
        crs = str(CRS.from_user_input(f"{organization}:{authority_id}"))
    elif definition and definition != "undefined":
        crs = str(CRS.from_wkt(definition))
    else:
        crs = ""
    return {
        "fields": [
            str(row[1]) for row in columns if row[1] != geometry_column and not row[5]
        ],
        "crs": crs,
        "geometryTypes": [geometry_type],
    }


def _table_candidate_fields(resource: DataResource) -> list[str]:
    from apps.catalog.nongeo import (
        NonGeoAnalysisError,
        SUPPORTED_TABLE_SUFFIXES,
        _resource_file_path,
    )

    if resource.file_format.upper() == "SQLITE":
        path = table_data_path("data.sqlite")
        quoted = '"' + resource.storage_path.replace('"', '""') + '"'
        with closing(
            sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        ) as connection:
            columns = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
        if not columns:
            raise ComputeError("数据资源对应的后台表格不存在或没有字段")
        return [str(row[1]) for row in columns]
    try:
        path = _resource_file_path(resource)
    except NonGeoAnalysisError as exc:
        raise ComputeError(str(exc)) from exc
    if path.suffix.lower() not in SUPPORTED_TABLE_SUFFIXES:
        raise ComputeError("该表格文件格式暂不支持在线分析")
    import pandas as pd

    if path.suffix.lower() in {".csv", ".tsv"}:
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                frame = pd.read_csv(
                    path,
                    sep="\t" if path.suffix.lower() == ".tsv" else ",",
                    encoding=encoding,
                    nrows=0,
                )
                return [str(column) for column in frame.columns]
            except UnicodeDecodeError:
                continue
        raise ComputeError("表格文件编码无法识别")
    frame = pd.read_excel(path, nrows=0)
    return [str(column) for column in frame.columns]


def candidate(resource, *, raster_metadata=False, semantic_metadata=False):
    from .input_metadata import candidate_metadata

    options = {"raster": raster_metadata, "semantic": semantic_metadata}
    return candidate_metadata(
        resource,
        options,
        lambda: _read_candidate(
            resource,
            raster_metadata=raster_metadata,
            semantic_metadata=semantic_metadata,
        ),
    )


def _read_candidate(resource, *, raster_metadata=False, semantic_metadata=False):
    result = _candidate_record(resource)
    if resource.data_type == "raster":
        import rasterio

        dataset = RasterDataset.objects.filter(
            data_resource=resource, status="ready"
        ).first()
        if not dataset:
            raise ComputeError("栅格尚未处理完成")
        with rasterio.open(raster_source_path(dataset.source_relative_path)) as src:
            result.update(bands=src.count, crs=str(src.crs or ""))
            if semantic_metadata:
                result.update(
                    bounds=list(src.bounds),
                    fieldTypes={
                        str(index): _semantic_type(dtype)
                        for index, dtype in enumerate(src.dtypes, 1)
                    },
                    fieldUnits={
                        str(index): unit
                        for index, unit in enumerate(src.units, 1)
                        if unit
                    },
                )
            if raster_metadata:
                result["rasterMetadata"] = {
                    "source": "actual_compute_input_file",
                    "size": [src.width, src.height],
                    "driver": src.driver,
                    "geoTransform": list(src.transform.to_gdal()),
                    "linearUnitMeters": src.crs.linear_units_factor[1]
                    if src.crs and src.crs.is_projected
                    else None,
                    "coordinateSystem": str(src.crs or ""),
                    "bounds": list(src.bounds),
                    "bands": [
                        {
                            "band": index,
                            "type": src.dtypes[index - 1],
                            "scale": src.scales[index - 1],
                            "offset": src.offsets[index - 1],
                            "description": src.descriptions[index - 1] or "",
                            "unit": src.units[index - 1] or "",
                        }
                        for index in src.indexes
                    ],
                    "calibrationNote": "数据类型及scale/offset是文件属性，不能仅据此确定是否完成辐射定标；未有产品或处理记录时定标状态保持未知。",
                }
    elif resource.data_type == "vector":
        import pyogrio

        info = pyogrio.read_info(
            vector_geopackage_path(),
            layer=validate_vector_layer_name(resource.storage_path),
        )
        result.update(
            fields=list(info["fields"]),
            crs=info.get("crs") or "",
            geometryTypes=[info["geometry_type"]],
        )
        if semantic_metadata:
            result.update(
                fieldTypes={
                    str(name): _semantic_type(str(dtype))
                    for name, dtype in zip(info["fields"], info["dtypes"])
                },
                bounds=list(info["total_bounds"])
                if info["total_bounds"] is not None
                else [],
            )
    elif resource.data_type == "table":
        from apps.catalog.nongeo import _resource_dataframe

        frame, _, _ = _resource_dataframe(resource, limit=1, offset=0)
        result["fields"] = [str(c) for c in frame.columns]
        if semantic_metadata:
            result["fieldTypes"] = {
                str(name): _semantic_type(str(dtype))
                for name, dtype in frame.dtypes.items()
            }
    elif resource.data_type in {"gene", "document", "image"}:
        from apps.catalog.nongeo import _resource_file_path

        result["sizeBytes"] = (
            _resource_file_path(resource, analysis_limit=False).stat().st_size
        )
    else:
        raise ComputeError("该资源暂不支持计算")
    return result


def _semantic_type(dtype):
    dtype = dtype.lower()
    if "datetime" in dtype or dtype in {"date", "timestamp"}:
        return "datetime"
    if "bool" in dtype:
        return "boolean"
    if "int" in dtype:
        return "integer"
    if "float" in dtype or "double" in dtype or "decimal" in dtype:
        return "number"
    return "string"


def freeze_input(record, directory):
    resource = DataResource.objects.filter(
        pk=record.resource_id, status="active"
    ).first()
    if not resource or resource.project_tag_id != record.task.project_tag_id:
        raise ComputeError("输入数据已停用、删除或项目权限已变更")
    actor = get_user_model().objects.get(pk=record.task.owner_id)
    if not actor.is_active or not user_can_access(resource, actor):
        raise ComputeError("输入数据已停用、删除或项目权限已变更")
    if resource.updated_at.isoformat() != record.snapshot["updatedAt"]:
        raise ComputeError("输入数据在提交后已修改，请重新选择数据提交")
    kind = resource.data_type
    extension = {"raster": ".tif", "vector": ".gpkg", "table": ".csv"}.get(kind)
    if extension is None:
        raw = PurePosixPath(resource.storage_path.replace("\\", "/")).suffix
        extension = raw if re.fullmatch(r"\.[a-zA-Z0-9]{1,10}", raw) else ".bin"
    target = directory / (record.key + extension)
    limit = config().input_mb * 1024**2
    if kind in {"vector", "table"}:
        limit = min(limit, 120 * 1024**2)
    if resource.size_bytes > limit:
        raise ComputeError("输入文件超过平台大小限制")
    if kind in {"vector", "table"} and resource.size_bytes > 120 * 1024**2:
        raise ComputeError("矢量和表格计算首期最多支持120 MiB，请先裁剪或分组")
    from .input_versions import stage_version

    max_band_pixels = 100_000_000
    if record.task.version.manifest.get("runtime") == "python-geospatial-gpu-v1":
        from .gpu_runtime import configured

        max_band_pixels = configured(
            record.task.version.manifest, record.task.project_tag_id
        ).max_band_pixels

    prepared = stage_version(
        resource,
        record.key,
        target,
        lambda path: (
            _materialize_input(resource, path, limit)
            if max_band_pixels == 100_000_000
            else _materialize_input(
                resource, path, limit, max_band_pixels=max_band_pixels
            )
        ),
        record.checksum,
    )
    current = DataResource.objects.filter(
        pk=resource.id, status="active", updated_at=resource.updated_at
    ).first()
    actor = get_user_model().objects.get(pk=record.task.owner_id)
    if (
        current is None
        or not actor.is_active
        or not user_can_access(current, actor)
        or (current.data_type, current.file_format, current.storage_path)
        != (resource.data_type, resource.file_format, resource.storage_path)
    ):
        target.unlink(missing_ok=True)
        raise ComputeError("输入数据或访问权限在准备期间变化，请重新提交")
    if target.stat().st_size > limit:
        target.unlink(missing_ok=True)
        raise ComputeError("输入快照超过大小限制")
    if kind == "raster":
        import rasterio

        with rasterio.open(target) as source:
            if source.width * source.height * source.count > max_band_pixels:
                target.unlink(missing_ok=True)
                raise ComputeError("输入栅格超过当前算子的波段像元预算")
    digest = prepared["sha256"]
    if record.checksum and record.checksum != digest:
        raise ComputeError("输入内容已变化，不能在原任务中自动重做")
    record.checksum = digest
    record.snapshot = {
        **record.snapshot,
        "fixedAtExecution": True,
        "sizeBytes": target.stat().st_size,
    }
    record.save(update_fields=["checksum", "snapshot"])
    return {
        "path": "/inputs/" + target.name,
        "kind": kind,
        "resourceId": resource.id,
        "sha256": digest,
        "verifiedEvidence": prepared["verifiedEvidence"],
        "preparation": prepared["preparation"],
    }


def _materialize_input(resource, target, limit, *, max_band_pixels=100_000_000):
    kind = resource.data_type
    if kind == "raster":
        dataset = RasterDataset.objects.get(data_resource=resource, status="ready")
        source = raster_source_path(dataset.source_relative_path)
        if source.stat().st_size > limit:
            raise ComputeError("输入栅格超过大小限制")
        # A standalone GeoTIFF snapshot copies every original band/scale/CRS.
        # Multi-file/VRT sources must be materialized; never mount a dataset tree.
        import rasterio
        from rasterio.shutil import copy as copy_raster

        with rasterio.open(source) as src:
            if src.width * src.height * src.count > max_band_pixels:
                raise ComputeError("输入栅格超过1亿波段像元限制")
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True, GDAL_PAM_ENABLED="NO"):
            copy_raster(source, target, driver="GTiff")
    elif kind == "vector":
        import geopandas as gpd
        import pyogrio

        source = vector_geopackage_path()
        info = pyogrio.read_info(
            source, layer=validate_vector_layer_name(resource.storage_path)
        )
        if info["features"] > 500_000:
            raise ComputeError("矢量计算首期最多支持50万个要素")
        frame = gpd.read_file(source, layer=resource.storage_path)
        frame.to_file(target, layer="data", driver="GPKG")
        # The driver stamps each export with its creation time. Normalize only
        # this new snapshot so unchanged data keeps the same real file SHA256.
        with closing(sqlite3.connect(target)) as connection:
            connection.execute(
                "UPDATE gpkg_contents SET last_change = ?",
                ("1970-01-01T00:00:00.000Z",),
            )
            connection.commit()
    elif kind in {"gene", "document", "image"}:
        from apps.catalog.nongeo import _resource_file_path

        source = _resource_file_path(resource, analysis_limit=False)
        if source.stat().st_size > limit:
            raise ComputeError("输入原始文件超过大小限制")
        shutil.copyfile(source, target)
    else:
        if resource.file_format.upper() == "SQLITE":
            table = '"' + resource.storage_path.replace('"', '""') + '"'
            with (
                closing(
                    sqlite3.connect(
                        f"{table_data_path('data.sqlite').as_uri()}?mode=ro", uri=True
                    )
                ) as connection,
                target.open("w", encoding="utf-8", newline="") as out,
            ):
                cursor = connection.execute(f"SELECT * FROM {table}")
                writer = csv.writer(out)
                writer.writerow([c[0] for c in cursor.description])
                while rows := cursor.fetchmany(2000):
                    writer.writerows(rows)
                    out.flush()
                    if out.tell() > limit:
                        raise ComputeError("表格数据超过大小限制")
        else:
            from apps.catalog.nongeo import _resource_dataframe

            frame, total, _ = _resource_dataframe(resource, limit=1_000_001, offset=0)
            if total > 1_000_000:
                raise ComputeError("文件表格首期最多支持100万行")
            frame.to_csv(target, index=False, encoding="utf-8")
    if target.stat().st_size > limit:
        raise ComputeError("输入快照超过大小限制")


def inspect_output(path, kind, *, contract=None):
    metadata = _inspect_output(path, kind, contract=contract)
    if contract:
        from .script_contracts import validate_metadata

        validate_metadata(metadata, kind, contract)
    return metadata


def _inspect_output(path, kind, *, contract=None):
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise ComputeError("算法没有生成有效的输出文件")
    if path.stat().st_size > config().output_mb * 1024**2:
        raise ComputeError("结果文件超过平台大小限制")
    if kind in {"vector", "table"} and path.stat().st_size > 120 * 1024**2:
        raise ComputeError("矢量和表格输出不可超过120 MiB")
    if kind == "archive":
        from .archives import inspect_archive

        return inspect_archive(path, config().output_mb * 1024**2)
    if kind == "raster":
        import rasterio

        with rasterio.open(path) as src:
            if (
                src.driver != "GTiff"
                or not src.crs
                or src.width * src.height * src.count > 100_000_000
            ):
                raise ComputeError(
                    "栅格输出须为有坐标参考系且不超过1亿波段像元的GeoTIFF"
                )
            if not src.count or not src.width or not src.height:
                raise ComputeError("栅格输出为空")
            from .raster_outputs import categorical_metadata

            categorical = categorical_metadata(src)
            for _, window in src.block_windows(1):
                if (contract or {}).get("semanticType") == "class_mask_stack_v1":
                    import numpy as np

                    values = src.read(window=window, masked=True)
                    if not np.isin(values.compressed(), [0, 1]).all():
                        raise ComputeError(
                            "实际类别掩膜含非0/1有效像元，不能作为分类输入"
                        )
                else:
                    values = src.read(window=window)  # Verify each actual block once.
                    if categorical:
                        import numpy as np

                        if not np.isin(
                            values, [row["code"] for row in categorical["legend"]]
                        ).all():
                            raise ComputeError("分类成果含图例未声明的像元值")
            return {
                "crs": str(src.crs),
                "width": src.width,
                "height": src.height,
                "bands": src.count,
                "bandNames": list(src.descriptions),
                "inputSemantics": src.tags().get("stisp_input_semantics", ""),
                "emptyCollection": src.tags().get("stisp_empty_collection") == "1",
                "dtypes": list(src.dtypes),
                "nodata": str(src.nodata),
                "bounds": list(src.bounds),
                **(categorical or {}),
            }
    if kind == "vector":
        import geopandas as gpd
        import pyogrio

        with closing(
            sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        ) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ComputeError("GeoPackage完整性检查失败")
        layers = pyogrio.list_layers(path)
        if len(layers) != 1:
            raise ComputeError("每项矢量输出须只包含一个图层")
        info = pyogrio.read_info(path, layer=layers[0][0])
        if not info.get("crs") or not 0 < info["features"] <= 500_000:
            raise ComputeError("矢量结果须包含坐标参考系和1至50万个要素")
        frame = gpd.read_file(path, layer=layers[0][0])
        if (
            not frame.is_valid.all()
            or frame.geometry.is_empty.any()
            or frame.geometry.isna().any()
        ):
            raise ComputeError("矢量输出包含无效或空几何")
        return {
            "crs": info["crs"],
            "rows": int(info["features"]),
            "layer": str(layers[0][0]),
            "fields": list(info["fields"]),
            "geometryType": info["geometry_type"],
        }
    if kind == "table":
        count = 0
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            header = next(reader, None)
            if (
                not header
                or len(header) > 500
                or len(header) != len(set(header))
                or any(not c or "\x00" in c for c in header)
            ):
                raise ComputeError("CSV须包含不重复、非空的字段名（最多500字段）")
            for row in reader:
                if len(row) != len(header) or any("\x00" in c for c in row):
                    raise ComputeError("CSV行列不一致或含无效字符")
                count += 1
                if count > 1_000_000:
                    raise ComputeError("CSV结果超过100万行")
        return {"fields": header, "rows": count}
    if kind == "image":
        from PIL import Image

        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            if img.format not in {"PNG", "JPEG"}:
                raise ComputeError("图像类型不受支持")
            return {"width": img.width, "height": img.height}
    if kind == "report":
        with path.open("rb") as stream:
            head = stream.read(5)
            stream.seek(max(0, path.stat().st_size - 2048))
            if head != b"%PDF-" or b"%%EOF" not in stream.read():
                raise ComputeError("PDF输出格式不正确")
        return {"format": "PDF"}
    if kind in {"document", "gene"}:
        records, has_header = 0, False
        with path.open(encoding="utf-8-sig") as stream:
            for line in stream:
                if "\x00" in line:
                    raise ComputeError("文本输出含无效字符")
                if kind == "gene":
                    value = line.strip()
                    if value.startswith(">"):
                        if not value[1:].strip():
                            raise ComputeError("FASTA记录需要真实名称")
                        records += 1
                        has_header = True
                    elif value and (
                        not has_header
                        or any(
                            not (char.isascii() and (char.isalpha() or char in "*-?. "))
                            for char in value
                        )
                    ):
                        raise ComputeError("基因输出须为有效FASTA序列")
        if kind == "gene" and not records:
            raise ComputeError("FASTA输出没有实际记录")
        if path.suffix == ".json":
            if path.stat().st_size > 32 * 1024**2:
                raise ComputeError("结构化文档不得超过32MiB")
            json.loads(path.read_text(encoding="utf-8-sig"))
        return {
            "format": "FASTA" if kind == "gene" else path.suffix[1:].upper(),
            "records": records,
            **(
                {
                    "fields": [
                        "sequenceId",
                        "description",
                        "length",
                        "gcContent",
                        "sequencePreview",
                    ]
                }
                if kind == "gene"
                else {}
            ),
        }
    raise ComputeError("未知输出类型")


def preview(output, view="table"):
    path = app_path(output.path)
    result = {
        "kind": output.kind,
        "metadata": output.metadata,
        "columns": [],
        "rows": [],
    }
    if view == "map":
        if output.kind != "vector":
            raise ComputeError("地图预览仅支持矢量输出")
        if not path.is_file() or path.is_symlink() or checksum(path) != output.checksum:
            raise ComputeError("结果文件内容已变化，无法读取地图", 409)
        import geopandas as gpd

        frame = gpd.read_file(path, layer=output.metadata["layer"], rows=30001)
        if len(frame) > 30000:
            raise ComputeError("图件超过30000要素，请缩小范围后查看", 409)
        if frame.crs is None:
            raise ComputeError("矢量输出缺少坐标系", 409)
        result["geojson"] = json.loads(frame.to_crs(4326).to_json())
        return result
    if output.kind == "table":
        from .result_reads import table_page

        if checksum(path) != output.checksum:
            raise ComputeError("结果文件内容已变化，无法预览", 409)
        with table_page(path, expected_checksum=output.checksum) as page:
            result["columns"] = page["columns"]
            result["rows"] = [
                [row[field][:2000] for field in page["columns"]] for row in page["rows"]
            ]
    elif output.kind == "vector":
        import geopandas as gpd

        frame = gpd.read_file(path, layer=output.metadata["layer"], rows=100).drop(
            columns="geometry"
        )
        result["columns"] = list(frame.columns)
        result["rows"] = json.loads(frame.to_json(orient="values"))
    return result


def import_output(record):
    from .access import require_actor

    output = record.output
    if output.kind == "archive":
        raise ComputeError("多文件结果请下载解压后，按数据格式分别导入")
    require_actor(
        record.requested_by, output.task.project_tag_id, "catalog.add_dataresource"
    )
    path = app_path(output.path)
    if output.expired or not path.is_file() or checksum(path) != output.checksum:
        raise ComputeError("结果已过期或文件校验失败，无法入库")
    # Stable marker recovers a successful import after worker termination.
    marker = f"compute-output:{record.storage_key}"
    existing = DataResource.objects.filter(source=marker).first()
    if existing:
        existing.is_compute_result = True
        existing.save(update_fields=["is_compute_result"])
        return existing
    if output.kind == "raster":
        from apps.raster.services.importer import import_raster_file
        from .raster_outputs import rendering_rules
        from apps.core.storage import research_path

        stable = research_path("raster", "original", "compute", f"{output.id}.tif")
        stable.parent.mkdir(parents=True, exist_ok=True)
        if not stable.exists():
            shutil.copyfile(path, stable)
        dataset = import_raster_file(
            stable,
            name=record.name,
            raster_kind=output.metadata.get("rasterKind", "continuous"),
            uploader_id=record.requested_by_id,
            source_checksum_sha256=output.checksum,
            **(
                {
                    "requested_default_rules": rendering_rules(output.metadata),
                    "resampling": "nearest",
                }
                if output.metadata.get("rasterKind") == "categorical"
                else {}
            ),
        )
        resource = dataset.data_resource
    elif output.kind in {"vector", "table"}:
        table_name = f"compute_{record.storage_key.hex}"
        # Existing import services are restart-safe at their database commit boundary.
        existing = DataResource.objects.filter(storage_path=table_name).first()
        if existing:
            resource = existing
        else:
            with path.open("rb") as stream:
                upload = UploadedFile(
                    stream, name=output.file_name, size=output.size_bytes
                )
                payload = {
                    "name": record.name,
                    "tableName": table_name,
                    "domainType": "other",
                    "accessGroupIds": [],
                }
                if output.kind == "vector":
                    from apps.catalog.vector_importer import commit_vector_import

                    result = commit_vector_import(
                        upload,
                        {**payload, "sourceLayerName": output.metadata["layer"]},
                        record.requested_by,
                    )
                else:
                    from apps.catalog.importer import import_uploaded_table

                    result = import_uploaded_table(
                        upload, {**payload, "importMode": "table"}, record.requested_by
                    )
                resource = DataResource.objects.get(pk=result["resourceId"])
    else:
        # Images and reports remain ordinary data resources; publishing is separate.
        from apps.core.storage import table_data_path

        relative = f"compute/{output.id}/{output.file_name}"
        target = table_data_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        resource = DataResource.objects.create(
            name=record.name,
            code=f"compute-{output.id}",
            data_type=output.kind if output.kind in {"image", "gene"} else "document",
            file_format=path.suffix[1:].upper(),
            storage_path="table/" + relative,
            size_bytes=output.size_bytes,
            maintainer=record.requested_by,
            source=marker,
            is_compute_result=True,
        )
    resource.is_compute_result = True
    with transaction.atomic():
        from django.contrib.auth import get_user_model

        # Reserve SQLite's writer before reading current permissions. Otherwise
        # a concurrent heartbeat can invalidate this read snapshot before save.
        ComputeImport.objects.filter(pk=record.pk).update(heartbeat=timezone.now())
        actor = get_user_model().objects.get(pk=record.requested_by_id)
        try:
            require_actor(actor, output.task.project_tag_id, "catalog.add_dataresource")
            from apps.agent.compute_tools import validate_import_intent

            validate_import_intent(record)
        except ComputeError:
            resource.status = "inactive"
            resource.save(update_fields=["status", "is_compute_result"])
            # Keep the imported resource hidden and preserve its provenance for review.
            record.resource = resource
            record.status = "failed"
            record.error = "入库期间权限发生变化，资源已停用，请管理员审核"
            record.save(update_fields=["resource", "status", "error"])
            return resource
        resource.source = marker
        resource.status = "active"
        resource.description = f"计算结果；任务 {output.task_id}；算法 {output.task.version.algorithm.name} {output.task.version.version}；SHA256 {output.checksum}"
        resource.save(
            update_fields=["source", "description", "status", "is_compute_result"]
        )
        record.resource = resource
        record.status = "ready"
        record.error = ""
        record.save(update_fields=["resource", "status", "error"])
    return resource
