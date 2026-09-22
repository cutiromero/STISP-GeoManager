"""Input snapshots and output adapters reuse the existing catalog services."""

import csv
import json
import shutil
import sqlite3
from contextlib import closing

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

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
from .packages import ComputeError, checksum


def candidate(resource):
    result = {
        "id": resource.id,
        "name": resource.name,
        "kind": resource.data_type,
        "projectTagId": resource.project_tag_id,
        "fields": [],
        "bands": 0,
        "crs": resource.coordinate_system,
        "geometryTypes": [],
        "sizeBytes": resource.size_bytes,
    }
    if resource.data_type == "raster":
        import rasterio

        dataset = RasterDataset.objects.filter(
            data_resource=resource, status="ready"
        ).first()
        if not dataset:
            raise ComputeError("栅格尚未处理完成")
        with rasterio.open(raster_source_path(dataset.source_relative_path)) as src:
            result.update(bands=src.count, crs=str(src.crs or ""))
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
    elif resource.data_type == "table":
        from apps.catalog.nongeo import _resource_dataframe

        frame, _, _ = _resource_dataframe(resource, limit=1, offset=0)
        result["fields"] = [str(c) for c in frame.columns]
    else:
        raise ComputeError("该资源暂不支持计算")
    return result


def freeze_input(record, directory):
    resource = DataResource.objects.filter(
        pk=record.resource_id, status="active"
    ).first()
    if not resource or resource.project_tag_id != record.task.project_tag_id:
        raise ComputeError("输入数据已停用、删除或项目权限已变更")
    if not user_can_access(resource, record.task.owner):
        raise ComputeError("输入数据已停用、删除或项目权限已变更")
    if resource.updated_at.isoformat() != record.snapshot["updatedAt"]:
        raise ComputeError("输入数据在提交后已修改，请重新选择数据提交")
    kind = resource.data_type
    target = directory / (
        record.key + {"raster": ".tif", "vector": ".gpkg", "table": ".csv"}[kind]
    )
    limit = config().input_mb * 1024**2
    if kind in {"vector", "table"}:
        limit = min(limit, 120 * 1024**2)
    if resource.size_bytes > limit:
        raise ComputeError("输入文件超过平台大小限制")
    if kind in {"vector", "table"} and resource.size_bytes > 120 * 1024**2:
        raise ComputeError("矢量和表格计算首期最多支持120 MiB，请先裁剪或分组")
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
            if src.width * src.height * src.count > 100_000_000:
                raise ComputeError("输入栅格超过1亿波段像元限制")
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
    digest = checksum(target)
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
    }


def inspect_output(path, kind):
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise ComputeError("算法没有生成有效的输出文件")
    if path.stat().st_size > config().output_mb * 1024**2:
        raise ComputeError("结果文件超过平台大小限制")
    if kind in {"vector", "table"} and path.stat().st_size > 120 * 1024**2:
        raise ComputeError("矢量和表格输出不可超过120 MiB")
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
            for _, window in src.block_windows(1):
                src.read(
                    window=window
                )  # Detect truncated data, not just a valid header.
            return {
                "crs": str(src.crs),
                "width": src.width,
                "height": src.height,
                "bands": src.count,
                "dtypes": list(src.dtypes),
                "nodata": str(src.nodata),
                "bounds": list(src.bounds),
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
    raise ComputeError("未知输出类型")


def preview(output):
    path = app_path(output.path)
    result = {
        "kind": output.kind,
        "metadata": output.metadata,
        "columns": [],
        "rows": [],
    }
    if output.kind == "table":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            result["columns"] = next(reader)
            import itertools

            result["rows"] = [
                [cell[:2000] for cell in row] for row in itertools.islice(reader, 100)
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
        return existing
    if output.kind == "raster":
        from apps.raster.services.importer import import_raster_file
        from apps.core.storage import research_path

        stable = research_path("raster", "original", "compute", f"{output.id}.tif")
        stable.parent.mkdir(parents=True, exist_ok=True)
        if not stable.exists():
            shutil.copyfile(path, stable)
        dataset = import_raster_file(
            stable,
            name=record.name,
            raster_kind="continuous",
            uploader_id=record.requested_by_id,
            source_checksum_sha256=output.checksum,
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
            data_type="image" if output.kind == "image" else "document",
            file_format=path.suffix[1:].upper(),
            storage_path=relative,
            size_bytes=output.size_bytes,
            maintainer=record.requested_by,
            source=marker,
        )
    with transaction.atomic():
        from django.contrib.auth import get_user_model

        actor = get_user_model().objects.get(pk=record.requested_by_id)
        try:
            require_actor(actor, output.task.project_tag_id, "catalog.add_dataresource")
        except ComputeError:
            resource.status = "inactive"
            resource.save(update_fields=["status"])
            # Keep the imported resource hidden and preserve its provenance for review.
            record.resource = resource
            record.status = "failed"
            record.error = "入库期间权限发生变化，资源已停用，请管理员审核"
            record.save(update_fields=["resource", "status", "error"])
            return resource
        resource.source = marker
        resource.status = "active"
        resource.description = f"计算结果；任务 {output.task_id}；算法 {output.task.version.algorithm.name} {output.task.version.version}；SHA256 {output.checksum}"
        resource.save(update_fields=["source", "description", "status"])
        record.resource = resource
        record.status = "ready"
        record.error = ""
        record.save(update_fields=["resource", "status", "error"])
    return resource
