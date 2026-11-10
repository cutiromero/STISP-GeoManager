"""Actual saved thinking reaches the existing parent stream before completion."""

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from apps.agent.config import registry
from apps.agent.model_activity import WorkflowModelActivity
from apps.agent.models import RunEvent
from apps.agent.policy import default_policy
from apps.agent.run_activity import load_run_activity
from apps.agent.workflow_model_events import EVENT_KIND
from apps.business_flows.state import parent_run
from apps.projects.context import project_scope
from tests.integration.test_business_flow_legacy import legacy_flow  # noqa: F401
from tests.integration.test_agent import setup_agent  # noqa: F401

# ruff: noqa: F811


@pytest.mark.efficiency
def test_partial_model_activity_streams_real_deltas_and_snapshot_without_rewriting_plan(
    legacy_flow, monkeypatch
):
    env = legacy_flow
    workflow = env["create"]()
    original = deepcopy(workflow.plan)
    clock = [0.0]
    monkeypatch.setattr("apps.agent.model_activity.time.monotonic", lambda: clock[0])
    activity = WorkflowModelActivity(
        workflow,
        "综合分析",
        registry()["mock"],
        {**default_policy(), "_thinking": True},
        Mock(),
    )
    with project_scope(env["scope"]):
        activity.progress({"status": "requesting", "attempt": 1})
        activity.thinking("第一段")
        events = list(
            RunEvent.objects.filter(run=parent_run(workflow), kind=EVENT_KIND).order_by(
                "id"
            )
        )
        assert json.loads(events[-1].text)["thinkingDelta"] == "第一段"
        for _ in range(100):
            clock[0] += 0.001
            activity.thinking("续")
        clock[0] += 0.7
        activity.thinking("末")
        run = parent_run(workflow)
        snapshot = load_run_activity([run])[run.pk]["generationParameters"][
            "workflowModelActivity"
        ]
        assert snapshot["status"] == "thinking"
        assert snapshot["thinkingText"] == "第一段" + "续" * 100 + "末"
        deltas = [
            json.loads(event.text)
            for event in RunEvent.objects.filter(run=run, kind=EVENT_KIND).order_by(
                "id"
            )
        ]
        assert len(deltas) == 3
        assert "thinkingText" not in deltas[-1]["activity"]
        assert (
            "".join(value["thinkingDelta"] for value in deltas)
            == snapshot["thinkingText"]
        )
        activity.progress({"status": "complete", "outputChars": 15})
        workflow.refresh_from_db()
        assert workflow.plan == original


def test_new_model_request_resets_thinking_and_wrong_parent_receives_nothing(
    legacy_flow,
):
    env = legacy_flow
    workflow = env["create"]()
    activity = WorkflowModelActivity(
        workflow,
        "分析",
        registry()["mock"],
        {**default_policy(), "_thinking": True},
        Mock(),
    )
    with project_scope(env["scope"]):
        activity.progress({"status": "requesting", "attempt": 1})
        activity.thinking("旧请求")
        activity.progress({"status": "complete"})
        activity.progress({"status": "requesting", "attempt": 2})
        latest = json.loads(
            RunEvent.objects.filter(run=parent_run(workflow), kind=EVENT_KIND)
            .latest("id")
            .text
        )
        assert latest["reset"] is True and latest["thinkingDelta"] == ""
        workflow.parameters["_businessFlow"]["runId"] += 1000
        before = RunEvent.objects.filter(kind=EVENT_KIND).count()
        activity.thinking("不得发给其他运行")
        assert RunEvent.objects.filter(kind=EVENT_KIND).count() == before
