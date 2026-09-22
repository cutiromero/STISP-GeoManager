from __future__ import annotations

from typing import Any

from apps.catalog.models import DataResource
from apps.raster.models import RasterDataset
from apps.raster.services.serializers import (
    compact_raster_metadata,
    serialize_raster_dataset,
)


def dataset_for_resource(resource: DataResource) -> RasterDataset | None:
    if resource.data_type != DataResource.DataType.RASTER:
        return None
    return (
        RasterDataset.objects.filter(data_resource=resource)
        .order_by("-imported_at")
        .first()
    )


def get_raster_profile(resource: DataResource) -> dict[str, Any] | None:
    dataset = dataset_for_resource(resource)
    if not dataset:
        return None
    metadata = compact_raster_metadata(
        dataset.processed_gdalinfo or dataset.source_gdalinfo, dataset.source_gdalinfo
    )
    fields = [
        {
            "name": f"Band {band['band']}",
            "type": band.get("type", ""),
            "nullable": False,
            "sampleValues": [band.get("min"), band.get("max")],
        }
        for band in metadata.get("bands", [])
    ]
    return {
        "fields": fields,
        "bounds": dataset.bounds_4326,
        "raster": {**serialize_raster_dataset(dataset), "metadata": metadata},
    }
