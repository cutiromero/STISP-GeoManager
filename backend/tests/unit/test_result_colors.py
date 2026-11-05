from types import SimpleNamespace
from unittest.mock import Mock
from contextlib import nullcontext
from io import StringIO
import json

import pandas as pd

import pytest

from apps.agent import result_colors
from apps.agent.color_library import candidates, library
from apps.agent.generic_inputs import LITHOLOGY_COLORS


def classes(style):
    return {item["value"]: item for item in style["renderer"]["classes"]}


def test_standard_lithology_model_selection_and_offline_fallback_are_identical():
    values = sorted(LITHOLOGY_COLORS)
    entries = [
        entry
        for entry in library()
        if entry["domain"] == "lithology" and entry["id"].startswith("lithology-")
    ]
    assert len(entries) == len(values) == 38
    assert {
        entry["name"]: entry["referenceColor"] for entry in entries
    } == LITHOLOGY_COLORS
    proposal = {
        "field": "name",
        "classes": [
            {"value": entry["name"], "color": entry["color"]} for entry in entries
        ],
    }
    audit, fallback_audit = [], []
    style, replaced = result_colors.category_style(
        "name", values, proposal, audit=audit
    )
    fallback, _ = result_colors.category_style("name", values, audit=fallback_audit)
    assert style == fallback
    assert not replaced
    assert {item["source"] for item in audit + fallback_audit} == {"library_selected"}
    assert all(not item["remainingIssues"] for item in audit + fallback_audit)
    assert {item["value"] for item in audit} == set(values)


def test_library_searches_aliases_codes_and_generic_fields():
    assert candidates("geo_sym", ["QHAL"])[0]["name"] == "全新世冲积物qhal"
    assert candidates("type", ["hematite"])[0]["color"] == "#c84545"
    assert candidates("grade", ["A级"])[0]["color"] == "#bb781b"
    assert len(candidates("name", ["花岗岩"])) <= 4


def test_reference_library_colors_do_not_bypass_validation():
    value = "全新世冲积物qhal"
    audit = []
    style, replaced = result_colors.category_style(
        "name",
        [value],
        {
            "field": "name",
            "classes": [{"value": value, "color": LITHOLOGY_COLORS[value]}],
        },
        audit=audit,
    )
    assert replaced == [value]
    assert audit[0]["source"] == "library_selected"
    assert "low_background_contrast" in audit[0]["replacementReasons"]
    assert not audit[0]["remainingIssues"]
    assert classes(style)[value]["color"] != LITHOLOGY_COLORS[value]


def test_known_categories_are_not_forced_to_use_library_color():
    audit = []
    style, replaced = result_colors.category_style(
        "alt",
        ["赤铁矿化"],
        {
            "field": "alt",
            "classes": [{"value": "赤铁矿化", "color": "#416fa4", "label": "赤铁矿化"}],
        },
        audit=audit,
    )
    assert not replaced
    assert classes(style)["赤铁矿化"]["color"] == "#416fa4"
    assert audit[0]["source"] == "model_suggestion"


def test_unknown_model_colors_and_library_fallback_have_correct_audit():
    audit = []
    style, _ = result_colors.category_style(
        "alt",
        ["未知", "赤铁矿化"],
        {
            "field": "alt",
            "classes": [{"value": "未知", "color": "#416fa4", "label": "未知矿物"}],
        },
        audit=audit,
    )
    sources = {item["value"]: item for item in audit}
    assert sources["未知"]["source"] == "model_suggestion"
    assert sources["赤铁矿化"]["source"] == "library_selected"
    assert sources["赤铁矿化"]["replacementReasons"] == ["missing_class"]
    assert classes(style)["未知"]["label"] == "未知矿物"


def registration(monkeypatch, values):
    resource = SimpleNamespace(
        id=123, data_type="vector", default_visualization={}, save=Mock()
    )
    workflow = SimpleNamespace(id="workflow", owner="owner", model="selected")
    monkeypatch.setattr(
        result_colors, "read_resource", lambda resource: pd.DataFrame({"alt": values})
    )
    audit = Mock()
    monkeypatch.setattr(result_colors, "log_operation", audit)
    return workflow, resource, audit


@pytest.mark.parametrize(
    "bad_color,reason",
    [
        ("#c84545", "duplicate_color"),
        ("#c84645", "low_delta_e"),
        ("#ffffff", "low_background_contrast"),
        ("red", "invalid_color"),
        ("#202938", "low_outline_contrast"),
    ],
)
@pytest.mark.parametrize("repaired", [True, False])
def test_invalid_model_colors_get_one_repair_then_deterministic_fill(
    monkeypatch, bad_color, reason, repaired
):
    workflow, resource, audit = registration(monkeypatch, ["甲", "乙"])
    bad = {
        "field": "alt",
        "classes": [
            {"value": "乙", "color": "#c84545"},
            {"value": "甲", "color": bad_color},
        ],
    }
    good = {
        "field": "alt",
        "classes": [
            {"value": "乙", "color": "#c84545"},
            {"value": "甲", "color": "#416fa4"},
        ],
    }
    model = Mock(side_effect=[bad, good if repaired else bad])
    monkeypatch.setattr(result_colors, "model_colors", model)
    result_colors.style_result(workflow, resource, "final_alterations")
    assert model.call_count == 2
    assert reason in model.call_args.kwargs["feedback"]["issues"]["甲"]
    assert (
        model.call_args_list[0].kwargs["deadline"]
        == model.call_args_list[1].kwargs["deadline"]
    )
    advice = resource.default_visualization["colorAdvice"]
    record = next(item for item in advice["classes"] if item["value"] == "甲")
    assert record["source"] == ("model_suggestion" if repaired else "system_palette")
    assert reason in record["replacementReasons"]
    assert not record["remainingIssues"]
    assert len(advice["attempts"]) == 2
    assert all(not item["remainingIssues"] for item in advice["classes"])
    audit.assert_called_once()


def test_registration_sends_all_known_categories_to_selected_model(monkeypatch):
    workflow, resource, _ = registration(monkeypatch, ["赤铁矿化", "绿泥石化"])
    proposal = {
        "field": "alt",
        "classes": [
            {"value": "赤铁矿化", "color": "#c84545"},
            {"value": "绿泥石化", "color": "#35824b"},
        ],
    }
    model = Mock(return_value=proposal)
    monkeypatch.setattr(result_colors, "model_colors", model)
    result_colors.style_result(workflow, resource, "final_alterations")
    model.assert_called_once()
    assert set(model.call_args.args[2]) == {"赤铁矿化", "绿泥石化"}
    assert {
        item["source"]
        for item in resource.default_visualization["colorAdvice"]["classes"]
    } == {"library_selected"}


def test_preview_is_read_only_and_force_recolors_existing_advice(monkeypatch):
    workflow, resource, audit = registration(monkeypatch, ["赤铁矿化"])
    model = Mock(return_value=None)
    monkeypatch.setattr(result_colors, "model_colors", model)
    preview = result_colors.style_result(
        workflow, resource, "final_alterations", force=True, persist=False
    )
    assert preview["colorAdvice"]["classes"][0]["source"] == "library_selected"
    assert resource.default_visualization == {}
    resource.save.assert_not_called()
    audit.assert_not_called()
    result_colors.style_result(workflow, resource, "final_alterations")
    result_colors.style_result(workflow, resource, "final_alterations")
    assert resource.save.call_count == 1
    result_colors.style_result(workflow, resource, "final_alterations", force=True)
    assert resource.save.call_count == 2


def test_mock_registration_uses_library_for_all_lithologies_without_network(
    monkeypatch,
):
    workflow, resource, _ = registration(monkeypatch, [])
    monkeypatch.setattr(
        result_colors,
        "read_resource",
        lambda resource: pd.DataFrame({"name": sorted(LITHOLOGY_COLORS)}),
    )
    monkeypatch.setattr(
        result_colors,
        "registry",
        lambda: {"selected": SimpleNamespace(agent=True, model_id="mock-local")},
    )
    request = Mock(side_effect=AssertionError("离线不得调用外部模型"))
    monkeypatch.setattr(result_colors.provider, "model_request", request)
    monkeypatch.setattr(result_colors.provider, "stream", request)
    result_colors.style_result(workflow, resource, "apply.lithology")
    records = resource.default_visualization["colorAdvice"]["classes"]
    assert len(records) == 38
    assert {item["source"] for item in records} == {"library_selected"}
    assert all(not item["remainingIssues"] for item in records)
    request.assert_not_called()


@pytest.fixture
def live_color_model(monkeypatch):
    from apps.agent import workflow

    model = SimpleNamespace(agent=True, model_id="real", qwen=True)
    monkeypatch.setattr(result_colors, "registry", lambda: {"selected": model})
    monkeypatch.setattr(workflow, "authorize_workflow_history", lambda workflow: None)
    limits = {
        "enabled": True,
        "agentEnabled": True,
        "maxOutputTokens": 1024,
        "maxContextBytes": 20000,
        "maxContextTokens": 1000,
    }
    monkeypatch.setattr(result_colors, "policy", lambda: limits)
    monkeypatch.setattr(
        result_colors,
        "visible_models",
        lambda *args: [{"alias": "selected", "status": "online"}],
    )
    return SimpleNamespace(id="workflow", model="selected", owner=None), limits


def test_model_request_compresses_related_candidates_without_dropping_values(
    monkeypatch, live_color_model
):
    workflow, _ = live_color_model
    value = "早三叠世中细粒二长花岗岩t1ny"
    payloads = []

    def request(model, path, body, **kwargs):
        if path == "/v1/models":
            return {"data": [{"id": "real", "max_model_len": 8192}]}
        payload = json.loads(body["messages"][1]["content"])
        payloads.append(payload)
        return {"count": 2000 if len(payload["colorCandidates"]) > 1 else 100}

    monkeypatch.setattr(result_colors.provider, "model_request", request)
    stream = Mock(return_value=iter(['{"field":"name","classes":[]}']))
    monkeypatch.setattr(result_colors.provider, "stream", stream)
    response = result_colors.model_colors(workflow, "name", [value])
    assert len(payloads) >= 2
    assert all(payload["values"] == [value] for payload in payloads)
    assert (
        len(payloads[0]["colorCandidates"]) > len(payloads[-1]["colorCandidates"]) == 1
    )
    assert response["requestBudget"]["budgetLevel"] >= 2
    assert stream.call_args.args[0].model_id == "real"


def test_repair_prompt_includes_issues_previous_colors_and_complete_categories(
    monkeypatch, live_color_model
):
    workflow, _ = live_color_model
    bodies = []

    def request(model, path, body, **kwargs):
        if path == "/v1/models":
            return {"data": [{"id": "real", "max_model_len": 8192}]}
        bodies.append(body)
        return {"count": 100}

    monkeypatch.setattr(result_colors.provider, "model_request", request)
    monkeypatch.setattr(
        result_colors.provider, "stream", Mock(return_value=iter(["{}"]))
    )
    feedback = {
        "issues": {"未知": ["duplicate_color"]},
        "previousClasses": [{"value": "未知", "color": "#c84545"}],
    }
    result_colors.model_colors(workflow, "alt", ["未知", "赤铁矿化"], feedback=feedback)
    payload = json.loads(bodies[-1]["messages"][1]["content"])
    assert payload["repair"] == feedback
    assert payload["values"] == ["未知", "赤铁矿化"]
    assert payload["colorCandidates"][0]["source"]
    assert "每一个类别" in bodies[-1]["messages"][0]["content"]


def test_malformed_json_is_repaired_once_and_keeps_the_reason(
    monkeypatch, live_color_model
):
    workflow, _ = live_color_model
    _, resource, _ = registration(monkeypatch, ["未知"])

    def request(model, path, body, **kwargs):
        return (
            {"data": [{"id": "real", "max_model_len": 8192}]}
            if path == "/v1/models"
            else {"count": 100}
        )

    monkeypatch.setattr(result_colors.provider, "model_request", request)
    stream = Mock(
        side_effect=[
            iter(["bad JSON"]),
            iter(['{"field":"alt","classes":[{"value":"未知","color":"#416fa4"}]}']),
        ]
    )
    monkeypatch.setattr(result_colors.provider, "stream", stream)
    result_colors.style_result(workflow, resource, "final_alterations")
    assert stream.call_count == 2
    advice = resource.default_visualization["colorAdvice"]
    assert advice["classes"][0]["source"] == "model_suggestion"
    assert advice["classes"][0]["replacementReasons"] == ["invalid_model_response"]
    assert advice["failure"] == ""
    assert len(advice["attempts"]) == 2


@pytest.mark.parametrize("apply", [False, True])
def test_management_command_previews_and_reapplies_current_flow(monkeypatch, apply):
    from apps.agent.management.commands import style_logic_results as command

    workflow = SimpleNamespace(
        project_tag_id=1,
        owner_id=2,
        owner="owner",
        plan={
            "stages": [
                {
                    "outputs": [
                        {"resourceId": 123, "key": "apply.lithology", "kind": "vector"}
                    ]
                }
            ]
        },
    )
    monkeypatch.setattr(
        command.AgentWorkflow.objects,
        "filter",
        Mock(return_value=SimpleNamespace(first=lambda: workflow)),
    )
    monkeypatch.setattr(command, "project_scope", lambda scope: nullcontext())
    monkeypatch.setattr(
        command, "authorize_workflow_history", lambda workflow: ("owner", {})
    )
    resource = SimpleNamespace(id=123)
    monkeypatch.setattr(command, "resolve_resource", lambda *args: resource)
    style = Mock(return_value={"symbolization": {}, "colorAdvice": {"classes": []}})
    monkeypatch.setattr(command, "style_result", style)
    output = StringIO()
    command.Command(stdout=output).handle(
        workflow="workflow", apply=apply, no_model=True
    )
    style.assert_called_once_with(
        workflow, resource, "apply.lithology", force=True, persist=apply
    )
    assert '"colorAdvice"' in output.getvalue()


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
