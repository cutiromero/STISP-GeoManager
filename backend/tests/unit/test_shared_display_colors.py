"""Both entry points consume one live table and the same validation service."""

from copy import deepcopy
import json
from types import SimpleNamespace

from apps.agent import color_library
from apps.agent.display_color_policy import refresh_snapshot, refresh_visualization
from apps.agent.map_styles import display_style
from apps.agent.result_colors import category_style


def profile():
    return {
        "categoryField": "name",
        "categoriesComplete": True,
        "geometryType": "Polygon",
        "categories": [
            {"value": value, "count": 1} for value in color_library.lithology_colors()
        ],
    }


def test_map_and_logic_use_all_38_exact_reference_colors_and_keep_standard_duplicates():
    expected = color_library.lithology_colors()
    data = profile()
    proposal = {
        "field": "name",
        "classes": [{"value": value, "color": "#123456"} for value in expected],
    }
    logic, _ = category_style("name", list(expected), proposal)
    records = []
    style = display_style(
        SimpleNamespace(data_type="vector"),
        data,
        {"resourceId": 1, "mode": "unique", **proposal},
        audit=records,
    )
    mapped = {row["values"][0]: row["color"] for row in style["renderer"]["classes"]}
    assert (
        mapped
        == expected
        == {row["value"]: row["color"] for row in logic["renderer"]["classes"]}
    )
    assert all(row["source"] == "library_selected" for row in records)
    assert any(
        "duplicate_standard_color_preserved" in row["replacementReasons"]
        for row in records
    )
    assert style["fill"] == logic["fill"]
    assert (
        color_library.reference_entries("name", list(expected))["全新世冲积物qhal"][
            "color"
        ]
        == "#ffffd8"
    )


def test_editing_only_canonical_table_updates_logic_tools_and_saved_maps(
    monkeypatch, tmp_path
):
    original = color_library.LITHOLOGY_PATH.read_bytes()
    target = tmp_path / "lithology_colors.json"
    target.write_bytes(original)
    monkeypatch.setattr(color_library, "LITHOLOGY_PATH", target)
    data = profile()
    args = {"resourceId": 1, "mode": "reference", "field": "name"}
    before = display_style(SimpleNamespace(data_type="vector"), data, args)
    snapshot = {
        "groups": [{"children": [{"layerType": "vector", "symbolization": before}]}]
    }
    untouched = deepcopy(snapshot)
    changed = json.loads(original)
    value = "全新世冲积物qhal"
    changed["colors"][value] = "#123456"
    target.write_text(json.dumps(changed))
    after = display_style(SimpleNamespace(data_type="vector"), data, args)
    logic, _ = category_style("name", list(changed["colors"]))
    restored = refresh_snapshot(snapshot)["groups"][0]["children"][0]["symbolization"]
    resource = refresh_visualization(
        {"symbolization": before, "colorAdvice": {"version": 3}}
    )
    for style in [after, logic, restored, resource["symbolization"]]:
        assert (
            next(
                row["color"]
                for row in style["renderer"]["classes"]
                if row.get("value") == value
            )
            == "#123456"
        )
        assert style["colorPolicy"]["revision"] != before["colorPolicy"]["revision"]
    assert snapshot == untouched


def test_color_index_cannot_keep_a_second_copy_of_lithology_or_mineral_colors():
    entries = json.loads(color_library.LIBRARY_PATH.read_bytes())["entries"]
    for row in entries:
        if row["id"].startswith("lithology-") or row["domain"] == "alteration":
            assert "color" not in row and "referenceColor" not in row


def test_manual_styles_without_rule_binding_are_preserved():
    style = {
        "renderer": {
            "type": "uniqueValue",
            "field": "name",
            "classes": [{"value": "全新世冲积物qhal", "color": "#123456"}],
        }
    }
    snapshot = {
        "groups": [{"children": [{"layerType": "vector", "symbolization": style}]}]
    }
    assert refresh_snapshot(snapshot) == snapshot


def test_one_mineral_table_edit_updates_raster_maps_and_logic_previews(
    monkeypatch, tmp_path
):
    from apps.agent.display_color_policy import raster_category_style
    from apps.compute.map_preview import _rules

    target = tmp_path / "alteration_colors.json"
    data = json.loads(color_library.ALTERATION_PATH.read_bytes())
    target.write_text(json.dumps(data))
    monkeypatch.setattr(color_library, "ALTERATION_PATH", target)
    rows = [
        {"value": 0, "label": "无蚀变", "color": "#00000000"},
        {"value": 1, "label": "方解石化", "color": "#123456ff"},
    ]
    table, binding = raster_category_style(rows, {"1": "方解石化"})
    assert table[1]["color"] == "#21869cff"
    style = {"mode": "unique", "uniqueValues": table, "colorPolicy": binding}
    saved = {
        "groups": [
            {
                "children": [
                    {
                        "layerType": "raster",
                        "symbolization": style,
                        "tileUrl": "/old.png",
                    }
                ]
            }
        ]
    }
    data["碳酸盐化"] = "#336699"
    target.write_text(json.dumps(data))
    restored = refresh_snapshot(saved)["groups"][0]["children"][0]
    assert restored["symbolization"]["uniqueValues"][1]["color"] == "#336699ff"
    assert restored["symbolization"]["uniqueValues"][0]["color"] == "#00000000"
    assert (
        "tileUrl" not in restored
        and saved["groups"][0]["children"][0]["tileUrl"] == "/old.png"
    )
    output = SimpleNamespace(
        key="calcite_corrected",
        metadata={"mapColorTable": {"classes": rows, "source": "model_validated"}},
    )
    assert _rules(output)["colorTable"][1]["color"] == "#336699ff"
