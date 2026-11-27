from __future__ import annotations

from collections.abc import Callable
import logging
import secrets

from django.http import HttpRequest, HttpResponse, JsonResponse

from .client_build import current_entry
from .browser_sessions import SESSION_KEY
from .localization import localized


CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https://api.mapbox.com "
        "https://tiles.openfreemap.org https://*.tile.openstreetmap.org "
        "https://*.tianditu.gov.cn https://images.unsplash.com",
        "font-src 'self' data:",
        "connect-src 'self' blob: https://api.mapbox.com "
        "https://tiles.openfreemap.org https://*.tile.openstreetmap.org "
        "https://*.tianditu.gov.cn",
        "worker-src 'self' blob:",
        "frame-src 'self' blob:",
        "media-src 'none'",
        "manifest-src 'self'",
    )
)

PERMISSIONS_POLICY = "autoplay=(), picture-in-picture=()"


class FrontendSecurityHeadersMiddleware:
    """Apply browser security policy to HTML documents served by Django."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        content_type = response.get("Content-Type", "").partition(";")[0].lower()
        if content_type != "text/html":
            return response

        if "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        if "Permissions-Policy" not in response:
            response["Permissions-Policy"] = PERMISSIONS_POLICY
        return response


logger = logging.getLogger(__name__)

_API_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_API_ERROR_DETAILS = {
    400: ("请求无效", "Invalid request"),
    401: ("请先登录", "Sign in first"),
    403: ("无权执行该操作", "You are not allowed to perform this action"),
    404: ("接口或资源不存在", "API route or resource not found"),
    405: ("接口不支持该请求方法", "Method not allowed for this API route"),
    413: ("请求内容超出大小限制", "Request body exceeds the size limit"),
    429: ("请求过于频繁，请稍后重试", "Too many requests. Try again later"),
}
_API_ERROR_HEADERS = (
    "Allow",
    "Content-Language",
    "Retry-After",
    "Vary",
    "WWW-Authenticate",
    "X-STISP-Session",
)


class ApiResponseMiddleware:
    """Return API error documents and provenance even for framework failures."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        path = request.path_info
        if path != "/api" and not path.startswith("/api/"):
            return self.get_response(request)

        request_id = secrets.token_hex(12)
        response = self.get_response(request)
        original_status = response.status_code
        content_type = (
            response.get("Content-Type", "").partition(";")[0].strip().lower()
        )
        unexpected_success = (
            200 <= original_status < 300
            and original_status not in {204, 205}
            and response.get("Content-Disposition", "")
            .partition(";")[0]
            .strip()
            .lower()
            != "attachment"
        )
        if content_type in _API_HTML_TYPES and (
            original_status >= 400 or unexpected_success
        ):
            status = 500 if unexpected_success else original_status
            detail = _API_ERROR_DETAILS.get(
                status,
                (
                    "服务处理失败，请稍后重试",
                    "The service could not complete the request. Try again later",
                )
                if status >= 500
                else ("请求未能完成", "The request could not be completed"),
            )
            replacement = JsonResponse(
                {
                    "detail": localized(*detail),
                    **(
                        {"code": "api_unexpected_response"}
                        if unexpected_success
                        else {}
                    ),
                },
                status=status,
                headers={
                    name: response[name]
                    for name in _API_ERROR_HEADERS
                    if name in response
                },
            )
            replacement.cookies.update(response.cookies)
            response = replacement
            if status >= 500:
                logger.error(
                    "API returned an HTML document request_id=%s method=%s route=%s status=%s",
                    request_id,
                    request.method,
                    getattr(request.resolver_match, "view_name", None) or "unresolved",
                    original_status,
                )

        response["X-STISP-Build"] = current_entry() or ""
        response["X-Request-Id"] = request_id
        if (
            response.get("Content-Type", "").partition(";")[0].strip().lower()
            == "application/json"
        ):
            response.setdefault("Cache-Control", "private, no-store")
        return response


class ApiContextMiddleware:
    """Reject requests from a stale browser session identity."""

    EXEMPT = {
        "/api/bootstrap/",
        "/api/auth/login/",
        "/api/auth/register/",
        "/api/auth/guest-login/",
        "/api/auth/csrf/",
        "/api/auth/browser-session/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)
        state = request.session.get(SESSION_KEY)
        state = state if isinstance(state, dict) else {}
        family = state.get("familyId", "") if request.user.is_authenticated else ""
        expected = request.headers.get("X-STISP-Session", "")
        if (
            expected
            and family
            and expected != family
            and request.path not in self.EXEMPT
        ):
            response = JsonResponse(
                {
                    "detail": "账号已在其他页面切换，请重新确认当前账号",
                    "code": "auth_context_changed",
                },
                status=409,
            )
        else:
            response = self.get_response(request)
        if family:
            response["X-STISP-Session"] = family
        return response
