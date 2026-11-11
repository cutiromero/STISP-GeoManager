from __future__ import annotations

import json
import logging
import sqlite3

from django.core.exceptions import RequestDataTooBig, ValidationError
from django.core import signing
from django.db import DatabaseError, transaction
from django.db.models import F
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from apps.audit.service import log_operation
from apps.catalog.models import DataResource, MapLayer
from apps.catalog.permissions import user_can_access
from apps.catalog.resource_references import resource_reference_reasons
from apps.catalog.resource_history_delete import (
    detach_history,
    history_snapshot,
    issue_confirmation,
    read_confirmation,
)
from apps.catalog.resource_storage_delete import ResourceStorageDeletion
from apps.core.api import api_login_required
from apps.core.permissions import feature_denied_response, has_feature_perm
from apps.core.storage import StoragePathError
from apps.projects.context import selected_project_id

logger = logging.getLogger(__name__)


def delete_resource(
    request,
    resource_id: int,
    *,
    confirmed_snapshot=None,
    duplicate_resource_id=None,
    deletion_guard=None,
) -> dict:
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
            if deletion_guard is not None and not deletion_guard(resource):
                return {
                    **result,
                    "status": "blocked",
                    "detail": "该数据仍有其他引用或无权清理，已保留",
                }
            duplicate_proof = None
            if duplicate_resource_id is not None:
                from .resource_duplicates import verify_duplicate

                if confirmed_snapshot is None:
                    return {
                        **result,
                        "status": "blocked",
                        "detail": "原始重复资料需要完整历史预检查凭据",
                    }
                duplicate_proof = verify_duplicate(
                    resource, duplicate_resource_id, request.user
                )
            reasons = resource_reference_reasons(
                resource,
                allow_history=confirmed_snapshot is not None,
                include_original=duplicate_proof is not None,
            )
            if reasons:
                result.update(
                    status="blocked",
                    detail="暂不能删除：" + "；".join(reasons) + "。请先解除对应引用。",
                )
                return result
            receipt = None
            if confirmed_snapshot is not None:
                digest, history = history_snapshot(
                    resource, include_original=duplicate_proof is not None
                )
                if digest != confirmed_snapshot:
                    result.update(
                        status="blocked",
                        detail="资源或历史引用已变化，请重新检查删除范围并确认。",
                    )
                    return result
                if resource.is_compute_result or duplicate_proof is not None:
                    receipt = detach_history(
                        resource, request.user, history, duplicate_proof=duplicate_proof
                    )
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
                    storage.detail
                    + (
                        "；历史引用已留存删除凭据："
                        + json.dumps(receipt, ensure_ascii=False)
                        if receipt
                        else ""
                    ),
                    request,
                    target_type="data_resource",
                    target_id=resource_id,
                    target_code=resource.code,
                    target_name=result["name"],
                )
            transaction.on_commit(storage.finalize)
        result.update(
            status="deleted",
            detail=storage.detail
            + ("；保留历史任务及名称、来源和删除记录" if receipt else ""),
        )
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
def preview_resource_deletion(request):
    payload, error = _deletion_payload(request, preview=True)
    if error is not None:
        return error
    ids = list(dict.fromkeys(payload["resourceIds"]))
    items, snapshots = [], {}
    for resource_id in ids:
        item = {
            "resourceId": resource_id,
            "name": None,
            "status": "not_found",
            "detail": "数据资源不存在或当前项目无权访问",
            "historyReferenceCount": 0,
        }
        resource = DataResource.objects.filter(
            pk=resource_id, project_tag_id=selected_project_id()
        ).first()
        if resource is not None and user_can_access(resource, request.user):
            item["name"] = resource.name
            digest, history = history_snapshot(resource)
            count = sum(len(history[key]) for key in ("inputs", "imports", "workflows"))
            item["historyReferenceCount"] = count
            reasons = resource_reference_reasons(resource, allow_history=True)
            if not reasons:
                snapshots[str(resource_id)] = digest
            item.update(
                status="blocked"
                if reasons
                else "confirmation_required"
                if count
                else "deletable",
                detail="暂不能删除：" + "；".join(reasons) + "。"
                if reasons
                else "历史任务或MH-workflow引用了该计算结果。确认后删除目录数据，保留名称、来源及删除记录；相关历史步骤将无法再次使用此数据。"
                if count
                else "将删除资源记录及平台管理的文件。",
            )
        items.append(item)
    return JsonResponse(
        {
            "items": items,
            "confirmationToken": issue_confirmation(request, ids, snapshots),
        }
    )


def _deletion_payload(request, *, preview=False):
    if not has_feature_perm(request.user, "catalog.delete_dataresource"):
        return None, feature_denied_response(request.user)
    if not request.headers.get("X-Project-Id"):
        return None, JsonResponse({"detail": "请显式选择要管理的项目"}, status=400)
    try:
        body = request.body
    except RequestDataTooBig:
        return None, JsonResponse({"detail": "删除请求过大"}, status=400)
    if len(body) > 16 * 1024:
        return None, JsonResponse({"detail": "删除请求过大"}, status=400)
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None, JsonResponse({"detail": "请求必须是有效JSON"}, status=400)
    required = {"resourceIds"} if preview else {"resourceIds", "confirmed"}
    allowed = required if preview else required | {"historyConfirmationToken"}
    if not isinstance(payload, dict) or not required <= set(payload) <= allowed:
        return None, JsonResponse({"detail": "删除请求字段无效"}, status=400)
    if not preview and payload["confirmed"] is not True:
        return None, JsonResponse({"detail": "请先确认永久删除"}, status=400)
    token = payload.get("historyConfirmationToken", "")
    if not isinstance(token, str) or len(token) > 12000:
        return None, JsonResponse({"detail": "删除确认凭据无效"}, status=400)
    ids = payload["resourceIds"]
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 100
        or any(type(value) is not int or value <= 0 for value in ids)
    ):
        return None, JsonResponse(
            {"detail": "resourceIds 须为1至100个正整数"}, status=400
        )
    return payload, None


@require_POST
@api_login_required
def bulk_delete_resources(request):
    payload, error = _deletion_payload(request)
    if error is not None:
        return error
    ids = list(dict.fromkeys(payload["resourceIds"]))
    try:
        snapshots = read_confirmation(
            request, ids, payload.get("historyConfirmationToken", "")
        )
    except signing.BadSignature:
        return JsonResponse(
            {"detail": "删除确认已失效或选择已变化，请重新预览并确认。"}, status=409
        )
    items = []
    for value in ids:
        if payload.get("historyConfirmationToken") and str(value) not in snapshots:
            resource = DataResource.objects.filter(
                pk=value, project_tag_id=selected_project_id()
            ).first()
            accessible = resource is not None and user_can_access(
                resource, request.user
            )
            items.append(
                {
                    "resourceId": value,
                    "name": resource.name if accessible else None,
                    "status": "blocked" if accessible else "not_found",
                    "detail": "预览时未列入可清理范围，请重新检查并确认。"
                    if accessible
                    else "数据资源不存在或当前项目无权访问",
                }
            )
        else:
            items.append(
                delete_resource(
                    request, value, confirmed_snapshot=snapshots.get(str(value))
                )
            )
    deleted = [item["resourceId"] for item in items if item["status"] == "deleted"]
    return JsonResponse(
        {
            "items": items,
            "deletedIds": deleted,
            "deletedCount": len(deleted),
            "failedCount": len(items) - len(deleted),
        }
    )
