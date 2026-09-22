from __future__ import annotations

import copy
import hashlib
import io
import json
import logging
from pathlib import Path
from typing import Any

from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.http import FileResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from PIL import Image, UnidentifiedImageError

from apps.audit.service import log_operation
from apps.catalog.models import (
    DataResource,
    MapComposition,
    MapCompositionVersion,
    WorkspaceScene,
)
from apps.catalog.permissions import (
    project_access_filter,
    resource_access_filter,
    user_has_full_data_access,
)
from apps.core.api import api_login_required
from apps.core.initialization import (
    GUEST_GROUP_NAME,
    SUPERADMIN_GROUP_NAME,
    ensure_superadmin_defaults,
)
from apps.core.permissions import feature_denied_response, has_feature_perm
from apps.core.principal_visibility import (
    selectable_access_groups_for,
    user_is_visible_to,
)
from apps.core.storage import app_path

LAYOUT_MAX_BYTES = 512 * 1024
WORKSPACE_SNAPSHOT_MAX_BYTES = 1024 * 1024
MAP_COMPOSITION_IMAGE_MAX_MB = 128
MAP_COMPOSITION_IMAGE_MAX_BYTES = MAP_COMPOSITION_IMAGE_MAX_MB * 1024 * 1024
MAX_OUTPUT_SIDE = 8192
MAX_OUTPUT_PIXELS = 36_000_000

logger = logging.getLogger(__name__)


@require_http_methods(["GET", "POST"])
@api_login_required
def map_compositions(request):
    if request.method == "POST":
        return _create_map_composition(request)
    if not has_feature_perm(request.user, "catalog.view_mapcomposition"):
        return feature_denied_response(request.user)

    queryset = _composition_queryset(request.user)
    project_id = str(request.GET.get("projectId", "")).strip()
    if project_id:
        if not project_id.isdigit() or int(project_id) <= 0:
            return JsonResponse({"detail": "projectId 必须是正整数"}, status=400)
        queryset = queryset.filter(project_id=int(project_id))
    status = str(request.GET.get("status", "")).strip()
    visible_statuses = {
        MapComposition.Status.DRAFT,
        MapComposition.Status.COMPLETED,
        MapComposition.Status.PUBLISHED,
    }
    if status:
        if status not in visible_statuses:
            return JsonResponse(
                {"detail": "status 仅支持 draft、completed 或 published"},
                status=400,
            )
        queryset = queryset.filter(status=status)
    return JsonResponse(
        {
            "items": [_serialize_composition(item, request.user) for item in queryset],
            "availableAudienceGroups": _available_audience_groups(request.user),
        }
    )


def _create_map_composition(request):
    if not has_feature_perm(request.user, "catalog.add_mapcomposition"):
        return feature_denied_response(request.user)
    payload = _json_payload(request)
    if isinstance(payload, JsonResponse):
        return payload
    values = _composition_values(payload, partial=False)
    if isinstance(values, JsonResponse):
        return values
    project_id = values.pop("project_id")
    project_query = WorkspaceScene.objects.filter(
        pk=project_id,
        kind=WorkspaceScene.Kind.PROJECT,
        status=WorkspaceScene.Status.ACTIVE,
    )
    if not user_has_full_data_access(request.user):
        project_query = project_query.filter(owner=request.user)
    project = project_query.first()
    if project is None:
        return JsonResponse({"detail": "来源工程不存在或不是可用工程"}, status=404)
    try:
        composition = MapComposition.objects.create(
            owner=request.user,
            project=project,
            source_workspace_snapshot=project.snapshot or {},
            **values,
        )
    except IntegrityError:
        return JsonResponse({"detail": "该工程下已存在同名出图稿"}, status=409)
    log_operation(
        request.user,
        "专题制图",
        "新建出图稿",
        "success",
        composition.name,
        request,
        target_type="map_composition",
        target_id=composition.id,
        target_code="draft",
        target_name=composition.name,
    )
    return JsonResponse(
        _serialize_composition(_get_composition(composition.id), request.user),
        status=201,
    )


@require_http_methods(["GET", "POST"])
@api_login_required
def map_composition_detail(request, composition_id: int):
    composition = _composition_for_user(request.user, composition_id)
    if composition is None:
        return JsonResponse({"detail": "出图稿不存在"}, status=404)
    if request.method == "GET":
        if not has_feature_perm(request.user, "catalog.view_mapcomposition"):
            return feature_denied_response(request.user)
        return JsonResponse(_serialize_composition(composition, request.user))

    if not _user_can_manage(composition, request.user):
        return JsonResponse({"detail": "出图稿不存在"}, status=404)
    payload = _json_payload(request)
    if isinstance(payload, JsonResponse):
        return payload
    action = str(payload.get("action", "update")).strip() or "update"
    if action == "delete":
        if not has_feature_perm(request.user, "catalog.delete_mapcomposition"):
            return feature_denied_response(request.user)
        composition_id = composition.id
        composition_name = composition.name
        with transaction.atomic():
            locked = MapComposition.objects.select_for_update().get(pk=composition_id)
            export_paths = {
                path
                for paths in locked.versions.values_list(
                    "preview_path", "artifact_path"
                )
                for path in paths
                if path
            }
            # The published version belongs to this composition. Clear the
            # self-reference explicitly before cascading all version records.
            if locked.published_version_id is not None:
                locked.published_version = None
                locked.save(update_fields=["published_version"])
            log_operation(
                request.user,
                "专题制图",
                "删除出图稿",
                "success",
                composition_name,
                request,
                target_type="map_composition",
                target_id=composition_id,
                target_code="deleted",
                target_name=composition_name,
            )
            locked.delete()
        _delete_composition_export_files(composition_id, export_paths)
        return JsonResponse(
            {"deleted": True, "id": composition_id, "detail": "出图稿已删除"}
        )
    if action != "update":
        return JsonResponse({"detail": "action 仅支持 update 或 delete"}, status=400)
    if not has_feature_perm(request.user, "catalog.change_mapcomposition"):
        return feature_denied_response(request.user)
    values = _composition_values(payload, partial=True)
    if isinstance(values, JsonResponse):
        return values
    if not values:
        return JsonResponse({"detail": "没有可更新的出图稿字段"}, status=400)
    try:
        with transaction.atomic():
            composition = MapComposition.objects.select_for_update().get(
                pk=composition.pk
            )
            expected = payload.get("expectedUpdatedAt")
            if expected is not None and expected != composition.updated_at.isoformat():
                return JsonResponse(
                    {"detail": "版式已被其他会话更新，请重新打开后再编辑"}, status=409
                )
            for key, value in values.items():
                setattr(composition, key, value)
            composition.save(update_fields=[*values.keys(), "updated_at"])
    except IntegrityError:
        return JsonResponse({"detail": "该工程下已存在同名出图稿"}, status=409)
    log_operation(
        request.user,
        "专题制图",
        "更新出图稿",
        "success",
        composition.name,
        request,
        target_type="map_composition",
        target_id=composition.id,
        target_code=composition.status,
        target_name=composition.name,
    )
    return JsonResponse(
        _serialize_composition(_get_composition(composition.id), request.user)
    )


@require_POST
@api_login_required
def publish_map_composition(request, composition_id: int):
    if not has_feature_perm(request.user, "catalog.publish_mapcomposition"):
        return feature_denied_response(request.user)
    composition = _manageable_composition(request.user, composition_id)
    if composition is None:
        return JsonResponse({"detail": "出图稿不存在"}, status=404)
    payload = _json_payload(request)
    if isinstance(payload, JsonResponse):
        return payload
    version_number = payload.get("versionNumber")
    if not isinstance(version_number, int) or version_number <= 0:
        return JsonResponse({"detail": "versionNumber 必须是正整数"}, status=400)
    version = composition.versions.filter(version_number=version_number).first()
    if version is None:
        return JsonResponse({"detail": "专题成果版本不存在"}, status=404)
    group_ids = _group_ids(payload.get("audienceGroupIds", []), required=False)
    if isinstance(group_ids, JsonResponse):
        return group_ids
    group_error = _validate_selectable_groups(group_ids, request.user)
    if group_error:
        return JsonResponse({"detail": group_error}, status=400)
    with transaction.atomic():
        composition.published_version = version
        composition.published_by = request.user
        composition.published_at = timezone.now()
        composition.status = MapComposition.Status.PUBLISHED
        composition.save(
            update_fields=[
                "published_version",
                "published_by",
                "published_at",
                "status",
                "updated_at",
            ]
        )
        composition.audience_groups.set(group_ids)
    log_operation(
        request.user,
        "专题制图",
        "发布专题图",
        "success",
        f"{composition.name} V{version.version_number}",
        request,
        target_type="map_composition",
        target_id=composition.id,
        target_code=f"published-v{version.version_number}",
        target_name=composition.name,
    )
    return JsonResponse(
        _serialize_composition(_get_composition(composition.id), request.user)
    )


@require_POST
@api_login_required
def unpublish_map_composition(request, composition_id: int):
    if not has_feature_perm(request.user, "catalog.publish_mapcomposition"):
        return feature_denied_response(request.user)
    composition = _manageable_composition(request.user, composition_id)
    if composition is None:
        return JsonResponse({"detail": "出图稿不存在"}, status=404)
    if composition.status != MapComposition.Status.PUBLISHED:
        return JsonResponse({"detail": "专题当前未发布"}, status=400)
    composition.status = (
        MapComposition.Status.COMPLETED
        if composition.versions.exists()
        else MapComposition.Status.DRAFT
    )
    composition.save(update_fields=["status", "updated_at"])
    log_operation(
        request.user,
        "专题制图",
        "下架专题图",
        "success",
        composition.name,
        request,
        target_type="map_composition",
        target_id=composition.id,
        target_code="unpublished",
        target_name=composition.name,
    )
    return JsonResponse(
        _serialize_composition(_get_composition(composition.id), request.user)
    )


@require_POST
@api_login_required
def create_map_composition_version(request, composition_id: int):
    if not has_feature_perm(request.user, "catalog.export_mapcomposition"):
        return feature_denied_response(request.user)
    composition = _manageable_composition(request.user, composition_id)
    if composition is None:
        return JsonResponse({"detail": "出图稿不存在"}, status=404)
    uploaded = request.FILES.get("image")
    if uploaded is None:
        return JsonResponse({"detail": "请上传 PNG 出图母图"}, status=400)
    if uploaded.size > MAP_COMPOSITION_IMAGE_MAX_BYTES:
        return JsonResponse(
            {"detail": f"出图母图不能超过 {MAP_COMPOSITION_IMAGE_MAX_MB} MB"},
            status=400,
        )
    try:
        payload = json.loads(request.POST.get("payload", "{}"))
    except json.JSONDecodeError:
        return JsonResponse({"detail": "成果版本参数不是有效 JSON"}, status=400)
    values = _version_values(payload)
    if isinstance(values, JsonResponse):
        return values
    try:
        image_bytes = uploaded.read()
        image = Image.open(io.BytesIO(image_bytes))
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError):
        return JsonResponse({"detail": "上传内容不是有效 PNG 图片"}, status=400)
    if image.format != "PNG":
        return JsonResponse({"detail": "出图母图必须使用 PNG 格式"}, status=400)
    width_px, height_px = image.size
    if (width_px, height_px) != (values["width_px"], values["height_px"]):
        return JsonResponse({"detail": "上传图片尺寸与成果参数不一致"}, status=400)
    if (
        width_px > MAX_OUTPUT_SIDE
        or height_px > MAX_OUTPUT_SIDE
        or width_px * height_px > MAX_OUTPUT_PIXELS
    ):
        return JsonResponse({"detail": "出图尺寸超过平台安全限制"}, status=400)
    try:
        image.load()
    except (Image.DecompressionBombError, OSError):
        return JsonResponse({"detail": "上传内容不是有效 PNG 图片"}, status=400)

    workspace_snapshot = values.pop("workspace_snapshot")
    resource_manifest = _resource_manifest(workspace_snapshot)
    snapshot_checksum = _snapshot_checksum(composition.layout, workspace_snapshot)
    snapshot_schema_version = _snapshot_schema_version(workspace_snapshot)
    with transaction.atomic():
        locked = MapComposition.objects.select_for_update().get(pk=composition.id)
        version_number = (
            locked.versions.aggregate(maximum=Max("version_number"))["maximum"] or 0
        ) + 1
        output_dir = app_path(
            "exports", "map-compositions", str(locked.id), f"v{version_number}"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        preview_relative = _relative_export_path(
            locked.id, version_number, "preview.png"
        )
        preview_path = app_path(*preview_relative.split("/"))
        image.save(preview_path, "PNG", dpi=(values["dpi"], values["dpi"]))
        artifact_relative, _ = _save_artifact(
            image,
            locked.id,
            version_number,
            values["format"],
            values["dpi"],
            preview_relative,
            preview_path,
        )
        version = MapCompositionVersion.objects.create(
            composition=locked,
            version_number=version_number,
            format=values["format"],
            dpi=values["dpi"],
            width_px=width_px,
            height_px=height_px,
            note=values["note"],
            preview_path=preview_relative,
            artifact_path=artifact_relative,
            layout_snapshot=locked.layout,
            workspace_snapshot=workspace_snapshot,
            snapshot_schema_version=snapshot_schema_version,
            snapshot_checksum=snapshot_checksum,
            resource_manifest=resource_manifest,
            created_by=request.user,
        )
        if locked.status != MapComposition.Status.PUBLISHED:
            locked.status = MapComposition.Status.COMPLETED
        locked.save(update_fields=["status", "updated_at"])
    log_operation(
        request.user,
        "专题制图",
        "生成专题成果",
        "success",
        f"{composition.name} V{version.version_number} {values['format'].upper()}",
        request,
        target_type="map_composition",
        target_id=composition.id,
        target_code=f"v{version.version_number}",
        target_name=composition.name,
    )
    return JsonResponse(_serialize_version(version), status=201)


@require_GET
@api_login_required
def map_composition_version_file(request, composition_id: int, version_number: int):
    if not has_feature_perm(request.user, "catalog.view_mapcomposition"):
        return feature_denied_response(request.user)
    composition = _composition_for_user(request.user, composition_id)
    if composition is None:
        return JsonResponse({"detail": "出图稿不存在"}, status=404)
    privileged = _user_can_manage(composition, request.user)
    if not privileged and composition.published_version_id is not None:
        version = (
            composition.published_version
            if composition.published_version.version_number == version_number
            else None
        )
    else:
        version = composition.versions.filter(version_number=version_number).first()
    if version is None:
        return JsonResponse({"detail": "专题成果版本不存在"}, status=404)
    variant = str(request.GET.get("variant", "artifact")).strip()
    if variant not in {"artifact", "preview"}:
        return JsonResponse(
            {"detail": "variant 仅支持 artifact 或 preview"}, status=400
        )
    if variant == "artifact" and not has_feature_perm(
        request.user, "catalog.export_mapcomposition"
    ):
        return feature_denied_response(request.user)
    relative_path = (
        version.preview_path if variant == "preview" else version.artifact_path
    )
    path = app_path(*relative_path.split("/"))
    if not path.is_file():
        return JsonResponse({"detail": "专题成果文件不存在"}, status=404)
    extension = "png" if variant == "preview" else version.format
    filename = f"{composition.name}_V{version.version_number}.{extension}"
    return FileResponse(
        path.open("rb"),
        as_attachment=variant == "artifact",
        filename=filename,
    )


@require_POST
@api_login_required
def restore_map_composition_project(request, composition_id: int):
    if not has_feature_perm(
        request.user, "catalog.restore_mapcomposition"
    ) or not has_feature_perm(request.user, "catalog.add_workspacescene"):
        return feature_denied_response(request.user)
    composition = _composition_for_user(request.user, composition_id)
    if composition is None:
        return JsonResponse({"detail": "出图稿不存在"}, status=404)
    payload = _json_payload(request, max_body_bytes=128 * 1024)
    if isinstance(payload, JsonResponse):
        return payload
    version_number = payload.get("versionNumber")
    if not isinstance(version_number, int) or version_number <= 0:
        return JsonResponse({"detail": "versionNumber 必须是正整数"}, status=400)
    privileged = _user_can_manage(composition, request.user)
    if privileged:
        version = composition.versions.filter(version_number=version_number).first()
    else:
        version = (
            composition.published_version
            if composition.published_version_id
            and composition.published_version.version_number == version_number
            else None
        )
    if version is None:
        return JsonResponse({"detail": "专题成果版本不存在"}, status=404)
    name = str(payload.get("name", "")).strip()
    if not name:
        return JsonResponse({"detail": "新工程名称不能为空"}, status=400)
    if len(name) > 160:
        return JsonResponse({"detail": "新工程名称不能超过 160 个字符"}, status=400)
    description = str(payload.get("description") or "").strip()
    if len(description) > 2000:
        return JsonResponse({"detail": "新工程说明不能超过 2000 个字符"}, status=400)
    policy = str(payload.get("unavailableResourcePolicy", "skip")).strip()
    if policy not in {"skip", "fail"}:
        return JsonResponse(
            {"detail": "unavailableResourcePolicy 仅支持 skip 或 fail"}, status=400
        )
    group_ids = _group_ids(payload.get("accessGroupIds", []), required=False)
    if isinstance(group_ids, JsonResponse):
        return group_ids
    group_error = _validate_selectable_groups(group_ids, request.user)
    if group_error:
        return JsonResponse({"detail": group_error}, status=400)
    snapshot, warnings = _workspace_snapshot_for_user(
        version.workspace_snapshot, request.user
    )
    if warnings and policy == "fail":
        return JsonResponse(
            {
                "detail": "专题版本包含当前用户不可访问或已失效的数据资源",
                "warnings": warnings,
            },
            status=400,
        )
    try:
        with transaction.atomic():
            project = WorkspaceScene.objects.create(
                owner=request.user,
                kind=WorkspaceScene.Kind.PROJECT,
                name=name,
                description=description,
                snapshot=snapshot,
            )
            _, superadmin_group = ensure_superadmin_defaults(
                create_account=False, attach_existing_superusers=False
            )
            project.access_groups.set(sorted({*group_ids, superadmin_group.id}))
    except IntegrityError:
        return JsonResponse({"detail": "同名工程已存在"}, status=409)
    log_operation(
        request.user,
        "专题制图",
        "还原专题版本为工程",
        "success",
        f"{composition.name} V{version.version_number} → {project.name}",
        request,
        target_type="workspace_scene",
        target_id=project.id,
        target_code="project",
        target_name=project.name,
    )
    project = (
        WorkspaceScene.objects.select_related("owner")
        .prefetch_related("access_groups")
        .get(pk=project.id)
    )
    return JsonResponse(
        {"project": _serialize_workspace(project, request.user), "warnings": warnings},
        status=201,
    )


def _composition_queryset(user):
    queryset = (
        MapComposition.objects.all()
        .select_related("owner", "project", "published_version", "published_by")
        .prefetch_related("versions", "audience_groups", "project__access_groups")
    )
    queryset = queryset.filter(project_access_filter(user))
    if user_has_full_data_access(user):
        return queryset
    return queryset.filter(
        Q(owner_id=getattr(user, "id", None))
        | Q(status=MapComposition.Status.PUBLISHED)
    ).distinct()


def _composition_for_user(user, composition_id: int) -> MapComposition | None:
    return _composition_queryset(user).filter(pk=composition_id).first()


def _manageable_composition(user, composition_id: int) -> MapComposition | None:
    queryset = (
        MapComposition.objects.all()
        .select_related("owner", "project", "published_version", "published_by")
        .prefetch_related("versions", "audience_groups", "project__access_groups")
        .filter(pk=composition_id)
    )
    if not user_has_full_data_access(user):
        queryset = queryset.filter(owner=user)
    return queryset.first()


def _get_composition(composition_id: int) -> MapComposition:
    return (
        MapComposition.objects.select_related(
            "owner", "project", "published_version", "published_by"
        )
        .prefetch_related("versions", "audience_groups", "project__access_groups")
        .get(pk=composition_id)
    )


def _user_can_manage(composition: MapComposition, user) -> bool:
    return bool(user_has_full_data_access(user) or composition.owner_id == user.id)


def _user_can_load_source_project(composition: MapComposition, user) -> bool:
    if not has_feature_perm(user, "catalog.view_workspacescene"):
        return False
    return WorkspaceScene.objects.filter(
        project_access_filter(user), pk=composition.project_id, status="active"
    ).exists()


def _composition_values(
    payload: dict[str, Any], *, partial: bool
) -> dict[str, Any] | JsonResponse:
    values: dict[str, Any] = {}
    if not partial or "projectId" in payload:
        project_id = payload.get("projectId")
        if not isinstance(project_id, int) or project_id <= 0:
            return JsonResponse({"detail": "projectId 必须是正整数"}, status=400)
        values["project_id"] = project_id
    if not partial or "name" in payload:
        name = str(payload.get("name", "")).strip()
        if not name:
            return JsonResponse({"detail": "专题图名称不能为空"}, status=400)
        if len(name) > 160:
            return JsonResponse({"detail": "专题图名称不能超过 160 个字符"}, status=400)
        values["name"] = name
    if "description" in payload:
        description = str(payload.get("description") or "").strip()
        if len(description) > 2000:
            return JsonResponse(
                {"detail": "专题图说明不能超过 2000 个字符"}, status=400
            )
        values["description"] = description
    elif not partial:
        values["description"] = ""
    if not partial or "layout" in payload:
        layout = payload.get("layout")
        layout_error = _validate_layout(layout)
        if layout_error:
            return JsonResponse({"detail": layout_error}, status=400)
        values["layout"] = layout
    return values


def _validate_layout(layout: Any) -> str | None:
    if not isinstance(layout, dict):
        return "layout 必须是 JSON 对象"
    encoded = json.dumps(layout, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    if len(encoded) > LAYOUT_MAX_BYTES:
        return "出图版式超过 512KB 限制"
    if _contains_embedded_data(layout, reject_images=True):
        return "出图版式不能包含原始 GeoJSON、图片 Data URL 或临时 Blob URL"
    return None


def _version_values(payload: Any) -> dict[str, Any] | JsonResponse:
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "成果版本参数必须是 JSON 对象"}, status=400)
    output_format = str(payload.get("format", "")).lower().strip()
    if output_format not in MapCompositionVersion.Format.values:
        return JsonResponse({"detail": "format 仅支持 png、jpg 或 pdf"}, status=400)
    dpi = payload.get("dpi")
    width_px = payload.get("widthPx")
    height_px = payload.get("heightPx")
    if not isinstance(dpi, int) or dpi < 72 or dpi > 600:
        return JsonResponse({"detail": "DPI 必须在 72 到 600 之间"}, status=400)
    if not isinstance(width_px, int) or not isinstance(height_px, int):
        return JsonResponse({"detail": "输出像素尺寸必须是整数"}, status=400)
    note = str(payload.get("note") or "").strip()
    if len(note) > 500:
        return JsonResponse({"detail": "版本说明不能超过 500 个字符"}, status=400)
    workspace_snapshot = payload.get("workspaceSnapshot")
    snapshot_error = _validate_workspace_snapshot(workspace_snapshot)
    if snapshot_error:
        return JsonResponse({"detail": snapshot_error}, status=400)
    return {
        "format": output_format,
        "dpi": dpi,
        "width_px": width_px,
        "height_px": height_px,
        "note": note,
        "workspace_snapshot": workspace_snapshot,
    }


def _validate_workspace_snapshot(snapshot: Any) -> str | None:
    if not isinstance(snapshot, dict):
        return "workspaceSnapshot 必须是 JSON 对象"
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    if len(encoded) > WORKSPACE_SNAPSHOT_MAX_BYTES:
        return "工程快照超过 1MB 限制"
    if _contains_embedded_data(snapshot, reject_images=False):
        return "工程快照不能包含原始 GeoJSON 要素集合"
    return None


def _contains_embedded_data(value: object, *, reject_images: bool) -> bool:
    if isinstance(value, dict):
        if "geojson" in value:
            return True
        if value.get("type") == "FeatureCollection" and isinstance(
            value.get("features"), list
        ):
            return True
        if isinstance(value.get("features"), list):
            return True
        return any(
            _contains_embedded_data(item, reject_images=reject_images)
            for item in value.values()
        )
    if isinstance(value, list):
        return any(
            _contains_embedded_data(item, reject_images=reject_images) for item in value
        )
    return bool(
        reject_images
        and isinstance(value, str)
        and value.lower().startswith(("data:image/", "blob:"))
    )


def _save_artifact(
    image: Image.Image,
    composition_id: int,
    version_number: int,
    output_format: str,
    dpi: int,
    preview_relative: str,
    preview_path: Path,
) -> tuple[str, Path]:
    if output_format == MapCompositionVersion.Format.PNG:
        return preview_relative, preview_path
    artifact_relative = _relative_export_path(
        composition_id, version_number, f"artifact.{output_format}"
    )
    artifact_path = app_path(*artifact_relative.split("/"))
    rgb = image.convert("RGB")
    if output_format == MapCompositionVersion.Format.JPG:
        rgb.save(artifact_path, "JPEG", quality=92, dpi=(dpi, dpi), optimize=True)
    else:
        rgb.save(artifact_path, "PDF", resolution=dpi)
    return artifact_relative, artifact_path


def _relative_export_path(
    composition_id: int, version_number: int, filename: str
) -> str:
    return f"exports/map-compositions/{composition_id}/v{version_number}/{filename}"


def _delete_composition_export_files(
    composition_id: int, relative_paths: set[str]
) -> None:
    expected_prefix = f"exports/map-compositions/{composition_id}/"
    for relative_path in relative_paths:
        normalized = relative_path.replace("\\", "/")
        if not normalized.startswith(expected_prefix) or ".." in normalized.split("/"):
            logger.warning(
                "Skipped unsafe map composition export path during deletion: %s",
                relative_path,
            )
            continue
        try:
            app_path(*normalized.split("/")).unlink(missing_ok=True)
        except OSError:
            logger.exception(
                "Failed to delete map composition export file: %s", relative_path
            )


def _serialize_composition(composition: MapComposition, request_user) -> dict[str, Any]:
    privileged = _user_can_manage(composition, request_user)
    all_versions = list(composition.versions.all())
    latest_version = all_versions[0] if all_versions else None
    published_version = composition.published_version
    versions = (
        all_versions
        if privileged
        else ([published_version] if published_version else [])
    )
    current_version = latest_version if privileged else published_version
    layout = (
        composition.layout
        if privileged
        else (published_version.layout_snapshot if published_version else {})
    )
    owner = (
        composition.owner
        if user_is_visible_to(request_user, composition.owner)
        else None
    )
    has_any_version = current_version is not None
    return {
        "id": composition.id,
        "projectTagId": composition.project_tag_id,
        "projectId": composition.project_id,
        "projectName": composition.project.name,
        "name": composition.name,
        "description": composition.description,
        "status": composition.status,
        "layout": layout,
        "owner": _serialize_user(owner),
        "audienceGroups": [
            _serialize_group(group)
            for group in selectable_access_groups_for(
                composition.audience_groups.all(), request_user
            )
        ],
        "currentVersion": _serialize_version(current_version)
        if current_version
        else None,
        "publishedVersion": _serialize_version(published_version)
        if published_version and composition.status == MapComposition.Status.PUBLISHED
        else None,
        "versions": [_serialize_version(version) for version in versions if version],
        "isOwner": composition.owner_id == request_user.id,
        "canPreview": has_any_version,
        "canDownload": bool(
            has_any_version
            and has_feature_perm(request_user, "catalog.export_mapcomposition")
        ),
        "canEditLayout": bool(
            privileged
            and has_feature_perm(request_user, "catalog.change_mapcomposition")
        ),
        "canPublish": bool(
            privileged
            and latest_version
            and has_feature_perm(request_user, "catalog.publish_mapcomposition")
        ),
        "canUnpublish": bool(
            privileged
            and composition.status == MapComposition.Status.PUBLISHED
            and has_feature_perm(request_user, "catalog.publish_mapcomposition")
        ),
        "canRestoreProject": bool(
            has_any_version
            and has_feature_perm(request_user, "catalog.restore_mapcomposition")
            and has_feature_perm(request_user, "catalog.add_workspacescene")
        ),
        "canLoadSourceProject": _user_can_load_source_project(
            composition, request_user
        ),
        "canDelete": bool(
            privileged
            and has_feature_perm(request_user, "catalog.delete_mapcomposition")
        ),
        "publishedAt": composition.published_at.isoformat()
        if composition.published_at
        else None,
        "publishedBy": _serialize_user(composition.published_by)
        if composition.published_by
        else None,
        "createdAt": composition.created_at.isoformat(),
        "updatedAt": composition.updated_at.isoformat(),
    }


def _serialize_version(version: MapCompositionVersion) -> dict[str, Any]:
    base = (
        f"/api/catalog/map-compositions/{version.composition_id}"
        f"/versions/{version.version_number}/file/"
    )
    return {
        "id": version.id,
        "compositionId": version.composition_id,
        "versionNumber": version.version_number,
        "format": version.format,
        "dpi": version.dpi,
        "widthPx": version.width_px,
        "heightPx": version.height_px,
        "note": version.note,
        "snapshotSchemaVersion": version.snapshot_schema_version,
        "snapshotChecksum": version.snapshot_checksum,
        "previewUrl": f"{base}?variant=preview&projectTagId={version.project_tag_id}",
        "downloadUrl": f"{base}?variant=artifact&projectTagId={version.project_tag_id}",
        "createdAt": version.created_at.isoformat(),
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


def _available_audience_groups(user) -> list[dict[str, Any]]:
    return [
        _serialize_group(group)
        for group in selectable_access_groups_for(Group.objects.order_by("name"), user)
    ]


def _group_ids(value: Any, *, required: bool) -> list[int] | JsonResponse:
    if value is None and not required:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, int) or item <= 0 for item in value
    ):
        return JsonResponse({"detail": "角色 ID 必须是正整数数组"}, status=400)
    group_ids = sorted(set(value))
    return group_ids


def _validate_selectable_groups(group_ids: list[int], user) -> str | None:
    selectable_ids = set(
        selectable_access_groups_for(
            Group.objects.filter(id__in=group_ids).only("id", "name"), user
        ).values_list("id", flat=True)
    )
    if selectable_ids != set(group_ids):
        return "包含不存在或不可选择的角色"
    return None


def _snapshot_checksum(layout: dict[str, Any], snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"layout": layout, "workspace": snapshot},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_schema_version(snapshot: dict[str, Any]) -> int:
    version = snapshot.get("version", 1)
    return version if isinstance(version, int) and version > 0 else 1


def _resource_manifest(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    resources: dict[int, dict[str, Any]] = {}
    groups = snapshot.get("groups")
    if not isinstance(groups, list):
        return []
    for group in groups:
        if not isinstance(group, dict):
            continue
        children = group.get("children")
        if not isinstance(children, list):
            continue
        for layer in children:
            if not isinstance(layer, dict):
                continue
            source = layer.get("sourceResource")
            if not isinstance(source, dict):
                continue
            resource_id = source.get("id")
            if isinstance(resource_id, int) and resource_id > 0:
                resources[resource_id] = {
                    "id": resource_id,
                    "name": str(source.get("name") or layer.get("name") or ""),
                    "dataType": str(
                        source.get("dataType") or layer.get("layerType") or ""
                    ),
                }
    return [resources[key] for key in sorted(resources)]


def _workspace_snapshot_for_user(
    snapshot: dict[str, Any], user
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result = copy.deepcopy(snapshot if isinstance(snapshot, dict) else {})
    groups = result.get("groups")
    if not isinstance(groups, list):
        return result, []
    referenced_ids = {
        item["id"]
        for item in _resource_manifest(result)
        if isinstance(item.get("id"), int)
    }
    accessible_ids = set(
        DataResource.objects.filter(id__in=referenced_ids)
        .filter(resource_access_filter(user))
        .values_list("id", flat=True)
    )
    warnings: list[dict[str, Any]] = []
    filtered_groups: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        next_group = copy.deepcopy(group)
        children = group.get("children")
        if not isinstance(children, list):
            next_group["children"] = []
            filtered_groups.append(next_group)
            continue
        next_children = []
        for layer in children:
            if not isinstance(layer, dict):
                continue
            source = layer.get("sourceResource")
            resource_id = source.get("id") if isinstance(source, dict) else None
            if (
                isinstance(resource_id, int)
                and resource_id > 0
                and resource_id not in accessible_ids
            ):
                warnings.append(
                    {
                        "code": "RESOURCE_UNAVAILABLE",
                        "resourceId": resource_id,
                        "message": f"图层“{layer.get('name') or resource_id}”的数据资源不可访问，已跳过",
                    }
                )
                continue
            next_children.append(copy.deepcopy(layer))
        next_group["children"] = next_children
        if next_children or bool(next_group.get("isManual")):
            filtered_groups.append(next_group)
    result["groups"] = filtered_groups
    selected_layer_id = result.get("selectedLayerId")
    valid_layer_ids = {
        layer.get("id")
        for group in filtered_groups
        for layer in group.get("children", [])
        if isinstance(layer, dict)
    }
    if selected_layer_id not in valid_layer_ids:
        result["selectedLayerId"] = None
    return result, warnings


def _serialize_workspace(scene: WorkspaceScene, request_user) -> dict[str, Any]:
    owner = scene.owner if user_is_visible_to(request_user, scene.owner) else None
    is_owner = scene.owner_id == request_user.id
    return {
        "id": scene.id,
        "kind": scene.kind,
        "name": scene.name,
        "description": scene.description,
        "snapshot": scene.snapshot,
        "owner": _serialize_user(owner),
        "accessGroups": [
            _serialize_group(group)
            for group in selectable_access_groups_for(
                scene.access_groups.all(), request_user
            )
        ],
        "isOwner": is_owner,
        "canEdit": bool(
            is_owner and has_feature_perm(request_user, "catalog.change_workspacescene")
        ),
        "canDelete": bool(
            is_owner and has_feature_perm(request_user, "catalog.delete_workspacescene")
        ),
        "canManageAccess": is_owner,
        "createdAt": scene.created_at.isoformat(),
        "updatedAt": scene.updated_at.isoformat(),
    }


def _json_payload(
    request, *, max_body_bytes: int = LAYOUT_MAX_BYTES + 64 * 1024
) -> dict[str, Any] | JsonResponse:
    if len(request.body) > max_body_bytes:
        return JsonResponse({"detail": "请求体超过平台限制"}, status=413)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except UnicodeDecodeError:
        return JsonResponse({"detail": "请求体编码必须是 UTF-8"}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "请求体不是有效 JSON"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "请求体必须是 JSON 对象"}, status=400)
    return payload
