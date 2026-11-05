"""Real model progress stays bounded, authorized and separate from large plans."""

import json
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.agent import generic_mapping, model_activity, provider
from apps.agent.config import registry
from apps.agent.demo_decisions import decide
from apps.agent.model_activity import WorkflowModelActivity, latest_model_activity
from apps.agent.models import AgentWorkflowStep
from apps.agent.policy import default_policy
from apps.agent.views import workflow_json
from apps.agent.workflow_controls import WorkflowPaused
from apps.agent.workflow_history import summary_list
from apps.agent.workflow_projection import project_workflow
from apps.compute.packages import ComputeError
from tests.integration.test_demo_decision_retry import ordinary_stage, retry_model  # noqa: F401
from tests.integration.test_demo_edit_context import model_response

pytestmark = pytest.mark.django_db
pytest_plugins = ["tests.integration.test_workflow_profile_models"]


def activity_for(env, guard=lambda: None):
    return WorkflowModelActivity(
        env["workflow"],
        "检查地质资料",
        registry()["qwen"],
        {**env["policy"], "_thinking": True},
        guard,
    )


def test_progress_throttles_small_records_without_rewriting_plan(profiles, monkeypatch):
    workflow = profiles["workflow"]
    workflow.plan["largeScientificResults"] = "科学结果" * 10000
    workflow.save(update_fields=["plan"])
    original_plan = dict(workflow.plan)
    clock = [0.0]
    monkeypatch.setattr(model_activity.time, "monotonic", lambda: clock[0])
    activity = activity_for(profiles)
    with CaptureQueriesContext(connection) as queries:
        activity.progress({"status": "requesting", "attempt": 1})
        for _ in range(100):
            activity.thinking("实际思考")
        for index in range(100):
            activity.progress({"status": "responding", "outputChars": index + 1})
        activity.progress({"status": "validating", "outputChars": 100})
        activity.progress({"status": "complete"})
    updates = [query["sql"] for query in queries if query["sql"].startswith("UPDATE")]
    assert len(updates) == 4
    assert all(AgentWorkflowStep._meta.db_table in sql for sql in updates)
    assert workflow.steps.filter(kind="model_activity").count() == 1
    workflow.refresh_from_db()
    assert workflow.plan == original_plan
    saved = latest_model_activity(workflow)
    assert saved["thinkingText"] == "实际思考" * 100
    assert saved["thinkingChars"] == 400 and saved["outputChars"] == 100
    assert saved["status"] == "complete"
    assert len(json.dumps(saved, ensure_ascii=False)) < 2000


def test_thinking_tail_survives_refresh_and_validation_recovery(profiles):
    text = "早" * 12500 + "最新真实思考"
    activity = activity_for(profiles)
    activity.progress({"status": "requesting", "attempt": 1})
    activity.thinking(text)
    activity.progress({"status": "responding", "outputChars": 872})
    resumed = activity_for(profiles)
    resumed.progress({"status": "validating", "attempt": 1})
    saved = latest_model_activity(profiles["workflow"])
    assert saved["thinkingText"] == text[-12000:]
    assert saved["thinkingChars"] == len(text) and saved["truncated"]
    assert saved["outputChars"] == 872
    assert saved["status"] == "validating"
    resumed.progress({"status": "complete"})
    assert profiles["workflow"].steps.filter(kind="model_activity").count() == 1
    assert latest_model_activity(profiles["workflow"])["status"] == "complete"


@pytest.mark.parametrize(
    "error", [PermissionDenied("撤权"), provider.ModelError("取消"), WorkflowPaused()]
)
def test_stopping_marks_existing_activity_failed_without_new_text(profiles, error):
    active = [True]

    def guard():
        if not active[0]:
            raise error

    activity = activity_for(profiles, guard)
    activity.progress({"status": "requesting", "attempt": 1})
    activity.thinking("撤权前可见内容")
    active[0] = False
    with pytest.raises(type(error)):
        activity.thinking("停止后不可新增内容")
    activity.fail()
    saved = latest_model_activity(profiles["workflow"])
    assert saved["status"] == "failed"
    assert saved["thinkingText"] == "撤权前可见内容"
    assert "停止后" not in json.dumps(saved, ensure_ascii=False)


def test_card_full_and_inspection_keep_bounded_model_activity(profiles):
    activity = activity_for(profiles)
    activity.progress({"status": "requesting", "attempt": 1})
    activity.thinking("真实模型思考")
    workflow = profiles["workflow"]
    full = workflow_json(workflow)
    card = workflow_json(workflow, view="card")
    inspection = project_workflow(workflow, dict(card), "inspection", "steps", 0, 50)
    assert full["modelActivity"] == card["modelActivity"] == inspection["modelActivity"]
    assert full["modelActivity"]["thinkingText"] == "真实模型思考"
    assert card["steps"] == []
    assert "uploadInputs" not in card["plan"]
    assert "plan" not in card["modelActivity"]
    history = summary_list(profiles["owner"], {})
    assert len(history["items"]) == 1
    assert "modelActivity" not in history["items"][0]


def test_mapping_reports_real_thinking_and_only_output_character_counts(
    profiles, monkeypatch
):
    thinking, statuses = [], []
    body = json.dumps(
        {"roles": {"lithology": {"name": {"field": "DCMC", "reason": "八宝山组"}}}}
    )

    def stream(model, messages, maximum, guard, **options):
        assert latest_model_activity(profiles["workflow"])["status"] == "requesting"
        options["on_thinking"]("读取八宝山组示例")
        yield body[:20]
        yield body[20:]

    monkeypatch.setattr(provider, "stream", stream)
    original_validate = generic_mapping._validate

    def validate(raw, roles):
        assert latest_model_activity(profiles["workflow"])["status"] == "validating"
        return original_validate(raw, roles)

    monkeypatch.setattr(generic_mapping, "_validate", validate)
    result = generic_mapping.model_targets(
        profiles["workflow"],
        profiles["policy"],
        profiles["roles"],
        on_thinking=thinking.append,
        on_progress=lambda update: statuses.append(update["status"]),
    )
    saved = latest_model_activity(profiles["workflow"])
    assert result["lithology"]["name"]["field"] == "DCMC"
    assert thinking == ["读取八宝山组示例"]
    assert statuses == [
        "requesting",
        "responding",
        "responding",
        "validating",
        "complete",
    ]
    assert saved["thinkingText"] == thinking[0]
    assert saved["outputChars"] == len(body) and saved["status"] == "complete"
    assert body not in json.dumps(saved)


def test_mapping_invalid_results_retry_without_false_completion(profiles, monkeypatch):
    calls = []

    def stream(model, messages, maximum, guard, **options):
        calls.append(1)
        options["on_thinking"]("当前实际尝试" + str(len(calls)))
        yield "invalid-json"

    monkeypatch.setattr(provider, "stream", stream)
    with pytest.raises(ComputeError, match="有效JSON"):
        generic_mapping.model_targets(
            profiles["workflow"], profiles["policy"], profiles["roles"]
        )
    records = profiles["workflow"].steps.filter(kind="model_activity")
    assert len(calls) == 2 and records.count() == 2
    assert all(item.status == "failed" for item in records)
    saved = latest_model_activity(profiles["workflow"])
    assert saved["status"] == "failed" and saved["attempt"] == 2
    assert saved["thinkingText"] == "当前实际尝试2"


def test_mapping_stream_failure_preserves_received_thinking_as_failed(
    profiles, monkeypatch
):
    def stream(model, messages, maximum, guard, **options):
        options["on_thinking"]("网络失败前的真实片段")
        options["on_thinking"]("，包括节流等待保存的尾部")
        raise provider.ModelError("连接中断")
        yield ""

    monkeypatch.setattr(provider, "stream", stream)
    with pytest.raises(ComputeError, match="连接中断"):
        generic_mapping.model_targets(
            profiles["workflow"], profiles["policy"], profiles["roles"]
        )
    saved = latest_model_activity(profiles["workflow"])
    assert saved["status"] == "failed"
    assert saved["thinkingText"] == "网络失败前的真实片段，包括节流等待保存的尾部"
    assert saved["outputChars"] == 0


def test_decision_becomes_complete_only_after_evidence_validation(retry_model):  # noqa: F811
    workflow, stage, results = ordinary_stage()
    correct = model_response("ecology-priority", [])
    invalid = model_response("ecology-priority", [])
    invalid["decision"]["evidenceRefs"] = [{"kind": "output", "id": "999"}]
    answers = iter([json.dumps(invalid), json.dumps(correct)])
    statuses, thinking = [], []

    def stream(model, messages, maximum, guard, **options):
        options["on_thinking"]("校验当前证据")
        body = next(answers)
        yield body[:25]
        yield body[25:]

    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=800),
        patch("apps.agent.demo_decisions.provider.stream", side_effect=stream),
    ):
        decide(
            workflow,
            None,
            default_policy(),
            stage,
            results,
            lambda: None,
            on_thinking=thinking.append,
            on_progress=lambda update: statuses.append(update),
        )
    assert [item["status"] for item in statuses] == [
        "requesting",
        "responding",
        "responding",
        "validating",
        "failed",
        "requesting",
        "responding",
        "responding",
        "validating",
        "complete",
    ]
    assert [item["attempt"] for item in statuses if item["status"] == "requesting"] == [
        1,
        2,
    ]
    assert thinking == ["校验当前证据", "校验当前证据"]
    assert "thinkingText" not in json.dumps(statuses)


def test_mock_decision_does_not_invent_model_progress(settings):
    settings.AGENT_MODELS = [
        {
            "alias": "online-fixture",
            "name": "模拟",
            "model_id": "mock-decision",
            "base_url": "http://127.0.0.1:19100/v1",
            "agent": True,
        }
    ]
    workflow, stage, results = ordinary_stage()
    workflow.workflow_type = "ecology_investigation"
    updates = []
    with patch("apps.agent.demo_decisions.resource_context", return_value=[]):
        decide(
            workflow,
            None,
            default_policy(),
            stage,
            results,
            lambda: None,
            on_progress=updates.append,
        )
    assert updates == []
