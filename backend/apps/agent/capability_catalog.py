"""Discover registered contracts without granting object access or execution."""

from functools import lru_cache
import json
from pathlib import Path

from apps.core.permissions import has_feature_perm
from .policy import CAPABILITIES, require_access

CONTRACT_FILE = Path(__file__).with_name("tool_contracts.json")


@lru_cache(maxsize=1)
def contracts():
    value = json.loads(CONTRACT_FILE.read_text())
    if value.get("schemaVersion") != 1:
        raise ValueError("不支持的Agent工具合同版本")
    return value["tools"]


def enabled(name, user, policy, *, run=None):
    contract = contracts()[name]
    capability = contract["capability"]
    switches = {
        "internet": policy["internetEnabled"] and bool(run and run.internet_enabled),
        "system_info": policy["systemInfoEnabled"],
        "execute_operator": policy["operatorEnabled"],
        "write_data": policy["operatorEnabled"],
        "map_display": policy.get("mapDisplayEnabled", True),
        "business_flow": policy.get("workflowEnabled", True),
    }
    if not CAPABILITIES.get(capability) or not switches.get(capability, True):
        return False
    if any(
        not has_feature_perm(user, feature)
        for feature in contract["requiredPermissions"]
    ):
        return False
    if contract["anyPermissions"] and not any(
        has_feature_perm(user, feature) for feature in contract["anyPermissions"]
    ):
        return False
    if (
        name in {"read_document", "read_knowledge_document"}
        and not policy["allowDocuments"]
    ):
        return False
    if name == "preview_data_import" and not (
        policy.get("allowDocuments") and policy.get("allowAttachments")
    ):
        return False
    if name == "compare_summaries" and not policy["allowCompare"]:
        return False
    if run is not None:
        from .selections import KNOWLEDGE_TOOLS, knowledge_selection

        if name in KNOWLEDGE_TOOLS and knowledge_selection(run)["mode"] == "none":
            return False
    return True


def catalog(user, project_id):
    policy = require_access(user, "agent")
    return {
        "schemaVersion": 1,
        "projectId": project_id,
        "scope": "current_user_current_project",
        "items": [
            value for name, value in contracts().items() if enabled(name, user, policy)
        ],
        "limitations": "能力目录不授予资料、算法或对象访问权；每次执行仍核对当前账号、项目、任务绑定、策略、预算和必要人工决定。联网能力须在具体会话另行开启。",
    }


def search(user, policy, run, args, *, allowed=None):
    """Return concise, pageable descriptions for the current execution scope."""
    from django.core.exceptions import ValidationError

    query, offset, limit = (
        args.get("query", ""),
        args.get("offset", 0),
        args.get("limit", 8),
    )
    if (
        not isinstance(query, str)
        or len(query) > 120
        or type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= 12
    ):
        raise ValidationError("工具检索词最多120字，分页上限为12项")
    query = query.strip().casefold()
    exact = query if query in contracts() else None
    terms = query.split()
    rows = [
        {
            "name": name,
            "purpose": contract["description"][:170],
            "arguments": list(contract["inputSchema"].get("properties", {})),
            "effect": contract["effect"],
        }
        for name, contract in contracts().items()
        if (allowed is None or name in allowed)
        and enabled(name, user, policy, run=run)
        and (exact is None or name == exact)
        and all(
            term in (name + " " + contract["description"]).casefold() for term in terms
        )
    ]
    return {
        "items": rows[offset : offset + limit],
        "total": len(rows),
        "nextOffset": offset + limit if offset + limit < len(rows) else None,
    }
