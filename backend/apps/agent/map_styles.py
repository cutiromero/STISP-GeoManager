"""A small display-only style vocabulary; never accepts data edits or file paths."""

import math
import re
from django.core.exceptions import ValidationError

COLOR = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")
STYLE_KEYS = {"resourceId", "mode", "field", "band", "classes", "color", "opacity"}


def color(value):
    if not isinstance(value, str) or not COLOR.fullmatch(value):
        raise ValidationError("颜色须为#RRGGBB或#RRGGBBAA，不能包含代码或地址")
    return value.lower()


def display_style(resource, profile, args):
    if not isinstance(args, dict) or set(args) - STYLE_KEYS:
        raise ValidationError(
            "只允许展示样式参数，不接受原始属性、几何、路径或权限修改"
        )
    mode = args.get("mode", "default")
    opacity = args.get("opacity", 100)
    if (
        type(opacity) not in {int, float}
        or not math.isfinite(opacity)
        or not 0 <= opacity <= 100
    ):
        raise ValidationError("透明度须为0至100")
    if mode == "default":
        if set(args) - {"resourceId", "mode"}:
            raise ValidationError("沿用显示方案时无需分类或颜色参数")
        return None
    if mode == "single" and resource.data_type == "vector":
        if set(args) - {"resourceId", "mode", "opacity", "color"}:
            raise ValidationError("单色模式只接受color和opacity")
        selected = color(args.get("color"))
        return {
            "opacity": opacity,
            "pointMode": "circle",
            "renderer": {"type": "single", "updatedByUser": True},
            "circle": {"circleColor": selected},
            "line": {"lineColor": selected, "lineWidth": 1.5},
            "fill": {
                "fillColor": selected,
                "fillOpacity": 0.72,
                "fillOutlineColor": "#475569",
            },
        }
    if mode != "unique":
        raise ValidationError(
            "第一批工具支持矢量single/unique和分类栅格unique；其他栅格沿用显示方案"
        )
    if not profile.get("categoriesComplete") or not profile.get("categories"):
        raise ValidationError("完整类别尚未读取，不能用不完整样本设置颜色表")
    if resource.data_type == "vector" and "band" in args:
        raise ValidationError("矢量分类不接受band参数")
    if resource.data_type == "vector" and args.get("field") != profile.get(
        "categoryField"
    ):
        raise ValidationError("配色字段必须与已读取的真实分类字段一致")
    if resource.data_type == "raster" and args.get("band", 1) != profile.get("band", 1):
        raise ValidationError("配色波段必须与已读取类别一致")
    if "color" in args or (resource.data_type == "raster" and "field" in args):
        raise ValidationError("分类模式应使用classes，不使用单色参数或错误字段")
    classes = args.get("classes")
    if not isinstance(classes, list) or not 1 <= len(classes) <= 96:
        raise ValidationError("classes须为1至96项实际类别及颜色")
    actual = {item["value"]: item for item in profile["categories"]}
    resolved = {}
    for item in classes:
        if not isinstance(item, dict) or set(item) - {"value", "label", "color"}:
            raise ValidationError("类别只接受value、label和color")
        value = item.get("value")
        if type(value) not in {str, int}:
            raise ValidationError("类别值须来自真实类别，不接受表达式或对象")
        value = str(value)
        if value not in actual or value in resolved:
            raise ValidationError("类别不存在或重复，请以get_map_data_profile结果为准")
        label = item.get("label", actual[value].get("label", value))
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise ValidationError("类别标签须为1至80字")
        resolved[value] = {
            "color": color(item.get("color")),
            "label": label.strip(),
            "count": actual[value]["count"],
        }
    if set(resolved) != set(actual):
        raise ValidationError("必须为全部实际类别赋色，不能遗漏类别或隐藏未读部分")
    visible_colors = [
        item["color"][:7]
        for item in resolved.values()
        if not item["color"].endswith("00") or len(item["color"]) == 7
    ]
    if len(visible_colors) != len(set(visible_colors)):
        raise ValidationError("不同可见类别请使用可区分的颜色，不能全部同色")
    if resource.data_type == "vector":
        return {
            "opacity": opacity,
            "pointMode": "circle",
            "renderer": {
                "type": "uniqueValue",
                "field": profile["categoryField"],
                "updatedByUser": True,
                "classes": [
                    {"id": f"agent-class-{index}", "values": [value], **item}
                    for index, (value, item) in enumerate(resolved.items())
                ],
                "defaultClass": {
                    "id": "agent-other",
                    "values": [],
                    "label": "其他/未分类",
                    "color": "#94a3b8",
                    "count": max(
                        0,
                        int(profile.get("featureCount") or 0)
                        - sum(item["count"] for item in resolved.values()),
                    ),
                },
            },
            "fill": {"fillOpacity": 0.8, "fillOutlineColor": "#475569"},
            "line": {"lineWidth": 1.2},
        }
    return {
        "opacity": opacity,
        "mode": "unique",
        "bands": [profile["band"]],
        "alphaBand": "mask",
        "nodata": {"enabled": True},
        "stretch": {"enabled": False, "type": "minmax", "perBand": {}},
        "palette": "poplar",
        "uniqueValues": [
            {"value": int(value), "label": item["label"], "color": item["color"]}
            for value, item in resolved.items()
        ],
    }
