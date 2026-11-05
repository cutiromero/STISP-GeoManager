from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd

import pytest

from apps.agent import result_colors


def classes(style):
    return {item["value"]: item for item in style["renderer"]["classes"]}


def test_multiple_alterations_have_conventional_colors_and_named_legends():
    style, _ = result_colors.category_style(
        "alt", ["赤铁矿化", "绿泥石化", "碳酸盐化", "水云母化"]
    )
    palette = classes(style)
    assert len({item["color"] for item in palette.values()}) == 4
    assert palette["赤铁矿化"]["color"] == "#c84545"
    assert palette["绿泥石化"]["label"] == "绿泥石化"
    assert style["renderer"]["field"] == "alt"


def test_unknown_classes_are_complete_and_deterministic():
    style, replaced = result_colors.category_style("alt", ["新矿物A", "新矿物B"])
    assert style == result_colors.category_style("alt", ["新矿物B", "新矿物A"])[0]
    assert set(replaced) == {"新矿物A", "新矿物B"}
    used = []
    for item in classes(style).values():
        assert result_colors.valid_color(item["color"], used)
        used.append(item["color"])


@pytest.mark.parametrize(
    "color", ["red", "#fff", "#ffffff", "url(javascript:bad)", "#gg3322"]
)
def test_invalid_or_low_contrast_model_colors_are_replaced(color):
    proposal = {
        "field": "alt",
        "classes": [{"value": "未知", "color": color, "label": "未知矿物"}],
    }
    style, replaced = result_colors.category_style("alt", ["未知", "遗漏"], proposal)
    assert set(replaced) == {"未知", "遗漏"}
    assert result_colors.valid_color(classes(style)["未知"]["color"], [])


def test_duplicate_model_colors_are_replaced():
    proposal = {
        "field": "grade",
        "classes": [{"value": name, "color": "#b32233"} for name in ["新A", "新B"]],
    }
    style, replaced = result_colors.category_style("grade", ["新A", "新B"], proposal)
    assert replaced == ["新B"]
    assert len({item["color"] for item in classes(style).values()}) == 2


@pytest.mark.parametrize("model_id", ["mock-local", "MOCK-offline"])
def test_mock_color_model_never_calls_model_services(monkeypatch, model_id):
    monkeypatch.setattr(
        result_colors,
        "registry",
        lambda: {"selected": SimpleNamespace(agent=True, model_id=model_id)},
    )
    request = Mock(side_effect=AssertionError("不得调用模型服务"))
    monkeypatch.setattr(result_colors.provider, "model_request", request)
    monkeypatch.setattr(result_colors.provider, "stream", request)
    assert (
        result_colors.model_colors(SimpleNamespace(model="selected"), "alt", ["未知"])
        is None
    )
    request.assert_not_called()


@pytest.mark.parametrize(
    "enabled,status", [(False, "online"), (True, "offline"), (True, "unknown")]
)
def test_disabled_or_offline_selected_model_does_not_call_service(
    monkeypatch, enabled, status
):
    monkeypatch.setattr(
        result_colors,
        "registry",
        lambda: {"selected": SimpleNamespace(agent=True, model_id="real")},
    )
    monkeypatch.setattr(
        result_colors, "policy", lambda: {"enabled": enabled, "agentEnabled": enabled}
    )
    monkeypatch.setattr(
        result_colors,
        "visible_models",
        lambda *args: [{"alias": "selected", "status": status}],
    )
    request = Mock(side_effect=AssertionError("不得调用模型服务"))
    monkeypatch.setattr(result_colors.provider, "model_request", request)
    monkeypatch.setattr(result_colors.provider, "stream", request)
    assert (
        result_colors.model_colors(
            SimpleNamespace(model="selected", owner=None), "alt", ["未知"]
        )
        is None
    )
    request.assert_not_called()


def test_model_disabled_does_not_make_network_call(settings, monkeypatch):
    settings.AGENT_COLOR_SUGGESTIONS_ENABLED = False
    monkeypatch.setattr(
        result_colors,
        "registry",
        lambda: {"model": SimpleNamespace(agent=True, model_id="real")},
    )
    monkeypatch.setattr(
        result_colors.provider,
        "stream",
        lambda *args, **kwargs: pytest.fail("模型关闭时不应调用"),
    )
    assert (
        result_colors.model_colors(SimpleNamespace(model="model"), "alt", ["新矿物"])
        is None
    )


def test_registration_survives_model_failure_and_audits_persisted_style(monkeypatch):
    resource = SimpleNamespace(
        id=123, data_type="vector", default_visualization={}, save=Mock()
    )
    workflow = SimpleNamespace(id="workflow", owner="owner", model="offline")
    monkeypatch.setattr(
        result_colors,
        "read_resource",
        lambda resource: pd.DataFrame({"alt": ["新A", "新B"]}),
    )
    monkeypatch.setattr(
        result_colors,
        "model_colors",
        Mock(side_effect=result_colors.provider.ModelError("offline")),
    )
    audit = Mock()
    monkeypatch.setattr(result_colors, "log_operation", audit)
    result_colors.style_result(workflow, resource, "final_alterations")
    assert (
        len(resource.default_visualization["symbolization"]["renderer"]["classes"]) == 2
    )
    assert (
        resource.default_visualization["colorAdvice"]["failure"]
        == "model_unavailable_or_invalid"
    )
    resource.save.assert_called_once()
    audit.assert_called_once()
    result_colors.style_result(workflow, resource, "final_alterations")
    resource.save.assert_called_once()


@pytest.mark.parametrize("input_tokens", [100, 8100])
def test_color_model_uses_actual_window_token_count_and_shared_deadline(
    monkeypatch, input_tokens
):
    from apps.agent import workflow

    model = SimpleNamespace(agent=True, model_id="color-model", qwen=True)
    monkeypatch.setattr(result_colors, "registry", lambda: {"model": model})
    monkeypatch.setattr(workflow, "authorize_workflow_history", lambda value: None)
    monkeypatch.setattr(
        result_colors,
        "policy",
        lambda: {
            "enabled": True,
            "agentEnabled": True,
            "maxOutputTokens": 1024,
            "maxContextBytes": 10000,
            "maxContextTokens": 8192,
        },
    )
    monkeypatch.setattr(
        result_colors,
        "visible_models",
        lambda *args: [{"alias": "model", "status": "online"}],
    )
    calls = []

    def request(model, path, body, *, timeout):
        calls.append((path, body, timeout))
        return (
            {"data": [{"id": "color-model", "max_model_len": 8192}]}
            if path == "/v1/models"
            else {"count": input_tokens}
        )

    monkeypatch.setattr(result_colors.provider, "model_request", request)
    stream = Mock(return_value=iter(['{"field":"alt","classes":[]}']))
    monkeypatch.setattr(result_colors.provider, "stream", stream)
    if input_tokens == 8100:
        with pytest.raises(result_colors.provider.ModelError):
            result_colors.model_colors(
                SimpleNamespace(model="model", owner=None), "alt", ["未知"]
            )
        stream.assert_not_called()
    else:
        proposal = result_colors.model_colors(
            SimpleNamespace(model="model", owner=None), "alt", ["未知"]
        )
        assert proposal["requestBudget"]["inputTokens"] == 100
        stream.assert_called_once()
    assert all(0 < timeout <= 8 for _, _, timeout in calls)
    assert calls[-1][1]["chat_template_kwargs"]["enable_thinking"] is False
