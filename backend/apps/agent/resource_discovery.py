"""Business discovery is narrower than ACL access to bound research materials."""

import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import BooleanField, Case, F, Q, Value, When

from apps.catalog.models import (
    DataResource,
    INTERNAL_SOURCE_PREFIXES,
    RESERVED_RULE_CODES,
)
from apps.catalog.permissions import filter_accessible
from apps.compute.access import project_id
from apps.compute.models import ComputeImport
from apps.projects.access import can_access_project

from .models import AgentWorkflow, AgentWorkflowStep, WorkflowUpload


MULTI_FINAL_OUTPUT_KEYS = {
    "apply": {"lithology", "final_faults", "final_alterations"}
    | {
        mineral + "_" + suffix
        for mineral in ("hematite", "chlorite", "hydromica", "calcite", "dolomite")
        for suffix in ("corrected", "weight")
    },
    "relations": {"intersections"},
    "prospect": {"before_zones", "after_zones", "evidence", "prospect_support"},
}
FINAL_STAGE_OUTPUTS = {
    **{
        (workflow_type, stage): ("geology-multi-" + stage, keys)
        for workflow_type in ("geology_generic", "geology_multi_element_reasoning")
        for stage, keys in MULTI_FINAL_OUTPUT_KEYS.items()
    },
    ("ecology_investigation", "change"): ("ndvi-change", {"change", "candidates"}),
    ("ecology_investigation", "priority"): (
        "ecology-priority",
        {"priority", "statistics"},
    ),
    ("geology_correction", "edit"): ("geology-edit", {"corrected"}),
    ("geology_age_correction", "edit"): ("geology-age-edit", {"corrected"}),
    ("geology_map_review", "edit"): (
        "geology-map-correct",
        {"corrected", "changes_map"},
    ),
}
_INTERNAL_SCOPE = ContextVar("agent_discovery_internal_scope", default=None)


@contextmanager
def discovery_scope():
    """Reuse provenance indexing within one authorization check, never across it."""
    if _INTERNAL_SCOPE.get() is not None:
        yield
        return
    token = _INTERNAL_SCOPE.set({})
    try:
        yield
    finally:
        _INTERNAL_SCOPE.reset(token)


def acl_resources(user, policy, selected=(), *, active=True):
    """Low-level access only; callers must independently prove internal binding."""
    query = filter_accessible(
        DataResource.objects.filter(project_tag_id=project_id()), user
    ).filter(data_type__in=policy["dataTypes"])
    if not user.is_active or not can_access_project(user, project_id()):
        return query.none()
    if active:
        query = query.filter(status="active")
    return query.filter(pk__in=selected) if selected else query


def resolve_acl_resource(user, policy, resource_id, selected=(), *, active=True):
    """For trusted binding/history resolvers, never a model-facing ID exception."""
    _validate_identity(resource_id)
    resource = (
        acl_resources(user, policy, selected, active=active)
        .filter(pk=resource_id)
        .first()
    )
    if resource is None:
        raise PermissionDenied("资源不存在、已失效或无权访问")
    return resource


def _validate_identity(resource_id):
    if type(resource_id) is not int or resource_id < 1:
        raise ValidationError("resourceId 必须是有效资源 ID")


def workflow_task_ids():
    return AgentWorkflowStep.objects.filter(
        workflow__project_tag_id=project_id(), compute_task_id__isnull=False
    ).values("compute_task_id")


def discover_resources(user, policy, selected=()):
    """One current-project set for search, counts, selectors and direct reads."""
    from apps.raster.models import RasterDataset

    ready_rasters = RasterDataset.objects.filter(
        project_tag_id=project_id(), status="ready"
    ).values("data_resource_id")
    query = acl_resources(user, policy, selected).filter(
        ~Q(data_type="raster") | Q(pk__in=ready_rasters)
    )
    excluded = Q(code__in=RESERVED_RULE_CODES)
    excluded |= Q(code__startswith="geology-multi-rules")
    excluded |= Q(code__startswith="geology-review-", code__endswith="-rules")
    for prefix in INTERNAL_SOURCE_PREFIXES:
        excluded |= Q(source__startswith=prefix)
    uploads = WorkflowUpload.objects.filter(source="upload").values("resource_id")
    query = (
        query.exclude(excluded)
        .exclude(pk__in=uploads)
        .exclude(pk__in=_internal_resource_ids())
    )
    imports = ComputeImport.objects.filter(resource__in=query)
    ordinary = (
        imports.filter(
            status="ready",
            output__task__status="succeeded",
            output__task__trial=False,
            output__task__project_tag_id=project_id(),
        )
        .exclude(output__task_id__in=workflow_task_ids())
        .exclude(request_source__startswith="workflow:")
    )
    finals = _final_resource_ids(query, imports) | _report_resource_ids(query, user)
    # Bare legacy flags and unverified system markers are not provenance.
    originals = Q(is_compute_result=False) & ~Q(pk__in=imports.values("resource_id"))
    originals &= ~Q(source__startswith="compute-output:")
    originals &= ~Q(source__startswith="workflow-report:")
    computed = Q(pk__in=ordinary.values("resource_id")) | Q(pk__in=finals)
    return query.filter(originals | computed).annotate(
        _agent_compute_result=Case(
            When(computed, then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        )
    )


def resolve_discoverable_resource(user, policy, resource_id, selected=()):
    _validate_identity(resource_id)
    if selected and resource_id not in selected:
        raise PermissionDenied("资源不在本轮已选择的数据范围")
    resource = discover_resources(user, policy, [resource_id]).first()
    if resource is None:
        raise PermissionDenied("资源不存在、已失效或不在当前业务数据范围")
    return resource


def _internal_resource_ids():
    scope = _INTERNAL_SCOPE.get()
    project = project_id()
    if scope is not None and project in scope:
        return scope[project]
    values = set()
    keys = ("workingCopies", "frozen_rules", "approved_changes", "model_changes")
    rows = AgentWorkflow.objects.filter(project_tag_id=project).values_list(
        *("plan__" + key for key in keys)
    )
    for row in rows.iterator():
        for item in row:
            if type(item) is int:
                values.add(item)
            elif isinstance(item, dict):
                values.update(value for value in item.values() if type(value) is int)
    if scope is not None:
        scope[project] = values
    return values


def _final_resource_ids(query, imports):
    """Completed stages, actual outputs and ready imports must agree."""
    records = {
        item.output_id: item
        for item in imports.filter(
            status="ready",
            output__task__status="succeeded",
            output__task__trial=False,
            output__task_id__in=workflow_task_ids(),
        ).select_related("output__task__version__algorithm")
    }
    if not records:
        return set()
    task_ids = {item.output.task_id for item in records.values()}
    workflows = list(
        AgentWorkflow.objects.filter(
            status="succeeded",
            project_tag_id=project_id(),
            steps__compute_task_id__in=task_ids,
        )
        .values(
            "id",
            "owner_id",
            "project_tag_id",
            "workflow_type",
            "result_resource_ids",
            "plan__stages",
        )
        .distinct()
    )
    completed = {
        (workflow_id, str(task_id))
        for workflow_id, task_id in AgentWorkflowStep.objects.filter(
            workflow_id__in=[item["id"] for item in workflows],
            compute_task_id__in=task_ids,
            kind="collect_results",
            status="succeeded",
        ).values_list("workflow_id", "compute_task_id")
    }
    results = set()
    for workflow in workflows:
        stages = workflow["plan__stages"]
        if not isinstance(stages, list) or not isinstance(
            workflow["result_resource_ids"], list
        ):
            continue
        for stage in stages:
            if not isinstance(stage, dict) or stage.get("status") != "completed":
                continue
            task_id = stage.get("taskId")
            if (workflow["id"], task_id) not in completed:
                continue
            outputs = stage.get("outputs", [])
            if not isinstance(outputs, list):
                continue
            for output in outputs:
                if not isinstance(output, dict):
                    continue
                record = records.get(output.get("outputId"))
                if record is None or not _terminal_output(
                    workflow["workflow_type"], stage, record.output
                ):
                    continue
                task = record.output.task
                if (
                    str(task.id) == task_id
                    and task.owner_id == workflow["owner_id"]
                    and task.project_tag_id == workflow["project_tag_id"]
                    and record.resource_id == output.get("resourceId")
                    and record.resource_id in workflow["result_resource_ids"]
                    and record.output.key == output.get("key")
                    and record.output.checksum == output.get("checksum")
                ):
                    results.add(record.resource_id)
    return results


def _terminal_output(workflow_type, stage, output):
    definition = FINAL_STAGE_OUTPUTS.get((workflow_type, stage.get("name")))
    if definition is None:
        return False
    identifier, keys = definition
    version = output.task.version
    manifest = version.manifest or {}
    if (
        version.algorithm.identifier != identifier
        or manifest.get("identifier") != identifier
        or stage.get("identifier", identifier) != identifier
    ):
        return False
    declared = {
        item.get("key")
        for item in manifest.get("outputs", [])
        if isinstance(item, dict) and item.get("kind") != "archive"
    }
    if output.key not in declared:
        return False
    if output.key in keys:
        return True
    if stage.get("name") == "apply" and workflow_type in {
        "geology_generic",
        "geology_multi_element_reasoning",
    }:
        if output.key == "faults" and "final_faults" not in declared:
            return True
        if output.key == "alterations" and "final_alterations" not in declared:
            return not any(
                key.endswith("_corrected") for key in declared if isinstance(key, str)
            )
    return False


def _report_resource_ids(query, user):
    from .workflow_reports import _paths, _source, load_report
    from apps.compute.packages import ComputeError

    reports = list(query.filter(source__startswith="workflow-report:"))
    if not reports:
        return set()
    workflow_ids = set()
    for item in reports:
        try:
            workflow_ids.add(uuid.UUID(item.source.split(":")[1]))
        except (ValueError, IndexError, AttributeError):
            continue
    results = set()
    workflows = (
        AgentWorkflow.objects.filter(
            pk__in=workflow_ids, status="succeeded", project_tag_id=project_id()
        )
        .annotate(_report_algorithms=F("plan__algorithms"))
        .only("id", "owner_id", "project_tag_id", "workflow_type")
    )
    for workflow in workflows:
        workflow.plan = {"algorithms": workflow._report_algorithms or {}}
        candidates = [item for item in reports if item.source == _source(workflow)]
        if not candidates:
            continue
        try:
            metadata, _ = load_report(workflow, user)
        except (ComputeError, PermissionDenied, OSError, ValueError):
            continue
        _, _, relative = _paths(workflow)
        for item in candidates:
            if (
                item.id == metadata.get("resourceId")
                and item.maintainer_id == workflow.owner_id
                and item.storage_path == "table/" + relative
                and item.quality_note == "SHA256: " + metadata["checksum"]
            ):
                results.add(item.id)
    return results
