"""Bounded, revision-bound exports through the existing geospatial job queue."""

import hashlib
import json

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.utils.dateparse import parse_datetime
from copy import deepcopy
import shutil
import tempfile

from apps.catalog.data_query import query_resource
from apps.catalog.export import validate_epsg
from apps.catalog.export_access import validate_download
from apps.compute.packages import ComputeError
from apps.core.storage import app_path
from apps.core.storage_locks import storage_lock
from apps.raster.services.jobs import get_job, get_job_artifact_path, start_export_job
from apps.raster.services.exceptions import RasterJobError
from .models import AgentRun, AgentToolCall
from .policy import fresh_user, require_access
from .resource_discovery import resolve_discoverable_resource
from .workspace_tools import context, versions

MAX_EXPORTS_PER_RUN = 3
MAX_VECTOR_FEATURES = 5000
MAX_VECTOR_BYTES = 10 * 1024 * 1024
MAX_RASTER_SOURCE_BYTES = 512 * 1024 * 1024


def read_export(run, user, policy, identity):
    recorded = (
        AgentToolCall.objects.filter(
            tool="export_map_workspace", run__owner=user, result_refs__jobId=identity
        )
        .order_by("created_at")
        .first()
    )
    if recorded is None:
        raise ComputeError("导出任务不存在或未登记为本人的平台操作", 404)
    workspace_id = recorded.result_refs.get("workspaceId")
    _, _, resources = context(run, user, policy, workspace_id)
    try:
        job = get_job(identity)
    except RasterJobError as error:
        raise ComputeError("导出任务不存在或已过期", 404) from error
    if (
        job.kind != "export"
        or job.created_by_id != user.pk
        or job.project_tag_id != run.project_tag_id
    ):
        raise ComputeError("导出任务不存在或无权访问", 404)
    validate_download(job, user)
    available = False
    if job.status == "ready":
        try:
            available = get_job_artifact_path(job.id).is_file()
        except RasterJobError:
            pass
    detail = (
        "导出文件已就绪"
        if available
        else "文件已过期或不可用，可在核对资料后明确重试"
        if job.status == "ready"
        else "导出失败，请核对资料和任务状态后决定是否重试"
        if job.status == "failed"
        else "已受理，正在等待或处理导出"
    )
    return {
        "jobId": job.id,
        "workspaceId": workspace_id,
        "status": job.status,
        "cancelRequested": job.cancel_requested,
        "stage": job.stage[:160],
        "progressPercent": job.progress_percent,
        "artifactAvailable": available,
        "downloadUrl": f"/api/catalog/export/jobs/{job.id}/download/?projectTagId={run.project_tag_id}"
        if available
        else None,
        "sourceVersions": recorded.result_refs.get("sourceVersions", []),
        "detail": "正在停止，当前I/O到保存点后结束"
        if job.cancel_requested and job.status in {"queued", "running"}
        else "导出已取消，未提供下载文件"
        if job.cancel_requested
        else detail,
    }, resources


def _items(layers, snapshot, only_visible, *, materialize=True, before_read=None):
    result = []
    payload_bytes = 0
    raster_bytes = 0
    visibility = {}

    def walk(value, parent=True):
        if isinstance(value, dict):
            visible = parent and value.get("visible", True)
            if isinstance(value.get("id"), str):
                visibility[value["id"]] = visible
            for child in value.get("children", []):
                walk(child, visible)
        elif isinstance(value, list):
            for child in value:
                walk(child, parent)

    walk(snapshot.get("groups", []))
    for layer, resource in layers:
        if only_visible and not visibility.get(layer["id"], True):
            continue
        item = {
            "name": str(layer.get("name", resource.name))[:160],
            "resourceId": resource.pk,
            "layerType": layer["layerType"],
        }
        if materialize and before_read is not None:
            before_read(resource)
        if item["layerType"] == "raster":
            item["datasetId"] = layer["rasterDatasetId"]
        elif materialize:
            query = layer.get("query", {})
            data = query_resource(
                resource,
                {
                    "attributeFilters": query.get("attributeFilters", []),
                    "spatialFilter": query.get("spatialFilter"),
                    "displayGeometry": False,
                    "limit": MAX_VECTOR_FEATURES,
                },
            )
            if data["limitExceeded"] or data["returnedCount"] != data["totalCount"]:
                raise ComputeError(
                    "矢量范围超过完整导出预算或存在不可导出几何，请在工程中收紧范围后重试"
                )
            item["geojson"] = data["geojson"]
            payload_bytes += len(
                json.dumps(data["geojson"], ensure_ascii=False).encode()
            )
            if payload_bytes > MAX_VECTOR_BYTES:
                raise ComputeError("矢量导出内容超过10MiB准备预算，请收紧工程范围")
        if materialize and layer["layerType"] == "raster":
            from apps.compute.input_versions import source_version

            source = source_version(resource)["source"]
            raster_bytes += source["file"][2] + sum(
                value[2]
                for value in source.get("dependencies", {}).values()
                if value is not None
            )
            if raster_bytes > MAX_RASTER_SOURCE_BYTES:
                raise ComputeError(
                    "原始栅格超过本次512MiB导出预算，请先生成受控区域成果"
                )
        result.append(item)
    if not result:
        raise ComputeError("工程没有需要导出的可见图层")
    if materialize and min(
        shutil.disk_usage(tempfile.gettempdir()).free,
        shutil.disk_usage(app_path("cache")).free,
    ) < max(512 * 1024 * 1024, 3 * (raster_bytes + payload_bytes)):
        raise ComputeError("临时导出空间不足，未发布导出文件")
    return result


def export_workspace(run, user, policy, args, call):
    scene, layers, resources = context(run, user, policy, args["workspaceId"])
    if scene.updated_at != parse_datetime(args["expectedUpdatedAt"]):
        raise ComputeError("工程已变化，请重新读取后导出", 409)
    source_versions = versions(resources)
    expected = {
        item["resourceId"]: item["versionKey"] for item in args["expectedSources"]
    }
    if len(expected) != len(args["expectedSources"]):
        raise ComputeError("资料版本引用重复")
    if {item["resourceId"]: item["versionKey"] for item in source_versions} != expected:
        raise ComputeError("资料版本已变化，请重新读取工程后导出", 409)
    if not all(item["available"] for item in source_versions):
        raise ComputeError("工程原始资料不可读，未创建导出任务")
    options = {
        "workspaceId": scene.pk,
        "revision": scene.updated_at.isoformat(),
        "sources": source_versions,
        "onlyVisible": args.get("onlyVisible", True),
        "reproject": args.get("reproject", False),
        "epsg": args.get("epsg", 4326),
        "format": args.get("format", "geojson"),
        "retryOfJobId": args.get("retryOfJobId"),
    }
    if options["reproject"]:
        validate_epsg(options["epsg"])
    key = (
        "export-"
        + hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()
    )
    bucket = int(hashlib.sha256(f"{run.pk}:{key}".encode()).hexdigest()[:8], 16) % 256

    def source_guard():
        actor = fresh_user(user.pk)
        current_policy = require_access(actor, "agent", run.model)
        current = [
            resolve_discoverable_resource(
                actor, current_policy, item["resourceId"], run.resource_ids
            )
            for item in source_versions
        ]
        if versions(current) != source_versions:
            raise ComputeError("导出期间资料版本已变化，成果未发布", 409)

    def resource_guard(resource):
        actor = fresh_user(user.pk)
        current_policy = require_access(actor, "agent", run.model)
        current = resolve_discoverable_resource(
            actor, current_policy, resource.pk, run.resource_ids
        )
        expected = next(
            item for item in source_versions if item["resourceId"] == resource.pk
        )
        if versions([current]) != [expected]:
            raise ComputeError("导出读取前资料版本已变化", 409)

    with storage_lock(app_path("cache", "agent-exports", f"{bucket}.lock"), timeout=30):
        prior = AgentToolCall.objects.filter(run=run, idempotency_key=key).first()
        if prior and prior.result_refs.get("jobId"):
            result, resources = read_export(
                run, user, policy, prior.result_refs["jobId"]
            )
            if result["status"] == "failed" or (
                result["status"] == "ready" and not result["artifactAvailable"]
            ):
                raise ComputeError(
                    "原导出失败或文件过期，请明确提供retryOfJobId后重试", 409
                )
            return {**result, "replayed": True}, [
                (resource, {"workspaceId": scene.pk}) for resource in resources
            ] + [(None, result)]
        if options["retryOfJobId"]:
            previous, _ = read_export(run, user, policy, options["retryOfJobId"])
            if (
                previous["workspaceId"] != scene.pk
                or previous["status"] not in {"failed", "ready"}
                or previous["artifactAvailable"]
            ):
                raise ComputeError("只能明确重试同一工程已失败或文件不可用的导出")
        if (
            AgentToolCall.objects.filter(
                run=run,
                tool="export_map_workspace",
                idempotency_key__startswith="export-",
            ).count()
            >= MAX_EXPORTS_PER_RUN
        ):
            raise ComputeError(
                "本轮已达到3次导出上限，请结束当前任务后重新明确操作范围"
            )
        frozen_snapshot = deepcopy(scene.snapshot)
        items = _items(
            layers, frozen_snapshot, options["onlyVisible"], materialize=False
        )
        source_guard()
        with transaction.atomic():
            get_user_model().objects.filter(pk=user.pk, is_active=True).update(
                last_login=F("last_login")
            )
            actor = fresh_user(user.pk)
            current_policy = require_access(actor, "agent", run.model)
            current_scene, _, _ = context(run, actor, current_policy, scene.pk)
            if current_scene.updated_at != scene.updated_at:
                raise ComputeError("工程已变化，导出未提交", 409)
            if not AgentRun.objects.filter(
                pk=run.pk, cancel_requested=False, status="running"
            ).exists():
                raise ComputeError("本轮已停止，导出未提交", 409)
            if (
                AgentToolCall.objects.filter(
                    run=run,
                    tool="export_map_workspace",
                    idempotency_key__startswith="export-",
                ).count()
                >= MAX_EXPORTS_PER_RUN
            ):
                raise ComputeError(
                    "本轮已达到3次导出上限，请结束当前任务后重新明确操作范围"
                )
            AgentToolCall.objects.filter(pk=call.pk).update(idempotency_key=key)
            job = start_export_job(
                items=items,
                epsg=options["epsg"] if options["reproject"] else None,
                reproject=options["reproject"],
                clip_geometry=None,
                vector_format=options["format"],
                created_by_id=user.pk,
                defer_submission=True,
                source_guard=source_guard,
                items_builder=lambda cancel_guard: _items(
                    layers,
                    frozen_snapshot,
                    options["onlyVisible"],
                    before_read=lambda resource: (
                        cancel_guard(),
                        resource_guard(resource),
                    ),
                ),
                retain_downloads=True,
            )
            AgentToolCall.objects.filter(pk=call.pk).update(
                result_refs={
                    "workspaceId": scene.pk,
                    "jobId": job.id,
                    "sourceVersions": source_versions,
                }
            )
        result, resources = read_export(run, user, policy, job.id)
        return result, [
            (resource, {"workspaceId": scene.pk}) for resource in resources
        ] + [(None, result)]
