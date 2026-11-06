"""Verify exact raster duplicates before privileged historical deduplication."""

import hashlib
import json
import rasterio
from rasterio.windows import Window
from django.core.exceptions import PermissionDenied
from apps.core.storage import raster_processed_path
from apps.projects.context import is_superadmin
from .models import DataResource


def raster_signature(resource):
    dataset = resource.raster_datasets.filter(status="ready").first()
    if dataset is None or not dataset.processed_relative_path:
        raise PermissionDenied("重复资料缺少已就绪的实际栅格")
    content = hashlib.sha256()
    with rasterio.open(
        raster_processed_path(dataset.processed_relative_path)
    ) as raster:
        header = {
            "crs": str(raster.crs),
            "transform": list(raster.transform),
            "shape": [raster.count, raster.height, raster.width],
            "dtypes": raster.dtypes,
            "nodata": str(raster.nodata),
        }
        content.update(json.dumps(header, sort_keys=True).encode())
        for y in range(0, raster.height, 512):
            for x in range(0, raster.width, 512):
                window = Window(
                    x, y, min(512, raster.width - x), min(512, raster.height - y)
                )
                content.update(raster.read(window=window).tobytes())
                content.update(raster.read_masks(window=window).tobytes())
    return content.hexdigest()


def verify_duplicate(resource, replacement_id, user):
    if (
        not is_superadmin(user)
        or resource.data_type != "raster"
        or resource.is_compute_result
    ):
        raise PermissionDenied("原始资料去重仅允许管理员核验原始栅格")
    replacement = (
        DataResource.objects.filter(
            pk=replacement_id,
            project_tag_id=resource.project_tag_id,
            data_type="raster",
            status="active",
            is_compute_result=False,
        )
        .exclude(pk=resource.pk)
        .first()
    )
    if replacement is None:
        raise PermissionDenied("保留的正式资料不存在或不属于当前项目")
    before, after = raster_signature(resource), raster_signature(replacement)
    if before != after:
        raise PermissionDenied(
            "两份栅格的像元、掩膜、网格、坐标系或范围不同，不能按重复资料删除"
        )
    return {
        "replacementResourceId": replacement.id,
        "replacementName": replacement.name,
        "rasterContentSha256": before,
    }
