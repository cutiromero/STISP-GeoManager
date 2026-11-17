"""Shared source authorization at export admission, completion and download."""

from django.contrib.auth import get_user_model

from apps.compute.packages import ComputeError
from apps.core.permissions import has_feature_perm
from apps.projects.context import selected_project_id
from apps.projects.access import can_access_project
from apps.raster.models import RasterDataset
from .permissions import user_can_access
from .models import DataResource, MapLayer


def positive_id(value):
    if type(value) is int:
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdecimal():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def validate_item(item, user):
    if not isinstance(item, dict):
        raise ComputeError("items 中的图层必须是对象")
    resource_id = item.get("resourceId")
    if item.get("layerType") == "raster":
        identity = positive_id(item.get("datasetId"))
        if identity is None:
            raise ComputeError("栅格图层缺少有效 datasetId")
        dataset = (
            RasterDataset.objects.select_related("data_resource")
            .filter(pk=identity)
            .first()
        )
        if dataset is None:
            raise ComputeError("栅格数据集不存在", 404)
        resource = dataset.data_resource
        if resource is None:
            raise ComputeError("栅格数据集未关联数据资源")
        if "resourceId" in item and positive_id(resource_id) != resource.pk:
            raise ComputeError("resourceId 与栅格数据集不匹配")
    elif resource_id:
        identity = positive_id(resource_id)
        if identity is None:
            raise ComputeError("resourceId 不合法")
        resource = DataResource.objects.filter(pk=identity).first()
        if resource is None:
            raise ComputeError("数据资源不存在", 404)
    elif item.get("layerId"):
        layer = (
            MapLayer.objects.select_related("data_resource")
            .filter(pk=positive_id(item["layerId"]))
            .first()
        )
        if layer is None or not user_can_access(layer, user):
            raise ComputeError("图层不存在或无权访问", 404)
        resource = layer.data_resource
        if resource is None:
            return
    else:
        return
    if resource.status != "active":
        raise ComputeError("数据资源不存在", 404)
    if not user_can_access(resource, user):
        raise ComputeError("无权访问该数据资源", 403)


def validate_items(items, user_id):
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        raise ComputeError("账号已停用或不存在", 403)
    if not can_access_project(user, selected_project_id()) or not has_feature_perm(
        user, "catalog.export_dataresource"
    ):
        raise ComputeError("当前账号或项目没有数据导出权限", 403)
    for item in items:
        validate_item(item, user)
    return user


def validate_download(job, user):
    if not has_feature_perm(user, "catalog.export_dataresource"):
        raise ComputeError("没有数据导出权限", 403)
    references = (job.result or {}).get("inputRefs")
    if not isinstance(references, list):
        raise ComputeError("历史导出缺少来源凭据，请按当前授权重新导出", 409)
    for item in references:
        if not isinstance(item, dict):
            raise ComputeError("导出来源凭据无效", 409)
        validate_item(
            {**item, "layerType": "raster" if "datasetId" in item else "vector"}, user
        )
