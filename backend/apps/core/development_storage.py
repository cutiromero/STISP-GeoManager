"""开发环境批量清理：保留输入、移除计算成果，并验证原始表未改变。"""

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.agent.models import (
    AgentCheckpoint,
    AgentRun,
    AgentWorkflow,
    AgentWorkflowStep,
)
from apps.catalog.models import (
    DataResource,
    MapComposition,
    MapCompositionVersion,
    MapLayer,
    ResultArtifact,
    WorkspaceScene,
)
from apps.catalog.resource_storage_delete import ResourceStorageDeletion
from apps.compute.models import ComputeImport, ComputeInput, ComputeOutput, ComputeTask
from apps.core.storage import table_data_path, vector_geopackage_path
from apps.projects.context import ProjectScope, project_scope

# 配置：只有原生资源和可复现元信息需要长期保留，默认只提供显式调用。
RESOURCE_FIELDS = (
    "id",
    "project_tag_id",
    "name",
    "code",
    "source",
    "data_type",
    "file_format",
    "storage_path",
    "maintainer_id",
    "owner_only",
)
ACTIVE_TASK_STATUSES = ("queued", "validating", "running", "cancelling")
ACTIVE_RUN_STATUSES = ("queued", "running")
ACTIVE_FLOW_STATUSES = ("queued", "running", "waiting_compute")
CLEANUP_REASON = "开发环境清理可重算的测试成果；用户原始输入保持不变"


def _table_signature(path, name):
    if not path.is_file():
        return {"missing": True}
    quoted = '"' + name.replace('"', '""') + '"'
    digest = hashlib.sha256()
    count = 0
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN (?,?) AND name=?",
            ("table", "view", name),
        ).fetchone()
        if not exists:
            return {"missing": True}
        for row in connection.execute(f"SELECT * FROM {quoted} ORDER BY rowid"):
            for value in row:
                data = (
                    value
                    if isinstance(value, bytes)
                    else json.dumps(value, ensure_ascii=False).encode()
                )
                digest.update(
                    type(value).__name__.encode() + len(data).to_bytes(8, "big") + data
                )
            count += 1
    return {"rows": count, "sha256": digest.hexdigest()}


def original_state():
    resources = list(
        DataResource._base_manager.filter(is_compute_result=False)
        .order_by("id")
        .values(*RESOURCE_FIELDS)
    )
    tables = {}
    for row in resources:
        if not row["storage_path"]:
            continue
        if row["data_type"] != "vector" and not (
            row["data_type"] == "table" and row["file_format"].upper() == "SQLITE"
        ):
            continue
        with project_scope(
            ProjectScope((row["project_tag_id"],), row["project_tag_id"])
        ):
            path = (
                vector_geopackage_path()
                if row["data_type"] == "vector"
                else table_data_path("data.sqlite")
            )
        identity = str(path) + "::" + row["storage_path"]
        if identity not in tables:
            tables[identity] = _table_signature(path, row["storage_path"])
    return {"resources": resources, "tables": tables}


def assert_idle():
    counts = {
        "tasks": ComputeTask._base_manager.filter(
            status__in=ACTIVE_TASK_STATUSES
        ).count(),
        "runs": AgentRun._base_manager.filter(status__in=ACTIVE_RUN_STATUSES).count(),
        "workflows": AgentWorkflow._base_manager.filter(
            status__in=ACTIVE_FLOW_STATUSES
        ).count(),
        "imports": ComputeImport.objects.filter(
            status__in=("queued", "running")
        ).count(),
    }
    if any(counts.values()):
        raise ValueError(f"仍有执行任务，拒绝清理：{counts}")


def _strip_references(value, resources, layers, rasters, *, container=""):
    def included(item, identifiers):
        return isinstance(item, int) and item in identifiers

    if isinstance(value, list):
        if container in (
            "resourceIds",
            "resource_ids",
            "resultResourceIds",
            "result_resource_ids",
        ):
            return [item for item in value if item not in resources]
        if container in ("layerIds", "selectedLayerIds"):
            return [item for item in value if item not in layers]
        result = []
        for item in value:
            if isinstance(item, dict):
                if any(
                    included(item.get(key), resources)
                    for key in ("resourceId", "dataResourceId", "data_resource_id")
                ):
                    continue
                if any(
                    included(item.get(key), layers) for key in ("layerId", "mapLayerId")
                ):
                    continue
                if any(
                    included(item.get(key), rasters)
                    for key in ("rasterDatasetId", "rasterId")
                ):
                    continue
                if container in ("layers", "mapLayers") and included(
                    item.get("id"), layers
                ):
                    continue
                if container == "resource_manifest" and included(
                    item.get("id"), resources
                ):
                    continue
            result.append(
                _strip_references(item, resources, layers, rasters, container=container)
            )
        return result
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in ("selectedLayerId", "activeLayerId") and included(item, layers):
                result[key] = None
            else:
                result[key] = _strip_references(
                    item, resources, layers, rasters, container=key
                )
        return result
    return value


def _detach_project(project_id, ids, layers, rasters, receipt):
    for item in ComputeInput.objects.filter(resource_id__in=ids):
        item.snapshot = {
            **item.snapshot,
            "deletedResource": {
                **receipt,
                "formerResourceId": item.resource_id,
                "status": "deleted",
            },
        }
        item.resource = None
        item.save(update_fields=("snapshot", "resource"))
    ComputeImport.objects.filter(resource_id__in=ids).update(
        resource=None, status="deleted", error=CLEANUP_REASON
    )
    for model, fields in [
        (WorkspaceScene, ("snapshot",)),
        (MapComposition, ("source_workspace_snapshot",)),
        (MapCompositionVersion, ("workspace_snapshot", "resource_manifest")),
    ]:
        for row in model._base_manager.filter(project_tag_id=project_id):
            changes = []
            for field in fields:
                old = getattr(row, field)
                new = _strip_references(old, ids, layers, rasters, container=field)
                if new != old:
                    setattr(row, field, new)
                    changes.append(field)
            if changes:
                row.save(update_fields=changes)
    for row in AgentRun._base_manager.filter(project_tag_id=project_id):
        removed = [value for value in row.resource_ids if value in ids]
        if removed:
            row.resource_ids = [value for value in row.resource_ids if value not in ids]
            row.execution_state = {
                **row.execution_state,
                "developmentCleanup": {**receipt, "removedResourceIds": removed},
            }
            row.save(update_fields=("resource_ids", "execution_state"))


def clean_generated_data(protected_files=()):
    """应在停止 web/worker 后调用；不删除用户输入、算法版本、账户或知识。"""
    assert_idle()
    before = original_state()
    generated = list(
        DataResource._base_manager.filter(is_compute_result=True).order_by(
            "project_tag_id", "id"
        )
    )
    grouped = defaultdict(list)
    for resource in generated:
        grouped[resource.project_tag_id].append(resource)
    protected = {Path(path).resolve() for path in protected_files}
    receipt = {"at": timezone.now().isoformat(), "reason": CLEANUP_REASON}
    result = {
        "rawResourcesKept": len(before["resources"]),
        "generatedResourcesDeleted": [],
        "sharedOriginalFilesKept": [],
        "dataFilesDeleted": 0,
    }
    for project_id, resources in grouped.items():
        ids = {row.pk for row in resources}
        with project_scope(ProjectScope((project_id,), project_id, superadmin=True)):
            layers = set(
                MapLayer._base_manager.filter(data_resource_id__in=ids).values_list(
                    "id", flat=True
                )
            )
            rasters = set()
            plans = []
            for resource in resources:
                rasters.update(resource.raster_datasets.values_list("id", flat=True))
                plans.append(
                    ResourceStorageDeletion(
                        resource, deleting_resource_ids=ids, deleting_layer_ids=layers
                    )
                )
            storage = ResourceStorageDeletion.combine(plans)
            overlapping = storage.files & protected
            storage.files -= protected
            result["sharedOriginalFilesKept"] += sorted(
                str(path) for path in overlapping
            )
            try:
                with transaction.atomic(durable=True):
                    with storage:
                        _detach_project(project_id, ids, layers, rasters, receipt)
                        from apps.raster.models import RasterDataset

                        RasterDataset._base_manager.filter(
                            data_resource_id__in=ids
                        ).delete()
                        MapLayer._base_manager.filter(data_resource_id__in=ids).delete()
                        for resource in resources:
                            resource.source_datasets.all().delete()
                        DataResource._base_manager.filter(
                            pk__in=ids, is_compute_result=True
                        ).delete()
                    transaction.on_commit(storage.finalize)
            except BaseException:
                storage.restore_staged_files()
                storage.close()
                raise
            result["dataFilesDeleted"] += len(storage.staged)
            result["generatedResourcesDeleted"] += sorted(ids)
            if storage.cleanup_failed or storage.recovery_failed:
                raise RuntimeError("成果清理未完成，需检查已保存的存储状态")
    # 保留目标、输入、参数和任务身份；释放工作流重复嵌入的数据及执行快照。
    AgentWorkflow._base_manager.all().update(
        plan={"developmentCleanup": receipt},
        plan_hash="",
        evidence=[],
        result_ids=[],
        result_resource_ids=[],
        detail=CLEANUP_REASON,
    )
    AgentWorkflow._base_manager.exclude(
        status__in=("succeeded", "failed", "cancelled", "interrupted")
    ).update(status="interrupted")
    AgentRun._base_manager.exclude(
        status__in=("succeeded", "failed", "cancelled", "interrupted")
    ).update(status="interrupted")
    for workflow in AgentWorkflow._base_manager.all():
        filtered = [
            value
            for value in workflow.resource_ids
            if value not in set(result["generatedResourcesDeleted"])
        ]
        if filtered != workflow.resource_ids:
            workflow.resource_ids = filtered
            workflow.save(update_fields=("resource_ids",))
    AgentWorkflowStep.objects.all().update(
        action={}, input_refs={}, output_refs={}, metrics={}
    )
    AgentCheckpoint.objects.all().update(state={})
    ComputeOutput.objects.all().update(expired=True)
    after = original_state()
    if before != after:
        raise RuntimeError("原生数据资源或原始表校验不一致；禁止继续清理工作目录")
    result["originalTablesVerified"] = before["tables"]
    result["rawResourcesUnchanged"] = True
    result["at"] = timezone.now().isoformat()
    return result
