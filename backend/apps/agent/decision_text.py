"""Bound presentation text without changing executable actions or evidence."""

from __future__ import annotations

from apps.compute.packages import ComputeError


def clipped(text, limit):
    return text if len(text) <= limit else text[: limit - 5] + "（已截断）"


def object_text(value):
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    if isinstance(value, list):
        return "；".join(filter(None, (object_text(item) for item in value)))
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = object_text(item)
            if text:
                parts.append(
                    text
                    if key in {"title", "description", "detail", "标题", "说明"}
                    else f"{key}：{text}"
                )
        return "：".join(parts)
    return str(value)


def normalize_items(value, field):
    if isinstance(value, (str, dict)):
        value = [value]
    if not isinstance(value, list):
        raise ComputeError(
            f"decision.{field} 应为列表、字符串或对象，实际类型为 {type(value).__name__}"
        )
    unique = {}
    for index, item in enumerate(value, 1):
        if item is None:
            continue
        if not isinstance(item, (str, dict)):
            raise ComputeError(
                f"decision.{field} 第{index}项应为字符串或对象，实际类型为 {type(item).__name__}（共{len(value)}项）"
            )
        text = object_text(item)
        if text:
            unique.setdefault(text, None)
    items = list(unique)
    if len(items) > 12:
        items = [*items[:11], f"另有 {len(items) - 11} 项：" + "；".join(items[11:])]
    return list(dict.fromkeys(clipped(text, 2000) for text in items))
