from __future__ import annotations

from typing import Any

from django.contrib.auth.models import Group

from apps.catalog.models import DataResource, MapLayer
from apps.catalog.taxonomy import resolve_data_category
from apps.core.initialization import ensure_superadmin_defaults
from apps.raster.models import RasterDataset
from apps.standards.models import DataDomainType


def upsert_catalog_records(
    *,
    dataset: RasterDataset,
    source_info: dict[str, Any],
    processed_info: dict[str, Any],
    default_rules: dict[str, Any],
    bounds_4326: list[float],
    uploader_id: int | None = None,
    access_group_ids: list[int] | None = None,
    category_code: str = "",
) -> tuple[DataResource, MapLayer]:
    spatial_extent = (
        ",".join(f"{value:.6f}" for value in bounds_4326) if bounds_4326 else ""
    )
    coordinate_system = (
        f"EPSG:{(processed_info.get('stac') or {}).get('proj:epsg', 3857)}"
    )
    resource_defaults = {
        "name": dataset.name,
        "data_type": DataResource.DataType.RASTER,
        "domain_type": DataDomainType.REMOTE_SENSING,
        "source": "栅格导入",
        "provider": "",
        "spatial_extent": spatial_extent,
        "coordinate_system": coordinate_system,
        "file_format": "COG",
        "storage_path": dataset.processed_relative_path,
        "description": "由栅格上传或目录扫描导入的预处理数据集。",
        "quality_note": (
            "导入时保留原始栅格数据包，并使用 gdalwarp 统一生成 EPSG:3857 "
            f"展示 COG；重采样方式为 {dataset.resampling}。"
        ),
        "size_bytes": dataset.source_file_size + dataset.processed_file_size,
        "item_count": 1,
        "maintainer_id": uploader_id,
        "status": DataResource.Status.ACTIVE,
    }
    if category_code:
        resource_defaults["category"] = resolve_data_category(category_code)
    data_resource, _ = DataResource.objects.update_or_create(
        code=dataset.code,
        defaults=resource_defaults,
    )
    map_layer, _ = MapLayer.objects.update_or_create(
        code=dataset.code,
        defaults={
            "name": dataset.name,
            "layer_type": MapLayer.LayerType.RASTER,
            "geometry_type": MapLayer.GeometryType.MIXED,
            "data_resource": data_resource,
            "source_path": dataset.processed_relative_path,
            "default_visible": False,
            "default_opacity": (
                100
                if dataset.raster_kind == RasterDataset.RasterKind.CATEGORICAL
                else 90
            ),
            "bounds": bounds_4326,
            "legend": "",
            "raster_rules": default_rules,
            "is_active": True,
        },
    )
    _, superadmin_group = ensure_superadmin_defaults(
        create_account=False, attach_existing_superusers=False
    )
    selected_groups = list(
        Group.objects.filter(pk__in=access_group_ids or []).exclude(
            pk=superadmin_group.pk
        )
    )
    groups = [superadmin_group, *selected_groups]
    data_resource.access_groups.set(groups)
    map_layer.access_groups.set(groups)
    return data_resource, map_layer
