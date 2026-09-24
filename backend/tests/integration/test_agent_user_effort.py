import json

import pytest

from apps.agent.models import AgentPolicy, AgentRun
from apps.agent.policy import default_policy
from tests.integration.test_agent import setup_agent  # noqa: F401


@pytest.mark.parametrize("mode", ["chat", "agent"])
@pytest.mark.parametrize("effort", ["low", "medium", "xhigh"])
def test_user_effort_persists_and_participates_in_idempotency(
    setup_agent, settings, mode, effort
):  # noqa: F811
    env = setup_agent
    settings.AGENT_MODELS[0]["qwen"] = True
    env["conversation"].mode = mode
    env["conversation"].save(update_fields=["mode"])
    data = {
        "model": "mock",
        "prompt": "test",
        "thinkingMode": "deep",
        "reasoningEffort": effort,
        "idempotencyKey": "user-effort-test",
    }
    url = f"/api/agent/conversations/{env['conversation'].id}/runs/"

    def submit(payload):
        return env["client"].post(
            url, json.dumps(payload), content_type="application/json", **env["header"]
        )

    result = submit(data)
    assert result.status_code == 202, result.content
    run = AgentRun._base_manager.get(pk=result.json()["id"])
    assert run.reasoning_effort == effort
    assert submit(data).json()["id"] == run.id
    assert (
        submit(
            {**data, "reasoningEffort": "low" if effort != "low" else "medium"}
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "mode,effort",
    [
        ("fast", "low"),
        ("deep", "high"),
        ("deep", ""),
        ("deep", None),
        ("deep", []),
        ("deep", 1),
    ],
)
def test_invalid_user_effort_is_rejected(setup_agent, mode, effort):  # noqa: F811
    env = setup_agent
    result = env["client"].post(
        f"/api/agent/conversations/{env['conversation'].id}/runs/",
        json.dumps(
            {
                "model": "mock",
                "prompt": "test",
                "thinkingMode": mode,
                "reasoningEffort": effort,
                "idempotencyKey": "invalid-effort",
            }
        ),
        content_type="application/json",
        **env["header"],
    )
    assert result.status_code == 400


def test_admin_thinking_switch_still_blocks_override(setup_agent, settings):  # noqa: F811
    env = setup_agent
    settings.AGENT_MODELS[0]["qwen"] = True
    policy = default_policy()
    policy.update(thinkingEnabled=False, reasoningEffort="low")
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": policy})
    bootstrap = env["client"].get("/api/agent/bootstrap/", **env["header"]).json()
    assert bootstrap["defaultReasoningEffort"] == "low"
    result = env["client"].post(
        f"/api/agent/conversations/{env['conversation'].id}/runs/",
        json.dumps(
            {
                "model": "mock",
                "prompt": "test",
                "thinkingMode": "deep",
                "reasoningEffort": "xhigh",
                "idempotencyKey": "disabled-effort",
            }
        ),
        content_type="application/json",
        **env["header"],
    )
    assert result.status_code == 403
