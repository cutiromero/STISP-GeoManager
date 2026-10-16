"""Research quotas are configurable independently of physical/safety guards."""

import json
import threading
from http.server import ThreadingHTTPServer

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from apps.agent.budgets import budget_options
from apps.agent.management.commands.mock_agent_model import MockHandler
from apps.agent.models import AgentPolicy
from apps.agent.policy import daily_quota, default_policy, validate_policy
from apps.agent.selections import normalize
from apps.agent.worker import run_task
from apps.catalog.models import DataResource
from apps.projects.context import project_scope
from tests.integration.test_agent import new_run, setup_agent  # noqa: F401


def test_research_settings_no_longer_have_fixed_upper_tiers(setup_agent):  # noqa: F811
    policy = default_policy()
    policy.update(
        dailyRuns=5000,
        maxSteps=256,
        maxResources=100,
        maxIterations=100,
        maxOperatorSteps=256,
        maxProtocolRetries=5,
        maxRunSeconds=14400,
        maxAttachments=40,
        maxContextBytes=2000000,
        maxContextTokens=524288,
        maxOutputTokens=65536,
    )
    policy["budgetLimits"]["superadmin"].update(
        contextWindowTokens=524288, maxOutputTokens=262144, maxRunSeconds=14400
    )
    assert validate_policy(policy) == policy


@pytest.mark.parametrize("field", ["dailyRuns", "maxSteps", "maxResources"])
def test_zero_can_remove_quantity_quotas(setup_agent, field):  # noqa: F811
    policy = default_policy()
    policy[field] = 0
    assert validate_policy(policy)[field] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"maxAttachmentBytes": 200000001},
        {"temperature": 2.1},
        {"maxRunSeconds": 0},
        {"maxIterations": 0},
    ],
)
def test_resource_safety_and_positive_runtime_remain(setup_agent, change):  # noqa: F811
    with pytest.raises(ValidationError):
        validate_policy({**default_policy(), **change})


def test_zero_quota_does_not_override_explicit_user_limit(setup_agent):  # noqa: F811
    env = setup_agent
    policy = default_policy()
    policy["dailyRuns"] = 0
    policy["quotas"] = [{"kind": "user", "id": env["user"].id, "dailyRuns": 0}]
    assert daily_quota(env["user"], validate_policy(policy)) == 0
    policy["quotas"][0]["dailyRuns"] = 7
    assert daily_quota(env["user"], policy) == 7
    policy["dailyRuns"] = 3
    assert daily_quota(env["user"], policy) == 3


def test_prompt_length_tracks_global_budgets_when_task_budgets_are_disabled(
    setup_agent,  # noqa: F811
):
    policy = default_policy()
    policy.update(maxContextBytes=800000, maxContextTokens=65536)
    options = budget_options(setup_agent["user"], policy)
    assert options["enabled"] is False
    assert options["maxPromptCharacters"] == 200000
    policy["maxContextTokens"] = 20000
    assert budget_options(setup_agent["user"], policy)["maxPromptCharacters"] == 80000


def test_admin_can_save_unlimited_research_quantities(setup_agent):  # noqa: F811
    env = setup_agent
    client = Client()
    client.force_login(env["admin"])
    current = client.get("/api/agent/admin/", **env["header"]).json()
    policy = {**current["policy"], "dailyRuns": 0, "maxSteps": 0, "maxResources": 0}
    response = client.put(
        "/api/agent/admin/",
        json.dumps({"policy": policy, "revision": current["revision"]}),
        content_type="application/json",
        **env["header"],
    )
    assert response.status_code == 200, response.content
    assert response.json()["policy"]["maxResources"] == 0
    submitted = env["client"].post(
        f"/api/agent/conversations/{env['conversation'].id}/runs/",
        json.dumps(
            {"model": "mock", "prompt": "检查资料", "idempotencyKey": "no-quota-run"}
        ),
        content_type="application/json",
        **env["header"],
    )
    assert submitted.status_code == 202, submitted.content


def test_manual_selection_can_exceed_three_items(setup_agent):  # noqa: F811
    env = setup_agent
    policy = {**default_policy(), "maxResources": 0}
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": policy})
    selected = []
    with project_scope(env["scope"]):
        for index in range(4):
            selected.append(
                DataResource.objects.create(
                    name=f"材料{index}",
                    code=f"manual-resource-{index}",
                    data_type="table",
                    storage_path="samples",
                ).id
            )
    response = env["client"].post(
        f"/api/agent/conversations/{env['conversation'].id}/runs/",
        json.dumps(
            {
                "model": "mock",
                "prompt": "比较这些资料",
                "resourceIds": selected,
                "idempotencyKey": "manual-four-inputs",
            }
        ),
        content_type="application/json",
        **env["header"],
    )
    assert response.status_code == 202, response.content
    assert normalize(
        {"algorithmSelectionMode": "manual", "algorithmVersionIds": [1, 2, 3, 4]}, []
    )["algorithm_version_ids"] == [1, 2, 3, 4]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("thinking_mode", ["fast", "deep"])
def test_zero_step_limit_still_runs_real_tool_loop(
    setup_agent,  # noqa: F811
    settings,
    thinking_mode,
):
    env = setup_agent
    policy = {**default_policy(), "maxSteps": 0, "maxResources": 0}
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": policy})
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings.AGENT_MODELS = [
        {
            **settings.AGENT_MODELS[0],
            "qwen": True,
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
        }
    ]
    try:
        with project_scope(env["scope"]):
            run = new_run(env, thinking_mode=thinking_mode)
        run_task(run.id)
        run.refresh_from_db()
        assert run.status == "succeeded", run.detail
        assert run.events.filter(kind="tool_completed").count() == 3
        assert run.evidence and run.answer
        assert run.events.filter(kind="thinking").exists() is (thinking_mode == "deep")
        assert "模拟思考片段" not in run.answer
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
