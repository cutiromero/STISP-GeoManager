from __future__ import annotations

from collections.abc import Callable
import secrets

from django.http import HttpRequest, HttpResponse, JsonResponse

from .client_build import current_entry
from .browser_sessions import SESSION_KEY


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
        "connect-src 'self' https://api.mapbox.com "
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


class ApiContextMiddleware:
    """Response provenance and an optional browser identity fence, never ACLs."""

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
        response["X-STISP-Build"] = current_entry() or ""
        response["X-Request-Id"] = secrets.token_hex(12)
        if family:
            response["X-STISP-Session"] = family
        if response.get("Content-Type", "").split(";")[0].strip() == "application/json":
            response.setdefault("Cache-Control", "private, no-store")
        return response
