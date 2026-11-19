"""Explicit publication and read-only monitoring projection."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.catalog.models import DataResource
from apps.catalog.monitoring_metadata import period_payload
from apps.catalog.serializers import serialize_resource
from apps.compute.access import require_actor, task_access
from apps.compute.models import ComputeImport
from apps.compute.packages import ComputeError
from apps.compute.quality import require_automatic_quality
from apps.projects.context import selected_project_id
from apps.projects.models import Project
from apps.raster.models import RasterDataset, RasterStyle
from apps.raster.services.renderer import register_tile_style, tile_style_is_ready
from apps.raster.services.exceptions import RasterRenderError
from .models import RemoteSensingProduct
from .monitoring import configured_scenes, visible_resources, normalize_product, METRICS

# Display overview is intentionally bounded. Rotation changes the view, not the data.
MAX_PRODUCTS = 240
MAX_REGIONS = 60
PUBLISHABLE = {
    ("landcover-unet-infer", "classification"): "landcover",
    ("spartina-rf-infer", "classification"): "spartina",
    ("wildfire-observe", "observation"): "wildfire",
}


def official_products():
    # Existing registry entries are published products, including imported
    # handoff results. A ready ComputeImport alone never qualifies.
    return RemoteSensingProduct.objects.filter(
        product_type__startswith="monitoring_",
        data_resource__isnull=False,
    )


def register_output(user, output_id):
    project_id = selected_project_id()
    require_actor(
        user, project_id, "catalog.add_dataresource", "core.load_raster_layer"
    )
    record = (
        ComputeImport.objects.filter(
            output_id=output_id,
            output__task__project_tag_id=project_id,
            status="ready",
            output__expired=False,
            output__task__status="succeeded",
            output__task__trial=False,
            resource__is_compute_result=True,
            resource__status="active",
            resource__project_tag_id=project_id,
        )
        .select_related("output__task__version__algorithm", "resource")
        .first()
    )
    if (
        record is None
        or record.requested_by_id != user.pk
        or record.output.task.owner_id != user.pk
    ):
        raise ComputeError("找不到本人已入库且可用的正式登记成果", 404)
    task_access(record.output.task, user)
    from apps.agent.models import AgentWorkflowStep

    if (
        AgentWorkflowStep.objects.filter(
            compute_task_id=record.output.task_id,
            workflow__project_tag_id=project_id,
            workflow__owner_id=user.pk,
            workflow__workflow_type="business_flow",
        )
        .exclude(workflow__status="succeeded")
        .exists()
    ):
        raise ComputeError("主 Agent 尚未完成本次业务流的成果核验", 409)

    scene = PUBLISHABLE.get(
        (record.output.task.version.algorithm.identifier, record.output.key)
    )
    if scene is None or scene not in configured_scenes(
        Project.objects.get(pk=project_id)
    ):
        raise ComputeError("只有本项目监测流程的主地图成果可以登记")
    require_automatic_quality(record.output)
    from .product_sources import source_resource_ids

    sources = set(source_resource_ids(record.output.task))
    if not sources or set(
        visible_resources(user, sources | {record.resource_id}).values_list(
            "pk", flat=True
        )
    ) != sources | {record.resource_id}:
        raise PermissionDenied("无法访问正式成果或其原始资料")
    # Keep publication distinct from import and stage display outside long SQL writes.
    from importlib import import_module

    domain = import_module(f"apps.ecology.{scene}")
    dataset = (
        RasterDataset.objects.filter(
            data_resource_id=record.resource_id, status="ready"
        )
        .order_by("-pk")
        .first()
    )
    if dataset is None:
        raise ComputeError("栅格展示资料尚未准备就绪")
    try:
        style = register_tile_style(dataset, dataset.default_rules)
        if not tile_style_is_ready(dataset, style["styleHash"]):
            from apps.raster.services.renderer import build_static_xyz_tile_pyramid

            build_static_xyz_tile_pyramid(dataset, style["styleHash"])
    except (OSError, ValueError, RasterRenderError) as error:
        raise ComputeError(f"正式地图准备失败，尚未公开：{error}") from error
    with transaction.atomic():
        result = domain.register_import(record.pk)
        if result is None:
            raise ComputeError("该成果不符合当前监测场景的登记条件")
        product, _ = result
        product = RemoteSensingProduct.objects.select_for_update().get(pk=product.pk)
        if not product.metadata.get("formalDisplay"):
            product.metadata = {
                **product.metadata,
                "formalDisplay": {"version": 1, "display": style},
            }
            product.save(update_fields=["metadata"])
        return product


def region_key(item, bounds):
    # The same observation footprint may come from multiple acquisitions/resources.
    # Rounded WGS84 footprint is a stable display grouping; never use the task UUID.
    if (
        isinstance(bounds, list)
        and len(bounds) == 4
        and all(type(x) in (int, float) for x in bounds)
    ):
        location = tuple(round(x, 4) for x in bounds)
    else:
        location = tuple(sorted(item["sourceResourceIds"]))
    series = (
        item.get("observation", {}).get("product") or item["kind"]
        if item["scene"] == "wildfire"
        else item["scene"]
    )
    return location, series


def _prepared_display(dataset, style_hash):
    from apps.raster.services.renderer import RASTER_RENDERER_VERSION
    from apps.raster.services.tile_pyramid import native_web_mercator_max_zoom

    return {
        "delivery": "xyz",
        "datasetId": dataset.pk,
        "layerId": dataset.map_layer_id,
        "styleHash": style_hash,
        "tileUrl": f"/api/raster/tiles/{dataset.pk}/{style_hash}/{{z}}/{{x}}/{{y}}.png?rv={RASTER_RENDERER_VERSION}",
        "minZoom": 0,
        "maxZoom": native_web_mercator_max_zoom(dataset.processed_gdalinfo),
        "tileSampling": "nearest" if dataset.raster_kind == "categorical" else "linear",
        "bounds3857": dataset.bounds_3857,
        "bounds4326": dataset.bounds_4326,
        "imageCoordinates": dataset.image_coordinates,
        "rules": dataset.default_rules,
        "status": "ready",
    }


def official_snapshot(user, scene):
    project = Project.objects.get(pk=selected_project_id(), is_active=True)
    if scene not in configured_scenes(project):
        raise PermissionDenied("当前项目尚未配置此监测场景")
    visible = visible_resources(user, DataResource.objects.values("pk"))
    rows = list(
        official_products()
        .filter(
            project_tag=project,
            product_type=f"monitoring_{scene}",
            data_resource__in=visible,
        )
        .select_related(
            "data_resource__category__parent", "data_resource__observation_metadata"
        )
        .order_by("-pk")[:MAX_PRODUCTS]
    )
    valid = []
    for row in rows:
        try:
            item = normalize_product(row.metadata.get("monitoring"))
        except (ValidationError, AttributeError):
            continue
        if item["scene"] == scene and item["resourceId"] == row.data_resource_id:
            valid.append((row, item))
    source_ids = {pk for _, item in valid for pk in item["sourceResourceIds"]}
    sources = visible_resources(user, source_ids).in_bulk()
    ids = {row.data_resource_id for row, _ in valid}
    if scene == "glacier":
        ids.update(
            item["sourceResourceIds"][0]
            for _, item in valid
            if item["sourceResourceIds"][0] in sources
        )
    datasets = {
        row.data_resource_id: row
        for row in RasterDataset.objects.filter(
            status="ready",
            data_resource_id__in=ids,
        )
        .defer("source_gdalinfo")
        .order_by("pk")
    }
    styles = {}
    for style in RasterStyle.objects.filter(
        dataset_id__in=[row.pk for row in datasets.values()]
    ).order_by("pk"):
        styles[(style.dataset_id, style.style_hash)] = style
    default_styles = {}
    by_dataset = {row.pk: row for row in datasets.values()}
    for (dataset_id, style_hash), style in styles.items():
        dataset = by_dataset[dataset_id]
        if style.rules == dataset.default_rules:
            default_styles[dataset_id] = style_hash

    def prepared_default(dataset):
        if dataset is None or dataset.pk not in default_styles:
            return None
        return _prepared_display(dataset, default_styles[dataset.pk])

    featured = {}
    for row, item in valid:
        if not set(item["sourceResourceIds"]) <= sources.keys():
            continue
        dataset = datasets.get(row.data_resource_id)
        stored = row.metadata.get("formalDisplay", {}).get("display") or {}
        display = None
        if dataset is not None:
            if (dataset.pk, stored.get("styleHash")) in styles:
                display = stored
            else:
                display = prepared_default(dataset)
        observed = period_payload(
            getattr(row.data_resource, "observation_metadata", None)
        )
        if not item["observedStart"] and observed and observed.get("startsAt"):
            item["observedStart"], item["observedEnd"] = (
                observed["startsAt"],
                observed["endsAt"],
            )
        key = region_key(item, dataset.bounds_4326 if dataset else None)
        rank = (item["observedEnd"] or "", row.pk)
        if key in featured and featured[key][0] >= rank:
            continue
        source = sources[item["sourceResourceIds"][0]]
        extra = {}
        if scene == "glacier":
            comparison = prepared_default(datasets.get(source.pk))
            extra = {
                "comparison": {
                    "resource": serialize_resource(source),
                    "display": comparison,
                }
                if comparison is not None
                else None,
                "references": [
                    serialize_resource(sources[pk])
                    for pk in item["sourceResourceIds"][1:]
                    if sources[pk].data_type in {"document", "image"}
                ],
            }
        featured[key] = (
            rank,
            {
                **item,
                **extra,
                "id": row.pk,
                "name": row.name,
                "resource": serialize_resource(row.data_resource),
                "registeredAt": row.created_at.isoformat(),
                "regionLabel": row.name
                if source.pk == row.data_resource_id or scene in {"wildfire", "glacier"}
                else source.name,
                "display": display,
                "metrics": [
                    {
                        "key": key,
                        "label": label,
                        "unit": unit,
                        "value": item["statistics"].get(key),
                    }
                    for key, (label, unit) in METRICS[scene].items()
                ],
            },
        )
    items = [
        item
        for _, item in sorted(
            featured.values(), key=lambda pair: pair[0], reverse=True
        )[:MAX_REGIONS]
    ]
    return {"scene": scene, "items": items}
