"""Resumable bounded SSE over durable events, without rerunning any work."""

from contextlib import ExitStack
import json
import time

from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.crypto import constant_time_compare

from apps.core.browser_sessions import SESSION_KEY, has_active_page
from apps.core.storage import app_path
from apps.core.storage_locks import storage_lock
from apps.projects.access import can_access_project
from apps.projects.context import current_scope, project_scope
from .models import AgentRun
from .policy import fresh_user, require_access
from .selections import check_history_evidence
from .resource_discovery import discovery_scope

# Configuration: three stream slots leave capacity for ordinary WSGI requests.
MAX_STREAMS = 3
STREAM_SECONDS = 25
POLL_SECONDS = 0.25
AUTH_SECONDS = 0.5
HEARTBEAT_SECONDS = 2
MAX_EVENTS = 100
SNAPSHOT_EVENTS = 40
STREAMING_STATUSES = {"queued", "running"}
SNAPSHOT_KINDS = {"tool_completed", "question", "interaction", "continuation"}


class StreamDenied(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


class StreamLease:
    def __init__(self):
        self.stack = ExitStack()

    def acquire(self):
        for slot in range(MAX_STREAMS):
            try:
                self.stack.enter_context(
                    storage_lock(
                        app_path("cache", "agent-streams", f"{slot}.lock"), wait=False
                    )
                )
                return True
            except OSError:
                continue
        self.close()
        return False

    def close(self):
        self.stack.close()


def frame(kind, value, cursor=None):
    prefix = f"id: {cursor}\n" if cursor is not None else ""
    return (
        prefix
        + f"event: {kind}\ndata: "
        + json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        + "\n\n"
    ).encode()


def event_json(event):
    return {
        "id": event.id,
        "kind": event.kind,
        "text": event.text,
        "createdAt": event.created_at.isoformat(),
    }


def snapshot(run_id, user):
    from .views import run_json

    with transaction.atomic():
        run = AgentRun.objects.select_related("conversation").get(pk=run_id, owner=user)
        cursor = run.events.order_by("-id").values_list("id", flat=True).first() or 0
        with discovery_scope():
            data = run_json(run, user)
        events = list(
            run.events.filter(pk__lte=cursor)
            .exclude(
                kind__in=[
                    "thinking",
                    "answer_preview",
                    "answer_delta",
                    "text",
                    "parameters",
                    "usage",
                ]
            )
            .order_by("-id")[:SNAPSHOT_EVENTS]
        )
    return {
        "run": data,
        "events": [event_json(item) for item in reversed(events)],
        "cursor": cursor,
    }


def live(request, run_id):
    user = fresh_user(request.user.id)
    session = SessionStore(session_key=request.session.session_key).load()
    if str(session.get("_auth_user_id")) != str(user.id) or not constant_time_compare(
        session.get("_auth_user_hash", ""), user.get_session_auth_hash()
    ):
        raise StreamDenied(401, "登录状态已失效，请重新登录")
    state = session.get(SESSION_KEY)
    if state is not None and not has_active_page(state):
        raise StreamDenied(401, "页面会话已失效，请重新登录")
    run = (
        AgentRun.objects.select_related("conversation")
        .filter(pk=run_id, owner=user)
        .first()
    )
    if run is None or not can_access_project(user, run.project_tag_id):
        raise StreamDenied(403, "任务或项目访问权限已变化")
    policy = require_access(user, run.conversation.mode)
    if run.conversation.mode == "agent":
        with discovery_scope():
            check_history_evidence(run, user, policy)
    return run, user


class ClosingStream:
    def __init__(self, iterator, lease):
        self.iterator, self.lease = iterator, lease

    def __iter__(self):
        return self.iterator

    def close(self):
        self.iterator.close()
        self.lease.close()


def response(request, run_id):
    from .views import endpoint

    @endpoint(["GET"])
    def open_stream(request):
        selected = current_scope.get()
        if selected is None or selected.selected is None:
            return JsonResponse({"detail": "请显式选择当前单个项目"}, status=400)
        run = get_object_or_404(
            AgentRun.objects.select_related("conversation"),
            pk=run_id,
            owner=request.user,
        )
        require_access(request.user, run.conversation.mode)
        lease = StreamLease()
        if not lease.acquire():
            result = JsonResponse(
                {"detail": "实时通道暂忙，请使用进度查询"}, status=503
            )
            result["Retry-After"] = "5"
            return result
        try:
            initial = snapshot(run.id, request.user)
        except BaseException:
            lease.close()
            raise
        scope = current_scope.get()

        def generate():
            started = time.monotonic()
            checked = heartbeat = started
            state = initial["run"]["status"]
            try:
                with project_scope(scope):
                    current, user = live(request, run_id)
                    packet = (
                        snapshot(run_id, user)
                        if current.updated_at.isoformat() != initial["run"]["updatedAt"]
                        or current.status != state
                        else initial
                    )
                    cursor, state = packet["cursor"], packet["run"]["status"]
                    yield frame("snapshot", packet, cursor)
                    while (
                        state in STREAMING_STATUSES
                        and time.monotonic() - started < STREAM_SECONDS
                    ):
                        now = time.monotonic()
                        if now - checked >= AUTH_SECONDS:
                            current, user = live(request, run_id)
                            checked = now
                        events = list(
                            current.events.filter(pk__gt=cursor).order_by("id")[
                                :MAX_EVENTS
                            ]
                        )
                        if current.status != state or any(
                            item.kind in SNAPSHOT_KINDS for item in events
                        ):
                            packet = snapshot(run_id, user)
                            cursor, state = packet["cursor"], packet["run"]["status"]
                            yield frame("snapshot", packet, cursor)
                        elif events:
                            old_cursor, cursor = cursor, events[-1].id
                            yield frame(
                                "progress",
                                {
                                    "runId": run_id,
                                    "conversationId": current.conversation_id,
                                    "fromCursor": old_cursor,
                                    "cursor": cursor,
                                    "events": [event_json(item) for item in events],
                                },
                                cursor,
                            )
                        elif now - heartbeat >= HEARTBEAT_SECONDS:
                            yield b": keep-alive\n\n"
                            heartbeat = now
                        time.sleep(POLL_SECONDS)
                    yield frame(
                        "end",
                        {
                            "reason": "renew"
                            if state in STREAMING_STATUSES
                            else "settled"
                        },
                    )
            except StreamDenied as error:
                yield frame("error", {"detail": error.detail, "status": error.status})
            except PermissionDenied:
                yield frame(
                    "error", {"detail": "访问权限已变化，实时连接已停止", "status": 403}
                )
            except (AgentRun.DoesNotExist, ValueError):
                yield frame(
                    "error", {"detail": "任务状态已变化，请重新读取", "status": 404}
                )
            finally:
                lease.close()
                connections.close_all()

        result = StreamingHttpResponse(
            ClosingStream(generate(), lease),
            content_type="text/event-stream; charset=utf-8",
        )
        result["Cache-Control"] = "no-store, no-transform"
        result["Content-Encoding"] = "identity"
        result["X-Accel-Buffering"] = "no"
        return result

    return open_stream(request)
