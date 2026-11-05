"""Bounded, resumable workflow model activity stored outside the workflow plan."""

from __future__ import annotations

import time

from django.utils import timezone

from .models import AgentWorkflowStep


# Configuration: progress saves are small and independent of the workflow plan.
SAVE_INTERVAL_SECONDS = 0.6
THINKING_TEXT_LIMIT = 12000
ACTIVITY_KIND = "model_activity"
ACTIVE_STATUSES = {"requesting", "thinking", "responding", "validating"}


class WorkflowModelActivity:
    def __init__(self, workflow, stage, model, policy, guard):
        self.workflow = workflow
        self.guard = guard
        self.identity = {
            "stage": stage,
            "thinkingEnabled": bool(policy.get("_thinking", False)),
            "reasoningEffort": policy["reasoningEffort"],
            "modelName": model.name,
        }
        self.state = None
        self.step_id = None
        self.saved_at = float("-inf")
        self.saved_status = None

    def _authorize(self):
        poll = getattr(self.guard, "poll", self.guard)
        poll()

    def _initialize(self, status, attempt):
        self.state = {
            **self.identity,
            "status": status,
            "attempt": attempt,
            "thinkingText": "",
            "thinkingChars": 0,
            "outputChars": 0,
            "truncated": False,
        }
        # A resumed response validates saved output rather than making a new call.
        if status != "requesting":
            previous = (
                self.workflow.steps.filter(
                    kind=ACTIVITY_KIND,
                    action__stage=self.identity["stage"],
                    action__attempt=attempt,
                )
                .order_by("-sequence", "-id")
                .first()
            )
            if previous:
                self.step_id = previous.id
                self.state.update(previous.output_refs.get("modelActivity", {}))
        else:
            self.step_id = None

    def progress(self, update):
        status = update["status"]
        if status not in ACTIVE_STATUSES | {"complete", "failed"}:
            raise ValueError("无效的模型进度状态")
        self.guard()
        attempt = update.get("attempt", (self.state or {}).get("attempt", 1))
        if self.state is None or status == "requesting":
            self._initialize(status, attempt)
        self.state["status"] = status
        if "outputChars" in update:
            self.state["outputChars"] = update["outputChars"]
        self._save(force=status in {"requesting", "validating", "complete", "failed"})

    def thinking(self, text):
        if not text:
            return
        self.guard()
        if self.state is None:
            self._initialize("thinking", 1)
        self.state["status"] = "thinking"
        self.state["thinkingChars"] += len(text)
        accumulated = self.state["thinkingText"] + text
        self.state["truncated"] |= len(accumulated) > THINKING_TEXT_LIMIT
        self.state["thinkingText"] = accumulated[-THINKING_TEXT_LIMIT:]
        self._save()

    def _save(self, *, force=False):
        now = time.monotonic()
        if (
            not force
            and self.state["status"] == self.saved_status
            and now - self.saved_at < SAVE_INTERVAL_SECONDS
        ):
            return
        self._authorize()
        checked_at = timezone.now()
        self.state["updatedAt"] = checked_at.isoformat()
        status = self.state["status"]
        values = {
            "status": "succeeded"
            if status == "complete"
            else "failed"
            if status == "failed"
            else "running",
            "output_refs": {"modelActivity": dict(self.state)},
            "finished_at": None if status in ACTIVE_STATUSES else checked_at,
        }
        if self.step_id is None:
            record = AgentWorkflowStep.objects.create(
                workflow=self.workflow,
                sequence=self.workflow.steps.count() + 1,
                kind=ACTIVITY_KIND,
                action={
                    "stage": self.identity["stage"],
                    "attempt": self.state["attempt"],
                },
                **values,
            )
            self.step_id = record.id
        else:
            AgentWorkflowStep.objects.filter(
                pk=self.step_id, workflow=self.workflow
            ).update(**values)
        self.saved_at, self.saved_status = now, status

    def fail(self):
        """Mark the existing activity stopped without saving unauthorized new text."""
        if self.step_id is not None:
            try:
                self.progress({"status": "failed"})
                return
            except Exception:
                # Cancellation and revocation forbid publishing buffered text,
                # but the already-visible activity must still stop spinning.
                pass
            AgentWorkflowStep.objects.filter(
                pk=self.step_id, workflow=self.workflow
            ).update(status="failed", finished_at=timezone.now())


def latest_model_activity(workflow):
    record = (
        workflow.steps.filter(kind=ACTIVITY_KIND).order_by("-sequence", "-id").first()
    )
    if record is None:
        return None
    activity = record.output_refs.get("modelActivity")
    if not isinstance(activity, dict):
        return None
    result = dict(activity)
    if record.status == "failed":
        result["status"] = "failed"
        if record.finished_at:
            result["updatedAt"] = record.finished_at.isoformat()
    return result
