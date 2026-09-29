"""Small explicit rule vocabulary. Model text is never executed as a rule."""

import math
from django.core.exceptions import ValidationError


def _strings(value, minimum=1):
    return (
        isinstance(value, list)
        and minimum <= len(value) <= 40
        and all(isinstance(v, str) and 0 < len(v) <= 120 for v in value)
    )


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def validate_rule(kind, config):
    if not isinstance(config, dict):
        raise ValidationError("规则配置必须为对象")
    config = dict(config)
    if kind == "mineral_equilibrium" and _strings(config.get("minerals"), 2):
        minerals = [m.strip().casefold() for m in config["minerals"]]
        if (
            len(set(minerals)) < 2
            or len(set(minerals)) != len(minerals)
            or not all(minerals)
        ):
            raise ValidationError("矿物规则需要至少两种不同且非空的矿物")
        config["minerals"] = minerals
        if isinstance(config.get("system"), str):
            config["system"] = config["system"].strip()
    if kind == "none" and not config:
        return kind, config
    if kind == "mineral_equilibrium":
        if (
            set(config) <= {"minerals", "system"}
            and _strings(config.get("minerals"), 2)
            and isinstance(config.get("system"), str)
            and 0 < len(config["system"]) <= 120
        ):
            return kind, config
    if kind == "numeric_range":
        if (
            set(config) <= {"field", "minimum", "maximum", "unit"}
            and isinstance(config.get("field"), str)
            and 0 < len(config["field"]) <= 120
            and _number(config.get("minimum"))
            and _number(config.get("maximum"))
            and config["minimum"] <= config["maximum"]
            and isinstance(config.get("unit", ""), str)
        ):
            return kind, config
    if kind == "required_fields":
        if set(config) == {"fields"} and _strings(config.get("fields")):
            return kind, config
    raise ValidationError("规则类型或结构化参数无效")


def evaluate(kind, config, facts):
    if kind == "mineral_equilibrium":
        minerals = facts.get("minerals")
        if not _strings(minerals):
            return (
                "needs_context",
                "需提供明确的矿物名称列表；遥感候选分类尚不能作为矿物鉴定。",
            )
        if (
            facts.get("equilibrium") is not True
            or facts.get("system") != config["system"]
        ):
            return (
                "needs_context",
                f"需确认属于 {config['system']} 体系且为同阶段平衡组合；保留原观测，核查温压、成分与反应边。",
            )
        present = {m.casefold().strip() for m in minerals}
        if all(m.strip().casefold() in present for m in config["minerals"]):
            return (
                "conflict",
                "给定平衡体系中的矿物组合与该规则冲突。建议复核鉴定、形成阶段和反应结构，保留原始观测及修订记录。",
            )
        return (
            "pass",
            "在已明确的体系和矿物名称范围内，未触发此组合冲突；不等同于全面矿物学验证。",
        )
    if kind == "numeric_range":
        values = facts.get("values", {})
        value = values.get(config["field"]) if isinstance(values, dict) else None
        if not _number(value):
            return (
                "needs_context",
                f"需要 {config['field']} 的有效数值；缺测和非有限值不能作为零处理。",
            )
        unit = config.get("unit", "")
        units = facts.get("units", {})
        if unit and (not isinstance(units, dict) or units.get(config["field"]) != unit):
            return "needs_context", f"请明确 {config['field']} 单位为 {unit} 后核查。"
        if config["minimum"] <= value <= config["maximum"]:
            return (
                "pass",
                f"{config['field']} 在 [{config['minimum']}, {config['maximum']}] 范围内。",
            )
        return (
            "conflict",
            f"{config['field']} 超出 [{config['minimum']}, {config['maximum']}]；检查缩放、单位、掩膜和输入质量。",
        )
    if kind == "required_fields":
        fields = facts.get("fields")
        if not isinstance(fields, list) or any(not isinstance(v, str) for v in fields):
            return "needs_context", "需要提供实际数据字段列表。"
        missing = sorted(set(config["fields"]) - set(fields))
        return (
            ("conflict", "缺少字段：" + "、".join(missing))
            if missing
            else ("pass", "所需字段均已提供；具体数值仍需核查。")
        )
    return "needs_context", "此条目用于解释和人工核查，未配置可计算规则。"
