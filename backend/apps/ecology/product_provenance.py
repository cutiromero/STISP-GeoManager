"""Batch product origins without reading scientific files or private conversations."""

from apps.agent.models import AgentWorkflowStep
from apps.compute.models import ComputeImport


def attach_provenance(items, user, project, computed_ids):
    records = list(
        ComputeImport.objects.filter(
            resource_id__in=[
                row["resourceId"] for row in items if row["resourceId"] in computed_ids
            ],
            status="ready",
            output__task__status="succeeded",
            output__task__trial=False,
            output__task__project_tag_id=project.pk,
        ).select_related("output__task__owner")
    )
    imports = {record.resource_id: record for record in records}
    workflows = {}
    for row in (
        AgentWorkflowStep.objects.filter(
            compute_task_id__in=[record.output.task_id for record in records],
            workflow__project_tag_id=project.pk,
            workflow__workflow_type="business_flow",
        )
        .values("compute_task_id", "workflow_id", "workflow__owner_id")
        .order_by("pk")
    ):
        workflows[str(row["compute_task_id"])] = row
    for item in items:
        record = imports.get(item["resourceId"])
        if record is None:
            item["provenance"] = {
                "type": "uploaded_standard"
                if item.get("referenceRole") == "standard"
                else "uploaded_result",
                "batchId": None,
                "taskId": None,
                "workflowId": None,
                "createdAt": item["registeredAt"],
                "creator": "",
                "owned": False,
            }
            continue
        task = record.output.task
        workflow = workflows.get(str(task.pk))
        owned = task.owner_id == user.pk
        item["provenance"] = {
            "type": "system_interpretation",
            "batchId": str(workflow["workflow_id"]) if workflow else str(task.pk),
            "taskId": str(task.pk),
            "workflowId": str(workflow["workflow_id"]) if workflow and owned else None,
            "createdAt": task.created_at.isoformat(),
            "creator": task.owner.get_full_name() or task.owner.get_username(),
            "owned": owned,
        }
