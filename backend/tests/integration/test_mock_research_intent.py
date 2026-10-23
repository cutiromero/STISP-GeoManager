"""Mock Demo routing chooses authorized files, never supplies scientific answers."""

import json
from types import SimpleNamespace

import pytest

from apps.agent.management.commands.mock_agent_model import mock_answer
from apps.agent.research_parser import validate
from apps.agent.geology_multi import _binding_integer


def request(*, scenario="geology_multi_element_reasoning", ambiguous=False):
    candidates = [{"id": 11, "name": "当前地质图"}]
    if ambiguous:
        candidates.append({"id": 12, "name": "另一张地质图"})
    scene = {
        "scenario": "geology_multi_element_reasoning",
        "title": "海德乌拉地质综合推理",
        "inputs": {"lithology": candidates, "rules": [{"id": 21, "name": "试用规则"}]},
        "preferredInputs": {} if ambiguous else {"lithology": 11, "rules": 21},
        "defaults": {"segment": "all", "working_epsg": 32649, "undeclared": "ignored"},
        "parameterSpecs": [
            {
                "key": "segment",
                "label": "演示入口",
                "type": "enum",
                "choices": ["all", "lithology"],
            },
            {"key": "working_epsg", "label": "工作坐标系", "type": "integer", "min": 1},
        ],
        "roleLabels": {"lithology": "岩性图"},
    }
    payload = {
        "userMessage": "使用演示资料检查地图，修改前等待我批准",
        "demoScenario": scenario,
        "authorizedCatalog": {"scenarios": [scene]},
        "responseContract": {"inputsType": "object"},
    }
    body = {"messages": [{"role": "user", "content": json.dumps(payload)}]}
    return payload, body


def test_mock_routes_explicit_demo_from_authorized_candidates():
    payload, body = request()
    answer = json.loads(mock_answer(body))
    validated = validate(
        answer,
        payload["authorizedCatalog"],
        SimpleNamespace(prompt=payload["userMessage"]),
    )
    assert validated["action"] == "start"
    assert validated["inputs"] == {"lithology": 11, "rules": 21}
    assert validated["parameters"] == {"segment": "all", "working_epsg": 32649}
    assert "模拟" in validated["message"]
    assert "edits" not in validated and "findings" not in validated


@pytest.mark.parametrize("scenario", [None, "not-authorized"])
def test_mock_does_not_fake_free_text_understanding_or_unauthorized_scene(scenario):
    _, body = request(scenario=scenario)
    assert json.loads(mock_answer(body)) == {"action": "ordinary"}


def test_ambiguous_candidates_require_selection_and_survive_retry_feedback():
    payload, body = request(ambiguous=True)
    body["messages"].append({"role": "user", "content": '{"validationError":"retry"}'})
    answer = json.loads(mock_answer(body))
    validated = validate(
        answer,
        payload["authorizedCatalog"],
        SimpleNamespace(prompt=payload["userMessage"]),
    )
    assert validated["action"] == "clarify"
    assert validated["inputs"] == {"rules": 21}
    assert validated["questions"][0]["key"] == "lithology"
    assert {item["value"] for item in validated["questions"][0]["options"]} == {
        "11",
        "12",
    }


@pytest.mark.parametrize("value", [True, 1.1, "1.1", 0, -1, float("inf"), "1e3"])
def test_rule_binding_never_truncates_fractional_or_invalid_ids(value):
    with pytest.raises((ValueError, OverflowError)):
        _binding_integer(value)
