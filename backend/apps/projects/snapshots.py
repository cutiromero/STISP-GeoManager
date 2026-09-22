from django.core.exceptions import ValidationError
from .context import current_scope


def validate_snapshot_project(snapshot):
    """Reject cross-project object references even inside JSON snapshots."""
    from apps.catalog.models import DataResource
    from apps.raster.models import RasterDataset

    scope = current_scope.get()
    if scope is None:
        return
    resource_ids, raster_ids = set(), set()

    def walk(value):
        if isinstance(value, dict):
            source = value.get("sourceResource")
            if isinstance(source, dict) and type(source.get("id")) is int:
                resource_ids.add(source["id"])
            for key, item in value.items():
                if key in {"resourceId", "dataResourceId"} and type(item) is int:
                    resource_ids.add(item)
                if key in {"datasetId", "rasterDatasetId"} and type(item) is int:
                    raster_ids.add(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(snapshot)
    # Missing resources may remain as unresolved references in old drafts.
    # Existing foreign-project references are never accepted.
    for model, ids in [(DataResource, resource_ids), (RasterDataset, raster_ids)]:
        if (
            model._base_manager.filter(pk__in=ids)
            .exclude(project_tag_id__in=scope.ids)
            .exists()
        ):
            raise ValidationError("工程快照包含其他项目的数据引用，请在对应项目中保存")
