"""Publish bounded model activity deltas through the existing parent-run stream."""

import json

from django.db import transaction
from django.utils import timezone

from .models import AgentRun, RunEvent

# Configuration: the activity record owns the bounded snapshot; events carry deltas.
EVENT_KIND = "workflow_model_activity"
PARAMETER_KEY = "workflowModelActivity"
SEQUENCE_KEY = "workflowModelActivitySequence"


def publish_activity(workflow, sequence, activity, delta, *, reset):
    bind = workflow.parameters.get("_businessFlow") or {}
    if not bind.get("runId"):
        return
    with transaction.atomic():
        matched = AgentRun._base_manager.filter(
            pk=bind["runId"],
            research_workflow_id=workflow.pk,
            owner_id=workflow.owner_id,
            project_tag_id=workflow.project_tag_id,
        ).update(updated_at=timezone.now())
        if matched:
            RunEvent.objects.create(
                run_id=bind["runId"],
                kind=EVENT_KIND,
                text=json.dumps(
                    {
                        "workflowId": str(workflow.pk),
                        "sequence": sequence,
                        "activity": {
                            key: value
                            for key, value in activity.items()
                            if key != "thinkingText"
                        },
                        "thinkingDelta": delta,
                        "reset": reset,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
