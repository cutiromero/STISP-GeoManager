"""Confirmed project removal with independent shared-data and file protection."""

from collections import defaultdict
import hashlib
import json
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.db.models.deletion import Collector, ProtectedError
from django.utils import timezone

from apps.audit.service import log_operation
from apps.catalog.models import (
    DataResource,
    MapLayer,
    ShareInvitation,
    WorkspaceScene,
    MapComposition,
    MapCompositionVersion,
    DataCatalog,
    ResultArtifact,
)
from apps.catalog.resource_storage_delete import ResourceStorageDeletion, _safe_file
from apps.compute.models import ComputeOutput, ComputeImport, ComputeTask
from apps.core.storage import app_path, StoragePathError
from apps.projects.context import ProjectScope, project_scope
from apps.raster.models import RasterDataset
from .models import Project, ProjectMembership, ProjectFeatureSetting
from .context import is_superadmin

TOKEN_SALT = "projects.confirmed-deletion.v1"
TOKEN_SECONDS = 600
MAX_RECORDS = 20000
MAX_RETENTION_PASSES = 12
OWNER_FIELDS = {
    "compute.computeinput": "task",
    "compute.computeoutput": "task",
    "compute.computeattempt": "task",
    "compute.computeimport": "output",
    "agent.agentrun": "conversation",
    "agent.runevent": "run",
    "agent.agentworkflowstep": "workflow",
    "agent.agentcheckpoint": "workflow",
    "agent.agentcomputefollowup": "run",
    "business_flows.businessflowversion": "flow",
}


def key(obj):
    return obj._meta.label_lower, str(obj.pk)


def parent(obj):
    names = (
        [OWNER_FIELDS[obj._meta.label_lower]]
        if obj._meta.label_lower in OWNER_FIELDS
        else [
            "data_resource",
            "resource",
            "dataset",
            "composition",
            "article",
            "workflow",
            "run",
            "task",
            "output",
            "flow",
            "algorithm",
            "conversation",
            "project",
        ]
    )
    fields = {f.name: f for f in obj._meta.concrete_fields if f.is_relation}
    for name in names:
        field = fields.get(name)
        if field is not None and getattr(obj, field.attname) is not None:
            return getattr(obj, name)
    if obj._meta.auto_created:
        for field in fields.values():
            if field.related_model._meta.app_label not in {"auth", "core"}:
                return getattr(obj, field.name)
    return None


def project_id(obj, seen=None):
    if isinstance(obj, Project):
        return obj.pk
    if hasattr(obj, "project_tag_id"):
        return obj.project_tag_id
    seen = set() if seen is None else seen
    if key(obj) in seen:
        return None
    seen.add(key(obj))
    owner = parent(obj)
    return project_id(owner, seen) if owner is not None else None


def kept(obj, retained, seen=None):
    if key(obj) in retained:
        return True
    seen = set() if seen is None else seen
    if key(obj) in seen:
        return False
    seen.add(key(obj))
    owner = parent(obj)
    return (
        kept(owner, retained, seen)
        if owner is not None and not isinstance(owner, Project)
        else False
    )


class ProjectCollector(Collector):
    def __init__(self, project, retained):
        super().__init__("default")
        self.project = project
        self.retained = retained
        self.preserved = set()

    def can_fast_delete(self, *args, **kwargs):
        return False

    def collect(self, objs, *args, **kwargs):
        owned = []
        for obj in objs:
            if (
                kept(obj, self.retained)
                or project_id(obj) != self.project.pk
                or obj._meta.app_label == "audit"
            ):
                self.preserved.add(obj)
            else:
                owned.append(obj)
        if not owned:
            return
        try:
            super().collect(owned, *args, **kwargs)
        except ProtectedError as error:
            # Traverse PROTECT only for this project's proven objects. Shared
            # dependents are preserved and retain their referenced parents below.
            grouped = defaultdict(list)
            for obj in error.protected_objects:
                grouped[type(obj)].append(obj)
            for group in grouped.values():
                self.collect(group)


def resource_ids(value, layers, rasters):
    result = set()
    if isinstance(value, list):
        for item in value:
            result.update(resource_ids(item, layers, rasters))
    elif isinstance(value, dict):
        for name, item in value.items():
            if name in {"resourceId", "dataResourceId"} and type(item) is int:
                result.add(item)
            elif name in {
                "resourceIds",
                "resultResourceIds",
                "resource_ids",
                "result_resource_ids",
            } and isinstance(item, list):
                result.update(v for v in item if type(v) is int)
            elif name == "inputs" and isinstance(item, dict):
                result.update(v for v in item.values() if type(v) is int)
            elif (
                name in {"layerId", "mapLayerId"}
                and type(item) is int
                and item in layers
            ):
                result.add(layers[item])
            elif (
                name in {"datasetId", "rasterDatasetId"}
                and type(item) is int
                and item in rasters
            ):
                result.add(rasters[item])
            elif (
                name == "sourceResource"
                and isinstance(item, dict)
                and type(item.get("id")) is int
            ):
                result.add(item["id"])
            elif name in {"resource_manifest", "resourceManifest"} and isinstance(
                item, list
            ):
                result.update(
                    row["id"]
                    for row in item
                    if isinstance(row, dict) and type(row.get("id")) is int
                )
            result.update(resource_ids(item, layers, rasters))
    return result


def shared_objects(project):
    from apps.agent.models import (
        AgentRun,
        AgentWorkflow,
        AgentWorkflowStep,
        AgentCheckpoint,
    )

    retained = set()
    layers = dict(
        MapLayer._base_manager.filter(project_tag_id=project.pk)
        .exclude(data_resource_id=None)
        .values_list("id", "data_resource_id")
    )
    rasters = dict(
        RasterDataset._base_manager.filter(project_tag_id=project.pk).values_list(
            "id", "data_resource_id"
        )
    )
    ids = set()
    sources = [
        (
            WorkspaceScene._base_manager.exclude(project_tag_id=project.pk),
            ("snapshot",),
        ),
        (
            MapComposition._base_manager.exclude(project_tag_id=project.pk),
            ("source_workspace_snapshot",),
        ),
        (
            MapCompositionVersion._base_manager.exclude(project_tag_id=project.pk),
            ("workspace_snapshot", "resource_manifest"),
        ),
        (
            AgentRun._base_manager.exclude(project_tag_id=project.pk),
            (
                "resource_ids",
                "evidence",
                "compute_intent",
                "research_intent",
                "execution_state",
            ),
        ),
        (
            AgentWorkflow._base_manager.exclude(project_tag_id=project.pk),
            ("resource_ids", "result_resource_ids", "plan", "evidence"),
        ),
        (
            AgentWorkflowStep.objects.exclude(workflow__project_tag_id=project.pk),
            ("input_refs", "output_refs", "action"),
        ),
        (
            AgentCheckpoint.objects.exclude(workflow__project_tag_id=project.pk),
            ("state",),
        ),
    ]
    for queryset, fields in sources:
        for row in queryset.values(*fields).iterator():
            ids.update(resource_ids(row, layers, rasters))
    ids.update(
        DataCatalog._base_manager.exclude(project_tag_id=project.pk).values_list(
            "resources__id", flat=True
        )
    )
    ids.update(
        ResultArtifact._base_manager.exclude(project_tag_id=project.pk).values_list(
            "related_resources__id", flat=True
        )
    )
    for identity in DataResource._base_manager.filter(
        pk__in=ids, project_tag_id=project.pk
    ).values_list("id", flat=True):
        retained.add((DataResource._meta.label_lower, str(identity)))
    shares = ShareInvitation._base_manager.filter(
        project_tag_id=project.pk, status__in=("pending", "accepted")
    )
    for share in shares:
        if share.kind == ShareInvitation.Kind.COMPUTE_OUTPUT:
            output = ComputeOutput.objects.filter(
                pk=share.object_id, task__project_tag_id=project.pk
            ).first()
            if output:
                retained.add((ComputeTask._meta.label_lower, str(output.task_id)))
        else:
            model = (
                WorkspaceScene
                if share.kind == ShareInvitation.Kind.WORKSPACE
                else MapComposition
            )
            obj = model._base_manager.filter(
                pk=share.object_id, project_tag_id=project.pk
            ).first()
            if obj:
                retained.add(key(obj))
                docs = [
                    getattr(obj, "snapshot", {}),
                    getattr(obj, "source_workspace_snapshot", {}),
                ]
                if model is MapComposition:
                    docs.extend(
                        MapCompositionVersion._base_manager.filter(
                            composition=obj
                        ).values("workspace_snapshot", "resource_manifest")
                    )
                retained.update(
                    (DataResource._meta.label_lower, str(i))
                    for i in resource_ids(docs, layers, rasters)
                )
    return retained


def require_idle(project):
    from apps.agent.models import AgentRun, AgentWorkflow, WORKFLOW_ACTIVE
    from apps.agent.interactions import BLOCKING
    from apps.raster.models import RasterProcessingJob

    busy = (
        AgentRun._base_manager.filter(
            project_tag_id=project.pk, status__in=BLOCKING
        ).exists()
        or AgentWorkflow._base_manager.filter(
            project_tag_id=project.pk, status__in=WORKFLOW_ACTIVE
        ).exists()
        or ComputeTask._base_manager.filter(
            project_tag_id=project.pk,
            status__in=("queued", "validating", "running", "cancelling"),
        ).exists()
        or ComputeImport.objects.filter(
            output__task__project_tag_id=project.pk, status__in=("queued", "running")
        ).exists()
        or RasterProcessingJob._base_manager.filter(
            project_tag_id=project.pk, status__in=("queued", "running")
        ).exists()
        or RasterDataset._base_manager.filter(
            project_tag_id=project.pk, status__in=("pending", "processing")
        ).exists()
    )
    if busy:
        raise ValidationError("项目仍有运行中或等待继续的任务，请先停止任务再删除")


def add_owned_files(collector, storage, project):
    from apps.agent.models import AgentAttachment
    from apps.knowledge.models import KnowledgeDocument

    definitions = {
        ComputeOutput: ("path",),
        AgentAttachment: ("path",),
        ResultArtifact: ("file_path",),
        MapCompositionVersion: ("preview_path", "artifact_path"),
        KnowledgeDocument: ("original_path", "extracted_path"),
    }
    deleted = {
        model: [obj.pk for obj in collector.data.get(model, ())]
        for model in definitions
    }
    shared = set()
    for model, fields in definitions.items():
        for obj in collector.data.get(model, ()):
            for field in fields:
                raw = getattr(obj, field)
                if not raw:
                    continue
                relative = (
                    "uploads/knowledge/" + raw if model is KnowledgeDocument else raw
                )
                prefixes = (
                    f"projects/{project.pk}/compute/outputs/{obj.task_id}/"
                    if model is ComputeOutput
                    else f"projects/{project.pk}/agent-attachments/"
                    if model is AgentAttachment
                    else f"exports/map-compositions/{obj.composition_id}/"
                    if model is MapCompositionVersion
                    else "uploads/knowledge/"
                    if model is KnowledgeDocument
                    else "exports/"
                )
                try:
                    if not relative.startswith(prefixes):
                        raise StoragePathError("路径归属无法确认")
                    path = _safe_file(app_path(), relative)
                except StoragePathError:
                    shared.add(relative)
                    continue
                reused = False
                for other_model, other_fields in definitions.items():
                    for other_field in other_fields:
                        candidates = [relative, str(path)]
                        if other_model is KnowledgeDocument and relative.startswith(
                            "uploads/knowledge/"
                        ):
                            candidates.append(
                                relative.removeprefix("uploads/knowledge/")
                            )
                        if (
                            other_model._base_manager.filter(
                                **{other_field + "__in": candidates}
                            )
                            .exclude(pk__in=deleted[other_model])
                            .exists()
                        ):
                            reused = True
                if reused:
                    shared.add(relative)
                else:
                    storage.files.add(path)
    return len(shared)


def external_storage(project):
    """Resolve other tenants' references read-only, including legacy symlinks."""
    from apps.catalog.models import VectorDataset

    files, databases = set(), set()

    def root(identity):
        base = settings.PROJECT_CONFIG.research_data_root
        return base if identity == 1 else base / "projects" / str(identity)

    def add(target, path):
        try:
            target.add(path.resolve())
        except (OSError, RuntimeError):
            pass

    for row in DataResource._base_manager.exclude(project_tag_id=project.pk).values(
        "project_tag_id", "storage_path", "data_type", "file_format"
    ):
        base, path = root(row["project_tag_id"]), row["storage_path"]
        if row["data_type"] == "vector":
            add(databases, base / "vector/vector.gpkg")
        elif row["data_type"] == "table" and row["file_format"].upper() == "SQLITE":
            add(databases, base / "table/data.sqlite")
        elif path:
            if row["data_type"] == "raster":
                add(files, base / "raster/preprocessed" / path)
            else:
                add(
                    files,
                    base / path
                    if path.startswith(("table/", "gene/"))
                    else base
                    / ("gene" if row["data_type"] == "gene" else "table")
                    / path,
                )
    fields = {
        "source_relative_path": "raster/original",
        "processed_relative_path": "raster/preprocessed",
        "source_metadata_relative_path": "raster/metadata",
        "processed_metadata_relative_path": "raster/metadata",
    }
    for row in RasterDataset._base_manager.exclude(project_tag_id=project.pk).values(
        "project_tag_id", "source_manifest", *fields
    ):
        for field, folder in fields.items():
            if row[field]:
                add(files, root(row["project_tag_id"]) / folder / row[field])
        source_parent = Path(row["source_relative_path"]).parent
        for item in row["source_manifest"] or []:
            if (
                isinstance(item, dict)
                and item.get("name")
                and len(Path(str(item["name"])).parts) == 1
            ):
                add(
                    files,
                    root(row["project_tag_id"])
                    / "raster/original"
                    / source_parent
                    / str(item["name"]),
                )
        if row["source_relative_path"].startswith("uploaded/"):
            add(
                files,
                root(row["project_tag_id"])
                / "raster/original"
                / source_parent
                / "manifest.json",
            )
    for row in VectorDataset._base_manager.exclude(project_tag_id=project.pk).values(
        "project_tag_id", "source_archive_path"
    ):
        if row["source_archive_path"]:
            add(
                files,
                root(row["project_tag_id"])
                / "vector/original"
                / row["source_archive_path"],
            )
    for row in MapLayer._base_manager.exclude(project_tag_id=project.pk).values(
        "project_tag_id", "layer_type", "source_path"
    ):
        if row["layer_type"] == "vector":
            add(databases, root(row["project_tag_id"]) / "vector/vector.gpkg")
        elif row["layer_type"] == "raster" and row["source_path"]:
            add(
                files,
                root(row["project_tag_id"])
                / "raster/preprocessed"
                / row["source_path"],
            )
    return files, databases


def storage_identity(path):
    try:
        value = path.stat()
        return value.st_dev, value.st_ino
    except (OSError, RuntimeError):
        return None


def build_plan(project):
    if project.is_default or project.pk == 1:
        raise ValidationError("公开项目不能删除")
    require_idle(project)
    foreign_files, foreign_databases = external_storage(project)
    shared_file_inodes = {
        identity
        for path in foreign_files
        if (identity := storage_identity(path)) is not None
    }
    shared_database_inodes = {
        identity
        for path in foreign_databases
        if (identity := storage_identity(path)) is not None
    }
    roots = []
    for model in apps.get_models():
        if model._meta.app_label == "audit" or not any(
            f.name == "project_tag" for f in model._meta.concrete_fields
        ):
            continue
        fields = [
            f.attname
            for f in model._meta.concrete_fields
            if f.is_relation
            or f.primary_key
            or f.name
            in {"status", "updated_at", "checksum", "path", "storage_path", "file_path"}
        ]
        roots.extend(
            model._base_manager.filter(project_tag_id=project.pk).only(*fields)[
                : MAX_RECORDS + 1
            ]
        )
        if len(roots) > MAX_RECORDS:
            raise ValidationError("项目记录较多，请先分批清理数据再删除项目")
    roots.extend(ProjectMembership.objects.filter(project=project))
    roots.extend(ProjectFeatureSetting.objects.filter(project=project))
    retained = shared_objects(project)
    for _ in range(MAX_RETENTION_PASSES):
        # Close the retained graph before staging files or deleting any rows.
        collector = ProjectCollector(project, retained)
        grouped = defaultdict(list)
        for obj in roots:
            grouped[type(obj)].append(obj)
        for group in grouped.values():
            collector.collect(group)
        candidates = {
            key(obj) for objects in collector.data.values() for obj in objects
        }
        preserve = set(collector.preserved)
        for (field, _), batches in collector.field_updates.items():
            for batch in batches:
                preserve.update(
                    obj
                    for obj in batch
                    if project_id(obj) != project.pk or kept(obj, retained)
                )
        extra = set()
        for obj in preserve:
            for field in obj._meta.concrete_fields:
                if field.is_relation and getattr(obj, field.attname) is not None:
                    identity = (
                        field.related_model._meta.label_lower,
                        str(getattr(obj, field.attname)),
                    )
                    if identity in candidates:
                        extra.add(identity)
        resources = list(collector.data.get(DataResource, ()))
        deleting_ids = [r.pk for r in resources]
        layer_ids = [r.pk for r in collector.data.get(MapLayer, ())]
        plans = []
        for resource in resources:
            try:
                plan = ResourceStorageDeletion(
                    resource,
                    deleting_resource_ids=deleting_ids,
                    deleting_layer_ids=layer_ids,
                )
                if any(
                    path.resolve() in foreign_databases
                    or storage_identity(path) in shared_database_inodes
                    for path, _, _ in plan.databases
                ):
                    extra.add(key(resource))
                else:
                    plans.append(plan)
            except StoragePathError:
                extra.add(key(resource))
        if extra - retained:
            retained.update(extra)
            continue
        storage = ResourceStorageDeletion.combine(plans)
        shared_files = add_owned_files(collector, storage, project)
        shared_paths = {
            path
            for path in storage.files
            if path.resolve() in foreign_files
            or storage_identity(path) in shared_file_inodes
        }
        storage.files.difference_update(shared_paths)
        rows = sorted((model, pk) for model, pk in candidates)
        signature = {
            "project": [project.pk, project.name, project.code, project.is_active],
            "rows": rows,
            "retained": sorted(retained),
            "revisions": sorted(
                (
                    key(o),
                    str(getattr(o, "updated_at", "")),
                    str(getattr(o, "checksum", "")),
                )
                for o in roots
            ),
            "files": sorted(str(p) for p in storage.files),
            "fileVersions": sorted(
                (
                    str(p),
                    p.stat().st_dev,
                    p.stat().st_ino,
                    p.stat().st_size,
                    p.stat().st_mtime_ns,
                )
                for p in storage.files
                if p.is_file()
            ),
            "tables": sorted((str(p), table) for p, table, _ in storage.databases),
        }
        digest = hashlib.sha256(
            json.dumps(signature, ensure_ascii=False).encode()
        ).hexdigest()
        summary = {
            "projectId": project.pk,
            "name": project.name,
            "resourceCount": len(resources),
            "recordCount": len(rows),
            "sharedResourceCount": sum(
                model == DataResource._meta.label_lower for model, _ in retained
            ),
            "sharedFileCount": sum(p.shared for p in plans)
            + shared_files
            + len(shared_paths),
            "estimatedBytes": sum(
                p.stat().st_size for p in storage.files if p.is_file()
            ),
        }
        return collector, storage, digest, summary
    raise ValidationError("共享关联较复杂，已保留全部数据，请先检查项目关联")


def preview(project, actor):
    if not is_superadmin(actor):
        raise ValidationError("只有超级管理员可以删除项目")
    with project_scope(ProjectScope((project.pk,), project.pk, actor.pk, True)):
        _, _, digest, summary = build_plan(project)
    token = signing.dumps(
        {"project": project.pk, "actor": actor.pk, "digest": digest},
        salt=TOKEN_SALT,
        compress=True,
    )
    return {**summary, "confirmationToken": token}


def remove(project, actor, value, request):
    if not is_superadmin(actor):
        raise ValidationError("只有超级管理员可以删除项目")
    if (
        value.get("confirmedName") != project.name
        or value.get("deleteExclusiveData") is not True
    ):
        raise ValidationError(
            "请输入完整项目名称，并确认清理项目独占数据；共享数据会保留"
        )
    try:
        signed = signing.loads(
            value.get("confirmationToken", ""), salt=TOKEN_SALT, max_age=TOKEN_SECONDS
        )
    except signing.BadSignature as exc:
        raise ValidationError("删除确认已失效，请重新检查范围") from exc
    storage = None
    try:
        with project_scope(ProjectScope((project.pk,), project.pk, actor.pk, True)):
            with transaction.atomic(durable=True):
                if not Project.objects.filter(pk=project.pk, deleted_at=None).update(
                    sort_order=F("sort_order")
                ):
                    raise ValidationError("项目已删除或状态已变化")
                project.refresh_from_db()
                collector, storage, digest, summary = build_plan(project)
                if signed != {
                    "project": project.pk,
                    "actor": actor.pk,
                    "digest": digest,
                }:
                    raise ValidationError("项目内容或共享引用已变化，请重新预览后确认")
                with storage:
                    collector.delete()
                    project.is_active = False
                    project.deleted_at = timezone.now()
                    project.save(update_fields=["is_active", "deleted_at"])
                    with project_scope(ProjectScope((1,), 1, actor.pk, True)):
                        log_operation(
                            actor,
                            "项目标签",
                            "删除项目及独占数据",
                            "success",
                            json.dumps(summary, ensure_ascii=False),
                            request,
                            target_type="project",
                            target_id=project.pk,
                            target_name=project.name,
                        )
                transaction.on_commit(storage.finalize)
        detail = "项目及独占数据已删除，共享数据已保留"
        if storage.cleanup_failed:
            detail = "项目已删除，共享数据已保留；部分隔离文件待清理"
        return {"detail": detail, **summary}
    except Exception:
        if storage:
            storage.restore_staged_files()
        raise
    finally:
        if storage and storage.locked:
            storage.close()
