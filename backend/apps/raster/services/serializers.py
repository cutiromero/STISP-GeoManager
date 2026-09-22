from __future__ import annotations

from typing import Any

from apps.raster.models import RasterDataset
from apps.raster.services.rules_engine import band_min_max, is_integer_band


def serialize_raster_dataset(dataset: RasterDataset) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "code": dataset.code,
        "status": dataset.status,
        "sourcePath": dataset.source_relative_path,
        "processedPath": dataset.processed_relative_path,
        "sourceMetadataPath": dataset.source_metadata_relative_path,
        "processedMetadataPath": dataset.processed_metadata_relative_path,
        "dataResourceId": dataset.data_resource_id,
        "mapLayerId": dataset.map_layer_id,
        "bandCount": dataset.band_count,
        "bounds3857": dataset.bounds_3857,
        "bounds4326": dataset.bounds_4326,
        "imageCoordinates": dataset.image_coordinates,
        "defaultRules": dataset.map_layer.raster_rules
        if dataset.map_layer_id and dataset.map_layer.raster_rules
        else dataset.default_rules,
        "sourceFileSize": dataset.source_file_size,
        "processedFileSize": dataset.processed_file_size,
        "progressLog": dataset.progress_log,
        "errorMessage": dataset.error_message,
        "importedAt": dataset.imported_at.isoformat() if dataset.imported_at else None,
        "processedAt": dataset.processed_at.isoformat()
        if dataset.processed_at
        else None,
        "sourceFileName": dataset.source_file_name,
        "sourceFormat": dataset.source_format,
        "sourceManifest": dataset.source_manifest,
        "sourceChecksumSha256": dataset.source_checksum_sha256,
        "rasterKind": dataset.raster_kind,
        "metadata": compact_raster_metadata(
            dataset.processed_gdalinfo or dataset.source_gdalinfo,
            dataset.source_gdalinfo,
        ),
    }


def compact_raster_metadata(
    metadata: dict[str, Any], fallback_metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    bands = []
    for band in metadata.get("bands") or []:
        band_number = int(band.get("band") or len(bands) + 1)
        bands.append(
            {
                "band": band_number,
                "type": band.get("type", ""),
                "description": band.get("description") or f"Band {band_number}",
                "colorInterpretation": band.get("colorInterpretation", ""),
                "min": band_min_max(metadata, band_number, fallback_metadata)[0],
                "max": band_min_max(metadata, band_number, fallback_metadata)[1],
                "isInteger": is_integer_band(metadata, band_number),
            }
        )
    return {
        "size": metadata.get("size") or [],
        "driver": metadata.get("driverShortName", ""),
        "coordinateSystem": (metadata.get("stac") or {}).get("proj:epsg") or "",
        "bands": bands,
    }
