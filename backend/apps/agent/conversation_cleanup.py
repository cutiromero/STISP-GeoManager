"""Delete only a conversation's proven computation outputs, preserving reuse."""

import hashlib
import json
import logging
from pathlib import Path
from uuid import uuid4

from django.core import signing
from django.db import transaction
from django.db.models import F, Q

from apps.catalog.models import DataResource, ShareInvitation
from apps.catalog.resource_history_delete import history_snapshot
from apps.catalog.resource_management import delete_resource
from apps.catalog.resource_references import (
    COMPUTE_TERMINAL,
    _contains_reference,
    historical_references,
    resource_reference_reasons,
)
from apps.catalog.resource_storage_delete import _safe_file
from apps.compute.models import ComputeImport, ComputeInput, ComputeOutput, ComputeTask
from apps.core.permissions import has_feature_perm
from apps.core.storage import app_path
from apps.projects.context import selected_project_id
from .models import AgentComputeFollowup, AgentRun, AgentWorkflow, AgentWorkflowStep

TOKEN_SALT = "agent.conversation-generated-data-deletion.v1"
TOKEN_MAX_AGE = 600
MAX_TASKS = 200
logger = logging.getLogger(__name__)


def resource_is_exclusive(resource, request, scope):
    if (
        not resource.is_compute_result
        or resource.maintainer_id != request.user.pk
        or resource.project_tag_id != selected_project_id()
        or not has_feature_perm(request.user, "catalog.delete_dataresource")
    ):
        return False
    # A catalog ID alone does not prove that this conversation created it.
    origin = (
        ComputeImport.objects.filter(
            resource=resource,
            output__task_id__in=scope["taskIds"],
            output__task__owner=request.user,
        )
        .select_related("output__task")
        .first()
    )
    if origin is None or not _task_is_exclusive(origin.output.task, scope):
        return False
    if (
        ComputeInput.objects.filter(resource=resource)
        .exclude(task_id__in=scope["taskIds"])
        .exists()
    ):
        return False
    if (
        ComputeImport.objects.filter(resource=resource)
        .exclude(output__task_id__in=scope["taskIds"])
        .exists()
    ):
        return False
    if resource_reference_reasons(resource, allow_history=True):
        return False
    _, _, workflows = historical_references(resource)
    if any(row["id"] not in scope["workflowIds"] for row in workflows):
        return False
    layer_ids = set(resource.map_layers.values_list("id", flat=True))
    raster_ids = set(resource.raster_datasets.values_list("id", flat=True))
    for run in (
        AgentRun.objects.filter(project_tag_id=resource.project_tag_id)
        .exclude(conversation_id=scope["conversationId"])
        .values(
            "resource_ids",
            "evidence",
            "compute_intent",
            "research_intent",
            "execution_state",
        )
    ):
        if resource.id in run["resource_ids"] or _contains_reference(
            [
                run["evidence"],
                run["compute_intent"],
                run["research_intent"],
                run["execution_state"],
            ],
            resource.pk,
            layer_ids,
            raster_ids,
        ):
            return False
    return True


def _task_is_exclusive(task, scope):
    if ShareInvitation.objects.filter(
        kind=ShareInvitation.Kind.COMPUTE_OUTPUT,
        object_id__in=task.outputs.values("id"),
        status__in=(ShareInvitation.Status.PENDING, ShareInvitation.Status.ACCEPTED),
    ).exists():
        return False
    if (
        AgentWorkflowStep.objects.filter(compute_task_id=task.pk)
        .exclude(workflow_id__in=scope["workflowIds"])
        .exists()
    ):
        return False
    if (
        AgentComputeFollowup.objects.filter(task=task)
        .exclude(run__conversation_id=scope["conversationId"])
        .exists()
    ):
        return False
    return (
        not AgentRun.objects.filter(research_workflow_id__in=scope["workflowIds"])
        .exclude(conversation_id=scope["conversationId"])
        .exists()
    )


def cleanup_plan(conversation, request):
    workflows = AgentWorkflow.objects.filter(
        chat_runs__conversation=conversation,
        owner=request.user,
        project_tag_id=selected_project_id(),
    ).distinct()
    workflow_ids = list(workflows.values_list("id", flat=True))
    task_ids = set(
        AgentWorkflowStep.objects.filter(workflow_id__in=workflow_ids)
        .exclude(compute_task_id=None)
        .values_list("compute_task_id", flat=True)
    )
    task_ids.update(
        AgentComputeFollowup.objects.filter(run__conversation=conversation).values_list(
            "task_id", flat=True
        )
    )
    if len(task_ids) > MAX_TASKS:
        raise ValueError("会话计算数量过多，请在数据管理中分批清理")
    scope = {
        "conversationId": conversation.pk,
        "workflowIds": sorted(str(x) for x in workflow_ids),
        "taskIds": [],
    }
    tasks = list(
        ComputeTask.objects.filter(
            pk__in=task_ids,
            owner=request.user,
            project_tag_id=selected_project_id(),
            status__in=COMPUTE_TERMINAL,
        )
    )
    scope["taskIds"] = sorted(str(t.pk) for t in tasks)
    all_task_ids = list(scope["taskIds"])
    tasks = [t for t in tasks if _task_is_exclusive(t, scope)]
    scope["taskIds"] = sorted(str(t.pk) for t in tasks)
    resources = list(
        DataResource.objects.filter(
            pk__in=ComputeImport.objects.filter(
                output__task_id__in=all_task_ids
            ).values("resource_id"),
            is_compute_result=True,
            maintainer=request.user,
        ).distinct()
    )
    allowed, retained = [], []
    for resource in resources:
        (
            allowed if resource_is_exclusive(resource, request, scope) else retained
        ).append(resource)
    retained_output_ids = (
        ComputeImport.objects.filter(output__task_id__in=scope["taskIds"])
        .filter(
            Q(status__in=("queued", "running"))
            | (Q(resource__isnull=False) & ~Q(resource_id__in=[r.pk for r in allowed]))
        )
        .values("output_id")
    )
    outputs = list(
        ComputeOutput.objects.filter(
            task_id__in=scope["taskIds"],
            expired=False,
        )
        .exclude(pk__in=retained_output_ids)
        .order_by("id")
    )
    value = {
        "scope": scope,
        "resources": [
            {"id": r.pk, "updatedAt": r.updated_at.isoformat()} for r in allowed
        ],
        "outputs": [{"id": o.pk, "sha256": o.checksum} for o in outputs],
        "conversationUpdatedAt": conversation.updated_at.isoformat(),
    }
    digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return {
        **value,
        "digest": digest,
        "resourceCount": len(allowed),
        "outputCount": len(outputs),
        "retainedCount": len(retained),
        "estimatedBytes": sum(r.size_bytes for r in allowed)
        + sum(o.size_bytes for o in outputs),
    }


def public_preview(conversation, request):
    plan = cleanup_plan(conversation, request)
    token = signing.dumps(
        {
            "actor": request.user.pk,
            "project": selected_project_id(),
            "conversation": conversation.pk,
            "digest": plan["digest"],
        },
        salt=TOKEN_SALT,
        compress=True,
    )
    return {
        "conversationId": conversation.pk,
        **{
            k: plan[k]
            for k in ("resourceCount", "outputCount", "retainedCount", "estimatedBytes")
        },
        "confirmationToken": token,
    }


def confirmed_plan(conversation, request, token):
    try:
        signed = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
    except signing.BadSignature as exc:
        raise ValueError("删除范围确认已失效，请重新打开删除窗口") from exc
    plan = cleanup_plan(conversation, request)
    if signed != {
        "actor": request.user.pk,
        "project": selected_project_id(),
        "conversation": conversation.pk,
        "digest": plan["digest"],
    }:
        raise ValueError("会话或数据引用已变化，请重新检查删除范围")
    return plan


def _expire_output(output_id, checksum, request, scope):
    staged = None
    try:
        with transaction.atomic(durable=True):
            ComputeTask.objects.filter(outputs__pk=output_id).update(stage=F("stage"))
            output = ComputeOutput.objects.select_related("task").get(pk=output_id)
            task = output.task
            if (
                str(task.pk) not in scope["taskIds"]
                or task.owner_id != request.user.pk
                or task.project_tag_id != selected_project_id()
                or task.status not in COMPUTE_TERMINAL
                or not _task_is_exclusive(task, scope)
                or output.expired
                or output.checksum != checksum
                or ComputeImport.objects.filter(output=output)
                .filter(Q(resource__isnull=False) | Q(status__in=("queued", "running")))
                .exists()
                or ComputeOutput._base_manager.filter(path=output.path)
                .exclude(pk=output.pk)
                .exists()
            ):
                return False
            prefix = (
                Path("projects")
                / str(task.project_tag_id)
                / "compute"
                / "outputs"
                / str(task.pk)
            )
            if not Path(output.path).is_relative_to(prefix):
                return False
            path = _safe_file(app_path(), output.path)
            if path.exists():
                staged = path.with_name("." + path.name + ".delete-" + uuid4().hex)
                path.replace(staged)
            output.expired = True
            output.save(update_fields=["expired"])
        if staged:
            staged.unlink(missing_ok=True)
        return True
    except Exception:
        if staged and staged.exists():
            staged.replace(path)
        raise


def cleanup_generated_data(plan, request):
    result = {
        "deletedResources": 0,
        "deletedOutputs": 0,
        "retainedResources": plan["retainedCount"],
        "retainedOutputs": 0,
        "failedItems": 0,
    }
    scope = plan["scope"]
    for row in plan["resources"]:
        try:
            resource = DataResource.objects.filter(pk=row["id"]).first()
            if resource is None:
                continue
            if resource.updated_at.isoformat() != row["updatedAt"]:
                result["retainedResources"] += 1
                continue
            snapshot, _ = history_snapshot(resource)
            deletion = delete_resource(
                request,
                resource.pk,
                confirmed_snapshot=snapshot,
                deletion_guard=lambda r: (
                    r.updated_at.isoformat() == row["updatedAt"]
                    and resource_is_exclusive(r, request, scope)
                ),
            )
            if deletion["status"] == "deleted":
                result["deletedResources"] += 1
            elif deletion["status"] == "failed":
                result["failedItems"] += 1
            else:
                result["retainedResources"] += 1
        except Exception:
            logger.exception(
                "Conversation result cleanup failed for resource %s", row["id"]
            )
            result["failedItems"] += 1
    for row in plan["outputs"]:
        try:
            if _expire_output(row["id"], row["sha256"], request, scope):
                result["deletedOutputs"] += 1
            else:
                result["retainedOutputs"] += 1
        except Exception:
            logger.exception(
                "Conversation output cleanup failed for output %s", row["id"]
            )
            result["failedItems"] += 1
    return result
