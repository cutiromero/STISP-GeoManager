from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.core.initialization import is_guest_user, GUEST_GROUP_NAME
from apps.core.permissions import has_feature_perm
from apps.projects.context import require_live_membership
from .config import registry
from .models import AgentPolicy, AgentRuntime
from .budgets import defaults as budget_defaults, validate_budgets

CAPABILITIES = {
    "chat": True,
    "read_data": True,
    "business_flow": True,
    "analyze_data": True,
    "map_display": True,
    # Registered side effects remain disabled by policy until an administrator
    # explicitly enables ``operatorEnabled``.  The registry flags only state
    # that the adapter exists; execute() performs the runtime policy check.
    "execute_operator": True,
    "write_data": True,
    "publish_result": False,
    "system_info": True,
    "internet": True,
}


def audience_default():
    return {"restricted": False, "groupIds": [], "userIds": [], "deniedUserIds": []}


def default_policy():
    models = registry()
    first = next(iter(models), "")
    agent = next((m.alias for m in models.values() if m.agent), "")
    return {
        **budget_defaults(),
        "enabled": True,
        "chatEnabled": True,
        "agentEnabled": True,
        "thinkingEnabled": True,
        "workflowEnabled": True,
        "operatorEnabled": False,
        "mapDisplayEnabled": True,
        "systemInfoEnabled": True,
        "internetEnabled": False,
        "allowAttachments": True,
        "chatAudience": audience_default(),
        "agentAudience": audience_default(),
        "defaultChatModel": first,
        "defaultAgentModel": agent,
        "dailyRuns": 100,
        # Context is tracked as a conservative UTF-8 byte budget.  With the
        # current 32K-token local model window this leaves room for the answer
        # and system/tool instructions instead of failing on a small file.
        "maxContextBytes": 384000,
        "maxOutputTokens": 8192,
        "maxContextTokens": 49152,
        "reasoningEffort": "medium",
        "temperature": 0.2,
        "topP": 0.9,
        "maxSteps": 32,
        "maxResources": 3,
        "maxIterations": 5,
        "maxOperatorSteps": 8,
        "maxProtocolRetries": 1,
        "maxRunSeconds": 600,
        "allowDocuments": True,
        "allowCompare": True,
        "maxAttachmentBytes": 20 * 1024 * 1024,
        "maxAttachments": 8,
        "dataTypes": ["table", "vector", "raster", "gene", "document", "image"],
        "models": [
            {
                "alias": m.alias,
                "enabled": True,
                "allowAgent": m.agent,
                "sortOrder": i,
                "concurrency": 1,
                "audience": audience_default(),
            }
            for i, m in enumerate(models.values())
        ],
        "quotas": [],
    }


def policy():
    saved = AgentPolicy.objects.filter(pk=1).first()
    if not saved or not saved.value:
        return default_policy()
    # New policy keys are additive so a server upgraded from the read-only
    # agent keeps working before the data migration is applied.
    value = default_policy()
    value.update(saved.value)
    return value


def audience_allows(user, rule):
    if user.pk in rule["deniedUserIds"]:
        return False
    return (
        not rule["restricted"]
        or user.pk in rule["userIds"]
        or user.groups.filter(pk__in=rule["groupIds"]).exists()
    )


def allowed(user, mode, p=None):
    p = p or policy()
    if (
        not user.is_authenticated
        or not user.is_active
        or is_guest_user(user)
        or user.groups.filter(name=GUEST_GROUP_NAME).exists()
    ):
        return False
    if (
        not p["enabled"]
        or not p[f"{mode}Enabled"]
        or not audience_allows(user, p[f"{mode}Audience"])
    ):
        return False
    needed = ["core.use_local_model"]
    if mode == "agent":
        needed += ["core.use_data_agent", "core.browse_data", "core.query_data"]
    return all(has_feature_perm(user, name) for name in needed)


def require_access(user, mode, alias=None):
    require_live_membership()
    p = policy()
    if not allowed(user, mode, p):
        raise PermissionDenied("智能体使用权限已关闭或不可用")
    if alias is not None and alias not in {
        m["alias"] for m in visible_models(user, mode, p)
    }:
        raise PermissionDenied("当前模型不可用或无权使用")
    return p


def fresh_user(user_id):
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        raise PermissionDenied("账号已停用")
    return user


def visible_models(user, mode=None, p=None, admin=False):
    p = p or policy()
    configs = registry()
    health = {h.name: h for h in AgentRuntime.objects.filter(name__startswith="model:")}
    output = []
    for rule in sorted(p["models"], key=lambda r: r["sortOrder"]):
        model = configs.get(rule["alias"])
        if not model or (
            not admin
            and (not rule["enabled"] or not audience_allows(user, rule["audience"]))
        ):
            continue
        can_agent = model.agent and rule["allowAgent"]
        if mode == "agent" and not can_agent:
            continue
        h = health.get("model:" + model.alias)
        recent = (
            h and h.heartbeat and h.heartbeat > timezone.now() - timedelta(seconds=90)
        )
        output.append(
            {
                "alias": model.alias,
                "name": model.name,
                "allowAgent": can_agent,
                "contextWindowTokens": h.detail.get(
                    "contextWindowTokens", model.context_window_tokens
                )
                if recent
                else model.context_window_tokens,
                "supportsThinking": model.qwen,
                "supportsVision": model.vision,
                "status": h.detail.get("status", "unknown") if recent else "unknown",
                "checkedAt": h.heartbeat.isoformat() if h and h.heartbeat else "",
            }
        )
    return output


def worker_online():
    return AgentRuntime.objects.filter(
        name="worker", heartbeat__gt=timezone.now() - timedelta(seconds=15)
    ).exists()


def daily_quota(user, p):
    limits = [p["dailyRuns"]]
    groups = set(user.groups.values_list("id", flat=True))
    for q in p["quotas"]:
        if (q["kind"] == "user" and q["id"] == user.id) or (
            q["kind"] == "group" and q["id"] in groups
        ):
            limits.append(q["dailyRuns"])
    finite = [limit for limit in limits if limit > 0]
    return min(finite) if finite else 0


def validate_policy(value):
    """Validate against the same explicit structure exposed in OpenAPI."""
    defaults = default_policy()
    if isinstance(value, dict) and "mapDisplayEnabled" not in value:
        value = {**value, "mapDisplayEnabled": defaults["mapDisplayEnabled"]}
    if not isinstance(value, dict) or set(value) != set(defaults):
        raise ValidationError("策略字段不完整或含未支持能力")
    validate_budgets(value)
    for k in (
        "enabled",
        "chatEnabled",
        "agentEnabled",
        "thinkingEnabled",
        "workflowEnabled",
        "operatorEnabled",
        "mapDisplayEnabled",
        "systemInfoEnabled",
        "internetEnabled",
        "allowAttachments",
        "allowDocuments",
        "allowCompare",
    ):
        if type(value[k]) is not bool:
            raise ValidationError("开关必须为布尔值")
    for k, lo in [
        ("dailyRuns", 0),
        ("maxContextBytes", 8000),
        ("maxOutputTokens", 128),
        ("maxContextTokens", 1024),
        ("maxSteps", 0),
        ("maxResources", 0),
        ("maxIterations", 1),
        ("maxOperatorSteps", 1),
        ("maxProtocolRetries", 0),
        ("maxRunSeconds", 60),
        ("maxAttachments", 1),
    ]:
        if type(value[k]) is not int or value[k] < lo:
            raise ValidationError(f"{k} 超出允许范围")
    if (
        type(value["maxAttachmentBytes"]) is not int
        or not 1024 <= value["maxAttachmentBytes"] <= 200_000_000
    ):
        raise ValidationError("单个附件大小须在 1 KB 至 200 MB 之间")
    if value["reasoningEffort"] not in {"low", "medium", "xhigh"}:
        raise ValidationError("思考强度必须为 low、medium 或 xhigh")
    for k, lo, hi in (("temperature", 0.0, 2.0), ("topP", 0.0, 1.0)):
        if type(value[k]) not in (int, float) or not lo <= value[k] <= hi:
            raise ValidationError(f"{k} 超出允许范围")

    def audience(a):
        if (
            not isinstance(a, dict)
            or set(a) != set(audience_default())
            or type(a["restricted"]) is not bool
        ):
            raise ValidationError("用户范围格式无效")
        for k in ("groupIds", "userIds", "deniedUserIds"):
            if (
                not isinstance(a[k], list)
                or len(a[k]) > 5000
                or any(type(i) is not int or i < 1 for i in a[k])
            ):
                raise ValidationError("用户或组 ID 无效")

    audience(value["chatAudience"])
    audience(value["agentAudience"])
    configs = registry()
    if not isinstance(value["models"], list) or len(value["models"]) != len(configs):
        raise ValidationError("模型注册已变化，请刷新配置")
    seen = set()
    for m in value["models"]:
        if (
            not isinstance(m, dict)
            or set(m)
            != {
                "alias",
                "enabled",
                "allowAgent",
                "sortOrder",
                "concurrency",
                "audience",
            }
            or m.get("alias") not in configs
            or m["alias"] in seen
        ):
            raise ValidationError("模型策略无效")
        seen.add(m["alias"])
        if any(type(m[k]) is not bool for k in ("enabled", "allowAgent")) or (
            m["allowAgent"] and not configs[m["alias"]].agent
        ):
            raise ValidationError("该模型尚未配置智能体协议")
        if (
            type(m["concurrency"]) is not int
            or not 1 <= m["concurrency"] <= 3
            or type(m["sortOrder"]) is not int
            or not 0 <= m["sortOrder"] <= 999
        ):
            raise ValidationError("模型排序或并发无效")
        audience(m["audience"])
    for key in ("defaultChatModel", "defaultAgentModel"):
        alias = value[key]
        if not isinstance(alias, str) or (alias and alias not in configs):
            raise ValidationError("默认模型不存在")
        if alias and not any(
            m["alias"] == alias
            and m["enabled"]
            and (key != "defaultAgentModel" or m["allowAgent"])
            for m in value["models"]
        ):
            raise ValidationError("默认模型已停用或不支持对应模式")
    if not isinstance(value["dataTypes"], list) or any(
        t not in defaults["dataTypes"] for t in value["dataTypes"]
    ):
        raise ValidationError("数据类型无效")
    if not isinstance(value["quotas"], list) or len(value["quotas"]) > 5000:
        raise ValidationError("额度策略无效")
    for q in value["quotas"]:
        if (
            not isinstance(q, dict)
            or set(q) != {"kind", "id", "dailyRuns"}
            or q["kind"] not in {"user", "group"}
            or type(q["id"]) is not int
            or q["id"] < 1
            or type(q["dailyRuns"]) is not int
            or q["dailyRuns"] < 0
        ):
            raise ValidationError("额度策略无效")
    return value
