from __future__ import annotations

import re
from typing import Any

from apps.raster.services.constants import UNIQUE_COLORS


_CLASS_CODE_SPLIT = re.compile(r"[;；\r\n]+")
_CLASS_CODE_ITEM = re.compile(r"^\s*(-?\d+(?:\.0+)?)\s*[:=：]\s*(.+?)\s*$")

_SEMANTIC_COLORS = (
    (("水体", "水域", "河流", "湖泊", "water", "river", "lake"), "#3b79b7"),
    (("林地", "森林", "forest", "woodland"), "#2f7d62"),
    (("耕地", "农田", "cropland", "farmland"), "#d9a441"),
    (("建筑", "建设用地", "building", "built"), "#c45c46"),
    (("道路", "公路", "road"), "#5b5b5b"),
    (("草地", "grass"), "#8aa66b"),
    (("裸地", "bare"), "#b8a978"),
)


def is_categorical_metadata(metadata: dict[str, Any]) -> bool:
    """Return whether GDAL metadata declares a thematic/categorical band."""

    if _metadata_value(metadata, "CLASS_CODES"):
        return True
    for band in metadata.get("bands") or []:
        if band.get("categoryNames") or band.get("colorTable"):
            return True
        rat = band.get("rat")
        if isinstance(rat, dict):
            table_type = str(rat.get("tableType") or "").lower()
            if table_type == "thematic" or rat.get("row") or rat.get("rows"):
                return True
    return False


def categorical_class_entries(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Read class values, labels, and colors from common GDAL metadata forms."""

    classes: dict[int, dict[str, Any]] = {}
    bands = metadata.get("bands") or []
    first_band = bands[0] if bands else {}

    rat = first_band.get("rat")
    if isinstance(rat, dict):
        for item in _rat_entries(rat):
            classes[item["value"]] = item

    category_names = first_band.get("categoryNames")
    if isinstance(category_names, list):
        for value, raw_label in enumerate(category_names):
            label = str(raw_label or "").strip()
            if label:
                classes.setdefault(value, {"value": value})["label"] = label

    class_codes = _metadata_value(metadata, "CLASS_CODES")
    if class_codes:
        for part in _CLASS_CODE_SPLIT.split(class_codes):
            match = _CLASS_CODE_ITEM.match(part)
            if not match:
                continue
            value = int(float(match.group(1)))
            label = match.group(2).strip()
            if label:
                classes.setdefault(value, {"value": value})["label"] = label

    color_entries = ((first_band.get("colorTable") or {}).get("entries") or [])
    if isinstance(color_entries, list):
        for value, rgba in enumerate(color_entries):
            if value not in classes or not isinstance(rgba, list | tuple):
                continue
            color = _rgba_color(rgba)
            if color:
                classes[value]["color"] = color

    result: list[dict[str, Any]] = []
    for index, value in enumerate(sorted(classes)):
        item = classes[value]
        label = str(item.get("label") or value)
        result.append(
            {
                "value": value,
                "label": label,
                "color": str(
                    item.get("color") or default_categorical_color(value, label, index)
                ),
            }
        )
    return result


def default_categorical_color(value: int, label: str, index: int) -> str:
    normalized = label.casefold()
    for keywords, color in _SEMANTIC_COLORS:
        if any(keyword.casefold() in normalized for keyword in keywords):
            return color
    if value == 0 or any(
        keyword in normalized for keyword in ("background", "背景", "未分类")
    ):
        return "#00000000"
    opaque_colors = UNIQUE_COLORS[1:] or ["#2f7d62"]
    return opaque_colors[index % len(opaque_colors)]


def _metadata_value(metadata: dict[str, Any], key: str) -> str:
    containers: list[Any] = [metadata.get("metadata")]
    containers.extend(
        band.get("metadata") for band in (metadata.get("bands") or [])
    )
    for container in containers:
        if not isinstance(container, dict):
            continue
        namespaces = [container, container.get("")]
        for namespace in namespaces:
            if not isinstance(namespace, dict):
                continue
            for candidate, value in namespace.items():
                if str(candidate).upper() == key.upper() and value is not None:
                    return str(value).strip()
    return ""


def _rat_entries(rat: dict[str, Any]) -> list[dict[str, Any]]:
    fields = rat.get("fieldDefn") or rat.get("fields") or []
    rows = rat.get("row") or rat.get("rows") or []
    if not isinstance(fields, list) or not isinstance(rows, list):
        return []

    definitions = [field for field in fields if isinstance(field, dict)]
    result: list[dict[str, Any]] = []
    for row_index, raw_row in enumerate(rows):
        if isinstance(raw_row, dict):
            row = raw_row
        elif isinstance(raw_row, list | tuple):
            row = {
                str(field.get("name") or field.get("index") or index): raw_row[index]
                for index, field in enumerate(definitions)
                if index < len(raw_row)
            }
        else:
            continue

        value = _rat_field_value(row, definitions, {3, 4, 5}, {"value", "minmax"})
        if value is None:
            value = row_index
        try:
            integer_value = int(float(value))
        except (TypeError, ValueError):
            continue
        label = _rat_field_value(row, definitions, {2}, {"name", "label", "class"})
        item: dict[str, Any] = {
            "value": integer_value,
            "label": str(label or integer_value),
        }
        channels = [
            _rat_field_value(row, definitions, {usage}, {name})
            for usage, name in ((6, "red"), (7, "green"), (8, "blue"), (9, "alpha"))
        ]
        if all(channel is not None for channel in channels[:3]):
            item["color"] = _rgba_color(
                [
                    channels[0],
                    channels[1],
                    channels[2],
                    channels[3] if channels[3] is not None else 255,
                ]
            )
        result.append(item)
    return result


def _rat_field_value(
    row: dict[str, Any],
    definitions: list[dict[str, Any]],
    usages: set[int],
    names: set[str],
) -> Any:
    for index, field in enumerate(definitions):
        name = str(field.get("name") or field.get("index") or index)
        usage = field.get("usage")
        normalized_name = name.casefold().replace("_", "").replace(" ", "")
        if usage in usages or normalized_name in names:
            if name in row:
                return row[name]
            if str(index) in row:
                return row[str(index)]
    for name, value in row.items():
        normalized_name = str(name).casefold().replace("_", "").replace(" ", "")
        if normalized_name in names:
            return value
    return None


def _rgba_color(channels: list[Any] | tuple[Any, ...]) -> str:
    if len(channels) < 3:
        return ""
    try:
        rgba = [max(0, min(255, int(float(value)))) for value in channels[:4]]
    except (TypeError, ValueError):
        return ""
    while len(rgba) < 4:
        rgba.append(255)
    suffix = "" if rgba[3] == 255 else f"{rgba[3]:02x}"
    return f"#{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}{suffix}"
