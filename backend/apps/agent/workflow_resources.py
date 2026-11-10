"""Explicit resource scopes for research tasks, separate from business discovery."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied

from apps.projects.context import selected_project_id


# Configuration: reserved, server-registered rule packets are scenario inputs.
RULE_CODES = {
    "geology_correction": ("demo-geology-rules",),
    "geology_age_correction": ("real-geology-age-rules",),
    "geology_map_review": ("geology-review-expanded-20261025-rules",),
}
MULTI_SCENARIOS = {"geology_generic", "geology_multi_element_reasoning"}
PRIVATE_SOURCE_PREFIXES = (
    "workflow-working:",
    "geology-multi-frozen-rules:",
    "demo-changes:",
    "geology-multi-approved:",
)


def _check_scope(user, scope):
    if scope.owner_id != user.pk or scope.project_tag_id != selected_project_id():
        raise PermissionDenied("资料不属于当前用户的项目任务")


def scenario_rule_resources(user, policy, scenario):
    """Only the registered rule family; rule contents still require knowledge ACL."""
    from .resource_discovery import acl_resources

    query = acl_resources(user, policy).filter(data_type="table")
    if scenario in MULTI_SCENARIOS:
        return query.filter(code__startswith="geology-multi-rules")
    return query.filter(code__in=RULE_CODES.get(scenario, ()))


def resolve_scenario_resource(user, policy, identity, scenario, role, selected=()):
    """A role is server-chosen; an arbitrary selected ID grants no internal access."""
    from .resource_discovery import resolve_discoverable_resource

    try:
        return resolve_discoverable_resource(user, policy, identity, selected)
    except PermissionDenied:
        if role != "rules" or (selected and identity not in selected):
            raise
        result = (
            scenario_rule_resources(user, policy, scenario).filter(pk=identity).first()
        )
        if result is None:
            raise PermissionDenied("规则资料未登记到当前场景") from None
        return result


def resolve_upload_resource(user, policy, identity, batch_id, *, workflow=None):
    from .models import WorkflowUpload
    from .resource_discovery import resolve_acl_resource, resolve_discoverable_resource
    from .workflow_uploads import checked_batch

    uploads = WorkflowUpload.objects.filter(
        owner=user,
        project_tag_id=selected_project_id(),
        resource_id=identity,
        batch_id=checked_batch(batch_id),
    )
    if workflow is not None:
        _check_scope(user, workflow)
        uploads = uploads.filter(workflow_id=workflow.pk)
    else:
        uploads = uploads.filter(workflow_id=None)
    upload = uploads.first()
    if upload is None:
        raise PermissionDenied("资料不属于本次上传批次或已用于其他任务")
    if upload.source == "catalog":
        return resolve_discoverable_resource(user, policy, identity)
    return resolve_acl_resource(user, policy, identity)


def _workflow_input_ids(workflow):
    plan = workflow.plan or {}
    values = set(workflow.resource_ids or [])
    for key in ("inputs", "uploadInputs", "workingCopies"):
        data = plan.get(key, {})
        if isinstance(data, dict):
            values.update(v for v in data.values() if type(v) is int)
    for key in ("rulesResourceId", "frozen_rules", "approved_changes", "model_changes"):
        if type(plan.get(key)) is int:
            values.add(plan[key])
    return values


def authorize_workflow_resources(user, policy, identities, workflow):
    """Batch the same live ACL and provenance checks used by the single resolver."""
    from .models import AgentWorkflow, WorkflowUpload
    from .resource_discovery import (
        acl_resources,
        discover_resources,
        _validate_identity,
    )
    from apps.compute.models import ComputeImport

    selected = set(identities)
    if not selected:
        return
    for identity in selected:
        _validate_identity(identity)
    _check_scope(user, workflow)
    if not AgentWorkflow.objects.filter(
        pk=workflow.pk, owner=user, project_tag_id=workflow.project_tag_id
    ).exists():
        raise PermissionDenied("科研任务不存在或已不可用")
    resources = (
        acl_resources(user, policy, selected)
        .only("id", "source", "owner_only", "maintainer_id")
        .in_bulk()
    )
    if set(resources) != selected:
        raise PermissionDenied("资源不存在、已失效或无权访问")
    inputs = _workflow_input_ids(workflow)
    allowed = set()
    for identity, resource in resources.items():
        if (
            identity in inputs
            and resource.owner_only
            and resource.maintainer_id == workflow.owner_id
        ):
            if any(
                resource.source == prefix + str(workflow.pk)
                or resource.source.startswith(prefix + str(workflow.pk) + ":")
                for prefix in PRIVATE_SOURCE_PREFIXES
            ):
                allowed.add(identity)
    remaining = selected - allowed
    if remaining:
        task_ids = workflow.steps.exclude(compute_task_id=None).values(
            "compute_task_id"
        )
        allowed.update(
            ComputeImport.objects.filter(
                resource_id__in=remaining,
                status="ready",
                output__task__status="succeeded",
                output__task__trial=False,
                output__task__owner_id=workflow.owner_id,
                output__task__project_tag_id=workflow.project_tag_id,
                output__task_id__in=task_ids,
            ).values_list("resource_id", flat=True)
        )
    remaining = selected - allowed
    if remaining and workflow.plan.get("uploadBatchId"):
        allowed.update(
            WorkflowUpload.objects.filter(
                workflow=workflow,
                owner=user,
                project_tag_id=workflow.project_tag_id,
                batch_id=workflow.plan["uploadBatchId"],
                resource_id__in=remaining & inputs,
                source="upload",
            ).values_list("resource_id", flat=True)
        )
    remaining = selected - allowed
    if remaining:
        rule_ids = {
            workflow.plan.get("rulesResourceId"),
            workflow.plan.get("inputs", {}).get("rules"),
        }
        rule_ids.discard(None)
        if remaining & rule_ids:
            allowed.update(
                scenario_rule_resources(user, policy, workflow.workflow_type)
                .filter(pk__in=remaining & rule_ids & inputs)
                .values_list("pk", flat=True)
            )
    remaining = selected - allowed
    if remaining:
        candidates = remaining & inputs
        if workflow.resource_ids:
            candidates &= set(workflow.resource_ids)
        allowed.update(
            discover_resources(user, policy)
            .filter(pk__in=candidates)
            .values_list("pk", flat=True)
        )
    # Retain specialized historical update-chain handling without duplicating it.
    for identity in selected - allowed:
        resolve_workflow_resource(user, policy, identity, workflow)


def resolve_generated_resource(user, policy, identity, workflow, purpose):
    """Recover a server-generated packet by its fixed task marker, never by selection."""
    from .models import AgentWorkflow
    from .resource_discovery import resolve_acl_resource

    _check_scope(user, workflow)
    if not AgentWorkflow.objects.filter(pk=workflow.pk, owner=user).exists():
        raise PermissionDenied("科研任务不存在")
    sources = {
        "frozen_rules": "geology-multi-frozen-rules:",
        "approved_changes": "geology-multi-approved:",
        "model_changes": "demo-changes:",
    }
    if purpose not in sources:
        raise PermissionDenied("未登记的内部资料用途")
    result = resolve_acl_resource(user, policy, identity)
    marker = sources[purpose] + str(workflow.pk)
    if purpose == "approved_changes" and workflow.plan.get("retainedReviewHistory"):
        marker += f":review-{len(workflow.plan['retainedReviewHistory'])}"
    if (
        result.source != marker
        or not result.owner_only
        or result.maintainer_id != workflow.owner_id
        or not result.storage_path.startswith(f"table/demo/workflows/{workflow.pk}/")
    ):
        raise PermissionDenied("内部资料不属于本次任务的指定用途")
    return result


def resolve_workflow_resource(user, policy, identity, workflow, *, history=False):
    """Read internal data only through the real task that created or bound it."""
    from .models import AgentWorkflow, WorkflowUpload
    from .resource_discovery import resolve_acl_resource, resolve_discoverable_resource
    from apps.compute.models import ComputeImport, ComputeInput

    _check_scope(user, workflow)
    if not AgentWorkflow.objects.filter(
        pk=workflow.pk, owner=user, project_tag_id=workflow.project_tag_id
    ).exists():
        raise PermissionDenied("科研任务不存在或已不可用")
    resource = resolve_acl_resource(user, policy, identity, active=not history)
    # Imported catalog data remains valid after its raw calculation file expires.
    # Only a real owned task recorded by this workflow establishes this binding.
    task_ids = workflow.steps.exclude(compute_task_id=None).values("compute_task_id")
    bound_output = ComputeImport.objects.filter(
        resource_id=identity,
        status="ready",
        output__task__status="succeeded",
        output__task__trial=False,
        output__task__owner_id=workflow.owner_id,
        output__task__project_tag_id=workflow.project_tag_id,
        output__task_id__in=task_ids,
    )
    if (
        history
        and ComputeInput.objects.filter(
            resource_id=identity,
            task_id__in=task_ids,
            task__owner_id=workflow.owner_id,
            task__project_tag_id=workflow.project_tag_id,
            task__trial=False,
        ).exists()
    ):
        # Previous rounds retain real task inputs. This is historical reading
        # under the current ACL; it never authorizes a new calculation.
        return resource
    inputs = _workflow_input_ids(workflow)
    if (
        history
        and identity in inputs
        and (not workflow.resource_ids or identity in workflow.resource_ids)
    ):
        # Saved input metadata remains readable under the current ACL even if
        # its discovery status changed. This branch never authorizes execution.
        return resource
    if bound_output.exists():
        return resource
    if identity in inputs:
        batch = (workflow.plan or {}).get("uploadBatchId")
        if (
            batch
            and WorkflowUpload.objects.filter(
                workflow=workflow,
                owner=user,
                project_tag_id=workflow.project_tag_id,
                batch_id=batch,
                resource_id=identity,
                source="upload",
            ).exists()
        ):
            return resource
        # Working copies and frozen packets are written by this workflow only.
        # Both the workflow ID in the marker and its private owner must match.
        if resource.owner_only and resource.maintainer_id == workflow.owner_id:
            for prefix in PRIVATE_SOURCE_PREFIXES:
                marker = prefix + str(workflow.pk)
                if resource.source == marker or resource.source.startswith(
                    marker + ":"
                ):
                    return resource
        role = next(
            (
                k
                for k, v in (workflow.plan or {}).get("inputs", {}).items()
                if v == identity
            ),
            "rules"
            if identity == (workflow.plan or {}).get("rulesResourceId")
            else None,
        )
        if (
            role == "rules"
            and scenario_rule_resources(user, policy, workflow.workflow_type)
            .filter(pk=identity)
            .exists()
        ):
            return resource
        try:
            business_resource = resolve_discoverable_resource(user, policy, identity)
        except PermissionDenied:
            pass
        else:
            if workflow.resource_ids and identity not in workflow.resource_ids:
                raise PermissionDenied("业务资料不在本次科研任务已选择的数据范围")
            return business_resource
    if (
        workflow.workflow_type == "ecology_investigation"
        and identity == (workflow.plan or {}).get("previous_change")
        and workflow.plan.get("previousWorkflowId")
    ):
        # Evidence updates reuse one verified earlier calculation. Neither a
        # previous workflow ID nor a copied resource ID alone establishes scope.
        from .demo_updates import _chain, _change, _semantics

        chain = _chain(workflow, user, policy, history=history)
        _semantics(chain[0], workflow, chain)
        previous_change = _change(chain, user, policy)
        if (
            previous_change != workflow.plan.get("previousChange")
            or previous_change["resourceId"] != identity
        ):
            raise PermissionDenied("前次计算结果的真实绑定已变化")
        return resource
    raise PermissionDenied("内部资料未绑定到当前科研任务")


def authorize_run_resource_ids(user, policy, identities, run):
    """Authorize one evidence set together; private bindings keep their resolver."""
    from .models import AgentRun
    from .resource_discovery import discover_resources

    _check_scope(user, run)
    persisted = AgentRun.objects.filter(
        pk=run.pk, owner=user, project_tag_id=run.project_tag_id
    ).first()
    if persisted is None:
        raise PermissionDenied("对话任务不存在")
    ordinary = set(
        discover_resources(user, policy, sorted(identities)).values_list(
            "id", flat=True
        )
    )
    selected = persisted.resource_ids or []
    if ordinary and (
        (persisted.data_selection_mode == "manual" and not selected)
        or (selected and not ordinary <= set(selected))
    ):
        raise PermissionDenied("业务资料不在本轮已选择的数据范围")
    for identity in identities - ordinary:
        resolve_run_resource(user, policy, identity, persisted)


def resolve_run_resource(user, policy, identity, run, *, history=False):
    """A run may use only its own workflow or its actually attached upload batch."""
    from .models import AgentRun, AgentWorkflow
    from .resource_discovery import resolve_discoverable_resource

    _check_scope(user, run)
    persisted = AgentRun.objects.filter(
        pk=run.pk, owner=user, project_tag_id=run.project_tag_id
    ).first()
    if persisted is None:
        raise PermissionDenied("对话任务不存在")
    try:
        business_resource = resolve_discoverable_resource(user, policy, identity)
    except PermissionDenied:
        business_resource = None
    if business_resource is not None:
        selected = persisted.resource_ids or []
        if (persisted.data_selection_mode == "manual" and not selected) or (
            selected and identity not in selected
        ):
            raise PermissionDenied("业务资料不在本轮已选择的数据范围")
        return business_resource
    if persisted.research_workflow_id:
        workflow = AgentWorkflow.objects.filter(
            pk=persisted.research_workflow_id,
            owner=user,
            project_tag_id=run.project_tag_id,
        ).first()
        if workflow is not None:
            return resolve_workflow_resource(
                user, policy, identity, workflow, history=history
            )
    batch_id = (persisted.research_intent or {}).get("_uploadBatchId")
    if batch_id:
        return resolve_upload_resource(user, policy, identity, batch_id)
    raise PermissionDenied("资料未绑定到当前对话任务")


def display_input_names(workflow):
    """Current permitted registration labels without altering frozen provenance."""
    from apps.catalog.models import DataResource
    from apps.catalog.permissions import filter_accessible

    sources = {
        **workflow.plan.get("inputs", {}),
        **workflow.plan.get("uploadInputs", {}),
    }
    resources = filter_accessible(
        DataResource.objects.filter(project_tag_id=workflow.project_tag_id),
        workflow.owner,
    )
    names = dict(
        resources.filter(pk__in=list(sources.values())).values_list("id", "name")
    )
    return {
        **workflow.plan.get("inputNames", {}),
        **{
            role: names[identity]
            for role, identity in sources.items()
            if identity in names
        },
    }
