from .access import permission, project_id
from .models import ComputeTask, ComputeImport


def version_data(version):
    return {
        "id": version.id,
        "version": version.version,
        "status": version.status,
        "checksum": version.checksum,
        "manifest": version.manifest,
        "runtimeDigest": version.runtime_digest,
        "validated": ComputeTask._base_manager.filter(
            version=version, trial=True, status="succeeded"
        ).exists(),
        "createdAt": version.created_at.isoformat(),
    }


def algorithm_data(algorithm, user):
    manage = algorithm.project_tag_id == project_id() and permission(
        user, "manage_algorithms"
    )
    versions = algorithm.versions.all()
    if not manage:
        versions = versions.filter(status="published")
    return {
        "id": algorithm.id,
        "projectTagId": algorithm.project_tag_id,
        "identifier": algorithm.identifier,
        "name": algorithm.name,
        "description": algorithm.description,
        "category": algorithm.category,
        "author": algorithm.author,
        "enabled": algorithm.enabled,
        "versions": [version_data(v) for v in versions],
        "canManage": manage,
    }


def output_data(output):
    record = ComputeImport.objects.filter(output=output).first()
    suffix = f"?projectTagId={output.task.project_tag_id}"
    resource = None
    if record and record.resource_id and record.status == "ready":
        from django.contrib.auth import get_user_model
        from apps.catalog.models import DataResource
        from apps.catalog.permissions import filter_accessible
        from apps.projects.context import current_scope

        scope = current_scope.get()
        actor = (
            get_user_model().objects.filter(pk=scope.user_id).first() if scope else None
        )
        if actor:
            resource = filter_accessible(
                DataResource.objects.filter(pk=record.resource_id, status="active"),
                actor,
            ).first()
    location = (
        output.task.project_tag.name + " / 数据资源 / 计算结果 / " + resource.name
        if resource
        else ""
    )
    return {
        "id": output.id,
        "key": output.key,
        "label": output.label,
        "kind": output.kind,
        "fileName": output.file_name,
        "sizeBytes": output.size_bytes,
        "checksum": output.checksum,
        "metadata": output.metadata,
        "expired": output.expired,
        "importStatus": record.status if record else "none",
        "resourceId": record.resource_id if record else None,
        "resourceName": resource.name
        if resource
        else record.name + "（目录数据已删除）"
        if record and record.status == "deleted"
        else "",
        "resourceLocation": location,
        "mapUrl": (
            f"/map?resourceId={resource.id}&projectTagId={output.task.project_tag_id}"
            + (
                "&displayGeometry=1"
                if output.task.version.algorithm.identifier.startswith("geology-multi-")
                else ""
            )
        )
        if resource
        else "",
        "importError": record.error if record else "",
        "downloadUrl": f"/api/compute/outputs/{output.id}/file/{suffix}",
        "previewUrl": f"/api/compute/outputs/{output.id}/preview/{suffix}",
    }


def task_data(task):
    return {
        "id": str(task.id),
        "name": task.name,
        "projectTagId": task.project_tag_id,
        "ownerName": task.owner.get_full_name() or task.owner.get_username(),
        "algorithmName": task.version.algorithm.name,
        "version": version_data(task.version),
        "status": task.status,
        "stage": task.stage,
        "progress": task.progress,
        "error": task.error,
        "parameters": task.parameters,
        "inputs": [
            {
                "key": r.key,
                "resourceId": r.resource_id,
                "checksum": r.checksum,
                **r.snapshot,
            }
            for r in task.input_records.all()
        ],
        "outputs": [output_data(o) for o in task.outputs.all()],
        "createdAt": task.created_at.isoformat(),
        "startedAt": task.started_at.isoformat() if task.started_at else None,
        "finishedAt": task.finished_at.isoformat() if task.finished_at else None,
        "trial": task.trial,
        "unread": task.unread,
        "retryOf": str(task.retry_of_id) if task.retry_of_id else None,
        "attemptCount": task.attempts.count(),
    }
