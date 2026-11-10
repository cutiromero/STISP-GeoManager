"""Task-scoped uploads for the generic geology workflow.

Uploads reuse the catalog's vector/table validation and the raster importer,
but are registered owner-only with a ``workflow-upload:<batch>`` source and no
catalog records. A batch binds to exactly one workflow when it is created.
"""

from __future__ import annotations

import io
import re
import sqlite3
import tempfile
import uuid
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F

from apps.catalog.importer import ImportDataError
from apps.catalog.models import DataResource
from apps.catalog.vector_importer import (
    discover_vector_layers,
    prepare_vector_frame,
    read_vector_layer,
    staged_vector_upload,
)
from apps.catalog.vector_storage import GEOPACKAGE_WRITE_LOCK
from apps.compute.access import require_actor
from apps.compute.packages import ComputeError
from apps.core.storage import table_data_path, vector_geopackage_path

from .models import WorkflowUpload
from .policy import require_access

SOURCE_PREFIX = "workflow-upload:"
BATCH = re.compile(r"^[0-9a-f]{32}$")
MAX_FILES = 12
MAX_TABLE_BYTES = 20 * 1024 * 1024
SAMPLE_ROWS = 1000
VECTOR_SUFFIXES = {".zip", ".gpkg", ".geojson", ".json"}
RASTER_SUFFIXES = {".tif", ".tiff"}
TABLE_SUFFIXES = {".csv", ".xlsx"}
MINERAL_HINTS = {
    "hematite": ("hematite", "chitiekuang", "赤铁"),
    "chlorite": ("chlorite", "lvnishi", "绿泥"),
    "hydromica": ("hydromica", "illite", "shuiyunmu", "水云母", "伊利"),
    "calcite": ("calcite", "fangjieshi", "方解"),
    "dolomite": ("dolomite", "baiyunshi", "白云石"),
}
COVERAGE_HINTS = ("范围", "边界", "研究区", "coverage", "extent", "boundary")


def require_upload_access(user, project_id):
    policy = require_access(user, "agent")
    if not policy.get("workflowEnabled", True):
        raise ComputeError("MH-workflow功能已关闭", 403)
    if not policy.get("operatorEnabled", False):
        raise ComputeError("智能体调用算子尚未由超级管理员开启", 403)
    require_actor(user, project_id, "catalog.add_dataresource")
    return policy


def checked_batch(value) -> str:
    if not isinstance(value, str) or not BATCH.fullmatch(value):
        raise ComputeError("上传批次号须为32位小写十六进制")
    return value


def batch_uploads(user, batch_id):
    from apps.catalog.permissions import resource_access_filter

    visible = DataResource.objects.filter(resource_access_filter(user)).values("pk")
    return WorkflowUpload.objects.select_related("resource").filter(
        owner=user,
        batch_id=checked_batch(batch_id),
        resource__status="active",
        resource_id__in=visible,
    )


def chat_claim(user, batch_id):
    from .models import AgentRun

    return AgentRun._base_manager.filter(
        owner=user, research_intent___uploadBatchId=batch_id
    ).first()


def upload_json(upload) -> dict:
    return {
        "id": str(upload.id),
        "source": upload.source,
        "batchId": upload.batch_id,
        "resourceId": upload.resource_id,
        "name": upload.resource.name,
        "fileName": upload.file_name,
        "dataType": upload.resource.data_type,
        "sizeBytes": upload.size_bytes,
        "roleHint": upload.role_hint or None,
        "profile": upload.profile,
        "workflowId": str(upload.workflow_id) if upload.workflow_id else None,
        "createdAt": upload.created_at.isoformat(),
    }


def _field_profile(frame, columns) -> list[dict]:
    sample = frame.head(SAMPLE_ROWS)
    fields = []
    for column in columns:
        series = sample[column]
        kind = (
            "integer"
            if series.dtype.kind in "iu"
            else "number"
            if series.dtype.kind == "f"
            else "text"
        )
        values = series.dropna().astype(str).str.strip()
        values = values[values != ""]
        fields.append(
            {
                "name": str(column),
                "type": kind,
                "samples": [value[:80] for value in values.unique()[:8]],
                "distinctCount": int(values.nunique()),
            }
        )
    return fields


def vector_profile(frame) -> dict:
    columns = [c for c in frame.columns if c != frame.geometry.name]
    bounds = frame.to_crs(4326).total_bounds if len(frame) and frame.crs else None
    return {
        "kind": "vector",
        "crs": frame.crs.to_string() if frame.crs else None,
        "geometryTypes": sorted({str(v) for v in frame.geom_type.dropna().unique()}),
        "featureCount": int(len(frame)),
        "bounds": [round(float(v), 6) for v in bounds] if bounds is not None else None,
        "bandCount": None,
        "width": None,
        "height": None,
        "fields": _field_profile(frame, columns),
        "warnings": [] if frame.crs else ["缺少坐标系"],
    }


def raster_profile(path) -> dict:
    import rasterio
    from rasterio.warp import transform_bounds

    with rasterio.open(path) as src:
        bounds = (
            [round(v, 6) for v in transform_bounds(src.crs, "EPSG:4326", *src.bounds)]
            if src.crs
            else None
        )
        warnings = [] if src.crs else ["缺少坐标系"]
        if (
            src.count != 1
            and src.tags().get("stisp_input_semantics") != "class_mask_stack_v1"
        ):
            warnings.append("多波段资料将按已登记的类别适配能力检查")
        return {
            "kind": "raster",
            "crs": src.crs.to_string() if src.crs else None,
            "geometryTypes": [],
            "featureCount": None,
            "bounds": bounds,
            "bandCount": src.count,
            "semanticType": src.tags().get("stisp_input_semantics", "")[:100],
            "bandNames": [value or "" for value in src.descriptions[:64]],
            "width": src.width,
            "height": src.height,
            "fields": [],
            "warnings": warnings,
        }


def table_profile(frame) -> dict:
    return {
        "kind": "table",
        "crs": None,
        "geometryTypes": [],
        "featureCount": int(len(frame)),
        "bounds": None,
        "bandCount": None,
        "width": None,
        "height": None,
        "fields": _field_profile(frame, list(frame.columns)),
        "warnings": [],
    }


def role_hint(file_name: str, profile: dict) -> str | None:
    lowered = file_name.casefold()
    if profile["kind"] == "raster":
        return next(
            (
                role
                for role, words in MINERAL_HINTS.items()
                if any(w in lowered for w in words)
            ),
            "alterations",
        )
    if profile["kind"] == "table":
        return "units"
    geometry = " ".join(profile["geometryTypes"])
    if any(
        word in lowered for word in ("蚀变", "矿物", "alteration", "mineral")
    ) or any(
        any(
            word in field.get("name", "").casefold()
            for word in ("mineral", "alteration", "矿物", "蚀变")
        )
        for field in profile.get("fields", [])
    ):
        return "alterations"
    if "Line" in geometry:
        return "faults"
    if "Polygon" in geometry:
        small = (profile["featureCount"] or 0) <= 3
        return (
            "coverage"
            if small or any(w in lowered for w in COVERAGE_HINTS)
            else "lithology"
        )
    return None


def register_vector(frame, *, user, name, source, geometry_type=None, compute=False):
    """Write one owner-only GeoPackage layer and its resource; no catalog records."""
    layer = "wf_" + uuid.uuid4().hex[:24]
    path = vector_geopackage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    options = {"geometry_type": geometry_type} if geometry_type and frame.empty else {}
    with GEOPACKAGE_WRITE_LOCK:
        frame.to_file(
            path,
            layer=layer,
            driver="GPKG",
            mode="a" if path.exists() else "w",
            **options,
        )
    return DataResource.objects.create(
        name=name[:160],
        code=layer.replace("_", "-"),
        data_type="vector",
        file_format="GPKG",
        storage_path=layer,
        coordinate_system=frame.crs.to_string() if frame.crs else "",
        source=source,
        owner_only=True,
        maintainer=user,
        item_count=len(frame),
        is_compute_result=compute,
    )


def register_table(frame, *, user, name, source, compute=False):
    relative = f"workflows/uploads/{uuid.uuid4().hex}.csv"
    path = table_data_path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")
    return DataResource.objects.create(
        name=name[:160],
        code="wf-table-" + path.stem[:24],
        data_type="table",
        file_format="CSV",
        storage_path="table/" + relative,
        source=source,
        owner_only=True,
        maintainer=user,
        size_bytes=path.stat().st_size,
        item_count=len(frame),
        is_compute_result=compute,
    )


def _store_vector(uploaded, user, name, source):
    with staged_vector_upload(uploaded) as staged:
        layers = discover_vector_layers(staged)
        if len(layers) != 1:
            raise ComputeError("一个文件请只包含一个矢量图层")
        frame, _ = read_vector_layer(layers[0])
    frame, issues = prepare_vector_frame(
        frame,
        source_crs=None,
        repair_invalid=True,
        skip_invalid=False,
        normalize_crs=False,
    )
    blocking = [item["message"] for item in issues if item.get("blocking")]
    if blocking:
        raise ComputeError("；".join(blocking)[:300])
    if frame.empty:
        raise ComputeError("没有可用的几何要素")
    profile = vector_profile(frame)
    return register_vector(frame, user=user, name=name, source=source), profile


def _store_table(uploaded, user, name, source):
    import pandas as pd

    if uploaded.size > MAX_TABLE_BYTES:
        raise ComputeError("表格文件不能超过20 MB")
    raw = uploaded.read()
    if Path(uploaded.name).suffix.lower() == ".xlsx":
        frame = pd.read_excel(io.BytesIO(raw), dtype=str, keep_default_na=False)
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030")
        frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    frame.columns = [str(c).strip() for c in frame.columns]
    if frame.empty or not len(frame.columns):
        raise ComputeError("表格没有可用的行或列")
    return register_table(frame, user=user, name=name, source=source), table_profile(
        frame
    )


def _store_raster(uploaded, user, name, source):
    from apps.raster.services.importer import (
        RasterImportError,
        import_raster_file,
        validate_raster_upload_size,
    )

    try:
        validate_raster_upload_size(uploaded)
    except RasterImportError as exc:
        raise ComputeError(str(exc)) from exc
    with tempfile.TemporaryDirectory(prefix="geomanager-wf-") as directory:
        path = Path(directory) / ("upload" + Path(uploaded.name).suffix.lower())
        with path.open("wb") as output:
            for chunk in uploaded.chunks():
                output.write(chunk)
        profile = raster_profile(path)
        if not profile["crs"] or profile["bandCount"] < 1:
            raise ComputeError("栅格资料须为带坐标系和有效波段的GeoTIFF")
        try:
            dataset = import_raster_file(
                path,
                name=name,
                raster_kind="categorical",
                uploader_id=user.id,
                owner_only=True,
                resource_source=source,
            )
        except RasterImportError as exc:
            raise ComputeError(str(exc)[:300]) from exc
    return dataset.data_resource, profile


@transaction.atomic
def store_upload(user, project_id, uploaded, batch_id) -> WorkflowUpload:
    batch_id = checked_batch(batch_id)
    get_user_model().objects.filter(pk=user.pk).update(last_login=F("last_login"))
    require_upload_access(user, project_id)
    existing = WorkflowUpload.objects.filter(owner=user, batch_id=batch_id)
    if chat_claim(user, batch_id):
        raise ComputeError("该批次已发送到对话，请新建批次", 409)
    if existing.filter(workflow__isnull=False).exists():
        raise ComputeError("该批次资料已用于任务，请新建批次", 409)
    if existing.filter(resource__status="active").count() >= MAX_FILES:
        raise ComputeError(f"每个任务最多上传{MAX_FILES}个文件")
    file_name = Path(uploaded.name or "upload").name[:255]
    suffix = Path(file_name).suffix.lower()
    name = Path(file_name).stem.strip() or "上传资料"
    source = SOURCE_PREFIX + batch_id
    try:
        if suffix in VECTOR_SUFFIXES:
            resource, profile = _store_vector(uploaded, user, name, source)
        elif suffix in TABLE_SUFFIXES:
            resource, profile = _store_table(uploaded, user, name, source)
        elif suffix in RASTER_SUFFIXES:
            resource, profile = _store_raster(uploaded, user, name, source)
        else:
            raise ComputeError(
                "支持Shapefile ZIP、GeoPackage、GeoJSON、GeoTIFF、CSV和XLSX"
            )
    except ImportDataError as exc:
        raise ComputeError(str(exc)[:300]) from exc
    with transaction.atomic():
        resource.owner_only, resource.maintainer, resource.source = True, user, source
        resource.description = f"MH-workflow任务资料，原文件：{file_name}"
        resource.size_bytes = uploaded.size or resource.size_bytes
        resource.save()
        return WorkflowUpload.objects.create(
            owner=user,
            batch_id=batch_id,
            resource=resource,
            file_name=file_name,
            size_bytes=uploaded.size or 0,
            role_hint=role_hint(file_name, profile) or "",
            profile=profile,
        )


def delete_upload(user, upload_id) -> None:
    with transaction.atomic():
        upload = (
            WorkflowUpload.objects.select_for_update()
            .select_related("resource")
            .filter(pk=upload_id, owner=user)
            .first()
        )
        if upload is None:
            raise ComputeError("上传资料不存在", 404)
        if upload.workflow_id or chat_claim(user, upload.batch_id):
            raise ComputeError("资料已用于任务，作为任务依据保留", 409)
        resource = upload.resource
        upload.delete()
        if upload.source == "upload":
            resource.status = "inactive"
            resource.save(update_fields=["status", "updated_at"])


def catalog_resources(user, project_id):
    from .resource_discovery import discover_resources
    from apps.compute.project_tools import GEOLOGY_PROJECT_CODES
    from apps.projects.models import Project

    policy = require_upload_access(user, project_id)
    if not Project.objects.filter(
        pk=project_id, code__in=GEOLOGY_PROJECT_CODES
    ).exists():
        raise ComputeError("请在逻辑推理项目选择系统数据", 400)
    return discover_resources(user, policy).filter(
        project_tag_id=project_id,
        data_type__in={"vector", "raster", "table"},
    )


def catalog_profile(resource):
    if resource.data_type == "vector":
        from .generic_inputs import _read

        return vector_profile(_read(resource))
    if resource.data_type == "table":
        from apps.catalog.nongeo import _resource_dataframe

        frame, total, _ = _resource_dataframe(resource, limit=SAMPLE_ROWS, offset=0)
        profile = table_profile(frame)
        profile["featureCount"] = total
        return profile
    from apps.core.storage import raster_source_path
    from apps.raster.models import RasterDataset

    dataset = RasterDataset.objects.filter(
        data_resource=resource, status="ready"
    ).first()
    if dataset is None:
        raise ComputeError("栅格尚未处理完成")
    profile = raster_profile(raster_source_path(dataset.source_relative_path))
    if not profile["crs"] or profile["bandCount"] < 1:
        raise ComputeError("栅格资料须具有坐标系和有效波段")
    return profile


@transaction.atomic
def add_catalog_references(user, project_id, batch_id, resource_ids):
    from pyogrio.errors import DataLayerError, DataSourceError

    batch_id = checked_batch(batch_id)
    if (
        not isinstance(resource_ids, list)
        or not 1 <= len(resource_ids) <= MAX_FILES
        or any(type(value) is not int or value < 1 for value in resource_ids)
        or len(set(resource_ids)) != len(resource_ids)
    ):
        raise ComputeError("请选择1至12份不重复的系统数据")
    get_user_model().objects.filter(pk=user.pk).update(last_login=F("last_login"))
    available = catalog_resources(user, project_id)
    existing = WorkflowUpload.objects.filter(owner=user, batch_id=batch_id)
    if chat_claim(user, batch_id) or existing.filter(workflow__isnull=False).exists():
        raise ComputeError("该批次已用于任务，请新建批次", 409)
    resources = {item.id: item for item in available.filter(pk__in=resource_ids)}
    if len(resources) != len(resource_ids):
        raise ComputeError("资源不存在、已失效或无权访问", 404)
    prior = {item.resource_id: item for item in existing}
    if len(prior) + len(set(resource_ids) - prior.keys()) > MAX_FILES:
        raise ComputeError(f"每个任务最多选择{MAX_FILES}份资料")
    result = []
    for identity in resource_ids:
        resource = resources[identity]
        item = prior.get(identity)
        if item is None:
            try:
                profile = catalog_profile(resource)
            except (
                OSError,
                ValueError,
                sqlite3.Error,
                DataSourceError,
                DataLayerError,
            ) as exc:
                raise ComputeError("无法读取系统数据资料画像，请核对资源文件") from exc
            item = WorkflowUpload.objects.create(
                owner=user,
                project_tag_id=resource.project_tag_id,
                batch_id=batch_id,
                resource=resource,
                source="catalog",
                file_name=resource.name,
                size_bytes=resource.size_bytes or 0,
                profile=profile,
                role_hint=role_hint(resource.name, profile) or "",
            )
        result.append(item)
    return result


def bind_batch(workflow, user, batch_id, inputs) -> None:
    """Attach an unbound batch to a new workflow; inputs must come from it."""
    claim = chat_claim(user, batch_id)
    if claim and workflow.plan.get("chatExecution", {}).get("originRunId") != claim.id:
        raise ComputeError("上传批次已关联其他对话研究任务", 409)
    uploads = list(
        batch_uploads(user, batch_id)
        .select_for_update()
        .filter(project_tag_id=workflow.project_tag_id)
    )
    if not uploads or any(upload.workflow_id for upload in uploads):
        raise ComputeError("上传批次不存在或已用于其他任务", 409)
    available = {upload.resource_id for upload in uploads}
    if not set(inputs.values()) <= available:
        raise ComputeError("资料角色只能选择本次任务上传的资料")
    WorkflowUpload.objects.filter(pk__in=[u.pk for u in uploads]).update(
        workflow=workflow
    )
