"""Transport to the private, upstream Hermes API server."""

from contextlib import contextmanager
from http.client import HTTPConnection, HTTPException
import json
import os
import re

from django.conf import settings
from django.core.exceptions import PermissionDenied
from .hermes_service import service_config, service_root

MAX_JSON_BYTES = 16 * 1024 * 1024
SESSION_ID = re.compile(r"stisp_([0-9a-f]{32})")
RUN_ID = re.compile(r"run_[0-9a-f]{32}")


class GatewayError(Exception):
    def __init__(self, status, payload):
        super().__init__(f"Hermes gateway returned {status}")
        self.status = status
        self.payload = payload


def gateway_key():
    if service_config(settings.PROJECT_CONFIG) or getattr(
        settings, "HERMES_WEB_ENABLED", settings.DEBUG
    ):
        return credential("gateway_key")
    return ""


def credential(name):
    override = os.environ.get(f"STISP_HERMES_{name.upper()}")
    if override is not None:
        return override
    try:
        local = (
            service_root(settings.PROJECT_CONFIG) / "credentials.json"
            if service_config(settings.PROJECT_CONFIG)
            else settings.PROGRAM_ROOT / ".runtime/hermes-web/credentials.json"
        )
        return json.loads(local.read_text(encoding="utf-8")).get(name, "")
    except (OSError, ValueError):
        return ""


def platform_session_id(identity):
    return f"stisp_{identity.hex}"


def session_identity(value):
    match = SESSION_ID.fullmatch(value) if isinstance(value, str) else None
    return match[1] if match else None


def require_tool_key(request):
    from secrets import compare_digest

    expected = credential("tool_key")
    supplied = request.headers.get("Authorization", "")
    if (
        not gateway_key()
        or not expected
        or request.META.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"}
        or not compare_digest(supplied.encode(), f"Bearer {expected}".encode())
    ):
        raise PermissionDenied("Hermes 工具凭据无效")


@contextmanager
def connect(method, path, *, payload=None, headers=None):
    connection = HTTPConnection(
        "127.0.0.1", int(credential("gateway_port") or 18642), timeout=25
    )
    try:
        request_headers = {"Authorization": f"Bearer {gateway_key()}"}
        request_headers.update(headers or {})
        request_body = None
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
            request_body = json.dumps(payload, ensure_ascii=False).encode()
        connection.request(method, path, request_body, request_headers)
        yield connection.getresponse()
    except (OSError, HTTPException) as exc:
        raise GatewayError(
            503,
            {"error": {"code": "hermes_unavailable", "message": "Hermes 网关暂不可用"}},
        ) from exc
    finally:
        connection.close()


def decode(response):
    try:
        body = response.read(MAX_JSON_BYTES + 1)
        payload = json.loads(body) if len(body) <= MAX_JSON_BYTES else None
    except (ValueError, UnicodeError):
        payload = None
    if not isinstance(payload, dict):
        raise GatewayError(
            502,
            {
                "error": {
                    "code": "invalid_gateway_response",
                    "message": "Hermes 返回格式无效",
                }
            },
        )
    if not 200 <= response.status < 300:
        if response.status in {400, 404, 409, 429}:
            raise GatewayError(response.status, payload)
        raise GatewayError(
            503,
            {"error": {"code": "hermes_unavailable", "message": "Hermes 网关暂不可用"}},
        )
    return payload


def request(method, path, *, payload=None, headers=None):
    with connect(method, path, payload=payload, headers=headers) as response:
        return decode(response)
