from apps.catalog.models import (
    DataCatalog,
    DataResource,
    DictionaryItem,
    MapLayer,
)
from apps.catalog.taxonomy import serialize_category_path


def current_visualization(resource):
    from apps.agent.display_color_policy import refresh_visualization

    return refresh_visualization(resource.default_visualization)


def serialize_dictionary(item: DictionaryItem | None) -> dict | None:
    if item is None:
        return None
    return {
        "id": item.id,
        "type": item.dict_type,
        "code": item.code,
        "name": item.name,
        "parentId": item.parent_id,
        "selectable": item.is_selectable,
    }


def serialize_resource(resource: DataResource) -> dict:
    available_views, default_view = _resource_views(resource)
    return {
        "id": resource.id,
        "projectTagId": resource.project_tag_id,
        "name": resource.name,
        "code": resource.code,
        "dataType": resource.data_type,
        "spatialClass": resource.spatial_class,
        "domainType": resource.domain_type or None,
        "category": serialize_dictionary(resource.category),
        "categoryPath": serialize_category_path(resource.category),
        "classificationStatus": (
            "classified" if resource.category_id is not None else "pending"
        ),
        "availableViews": available_views,
        "defaultView": default_view,
        "source": resource.source,
        "provider": resource.provider,
        "dataDate": resource.data_date.isoformat() if resource.data_date else None,
        "spatialExtent": resource.spatial_extent,
        "coordinateSystem": resource.coordinate_system,
        "fileFormat": resource.file_format,
        "description": resource.description,
        "qualityNote": resource.quality_note,
        "sizeBytes": resource.size_bytes,
        "itemCount": resource.item_count,
        "status": resource.status,
        "isQueryable": bool(
            resource.data_type == DataResource.DataType.VECTOR and resource.storage_path
        ),
        "isRenderable": bool(
            resource.data_type == DataResource.DataType.RASTER and resource.storage_path
        ),
        "updatedAt": resource.updated_at.isoformat(),
    }


def _resource_views(resource: DataResource) -> tuple[list[str], str]:
    if (
        resource.data_type
        in {DataResource.DataType.VECTOR, DataResource.DataType.RASTER}
        and resource.spatial_class != DataResource.SpatialClass.SPATIAL
    ):
        return ["metadata"], "metadata"
    if resource.data_type == DataResource.DataType.VECTOR:
        return ["map", "table", "metadata"], "map"
    if resource.data_type == DataResource.DataType.RASTER:
        return ["map", "metadata"], "map"
    if resource.data_type == DataResource.DataType.IMAGE:
        return ["gallery", "metadata"], "gallery"
    if resource.data_type in {DataResource.DataType.TABLE, DataResource.DataType.GENE}:
        return ["table", "metadata"], "table"
    return ["metadata"], "metadata"


def serialize_catalog(catalog: DataCatalog) -> dict:
    return {
        "id": catalog.id,
        "name": catalog.name,
        "code": catalog.code,
        "parentId": catalog.parent_id,
        "description": catalog.description,
        "sortOrder": catalog.sort_order,
        "resources": [
            serialize_resource(resource) for resource in catalog.resources.all()
        ],
    }


def serialize_layer(layer: MapLayer) -> dict:
    return {
        "id": layer.id,
        "projectTagId": layer.project_tag_id,
        "name": layer.name,
        "code": layer.code,
        "layerType": layer.layer_type,
        "geometryType": layer.geometry_type,
        "category": serialize_dictionary(layer.category),
        "dataResourceId": layer.data_resource_id,
        "sortOrder": layer.sort_order,
        "defaultVisible": layer.default_visible,
        "defaultOpacity": layer.default_opacity,
        "symbolization": layer.symbolization,
        "bounds": layer.bounds,
        "legend": layer.legend,
        "rasterRules": layer.raster_rules,
        "isActive": layer.is_active,
        "updatedAt": layer.updated_at.isoformat(),
    }
