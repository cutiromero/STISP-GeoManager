"""User/project-owned confirmed catalog inputs; never an execution authorization."""

from .models import AgentRun, LogicConfiguration, WorkflowUpload
from .workflow import _state_hash
from .workflow_uploads import catalog_resources


PUBLIC_KEYS = ("resourceIds", "roles", "fieldMapping", "prompt", "reasoningEffort")


def snapshot(upload):
    return _state_hash(
        {
            "updatedAt": upload.resource.updated_at.isoformat(),
            "profile": upload.profile,
        }
    )


def read_configuration(user, project_id):
    available = catalog_resources(user, project_id)
    saved = LogicConfiguration.objects.filter(
        owner=user, project_tag_id=project_id
    ).first()
    if saved is None:
        return None, []
    value = saved.value
    resources = {
        str(item.pk): item for item in available.filter(pk__in=value["resourceIds"])
    }
    unavailable = [
        identity
        for identity in value["resourceIds"]
        if str(identity) not in resources
        or resources[str(identity)].updated_at.isoformat()
        != value["updatedAt"].get(str(identity))
    ]
    return value, unavailable


def configuration_json(value, unavailable, items=None):
    return {
        "configuration": {key: value[key] for key in PUBLIC_KEYS} if value else None,
        "unavailableResourceIds": unavailable,
        "items": items or [],
    }


def matching_configuration(run, uploads):
    if not run.research_intent.get("_reuseConfirmedConfiguration"):
        return None
    value, unavailable = read_configuration(run.owner, run.project_tag_id)
    if (
        not value
        or unavailable
        or "lithology" not in value["roles"]
        or any(item.source != "catalog" for item in uploads)
    ):
        return None
    if {item.resource_id for item in uploads} != set(value["resourceIds"]):
        return None
    if any(
        snapshot(item) != value["snapshots"].get(str(item.resource_id))
        for item in uploads
    ):
        return None
    return value


def save_configuration(workflow, mapping):
    if workflow.workflow_type != "geology_generic":
        return
    from apps.compute.project_tools import GEOLOGY_PROJECT_CODES
    from apps.projects.models import Project

    if not Project.objects.filter(
        pk=workflow.project_tag_id, code__in=GEOLOGY_PROJECT_CODES
    ).exists():
        return
    uploads = list(
        WorkflowUpload.objects.filter(
            workflow=workflow, source="catalog"
        ).select_related("resource")
    )
    if not uploads:
        return
    available = catalog_resources(workflow.owner, workflow.project_tag_id)
    identities = {item.resource_id for item in uploads}
    if (
        set(available.filter(pk__in=identities).values_list("pk", flat=True))
        != identities
    ):
        return
    run = (
        AgentRun.objects.filter(research_workflow=workflow, owner=workflow.owner)
        .order_by("id")
        .first()
    )
    value = {
        "resourceIds": sorted(identities),
        "roles": {
            role: identity
            for role, identity in workflow.plan["uploadInputs"].items()
            if identity in identities
        },
        "fieldMapping": {
            role: fields
            for role, fields in mapping.items()
            if workflow.plan["uploadInputs"].get(role) in identities
        },
        "prompt": workflow.goal,
        "reasoningEffort": (
            run.reasoning_effort if run and run.thinking_mode == "deep" else "low"
        )
        or "low",
        "updatedAt": {
            str(item.resource_id): item.resource.updated_at.isoformat()
            for item in uploads
        },
        "snapshots": {str(item.resource_id): snapshot(item) for item in uploads},
    }
    LogicConfiguration.objects.update_or_create(
        owner=workflow.owner,
        project_tag_id=workflow.project_tag_id,
        defaults={"value": value},
    )
