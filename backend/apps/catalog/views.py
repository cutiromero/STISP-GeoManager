import json
import threading
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from django.contrib.auth.models import Group
from django.core.exceptions import RequestDataTooBig
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.gzip import gzip_page
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.audit.service import log_operation
from apps.catalog.data_query import (
    DataQueryError,
    get_resource_profile,
)
from apps.catalog.data_query import (
    query_resource as query_data_resource,
)
from apps.catalog.export import (
    ExportError,
    export_layers_zip_to_path,
    validate_epsg,
    validate_vector_format,
)
from apps.catalog.importer import (
    ImportDataError,
    import_uploaded_table,
    preview_uploaded_table,
    validate_uploaded_table,
)
from apps.catalog.models import (
    DataCatalog,
    DataResource,
    MapLayer,
    WorkspaceScene,
    task_resource_q,
)
from apps.catalog.permissions import (
    filter_accessible,
    filter_accessible_layers,
    user_can_access,
    user_can_bypass_owner_only,
    workspace_access_filter,
)
from apps.catalog.serializers import (
    current_visualization,
    serialize_catalog,
    serialize_layer,
    serialize_resource,
)
from apps.catalog.services import (
    scan_catalog_sources,
)
from apps.catalog.taxonomy import TaxonomyError, category_codes_for_filter
from apps.catalog.vector_importer import (
    commit_vector_import,
    preview_vector_import,
    validate_vector_import,
)
from apps.catalog.vector_tiles import vector_tile_preview
from apps.catalog.visualization import resource_visualization_summary
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
from apps.raster.models import RasterDataset
from apps.raster.services import (
    RasterJobError,
    get_job,
    open_job_artifact_for_download,
    start_export_job,
)
from apps.standards.models import DataDomainType

_CATALOG_SCAN_LOCK = threading.Lock()
_RESOURCE_QUERY_GATE = threading.BoundedSemaphore(value=1)
_DISPLAY_QUERY_GATE = threading.BoundedSemaphore(value=2)

WORKSPACE_SNAPSHOT_MAX_BODY_BYTES = 1024 * 1024
RESOURCE_QUERY_MAX_BODY_BYTES = 1024 * 1024
EXPORT_REQUEST_MAX_BODY_BYTES = 10 * 1024 * 1024
RESOURCE_QUERY_GATE_WAIT_SECONDS = 1.0


class _TemporaryExportFile:
    def __init__(self, file_object, temporary: TemporaryDirectory) -> None:
        self._file_object = file_object
        self._temporary = temporary
        self._closed = False

    def read(self, *args, **kwargs):
        return self._file_object.read(*args, **kwargs)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._file_object.close()
        finally:
            self._temporary.cleanup()

    def __getattr__(self, name: str):
        return getattr(self._file_object, name)


@require_GET
@api_login_required
def directories(request):
    if not has_feature_perm(request.user, "core.browse_data"):
        return feature_denied_response(request.user)
    queryset = DataCatalog.objects.filter(is_active=True).prefetch_related(
        "resources", "resources__category", "resources__category__parent"
    )
    catalogs = filter_accessible(queryset, request.user)
    return JsonResponse(
        {
            "items": [
                _serialize_catalog_for_user(item, request.user) for item in catalogs
            ]
        }
    )


@require_GET
@api_login_required
def resources(request):
    if not has_feature_perm(request.user, "core.browse_data"):
        return feature_denied_response(request.user)

    data_type = request.GET.get("dataType", "").strip()
    spatial_class = request.GET.get("spatialClass", "").strip()
    domain_type = request.GET.get("domainType", "").strip()
    query = request.GET.get("q", "").strip()
    if spatial_class and spatial_class not in DataResource.SpatialClass.values:
        return JsonResponse({"detail": "无效的空间数据分类"}, status=400)
    if domain_type and domain_type not in DataDomainType.values:
        return JsonResponse({"detail": "无效的数据业务类型"}, status=400)

    queryset = (
        DataResource.objects.filter(status=DataResource.Status.ACTIVE)
        .exclude(task_resource_q())
        .select_related("category", "category__parent")
    )
    if query:
        queryset = queryset.filter(name__icontains=query)
    if data_type:
        queryset = queryset.filter(data_type=data_type)
    if spatial_class == DataResource.SpatialClass.SPATIAL:
        queryset = queryset.filter(
            Q(
                data_type__in=(
                    DataResource.DataType.VECTOR,
                    DataResource.DataType.RASTER,
                )
            )
            & ~Q(coordinate_system="")
        )
    elif spatial_class == DataResource.SpatialClass.NON_SPATIAL:
        queryset = queryset.exclude(
            Q(
                data_type__in=(
                    DataResource.DataType.VECTOR,
                    DataResource.DataType.RASTER,
                )
            )
            & ~Q(coordinate_system="")
        )
    if domain_type:
        queryset = queryset.filter(domain_type=domain_type)
    category = request.GET.get("categoryCode", "").strip()
    legacy_category = request.GET.get("category", "").strip()
    if category and legacy_category and category != legacy_category:
        return JsonResponse({"detail": "category 与 categoryCode 不能冲突"}, status=400)
    category = category or legacy_category
    if category:
        try:
            category_codes = category_codes_for_filter(category)
        except TaxonomyError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        queryset = queryset.filter(category__code__in=category_codes)
    classification_status = request.GET.get("classificationStatus", "").strip()
    if classification_status == "classified":
        queryset = queryset.filter(category_id__isnull=False)
    elif classification_status == "pending":
        queryset = queryset.filter(category_id__isnull=True)
    elif classification_status:
        return JsonResponse(
            {"detail": "classificationStatus 仅支持 classified 或 pending"},
            status=400,
        )
    source = request.GET.get("source", "").strip()
    if source:
        queryset = queryset.filter(source__icontains=source)
    provider = request.GET.get("provider", "").strip()
    if provider:
        queryset = queryset.filter(provider__icontains=provider)
    date_from = request.GET.get("dateFrom", "").strip()
    if date_from:
        queryset = queryset.filter(data_date__gte=date_from)
    date_to = request.GET.get("dateTo", "").strip()
    if date_to:
        queryset = queryset.filter(data_date__lte=date_to)
    items = [
        serialize_resource(item) for item in filter_accessible(queryset, request.user)
    ]

    return JsonResponse({"items": items})


@require_POST
@api_login_required
def scan_sources(request):
    if not _can_create_data_resource(request.user):
        return feature_denied_response(request.user)
    if not _CATALOG_SCAN_LOCK.acquire(blocking=False):
        return JsonResponse({"detail": "数据目录扫描正在进行，请稍后重试"}, status=409)
    try:
        resources = scan_catalog_sources()
    finally:
        _CATALOG_SCAN_LOCK.release()
    items = [
        serialize_resource(item)
        for item in resources
        if user_can_access(item, request.user)
    ]
    return JsonResponse({"items": items, "count": len(items)})


@require_POST
@api_login_required
def import_preview(request):
    if not _can_create_data_resource(request.user):
        return feature_denied_response(request.user)
    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        log_operation(
            request.user,
            "数据导入",
            "预览导入文件",
            "failed",
            "未上传 Excel 或 CSV 文件",
            request,
        )
        return JsonResponse({"detail": "请上传 Excel 或 CSV 文件"}, status=400)
    try:
        result = preview_uploaded_table(
            uploaded_file, sheet_name=request.POST.get("sheetName")
        )
    except ImportDataError as exc:
        log_operation(
            request.user,
            "数据导入",
            "预览导入文件",
            "failed",
            str(exc),
            request,
        )
        return JsonResponse(_import_error_payload(exc), status=400)
    log_operation(
        request.user,
        "数据导入",
        "预览导入文件",
        "success",
        uploaded_file.name,
        request,
    )
    return JsonResponse(result)


@require_POST
@api_login_required
def import_validate(request):
    if not _can_create_data_resource(request.user):
        return feature_denied_response(request.user)
    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        log_operation(
            request.user,
            "数据导入",
            "校验导入文件",
            "failed",
            "未上传 Excel 或 CSV 文件",
            request,
        )
        return JsonResponse({"detail": "请上传 Excel 或 CSV 文件"}, status=400)
    try:
        payload = json.loads(request.POST.get("payload", "{}"))
    except json.JSONDecodeError:
        log_operation(
            request.user,
            "数据导入",
            "校验导入文件",
            "failed",
            "导入参数不是有效 JSON",
            request,
        )
        return JsonResponse({"detail": "导入参数不是有效 JSON"}, status=400)
    try:
        result = validate_uploaded_table(uploaded_file, payload)
    except ImportDataError as exc:
        log_operation(
            request.user,
            "数据导入",
            "校验导入文件",
            "failed",
            str(exc),
            request,
        )
        return JsonResponse(_import_error_payload(exc), status=400)
    log_operation(
        request.user,
        "数据导入",
        "校验导入文件",
        "success",
        uploaded_file.name,
        request,
    )
    return JsonResponse(result)


@require_POST
@api_login_required
def import_commit(request):
    if not _can_create_data_resource(request.user):
        return feature_denied_response(request.user)
    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        log_operation(
            request.user,
            "数据导入",
            "提交导入文件",
            "failed",
            "未上传 Excel 或 CSV 文件",
            request,
        )
        return JsonResponse({"detail": "请上传 Excel 或 CSV 文件"}, status=400)
    try:
        payload = json.loads(request.POST.get("payload", "{}"))
    except json.JSONDecodeError:
        log_operation(
            request.user,
            "数据导入",
            "提交导入文件",
            "failed",
            "导入参数不是有效 JSON",
            request,
        )
        return JsonResponse({"detail": "导入参数不是有效 JSON"}, status=400)
    try:
        result = import_uploaded_table(uploaded_file, payload, request.user)
    except ImportDataError as exc:
        log_operation(
            request.user,
            "数据导入",
            "提交导入文件",
            "failed",
            str(exc),
            request,
        )
        return JsonResponse(_import_error_payload(exc), status=400)
    resource = DataResource.objects.filter(pk=result.get("resourceId")).first()
    log_operation(
        request.user,
        "数据导入",
        "提交导入文件",
        "success",
        f"{result.get('resourceName', uploaded_file.name)}：导入 {result.get('importedRows', 0)} 行",
        request,
        target_type="data_resource",
        target_id=resource.id if resource else result.get("resourceId"),
        target_code=resource.code if resource else "",
        target_name=resource.name if resource else result.get("resourceName", ""),
    )
    return JsonResponse(result, status=201)


@require_POST
@api_login_required
def vector_import_preview(request):
    if not _can_create_data_resource(request.user):
        return feature_denied_response(request.user)
    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return JsonResponse({"detail": "请上传矢量文件"}, status=400)
    try:
        result = preview_vector_import(
            uploaded_file, encoding=request.POST.get("encoding") or None
        )
    except ImportDataError as exc:
        log_operation(
            request.user,
            "数据导入",
            "预检矢量文件",
            "failed",
            str(exc),
            request,
        )
        return JsonResponse(_import_error_payload(exc), status=400)
    log_operation(
        request.user,
        "数据导入",
        "预检矢量文件",
        "success",
        uploaded_file.name,
        request,
    )
    return JsonResponse(result)


@require_POST
@api_login_required
def vector_import_validate(request):
    if not _can_create_data_resource(request.user):
        return feature_denied_response(request.user)
    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return JsonResponse({"detail": "请上传矢量文件"}, status=400)
    try:
        payload = json.loads(request.POST.get("payload", "{}"))
    except json.JSONDecodeError:
        return JsonResponse({"detail": "矢量导入参数不是有效 JSON"}, status=400)
    try:
        result = validate_vector_import(uploaded_file, payload)
    except ImportDataError as exc:
        log_operation(
            request.user,
            "数据导入",
            "校验矢量文件",
            "failed",
            str(exc),
            request,
        )
        return JsonResponse(_import_error_payload(exc), status=400)
    log_operation(
        request.user,
        "数据导入",
        "校验矢量文件",
        "success",
        uploaded_file.name,
        request,
    )
    return JsonResponse(result)


@require_POST
@api_login_required
def vector_import_commit(request):
    if not _can_create_data_resource(request.user):
        return feature_denied_response(request.user)
    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return JsonResponse({"detail": "请上传矢量文件"}, status=400)
    try:
        payload = json.loads(request.POST.get("payload", "{}"))
    except json.JSONDecodeError:
        return JsonResponse({"detail": "矢量导入参数不是有效 JSON"}, status=400)
    try:
        result = commit_vector_import(uploaded_file, payload, request.user)
    except ImportDataError as exc:
        log_operation(
            request.user,
            "数据导入",
            "提交矢量导入",
            "failed",
            str(exc),
            request,
        )
        return JsonResponse(_import_error_payload(exc), status=400)
    resource = DataResource.objects.filter(pk=result.get("resourceId")).first()
    log_operation(
        request.user,
        "数据导入",
        "提交矢量导入",
        "success",
        f"{result.get('resourceName', uploaded_file.name)}：导入 {result.get('importedFeatures', 0)} 个要素",
        request,
        target_type="data_resource",
        target_id=resource.id if resource else result.get("resourceId"),
        target_code=resource.code if resource else "",
        target_name=resource.name if resource else result.get("resourceName", ""),
    )
    return JsonResponse(result, status=201)


def _can_create_data_resource(user) -> bool:
    return has_feature_perm(user, "catalog.add_dataresource")


def _serialize_catalog_for_user(catalog: DataCatalog, user) -> dict:
    payload = serialize_catalog(catalog)
    payload["resources"] = [
        serialize_resource(resource)
        for resource in catalog.resources.all()
        if user_can_access(resource, user)
    ]
    return payload


@require_http_methods(["GET", "POST"])
@api_login_required
def workspaces(request):
    if request.method == "POST":
        return _create_workspace(request)
    if not has_feature_perm(request.user, "catalog.view_workspacescene"):
        return feature_denied_response(request.user)
    kind = str(request.GET.get("kind", "")).strip()
    if kind and kind != WorkspaceScene.Kind.PROJECT:
        return JsonResponse({"detail": "kind 仅支持 project"}, status=400)
    queryset = (
        WorkspaceScene.objects.select_related("owner")
        .prefetch_related("access_groups")
        .filter(status=WorkspaceScene.Status.ACTIVE)
        .filter(_workspace_access_filter(request.user))
        .order_by("-updated_at", "name")
        .distinct()
    )
    if kind:
        queryset = queryset.filter(kind=kind)
    query = request.GET.get("q", "").strip()[:150]
    if query:
        queryset = queryset.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )
    try:
        limit = int(request.GET.get("limit", 24))
        offset = int(request.GET.get("offset", 0))
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError
    except ValueError:
        return JsonResponse({"detail": "分页参数无效"}, status=400)
    return JsonResponse(
        {
            "items": [
                _serialize_workspace(item, request.user, summary=True)
                for item in queryset.defer("snapshot")[offset : offset + limit]
            ],
            "total": queryset.count(),
            "limit": limit,
            "offset": offset,
            "availableAccessGroups": [],
        }
    )


def _create_workspace(request):
    if not has_feature_perm(request.user, "catalog.add_workspacescene"):
        return feature_denied_response(request.user)
    payload = _json_payload(request, max_body_bytes=WORKSPACE_SNAPSHOT_MAX_BODY_BYTES)
    if isinstance(payload, JsonResponse):
        return payload
    values = _workspace_payload(payload, partial=False)
    if isinstance(values, JsonResponse):
        return values
    group_ids = _workspace_access_group_ids(payload, request.user)
    if isinstance(group_ids, JsonResponse):
        return group_ids
    try:
        with transaction.atomic():
            scene = WorkspaceScene.objects.create(owner=request.user, **values)
    except IntegrityError:
        return JsonResponse({"detail": "同名工程已存在"}, status=400)
    access_error = _set_access_groups_with_superadmin(scene, group_ids, request.user)
    if isinstance(access_error, JsonResponse):
        scene.delete()
        return access_error
    log_operation(
        request.user,
        "工作台",
        f"保存{_workspace_kind_label(scene.kind)}",
        "success",
        scene.name,
        request,
        target_type="workspace_scene",
        target_id=scene.id,
        target_code=scene.kind,
        target_name=scene.name,
    )
    scene = (
        WorkspaceScene.objects.select_related("owner")
        .prefetch_related("access_groups")
        .get(pk=scene.id)
    )
    return JsonResponse(_serialize_workspace(scene, request.user), status=201)


@require_http_methods(["GET", "POST"])
@api_login_required
def workspace_detail(request, workspace_id: int):
    scene = _workspace_for_user(
        request.user,
        workspace_id,
        require_owner=request.method == "POST",
    )
    if isinstance(scene, JsonResponse):
        return scene
    if request.method == "GET":
        if not has_feature_perm(request.user, "catalog.view_workspacescene"):
            return feature_denied_response(request.user)
        log_operation(
            request.user,
            "工作台",
            f"查看{_workspace_kind_label(scene.kind)}",
            "success",
            scene.name,
            request,
            target_type="workspace_scene",
            target_id=scene.id,
            target_code=scene.kind,
            target_name=scene.name,
        )
        return JsonResponse(_serialize_workspace(scene, request.user))
    payload = _json_payload(request, max_body_bytes=WORKSPACE_SNAPSHOT_MAX_BODY_BYTES)
    if isinstance(payload, JsonResponse):
        return payload
    if payload.get("action") == "delete":
        if not has_feature_perm(request.user, "catalog.delete_workspacescene"):
            return feature_denied_response(request.user)
        name = scene.name
        target_id = scene.id
        target_code = scene.kind
        kind_label = _workspace_kind_label(scene.kind)
        _delete_workspace_scene(scene)
        log_operation(
            request.user,
            "工作台",
            f"删除{kind_label}",
            "success",
            name,
            request,
            target_type="workspace_scene",
            target_id=target_id,
            target_code=target_code,
            target_name=name,
        )
        return JsonResponse({"detail": f"{kind_label}已删除"})
    values = _workspace_payload(payload, partial=True)
    if isinstance(values, JsonResponse):
        return values
    if values and not has_feature_perm(request.user, "catalog.change_workspacescene"):
        return feature_denied_response(request.user)
    group_ids = None
    if "accessGroupIds" in payload:
        group_ids = _workspace_access_group_ids(payload, request.user)
        if isinstance(group_ids, JsonResponse):
            return group_ids
    if not values and group_ids is None:
        return JsonResponse({"detail": "没有可更新的工程字段"}, status=400)
    for key, value in values.items():
        setattr(scene, key, value)
    try:
        with transaction.atomic():
            conflict = _save_workspace_conditionally(scene, payload, values)
            if conflict is not None:
                return conflict
            if group_ids is not None:
                access_error = _set_access_groups_with_superadmin(
                    scene, group_ids, request.user
                )
                if isinstance(access_error, JsonResponse):
                    transaction.set_rollback(True)
                    return access_error
    except IntegrityError:
        return JsonResponse({"detail": "同名工程已存在"}, status=400)
    log_operation(
        request.user,
        "工作台",
        f"更新{_workspace_kind_label(scene.kind)}",
        "success",
        scene.name,
        request,
        target_type="workspace_scene",
        target_id=scene.id,
        target_code=scene.kind,
        target_name=scene.name,
    )
    scene = (
        WorkspaceScene.objects.select_related("owner")
        .prefetch_related("access_groups")
        .get(pk=scene.id)
    )
    return JsonResponse(_serialize_workspace(scene, request.user))


def _workspace_for_user(
    user, workspace_id: int, *, require_owner: bool = False
) -> WorkspaceScene | JsonResponse:
    queryset = (
        WorkspaceScene.objects.select_related("owner")
        .prefetch_related("access_groups")
        .filter(pk=workspace_id, status=WorkspaceScene.Status.ACTIVE)
    )
    if require_owner:
        if not user_can_bypass_owner_only(user):
            queryset = queryset.filter(owner=user)
    else:
        queryset = queryset.filter(_workspace_access_filter(user)).distinct()
    scene = queryset.first()
    if scene is None:
        return JsonResponse({"detail": "工程不存在"}, status=404)
    return scene


def _workspace_payload(
    payload: dict, *, partial: bool
) -> dict[str, object] | JsonResponse:
    values: dict[str, object] = {}
    if not partial or "kind" in payload:
        kind = str(payload.get("kind", "")).strip()
        if kind != WorkspaceScene.Kind.PROJECT:
            return JsonResponse({"detail": "kind 仅支持 project"}, status=400)
        values["kind"] = kind
    if not partial or "name" in payload:
        name = str(payload.get("name", "")).strip()
        if not name:
            return JsonResponse({"detail": "名称不能为空"}, status=400)
        values["name"] = name
    if "description" in payload:
        values["description"] = str(payload.get("description") or "").strip()
    elif not partial:
        values["description"] = ""
    if not partial or "snapshot" in payload:
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict):
            return JsonResponse({"detail": "snapshot 必须是 JSON 对象"}, status=400)
        if _snapshot_contains_embedded_data(snapshot):
            return JsonResponse(
                {
                    "detail": "工程快照只能保存查询、范围、资源引用和图层结构，不能包含原始数据"
                },
                status=400,
            )
        values["snapshot"] = snapshot
    return values


def _serialize_workspace(
    scene: WorkspaceScene, request_user, *, summary=False
) -> dict[str, object]:
    from apps.agent.display_color_policy import refresh_snapshot

    is_owner = scene.owner_id == getattr(request_user, "id", None)
    can_manage_all = user_can_bypass_owner_only(request_user)
    owner = scene.owner if user_is_visible_to(request_user, scene.owner) else None
    return {
        "id": scene.id,
        "projectTagId": scene.project_tag_id,
        "kind": scene.kind,
        "name": scene.name,
        "description": scene.description,
        **({} if summary else {"snapshot": refresh_snapshot(scene.snapshot)}),
        "owner": {
            "id": owner.id if owner else 0,
            "displayName": (
                owner.get_full_name() or owner.get_username() if owner else "系统维护"
            ),
            "username": owner.get_username() if owner else "",
        },
        "accessGroups": [
            _serialize_access_group(group)
            for group in selectable_access_groups_for(
                scene.access_groups.all(), request_user
            )
        ],
        "isOwner": is_owner,
        "canEdit": bool(
            (is_owner or can_manage_all)
            and has_feature_perm(request_user, "catalog.change_workspacescene")
        ),
        "canDelete": bool(
            (is_owner or can_manage_all)
            and has_feature_perm(request_user, "catalog.delete_workspacescene")
        ),
        "canManageAccess": bool(is_owner or can_manage_all),
        "createdAt": scene.created_at.isoformat(),
        "updatedAt": scene.updated_at.isoformat(),
    }


@require_GET
@api_login_required
def admin_workspaces(request):
    if not _can_open_workspace_admin(request.user):
        return feature_denied_response(request.user)
    kind = str(request.GET.get("kind", "")).strip()
    status = str(request.GET.get("status", "")).strip()
    if kind and kind != WorkspaceScene.Kind.PROJECT:
        return JsonResponse({"detail": "kind 仅支持 project"}, status=400)
    if status and status not in WorkspaceScene.Status.values:
        return JsonResponse({"detail": "status 仅支持 active 或 inactive"}, status=400)
    query = str(request.GET.get("q", "")).strip()
    queryset = (
        WorkspaceScene.objects.select_related("owner")
        .prefetch_related("access_groups")
        .filter(_workspace_admin_access_filter(request.user))
        .order_by("-updated_at", "name")
        .distinct()
    )
    if query:
        queryset = queryset.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(owner__username__icontains=query)
            | Q(owner__first_name__icontains=query)
        )
    if kind:
        queryset = queryset.filter(kind=kind)
    if status:
        queryset = queryset.filter(status=status)
    total = queryset.count()
    current = _positive_query_int(request.GET.get("current"), default=1)
    page_size = _positive_query_int(request.GET.get("pageSize"), default=20)
    if isinstance(current, JsonResponse):
        return current
    if isinstance(page_size, JsonResponse):
        return page_size
    start = (current - 1) * page_size
    return JsonResponse(
        {
            "items": [
                _serialize_admin_workspace(scene, request.user)
                for scene in queryset[start : start + page_size]
            ],
            "total": total,
            "availableAccessGroups": _available_access_groups(request.user),
        }
    )


@require_http_methods(["POST"])
@api_login_required
def admin_workspace_detail(request, workspace_id: int):
    payload = _json_payload(request)
    if isinstance(payload, JsonResponse):
        return payload
    scene = (
        WorkspaceScene.objects.select_related("owner")
        .prefetch_related("access_groups")
        .filter(pk=workspace_id)
        .first()
    )
    if scene is None:
        return JsonResponse({"detail": "工程不存在"}, status=404)
    if not _user_can_see_admin_workspace(scene, request.user):
        return JsonResponse({"detail": "工程不存在"}, status=404)

    action = str(payload.get("action", "update")).strip()
    is_owner = scene.owner_id == request.user.id
    can_manage_all = user_can_bypass_owner_only(request.user)
    can_change = has_feature_perm(request.user, "catalog.change_workspacescene") and (
        can_manage_all or is_owner
    )
    can_delete = has_feature_perm(request.user, "catalog.delete_workspacescene") and (
        can_manage_all or is_owner
    )
    can_update_access = can_manage_all or is_owner
    if action == "delete":
        if not can_delete:
            return feature_denied_response(request.user)
        return _delete_admin_workspace(request, scene, payload)
    if action not in {"update", "setStatus", "updateAccess"}:
        return JsonResponse({"detail": "不支持的工程操作"}, status=400)
    if action == "updateAccess":
        if not can_update_access:
            return feature_denied_response(request.user)
    elif not can_change:
        return feature_denied_response(request.user)

    update_fields = []
    changed_access = False
    if action in {"update", "setStatus"} and "status" in payload:
        status = str(payload.get("status", "")).strip()
        if status not in WorkspaceScene.Status.values:
            return JsonResponse(
                {"detail": "status 仅支持 active 或 inactive"}, status=400
            )
        scene.status = status
        update_fields.append("status")
    if action == "update":
        values = _admin_workspace_payload(payload)
        if isinstance(values, JsonResponse):
            return values
        for key, value in values.items():
            setattr(scene, key, value)
        update_fields.extend(values.keys())
    group_ids = None
    if action in {"update", "updateAccess"} and "accessGroupIds" in payload:
        group_ids = _group_ids_payload(payload.get("accessGroupIds"))
        if isinstance(group_ids, JsonResponse):
            return group_ids
        changed_access = True
    if not update_fields and not changed_access:
        return JsonResponse({"detail": "没有可更新的工程字段"}, status=400)
    try:
        with transaction.atomic():
            conflict = _save_workspace_conditionally(
                scene,
                payload,
                {field: getattr(scene, field) for field in update_fields},
            )
            if conflict is not None:
                return conflict
            if group_ids is not None:
                access_error = _set_access_groups_with_superadmin(
                    scene, group_ids, request.user
                )
                if isinstance(access_error, JsonResponse):
                    transaction.set_rollback(True)
                    return access_error
    except IntegrityError:
        return JsonResponse({"detail": "同名工程已存在"}, status=400)
    log_operation(
        request.user,
        "数据管理",
        _admin_workspace_action_label(action, payload),
        "success",
        scene.name,
        request,
        target_type="workspace_scene",
        target_id=scene.id,
        target_code=scene.kind,
        target_name=scene.name,
    )
    scene.refresh_from_db()
    scene = (
        WorkspaceScene.objects.select_related("owner")
        .prefetch_related("access_groups")
        .get(pk=scene.id)
    )
    return JsonResponse(_serialize_admin_workspace(scene, request.user))


def _workspace_kind_label(kind: str) -> str:
    return "工程"


def _admin_workspace_payload(payload: dict[str, Any]) -> dict[str, Any] | JsonResponse:
    values: dict[str, Any] = {}
    if "kind" in payload:
        kind = str(payload.get("kind", "")).strip()
        if kind != WorkspaceScene.Kind.PROJECT:
            return JsonResponse({"detail": "kind 仅支持 project"}, status=400)
        values["kind"] = kind
    if "name" in payload:
        name = str(payload.get("name", "")).strip()
        if not name:
            return JsonResponse({"detail": "名称不能为空"}, status=400)
        values["name"] = name
    if "description" in payload:
        values["description"] = str(payload.get("description") or "").strip()
    return values


def _delete_workspace_scene(scene: WorkspaceScene) -> bool:
    try:
        scene.delete()
        return True
    except ProtectedError:
        scene.status = WorkspaceScene.Status.INACTIVE
        scene.save(update_fields=["status", "updated_at"])
        return False


def _delete_admin_workspace(request, scene: WorkspaceScene, payload: dict[str, Any]):
    confirmation = str(payload.get("confirmationName", "")).strip()
    if confirmation != scene.name:
        return JsonResponse({"detail": "确认名称不匹配"}, status=400)
    name = scene.name
    target_id = scene.id
    target_code = scene.kind
    _delete_workspace_scene(scene)
    log_operation(
        request.user,
        "数据管理",
        f"删除{_workspace_kind_label(target_code)}",
        "success",
        name,
        request,
        target_type="workspace_scene",
        target_id=target_id,
        target_code=target_code,
        target_name=name,
    )
    return JsonResponse({"detail": f"{_workspace_kind_label(target_code)}已删除"})


def _can_open_workspace_admin(user) -> bool:
    return (
        has_feature_perm(user, "catalog.view_workspacescene")
        or has_feature_perm(user, "catalog.change_workspacescene")
        or has_feature_perm(user, "catalog.delete_workspacescene")
    )


def _workspace_admin_access_filter(user):
    return _workspace_access_filter(user)


def _workspace_access_filter(user):
    return workspace_access_filter(user)


def _user_can_see_admin_workspace(scene, user):
    return WorkspaceScene.objects.filter(
        _workspace_access_filter(user), pk=scene.pk
    ).exists()


def _serialize_admin_workspace(scene: WorkspaceScene, request_user) -> dict[str, Any]:
    payload = _serialize_workspace(scene, request_user)
    payload.update(
        {
            "status": scene.status,
            "accessGroups": [
                _serialize_access_group(group)
                for group in selectable_access_groups_for(
                    scene.access_groups.all(), request_user
                )
            ],
            "canManageAccess": bool(
                user_can_bypass_owner_only(request_user)
                or scene.owner_id == getattr(request_user, "id", None)
            ),
        }
    )
    return payload


def _available_access_groups(request_user) -> list[dict[str, Any]]:
    return [
        _serialize_access_group(group)
        for group in selectable_access_groups_for(
            Group.objects.order_by("name"), request_user
        )
    ]


def _serialize_access_group(group: Group) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "isGuest": group.name == GUEST_GROUP_NAME,
        "isSuperadmin": group.name == SUPERADMIN_GROUP_NAME,
    }


def _set_access_groups_with_superadmin(obj, group_ids: list[int], viewer):
    visible_requested_ids = set(
        selectable_access_groups_for(
            Group.objects.filter(id__in=group_ids).only("id", "name"), viewer
        ).values_list("id", flat=True)
    )
    if visible_requested_ids != set(group_ids):
        return JsonResponse({"detail": "包含不存在或不可选择的角色"}, status=400)
    _, superadmin_group = ensure_superadmin_defaults(
        create_account=False, attach_existing_superusers=False
    )
    obj.access_groups.set(sorted({*group_ids, superadmin_group.id}))
    return None


def _workspace_access_group_ids(payload: dict[str, Any], viewer):
    group_ids = _group_ids_payload(payload.get("accessGroupIds", []))
    if isinstance(group_ids, JsonResponse):
        return group_ids
    selectable_ids = set(
        selectable_access_groups_for(
            Group.objects.filter(id__in=group_ids).only("id", "name"), viewer
        ).values_list("id", flat=True)
    )
    if selectable_ids != set(group_ids):
        return JsonResponse({"detail": "包含不存在或不可选择的角色"}, status=400)
    return group_ids


def _admin_workspace_action_label(action: str, payload: dict[str, Any]) -> str:
    if action == "setStatus":
        return "切换工程状态"
    if action == "updateAccess":
        return "更新工程可见范围"
    if "accessGroupIds" in payload:
        return "更新工程信息和可见范围"
    return "更新工程信息"


def _json_payload(
    request, *, max_body_bytes: int | None = None
) -> dict[str, Any] | JsonResponse:
    if max_body_bytes is not None:
        try:
            content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            return JsonResponse({"detail": "Content-Length 不合法"}, status=400)
        if content_length > max_body_bytes:
            return JsonResponse({"detail": "请求体过大"}, status=413)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except RequestDataTooBig:
        return JsonResponse({"detail": "请求体过大"}, status=413)
    except UnicodeDecodeError:
        return JsonResponse({"detail": "请求体编码必须是 UTF-8"}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "请求体不是有效 JSON"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "请求体必须是 JSON 对象"}, status=400)
    return payload


def _json_payload_from_stream(
    request, *, max_body_bytes: int = EXPORT_REQUEST_MAX_BODY_BYTES
) -> dict[str, Any] | JsonResponse:
    try:
        content_length = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        return JsonResponse({"detail": "Content-Length 不合法"}, status=400)
    if content_length < 0:
        return JsonResponse({"detail": "Content-Length 不合法"}, status=400)
    if content_length > max_body_bytes:
        return JsonResponse({"detail": "请求体过大"}, status=413)

    stream = request.META.get("wsgi.input")
    try:
        if stream is not None:
            read_size = content_length if content_length else max_body_bytes + 1
            raw = stream.read(min(read_size, max_body_bytes + 1))
        else:
            raw = request.body
    except RequestDataTooBig:
        return JsonResponse({"detail": "请求体过大"}, status=413)
    except OSError:
        return JsonResponse({"detail": "读取请求体失败"}, status=400)
    if len(raw) > max_body_bytes:
        return JsonResponse({"detail": "请求体过大"}, status=413)
    if not raw:
        raw = b"{}"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return JsonResponse({"detail": "请求体编码必须是 UTF-8"}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "请求体不是有效 JSON"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "请求体必须是 JSON 对象"}, status=400)
    return payload


def _snapshot_contains_embedded_data(value: object) -> bool:
    if isinstance(value, dict):
        if "geojson" in value:
            return True
        if value.get("type") == "FeatureCollection" and isinstance(
            value.get("features"), list
        ):
            return True
        return any(_snapshot_contains_embedded_data(item) for item in value.values())
    if isinstance(value, list):
        return any(_snapshot_contains_embedded_data(item) for item in value)
    return False


def _import_error_payload(exc: ImportDataError) -> dict:
    detail = str(exc.args[0]) if exc.args else str(exc)
    payload = {"detail": detail}
    if len(exc.args) > 1 and isinstance(exc.args[1], list):
        payload["issues"] = exc.args[1]
    return payload


@require_GET
@api_login_required
def resource_profile(request, pk: int):
    if not has_feature_perm(request.user, "core.browse_data"):
        return feature_denied_response(request.user)
    resource = get_object_or_404(
        DataResource.objects.select_related("category", "category__parent"),
        pk=pk,
        status=DataResource.Status.ACTIVE,
    )
    if not user_can_access(resource, request.user):
        return JsonResponse({"detail": "无权访问该数据资源"}, status=403)
    try:
        profile = get_resource_profile(resource)
    except DataQueryError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    log_operation(
        request.user,
        "数据查询",
        "查看数据资源",
        "success",
        resource.name,
        request,
        target_type="data_resource",
        target_id=resource.id,
        target_code=resource.code,
        target_name=resource.name,
    )
    return JsonResponse(
        {
            "resource": serialize_resource(resource),
            "fields": profile.fields,
            "featureCount": profile.feature_count,
            "geometryType": profile.geometry_type,
            "bounds": profile.bounds,
            "raster": profile.raster,
            "defaultVisualization": current_visualization(resource),
            "vectorTiles": vector_tile_preview(resource),
        }
    )


@require_GET
@api_login_required
def resource_visualization_summary_view(request, pk: int):
    if not has_feature_perm(request.user, "core.browse_data"):
        return feature_denied_response(request.user)
    resource = get_object_or_404(
        DataResource.objects.select_related("category", "category__parent"),
        pk=pk,
        status=DataResource.Status.ACTIVE,
    )
    if not user_can_access(resource, request.user):
        return JsonResponse({"detail": "无权访问该数据资源"}, status=403)
    try:
        top_n = _bounded_int_query(request, "topN", 8, 3, 20)
        histogram_bins = _bounded_int_query(request, "histogramBins", 8, 4, 20)
        summary = resource_visualization_summary(
            resource,
            top_n=top_n,
            histogram_bins=histogram_bins,
        )
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    except DataQueryError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    log_operation(
        request.user,
        "数据查询",
        "查看数据可视化摘要",
        "success",
        resource.name,
        request,
        target_type="data_resource",
        target_id=resource.id,
        target_code=resource.code,
        target_name=resource.name,
    )
    return JsonResponse(summary)


def _bounded_int_query(request, name: str, default: int, minimum: int, maximum: int):
    raw_value = request.GET.get(name, default)
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
    return value


@gzip_page
@require_POST
@api_login_required
def resource_query(request, pk: int):
    can_query = has_feature_perm(request.user, "core.query_data")
    can_load_vector = has_feature_perm(request.user, "core.load_vector_layer")
    if not can_query or not can_load_vector:
        return feature_denied_response(request.user)
    resource = get_object_or_404(
        DataResource.objects.select_related("category", "category__parent"),
        pk=pk,
        status=DataResource.Status.ACTIVE,
    )
    if not user_can_access(resource, request.user):
        return JsonResponse({"detail": "无权访问该数据资源"}, status=403)
    payload = _json_payload(request, max_body_bytes=RESOURCE_QUERY_MAX_BODY_BYTES)
    if isinstance(payload, JsonResponse):
        return payload
    query_gate = (
        _DISPLAY_QUERY_GATE
        if payload.get("displayGeometry") is True
        else _RESOURCE_QUERY_GATE
    )
    if not query_gate.acquire(timeout=RESOURCE_QUERY_GATE_WAIT_SECONDS):
        response = JsonResponse({"detail": "查询任务繁忙，请稍后重试"}, status=503)
        response["Retry-After"] = "2"
        return response
    try:
        try:
            result = query_data_resource(resource, payload)
        except DataQueryError as exc:
            log_operation(
                request.user,
                "数据查询",
                "查询数据资源",
                "failed",
                f"{resource.name}：{exc}",
                request,
                target_type="data_resource",
                target_id=resource.id,
                target_code=resource.code,
                target_name=resource.name,
            )
            return JsonResponse({"detail": str(exc)}, status=400)
    finally:
        query_gate.release()
    log_operation(
        request.user,
        "数据查询",
        "查询数据资源",
        "success",
        f"{resource.name}：返回 {result.get('returnedCount', 0)} 条",
        request,
        target_type="data_resource",
        target_id=resource.id,
        target_code=resource.code,
        target_name=resource.name,
    )
    return JsonResponse(result)


def _validate_export_item_access(item: Any, user) -> JsonResponse | None:
    if not isinstance(item, dict):
        return JsonResponse({"detail": "items 中的图层必须是对象"}, status=400)

    resource_id = item.get("resourceId")
    if item.get("layerType") != "raster":
        if resource_id:
            resource = get_object_or_404(
                DataResource,
                pk=resource_id,
                status=DataResource.Status.ACTIVE,
            )
            if not user_can_access(resource, user):
                return JsonResponse({"detail": "无权访问该数据资源"}, status=403)
        return None

    dataset_id = _positive_export_id(item.get("datasetId"))
    if dataset_id is None:
        return JsonResponse({"detail": "栅格图层缺少有效 datasetId"}, status=400)
    dataset = (
        RasterDataset.objects.select_related("data_resource")
        .filter(pk=dataset_id)
        .first()
    )
    if dataset is None:
        return JsonResponse({"detail": "栅格数据集不存在"}, status=404)

    resource = dataset.data_resource
    if resource is None:
        return JsonResponse({"detail": "栅格数据集未关联数据资源"}, status=400)
    if resource.status != DataResource.Status.ACTIVE:
        return JsonResponse({"detail": "数据资源不存在"}, status=404)
    if not user_can_access(resource, user):
        return JsonResponse({"detail": "无权访问该数据资源"}, status=403)

    if "resourceId" in item:
        supplied_resource_id = _positive_export_id(resource_id)
        if supplied_resource_id is None:
            return JsonResponse({"detail": "resourceId 不合法"}, status=400)
        if supplied_resource_id != resource.id:
            return JsonResponse({"detail": "resourceId 与栅格数据集不匹配"}, status=400)
    return None


def _positive_export_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdecimal():
        parsed = int(value.strip())
    else:
        return None
    return parsed if parsed > 0 else None


@require_POST
@api_login_required
def export_loaded_layers(request):
    if not has_feature_perm(request.user, "catalog.export_dataresource"):
        return feature_denied_response(request.user)
    payload = _json_payload_from_stream(
        request, max_body_bytes=EXPORT_REQUEST_MAX_BODY_BYTES
    )
    if isinstance(payload, JsonResponse):
        return payload
    try:
        epsg = validate_epsg(payload.get("epsg", 4326))
    except Exception as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    try:
        vector_format = validate_vector_format(payload.get("format", "geojson"))
    except ExportError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    items = payload.get("items") or []
    if not isinstance(items, list):
        return JsonResponse({"detail": "items 必须是数组"}, status=400)

    for item in items:
        access_error = _validate_export_item_access(item, request.user)
        if access_error is not None:
            return access_error

    temporary = TemporaryDirectory(prefix="geomanager-export-")
    output_path = Path(temporary.name) / "layers.zip"
    try:
        export_layers_zip_to_path(
            items,
            epsg,
            output_path=output_path,
            reproject=bool(payload.get("reproject", True)),
            clip_geometry=payload.get("clipGeometry") if payload.get("clip") else None,
            vector_format=vector_format,
        )
    except ExportError as exc:
        temporary.cleanup()
        log_operation(
            request.user,
            "数据导出",
            "导出已加载图层",
            "failed",
            str(exc),
            request,
        )
        return JsonResponse({"detail": str(exc)}, status=400)
    except Exception:
        temporary.cleanup()
        raise

    filename = f"layers-export-{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
    try:
        artifact_file = _TemporaryExportFile(output_path.open("rb"), temporary)
        response = FileResponse(
            artifact_file,
            as_attachment=True,
            filename=filename,
            content_type="application/zip",
        )
    except Exception:
        if "artifact_file" in locals():
            artifact_file.close()
        else:
            temporary.cleanup()
        raise
    log_operation(
        request.user,
        "数据导出",
        "导出已加载图层",
        "success",
        f"{filename}：{len(items)} 个图层",
        request,
    )
    return response


@require_POST
@api_login_required
def export_loaded_layers_async(request):
    if not has_feature_perm(request.user, "catalog.export_dataresource"):
        return feature_denied_response(request.user)
    payload = _json_payload_from_stream(
        request, max_body_bytes=EXPORT_REQUEST_MAX_BODY_BYTES
    )
    if isinstance(payload, JsonResponse):
        return payload

    reproject = bool(payload.get("reproject", True))
    epsg = None
    if reproject:
        try:
            epsg = validate_epsg(payload.get("epsg", 4326))
        except Exception as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
    try:
        vector_format = validate_vector_format(payload.get("format", "geojson"))
    except ExportError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    items = payload.get("items") or []
    if not isinstance(items, list):
        return JsonResponse({"detail": "items 必须是数组"}, status=400)

    for item in items:
        access_error = _validate_export_item_access(item, request.user)
        if access_error is not None:
            return access_error

    clip_geometry = payload.get("clipGeometry") if payload.get("clip") else None
    try:
        job = start_export_job(
            items=items,
            epsg=epsg,
            reproject=reproject,
            clip_geometry=clip_geometry,
            vector_format=vector_format,
            created_by_id=request.user.id,
        )
    except ExportError as exc:
        log_operation(
            request.user,
            "数据导出",
            "发起异步导出",
            "failed",
            str(exc),
            request,
        )
        return JsonResponse({"detail": str(exc)}, status=400)
    log_operation(
        request.user,
        "数据导出",
        "发起异步导出",
        "success",
        f"任务 {job.id}：{len(items)} 个图层",
        request,
    )
    return JsonResponse(job.as_dict(), status=202)


@require_GET
@api_login_required
def export_job_download(request, job_id: str):
    if not has_feature_perm(request.user, "catalog.export_dataresource"):
        return feature_denied_response(request.user)
    try:
        job = get_job(job_id)
        if (
            job.created_by_id
            and job.created_by_id != request.user.id
            and not request.user.is_superuser
        ):
            return JsonResponse({"detail": "无权访问该导出任务"}, status=403)
    except RasterJobError as exc:
        return JsonResponse({"detail": str(exc)}, status=404)
    if job.status != "ready":
        return JsonResponse({"detail": "导出任务尚未完成"}, status=409)
    try:
        artifact_file = open_job_artifact_for_download(job_id)
    except RasterJobError as exc:
        return JsonResponse({"detail": str(exc)}, status=404)
    filename = (job.result or {}).get(
        "filename"
    ) or f"layers-export-{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
    log_operation(
        request.user,
        "数据导出",
        "下载异步导出文件",
        "success",
        filename,
        request,
    )
    try:
        return FileResponse(
            artifact_file,
            as_attachment=True,
            filename=filename,
            content_type="application/zip",
        )
    except Exception:
        artifact_file.close()
        raise


@require_GET
@api_login_required
def layers(request):
    if not has_feature_perm(request.user, "core.browse_data"):
        return feature_denied_response(request.user)

    queryset = (
        MapLayer.objects.filter(is_active=True)
        .exclude(task_resource_q("data_resource"))
        .select_related("category", "data_resource")
    )
    layers_qs = filter_accessible_layers(queryset, request.user)
    items = [serialize_layer(item) for item in layers_qs]

    return JsonResponse({"items": items})


@require_GET
@api_login_required
def search(request):
    if not has_feature_perm(request.user, "core.browse_data"):
        return feature_denied_response(request.user)
    query = request.GET.get("q", "").strip()
    if not query:
        return JsonResponse({"resources": []})

    resource_qs = (
        DataResource.objects.filter(
            status=DataResource.Status.ACTIVE, name__icontains=query
        )
        .exclude(task_resource_q())
        .select_related("category", "category__parent")
    )
    items = [
        serialize_resource(item)
        for item in filter_accessible(resource_qs, request.user)
    ]

    return JsonResponse({"resources": items})


def _group_ids_payload(value: Any) -> list[int] | JsonResponse:
    if not isinstance(value, list):
        return JsonResponse({"detail": "accessGroupIds 必须是数组"}, status=400)
    try:
        group_ids = sorted({int(group_id) for group_id in value})
    except (TypeError, ValueError):
        return JsonResponse({"detail": "accessGroupIds 必须是整数数组"}, status=400)
    if Group.objects.filter(id__in=group_ids).count() != len(group_ids):
        return JsonResponse({"detail": "包含不存在的访问角色"}, status=400)
    return group_ids


def _positive_query_int(value: Any, *, default: int) -> int | JsonResponse:
    try:
        parsed = int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return JsonResponse({"detail": "分页参数必须是正整数"}, status=400)
    if parsed < 1:
        return JsonResponse({"detail": "分页参数必须是正整数"}, status=400)
    return parsed


def _save_workspace_conditionally(scene, payload, values):
    expected = payload.get("expectedUpdatedAt")
    try:
        stamp = parse_datetime(expected) if isinstance(expected, str) else None
    except ValueError:
        stamp = None
    if stamp is None or timezone.is_naive(stamp):
        return JsonResponse(
            {"detail": "保存须提供最后读取的 expectedUpdatedAt"}, status=400
        )
    scene.prepare_project_scope()
    scene.validate_project_relations()
    if not WorkspaceScene.objects.filter(pk=scene.pk, updated_at=stamp).update(
        **values, updated_at=timezone.now()
    ):
        return JsonResponse(
            {
                "detail": "工程已被其他会话更新。当前修改未保存，请保留修改并重新读取工程。"
            },
            status=409,
        )
    return None
