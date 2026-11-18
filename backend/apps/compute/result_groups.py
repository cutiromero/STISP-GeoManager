"""Bounded task-oriented catalogue projection; never rewrites import provenance."""

from django.db.models import Exists, Max, OuterRef, Subquery, UUIDField
from django.db.models.functions import Coalesce

from apps.agent.models import AgentWorkflowStep
from apps.catalog.models import DataResource, task_resource_q
from apps.catalog.permissions import filter_accessible
from apps.ecology.official_monitoring import PUBLISHABLE, official_products
from .access import project_id, permission, require_actor
from .models import ComputeImport, ComputeTask

PAGE_SIZE = 15
MAX_RESULTS_PER_GROUP = 100


def catalogue_groups(user, page, group_id=None):
    project = project_id()
    require_actor(user, project, "core.browse_data")
    own = permission(user, "view_own_task")
    manage = permission(user, "manage_tasks")
    if not own and not manage:
        return {"items": [], "hasMore": False}
    visible = filter_accessible(
        DataResource.objects.filter(
            project_tag_id=project,
            status="active",
            is_compute_result=True,
        ).exclude(task_resource_q()),
        user,
    )
    imports = ComputeImport.objects.filter(
        status="ready", resource_id__in=visible.values("pk")
    )
    links = AgentWorkflowStep.objects.filter(
        compute_task_id=OuterRef("pk"),
        workflow__project_tag_id=project,
        workflow__owner_id=OuterRef("owner_id"),
    ).order_by("pk")
    tasks = ComputeTask.objects.filter(
        status="succeeded", trial=False, project_tag_id=project
    )
    if not manage:
        tasks = tasks.filter(owner=user)
    tasks = (
        tasks.filter(Exists(imports.filter(output__task_id=OuterRef("pk"))))
        .annotate(
            parent=Subquery(links.values("workflow_id")[:1], output_field=UUIDField()),
            parent_name=Subquery(links.values("workflow__goal")[:1]),
            parent_created=Subquery(links.values("workflow__created_at")[:1]),
        )
        .annotate(
            group_id=Coalesce("parent", "pk", output_field=UUIDField()),
            group_created=Coalesce("parent_created", "created_at"),
        )
    )
    if group_id is not None:
        tasks = tasks.filter(group_id=group_id)
    offset = (page - 1) * PAGE_SIZE
    heads = list(
        tasks.order_by()
        .values("group_id")
        .annotate(latest=Max("group_created"))
        .order_by("-latest", "group_id")[offset : offset + PAGE_SIZE + 1]
    )
    selected = heads[:PAGE_SIZE]
    identities = [head["group_id"] for head in selected]
    if not identities:
        return {"items": [], "hasMore": False}
    task_rows = list(
        tasks.filter(group_id__in=identities)
        .select_related("version__algorithm")
        .order_by("created_at", "pk")
    )
    task_lookup = {task.pk: task for task in task_rows}
    rows = list(
        imports.filter(output__task_id__in=task_lookup)
        .select_related("output", "resource")
        .order_by("output_id")
    )
    published = set(
        official_products()
        .filter(
            data_resource_id__in=[row.resource_id for row in rows],
            project_tag_id=project,
        )
        .values_list("data_resource_id", flat=True)
    )
    can_register = permission(user, "catalog.add_dataresource") and permission(
        user, "core.load_raster_layer"
    )
    can_download = permission(user, "catalog.export_dataresource")
    groups = {}
    for row in rows:
        output = row.output
        task = task_lookup[output.task_id]
        group = groups.setdefault(
            task.group_id,
            {
                "id": str(task.group_id),
                "name": (task.parent_name or task.name)[:180],
                "workflowId": str(task.parent)
                if task.parent and task.owner_id == user.pk
                else None,
                "createdAt": task.group_created.isoformat(),
                "items": [],
                "total": 0,
            },
        )
        group["total"] += 1
        if len(group["items"]) >= MAX_RESULTS_PER_GROUP:
            continue
        trusted = output.metadata.get("qualityCheck", {}).get("status") == "passed"
        registered = row.resource_id in published
        eligible = bool(
            can_register
            and task.owner_id == user.pk
            and row.requested_by_id == user.pk
            and trusted
            and not output.expired
            and (task.version.algorithm.identifier, output.key) in PUBLISHABLE
        )
        group["items"].append(
            {
                "id": output.pk,
                "taskId": str(task.pk),
                "taskName": task.name,
                "name": row.resource.name,
                "kind": output.kind,
                "resourceId": row.resource_id,
                "fileName": output.file_name,
                "registered": registered,
                "canRegister": eligible,
                "downloadUrl": f"/api/compute/outputs/{output.pk}/file/?projectTagId={project}"
                if can_download and not output.expired
                else None,
            }
        )
    return {
        "items": [groups[key] for key in identities if key in groups],
        "hasMore": len(heads) > PAGE_SIZE,
    }
