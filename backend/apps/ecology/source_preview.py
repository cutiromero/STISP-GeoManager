"""Bounded, source-versioned previews on the shared raster background worker."""

import hashlib
import json
from pathlib import Path
import threading
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth import get_user_model
from apps.core.permissions import has_feature_perm
from apps.core.storage import research_path
from apps.projects.context import selected_project_id
from apps.raster.services.jobs import get_job, start_source_preview_job
from .source_catalog import require_scene, source_query

# CONFIGURATION
MAX_FLIGHTS = 64
PREVIEW_WIDTH = 1024
PREVIEW_VERSION = "native-observation-preview-v1"
_FLIGHTS = {}
_LOCK = threading.RLock()


def authorized_source(user, scene, resource_id):
    require_scene(scene)
    if (
        not user.is_active
        or not has_feature_perm(user, "core.browse_data")
        or not has_feature_perm(user, "core.load_raster_layer")
    ):
        raise PermissionDenied("当前用户无原始图层查看权限")
    resource = source_query(user, scene).filter(pk=resource_id).first()
    if resource is None:
        raise PermissionDenied("资料不存在或当前无权使用")
    return resource


def request_preview(user, scene, resource_id, product, ordinal):
    from apps.compute.cube_inputs import cube_root, fingerprint
    from apps.compute.native_cube_reader import Cube, PRODUCTS

    if scene != "wildfire":
        raise ValidationError("当前场景不支持原生观测预览")
    resource = authorized_source(user, scene, resource_id)
    metadata = getattr(resource, "observation_metadata", None)
    if metadata is None:
        raise ValidationError("请先登记原始资料的用途与观测时间")
    point = metadata.time_points.filter(ordinal=ordinal).first()
    if (
        metadata.family != "seasfire"
        or product not in PRODUCTS
        or point is None
        or product not in point.available_products
    ):
        raise ValidationError("请选择有效的原生资料、监测内容和观测时期")
    source_version = resource.updated_at.isoformat()
    index_version = metadata.index_version
    root = cube_root(resource)
    cube = Cube(root)
    bounds = metadata.source_schema["bounds"]
    plan = cube.plan(product, ordinal, bounds, 1)
    source_fingerprint = fingerprint(root, plan)
    identity = [
        selected_project_id(),
        resource.pk,
        source_version,
        index_version,
        product,
        ordinal,
        source_fingerprint,
        PREVIEW_VERSION,
    ]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    preview_result = {
        "resourceId": resource_id,
        "resourceVersion": source_version,
        "indexVersion": index_version,
        "scene": scene,
        "bounds": [-180, -85, 180, 85],
        "product": product,
        "ordinal": ordinal,
        "key": key,
    }
    cache_target = research_path("raster", "cache", "monitoring-previews", key + ".png")

    def validate():
        actor = get_user_model().objects.get(pk=user.pk)
        current = authorized_source(actor, scene, resource_id)
        if (
            current.updated_at.isoformat() != source_version
            or current.observation_metadata.index_version != index_version
            or fingerprint(cube_root(current), plan) != source_fingerprint
        ):
            raise ValidationError("原始资料已更新，请重新选择观测时期")
        return current

    def build():
        import numpy as np
        from osgeo import gdal, osr
        import os
        import tempfile

        validate()
        cache = research_path("raster", "cache", "monitoring-previews")
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / (key + ".png")
        from apps.core.storage_locks import storage_lock

        with storage_lock(
            cache / "locks" / (str(int(key[:8], 16) % MAX_FLIGHTS) + ".lock"),
            timeout=120,
        ):
            if not target.is_file():
                values, report = Cube(root).observation(product, ordinal, bounds, 1)
                # Display clipping and log stretch apply only to this preview image.
                finite = np.isfinite(values)
                positive = values[finite & (values > 0)]
                upper = float(np.percentile(positive, 98)) if positive.size else 1
                stretch = np.clip(
                    np.log1p(np.maximum(values, 0)) / max(np.log1p(upper), 1e-12), 0, 1
                )
                stretch = np.nan_to_num(stretch)
                colors = [
                    (255 * stretch).astype("uint8"),
                    (210 * (1 - stretch)).astype("uint8"),
                    np.full(values.shape, 90, dtype="uint8"),
                    np.where(finite & (values > 0), 220, 0).astype("uint8"),
                ]
                source = gdal.GetDriverByName("MEM").Create(
                    "", values.shape[1], values.shape[0], 4, gdal.GDT_Byte
                )
                reference = osr.SpatialReference()
                reference.ImportFromEPSG(4326)
                source.SetProjection(reference.ExportToWkt())
                source.SetGeoTransform(report["grid"]["transform"])
                for position, channel in enumerate(colors, 1):
                    source.GetRasterBand(position).WriteArray(channel)
                source.GetRasterBand(4).SetColorInterpretation(gdal.GCI_AlphaBand)
                projected = gdal.Warp(
                    "",
                    source,
                    format="MEM",
                    dstSRS="EPSG:3857",
                    outputBounds=[
                        -20037508.342789244,
                        -19971868.880408566,
                        20037508.342789244,
                        19971868.880408566,
                    ],
                    width=PREVIEW_WIDTH,
                    height=PREVIEW_WIDTH,
                    resampleAlg="near",
                    multithread=False,
                )
                with tempfile.TemporaryDirectory(
                    prefix=".preview-", dir=cache
                ) as directory:
                    temporary = Path(directory) / "image.png"
                    gdal.GetDriverByName("PNG").CreateCopy(
                        str(temporary), projected
                    ).FlushCache()
                    validate()
                    os.replace(temporary, target)
                files = sorted(
                    cache.glob("*.png"), key=lambda path: path.stat().st_mtime
                )
                for path in files[:-MAX_FLIGHTS]:
                    path.unlink(missing_ok=True)
        validate()
        return preview_result, target

    with _LOCK:
        existing = _FLIGHTS.get(key)
        if existing:
            try:
                job = get_job(existing)
                if job.status in {"queued", "running"} or (
                    job.status == "ready" and Path(job.artifact_path).is_file()
                ):
                    # A shared artifact still gets an account-owned job handle.
                    if job.created_by_id == user.pk:
                        return job
            except Exception:
                pass
        validate()
        job = start_source_preview_job(
            resource.pk,
            user.pk,
            build,
            cached=(preview_result, cache_target) if cache_target.is_file() else None,
        )
        _FLIGHTS[key] = job.id
        while len(_FLIGHTS) > MAX_FLIGHTS:
            _FLIGHTS.pop(next(iter(_FLIGHTS)))
        return job


def readable_job(user, job_id):
    job = get_job(job_id)
    if (
        job.kind != "source-preview"
        or job.created_by_id != user.pk
        or job.project_tag_id != selected_project_id()
    ):
        raise PermissionDenied("当前用户无权查看该预览")
    result = job.result or {}
    resource_id = result.get("resourceId") or (result.get("inputRefs") or [{}])[0].get(
        "resourceId"
    )
    # Pending jobs use their persisted source reference and current project scene.
    resource = None
    for scene in [result["scene"]] if result.get("scene") else ["wildfire"]:
        resource = authorized_source(user, scene, resource_id)
    if result.get("resourceVersion") and (
        resource.updated_at.isoformat() != result["resourceVersion"]
        or resource.observation_metadata.index_version != result["indexVersion"]
    ):
        raise PermissionDenied("资料已更新，请重新准备预览")
    return job


def job_payload(job):
    result = job.result or {}
    return {
        "id": job.id,
        "status": job.status,
        "error": job.error,
        "imageUrl": f"/api/ecology/monitoring/source-preview/{job.id}/image/"
        if job.status == "ready"
        else None,
        "bounds": result.get("bounds"),
        "resourceId": result.get("resourceId"),
    }
