"""Read agent progress once per response, without storing authorization or state."""

import json

from django.db.models import Max, Q, Subquery
from django.utils import timezone

from .answer_preview import (
    MAX_PREVIEW_CHARACTERS,
    PREVIEW_EVENT_KIND,
    PREVIEW_DELTA_KIND,
    preview_delta_filter,
)
from .models import ACTIVE, RunEvent


def load_run_activity(runs):
    """Batch history and progress with one event query and one response lifetime.

    Read complete thinking/usage, but only the latest parameter and preview
    snapshots. Old cumulative previews can be large and must stay in storage.
    Callers still authorize every run before exposing the response.
    """
    runs = list(runs)
    if not runs:
        return {}
    identities = [run.pk for run in runs]
    preview_ids = [run.pk for run in runs if run.status != "succeeded"]
    latest = (
        RunEvent.objects.filter(run_id__in=identities)
        .filter(
            Q(kind="parameters") | Q(kind=PREVIEW_EVENT_KIND, run_id__in=preview_ids)
        )
        .order_by()
        .values("run_id", "kind")
        .annotate(latest_id=Max("id"))
        .values("latest_id")
    )
    events = (
        RunEvent.objects.filter(run_id__in=identities)
        .filter(
            Q(kind__in=("thinking", "usage"))
            | Q(pk__in=Subquery(latest))
            | preview_delta_filter(preview_ids)
        )
        .order_by("id")
        .values_list("run_id", "kind", "text", "created_at")
    )
    result = {
        identity: {
            "generationParameters": {},
            "answerPreview": "",
            "thinkingText": "",
            "thinkingDurationMs": 0,
        }
        for identity in identities
    }
    thinking = {identity: [] for identity in identities}
    previews = {identity: [] for identity in identities}
    started, usages = {}, {}
    for identity, kind, text, created_at in events.iterator():
        activity = result[identity]
        if kind == "thinking":
            thinking[identity].append(text)
            started[identity] = min(started.get(identity, created_at), created_at)
        elif kind == "parameters":
            activity["generationParameters"] = json.loads(text)
        elif kind == PREVIEW_EVENT_KIND:
            previews[identity] = [text]
        elif kind == PREVIEW_DELTA_KIND:
            previews[identity].append(text)
        elif kind == "usage":
            usage = json.loads(text)
            totals = usages.setdefault(
                identity, {"modelCalls": 0, "generatedTokens": 0}
            )
            totals["modelCalls"] += 1
            totals["lastGeneratedTokens"] = usage.get("completion_tokens", 0)
            totals["generatedTokens"] += totals["lastGeneratedTokens"]
    observed_at = timezone.now()
    for run in runs:
        activity = result[run.pk]
        activity["generationParameters"].update(usages.get(run.pk, {}))
        activity["thinkingText"] = "".join(thinking[run.pk])
        activity["answerPreview"] = "".join(previews[run.pk])[:MAX_PREVIEW_CHARACTERS]
        if run.pk in started:
            end = observed_at if run.status in ACTIVE else run.updated_at
            activity["thinkingDurationMs"] = max(
                0, int((end - started[run.pk]).total_seconds() * 1000)
            )
    workflow_ids = {
        run.research_workflow_id for run in runs if run.research_workflow_id
    }
    if workflow_ids:
        from .models import AgentWorkflowStep
        from .model_activity import ACTIVITY_KIND
        from .workflow_model_events import PARAMETER_KEY, SEQUENCE_KEY

        latest_steps = (
            AgentWorkflowStep.objects.filter(
                workflow_id__in=workflow_ids, kind=ACTIVITY_KIND
            )
            .order_by()
            .values("workflow_id")
            .annotate(latest_id=Max("id"))
            .values("latest_id")
        )
        snapshots = {
            step.workflow_id: step
            for step in AgentWorkflowStep.objects.filter(
                pk__in=Subquery(latest_steps)
            ).only("id", "workflow_id", "status", "output_refs")
        }
        for run in runs:
            step = snapshots.get(run.research_workflow_id)
            if not step:
                continue
            snapshot = step.output_refs.get("modelActivity")
            if not isinstance(snapshot, dict):
                continue
            snapshot = dict(snapshot)
            if step.status == "failed":
                snapshot["status"] = "failed"
            result[run.pk]["generationParameters"].update(
                {PARAMETER_KEY: snapshot, SEQUENCE_KEY: step.pk}
            )
    return result
