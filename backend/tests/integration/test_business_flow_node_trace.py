"""Actual node records stay separate from snapshots and obey live source access."""

import json

import pytest

from apps.agent import provider
from apps.agent.business_flow_execution import execute_node
from apps.agent.models import AgentWorkflowStep
from apps.business_flows.runtime import serialize_run
from apps.business_flows.state import state
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent
from tests.integration.test_business_flow_runtime import flows, start

__all__ = ["setup_agent", "flows"]
pytestmark = [pytest.mark.django_db, pytest.mark.efficiency]


@pytest.fixture
def trace_env(flows, settings, monkeypatch):
    settings.AGENT_MODELS[0]["qwen"] = True
    _, version = flows["create"]()
    workflow, _ = start(flows, version, reasoningEffort="xhigh")
    node = version.definition["nodes"][0]
    workflow.status, workflow.current_step = "running", node["id"]
    workflow.save(update_fields=["status", "current_step"])
    monkeypatch.setattr(provider, "model_window", lambda *args: 32768)
    monkeypatch.setattr(provider, "count_tokens", lambda *args, **kwargs: 123)
    raw = json.dumps(
        {
            "summary": "actual_reply_marker；secret='trace-private-value'",
            "evidenceIds": ["actual"],
        },
        ensure_ascii=False,
    )

    def stream(model, messages, maximum, guard, **options):
        guard()
        options["on_thinking"]("对实际数量进行核验。")
        yield raw

    monkeypatch.setattr(provider, "stream", stream)
    return {**flows, "workflow": workflow, "node": node, "version": version}


def run_model(env):
    with project_scope(env["scope"]):
        return execute_node(
            env["workflow"],
            env["node"],
            1,
            [
                {
                    "id": "actual",
                    "kind": "analysis",
                    "title": "真实数量",
                    "result": {"count": 8},
                }
            ],
            guard=lambda: None,
        )


def url(env, node_id=None, offset=0):
    return f"/api/business-flows/runs/{env['workflow'].pk}/nodes/{node_id or env['node']['id']}/trace/?offset={offset}"


def test_actual_thinking_body_and_strength_are_node_scoped_and_not_in_snapshot(
    trace_env,
):
    env = trace_env
    result = run_model(env)
    assert result["findings"] == result["limitations"] == []
    response = env["client"].get(url(env), **env["header"])
    assert response.status_code == 200
    data = response.json()
    assert data["historical"] is False and data["nodeId"] == env["node"]["id"]
    actual = data["requests"][0]
    assert actual["role"] == "executor"
    assert actual["thinkingEnabled"] is True and actual["reasoningEffort"] == "xhigh"
    assert actual["thinkingText"] == "对实际数量进行核验。"
    assert "actual_reply_marker" in actual["response"]["content"]
    assert "trace-private-value" not in response.content.decode()
    with project_scope(env["scope"]):
        item = state(env["workflow"])["nodes"][env["node"]["id"]]
        item["executor"]["audit"] = {"responsePreview": "bulk_private_marker"}
        item["attempts"] = [{"responsePreview": "bulk_private_marker"}]
        public = serialize_run(env["user"], env["workflow"])
    assert "modelResponse" not in json.dumps(public)
    assert "bulk_private_marker" not in json.dumps(public)
    assert item["executor"]["audit"]["responsePreview"] == "bulk_private_marker"


def test_trace_read_does_not_execute_or_reset_model_budget(trace_env):
    env = trace_env
    run_model(env)
    env["workflow"].refresh_from_db()
    before = (
        env["workflow"].status,
        env["workflow"].current_step,
        env["workflow"].max_iterations,
        env["workflow"].parameters,
        env["workflow"].plan,
    )
    steps = env["workflow"].steps.count()
    assert env["client"].get(url(env), **env["header"]).status_code == 200
    env["workflow"].refresh_from_db()
    assert before == (
        env["workflow"].status,
        env["workflow"].current_step,
        env["workflow"].max_iterations,
        env["workflow"].parameters,
        env["workflow"].plan,
    )
    assert env["workflow"].steps.count() == steps


def test_pagination_does_not_mix_another_nodes_model_text(trace_env):
    env = trace_env
    workflow = env["workflow"]
    sequence = workflow.steps.count()
    records = []
    for index in range(9):
        records.append(
            AgentWorkflowStep(
                workflow=workflow,
                sequence=sequence + index + 1,
                kind="model_activity",
                status="succeeded",
                action={
                    "nodeId": env["node"]["id"]
                    if index < 8
                    else env["version"].definition["nodes"][1]["id"],
                    "actor": "executor",
                },
                output_refs={
                    "modelActivity": {"status": "complete", "attempt": index + 1},
                    "modelResponse": {
                        "content": f"body-{index}",
                        "truncated": False,
                        "sizeBytes": 6,
                    },
                },
            )
        )
    AgentWorkflowStep.objects.bulk_create(records)
    first = env["client"].get(url(env), **env["header"]).json()
    second = (
        env["client"].get(url(env, offset=first["nextOffset"]), **env["header"]).json()
    )
    assert len(first["requests"]) == 5 and len(second["requests"]) == 3
    assert not (
        {row["id"] for row in first["requests"]}
        & {row["id"] for row in second["requests"]}
    )
    assert "body-8" not in json.dumps([first, second])


def test_source_revocation_removes_access_to_saved_model_text(trace_env):
    env = trace_env
    run_model(env)
    env["resource"].owner_only = True
    env["resource"].maintainer = env["other"]
    env["resource"].save(update_fields=["owner_only", "maintainer", "updated_at"])
    response = env["client"].get(url(env), **env["header"])
    assert response.status_code == 403
    assert "actual_reply_marker" not in response.content.decode()


def test_other_account_cannot_read_node_records(trace_env):
    env = trace_env
    run_model(env)
    env["client"].force_login(env["other"])
    response = env["client"].get(url(env), **env["header"])
    assert response.status_code in {403, 404}
    assert "actual_reply_marker" not in response.content.decode()


def test_historical_state_is_identified_without_inventing_a_raw_reply(trace_env):
    env = trace_env
    with project_scope(env["scope"]):
        item = state(env["workflow"])["nodes"][env["node"]["id"]]
        item["executor"].update(
            status="succeeded", thinking="历史实际思考", summary="已保存结果"
        )
        env["workflow"].save(update_fields=["plan"])
    data = env["client"].get(url(env), **env["header"]).json()
    assert data["historical"] is True
    assert data["requests"][0]["thinkingText"] == "历史实际思考"
    assert data["requests"][0]["response"] is None
    assert data["requests"][0]["structuredResult"]["summary"] == "已保存结果"
