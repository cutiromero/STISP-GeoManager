import json
from pathlib import Path

from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from apps.audit.service import log_operation
from apps.core.api import api_login_required
from apps.core.storage import StoragePathError, raster_source_path
from apps.catalog.models import MapLayer
from apps.catalog.permissions import related_access_filter, user_can_access
from apps.catalog.taxonomy import TaxonomyError, resolve_data_category
from apps.core.permissions import feature_denied_response, has_feature_perm
from apps.raster.models import RasterDataset
from apps.raster.permissions import can_manage_raster_data
from apps.raster.services import (
    RasterImportError,
    RasterJobError,
    RasterRenderError,
    RasterTileOutsideExtent,
    build_static_xyz_tile_pyramid,
    classify_unique_values,
    get_job,
    import_raster_file,
    register_tile_style,
    render_xyz_tile,
    serialize_raster_dataset,
    start_import_job,
    start_render_job,
    start_scan_job,
    store_uploaded_source_file,
)
from apps.raster.services.package import (
    preview_uploaded_raster_package,
    store_uploaded_raster_package,
)
from apps.raster.services.renderer import RASTER_RENDERER_VERSION


@require_POST
@api_login_required
def preview_import(request):
    if not can_manage_raster_data(request.user):
        return feature_denied_response(request.user)
    uploaded_files = request.FILES.getlist("files")
    if not uploaded_files:
        legacy_file = request.FILES.get("file")
        uploaded_files = [legacy_file] if legacy_file is not None else []
    try:
        result = preview_uploaded_raster_package(
            uploaded_files, str(request.POST.get("primaryFileName") or "")
        )
    except (RasterImportError, OSError) as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return JsonResponse(result)


@require_POST
@api_login_required
def render(request):
    if not has_feature_perm(request.user, "core.load_raster_layer"):
        return feature_denied_response(request.user)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"detail": "请求体不是有效 JSON"}, status=400)

    rules_mode = str(payload.get("rulesMode") or "default")
    if rules_mode == "custom" and not has_feature_perm(
        request.user, "core.custom_symbolization"
    ):
        return feature_denied_response(request.user)
    rules = payload.get("rules") if rules_mode == "custom" else None
    layer = get_object_or_404(MapLayer, pk=payload.get("layerId"), is_active=True)
    if not user_can_access(layer, request.user):
        return JsonResponse({"detail": "无权访问该图层"}, status=403)

    try:
        dataset = RasterDataset.objects.filter(
            map_layer=layer, status=RasterDataset.Status.READY
        ).first()
        if not dataset:
            return JsonResponse(
                {"detail": "该图层没有已预处理的栅格数据集"}, status=400
            )
        result = register_tile_style(dataset, rules or layer.raster_rules)
        if dataset.raster_kind == RasterDataset.RasterKind.CATEGORICAL:
            build_static_xyz_tile_pyramid(dataset, str(result["styleHash"]))
    except (OSError, ValueError, RasterRenderError) as exc:
        log_operation(
            request.user,
            "栅格管理",
            "注册栅格渲染样式",
            "failed",
            str(exc),
            request,
        )
        return JsonResponse({"detail": str(exc)}, status=400)
    log_operation(
        request.user,
        "栅格管理",
        "注册栅格渲染样式",
        "success",
        f"{dataset.name}：{result.get('styleHash', '')}",
        request,
    )
    return JsonResponse(result)


@require_POST
@api_login_required
def render_async(request):
    if not has_feature_perm(request.user, "core.load_raster_layer"):
        return feature_denied_response(request.user)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"detail": "请求体不是有效 JSON"}, status=400)

    rules_mode = str(payload.get("rulesMode") or "default")
    if rules_mode == "custom" and not has_feature_perm(
        request.user, "core.custom_symbolization"
    ):
        return feature_denied_response(request.user)
    rules = payload.get("rules") if rules_mode == "custom" else None
    layer_id = payload.get("layerId")
    dataset_id = payload.get("datasetId")
    layer = (
        MapLayer.objects.filter(pk=layer_id, is_active=True).first()
        if layer_id
        else None
    )
    dataset = (
        RasterDataset.objects.filter(pk=dataset_id)
        .select_related("data_resource", "map_layer")
        .first()
        if dataset_id
        else None
    )
    if layer and not user_can_access(layer, request.user):
        return JsonResponse({"detail": "无权访问该图层"}, status=403)
    if (
        dataset
        and dataset.data_resource
        and not user_can_access(dataset.data_resource, request.user)
    ):
        return JsonResponse({"detail": "无权访问该数据资源"}, status=403)
    if not layer and not dataset:
        return JsonResponse({"detail": "缺少 layerId 或 datasetId"}, status=400)

    try:
        job = start_render_job(
            layer_id=layer.id if layer else None,
            dataset_id=dataset.id if dataset else None,
            rules=rules,
            created_by_id=request.user.id,
        )
        if not request.user.is_authenticated:
            request.session["public_render_jobs"] = request.session.get(
                "public_render_jobs", []
            )[-19:] + [job.id]
    except (ValueError, RasterRenderError) as exc:
        log_operation(
            request.user,
            "栅格管理",
            "发起栅格渲染任务",
            "failed",
            str(exc),
            request,
        )
        return JsonResponse({"detail": str(exc)}, status=400)
    log_operation(
        request.user,
        "栅格管理",
        "发起栅格渲染任务",
        "success",
        f"任务 {job.id}",
        request,
    )
    return JsonResponse(job.as_dict(), status=202)


@require_POST
@api_login_required
def unique_values(request):
    if not has_feature_perm(request.user, "core.custom_symbolization"):
        return feature_denied_response(request.user)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"detail": "请求体不是有效 JSON"}, status=400)

    dataset = (
        RasterDataset.objects.filter(pk=payload.get("datasetId"))
        .select_related("data_resource")
        .first()
    )
    if not dataset:
        return JsonResponse({"detail": "栅格数据集不存在"}, status=404)
    if dataset.data_resource and not user_can_access(
        dataset.data_resource, request.user
    ):
        return JsonResponse({"detail": "无权访问该数据资源"}, status=403)

    try:
        band = int(payload.get("band", 1))
        result = classify_unique_values(dataset, band)
    except (ValueError, RasterRenderError) as exc:
        log_operation(
            request.user,
            "栅格管理",
            "统计栅格唯一值",
            "failed",
            str(exc),
            request,
        )
        return JsonResponse({"detail": str(exc)}, status=400)
    log_operation(
        request.user,
        "栅格管理",
        "统计栅格唯一值",
        "success",
        f"{dataset.name}：第 {band} 波段",
        request,
    )
    return JsonResponse(result)


@require_POST
@api_login_required
def import_raster(request):
    if not can_manage_raster_data(request.user):
        return feature_denied_response(request.user)
    uploaded_files = request.FILES.getlist("files")
    legacy_file = request.FILES.get("file")
    is_legacy_upload = not uploaded_files and legacy_file is not None
    if not uploaded_files and legacy_file is not None:
        uploaded_files = [legacy_file]
    if uploaded_files:
        try:
            raw_payload = str(request.POST.get("payload") or "").strip()
            payload = json.loads(raw_payload) if raw_payload else {}
            if not isinstance(payload, dict):
                raise RasterImportError("payload 必须是 JSON 对象")
            category_code = _validated_category_code(payload)
            if is_legacy_upload and not raw_payload and legacy_file is not None:
                display_name = (
                    str(request.POST.get("name") or "").strip()
                    or Path(legacy_file.name or "uploaded-raster").stem
                )
                source_path = store_uploaded_source_file(legacy_file)
                job = start_import_job(
                    str(source_path),
                    name=display_name,
                    cleanup_upload_on_failure=True,
                    uploader_id=request.user.id,
                    created_by_id=request.user.id,
                    category_code=category_code,
                )
                source_manifest = []
                checksum = ""
            else:
                primary_file_name = str(payload.get("primaryFileName") or "")
                source_path, source_manifest, checksum = store_uploaded_raster_package(
                    uploaded_files, primary_file_name
                )
                display_name = (
                    str(payload.get("name") or request.POST.get("name") or "").strip()
                    or Path(source_path.name).stem
                )
                access_group_ids = [
                    int(value) for value in payload.get("accessGroupIds") or []
                ]
                job = start_import_job(
                    str(source_path),
                    name=display_name,
                    cleanup_upload_on_failure=True,
                    source_manifest=source_manifest,
                    source_checksum_sha256=checksum,
                    raster_kind=str(payload.get("rasterKind") or "imagery"),
                    resampling=str(payload.get("resampling") or "bilinear"),
                    default_rules=payload.get("defaultRules")
                    if isinstance(payload.get("defaultRules"), dict)
                    else None,
                    uploader_id=request.user.id,
                    access_group_ids=access_group_ids,
                    category_code=category_code,
                    created_by_id=request.user.id,
                )
        except (
            json.JSONDecodeError,
            TypeError,
            ValueError,
            RasterImportError,
            OSError,
        ) as exc:
            log_operation(
                request.user,
                "栅格管理",
                "上传栅格文件",
                "failed",
                str(exc),
                request,
            )
            return JsonResponse({"detail": str(exc)}, status=400)
        log_operation(
            request.user,
            "栅格管理",
            "发起栅格导入任务",
            "success",
            f"任务 {job.id}：{source_path.name}",
            request,
        )
        return JsonResponse(job.as_dict(), status=202)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"detail": "请求体不是有效 JSON"}, status=400)
    source_relative = str(payload.get("sourcePath") or "").strip()
    try:
        category_code = _validated_category_code(payload)
    except RasterImportError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    if not source_relative:
        log_operation(
            request.user,
            "栅格管理",
            "导入栅格文件",
            "failed",
            "缺少源文件路径",
            request,
        )
        return JsonResponse({"detail": "缺少 sourcePath"}, status=400)
    if payload.get("async", True):
        try:
            source_path = raster_source_path(source_relative)
        except StoragePathError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        job = start_import_job(
            str(source_path),
            name=str(payload.get("name") or ""),
            created_by_id=request.user.id,
            uploader_id=request.user.id,
            category_code=category_code,
        )
        log_operation(
            request.user,
            "栅格管理",
            "发起栅格导入任务",
            "success",
            f"任务 {job.id}：{source_relative}",
            request,
        )
        return JsonResponse(job.as_dict(), status=202)
    try:
        try:
            source_path = raster_source_path(source_relative)
        except StoragePathError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        dataset = import_raster_file(
            source_path,
            name=str(payload.get("name") or ""),
            uploader_id=request.user.id,
            category_code=category_code,
        )
    except (RasterImportError, OSError) as exc:
        log_operation(
            request.user,
            "栅格管理",
            "导入栅格文件",
            "failed",
            str(exc),
            request,
        )
        return JsonResponse({"detail": str(exc)}, status=400)
    log_operation(
        request.user,
        "栅格管理",
        "导入栅格文件",
        "success",
        dataset.name,
        request,
    )
    return JsonResponse(serialize_raster_dataset(dataset), status=201)


def _validated_category_code(payload: dict) -> str:
    category_code = str(payload.get("categoryCode") or "").strip()
    if not category_code:
        return ""
    try:
        resolve_data_category(category_code)
    except TaxonomyError as exc:
        raise RasterImportError(str(exc)) from exc
    return category_code


@require_POST
@api_login_required
def scan_sources(request):
    if not can_manage_raster_data(request.user):
        return feature_denied_response(request.user)
    job = start_scan_job(created_by_id=request.user.id)
    return JsonResponse(job.as_dict(), status=202)


@require_GET
@api_login_required
def datasets(request):
    if not has_feature_perm(request.user, "core.browse_data"):
        return feature_denied_response(request.user)
    queryset = RasterDataset.objects.select_related(
        "data_resource", "map_layer"
    ).prefetch_related("data_resource__access_groups")
    if not request.user.is_superuser:
        queryset = queryset.filter(
            Q(data_resource__isnull=True)
            | related_access_filter(request.user, "data_resource")
        ).distinct()
    items = [serialize_raster_dataset(dataset) for dataset in queryset]
    return JsonResponse({"items": items})


@require_GET
@api_login_required
def job_status(request, job_id: str):
    try:
        job = get_job(job_id)
        if not request.user.is_authenticated and (
            job.kind != "render"
            or job_id not in request.session.get("public_render_jobs", [])
        ):
            return JsonResponse({"detail": "无权查看该任务"}, status=403)
        if (
            job.created_by_id
            and job.created_by_id != request.user.id
            and not request.user.is_superuser
        ):
            return JsonResponse({"detail": "无权查看该任务"}, status=403)
        return JsonResponse(job.as_dict())
    except RasterJobError as exc:
        return JsonResponse({"detail": str(exc)}, status=404)


@require_GET
@api_login_required
def tile(request, dataset_id: int, style_hash: str, z: int, x: int, y: int):
    if not has_feature_perm(request.user, "core.load_raster_layer"):
        return feature_denied_response(request.user)
    dataset = get_object_or_404(
        RasterDataset.objects.select_related("data_resource"), pk=dataset_id
    )
    if dataset.data_resource and not user_can_access(
        dataset.data_resource, request.user
    ):
        return JsonResponse({"detail": "无权访问该数据资源"}, status=403)
    try:
        content = render_xyz_tile(dataset_id, style_hash, z, x, y)
    except RasterTileOutsideExtent:
        return HttpResponse(status=204)
    except RasterRenderError as exc:
        return JsonResponse({"detail": str(exc)}, status=404)
    response = HttpResponse(content, content_type="image/png")
    # The URL is content-addressed by COG fingerprint, rules and renderer
    # version, so a completed static categorical pyramid is safe to retain.
    response["Cache-Control"] = "private, max-age=31536000, immutable"
    response["ETag"] = f'"{style_hash}-rv{RASTER_RENDERER_VERSION}-{z}-{x}-{y}"'
    return response
