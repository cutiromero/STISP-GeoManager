from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

from django.db import OperationalError, ProgrammingError, transaction
from django.utils import timezone

from apps.core.runtime_config import (
    RuntimeConfigError,
    runtime_max_raster_side_pixels,
    runtime_upload_max_mb,
)
from apps.core.storage import (
    raster_metadata_path,
    raster_processed_path,
    raster_source_path,
)
from apps.raster.models import RasterBand, RasterDataset
from apps.raster.services.catalog_sync import upsert_catalog_records
from apps.raster.services.constants import RASTER_EXTENSIONS
from apps.raster.services.exceptions import RasterImportError
from apps.raster.services.gdal_ops import gdalinfo_json, run_gdal_command
from apps.raster.services.geo_utils import (
    bounds_4326_from_gdalinfo,
    bounds_from_gdalinfo,
    image_coordinates_from_gdalinfo,
)
from apps.raster.services.progress import normalize_progress_text
from apps.raster.services.rules_engine import default_raster_rules, normalize_rules


RASTER_PREPROCESSING_VERSION = 2


def is_raster_file(path: Path) -> bool:
    return (
        path.is_file()
        and not path.name.startswith(".")
        and path.suffix.lower() in RASTER_EXTENSIONS
    )


def normalize_import_resampling(raster_kind: str, resampling: str) -> str:
    """Categorical rasters must never interpolate class identifiers."""

    return (
        "nearest" if raster_kind == RasterDataset.RasterKind.CATEGORICAL else resampling
    )


def gdalwarp_cog_command(
    source_path: Path,
    processed_path: Path,
    resampling: str,
    *,
    nodata: int | float | None = None,
) -> list[str]:
    """Build a COG command whose warp and every overview use one resampler."""

    overview_resampling = resampling.upper()
    command = [
        "gdalwarp",
        "--config",
        "GDAL_CACHEMAX",
        "128",
        "-t_srs",
        "EPSG:3857",
        "-r",
        resampling,
        "-wo",
        "NUM_THREADS=1",
        "-wo",
        "UNIFIED_SRC_NODATA=YES",
        "-wo",
        "INIT_DEST=NO_DATA",
        "-wm",
        "128",
        "-co",
        "COMPRESS=DEFLATE",
        "-co",
        "BLOCKSIZE=512",
        "-co",
        "BIGTIFF=IF_SAFER",
        "-co",
        "NUM_THREADS=1",
        # A source GeoTIFF may already contain overviews created with bilinear
        # interpolation. Never copy those into a categorical COG.
        "-co",
        "OVERVIEWS=IGNORE_EXISTING",
        "-co",
        f"WARP_RESAMPLING={overview_resampling}",
        "-co",
        f"OVERVIEW_RESAMPLING={overview_resampling}",
        "-of",
        "COG",
    ]
    if nodata is not None:
        command.extend(("-srcnodata", str(nodata), "-dstnodata", str(nodata)))
    command.extend((str(source_path), str(processed_path)))
    return command


def validate_raster_upload_size(uploaded_file) -> None:
    try:
        upload_max_mb = runtime_upload_max_mb()
    except RuntimeConfigError as exc:
        raise RasterImportError(str(exc)) from exc
    max_bytes = upload_max_mb * 1024 * 1024
    if uploaded_file.size > max_bytes:
        raise RasterImportError(f"栅格文件大小不能超过 {upload_max_mb} MB")


def validate_raster_pixel_size(info: dict[str, Any]) -> None:
    try:
        max_side_pixels = runtime_max_raster_side_pixels()
    except RuntimeConfigError as exc:
        raise RasterImportError(str(exc)) from exc
    raw_size = info.get("size")
    if (
        not isinstance(raw_size, list | tuple)
        or len(raw_size) < 2
        or not all(isinstance(value, int) for value in raw_size[:2])
    ):
        raise RasterImportError("无法读取栅格像素尺寸")
    width, height = raw_size[:2]
    if width > max_side_pixels or height > max_side_pixels:
        raise RasterImportError(
            f"栅格单边长度不能超过 {max_side_pixels} 像素，当前为 {width} x {height}"
        )


def store_source_file(input_path: Path) -> tuple[Path, str]:
    source_root = raster_source_path("")
    try:
        relative = input_path.relative_to(source_root).as_posix()
        return input_path, relative
    except ValueError:
        digest = hashlib.sha256(str(input_path).encode("utf-8")).hexdigest()[:12]
        target_relative = f"imported/{digest}-{input_path.name}"
        target_path = raster_source_path(target_relative)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if input_path.resolve() != target_path.resolve():
            shutil.copy2(input_path, target_path)
        return target_path, target_relative


def store_uploaded_source_file(uploaded_file) -> Path:
    source_name = Path(uploaded_file.name or "uploaded-raster").name
    suffix = Path(source_name).suffix.lower()
    if suffix not in RASTER_EXTENSIONS:
        raise RasterImportError(f"不支持的栅格文件格式：{suffix or source_name}")
    validate_raster_upload_size(uploaded_file)
    target_relative = f"uploaded/{uuid.uuid4().hex}{suffix}"
    target_path = raster_source_path(target_relative)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("wb") as output:
        for chunk in uploaded_file.chunks():
            output.write(chunk)
    try:
        validate_raster_pixel_size(gdalinfo_json(target_path))
    except Exception:
        target_path.unlink(missing_ok=True)
        raise
    return target_path


def cleanup_uploaded_import_files(source_path: Path) -> None:
    source_root = raster_source_path("")
    source_path = source_path.expanduser().resolve()
    try:
        source_relative = source_path.relative_to(source_root).as_posix()
    except ValueError:
        return
    if not source_relative.startswith("uploaded/"):
        return

    processed_relative = processed_relative_path(source_relative)
    source_metadata_relative = metadata_relative_path("source", source_relative)
    processed_metadata_relative = metadata_relative_path(
        "preprocessed", processed_relative
    )
    cleanup_paths = [
        source_path,
        raster_processed_path(processed_relative),
        raster_metadata_path(source_metadata_relative),
        raster_metadata_path(processed_metadata_relative),
    ]
    manifest_path = source_path.parent / "manifest.json"
    if manifest_path.exists():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest_data = {}
        for item in manifest_data.get("files") or []:
            name = Path(str(item.get("name") or "")).name
            if name:
                cleanup_paths.append(source_path.parent / name)
        cleanup_paths.append(manifest_path)
    for path in dict.fromkeys(cleanup_paths):
        path.unlink(missing_ok=True)
    RasterDataset.objects.filter(source_relative_path=source_relative).delete()


def processed_relative_path(source_relative: str) -> str:
    source = Path(source_relative)
    return (source.parent / f"{source.stem}.cog.tif").as_posix()


def metadata_relative_path(kind: str, raster_relative: str) -> str:
    return (Path(kind) / f"{raster_relative}.gdalinfo.json").as_posix()


def stable_code(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def save_metadata(relative_path: str, metadata: dict[str, Any]) -> None:
    path = raster_metadata_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def handle_import_progress(
    text: str, progress: Callable[[str], None] | None = None
) -> None:
    cleaned = normalize_progress_text(text)
    if not cleaned:
        return
    if progress:
        progress(cleaned)


def scan_unprocessed_source_files(
    progress: Callable[[str], None] | None = None,
) -> list[RasterDataset]:
    import logging

    logger = logging.getLogger(__name__)
    source_root = raster_source_path("")
    imported: list[RasterDataset] = []
    for source_path in sorted(source_root.rglob("*")):
        if not is_raster_file(source_path):
            continue
        source_relative = source_path.relative_to(source_root).as_posix()
        dataset = (
            RasterDataset.objects.select_related("map_layer", "data_resource__category")
            .prefetch_related("data_resource__access_groups")
            .filter(source_relative_path=source_relative)
            .first()
        )
        processed_exists = bool(
            dataset
            and dataset.processed_relative_path
            and raster_processed_path(dataset.processed_relative_path).exists()
        )
        if (
            dataset
            and dataset.status == RasterDataset.Status.READY
            and processed_exists
            and _preprocessing_is_current(dataset)
        ):
            continue
        if progress:
            progress(f"发现未处理源文件：{source_relative}")
        try:
            import_options: dict[str, Any] = {"progress": progress}
            if dataset:
                resource = dataset.data_resource
                import_options.update(
                    {
                        "name": dataset.name,
                        "source_manifest": dataset.source_manifest,
                        "source_checksum_sha256": dataset.source_checksum_sha256,
                        "raster_kind": dataset.raster_kind,
                        "resampling": dataset.resampling,
                        "requested_default_rules": (
                            dataset.map_layer.raster_rules
                            if dataset.map_layer_id and dataset.map_layer.raster_rules
                            else dataset.default_rules
                        ),
                        "uploader_id": resource.maintainer_id if resource else None,
                        "access_group_ids": (
                            list(resource.access_groups.values_list("id", flat=True))
                            if resource
                            else None
                        ),
                        "category_code": (
                            resource.category.code
                            if resource and resource.category_id
                            else ""
                        ),
                    }
                )
            imported.append(import_raster_file(source_path, **import_options))
        except Exception:
            logger.exception("扫描导入栅格文件失败：%s", source_relative)
            if progress:
                progress(f"导入失败（已跳过）：{source_relative}")
    return imported


def scan_unprocessed_source_files_safely() -> None:
    import logging

    logger = logging.getLogger(__name__)
    try:
        scan_unprocessed_source_files()
    except (OperationalError, ProgrammingError):
        logger.debug("栅格扫描跳过：数据库尚未就绪")
    except Exception:
        logger.exception("栅格扫描失败")


def import_raster_file(
    input_path: Path,
    *,
    name: str = "",
    progress: Callable[[str], None] | None = None,
    source_manifest: list[dict[str, Any]] | None = None,
    source_checksum_sha256: str = "",
    raster_kind: str = RasterDataset.RasterKind.IMAGERY,
    resampling: str = "bilinear",
    requested_default_rules: dict[str, Any] | None = None,
    uploader_id: int | None = None,
    access_group_ids: list[int] | None = None,
    category_code: str = "",
) -> RasterDataset:
    input_path = input_path.expanduser().resolve()
    if not input_path.exists() or not input_path.is_file():
        raise RasterImportError(f"源文件不存在：{input_path}")
    if not is_raster_file(input_path):
        raise RasterImportError(f"不支持的栅格文件格式：{input_path.suffix}")

    source_path, source_relative = store_source_file(input_path)
    processed_relative = processed_relative_path(source_relative)
    processed_path = raster_processed_path(processed_relative)
    source_metadata_relative = metadata_relative_path("source", source_relative)
    processed_metadata_relative = metadata_relative_path(
        "preprocessed", processed_relative
    )

    manifest = source_manifest or [
        {
            "name": source_path.name,
            "size": source_path.stat().st_size,
            "role": "primary",
        }
    ]
    source_total_size = sum(int(item.get("size") or 0) for item in manifest)
    if raster_kind not in RasterDataset.RasterKind.values:
        raise RasterImportError(f"不支持的栅格数据语义：{raster_kind}")
    if resampling not in {"nearest", "bilinear", "cubic"}:
        raise RasterImportError(f"不支持的栅格重采样方式：{resampling}")
    resampling = normalize_import_resampling(raster_kind, resampling)

    dataset, _ = RasterDataset.objects.update_or_create(
        source_relative_path=source_relative,
        defaults={
            "name": name.strip() or input_path.stem,
            "code": stable_code("raster", source_relative),
            "source_file_name": input_path.name,
            "source_manifest": manifest,
            "source_checksum_sha256": source_checksum_sha256,
            "raster_kind": raster_kind,
            "resampling": resampling,
            "processed_relative_path": processed_relative,
            "source_metadata_relative_path": source_metadata_relative,
            "processed_metadata_relative_path": processed_metadata_relative,
            "status": RasterDataset.Status.PROCESSING,
            "error_message": "",
            "source_file_size": source_total_size or source_path.stat().st_size,
        },
    )
    try:
        if progress:
            progress("gdalinfo -json 源文件")
        source_info = gdalinfo_json(source_path, calculate_statistics=True)
        validate_raster_pixel_size(source_info)
        save_metadata(source_metadata_relative, source_info)
        dataset.source_format = str(source_info.get("driverShortName") or "")

        # Source-side thematic metadata is authoritative. This also protects
        # legacy upload and directory-scan clients that did not send rasterKind.
        from apps.raster.services.package import (
            infer_raster_kind,
            suggested_default_rules,
        )

        if infer_raster_kind(source_info) == RasterDataset.RasterKind.CATEGORICAL:
            raster_kind = RasterDataset.RasterKind.CATEGORICAL
            resampling = normalize_import_resampling(raster_kind, resampling)
            dataset.raster_kind = raster_kind
            dataset.resampling = resampling

        processed_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_processed_path = processed_path.with_name(
            f".{processed_path.stem}.{uuid.uuid4().hex}.tmp.tif"
        )

        if progress:
            progress(
                f"gdalwarp -t_srs EPSG:3857 -r {resampling} "
                "-co COMPRESS=DEFLATE -of COG"
            )
        try:
            run_gdal_command(
                gdalwarp_cog_command(
                    source_path,
                    temporary_processed_path,
                    resampling,
                    nodata=(
                        _first_band_nodata(source_info)
                        if raster_kind == RasterDataset.RasterKind.CATEGORICAL
                        else None
                    ),
                ),
                progress=lambda text: handle_import_progress(text, progress),
            )
            os.replace(temporary_processed_path, processed_path)
        finally:
            temporary_processed_path.unlink(missing_ok=True)
        if progress:
            progress("gdalwarp 预处理完成")

        if progress:
            progress("gdalinfo -json 预处理文件")
        processed_info = gdalinfo_json(processed_path, calculate_statistics=True)
        processed_info["geoManager"] = {
            "preprocessingVersion": RASTER_PREPROCESSING_VERSION,
            "rasterKind": raster_kind,
            "resampling": resampling,
        }
        save_metadata(processed_metadata_relative, processed_info)

        default_rules = normalize_rules(
            requested_default_rules
            or (
                suggested_default_rules(source_info, input_path.name)
                if raster_kind == RasterDataset.RasterKind.CATEGORICAL
                else default_raster_rules(source_info, processed_info)
            ),
            processed_info,
        )
        bounds_3857 = bounds_from_gdalinfo(processed_info)
        bounds_4326 = bounds_4326_from_gdalinfo(processed_info)
        image_coordinates = image_coordinates_from_gdalinfo(processed_info)
        dataset.processed_file_size = processed_path.stat().st_size
        with transaction.atomic():
            data_resource, map_layer = upsert_catalog_records(
                dataset=dataset,
                source_info=source_info,
                processed_info=processed_info,
                default_rules=default_rules,
                bounds_4326=bounds_4326,
                uploader_id=uploader_id,
                access_group_ids=access_group_ids,
                category_code=category_code,
            )

            dataset.source_gdalinfo = source_info
            dataset.processed_gdalinfo = processed_info
            dataset.default_rules = default_rules
            dataset.bounds_3857 = bounds_3857
            dataset.bounds_4326 = bounds_4326
            dataset.image_coordinates = image_coordinates
            dataset.band_count = len(processed_info.get("bands") or [])
            dataset.data_resource = data_resource
            dataset.map_layer = map_layer
            dataset.status = RasterDataset.Status.READY
            dataset.error_message = ""
            dataset.processed_at = timezone.now()
            dataset.save()
            _sync_band_records(dataset, processed_info)
        if raster_kind == RasterDataset.RasterKind.CATEGORICAL:
            from apps.raster.services.renderer import (
                build_static_xyz_tile_pyramid,
                register_tile_style,
            )

            if progress:
                progress("生成 LUCC 最近邻静态瓦片金字塔")
            render_result = register_tile_style(dataset, default_rules)

            def report_pyramid_progress(done: int, total: int, zoom: int) -> None:
                if progress:
                    percent = round(done * 100 / max(1, total))
                    progress(f"LUCC 静态瓦片 z{zoom}：{done}/{total}（{percent}%）")

            pyramid = build_static_xyz_tile_pyramid(
                dataset,
                str(render_result["styleHash"]),
                progress=report_pyramid_progress,
            )
            if progress and pyramid:
                action = "复用" if pyramid.reused else "生成"
                progress(
                    f"LUCC 静态瓦片已{action}：z{pyramid.min_zoom}–"
                    f"z{pyramid.max_zoom}，共 {pyramid.total_tiles} 张"
                )
        if progress:
            progress("导入完成")
        return dataset
    except Exception as exc:
        dataset.status = RasterDataset.Status.FAILED
        dataset.error_message = str(exc)
        if progress:
            progress(f"导入失败：{exc}")
        dataset.save(update_fields=("status", "error_message", "updated_at"))
        raise


def _sync_band_records(dataset: RasterDataset, metadata: dict[str, Any]) -> None:
    seen: set[int] = set()
    for raw_band in metadata.get("bands") or []:
        band_index = int(raw_band.get("band") or len(seen) + 1)
        seen.add(band_index)
        band_metadata = raw_band.get("metadata") or {}
        minimum = raw_band.get("min", raw_band.get("minimum"))
        maximum = raw_band.get("max", raw_band.get("maximum"))
        RasterBand.objects.update_or_create(
            dataset=dataset,
            band_index=band_index,
            defaults={
                "name": str(raw_band.get("description") or f"Band {band_index}"),
                "data_type": str(raw_band.get("type") or ""),
                "color_interpretation": str(raw_band.get("colorInterpretation") or ""),
                "nodata": raw_band.get("noDataValue"),
                "unit": str(raw_band.get("unit") or ""),
                "minimum": float(minimum) if minimum is not None else None,
                "maximum": float(maximum) if maximum is not None else None,
                "metadata": band_metadata,
            },
        )
    RasterBand.objects.filter(dataset=dataset).exclude(band_index__in=seen).delete()


def _first_band_nodata(metadata: dict[str, Any]) -> int | float | None:
    bands = metadata.get("bands") or []
    value = bands[0].get("noDataValue") if bands else None
    return value if isinstance(value, int | float) else None


def _preprocessing_is_current(dataset: RasterDataset) -> bool:
    if dataset.raster_kind != RasterDataset.RasterKind.CATEGORICAL:
        return True
    marker = (dataset.processed_gdalinfo or {}).get("geoManager") or {}
    try:
        version = int(marker.get("preprocessingVersion") or 0)
    except (TypeError, ValueError):
        version = 0
    return (
        version >= RASTER_PREPROCESSING_VERSION
        and marker.get("rasterKind") == RasterDataset.RasterKind.CATEGORICAL
        and marker.get("resampling") == "nearest"
        and dataset.resampling == "nearest"
    )


def dataset_for_layer(layer: Any) -> RasterDataset:
    from apps.catalog.models import MapLayer
    from apps.raster.services.exceptions import RasterRenderError

    if layer.layer_type != MapLayer.LayerType.RASTER:
        raise RasterRenderError("该图层不是栅格图层")
    dataset = RasterDataset.objects.filter(
        map_layer=layer, status=RasterDataset.Status.READY
    ).first()
    if dataset:
        return dataset
    if layer.data_resource_id:
        dataset = RasterDataset.objects.filter(
            data_resource=layer.data_resource, status=RasterDataset.Status.READY
        ).first()
        if dataset:
            return dataset
    raise RasterRenderError("该图层没有关联已预处理的栅格数据集")
