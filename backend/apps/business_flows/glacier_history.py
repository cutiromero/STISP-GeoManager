"""Resolve a glacier comparison's server-owned inputs at Agent preflight."""

from django.db.models import F, Q, OuterRef, Subquery

from apps.agent.resource_discovery import acl_resources
from apps.catalog.models import ResourceObservationMetadata
from apps.compute.models import (
    AlgorithmVersion,
    ComputeImport,
    ComputeInput,
    ComputeOutput,
)
from apps.compute.packages import ComputeError
from apps.compute.quality import require_automatic_quality
from apps.projects.context import selected_project_id
from apps.raster.models import RasterDataset

from .state import state

COMPARISON = "glacier-temporal-compare"
AUTOMATIC_VERSION = "1.2.0"
REGISTRATION_VERSION = "1.3.0"
MANANS_REGISTRATION_VERSION = "1.4.0"
INFERENCE = "glacier-b15-infer"
GRID_FIELDS = (
    ("coordinateSystem", 0),
    ("size", 2),
    ("geoTransform", 6),
)


def enabled(node, version):
    return (
        node.get("algorithmVersionId") == version.pk
        and version.algorithm.identifier == COMPARISON
        and version.version
        in {AUTOMATIC_VERSION, REGISTRATION_VERSION, MANANS_REGISTRATION_VERSION}
    )


def fixed_manans_comparison(node):
    return (
        node.get("id") == "compare"
        and node.get("kind") == "operator"
        and AlgorithmVersion.objects.filter(
            pk=node.get("algorithmVersionId"),
            algorithm__identifier=COMPARISON,
            version=MANANS_REGISTRATION_VERSION,
        ).exists()
    )


def comparison_action(item, contract):
    """Describe the next mechanical action for a frozen, bound comparison."""
    loop = item["toolLoop"]
    if failure := loop.get("failure"):
        raise ComputeError(
            failure.get("message", "登记期比较未完成，请核对资料"),
            failure=failure,
        )
    if successful := loop.get("successfulTaskId"):
        outputs = {
            row.key: row
            for row in ComputeOutput.objects.filter(
                task_id=successful, expired=False
            ).select_related("task__version")
        }
        required = contract["requiredOutputs"]
        if any(
            spec["name"] not in outputs
            or outputs[spec["name"]].kind != spec["semanticType"]
            for spec in required
        ):
            raise ComputeError("登记期比较缺少可交付的实际表格")
        coverage = outputs.get("coverage")
        if coverage is None:
            raise ComputeError("登记期比较缺少有效范围统计")
        require_automatic_quality(coverage)
        checked = coverage.metadata["qualityCheck"]
        metrics = checked["metrics"]
        summary = checked["summary"]
        if metrics["comparisonStatus"] == "compared":
            summary = (
                f"{metrics['baselineDate']} 至 {metrics['currentDate']}，"
                f"共同有效面积 {metrics['commonAreaKm2']} 平方公里，"
                f"分类变化占比 {metrics['changedPercent']}%，"
                f"冰川分类净面积差 {metrics['netIceAreaKm2']} 平方公里。"
            )
        delivery = [
            {**spec, "evidenceId": f"output-{outputs[spec['name']].pk}"}
            for spec in required
        ]
        return {
            "action": "finish_node",
            "arguments": {
                "summary": summary,
                "outputs": delivery,
                "evidenceIds": [entry["evidenceId"] for entry in delivery],
                "limitations": ["登记期变化反映分类结果差异。"]
                if metrics["comparisonStatus"] == "compared"
                else [checked["summary"]],
            },
        }
    last_failure = loop.get("lastObservation", {}).get("result", {}).get("failure", {})
    if (
        loop.get("preflightRequestHash")
        and last_failure.get("code") != "PREFLIGHT_REQUIRED"
    ):
        return {"action": "run_operator", "arguments": {"usePreflight": True}}
    return {"action": "preflight_operator", "arguments": {}}


def _classification_filters(algorithm):
    return {
        "status": "ready",
        "output__key": "classification",
        "output__kind": "raster",
        "output__task__trial": False,
        "output__task__status": "succeeded",
        "output__task__version__algorithm__identifier": algorithm,
    }


def _grid_filters(snapshot):
    grid = snapshot.get("rasterMetadata", {})
    filters = {}
    for key, count in GRID_FIELDS:
        value = grid.get(key)
        prefix = "snapshot__rasterMetadata__" + key
        if count:
            if not isinstance(value, list) or len(value) != count:
                return {}
            filters.update({f"{prefix}__{i}": v for i, v in enumerate(value)})
        elif isinstance(value, str) and value:
            filters[prefix] = value
        else:
            return {}
    return filters


def _source_day(metadata, snapshot, resource):
    # Editing catalog metadata changes the resource revision. It must not
    # silently add a new date to a computation made against an earlier revision.
    if (
        metadata
        and metadata.starts_at
        and metadata.starts_at == metadata.ends_at
        and metadata.precision == "day"
        and snapshot.get("updatedAt") == resource.updated_at.isoformat()
    ):
        return metadata.starts_at
    return None


def resolve(
    workflow, user, policy, node, current_id, *, registration=False, manans=False
):
    """Use only the immediate authorized history of the same registered series."""
    link = node.get("inputBindings", {}).get("current", {})
    if (
        link.get("outputKey") != "classification"
        or link.get("nodeId") not in node["dependsOn"]
        or selected_project_id() != workflow.project_tag_id
        or user.pk != workflow.owner_id
    ):
        raise ComputeError("冰川自动对比必须绑定本次上游的真实解译成果")
    upstream = state(workflow)["nodes"][link["nodeId"]]
    scoped = acl_resources(user, policy).filter(data_type="raster")
    from apps.ecology import glacier

    imports = ComputeImport.objects.filter(
        **_classification_filters(glacier.MANANS_OPERATOR if manans else INFERENCE),
        output__task__project_tag_id=workflow.project_tag_id,
        resource__in=scoped,
    )
    current = (
        imports.select_related("output__task__version")
        .filter(
            resource_id=current_id,
            output__task_id=upstream.get("computeTaskId"),
            output__task__owner=user,
        )
        .first()
        if upstream["status"] == "succeeded"
        else None
    )
    if current is None:
        raise ComputeError("本期分类不是本次解译已入库的成果")
    require_automatic_quality(current.output)
    source = (
        current.output.task.input_records.select_related("resource")
        .filter(key="image", resource__in=scoped)
        .first()
    )
    if source is None:
        raise ComputeError("本期原始影像未绑定或访问权限已撤回", 403)
    if manans:
        return glacier.resolve_manans_registered(workflow, user, source)
    if registration:
        return glacier.resolve_registered(workflow, user, source)
    metadata = ResourceObservationMetadata.objects.filter(
        resource=source.resource
    ).first()
    day = _source_day(metadata, source.snapshot, source.resource)
    receipt = {"currentSourceId": source.resource_id}
    if not day:
        return None, {**receipt, "reason": "no_current_date"}
    receipt["currentDate"] = day.isoformat()
    if not metadata.collection_key:
        return None, {**receipt, "reason": "no_series"}

    grid = _grid_filters(source.snapshot)
    if not grid or not source.checksum:
        return None, {**receipt, "reason": "no_prior"}
    accepted_imports = imports.exclude(pk=current.pk).filter(
        output__task__version_id=current.output.task.version_id,
        output__metadata__qualityCheck__status="passed",
        resource__raster_datasets__status="ready",
        resource__raster_datasets__project_tag_id=workflow.project_tag_id,
        resource__raster_datasets__raster_kind=RasterDataset.RasterKind.CATEGORICAL,
        resource__raster_datasets__source_checksum_sha256=F("output__checksum"),
    )
    older = (
        ComputeInput.objects.filter(
            key="image",
            resource__in=scoped,
            task__in=accepted_imports.values("output__task_id"),
            resource__observation_metadata__collection_key=metadata.collection_key,
            resource__observation_metadata__project_tag_id=workflow.project_tag_id,
            resource__observation_metadata__family=metadata.family,
            resource__observation_metadata__precision="day",
            resource__observation_metadata__starts_at__lt=day,
            resource__observation_metadata__ends_at=F(
                "resource__observation_metadata__starts_at"
            ),
            **grid,
        )
        .exclude(
            Q(resource_id=source.resource_id)
            | Q(checksum=source.checksum)
            | Q(checksum="")
        )
        .select_related("resource__observation_metadata")
        .annotate(
            classification_import=Subquery(
                accepted_imports.filter(output__task_id=OuterRef("task_id"))
                .order_by("-pk")
                .values("pk")[:1]
            )
        )
        .order_by(
            "-resource__observation_metadata__starts_at", "-task__finished_at", "pk"
        )
    )
    # Bound history reads; repeated runs can point to one earlier image.
    for candidate in older[:32]:
        previous = candidate.resource.observation_metadata
        effective_day = _source_day(previous, candidate.snapshot, candidate.resource)
        if effective_day is None:
            continue
        imported = (
            accepted_imports.select_related("resource", "output__task__version")
            .filter(
                pk=candidate.classification_import,
            )
            .first()
        )
        if imported is None:
            continue
        try:
            require_automatic_quality(imported.output)
        except ComputeError:
            continue
        return imported.resource, {
            **receipt,
            "reason": "matched",
            "baselineSourceId": candidate.resource_id,
            "baselineResourceId": imported.resource_id,
            "baselineDate": effective_day.isoformat(),
        }
    return None, {**receipt, "reason": "no_prior"}


def parameters(receipt):
    return {
        "current_date": receipt.get("currentDate", ""),
        "baseline_date": receipt.get("baselineDate", ""),
        "baseline_reason": receipt["reason"],
        **(
            {
                "region": receipt["region"],
                "baseline_product_id": receipt.get("baselineProductId", 0),
                "baseline_basis": receipt.get("baselineBasis", "classification"),
            }
            if "region" in receipt
            else {}
        ),
    }


def is_bound_baseline(workflow, task, record):
    if record.key not in {"baseline", "baseline_image"} or task.trial:
        return False
    if (
        record.key == "baseline_image"
        and task.version.version != MANANS_REGISTRATION_VERSION
    ):
        return False
    nodes = (
        workflow.parameters.get("_businessFlow", {})
        .get("definitionSnapshot", {})
        .get("nodes", [])
    )
    return any(enabled(node, task.version) for node in nodes)
