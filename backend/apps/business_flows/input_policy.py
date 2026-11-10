"""Preparation policy is frozen per run; scientific nodes stay immutable."""

from django.core.exceptions import ValidationError


def validate(value):
    if not isinstance(value, dict) or set(value) - {
        "allowScripts",
        "reviewScripts",
        "maxRepairs",
    }:
        raise ValidationError("输入准备策略包含未知字段")
    for key in ("allowScripts", "reviewScripts"):
        if key in value and type(value[key]) is not bool:
            raise ValidationError("输入准备开关必须为布尔值")
    if "maxRepairs" in value and (
        type(value["maxRepairs"]) is not int or not 0 <= value["maxRepairs"] <= 2
    ):
        raise ValidationError("衔接脚本最多返修两次")
    return dict(value)


def for_definition(definition):
    value = validate(definition.get("inputPreparation", {}))
    return {
        "version": 1,
        "allowScripts": value.get("allowScripts", True),
        "reviewScripts": value.get(
            "reviewScripts", any(node["review"]["ai"] for node in definition["nodes"])
        ),
        "maxRepairs": value.get("maxRepairs", 2),
    }
