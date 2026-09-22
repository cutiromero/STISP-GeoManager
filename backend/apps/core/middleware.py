from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse


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
