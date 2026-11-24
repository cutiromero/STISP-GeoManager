"""原生工具SSE与JSON动作采用相同的单动作校验。"""

import json
from unittest.mock import MagicMock

import pytest

from apps.agent import provider
from apps.agent.business_flow_actions import (
    validate_action,
    ActionFormatError,
    NATIVE_TOOLS,
    action_tools,
    validate_contract_action,
)
from apps.agent.config import ModelConfig

MODEL = ModelConfig(
    "test", "桩模型", "http://127.0.0.1:19100/v1", "mock", native_tools=True
)
ACTION = {"action": "operator_catalog", "arguments": {"operation": "statistics"}}


def connection(monkeypatch, chunks):
    response = MagicMock(status=200)
    response.readline.side_effect = [
        *(("data: " + json.dumps(chunk) + "\n").encode() for chunk in chunks),
        b"data: [DONE]\n",
    ]
    client = MagicMock()
    client.getresponse.return_value = response
    monkeypatch.setattr(
        provider.http.client, "HTTPConnection", lambda *args, **kwargs: client
    )
    return client


def test_native_tool_stream_joins_argument_fragments_and_sends_one_tool(monkeypatch):
    raw = json.dumps(ACTION)
    client = connection(
        monkeypatch,
        [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {
                                        "name": "node_action",
                                        "arguments": raw[:20],
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": raw[20:]}}
                            ]
                        }
                    }
                ]
            },
        ],
    )
    result = "".join(
        provider.stream(
            MODEL,
            [{"role": "user", "content": "测试"}],
            100,
            lambda: None,
            tools=NATIVE_TOOLS,
        )
    )
    assert validate_action(result, set()) == ACTION
    body = json.loads(client.request.call_args.kwargs["body"])
    assert (
        body["tools"] == NATIVE_TOOLS
        and body["parallel_tool_calls"] is False
        and body["tool_choice"] == "required"
    )


def test_native_token_measurement_includes_tool_schema(monkeypatch):
    captured = []
    monkeypatch.setattr(
        provider,
        "model_request",
        lambda model, path, body: captured.append(body) or {"count": 99},
    )
    assert provider.count_tokens(MODEL, [], tools=NATIVE_TOOLS) == 99
    assert captured[0]["tools"] == NATIVE_TOOLS


@pytest.mark.parametrize(
    "delta",
    [
        {"content": "我认为应该调用工具"},
        {
            "tool_calls": [
                {"index": 1, "function": {"name": "node_action", "arguments": "{}"}}
            ]
        },
        {
            "tool_calls": [
                {"index": 0, "function": {"name": "approve", "arguments": "{}"}}
            ]
        },
    ],
)
def test_native_rejects_text_parallel_or_unknown_function(monkeypatch, delta):
    connection(monkeypatch, [{"choices": [{"delta": delta}]}])
    with pytest.raises(provider.ModelError):
        list(provider.stream(MODEL, [], 100, lambda: None, tools=NATIVE_TOOLS))


@pytest.mark.parametrize(
    "value",
    [
        "broken",
        "[]",
        '{"action":"shell","arguments":{}}',
        '{"action":"ask_user","arguments":{"approved":true}}',
    ],
)
def test_json_protocol_never_admits_extra_commands(value):
    with pytest.raises(ActionFormatError):
        validate_action(value, set())


def test_json_protocol_accepts_exactly_one_action():
    assert validate_action(json.dumps(ACTION), set()) == ACTION


@pytest.mark.parametrize(
    "raw",
    [
        {"name": "node_action", "arguments": ACTION},
        {"name": "node_action", "arguments": json.dumps(ACTION)},
        {"name": ACTION["action"], "arguments": ACTION["arguments"]},
        {**ACTION, "arguments": json.dumps(ACTION["arguments"])},
    ],
)
def test_exact_native_wrappers_do_not_change_the_action(raw):
    assert (
        validate_contract_action(json.dumps(raw), set(), [ACTION["action"]]) == ACTION
    )


@pytest.mark.parametrize(
    "raw",
    [
        '{"action":"ask_user","action":"operator_catalog","arguments":{}}',
        '{"action":"operator_catalog","arguments":{"limit":NaN}}',
        '{"name":"node_action","arguments":{"action":"ask_user","arguments":{"approved":true}}}',
        '{"name":"start_node","arguments":{"nodeId":"other"}}',
        '[{"action":"operator_catalog","arguments":{}}]',
    ],
)
def test_normalization_never_selects_ambiguous_or_nonlocal_actions(raw):
    with pytest.raises(ActionFormatError):
        validate_contract_action(raw, set(), ["operator_catalog"])


def test_native_schema_only_offers_current_phase_actions():
    native = action_tools(["start_node", "ask_user"])
    assert native[0]["function"]["parameters"]["properties"]["action"]["enum"] == [
        "start_node",
        "ask_user",
    ]
    assert (
        "run_operator"
        in NATIVE_TOOLS[0]["function"]["parameters"]["properties"]["action"]["enum"]
    )


@pytest.mark.parametrize("name", ["preflight_operator", "run_operator"])
def test_unique_mapping_next_to_arguments_is_normalized_for_operator_validation(name):
    mapping = {"lithology": {"class_name": "name"}}
    args = {"versionId": 32, "inputs": {"lithology": 40}, "parameters": {}}
    result = validate_contract_action(
        json.dumps({"action": name, "arguments": args, "fieldMappings": mapping}),
        set(),
        [name],
    )
    assert result == {"action": name, "arguments": {**args, "fieldMappings": mapping}}


@pytest.mark.parametrize(
    "action,args,mapping",
    [
        ("preflight_operator", {"fieldMappings": {}}, {}),
        ("preflight_operator", {}, []),
        ("ask_user", {"question": "待确认"}, {}),
    ],
)
def test_ambiguous_or_other_top_level_mappings_are_rejected(action, args, mapping):
    with pytest.raises(ActionFormatError):
        validate_contract_action(
            json.dumps({"action": action, "arguments": args, "fieldMappings": mapping}),
            set(),
            [action],
        )


@pytest.mark.parametrize("native", [False, True])
def test_catalog_query_uses_the_same_keyword_in_native_and_json_actions(native):
    arguments = {"query": "冰川 分类 提取 面积", "limit": 4}
    action = {"action": "operator_catalog", "arguments": arguments}
    payload = (
        {"name": "node_action", "arguments": json.dumps(action)} if native else action
    )
    assert validate_contract_action(
        json.dumps(payload), set(), ["operator_catalog"]
    ) == {
        "action": "operator_catalog",
        "arguments": {"keyword": "冰川 分类 提取 面积", "limit": 4},
    }


@pytest.mark.parametrize(
    "action,arguments",
    [
        ("operator_catalog", {"query": "冰川", "keyword": "积雪"}),
        ("operator_catalog", {"query": ["冰川"]}),
        ("operator_catalog", {"query": "冰川", "approved": True}),
        ("preflight_operator", {"query": "冰川"}),
    ],
)
def test_catalog_query_never_resolves_conflicts_or_allows_other_tool_fields(
    action, arguments
):
    with pytest.raises(ActionFormatError):
        validate_contract_action(
            json.dumps({"action": action, "arguments": arguments}), set(), [action]
        )
