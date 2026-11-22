"""Native Hermes registration for the platform business flow services."""

from functools import partial
from http.client import HTTPConnection, HTTPException
import json
import os
from pathlib import Path

from agent.redact import _PREFIX_RE
from gateway.session_context import get_session_env
from tools.approval_context import _approval_tool_call_id, _approval_turn_id

TOOLSET = "stisp_business_flows"
TOOLS = ("list_business_flows", "prepare_business_flow_inputs", "start_business_flow")
WEB_TOOLS = {"web_search", "web_extract"}


def authorize_native_tool(tool_name, args=None, session_id=None, turn_id=None, **_):
    if tool_name == "skill_manage":
        return {"action": "block", "message": "共享平台技能由开发者维护"}
    if tool_name not in WEB_TOOLS:
        return None
    args = args or {}
    if tool_name == "web_search":
        query = args.get("query")
        limit = args.get("limit", 5)
        if (
            not isinstance(query, str)
            or not 1 <= len(query.strip()) <= 500
            or type(limit) is not int
            or not 1 <= limit <= 10
        ):
            return {
                "action": "block",
                "message": "公开检索词须为 1 至 500 字，每次最多 10 条结果",
            }
        if _PREFIX_RE.search(query):
            return {"action": "block", "message": "检索词中不能包含凭据"}
    else:
        urls = args.get("urls")
        char_limit = args.get("char_limit", 8000)
        if (
            not isinstance(urls, list)
            or not 1 <= len(urls) <= 4
            or any(
                not isinstance(url, str) or not 1 <= len(url) <= 4096 for url in urls
            )
            or type(char_limit) is not int
            or not 500 <= char_limit <= 12000
        ):
            return {
                "action": "block",
                "message": "每次最多读取 4 个公开页面，每页最多 12000 字符",
            }
    result = platform_call("check_public_web", {}, session_id, turn_id=turn_id)
    if result.get("allowed") is not True:
        return {"action": "block", "message": result.get("error") or "联网授权不可用"}
    return None


def platform_call(name, arguments, session_id, *, turn_id):
    session_id = get_session_env("HERMES_SESSION_CHAT_ID") or session_id
    connection = HTTPConnection(
        "127.0.0.1", int(os.environ["STISP_HERMES_BACKEND_PORT"]), timeout=20
    )
    try:
        connection.request(
            "POST",
            "/internal/hermes/tool/",
            json.dumps(
                {
                    "name": name,
                    "arguments": arguments,
                    "session_id": session_id,
                    "turn_id": turn_id or _approval_turn_id.get(),
                    "tool_call_id": _approval_tool_call_id.get(),
                },
                ensure_ascii=False,
            ).encode(),
            {
                "Authorization": "Bearer " + os.environ["STISP_HERMES_TOOL_KEY"],
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        raw = response.read(262145)
        if len(raw) <= 262144:
            value = json.loads(raw)
            if isinstance(value, dict):
                return value
    except (OSError, HTTPException, ValueError):
        pass
    finally:
        connection.close()
    return {"error": "平台工具服务暂不可用"}


def call(name, arguments, *, session_id=None, turn_id=None, **_):
    return json.dumps(
        platform_call(name, arguments, session_id, turn_id=turn_id),
        ensure_ascii=False,
    )


def register(ctx):
    ctx.register_hook("pre_tool_call", authorize_native_tool)
    path = Path(os.environ["STISP_HERMES_TOOL_CONTRACTS"])
    contracts = json.loads(path.read_text(encoding="utf-8"))["tools"]
    inventory = Path(os.environ["STISP_HERMES_TOOLSETS"])
    for toolset, names in json.loads(inventory.read_text(encoding="utf-8")).items():
        for name in names:
            contract = contracts[name]
            description = contract["description"]
            ctx.register_tool(
                name=name,
                toolset=toolset,
                schema={
                    "name": name,
                    "description": description,
                    "parameters": contract["inputSchema"],
                },
                handler=partial(call, name),
                description=description,
            )
