from __future__ import annotations

import csv
import json
import re
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

from django.core.exceptions import ValidationError

from apps.core.storage import raster_source_path
from apps.raster.models import RasterDataset
from apps.raster.services.gdal_ops import run_gdal_command


class ExportError(Exception):
    pass


ProgressCallback = Callable[[str], None]


def export_layers_zip(
    items: list[dict[str, Any]],
    epsg: int | None,
    *,
    reproject: bool = True,
    clip_geometry: dict[str, Any] | None = None,
    vector_format: str = "geojson",
    progress: ProgressCallback | None = None,
) -> bytes:
    """Compatibility wrapper for callers that still require in-memory bytes."""

    with TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "layers.zip"
        export_layers_zip_to_path(
            items,
            epsg,
            output_path=zip_path,
            reproject=reproject,
            clip_geometry=clip_geometry,
            vector_format=vector_format,
            progress=progress,
        )
        return zip_path.read_bytes()


def export_layers_zip_to_path(
    items: list[dict[str, Any]],
    epsg: int | None,
    *,
    output_path: Path,
    reproject: bool = True,
    clip_geometry: dict[str, Any] | None = None,
    vector_format: str = "geojson",
    progress: ProgressCallback | None = None,
) -> Path:
    if not items:
        raise ExportError("缺少导出图层")
    if reproject and (epsg is None or epsg < 1024 or epsg > 999999):
        raise ExportError("EPSG code 不合法")
    vector_format = validate_vector_format(vector_format)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="geomanager-export-work-") as tmpdir:
        root = Path(tmpdir)
        cutline_path = write_cutline(root, clip_geometry) if clip_geometry else None
        with zipfile.ZipFile(
            output_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for index, item in enumerate(items, start=1):
                layer_type = item.get("layerType")
                name = safe_filename(str(item.get("name") or f"layer-{index}"))
                prefix = f"{index:02d}-{name}"
                if layer_type == "vector":
                    export_vector_layer(
                        item.get("geojson"),
                        epsg if reproject and epsg else 4326,
                        root,
                        prefix,
                        vector_format,
                        archive,
                    )
                elif layer_type == "raster":
                    output = root / f"{prefix}.tif"
                    if progress:
                        progress(f"开始导出栅格：{name}")
                    export_raster_tif(
                        int(item.get("datasetId") or 0),
                        epsg if reproject else None,
                        output,
                        clip_cutline=cutline_path,
                        progress=progress,
                    )
                    archive.write(output, output.name)
                else:
                    raise ExportError(f"不支持的图层类型：{layer_type}")
        if progress:
            progress("导出压缩包已生成 100%")
    return output_path


def validate_vector_format(value: Any) -> str:
    vector_format = str(value or "geojson").strip().lower()
    if vector_format not in {"geojson", "shapefile"}:
        raise ExportError("导出格式必须是 geojson 或 shapefile")
    return vector_format


def export_vector_layer(
    geojson: Any,
    epsg: int,
    root: Path,
    prefix: str,
    vector_format: str,
    archive: zipfile.ZipFile,
) -> None:
    if vector_format == "geojson":
        output = root / f"{prefix}.geojson"
        export_vector_geojson(geojson, epsg, output)
        archive.write(output, output.name)
        attributes_output = root / f"{prefix}-attributes.csv"
        export_vector_attributes_csv(geojson, attributes_output)
        archive.write(attributes_output, attributes_output.name)
        return

    folder = root / prefix
    folder.mkdir()
    output = folder / f"{prefix}.shp"
    export_vector_shapefile(geojson, epsg, output)
    for file_path in folder.iterdir():
        archive.write(file_path, f"{prefix}/{file_path.name}")
    attributes_output = root / f"{prefix}-attributes.csv"
    export_vector_attributes_csv(geojson, attributes_output)
    archive.write(attributes_output, f"{prefix}/{attributes_output.name}")


def export_vector_geojson(geojson: Any, epsg: int, output: Path) -> None:
    if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
        raise ExportError("矢量图层缺少有效 GeoJSON")
    features = geojson.get("features") or []
    if not features:
        output.write_text(
            json.dumps(
                {"type": "FeatureCollection", "features": []}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        return

    try:
        import geopandas as gpd

        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        if epsg != 4326:
            gdf = gdf.to_crs(epsg=epsg)
        gdf.to_file(output, driver="GeoJSON", index=False)
    except Exception as exc:
        raise ExportError(f"导出矢量 GeoJSON 失败：{exc}") from exc


def export_vector_attributes_csv(geojson: Any, output: Path) -> None:
    if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
        raise ExportError("矢量图层缺少有效 GeoJSON，无法导出属性表")
    features = geojson.get("features") or []
    if not isinstance(features, list):
        raise ExportError("矢量图层 GeoJSON features 必须是数组")

    columns = attribute_columns(features)
    index_column = unique_index_column(columns)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[index_column, *columns])
        writer.writeheader()
        for index, feature in enumerate(features, start=1):
            properties = {}
            if isinstance(feature, dict) and isinstance(
                feature.get("properties"), dict
            ):
                properties = feature["properties"]
            row = {index_column: index}
            for column in columns:
                row[column] = csv_value(properties.get(column))
            writer.writerow(row)


def attribute_columns(features: list[Any]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue
        for key in properties:
            column = str(key)
            if column in seen:
                continue
            seen.add(column)
            columns.append(column)
    return columns


def unique_index_column(columns: list[str]) -> str:
    column = "feature_index"
    while column in columns:
        column = f"_{column}"
    return column


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False)


def export_vector_shapefile(geojson: Any, epsg: int, output: Path) -> None:
    if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
        raise ExportError("矢量图层缺少有效 GeoJSON")
    features = geojson.get("features") or []
    if not features:
        raise ExportError("Shapefile 导出需要至少一条矢量要素")

    try:
        import geopandas as gpd

        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        if epsg != 4326:
            gdf = gdf.to_crs(epsg=epsg)
        gdf.to_file(output, driver="ESRI Shapefile", encoding="UTF-8")
    except Exception as exc:
        raise ExportError(f"导出矢量 Shapefile 失败：{exc}") from exc


def export_raster_tif(
    dataset_id: int,
    epsg: int | None,
    output: Path,
    *,
    clip_cutline: Path | None = None,
    progress: ProgressCallback | None = None,
) -> None:
    dataset = RasterDataset.objects.filter(
        pk=dataset_id, status=RasterDataset.Status.READY
    ).first()
    if not dataset or not dataset.source_relative_path:
        raise ExportError("栅格数据集不可导出")
    source = raster_source_path(dataset.source_relative_path)
    if not source.exists():
        raise ExportError("栅格源文件不存在")

    try:
        command = [
            "gdalwarp",
            "--config",
            "GDAL_CACHEMAX",
            "128",
            "-overwrite",
            "-of",
            "GTiff",
            "-r",
            "near",
            "-wo",
            "NUM_THREADS=1",
            "-wm",
            "128",
            "-co",
            "COMPRESS=DEFLATE",
            "-co",
            "NUM_THREADS=1",
        ]
        if epsg:
            command.extend(["-t_srs", f"EPSG:{epsg}"])
        if clip_cutline:
            command.extend(
                ["-cutline", str(clip_cutline), "-crop_to_cutline", "-dstalpha"]
            )
        command.extend([str(source), str(output)])
        run_gdal_command(command, progress=progress)
    except Exception as exc:
        raise ExportError(f"导出栅格 TIF 失败：{exc}") from exc


def write_cutline(root: Path, geometry: dict[str, Any]) -> Path:
    if not isinstance(geometry, dict) or geometry.get("type") not in {
        "Polygon",
        "MultiPolygon",
    }:
        raise ExportError("裁切图形必须是 Polygon 或 MultiPolygon")
    path = root / "export-cutline.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {}, "geometry": geometry}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value, flags=re.UNICODE).strip(".-")
    return cleaned[:80] or "layer"


def validate_epsg(value: Any) -> int:
    try:
        epsg = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("EPSG code 必须为数字") from exc
    if epsg < 1024 or epsg > 999999:
        raise ValidationError("EPSG code 不合法")
    return epsg
