"""The real HTTP stream monitor preserves scope and rechecks live permissions."""

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from django.core.exceptions import PermissionDenied

from apps.agent.config import ModelConfig
from apps.agent.demo_workflow import authorize_demo
from apps.agent.models import AgentWorkflow
from apps.agent.model_guard import ModelStreamGuard
from apps.agent.provider import stream
from apps.agent.workflow import _authorize
from apps.knowledge.models import KnowledgeEntry
from apps.knowledge.services import serialize, visible_entries
from apps.projects.context import ProjectScope, current_scope, project_scope
from apps.projects.models import Project, ProjectMembership
from tests.integration.test_agent import setup_agent  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


@contextmanager
def waiting_http_model(monitored):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            if not monitored.wait(4):
                self.send_error(504)
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                value = {"choices": [{"delta": {"content": "完成"}}]}
                self.wfile.write(
                    ("data: " + json.dumps(value) + "\n\ndata: [DONE]\n\n").encode()
                )
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield ModelConfig(
            "mock",
            "Mock",
            f"http://127.0.0.1:{server.server_port}/v1",
            "mock-local",
            agent=True,
        )
    finally:
        monitored.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.fixture
def scoped_workflow(transactional_db, setup_agent):  # noqa: F811
    env = setup_agent
    with project_scope(ProjectScope((1,), 1, env["admin"].id, True)):
        public = [
            KnowledgeEntry.objects.create(
                title=f"NDVI公开依据{index}",
                category="遥感",
                subject="NDVI",
                predicate="依据",
                object="有效像元",
                statement="核对有效像元",
                domain="remote_sensing",
                status="published",
            )
            for index in range(7)
        ]
    with project_scope(env["scope"]):
        own = KnowledgeEntry.objects.create(
            title="本项目NDVI观测",
            category="遥感",
            subject="NDVI",
            predicate="依据",
            object="调查",
            statement="结合本项目观测",
            domain="remote_sensing",
            status="published",
        )
        workflow = AgentWorkflow.objects.create(
            owner=env["user"],
            model="mock",
            workflow_type="ecology_investigation",
            goal="生态调查",
            resource_ids=[env["resource"].id],
            evidence=[serialize(entry) for entry in [*public, own]],
            status="running",
            idempotency_key="thread-scope-workflow",
            import_results=False,
            plan={
                "knowledgeSelection": {"mode": "manual", "domains": ["remote_sensing"]},
                "inputs": {"context": env["resource"].id},
                "inputSnapshots": {"context": env["resource"].updated_at.isoformat()},
                "algorithms": {},
                "stages": [],
            },
        )
    other = Project.objects.create(code="another-member-project", name="另一成员项目")
    ProjectMembership.objects.create(project=other, user=env["user"])
    with project_scope(ProjectScope((other.id,), other.id, env["user"].id)):
        private = KnowledgeEntry.objects.create(
            title="其他项目私有依据",
            category="遥感",
            statement="其他项目资料",
            domain="remote_sensing",
            status="published",
        )
    return env, workflow, public[0], own, private


def consume(env, workflow, private, on_monitor=None, *, cached=False):
    calling_thread = threading.get_ident()
    monitored = threading.Event()
    scopes = []

    def guard():
        in_monitor = threading.get_ident() != calling_thread
        try:
            scopes.append((in_monitor, current_scope.get()))
            if in_monitor and on_monitor:
                on_monitor()
            user, policy = _authorize(workflow)
            authorize_demo(workflow, user, {**policy, "operatorEnabled": True})
            # Membership in a second project does not widen the selected scope.
            assert not visible_entries(user).filter(pk=private.id).exists()
        finally:
            if in_monitor:
                monitored.set()

    with waiting_http_model(monitored) as model, project_scope(env["scope"]):
        stream_guard = (
            ModelStreamGuard(guard, time.monotonic() + 10) if cached else guard
        )
        result = "".join(
            stream(
                model,
                [{"role": "user", "content": "分析"}],
                200,
                stream_guard,
                monitor_guard=stream_guard.poll if cached else None,
            )
        )
    return result, scopes


@pytest.mark.parametrize("cached", [False, True])
def test_real_monitor_keeps_public_and_selected_project_knowledge(
    scoped_workflow, cached
):
    env, workflow, _, _, private = scoped_workflow
    result, scopes = consume(env, workflow, private, cached=cached)
    assert result == "完成"
    assert any(in_monitor for in_monitor, _ in scopes)
    assert all(scope == env["scope"] for _, scope in scopes)


@pytest.mark.parametrize("source", ["public", "own"])
@pytest.mark.parametrize("cached", [False, True])
def test_real_monitor_rejects_changed_knowledge_revision(
    scoped_workflow, source, cached
):
    env, workflow, public, own, private = scoped_workflow
    entry = public if source == "public" else own

    def revise():
        KnowledgeEntry._base_manager.filter(pk=entry.id).update(revision=2)

    with pytest.raises(PermissionDenied, match="知识依据已变化"):
        consume(env, workflow, private, revise, cached=cached)


@pytest.mark.parametrize("cached", [False, True])
def test_real_monitor_rejects_live_project_membership_revocation(
    scoped_workflow, cached
):
    env, workflow, _, _, private = scoped_workflow

    def revoke():
        ProjectMembership.objects.filter(
            project=env["project"], user=env["user"]
        ).delete()

    with pytest.raises(PermissionDenied, match="项目访问权限已撤回"):
        consume(env, workflow, private, revoke, cached=cached)


@pytest.mark.parametrize("cached", [False, True])
def test_real_monitor_rejects_other_private_project_evidence(scoped_workflow, cached):
    env, workflow, _, _, private = scoped_workflow

    def inject():
        workflow.evidence.append(serialize(private))

    with pytest.raises(PermissionDenied, match="知识依据已变化"):
        consume(env, workflow, private, inject, cached=cached)
