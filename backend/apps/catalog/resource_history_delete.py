"""Confirm deletion of terminal provenance without deleting task histories."""

from __future__ import annotations

import hashlib
import json

from django.core import signing
from django.utils import timezone

from apps.agent.models import AgentRun, AgentWorkflow
from apps.catalog.permissions import user_can_access
from apps.catalog.resource_references import historical_references, _contains_reference
from apps.compute.models import ComputeImport, ComputeInput
from apps.projects.context import selected_project_id

TOKEN_SALT = "catalog.historical-result-deletion.v1"
TOKEN_MAX_AGE = 600


def history_snapshot(resource):
    inputs, imports, workflows = historical_references(resource)
    value = {
        "resource": {
            "id": resource.id,
            "updatedAt": resource.updated_at.isoformat(),
            "name": resource.name,
            "source": resource.source,
            "storagePath": resource.storage_path,
            "dataType": resource.data_type,
            "ownerOnly": resource.owner_only,
            "maintainerId": resource.maintainer_id,
        },
        "inputs": inputs,
        "imports": imports,
        "workflows": workflows,
    }
    raw = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest(), value


def issue_confirmation(request, ids, snapshots):
    return signing.dumps(
        {
            "actor": request.user.id,
            "project": selected_project_id(),
            "ids": ids,
            "snapshots": snapshots,
        },
        salt=TOKEN_SALT,
        compress=True,
    )


def read_confirmation(request, ids, token):
    if not token:
        return {}
    data = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
    if (
        data.get("actor") != request.user.id
        or data.get("project") != selected_project_id()
        or data.get("ids") != ids
    ):
        raise signing.BadSignature("确认不属于当前用户、项目或资源选择")
    return data["snapshots"]


def detach_history(resource, actor, state):
    """Keep named evidence, original plans, output files and audit identities."""
    receipt = {
        "formerResourceId": resource.id,
        "name": resource.name,
        "code": resource.code,
        "source": resource.source,
        "projectTagId": resource.project_tag_id,
        "deletedAt": timezone.now().isoformat(),
        "deletedBy": actor.id,
        "status": "deleted",
        "platformDeletion": True,
        "dataType": resource.data_type,
        "ownerOnly": resource.owner_only,
        "maintainerId": resource.maintainer_id,
    }
    for row in state["inputs"]:
        item = ComputeInput.objects.get(pk=row["id"], resource_id=resource.id)
        item.snapshot = {**item.snapshot, "deletedResource": receipt}
        item.resource = None
        item.save(update_fields=["snapshot", "resource"])
    for row in state["imports"]:
        item = ComputeImport.objects.get(pk=row["id"], resource_id=resource.id)
        item.resource = None
        item.status = "deleted"
        item.name = resource.name
        item.error = (
            "已由用户确认删除目录数据；保留计算记录及仍在有效期内的独立输出文件。"
        )
        item.save(update_fields=["resource", "status", "name", "error"])
    for row in state["workflows"]:
        workflow = AgentWorkflow.objects.select_related("owner").get(pk=row["id"])
        history_receipt = {
            **receipt,
            "historyReadableByOwner": user_can_access(resource, workflow.owner),
        }
        workflow.plan = {
            **workflow.plan,
            "deletedResources": [
                *workflow.plan.get("deletedResources", []),
                history_receipt,
            ],
        }
        # Archived plans/checkpoints remain exact provenance; executable lists
        # never pretend that the deleted resource is still an available input.
        workflow.resource_ids = [x for x in workflow.resource_ids if x != resource.id]
        workflow.result_resource_ids = [
            x for x in workflow.result_resource_ids if x != resource.id
        ]
        workflow.save(
            update_fields=["plan", "resource_ids", "result_resource_ids", "updated_at"]
        )
    for run in AgentRun.objects.filter(
        project_tag_id=resource.project_tag_id,
        status__in=["succeeded", "failed", "cancelled", "interrupted"],
    ).select_related("owner"):
        referenced = resource.id in run.resource_ids or _contains_reference(
            [run.evidence, run.compute_intent, run.research_intent],
            resource.id,
            set(),
            set(),
        )
        if referenced and user_can_access(resource, run.owner):
            run.execution_state = {
                **run.execution_state,
                "deletedResources": [
                    *run.execution_state.get("deletedResources", []),
                    {**receipt, "historyReadableByOwner": True},
                ],
            }
            run.save(update_fields=["execution_state"])
    return receipt
