"""Refresh rule-bound display styles without reading or writing scientific data."""

from copy import deepcopy
from functools import lru_cache
import json

from .color_library import policy_revision


def raster_category_style(rows, names, *, audit=None):
    from .result_colors import category_style

    visible = [
        item
        for item in rows
        if len(item["color"]) == 7 or not item["color"].endswith("00")
    ]
    semantic = {
        str(item["value"]): names.get(str(item["value"]), str(item["value"]))
        for item in visible
    }
    if len(set(semantic.values())) != len(semantic):
        semantic = {key: key for key in semantic}
    proposal = {
        "field": "name",
        "classes": [
            {
                "value": semantic[str(item["value"])],
                "label": item.get("label", str(item["value"])),
                "color": item["color"][:7],
            }
            for item in visible
        ],
    }
    records = []
    style, _ = category_style("name", list(semantic.values()), proposal, audit=records)
    colors = {item["value"]: item["color"] for item in style["renderer"]["classes"]}
    result = deepcopy(rows)
    for item in result:
        name = semantic.get(str(item["value"]))
        if name is not None:
            item["color"] = colors[name] + (
                item["color"][7:] if len(item["color"]) == 9 else ""
            )
    if audit is not None:
        reverse = {name: value for value, name in semantic.items()}
        audit.extend(
            {**item, "value": reverse[item["value"]], "categoryLabel": item["value"]}
            for item in records
        )
    return result, {**style["colorPolicy"], "categoryNames": semantic}


@lru_cache(maxsize=256)
def _refresh(raw, revision):
    from .result_colors import category_style

    style = json.loads(raw)
    renderer = style["renderer"]
    rows = renderer.get("classes", [])
    if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
        return style
    values = []
    for item in rows:
        value = item.get("value")
        grouped = item.get("values", [])
        if value is None and isinstance(grouped, list) and len(grouped) == 1:
            value = item["values"][0]
        if value is None:
            return style
        values.append(str(value))
    if not values or len(values) > 96 or len(values) != len(set(values)):
        return style
    proposal = {
        "field": renderer.get("field"),
        "classes": [
            {
                "value": value,
                "label": row.get("label", value),
                "color": row.get("color"),
            }
            for value, row in zip(values, rows, strict=True)
        ],
    }
    current, _ = category_style(renderer["field"], values, proposal)
    classes = {item["value"]: item for item in current["renderer"]["classes"]}
    for value, row in zip(values, rows, strict=True):
        row["color"] = classes[value]["color"]
    for key in ["fill", "line"]:
        style[key] = {**style.get(key, {}), **current[key]}
    style["colorPolicy"] = current["colorPolicy"]
    return style


def refresh_style(style, *, bound=False):
    if not isinstance(style, dict):
        return style
    renderer = style.get("renderer", {})
    renderer = renderer if isinstance(renderer, dict) else {}
    binding = style.get("colorPolicy", {})
    binding = binding if isinstance(binding, dict) else {}
    if style.get("mode") == "unique" and binding.get("binding") == "platform":
        if binding.get("revision") == policy_revision():
            return style
        table, current = raster_category_style(
            style.get("uniqueValues", []), binding.get("categoryNames", {})
        )
        return {**style, "uniqueValues": table, "colorPolicy": current}
    if (
        renderer.get("type") != "uniqueValue"
        or not isinstance(renderer.get("field"), str)
        or (not bound and binding.get("binding") != "platform")
    ):
        return style
    revision = policy_revision()
    if binding.get("revision") == revision:
        return style
    return deepcopy(_refresh(json.dumps(style, sort_keys=True), revision))


def refresh_visualization(visualization):
    if not isinstance(visualization, dict):
        return visualization
    style = refresh_style(
        visualization.get("symbolization"), bound=bool(visualization.get("colorAdvice"))
    )
    if style is visualization.get("symbolization"):
        return visualization
    return {**visualization, "symbolization": style}


def refresh_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return snapshot
    result = dict(snapshot)
    agent_map = bool(result.get("agentSource"))
    if not isinstance(result.get("groups"), list):
        return result
    result["groups"] = []
    for original in snapshot["groups"]:
        if not isinstance(original, dict) or not isinstance(
            original.get("children"), list
        ):
            result["groups"].append(original)
            continue
        group = {**original, "children": []}
        result["groups"].append(group)
        for source_layer in original["children"]:
            if not isinstance(source_layer, dict):
                group["children"].append(source_layer)
                continue
            layer = dict(source_layer)
            group["children"].append(layer)
            style = refresh_style(
                layer.get("symbolization"),
                bound=agent_map or bool(layer.get("colorAdvice")),
            )
            # Layers saved without a style keep that shape; no empty key is added.
            if style is not None or "symbolization" in layer:
                layer["symbolization"] = style
            if layer.get("layerType") == "raster" and layer.get(
                "symbolization"
            ) is not source_layer.get("symbolization"):
                layer.pop("tileUrl", None)
                layer["renderStatus"] = "queued"
    return result
