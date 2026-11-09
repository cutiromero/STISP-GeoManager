"""Parameter revision planning cannot choose tools, inputs or human outcomes."""

from copy import deepcopy
import json

import pytest

from apps.agent import business_flow_operator_repair as repair
from apps.agent import provider
from apps.compute.packages import ComputeError
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401
from tests.integration.test_business_flow_review import env, EVIDENCE, NODE, REJECT  # noqa: F401

# ruff: noqa: F811
MANIFEST = {
    "parameters": [
        {
            "key": "threshold",
            "label": "阈值",
            "type": "number",
            "required": True,
            "default": 0.5,
            "min": 0,
            "max": 1,
        }
    ]
}
PROPOSAL = {
    "canRepair": True,
    "parameters": {"threshold": 0.6},
    "reason": "针对实际结果提高已声明阈值",
    "evidenceIds": ["result-1"],
}


def run(env, manifest=MANIFEST, current=None, **kwargs):
    node = deepcopy(NODE)
    node.update(kind="operator", algorithmVersionId=19)
    with project_scope(env["scope"]):
        return repair.propose_parameters(
            env["workflow"],
            kwargs.pop("node", node),
            kwargs.pop("attempt", 2),
            kwargs.pop("evidence", deepcopy(EVIDENCE)),
            manifest,
            current if current is not None else {"threshold": 0.5},
            kwargs.pop("feedback", deepcopy(REJECT)),
            guard=kwargs.pop("guard", lambda: None),
            **kwargs,
        )


def stream(monkeypatch, value=PROPOSAL):
    calls = []

    def generate(model, messages, maximum, guard, **kwargs):
        calls.append(
            {"messages": deepcopy(messages), "maximum": maximum, "options": kwargs}
        )
        guard()
        kwargs["on_usage"](
            {"prompt_tokens": 123, "completion_tokens": 32, "total_tokens": 155}
        )
        yield (
            json.dumps(value, ensure_ascii=False)
            if not isinstance(value, str)
            else value
        )

    monkeypatch.setattr(provider, "stream", generate)
    return calls


def test_plans_one_actual_change_with_frozen_binding_and_no_tools(env, monkeypatch):
    calls = stream(monkeypatch)
    records = []
    result = run(env, on_record=records.append)
    assert result["canRepair"] and result["parameters"] == {"threshold": 0.6}
    assert len(calls) == 1 and "tools" not in calls[0]["options"]
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert payload["nodeContext"]["currentParameters"] == {"threshold": 0.5}
    assert payload["nodeContext"]["parameterManifest"] == MANIFEST["parameters"]
    assert payload["nodeContext"]["algorithmBindingFrozen"] is True
    assert payload["nodeContext"]["inputsFrozen"] is True
    assert (
        payload["revisionFeedback"]["repairInstructions"]
        == REJECT["repairInstructions"]
    )
    assert result["audit"]["purpose"] == "operator_parameter_repair"
    assert (
        result["audit"]["parameterBeforeSha256"]
        != result["audit"]["parameterAfterSha256"]
    )
    assert all(row["purpose"] == "operator_parameter_repair" for row in records)


@pytest.mark.efficiency
def test_no_registered_parameters_returns_inability_without_model_call(
    env, monkeypatch
):
    calls = stream(monkeypatch)
    records = []
    result = run(env, manifest={"parameters": []}, current={}, on_record=records.append)
    assert not result["canRepair"] and result["parameters"] == {}
    assert result["audit"]["requested"] is False and not calls
    assert records[-1]["status"] == "not_applicable"


@pytest.mark.parametrize(
    "value",
    [
        {**PROPOSAL, "algorithmVersionId": 25},
        {**PROPOSAL, "inputs": {"source": 99}},
        {**PROPOSAL, "humanApproved": True},
        {**PROPOSAL, "parameters": {"resource_id": 2}},
        {**PROPOSAL, "parameters": {"threshold": 0.5}},
        {**PROPOSAL, "parameters": {"threshold": True}},
        {**PROPOSAL, "parameters": {"threshold": 2}},
        {**PROPOSAL, "parameters": {"threshold": "0.6"}},
        {**PROPOSAL, "parameters": {"threshold": {"execute": "python"}}},
        {**PROPOSAL, "parameters": {"threshold": float("nan")}},
        {**PROPOSAL, "evidenceIds": ["invented"]},
        "not json",
    ],
)
def test_boundary_same_value_type_range_and_reference_errors_fail_once(
    env, monkeypatch, value
):
    calls = stream(monkeypatch, value)
    with pytest.raises(ComputeError):
        run(env)
    assert len(calls) == 1


def test_adding_an_unchanged_default_is_not_a_repair(env, monkeypatch):
    calls = stream(monkeypatch, {**PROPOSAL, "parameters": {"threshold": 0.5}})
    with pytest.raises(ComputeError, match="没有实际有效变化"):
        run(env, current={})
    assert len(calls) == 1


def test_equivalent_integer_float_value_is_not_a_repair(env, monkeypatch):
    manifest = {"parameters": [{**MANIFEST["parameters"][0], "max": 10}]}
    calls = stream(monkeypatch, {**PROPOSAL, "parameters": {"threshold": 1}})
    with pytest.raises(ComputeError, match="没有实际有效变化"):
        run(env, manifest=manifest, current={"threshold": 1.0})
    assert len(calls) == 1


def test_hidden_conditional_parameter_cannot_fake_a_change(env, monkeypatch):
    manifest = {
        "parameters": [
            {
                "key": "mode",
                "label": "模式",
                "type": "enum",
                "required": True,
                "default": "simple",
                "choices": ["simple", "extended"],
            },
            {
                "key": "threshold",
                "label": "阈值",
                "type": "number",
                "required": False,
                "default": 0.5,
                "when": {"key": "mode", "equals": "extended"},
            },
        ]
    }
    calls = stream(monkeypatch, {**PROPOSAL, "parameters": {"threshold": 0.9}})
    with pytest.raises(ComputeError, match="没有实际有效变化"):
        run(env, manifest=manifest, current={"mode": "simple"})
    assert len(calls) == 1


def test_cannot_repair_answer_retains_current_parameters(env, monkeypatch):
    calls = stream(
        monkeypatch,
        {
            **PROPOSAL,
            "canRepair": False,
            "parameters": {},
            "reason": "当前问题超出已声明参数边界",
        },
    )
    result = run(env)
    assert not result["canRepair"] and result["parameters"] == {"threshold": 0.5}
    assert len(calls) == 1


def test_partial_proposal_keeps_unmodified_parameters(env, monkeypatch):
    manifest = {
        "parameters": [
            *MANIFEST["parameters"],
            {
                "key": "preserve",
                "label": "保留",
                "type": "boolean",
                "required": True,
                "default": True,
            },
        ]
    }
    stream(monkeypatch)
    result = run(env, manifest=manifest, current={"threshold": 0.5, "preserve": True})
    assert result["parameters"] == {"threshold": 0.6, "preserve": True}


def test_repair_limit_and_source_guard_prevent_new_model_requests(env, monkeypatch):
    from django.core.exceptions import PermissionDenied

    calls = stream(monkeypatch)
    with pytest.raises(ComputeError):
        run(env, attempt=3)

    def deny():
        raise PermissionDenied("原资料已撤权")

    with pytest.raises(PermissionDenied):
        run(env, guard=deny)
    assert not calls
