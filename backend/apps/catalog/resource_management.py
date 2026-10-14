from __future__ import annotations

import json
import logging
import sqlite3

from django.core.exceptions import RequestDataTooBig, ValidationError
from django.db import DatabaseError, transaction
from django.db.models import F
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from apps.audit.service import log_operation
from apps.catalog.models import DataResource, MapLayer
from apps.catalog.permissions import user_can_access
from apps.catalog.resource_references import resource_reference_reasons
from apps.catalog.resource_storage_delete import ResourceStorageDeletion
from apps.core.api import api_login_required
from apps.core.permissions import feature_denied_response, has_feature_perm
from apps.core.storage import StoragePathError
from apps.projects.context import selected_project_id

logger = logging.getLogger(__name__)


def delete_resource(request, resource_id: int) -> dict:
    """One guarded deletion shared by the catalog and existing admin controls."""
    result = {
        "resourceId": resource_id,
        "name": None,
        "status": "not_found",
        "detail": "数据资源不存在或当前项目无权访问",
    }
    storage = None
    try:
        # Own the commit boundary: nested application transactions cannot safely
        # finalize physical storage. TestCase's transaction is exempt by Django.
        with transaction.atomic(durable=True):
            DataResource.objects.filter(
                pk=resource_id, project_tag_id=selected_project_id()
            ).update(updated_at=F("updated_at"))
            resource = (
                DataResource.objects.select_for_update()
                .filter(pk=resource_id, project_tag_id=selected_project_id())
                .first()
            )
            if resource is None or not user_can_access(resource, request.user):
                return result
            result["name"] = resource.name
            reasons = resource_reference_reasons(resource)
            if reasons:
                result.update(
                    status="blocked",
                    detail="暂不能删除：" + "；".join(reasons) + "。请先解除对应引用。",
                )
                return result
            storage = ResourceStorageDeletion(resource)
            with storage:
                # Remove only resource-owned derived records; saved references
                # have already been checked and PROTECT is still enforced by ORM.
                resource.raster_datasets.all().delete()
                MapLayer.objects.filter(data_resource=resource).delete()
                resource.source_datasets.all().delete()
                resource.delete()
                log_operation(
                    request.user,
                    "数据管理",
                    "删除存量数据",
                    "success",
                    storage.detail,
                    request,
                    target_type="data_resource",
                    target_id=resource_id,
                    target_code=resource.code,
                    target_name=result["name"],
                )
            transaction.on_commit(storage.finalize)
        result.update(status="deleted", detail=storage.detail)
    except ProtectedError:
        if storage is not None:
            storage.close()
        result.update(
            status="blocked", detail="该数据仍被计算任务或其他记录引用，请先解除引用。"
        )
    except StoragePathError as exc:
        if storage is not None:
            storage.close()
        result.update(status="blocked", detail=f"未删除：{exc}")
    except (OSError, DatabaseError, sqlite3.Error, ValidationError, RuntimeError):
        if storage is not None:
            storage.restore_staged_files()
            storage.close()
        logger.exception(
            "Catalog resource deletion failed for resource %s", resource_id
        )
        result.update(
            status="failed", detail="删除失败，存储文件或数据库暂不可用，请稍后重试。"
        )
    finally:
        if storage is not None and storage.recovery_failed:
            result.update(
                status="failed",
                detail="删除失败，原文件仍在隔离目录且恢复未完成，请联系管理员处理。",
            )
    return result


@require_POST
@api_login_required
def bulk_delete_resources(request):
    if not has_feature_perm(request.user, "catalog.delete_dataresource"):
        return feature_denied_response(request.user)
    if not request.headers.get("X-Project-Id"):
        return JsonResponse({"detail": "请显式选择要管理的项目"}, status=400)
    try:
        body = request.body
    except RequestDataTooBig:
        return JsonResponse({"detail": "删除请求过大"}, status=400)
    if len(body) > 16 * 1024:
        return JsonResponse({"detail": "删除请求过大"}, status=400)
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"detail": "请求必须是有效JSON"}, status=400)
    if not isinstance(payload, dict) or set(payload) != {"resourceIds", "confirmed"}:
        return JsonResponse(
            {"detail": "请求仅接受 resourceIds 与 confirmed"}, status=400
        )
    if payload["confirmed"] is not True:
        return JsonResponse({"detail": "请先确认永久删除"}, status=400)
    ids = payload["resourceIds"]
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 100
        or any(type(value) is not int or value <= 0 for value in ids)
    ):
        return JsonResponse({"detail": "resourceIds 须为1至100个正整数"}, status=400)
    items = [delete_resource(request, value) for value in dict.fromkeys(ids)]
    deleted = [item["resourceId"] for item in items if item["status"] == "deleted"]
    return JsonResponse(
        {
            "items": items,
            "deletedIds": deleted,
            "deletedCount": len(deleted),
            "failedCount": len(items) - len(deleted),
        }
    )
