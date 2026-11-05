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
    if (
        result.source != sources[purpose] + str(workflow.pk)
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
    from apps.compute.models import ComputeImport

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
    inputs = _workflow_input_ids(workflow)
    if (
        history
        and identity in inputs
        and (not workflow.resource_ids or identity in workflow.resource_ids)
    ):
        # Saved input metadata remains readable under the current ACL even if
        # its discovery status changed. This branch never authorizes execution.
        return resource
    if identity in inputs:
        try:
            business_resource = resolve_discoverable_resource(user, policy, identity)
        except PermissionDenied:
            business_resource = None
        if business_resource is not None:
            if workflow.resource_ids and identity not in workflow.resource_ids:
                if bound_output.exists():
                    return resource
                raise PermissionDenied("业务资料不在本次科研任务已选择的数据范围")
            return business_resource
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
    if bound_output.exists():
        return resource
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
