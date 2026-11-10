from types import SimpleNamespace
from unittest.mock import Mock

from apps.agent import alteration_result_colors as colors


def output(identity, mineral, suffix):
    return SimpleNamespace(
        id=identity, key=f"{mineral}_{suffix}", kind="raster", metadata={}, save=Mock()
    )


def test_model_palette_is_requested_once_and_reused_by_corrected_rasters(monkeypatch):
    before = [
        output(i, mineral, "before") for i, mineral in enumerate(colors.MINERALS, 1)
    ]
    after = [
        output(i + 10, mineral, "corrected")
        for i, mineral in enumerate(colors.MINERALS, 1)
    ]
    proposal = {
        "field": "mineral",
        "classes": [
            {"value": mineral, "label": label, "color": "#416fa4"}
            for mineral, label in colors.MINERALS.items()
        ],
    }
    model = Mock(return_value=proposal)
    manager = Mock(return_value=[])
    monkeypatch.setattr(colors, "model_colors", model)
    monkeypatch.setattr(colors.ComputeOutput.objects, "filter", manager)
    audit = Mock()
    monkeypatch.setattr(colors, "log_operation", audit)
    workflow = SimpleNamespace(id="workflow", owner=object(), result_ids=[])
    first = colors.style_alteration_outputs(workflow, before)
    manager.return_value = before
    workflow.result_ids = [item.id for item in before]
    second = colors.style_alteration_outputs(workflow, after)
    assert model.call_count == audit.call_count == 1
    assert [item["mapColorTable"] for item in first] == [
        item["mapColorTable"] for item in second
    ]
    assert len({item["mapColorTable"]["classes"][1]["color"] for item in first}) == 5
    assert all(
        item["mapColorTable"]["classes"][0]["color"] == "#00000000" for item in first
    )
    assert all(
        item.metadata["colorAdvice"]["source"] == "model_validated" for item in before
    )
    assert all(item.save.call_count == 1 for item in before + after)
    colors.style_alteration_outputs(workflow, after)
    assert model.call_count == 1


def test_unavailable_model_has_honest_deterministic_audit_and_preview_does_not_save(
    monkeypatch,
):
    from apps.agent.provider import ModelError

    monkeypatch.setattr(colors, "model_colors", Mock(side_effect=ModelError("offline")))
    monkeypatch.setattr(colors.ComputeOutput.objects, "filter", Mock(return_value=[]))
    audit = Mock()
    monkeypatch.setattr(colors, "log_operation", audit)
    raster = output(1, "calcite", "before")
    result = colors.style_alteration_outputs(
        SimpleNamespace(result_ids=[]), [raster], persist=False
    )
    assert result[0]["mapColorTable"]["source"] == "deterministic"
    assert raster.metadata == {} and not raster.save.called and not audit.called


def test_named_class_stack_uses_actual_labels_and_one_shared_palette(monkeypatch):
    model = Mock(return_value=None)
    monkeypatch.setattr(colors, "model_colors", model)
    monkeypatch.setattr(colors, "log_operation", Mock())
    previous = []
    monkeypatch.setattr(
        colors.ComputeOutput.objects, "filter", Mock(side_effect=lambda **_: previous)
    )
    workflow = SimpleNamespace(result_ids=[], owner=None, id="stack-palette")
    before = output(10, "calcite", "before")
    before.key = "alteration_stack_before"
    before.metadata = {"bandNames": ["黄铁矿化", "高岭石化", "萤石化"]}
    colors.style_alteration_outputs(workflow, [before])
    assert model.call_args.args[2] == ["萤石化", "高岭石化", "黄铁矿化"]
    tables = before.metadata["mapBandColorTables"]
    assert [item["label"] for item in tables] == before.metadata["bandNames"]
    assert [item["band"] for item in tables] == [1, 2, 3]
    assert len({item["classes"][1]["color"] for item in tables}) == 3
    previous.append(before)
    after = output(11, "calcite", "corrected")
    after.key = "alteration_stack_corrected"
    after.metadata = {"bandNames": before.metadata["bandNames"]}
    colors.style_alteration_outputs(workflow, [after])
    assert model.call_count == 1
    assert after.metadata["mapBandColorTables"] == tables
