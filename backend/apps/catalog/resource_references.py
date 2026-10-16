"""References that must survive a catalog deletion, including JSON snapshots."""

from __future__ import annotations

from typing import Any

from apps.agent.models import AgentCheckpoint, AgentWorkflow, AgentWorkflowStep
from apps.catalog.models import MapComposition, MapCompositionVersion, WorkspaceScene
from apps.compute.models import ComputeImport, ComputeInput
from apps.raster.models import RasterProcessingJob


def _contains_reference(
    value: Any, resource_id: int, layer_ids: set[int], raster_ids: set[int]
) -> bool:
    if isinstance(value, dict):
        source = value.get("sourceResource")
        if isinstance(source, dict) and source.get("id") == resource_id:
            return True
        for key, item in value.items():
            if (
                key == "inputs"
                and isinstance(item, dict)
                and resource_id in item.values()
            ):
                return True
            if key in {"resourceId", "dataResourceId"} and item == resource_id:
                return True
            if key in {"resourceIds", "resultResourceIds"} and isinstance(item, list):
                if resource_id in item:
                    return True
            if key in {"layerId", "mapLayerId"} and type(item) is int:
                if item in layer_ids:
                    return True
            if key in {"datasetId", "rasterDatasetId"} and type(item) is int:
                if item in raster_ids:
                    return True
            if _contains_reference(item, resource_id, layer_ids, raster_ids):
                return True
    elif isinstance(value, list):
        return any(
            _contains_reference(item, resource_id, layer_ids, raster_ids)
            for item in value
        )
    return False


COMPUTE_TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
WORKFLOW_TERMINAL = {"succeeded", "failed", "cancelled"}


def historical_references(resource):
    """Only completed provenance of a registered computation result is removable."""
    if not resource.is_compute_result:
        return [], [], []
    inputs = list(
        ComputeInput.objects.filter(
            resource_id=resource.id, task__status__in=COMPUTE_TERMINAL
        ).values("id", "task_id", "task__status", "key", "checksum", "snapshot")
    )
    imports = list(
        ComputeImport.objects.filter(
            resource_id=resource.id,
            status__in=("ready", "failed"),
            output__task__status__in=COMPUTE_TERMINAL,
        ).values("id", "output_id", "status", "output__task__status", "name")
    )
    layer_ids = set(resource.map_layers.values_list("id", flat=True))
    raster_ids = set(resource.raster_datasets.values_list("id", flat=True))
    workflows = []
    for workflow in AgentWorkflow.objects.filter(
        project_tag_id=resource.project_tag_id, status__in=WORKFLOW_TERMINAL
    ):

        def contains(value):
            return _contains_reference(value, resource.id, layer_ids, raster_ids)

        step_refs = [
            row
            for row in workflow.steps.values(
                "id", "input_refs", "output_refs", "action"
            )
            if any(
                contains(row[key]) for key in ("input_refs", "output_refs", "action")
            )
        ]
        checkpoint_refs = [
            row
            for row in workflow.checkpoints.values("id", "state")
            if contains(row["state"])
        ]
        if (
            resource.id in workflow.resource_ids
            or resource.id in workflow.result_resource_ids
            or contains(workflow.plan)
            or contains(workflow.evidence)
            or step_refs
            or checkpoint_refs
        ):
            workflows.append(
                {
                    "id": str(workflow.id),
                    "status": workflow.status,
                    "planHash": workflow.plan_hash,
                    "plan": {
                        key: value
                        for key, value in workflow.plan.items()
                        if key != "deletedResources"
                    },
                    "evidence": workflow.evidence,
                    "input": resource.id in workflow.resource_ids,
                    "output": resource.id in workflow.result_resource_ids,
                    "steps": step_refs,
                    "checkpoints": checkpoint_refs,
                }
            )
    return inputs, imports, workflows


def resource_reference_reasons(resource, *, allow_history=False) -> list[str]:
    """Return generic categories without revealing another user's object names."""
    from apps.agent.resource_dependencies import active_run_reasons

    reasons = []
    reasons.extend(active_run_reasons(resource.id))
    removable = bool(allow_history and resource.is_compute_result)
    inputs = ComputeInput.objects.filter(resource_id=resource.id)
    imports = ComputeImport.objects.filter(resource_id=resource.id)
    if removable:
        inputs = inputs.exclude(task__status__in=COMPUTE_TERMINAL)
        imports = imports.exclude(
            status__in=("ready", "failed"),
            output__task__status__in=COMPUTE_TERMINAL,
        )
    if inputs.exists():
        reasons.append(
            "计算任务仍在使用该数据" if removable else "已有计算任务使用该数据"
        )
    if imports.exists():
        reasons.append(
            "计算或入库任务尚未结束" if removable else "已有计算任务关联该入库结果"
        )
    if resource.result_artifacts.exists():
        reasons.append("成果展示关联了该数据")
    layer_ids = set(resource.map_layers.values_list("id", flat=True))
    datasets = resource.raster_datasets.all()
    raster_ids = set(datasets.values_list("id", flat=True))
    if datasets.filter(status__in=("pending", "processing")).exists():
        reasons.append("栅格数据仍在处理中")
    project_id = resource.project_tag_id

    def contains(value):
        return _contains_reference(value, resource.id, layer_ids, raster_ids)

    snapshots = (
        (WorkspaceScene.objects.filter(project_tag_id=project_id), ("snapshot",)),
        (
            MapComposition.objects.filter(project_tag_id=project_id),
            ("source_workspace_snapshot",),
        ),
        (
            MapCompositionVersion.objects.filter(project_tag_id=project_id),
            ("workspace_snapshot", "resource_manifest"),
        ),
    )
    for queryset, fields in snapshots:
        if any(
            contains(value)
            or (
                field == "resource_manifest"
                and any(
                    isinstance(item, dict) and item.get("id") == resource.id
                    for item in value or []
                )
            )
            for row in queryset.values(*fields).iterator()
            for field, value in row.items()
        ):
            reasons.append("已保存的工程或专题图引用该数据")
            break
    workflows = AgentWorkflow.objects.filter(project_tag_id=project_id)
    if removable:
        workflows = workflows.exclude(status__in=WORKFLOW_TERMINAL)
    if any(
        resource.id in row["resource_ids"]
        or resource.id in row["result_resource_ids"]
        or contains(row["plan"])
        or contains(row["evidence"])
        for row in workflows.values(
            "resource_ids", "result_resource_ids", "plan", "evidence"
        )
    ):
        reasons.append("科研工作流引用该数据")
    elif any(
        contains(value)
        for row in AgentWorkflowStep.objects.filter(workflow__project_tag_id=project_id)
        .filter(workflow_id__in=workflows.values("id"))
        .values("input_refs", "output_refs", "action")
        .iterator()
        for value in row.values()
    ) or any(
        contains(row["state"])
        for row in AgentCheckpoint.objects.filter(workflow__project_tag_id=project_id)
        .filter(workflow_id__in=workflows.values("id"))
        .values("state")
        .iterator()
    ):
        reasons.append("科研工作流引用该数据")
    if any(
        contains(row["result"])
        for row in RasterProcessingJob.objects.filter(
            project_tag_id=project_id, status__in=("queued", "running")
        ).values("result")
    ):
        reasons.append("数据处理任务尚未结束")
    return reasons
