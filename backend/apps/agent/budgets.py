"""Task defaults and authenticated role ceilings, separate from model capacity."""

from copy import deepcopy

from django.core.exceptions import PermissionDenied, ValidationError
from apps.projects.context import is_superadmin
from .provider import ModelError

PROFILES = ("normal", "materials", "reasoning")
TIERS = ("standard", "superadmin")
SAFETY_TOKENS = 256


def defaults():
    return {
        "taskBudgetsEnabled": False,
        "defaultBudgetProfile": "normal",
        "budgetProfiles": {
            "normal": {
                "maxOutputTokens": 32768,
                "maxRunSeconds": 1800,
                "reasoningEffort": "medium",
            },
            "materials": {
                "maxOutputTokens": 16384,
                "maxRunSeconds": 1800,
                "reasoningEffort": "low",
            },
            "reasoning": {
                "maxOutputTokens": 65536,
                "maxRunSeconds": 3600,
                "reasoningEffort": "xhigh",
            },
        },
        "budgetLimits": {
            "standard": {
                "contextWindowTokens": 65536,
                "maxOutputTokens": 16384,
                "maxRunSeconds": 600,
            },
            "superadmin": {
                "contextWindowTokens": 262144,
                "maxOutputTokens": 261632,
                "maxRunSeconds": 7200,
            },
        },
    }


def validate_budgets(value):
    if (
        type(value["taskBudgetsEnabled"]) is not bool
        or value["defaultBudgetProfile"] not in PROFILES
    ):
        raise ValidationError("任务预算开关或默认方案无效")
    profiles, limits = value["budgetProfiles"], value["budgetLimits"]
    if not isinstance(profiles, dict) or set(profiles) != set(PROFILES):
        raise ValidationError("须配置普通分析、长材料和长推理三种预算")
    if not isinstance(limits, dict) or set(limits) != set(TIERS):
        raise ValidationError("须配置普通用户和超级管理员额度")
    for name, rule in list(profiles.items()) + list(limits.items()):
        is_limit = name in TIERS
        keys = (
            {"contextWindowTokens", "maxOutputTokens", "maxRunSeconds"}
            if is_limit
            else {"maxOutputTokens", "maxRunSeconds", "reasoningEffort"}
        )
        if not isinstance(rule, dict) or set(rule) != keys:
            raise ValidationError("预算字段不完整或包含未知字段")
        for key, low in [
            ("maxOutputTokens", 128),
            ("maxRunSeconds", 60),
        ]:
            if type(rule[key]) is not int or rule[key] < low:
                raise ValidationError(f"{name}.{key} 超出允许范围")
        if is_limit:
            window = rule["contextWindowTokens"]
            if (
                type(window) is not int
                or window < 1024
                or rule["maxOutputTokens"] > window - 512
            ):
                raise ValidationError("用户窗口须容纳生成额度、输入和安全余量")
        elif rule["reasoningEffort"] not in {"low", "medium", "xhigh"}:
            raise ValidationError("预算思考强度无效")


def tier_for(user):
    return "superadmin" if is_superadmin(user) else "standard"


def resolve_budget(user, policy, profile="", output=None, service_window=None):
    if not policy["taskBudgetsEnabled"]:
        if profile or output is not None:
            raise ValidationError("管理员尚未开启按任务配置预算")
        return {}
    selected = profile or policy["defaultBudgetProfile"]
    if selected not in PROFILES:
        raise ValidationError("任务预算方案无效")
    tier = tier_for(user)
    limits = policy["budgetLimits"][tier]
    preset = policy["budgetProfiles"][selected]
    window = min(
        limits["contextWindowTokens"], service_window or limits["contextWindowTokens"]
    )
    if output is not None and (
        type(output) is not int
        or not 128 <= output <= min(limits["maxOutputTokens"], window - 512)
    ):
        raise ValidationError("本次生成额度超出您的允许范围")
    return {
        "budgetProfile": selected,
        "tier": tier,
        "contextWindowTokens": window,
        "maxOutputTokens": output
        if output is not None
        else min(preset["maxOutputTokens"], limits["maxOutputTokens"], window // 2),
        "maxRunSeconds": min(preset["maxRunSeconds"], limits["maxRunSeconds"]),
        "reasoningEffort": preset["reasoningEffort"],
        "requestedMaxOutputTokens": output,
    }


def check_budget_access(user, policy, snapshot):
    if not snapshot:
        return
    limits = policy["budgetLimits"][tier_for(user)]
    if not policy["taskBudgetsEnabled"] or any(
        snapshot[key] > limits[key] for key in limits
    ):
        raise PermissionDenied("任务预算权限已收窄，请按当前额度重新提交")


def apply_budget(user, policy, snapshot, service_window):
    if not snapshot:
        return policy, service_window
    check_budget_access(user, policy, snapshot)
    result = deepcopy(policy)
    window = min(service_window, snapshot["contextWindowTokens"])
    if snapshot["maxOutputTokens"] > window - 512:
        raise ModelError("本次生成额度占满实际模型窗口，请降低额度或切换模型")
    result.update(
        {
            key: snapshot[key]
            for key in ("maxOutputTokens", "maxRunSeconds", "reasoningEffort")
        }
    )
    result["maxContextTokens"] = window - result["maxOutputTokens"] - SAFETY_TOKENS
    # A character/byte guard is not a tokenizer. Allow enough text for native
    # windows; prepare_context still measures the complete multimodal request.
    result["maxContextBytes"] = max(policy["maxContextBytes"], window * 8)
    return result, window


def budget_options(user, policy):
    enabled = policy["taskBudgetsEnabled"]
    tier = tier_for(user)
    return {
        "enabled": enabled,
        "tier": tier,
        "defaultProfile": policy["defaultBudgetProfile"],
        "limits": policy["budgetLimits"][tier],
        "profiles": [resolve_budget(user, policy, name) for name in PROFILES]
        if enabled
        else [],
        "maxPromptCharacters": policy["budgetLimits"][tier]["contextWindowTokens"] * 4
        if enabled
        # A Unicode character may consume four UTF-8 bytes. This request-size
        # estimate follows the configured budgets; prepare_context still counts
        # the complete model request with the serving tokenizer.
        else min(policy["maxContextTokens"] * 4, policy["maxContextBytes"] // 4),
    }
