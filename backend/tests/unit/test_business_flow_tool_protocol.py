"""原生工具SSE与JSON动作采用相同的单动作校验。"""

import json
from unittest.mock import MagicMock

import pytest

from apps.agent import provider
from apps.agent.business_flow_actions import (
    validate_action,
    ActionFormatError,
    NATIVE_TOOLS,
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
