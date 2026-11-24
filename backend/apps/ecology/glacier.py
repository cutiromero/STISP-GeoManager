"""Registration series and workflow publication for the glacier board."""

from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.catalog.models import ResourceObservationMetadata
from apps.compute.models import ComputeImport, ComputeOutput
from apps.compute.packages import ComputeError
from apps.compute.quality import require_automatic_quality
from apps.projects.context import selected_project_id
from apps.raster.models import RasterDataset

from .models import RemoteSensingProduct

FLOW_CODE = "glacier-monitoring-dynamic"
MANANS_FLOW_CODE = "manans-glacier-interpretation"
MANANS_OPERATOR = "manans-glacier-infer"
MANANS_VARIANT = "manans-s2-dlinknet34"
MANANS_STANDARD_TASK = "manans-glacier-standard"
MANANS_SERIES = (MANANS_FLOW_CODE, MANANS_STANDARD_TASK)
TASK_KEY = "glacier-classification"
PRODUCT_TYPE = "monitoring_glacier"
PRODUCT_LIMIT = 240
BACKGROUND_COLOR = "#364a5c"


def prepare_classification_display(dataset):
    """Prepare the board's palette separately from the imported raster's defaults."""
    from apps.raster.services.renderer import (
        build_static_xyz_tile_pyramid,
        register_tile_style,
        tile_style_is_ready,
    )

    rules = dataset.default_rules
    if rules.get("mode") == "unique":
        # Model code 0 is valid non-ice; the source NoData mask still applies.
        rules = {
            **rules,
            "uniqueValues": [
                {**entry, "color": BACKGROUND_COLOR} if entry["value"] == 0 else entry
                for entry in rules["uniqueValues"]
            ],
        }
    display = register_tile_style(dataset, rules)
    if not tile_style_is_ready(dataset, display["styleHash"]):
        build_static_xyz_tile_pyramid(dataset, display["styleHash"])
    return display


def period_day(workflow):
    return workflow.created_at.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()


def overlap(left, right):
    return (
        len(left) == len(right) == 4
        and max(left[0], right[0]) < min(left[2], right[2])
        and max(left[1], right[1]) < min(left[3], right[3])
    )


def registered_products(user, series=(TASK_KEY,)):
    from .monitoring import visible_resources

    rows = list(
        RemoteSensingProduct.objects.filter(
            product_type=PRODUCT_TYPE,
            project_tag_id=selected_project_id(),
            data_resource__status="active",
            metadata__glacierTask__in=series,
        )
        .select_related("data_resource")
        .order_by("-pk")[:PRODUCT_LIMIT]
    )
    pairs = [
        (row, row.metadata["monitoring"])
        for row in rows
        if row.metadata.get("glacierRegion")
        and row.metadata.get("monitoring", {}).get("registrationDate")
    ]
    identities = {
        pk
        for row, item in pairs
        for pk in [row.data_resource_id, *item["sourceResourceIds"]]
    }
    allowed = set(visible_resources(user, identities).values_list("pk", flat=True))
    datasets = dict(
        RasterDataset.objects.filter(
            status="ready", data_resource_id__in=allowed, raster_kind="categorical"
        ).values_list("data_resource_id", "bounds_4326")
    )
    return [
        (row, item, datasets[row.data_resource_id])
        for row, item in pairs
        if row.data_resource_id in datasets
        and set(item["sourceResourceIds"]) <= allowed
    ]


def resolve_registered(workflow, user, source):
    """Find the latest earlier registration of the same job and site."""
    day = period_day(workflow)
    # Snapshot bounds are in native CRS. Match geography using the catalog WGS84
    # footprint; the operator checks the actual pixel intersection independently.
    dataset = (
        RasterDataset.objects.filter(
            data_resource_id=source.resource_id, status="ready"
        )
        .only("bounds_4326")
        .order_by("-pk")
        .first()
    )
    bounds = dataset.bounds_4326 if dataset is not None else []
    candidates = registered_products(user)
    intersecting = [
        (row, item) for row, item, extent in candidates if overlap(bounds, extent)
    ]
    exact = [
        (row, item)
        for row, item in intersecting
        if item["sourceResourceIds"][0] == source.resource_id
    ]
    group = (
        ResourceObservationMetadata.objects.filter(resource_id=source.resource_id)
        .values_list("collection_key", flat=True)
        .first()
    )
    nearby = {row.metadata["glacierRegion"] for row, _ in intersecting}
    if exact:
        region = exact[0][0].metadata["glacierRegion"]
    elif group:
        known_ids = set(
            ResourceObservationMetadata.objects.filter(
                collection_key=group,
                resource_id__in=[
                    item["sourceResourceIds"][0] for _, item in intersecting
                ],
            ).values_list("resource_id", flat=True)
        )
        same_series = {
            row.metadata["glacierRegion"]
            for row, item in intersecting
            if item["sourceResourceIds"][0] in known_ids
        }
        region = same_series.pop() if len(same_series) == 1 else "collection-" + group
    elif len(nearby) == 1:
        region = nearby.pop()
    else:
        region = f"source-{source.resource_id}"
    receipt = {
        "currentSourceId": source.resource_id,
        "currentDate": day,
        "region": region,
        "reason": "no_prior",
    }
    choices = [
        (row, item)
        for row, item in intersecting
        if row.metadata["glacierRegion"] == region and item["registrationDate"] < day
    ]
    if not choices:
        return None, receipt
    row, item = max(choices, key=lambda x: (x[1]["registrationDate"], x[0].pk))
    return row.data_resource, {
        **receipt,
        "reason": "matched",
        "baselineResourceId": row.data_resource_id,
        "baselineProductId": row.pk,
        "baselineDate": item["registrationDate"],
        "baselineBasis": "registered_codes"
        if item["kind"] == "historical"
        else "classification",
    }


def resolve_manans_registered(workflow, user, source):
    """Find the preceding authorized binary classification on the same native grid."""
    day = period_day(workflow)
    origin = RasterDataset.objects.filter(
        data_resource_id=source.resource_id, status="ready"
    ).first()
    receipt = {
        "currentSourceId": source.resource_id,
        "currentDate": day,
        "region": f"source-{source.resource_id}",
        "reason": "no_prior",
    }
    if origin is None or not origin.bounds_4326:
        return None, receipt

    matches = [
        (row, item)
        for row, item, bounds in registered_products(user, MANANS_SERIES)
        if bounds == origin.bounds_4326 and item["quality"] == "passed"
    ]
    dataset_ids = {
        identity
        for row, item in matches
        for identity in (row.data_resource_id, item["sourceResourceIds"][0])
    }
    datasets = {
        row.data_resource_id: row
        for row in RasterDataset.objects.filter(
            status="ready", data_resource_id__in=dataset_ids
        ).only("data_resource_id", "source_gdalinfo", "source_checksum_sha256")
    }
    grid = {key: origin.source_gdalinfo.get(key) for key in ("size", "geoTransform")}
    compatible = []
    for row, item in matches:
        original = datasets.get(item["sourceResourceIds"][0])
        if original is None or any(
            value is None or original.source_gdalinfo.get(key) != value
            for key, value in grid.items()
        ):
            continue
        baseline_image = None
        if row.metadata["glacierTask"] == MANANS_STANDARD_TASK:
            provenance = row.metadata.get("standardSource", {})
            result = datasets.get(row.data_resource_id)
            if (
                item.get("referenceRole") != "standard"
                or not provenance.get("sourceSha256")
                or original.source_checksum_sha256 != provenance["sourceSha256"]
                or result is None
                or result.source_checksum_sha256 != provenance.get("resultSha256")
            ):
                continue
            baseline_image = original.data_resource_id
        elif (item.get("model") or {}).get("variant") != MANANS_VARIANT:
            continue
        compatible.append((row, item, baseline_image))

    if compatible:
        receipt["region"] = max(
            compatible,
            key=lambda entry: (
                entry[1]["sourceResourceIds"][0] == source.resource_id,
                entry[1]["registrationDate"],
                entry[0].pk,
            ),
        )[0].metadata["glacierRegion"]
    earlier = [entry for entry in compatible if entry[1]["registrationDate"] < day]
    if not earlier:
        return None, receipt
    row, item, baseline_image = max(
        earlier, key=lambda entry: (entry[1]["registrationDate"], entry[0].pk)
    )
    return row.data_resource, {
        **receipt,
        "reason": "matched",
        "region": row.metadata["glacierRegion"],
        "baselineResourceId": row.data_resource_id,
        "baselineProductId": row.pk,
        "baselineDate": item["registrationDate"],
        "baselineBasis": "classification",
        **({"baselineImageId": baseline_image} if baseline_image else {}),
    }


def _workflow_classification(
    workflow, user, value, *, flow_code=FLOW_CODE, algorithm="glacier-b15-infer"
):
    from apps.business_flows.models import BusinessFlowDefinition
    from apps.business_flows.state import binding

    spec = binding(workflow)
    if (
        workflow.status != "succeeded"
        or workflow.owner_id != user.pk
        or not BusinessFlowDefinition.objects.filter(
            pk=spec["flowId"], code=flow_code, project_tag_id=workflow.project_tag_id
        ).exists()
    ):
        raise PermissionDenied("只有已完成的冰川业务流可以自动登记分类图")
    infer = value["nodes"].get("interpret", {})
    classification = next(
        (
            row["evidenceId"]
            for row in infer.get("contractOutputs", [])
            if row["name"] == "classification"
        ),
        "",
    )
    identity = classification.removeprefix("output-")
    if infer.get("status") != "succeeded" or not identity.isdecimal():
        raise ComputeError("找不到本次真实分类成果")
    record = (
        ComputeImport.objects.filter(
            output_id=int(identity),
            status="ready",
            resource__is_compute_result=True,
            resource__status="active",
            resource__project_tag_id=workflow.project_tag_id,
            output__key="classification",
            output__task_id=infer.get("computeTaskId"),
            output__task__version__algorithm__identifier=algorithm,
            output__task__trial=False,
            output__task__status="succeeded",
            output__task__owner=user,
            output__task__project_tag_id=workflow.project_tag_id,
            requested_by=user,
            request_source=f"workflow:{workflow.pk}",
        )
        .select_related("output__task__version", "resource")
        .get()
    )
    return record


def _registered_comparison(workflow, user, value, record, *, version, series):
    """Bind published metrics only to the completed comparison and its authorized registration."""
    user_id = user.pk
    comparison = value["nodes"].get("compare", {})
    task_id = comparison.get("computeTaskId")
    if not task_id or comparison.get("status") != "succeeded":
        raise ComputeError("找不到已完成的登记期统计")
    summary = ComputeOutput.objects.select_related("task").get(
        task_id=task_id,
        key="coverage",
        task__status="succeeded",
        task__project_tag_id=workflow.project_tag_id,
        task__owner_id=user_id,
        task__version__algorithm__identifier="glacier-temporal-compare",
        task__version__version=version,
    )
    require_automatic_quality(summary)
    comparison_inputs = dict(
        summary.task.input_records.values_list("key", "resource_id")
    )
    if comparison_inputs.get("current") != record.resource_id:
        raise ComputeError("统计与本次入库分类不一致")
    parameters = summary.task.parameters
    region = parameters["region"]
    reference = None
    change = None
    if comparison_inputs.get("baseline"):
        from .monitoring import visible_resources

        reference = RemoteSensingProduct.objects.get(
            pk=parameters["baseline_product_id"],
            project_tag_id=workflow.project_tag_id,
            data_resource_id=comparison_inputs["baseline"],
            product_type=PRODUCT_TYPE,
        )
        early = reference.metadata["monitoring"]
        ref_ids = set(early["sourceResourceIds"]) | {reference.data_resource_id}
        if (
            reference.metadata.get("glacierTask") not in series
            or reference.metadata.get("glacierRegion") != region
            or early["registrationDate"] != parameters["baseline_date"]
            or set(visible_resources(user, ref_ids).values_list("pk", flat=True))
            != ref_ids
        ):
            raise PermissionDenied("前期登记成果的范围或权限已变化")
        if MANANS_STANDARD_TASK in series:
            original = (
                early["sourceResourceIds"][0]
                if reference.metadata["glacierTask"] == MANANS_STANDARD_TASK
                else None
            )
            if comparison_inputs.get("baseline_image") != original:
                raise ComputeError("前期标准图与有效区来源不一致")
        metrics = summary.metadata["qualityCheck"]["metrics"]
        if metrics["comparisonStatus"] == "compared":
            change = {
                "baselineProductId": reference.pk,
                "baselineDate": early["registrationDate"],
                "basis": parameters["baseline_basis"],
                "commonAreaKm2": metrics["commonAreaKm2"],
                "changedPercent": metrics["changedPercent"],
                "netClass1Km2": metrics["netClass1Km2"],
                "netClass2Km2": metrics["netClass2Km2"],
                "netIceAreaKm2": metrics["netIceAreaKm2"],
            }
    return region, reference, change


def publish_workflow(workflow_id, user_id):
    """Called after successful completion, never by an upload or a trial."""
    from django.contrib.auth import get_user_model

    from apps.agent.models import AgentWorkflow
    from apps.business_flows.state import state
    from apps.compute.access import require_actor
    from .monitoring import register_product

    workflow = AgentWorkflow.objects.get(pk=workflow_id, status="succeeded")
    if not workflow.owner_id == user_id:
        raise PermissionDenied("任务归属已变化")
    user = get_user_model().objects.get(pk=user_id)
    require_actor(
        user,
        workflow.project_tag_id,
        "catalog.add_dataresource",
        "core.load_raster_layer",
    )
    value = state(workflow)
    record = _workflow_classification(workflow, user, value)
    output = record.output
    require_automatic_quality(output)
    from apps.business_flows.glacier_history import REGISTRATION_VERSION

    region, reference, change = _registered_comparison(
        workflow,
        user,
        value,
        record,
        version=REGISTRATION_VERSION,
        series=(TASK_KEY,),
    )
    raw = output.task.input_records.select_related("resource").get(key="image")
    counts = output.metadata["qualityCheck"]["metrics"]["classCounts"]
    facts = output.metadata["knowledgeFacts"]
    valid = sum(counts[k] for k in ("0", "1", "2"))
    previous_standard = None
    if (
        reference is not None
        and reference.metadata["monitoring"]["kind"] == "historical"
    ):
        previous_standard = reference
    if previous_standard is None:
        previous_standard = RemoteSensingProduct.objects.filter(
            project_tag_id=workflow.project_tag_id,
            product_type=PRODUCT_TYPE,
            metadata__glacierRegion=region,
            metadata__monitoring__kind="historical",
        ).first()
    more = (
        previous_standard.metadata["monitoring"]["sourceResourceIds"][1:]
        if previous_standard
        else []
    )
    from .monitoring import visible_resources

    more = list(
        visible_resources(user, more).order_by("pk").values_list("pk", flat=True)
    )
    title = previous_standard.name if previous_standard else raw.resource.name
    product = {
        "schemaVersion": 1,
        "code": f"glacier-workflow-{workflow.pk}",
        "name": title,
        "resourceId": record.resource_id,
        "scene": "glacier",
        "kind": "model",
        "quality": "passed",
        "registrationDate": period_day(workflow),
        "observedStart": None,
        "observedEnd": None,
        "sourceResourceIds": [raw.resource_id, *more],
        "sourceLabel": raw.resource.name,
        "limitations": ["登记期不是影像拍摄日期。"],
        "interpretation": "分类面积按影像缺测标记计算。"
        if facts["coverageBasis"] == "source_mask"
        else "原图没有缺测标记，按整幅影像统计。",
        "statistics": {
            "valid_coverage_percent": 100 * valid / sum(counts.values()),
            "class_1_percent": 100 * counts["1"] / valid,
            "class_2_percent": 100 * counts["2"] / valid,
            "valid_pixels": valid,
            "ice_area_km2": (counts["1"] + counts["2"]) * 0.000009,
        },
        "statisticsMethod": "在原生3米网格上计数。",
        "model": {
            "name": "冰川影像分类",
            "version": output.task.version.version,
            "variant": "b15",
            "checkpointSha256": facts["checkpointSha256"],
            "forecastLeadDays": None,
        },
    }
    dataset = RasterDataset.objects.get(
        data_resource_id=record.resource_id, status="ready"
    )
    style = prepare_classification_display(dataset)
    with transaction.atomic():
        row, created = register_product(user, product, computed_import=record)
        if created or row.metadata.get("glacierTask") != TASK_KEY:
            row.metadata = {
                **row.metadata,
                "glacierTask": TASK_KEY,
                "glacierRegion": region,
                "glacierChange": change,
                "formalDisplay": {"version": 1, "display": style},
            }
            row.save(update_fields=["metadata"])
    return row


def publish_manans(workflow_id, user_id):
    """Register a finished binary glacier map with its actual observed date."""
    from django.contrib.auth import get_user_model

    from apps.agent.models import AgentWorkflow
    from apps.business_flows.state import state
    from apps.compute.access import require_actor
    from apps.raster.services.renderer import register_tile_style
    from .monitoring import register_product

    workflow = AgentWorkflow.objects.get(pk=workflow_id, status="succeeded")
    if workflow.owner_id != user_id:
        raise PermissionDenied("任务归属已变化")
    user = get_user_model().objects.get(pk=user_id)
    require_actor(
        user,
        workflow.project_tag_id,
        "catalog.add_dataresource",
        "core.load_raster_layer",
    )
    value = state(workflow)
    record = _workflow_classification(
        workflow,
        user,
        value,
        flow_code=MANANS_FLOW_CODE,
        algorithm=MANANS_OPERATOR,
    )
    output = record.output
    require_automatic_quality(output)
    raw = output.task.input_records.select_related("resource").get(key="image")
    if raw.snapshot.get("updatedAt") != raw.resource.updated_at.isoformat():
        raise ComputeError("原始影像登记信息已更新，请重新核对本次观测日期")
    summary = output.metadata["qualityCheck"]["metrics"]
    total, valid, ice = (
        summary[key] for key in ("scene_pixels", "valid_pixels", "glacier_pixels")
    )
    if not 0 <= ice <= valid <= total or valid == 0:
        raise ComputeError("冰川面积统计与有效像元范围不一致")
    region, change = f"source-{raw.resource_id}", None
    if "compare" in value["nodes"]:
        from apps.business_flows.glacier_history import MANANS_REGISTRATION_VERSION

        region, _, change = _registered_comparison(
            workflow,
            user,
            value,
            record,
            version=MANANS_REGISTRATION_VERSION,
            series=MANANS_SERIES,
        )
    date = raw.resource.data_date.isoformat() if raw.resource.data_date else None
    product = {
        "schemaVersion": 1,
        "code": f"manans-glacier-workflow-{workflow.pk}",
        "name": raw.resource.name.replace("玛纳斯原始影像", "玛纳斯冰川"),
        "resourceId": record.resource_id,
        "scene": "glacier",
        "kind": "model",
        "quality": "passed",
        "registrationDate": period_day(workflow),
        "observedStart": date,
        "observedEnd": date,
        "sourceResourceIds": [raw.resource_id],
        "sourceLabel": raw.resource.name,
        "interpretation": "在有源像元的范围内解译冰川，背景像元计入有效区。",
        "limitations": ["单景光学分类中的季节性积雪和冰川混淆需靠多时相影像复核。"],
        "statistics": {
            "valid_coverage_percent": 100 * valid / total,
            "class_1_percent": 100 * ice / valid,
            "valid_pixels": valid,
            "ice_area_km2": ice / 10_000,
        },
        "statisticsMethod": "在原始10米网格上统计，每个冰川像元面积为100平方米。",
        "model": {
            "name": "AGRS DLinkNet34",
            "version": output.task.version.version,
            "variant": MANANS_VARIANT,
            "checkpointSha256": output.metadata["knowledgeFacts"]["checkpointSha256"],
            "forecastLeadDays": None,
        },
    }
    original = RasterDataset.objects.get(
        data_resource_id=raw.resource_id, status="ready"
    )
    original_style = register_tile_style(original, original.default_rules)
    dataset = RasterDataset.objects.get(
        data_resource_id=record.resource_id, status="ready"
    )
    style = prepare_classification_display(dataset)
    with transaction.atomic():
        row, created = register_product(user, product, computed_import=record)
        if created:
            row.metadata = {
                **row.metadata,
                "glacierTask": MANANS_FLOW_CODE,
                "glacierRegion": region,
                "glacierChange": change,
                "formalDisplay": {
                    "version": 1,
                    "display": style,
                    "sourceDisplay": original_style,
                },
            }
            row.save(update_fields=["metadata"])
    return row


def publish_after_finish(workflow_id, user_id, *, manans=False):
    """A registry failure does not undo successful classification or report."""
    import logging

    from django.db import OperationalError
    from time import sleep

    logger = logging.getLogger(__name__)
    for attempt in range(4):
        try:
            publish = publish_manans if manans else publish_workflow
            return publish(workflow_id, user_id)
        except OperationalError as error:
            if "database is locked" in str(error).lower() and attempt < 3:
                sleep(0.15 * (attempt + 1))
                continue
            logger.exception("Glacier board publication failed for %s", workflow_id)
            return None
        except Exception:
            logger.exception("Glacier board publication failed for %s", workflow_id)
            return None
