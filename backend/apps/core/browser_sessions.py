"""Page leases in Django Session; tokens stay out of URLs and persistent storage."""

from __future__ import annotations

import hashlib
from functools import wraps
import json
import re
import secrets
import time

from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import OperationalError, transaction
from django.db.models import F
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from apps.core.localization import localized

SESSION_KEY = "_stisp_browser_pages"
LEASE_SECONDS = 120
RESUME_SECONDS = 120
RECOVERY_SECONDS = 12 * 60 * 60
START_SECONDS = 30
PAGE_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,80}\Z")
TOKEN_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
EXEMPT_PATHS = {
    "/api/auth/browser-session/",
    "/api/auth/login/",
    "/api/auth/guest-login/",
    "/api/auth/register/",
    "/api/auth/logout/",
    "/api/auth/csrf/",
}


def prepare_browser_session(request) -> None:
    request.session.set_expiry(0)
    request.session[SESSION_KEY] = {
        "familyId": secrets.token_hex(16),
        "startUntil": time.time() + START_SECONDS,
        "pages": {},
    }


def has_active_page(state: dict, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return any(
        page.get("expiresAt", 0) > now for page in state.get("pages", {}).values()
    )


def recoverable_page(page: dict, now: float) -> bool:
    # A missing heartbeat is different from an explicit pagehide suspension.
    expires = page.get("expiresAt", 0)
    return expires > 0 and expires + RECOVERY_SECONDS > now


def retained_page(page: dict, now: float) -> bool:
    return recoverable_page(page, now) or page.get("resumeUntil", 0) > now


def unauthorized() -> JsonResponse:
    return JsonResponse({"detail": localized("请先登录", "Sign in first")}, status=401)


class BrowserPageSessionMiddleware:
    """Apply the lease to all cookie-backed data, file, image and tile requests."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        state = request.session.get(SESSION_KEY)
        if (
            request.path not in EXEMPT_PATHS
            and request.user.is_authenticated
            and state is not None
            and not has_active_page(state)
        ):
            # Keep the authenticated session for the brief refresh handshake;
            # downstream permissions receive an anonymous principal meanwhile.
            request.user = request._cached_user = AnonymousUser()
        return self.get_response(request)


def retry_session_write(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        for attempt in range(5):
            try:
                return view(*args, **kwargs)
            except OperationalError as error:
                if "locked" not in str(error).lower() or attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))

    return wrapped


@require_POST
@retry_session_write
def browser_session_view(request):
    if not request.user.is_authenticated:
        return unauthorized()
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeError):
        payload = None
    if not isinstance(payload, dict) or payload.get("action") not in {
        "start",
        "resume",
        "join",
        "heartbeat",
        "suspend",
        "abandon",
    }:
        return JsonResponse({"detail": "页面会话请求无效"}, status=400)
    action = payload["action"]
    if action == "abandon":
        # An unclaimed tab must not flush the shared Cookie or revoke another
        # page. Mark legacy sessions without issuing a stale Set-Cookie header.
        row = Session.objects.filter(session_key=request.session.session_key).first()
        data = row.get_decoded() if row else {}
        state = data.get(SESSION_KEY)
        if not isinstance(state, dict):
            state = {"familyId": secrets.token_hex(16), "startUntil": 0, "pages": {}}
            data[SESSION_KEY] = state
            if row:
                Session.objects.filter(pk=row.pk).update(
                    session_data=SessionStore().encode(data)
                )
        return JsonResponse(
            {
                "detail": "当前页面未续接，其他页面会话保留",
                "active": has_active_page(state),
            }
        )
    page_id, token = payload.get("pageId"), payload.get("token")
    if not isinstance(page_id, str) or not PAGE_PATTERN.fullmatch(page_id):
        return JsonResponse({"detail": "页面标识无效"}, status=400)
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        return JsonResponse({"detail": "页面会话令牌无效"}, status=400)
    sequence = payload.get("sequence")
    if type(sequence) is not int or sequence < 1:
        return JsonResponse({"detail": "页面会话序号无效"}, status=400)
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    # Refetch and save only the current session row. SessionMiddleware must not
    # later save an older cached registry over another tab's update.
    with transaction.atomic():
        # SQLite cannot upgrade an old WAL read snapshot after a worker writes.
        # Reserve this short write before reading; page validation still uses
        # the latest session registry and no lease is extended by this update.
        if not Session.objects.filter(session_key=request.session.session_key).update(
            session_data=F("session_data")
        ):
            return unauthorized()
        row = (
            Session.objects.select_for_update()
            .filter(session_key=request.session.session_key)
            .first()
        )
        if row is None:
            return unauthorized()
        data = row.get_decoded()
        state = data.get(SESSION_KEY)
        if not isinstance(state, dict):
            return unauthorized()
        pages = state.get("pages", {})
        page = pages.get(page_id)

        def matches(entry: dict) -> bool:
            return secrets.compare_digest(entry.get("digest", ""), digest)

        if page and matches(page) and sequence <= page.get("sequence", 0):
            return JsonResponse(
                {
                    "detail": "较早的页面请求已忽略",
                    "active": has_active_page(state, now),
                }
            )
        if action == "start":
            allowed = not pages and state.get("startUntil", 0) > now
        elif action == "join":
            # The authenticated Cookie and CSRF token can join a live browser
            # session even when a background peer cannot answer its channel.
            allowed = has_active_page(state, now)
        elif action == "resume":
            allowed = any(
                matches(entry) and recoverable_page(entry, now)
                for entry in pages.values()
            )
            allowed = allowed or bool(
                page and matches(page) and page.get("resumeUntil", 0) > now
            )
        else:
            allowed = bool(page and matches(page) and recoverable_page(page, now))
            if action == "suspend":
                allowed = allowed or bool(
                    page and matches(page) and page.get("resumeUntil", 0) > now
                )
        if not allowed:
            return unauthorized()
        pages = {
            key: value for key, value in pages.items() if retained_page(value, now)
        }
        if page_id not in pages and len(pages) >= 128:
            return JsonResponse(
                {"detail": "打开的页面过多，请关闭不用的标签页"}, status=400
            )
        pages[page_id] = {
            "digest": digest,
            "sequence": sequence,
            "expiresAt": 0 if action == "suspend" else now + LEASE_SECONDS,
            "resumeUntil": now + RESUME_SECONDS if action == "suspend" else 0,
        }
        family_id = state.get("familyId") or secrets.token_hex(16)
        state = {"familyId": family_id, "startUntil": 0, "pages": pages}
        data[SESSION_KEY] = state
        row.session_data = SessionStore().encode(data)
        row.save(update_fields=["session_data"])
    request.session = SessionStore(session_key=request.session.session_key)
    return JsonResponse(
        {
            "detail": "页面会话已更新",
            "active": has_active_page(state, now),
            "familyId": family_id,
        }
    )
