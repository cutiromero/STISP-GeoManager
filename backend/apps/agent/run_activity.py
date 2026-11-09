"""Read agent progress once per response, without storing authorization or state."""

import json

from django.db.models import Max, Q, Subquery
from django.utils import timezone

from .answer_preview import MAX_PREVIEW_CHARACTERS, PREVIEW_EVENT_KIND
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
        .filter(Q(kind__in=("thinking", "usage")) | Q(pk__in=Subquery(latest)))
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
    started, usages = {}, {}
    for identity, kind, text, created_at in events.iterator():
        activity = result[identity]
        if kind == "thinking":
            thinking[identity].append(text)
            started[identity] = min(started.get(identity, created_at), created_at)
        elif kind == "parameters":
            activity["generationParameters"] = json.loads(text)
        elif kind == PREVIEW_EVENT_KIND:
            activity["answerPreview"] = text[:MAX_PREVIEW_CHARACTERS]
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
        if run.pk in started:
            end = observed_at if run.status in ACTIVE else run.updated_at
            activity["thinkingDurationMs"] = max(
                0, int((end - started[run.pk]).total_seconds() * 1000)
            )
    return result
