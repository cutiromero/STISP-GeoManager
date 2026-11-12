"""目录启动、父运行、计量与生成必须使用同一思考选择。"""

import json

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.agent import provider
from apps.agent.business_flow_model import request_node_result
from apps.agent.business_flow_review import review_node
from apps.agent.workflow_model_policy import workflow_model_policy
from apps.business_flows.state import parent_run
from apps.projects.context import project_scope
from tests.integration.test_business_flow_runtime import flows, start
from tests.integration.test_agent import setup_agent

# ruff: noqa: F811
__all__ = ["flows", "setup_agent"]

pytestmark = [pytest.mark.django_db, pytest.mark.efficiency]
CAPS = {
    "maxOutputTokens": 4096,
    "maxContextTokens": 32768,
    "maxContextBytes": 192 * 1024,
    "maxRunSeconds": 180,
}


@pytest.mark.parametrize("effort", [None, "low", "medium", "xhigh"])
@pytest.mark.parametrize("actor", ["executor", "reviewer"])
def test_launch_setting_reaches_tokenizer_transport_and_audit(
    flows, settings, monkeypatch, effort, actor
):
    settings.AGENT_MODELS[0]["qwen"] = True
    _, version = flows["create"](ai=True, human=True)
    workflow, _ = start(
        flows, version, **({"reasoningEffort": effort} if effort else {})
    )
    workflow.status = "running"
    workflow.save(update_fields=["status"])
    expected = effort or "medium"
    measured, sent = [], []
    monkeypatch.setattr(provider, "model_window", lambda model: 32768)

    def counter(model, messages, thinking, strength, **kwargs):
        measured.append((thinking, strength))
        return 1000

    def stream(model, messages, maximum, guard, **options):
        guard()
        sent.append(options)
        yield json.dumps(
            {
                "decision": "accept",
                "reason": "核对实际证据",
                "issues": [],
                "repairInstructions": "",
                "evidenceIds": ["actual"],
            }
        )

    monkeypatch.setattr(provider, "count_tokens", counter)
    monkeypatch.setattr(provider, "stream", stream)
    node = version.definition["nodes"][0]
    evidence = [
        {
            "id": "actual",
            "kind": "analysis",
            "title": "真实统计",
            "result": {"count": 8},
        }
    ]
    with project_scope(flows["scope"]):
        run = parent_run(workflow)
        assert (run.thinking_mode, run.reasoning_effort) == ("deep", expected)
        if actor == "reviewer":
            result = review_node(workflow, node, 1, evidence, guard=lambda: None)
        else:
            result = request_node_result(
                workflow,
                node,
                1,
                evidence,
                role=actor,
                instruction="核对实际统计",
                validate=lambda raw, available: json.loads(raw),
                caps=CAPS,
                guard=lambda: None,
            )
    assert measured and set(measured) == {(True, expected)}
    assert sent[0]["thinking"] is True
    assert sent[0]["reasoning_effort"] == expected
    assert (result["audit"]["thinkingEnabled"], result["audit"]["reasoningEffort"]) == (
        True,
        expected,
    )


def test_unsupported_reviewer_cannot_silently_disable_selected_thinking(
    flows, settings
):
    settings.AGENT_MODELS[0]["qwen"] = True
    settings.AGENT_MODELS.append(
        {**settings.AGENT_MODELS[0], "alias": "no-thinking", "qwen": False}
    )
    _, version = flows["create"](ai=True)
    workflow, _ = start(flows, version, reasoningEffort="xhigh")
    with project_scope(flows["scope"]), pytest.raises(PermissionDenied, match="不支持"):
        from apps.agent.policy import require_access

        workflow_model_policy(
            workflow,
            flows["user"],
            require_access(flows["user"], "agent", "no-thinking"),
            model_alias="no-thinking",
        )


@pytest.mark.parametrize("effort", ["high", 1, [], None])
def test_invalid_launch_effort_is_rejected(flows, effort):
    _, version = flows["create"]()
    with pytest.raises(ValidationError):
        start(flows, version, reasoningEffort=effort)
