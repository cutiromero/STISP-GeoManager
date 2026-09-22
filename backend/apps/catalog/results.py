from __future__ import annotations

import json
import logging
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any

from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from PIL import Image, UnidentifiedImageError

from apps.audit.service import log_operation
from apps.catalog.models import ResultArtifact
from apps.catalog.permissions import (
    project_access_filter,
    user_has_full_data_access,
)
from apps.catalog.taxonomy import (
    TaxonomyError,
    category_codes_for_filter,
    resolve_data_category,
    serialize_category_path,
)
from apps.core.api import api_login_required
from apps.core.initialization import GUEST_GROUP_NAME, SUPERADMIN_GROUP_NAME
from apps.core.permissions import feature_denied_response, has_feature_perm
from apps.core.principal_visibility import (
    selectable_access_groups_for,
    user_is_visible_to,
)
from apps.core.runtime_config import RuntimeConfigError, runtime_upload_max_mb
from apps.core.storage import app_path

ALLOWED_RESULT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".csv", ".xlsx"}
PREVIEWABLE_RESULT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}

TRUSTED_RESULT_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

logger = logging.getLogger(__name__)


@require_http_methods(["GET", "POST"])
@api_login_required
def result_artifacts(request):
    if request.method == "POST":
        return _create_result_artifact(request)
    if not has_feature_perm(request.user, "catalog.view_resultartifact"):
        return feature_denied_response(request.user)

    queryset = _result_queryset(request.user)
    query = str(request.GET.get("q", "")).strip()
    source_type = str(request.GET.get("sourceType", "")).strip()
    result_type = str(request.GET.get("resultType", "")).strip()
    category_code = str(request.GET.get("categoryCode", "")).strip()
    if query:
        queryset = queryset.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(provider__icontains=query)
            | Q(file_name__icontains=query)
        )
    if source_type:
        if source_type not in ResultArtifact.SourceType.values:
            return JsonResponse({"detail": "成果来源类型无效"}, status=400)
        queryset = queryset.filter(source_type=source_type)
    if result_type:
        if result_type not in ResultArtifact.ResultType.values:
            return JsonResponse({"detail": "成果类型无效"}, status=400)
        queryset = queryset.filter(result_type=result_type)
    if category_code:
        try:
            category_codes = category_codes_for_filter(category_code)
        except TaxonomyError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        queryset = queryset.filter(category__code__in=category_codes)
    return JsonResponse(
        {
            "items": [_serialize_result(item, request.user) for item in queryset],
            "availableAccessGroups": _available_access_groups(request.user),
        }
    )


def _create_result_artifact(request):
    required_permissions = (
        "catalog.view_resultartifact",
        "catalog.add_resultartifact",
        "catalog.publish_resultartifact",
    )
    if not all(
        has_feature_perm(request.user, permission)
        for permission in required_permissions
    ):
        return feature_denied_response(request.user)
    upload = request.FILES.get("file")
    if upload is None:
        return JsonResponse({"detail": "请选择成果文件"}, status=400)
    payload = _multipart_json_payload(request)
    if isinstance(payload, JsonResponse):
        return payload

    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    provider = str(payload.get("provider") or "").strip()
    source_type = str(payload.get("sourceType") or "").strip()
    result_type = str(payload.get("resultType") or "").strip()
    if not name or len(name) > 160:
        return JsonResponse(
            {"detail": "成果名称不能为空且不能超过 160 个字符"}, status=400
        )
    if len(description) > 4000:
        return JsonResponse({"detail": "成果说明不能超过 4000 个字符"}, status=400)
    if len(provider) > 200:
        return JsonResponse({"detail": "提供单位不能超过 200 个字符"}, status=400)
    if source_type not in ResultArtifact.SourceType.values:
        return JsonResponse({"detail": "请选择有效的成果来源"}, status=400)
    if result_type not in ResultArtifact.ResultType.values:
        return JsonResponse({"detail": "请选择有效的成果类型"}, status=400)
    if "publish" in payload and payload.get("publish") is not True:
        return JsonResponse({"detail": "成果导入必须直接发布"}, status=400)

    try:
        category = resolve_data_category(str(payload.get("categoryCode") or ""))
    except TaxonomyError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    group_ids = _positive_integer_list(payload.get("accessGroupIds", []))
    if isinstance(group_ids, JsonResponse):
        return group_ids
    selectable_ids = set(
        selectable_access_groups_for(
            Group.objects.filter(id__in=group_ids).only("id", "name"), request.user
        ).values_list("id", flat=True)
    )
    if selectable_ids != set(group_ids):
        return JsonResponse({"detail": "包含不存在或不可选择的访问角色"}, status=400)

    original_name = _safe_result_filename(upload.name)
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_RESULT_EXTENSIONS:
        return JsonResponse(
            {"detail": "成果文件仅支持 PNG、JPG、PDF、CSV 或 XLSX"}, status=400
        )
    try:
        max_size_bytes = runtime_upload_max_mb() * 1024 * 1024
    except RuntimeConfigError as exc:
        return JsonResponse({"detail": str(exc)}, status=500)
    if upload.size > max_size_bytes:
        return JsonResponse({"detail": "成果文件超过平台上传大小限制"}, status=400)
    try:
        trusted_mime_type = _validate_result_upload(upload, extension)
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    artifact_key = uuid.uuid4().hex
    relative_path = f"exports/results/{artifact_key}/{original_name}"
    destination = app_path(*relative_path.split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as target:
            for chunk in upload.chunks():
                target.write(chunk)
        with transaction.atomic():
            now = timezone.now()
            artifact = ResultArtifact.objects.create(
                owner=request.user,
                name=name,
                description=description,
                source_type=source_type,
                result_type=result_type,
                status=ResultArtifact.Status.PUBLISHED,
                category=category,
                provider=provider,
                file_path=relative_path,
                file_name=original_name,
                mime_type=trusted_mime_type,
                size_bytes=upload.size,
                published_by=request.user,
                published_at=now,
            )
            artifact.access_groups.set(group_ids)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    log_operation(
        request.user,
        "成果展示",
        "导入并发布成果",
        "success",
        artifact.name,
        request,
        target_type="result_artifact",
        target_id=artifact.id,
        target_name=artifact.name,
    )
    artifact = _result_queryset(request.user).get(pk=artifact.id)
    return JsonResponse(_serialize_result(artifact, request.user), status=201)


@require_http_methods(["GET", "POST"])
@api_login_required
def result_artifact_detail(request, result_id: int):
    artifact = _result_for_user(request.user, result_id)
    if artifact is None:
        return JsonResponse({"detail": "成果不存在"}, status=404)
    if request.method == "GET":
        if not has_feature_perm(request.user, "catalog.view_resultartifact"):
            return feature_denied_response(request.user)
        return JsonResponse(_serialize_result(artifact, request.user))

    if not _user_can_manage_result(artifact, request.user):
        return JsonResponse({"detail": "成果不存在"}, status=404)
    payload = _json_payload(request)
    if isinstance(payload, JsonResponse):
        return payload
    action = str(payload.get("action") or "").strip()
    if action == "publish":
        if not has_feature_perm(request.user, "catalog.publish_resultartifact"):
            return feature_denied_response(request.user)
        group_ids = _positive_integer_list(payload.get("accessGroupIds", []))
        if isinstance(group_ids, JsonResponse):
            return group_ids
        group_error = _validate_access_groups(group_ids, request.user)
        if group_error:
            return JsonResponse({"detail": group_error}, status=400)
        with transaction.atomic():
            artifact.status = ResultArtifact.Status.PUBLISHED
            artifact.published_by = request.user
            artifact.published_at = timezone.now()
            artifact.save(
                update_fields=[
                    "status",
                    "published_by",
                    "published_at",
                    "updated_at",
                ]
            )
            artifact.access_groups.set(group_ids)
        operation = "发布成果文件"
    elif action == "unpublish":
        if not has_feature_perm(request.user, "catalog.publish_resultartifact"):
            return feature_denied_response(request.user)
        if artifact.status != ResultArtifact.Status.PUBLISHED:
            return JsonResponse({"detail": "成果当前未发布"}, status=400)
        artifact.status = ResultArtifact.Status.DRAFT
        artifact.save(update_fields=["status", "updated_at"])
        operation = "下架成果文件"
    elif action == "delete":
        if not has_feature_perm(request.user, "catalog.delete_resultartifact"):
            return feature_denied_response(request.user)
        artifact_id = artifact.id
        artifact_name = artifact.name
        relative_path = artifact.file_path
        with transaction.atomic():
            artifact.delete()
            log_operation(
                request.user,
                "成果管理",
                "删除成果文件",
                "success",
                artifact_name,
                request,
                target_type="result_artifact",
                target_id=artifact_id,
                target_code="deleted",
                target_name=artifact_name,
            )
        normalized_path = relative_path.replace("\\", "/")
        if normalized_path.startswith(
            "exports/results/"
        ) and ".." not in normalized_path.split("/"):
            try:
                app_path(*normalized_path.split("/")).unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    "Failed to delete result artifact file: %s", relative_path
                )
        else:
            logger.warning(
                "Skipped unsafe result artifact path during deletion: %s",
                relative_path,
            )
        return JsonResponse(
            {
                "deleted": True,
                "id": artifact_id,
                "detail": "成果文件已删除",
            }
        )
    else:
        return JsonResponse(
            {"detail": "action 仅支持 publish、unpublish 或 delete"}, status=400
        )

    log_operation(
        request.user,
        "成果管理",
        operation,
        "success",
        artifact.name,
        request,
        target_type="result_artifact",
        target_id=artifact.id,
        target_code=artifact.status,
        target_name=artifact.name,
    )
    artifact = _result_queryset(request.user).get(pk=artifact.id)
    return JsonResponse(_serialize_result(artifact, request.user))


@require_GET
@api_login_required
def result_artifact_file(request, result_id: int):
    if not has_feature_perm(request.user, "catalog.view_resultartifact"):
        return feature_denied_response(request.user)
    artifact = _result_queryset(request.user).filter(pk=result_id).first()
    if artifact is None:
        return JsonResponse({"detail": "成果不存在"}, status=404)
    variant = str(request.GET.get("variant", "artifact")).strip()
    if variant not in {"artifact", "preview"}:
        return JsonResponse(
            {"detail": "variant 仅支持 artifact 或 preview"}, status=400
        )
    extension = Path(artifact.file_name).suffix.lower()
    if variant == "preview" and extension not in PREVIEWABLE_RESULT_EXTENSIONS:
        return JsonResponse({"detail": "该成果格式不支持在线预览"}, status=400)
    if variant == "artifact" and not has_feature_perm(
        request.user, "catalog.download_resultartifact"
    ):
        return feature_denied_response(request.user)
    path = app_path(*artifact.file_path.split("/"))
    if not path.is_file():
        return JsonResponse({"detail": "成果文件不存在"}, status=404)
    response = FileResponse(
        path.open("rb"),
        as_attachment=variant == "artifact",
        filename=artifact.file_name,
        content_type=TRUSTED_RESULT_MIME_TYPES.get(extension)
        or "application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    if variant == "preview":
        response["X-Frame-Options"] = "SAMEORIGIN"
        response["Content-Security-Policy"] = (
            "sandbox; default-src 'none'; img-src 'self' data:; "
            "style-src 'unsafe-inline'"
        )
        response["Referrer-Policy"] = "no-referrer"
    return response


def _validate_result_upload(upload, extension: str) -> str:
    """Validate the actual file structure and return a server-owned MIME type."""

    try:
        upload.seek(0)
        if extension in {".png", ".jpg", ".jpeg"}:
            try:
                with Image.open(upload) as image:
                    expected_format = "PNG" if extension == ".png" else "JPEG"
                    if image.format != expected_format:
                        raise ValueError("成果文件扩展名与实际图片格式不一致")
                    image.verify()
            except (UnidentifiedImageError, OSError, SyntaxError) as exc:
                raise ValueError("成果图片内容无效或已损坏") from exc
        elif extension == ".pdf":
            header = upload.read(8)
            upload.seek(max(int(upload.size) - 2048, 0))
            trailer = upload.read(2048)
            if not header.startswith(b"%PDF-") or b"%%EOF" not in trailer:
                raise ValueError("成果 PDF 内容无效或已损坏")
        elif extension == ".csv":
            sample = upload.read(min(int(upload.size), 1024 * 1024))
            if not sample or b"\x00" in sample:
                raise ValueError("成果 CSV 内容无效或已损坏")
            try:
                sample.decode("utf-8-sig")
            except UnicodeDecodeError:
                try:
                    sample.decode("gb18030")
                except UnicodeDecodeError as exc:
                    raise ValueError(
                        "成果 CSV 编码无效，仅支持 UTF-8 或 GB18030"
                    ) from exc
        elif extension == ".xlsx":
            if not zipfile.is_zipfile(upload):
                raise ValueError("成果 XLSX 内容无效或已损坏")
            upload.seek(0)
            try:
                with zipfile.ZipFile(upload) as workbook:
                    names = set(workbook.namelist())
                    if not {"[Content_Types].xml", "xl/workbook.xml"}.issubset(names):
                        raise ValueError("成果 XLSX 缺少必要的工作簿结构")
                    infos = workbook.infolist()
                    total_uncompressed = sum(info.file_size for info in infos)
                    if len(infos) > 10000 or total_uncompressed > max(
                        1024 * 1024 * 1024, int(upload.size) * 200
                    ):
                        raise ValueError("成果 XLSX 解压内容超过安全限制")
            except (zipfile.BadZipFile, OSError) as exc:
                raise ValueError("成果 XLSX 内容无效或已损坏") from exc
        else:
            raise ValueError("成果文件格式不受支持")
    finally:
        upload.seek(0)
    return TRUSTED_RESULT_MIME_TYPES[extension]


def _result_queryset(user):
    queryset = (
        ResultArtifact.objects.select_related("owner", "category", "published_by")
        .prefetch_related("access_groups")
        .all()
    )
    queryset = queryset.filter(project_access_filter(user))
    if user_has_full_data_access(user):
        return queryset
    return queryset.filter(
        Q(owner_id=getattr(user, "id", None))
        | Q(status=ResultArtifact.Status.PUBLISHED)
    ).distinct()


def _result_for_user(user, result_id: int) -> ResultArtifact | None:
    return _result_queryset(user).filter(pk=result_id).first()


def _user_can_manage_result(artifact: ResultArtifact, user) -> bool:
    return bool(user_has_full_data_access(user) or artifact.owner_id == user.id)


def _serialize_result(artifact: ResultArtifact, request_user) -> dict[str, Any]:
    extension = Path(artifact.file_name).suffix.lower().lstrip(".")
    base = f"/api/catalog/results/{artifact.id}/file/"
    owner = artifact.owner if user_is_visible_to(request_user, artifact.owner) else None
    return {
        "id": artifact.id,
        "projectTagId": artifact.project_tag_id,
        "name": artifact.name,
        "description": artifact.description,
        "sourceType": artifact.source_type,
        "resultType": artifact.result_type,
        "status": artifact.status,
        "category": _serialize_dictionary_item(artifact.category),
        "categoryPath": serialize_category_path(artifact.category),
        "provider": artifact.provider,
        "fileName": artifact.file_name,
        "fileFormat": extension,
        "sizeBytes": artifact.size_bytes,
        "previewUrl": f"{base}?variant=preview&projectTagId={artifact.project_tag_id}",
        "downloadUrl": f"{base}?variant=artifact&projectTagId={artifact.project_tag_id}",
        "owner": _serialize_user(owner),
        "accessGroups": [
            _serialize_group(group)
            for group in selectable_access_groups_for(
                artifact.access_groups.all(), request_user
            )
        ],
        "canPreview": has_feature_perm(request_user, "catalog.view_resultartifact")
        and extension in {item.lstrip(".") for item in PREVIEWABLE_RESULT_EXTENSIONS},
        "canDownload": has_feature_perm(
            request_user, "catalog.download_resultartifact"
        ),
        "canPublish": _user_can_manage_result(artifact, request_user)
        and has_feature_perm(request_user, "catalog.publish_resultartifact"),
        "canUnpublish": artifact.status == ResultArtifact.Status.PUBLISHED
        and _user_can_manage_result(artifact, request_user)
        and has_feature_perm(request_user, "catalog.publish_resultartifact"),
        "canDelete": _user_can_manage_result(artifact, request_user)
        and has_feature_perm(request_user, "catalog.delete_resultartifact"),
        "publishedAt": (
            artifact.published_at.isoformat() if artifact.published_at else None
        ),
        "publishedBy": (
            _serialize_user(artifact.published_by) if artifact.published_by else None
        ),
        "createdAt": artifact.created_at.isoformat(),
        "updatedAt": artifact.updated_at.isoformat(),
    }


def _multipart_json_payload(request) -> dict[str, Any] | JsonResponse:
    raw_payload = request.POST.get("payload")
    if not raw_payload:
        return JsonResponse({"detail": "缺少成果登记参数"}, status=400)
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "成果登记参数不是有效 JSON"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "成果登记参数必须是 JSON 对象"}, status=400)
    return payload


def _json_payload(request) -> dict[str, Any] | JsonResponse:
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "请求体不是有效 JSON"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "请求体必须是 JSON 对象"}, status=400)
    return payload


def _available_access_groups(user) -> list[dict[str, Any]]:
    return [
        _serialize_group(group)
        for group in selectable_access_groups_for(Group.objects.order_by("name"), user)
    ]


def _validate_access_groups(group_ids: list[int], user) -> str | None:
    selectable_ids = set(
        selectable_access_groups_for(
            Group.objects.filter(id__in=group_ids).only("id", "name"), user
        ).values_list("id", flat=True)
    )
    if selectable_ids != set(group_ids):
        return "包含不存在或不可选择的访问角色"
    return None


def _positive_integer_list(value: Any) -> list[int] | JsonResponse:
    if not isinstance(value, list) or any(
        not isinstance(item, int) or item <= 0 for item in value
    ):
        return JsonResponse({"detail": "访问角色 ID 必须是正整数数组"}, status=400)
    return sorted(set(value))


def _safe_result_filename(value: str) -> str:
    filename = Path(str(value or "result")).name.strip() or "result"
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename)
    stem = Path(filename).stem[:180].rstrip(". ") or "result"
    suffix = Path(filename).suffix[:16].lower()
    return f"{stem}{suffix}"


def _serialize_dictionary_item(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "type": item.dict_type,
        "code": item.code,
        "name": item.name,
        "parentId": item.parent_id,
        "selectable": item.is_selectable,
    }


def _serialize_user(user) -> dict[str, Any]:
    if user is None:
        return {"id": 0, "username": "", "displayName": "系统维护"}
    return {
        "id": user.id,
        "username": user.get_username(),
        "displayName": user.get_full_name() or user.get_username(),
    }


def _serialize_group(group: Group) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "isGuest": group.name == GUEST_GROUP_NAME,
        "isSuperadmin": group.name == SUPERADMIN_GROUP_NAME,
    }
