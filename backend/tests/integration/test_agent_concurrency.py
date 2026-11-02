"""Ordinary chat and research-agent admission share three atomic account slots."""

# ruff: noqa: F811 - reusable pytest fixture imported by name.
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections, connections
from django.test import Client, RequestFactory

from apps.agent.interactions import resume_compute, wait_for_answer
from apps.agent.models import ACTIVE, AgentRun, Conversation
from apps.agent.views import ApiProblem, submit_value
from apps.compute.models import AlgorithmResource, AlgorithmVersion, ComputeTask
from apps.compute.packages import ComputeError
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import ProjectMembership
from tests.integration.test_agent import setup_agent  # noqa: F401
from tests.integration.test_agent_interactions import question, respond


def conversation(env, mode="agent", *, owner=None, project_id=None):
    owner = owner or env["user"]
    project_id = project_id or env["project"].id
    with project_scope(ProjectScope((project_id,), project_id, owner.id)):
        return Conversation.objects.create(owner=owner, mode=mode)


def make_run(env, *, status="queued", mode="agent", convo=None, owner=None):
    owner = owner or env["user"]
    convo = convo or conversation(env, mode, owner=owner)
    with project_scope(
        ProjectScope((convo.project_tag_id,), convo.project_tag_id, owner.id)
    ):
        return AgentRun.objects.create(
            owner=owner,
            conversation=convo,
            model="mock",
            prompt="测试一个独立问题",
            idempotency_key="unique-run-key",
            status=status,
        )


def submit(env, convo, *, key="submit-question", client=None):
    return (client or env["client"]).post(
        f"/api/agent/conversations/{convo.id}/runs/",
        json.dumps(
            {"model": "mock", "prompt": "请简短介绍遥感", "idempotencyKey": key}
        ),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(convo.project_tag_id),
    )


def waiting_question(env, *, review=False):
    run = make_run(env, status="running")
    card = question()
    if review:
        card.update(
            kind="review",
            questions=[
                {
                    "key": "approval",
                    "label": "是否批准？",
                    "type": "single",
                    "required": True,
                    "options": [
                        {"value": "approve", "label": "批准"},
                        {"value": "reject", "label": "拒绝"},
                    ],
                }
            ],
        )
    with project_scope(env["scope"]):
        wait_for_answer(
            run,
            card,
            {"messages": [{"role": "user", "content": run.prompt}], "currentIndex": 0},
        )
    run.refresh_from_db()
    return run


def test_three_mixed_mode_questions_are_admitted_fourth_is_409_and_retries_are_idempotent(
    setup_agent,
):
    env = setup_agent
    convos = [conversation(env, mode) for mode in ["chat", "agent", "chat", "agent"]]
    admitted = [submit(env, convo) for convo in convos[:3]]
    assert [result.status_code for result in admitted] == [202, 202, 202]
    fourth = submit(env, convos[3])
    assert fourth.status_code == 409
    assert "3个" in fourth.json()["detail"] and "权限" not in fourth.json()["detail"]
    retry = submit(env, convos[0])
    assert retry.status_code == 202 and retry.json()["id"] == admitted[0].json()["id"]
    assert (
        AgentRun._base_manager.filter(owner=env["user"], status__in=ACTIVE).count() == 3
    )


@pytest.mark.parametrize(
    "status",
    ["queued", "running", "waiting_input", "waiting_review", "waiting_compute"],
)
def test_same_conversation_remains_serial_for_active_and_waiting_tasks(
    setup_agent, status
):
    env = setup_agent
    run = make_run(env, status=status)
    result = submit(env, run.conversation)
    assert result.status_code == 409, result.content
    assert "当前会话" in result.json()["detail"]
    assert AgentRun._base_manager.filter(conversation=run.conversation).count() == 1


@pytest.mark.parametrize(
    "status", ["waiting_input", "waiting_review", "waiting_compute"]
)
def test_waiting_tasks_release_account_model_slots(setup_agent, status):
    env = setup_agent
    for _ in range(3):
        make_run(env, status=status)
    admitted = [
        submit(env, conversation(env, mode)) for mode in ["chat", "agent", "chat"]
    ]
    assert [result.status_code for result in admitted] == [202, 202, 202]
    assert submit(env, conversation(env)).status_code == 409


def test_account_limit_spans_projects_but_other_accounts_have_their_own_slots(
    setup_agent,
):
    env = setup_agent
    for project_id in [1, env["project"].id, 1]:
        assert submit(env, conversation(env, project_id=project_id)).status_code == 202
    assert submit(env, conversation(env)).status_code == 409
    other = env["other"]
    other.user_permissions.set(env["user"].user_permissions.all())
    ProjectMembership.objects.create(project=env["project"], user=other)
    client = Client()
    client.force_login(other)
    for mode in ["chat", "agent", "chat"]:
        assert (
            submit(env, conversation(env, mode, owner=other), client=client).status_code
            == 202
        )
    assert AgentRun._base_manager.filter(status__in=ACTIVE).count() == 6


def test_answer_resume_shares_three_slots_preserves_full_card_and_is_idempotent(
    setup_agent,
):
    env = setup_agent
    waiting = waiting_question(env)
    active = [make_run(env) for _ in range(2)]
    result, payload = respond(env, waiting)
    assert result.status_code == 202, result.content
    retry = env["client"].post(
        f"/api/agent/runs/{waiting.id}/interaction/",
        json.dumps(payload),
        content_type="application/json",
        **env["header"],
    )
    assert retry.status_code == 202
    other_waiting = waiting_question(env)
    blocked, blocked_payload = respond(env, other_waiting)
    assert blocked.status_code == 409 and "3个" in blocked.json()["detail"]
    other_waiting.refresh_from_db()
    assert other_waiting.status == "waiting_input"
    assert (
        other_waiting.interaction["status"] == "pending"
        and "answer" not in other_waiting.interaction
    )
    AgentRun._base_manager.filter(pk=active[0].id).update(status="succeeded")
    resumed = env["client"].post(
        f"/api/agent/runs/{other_waiting.id}/interaction/",
        json.dumps(blocked_payload),
        content_type="application/json",
        **env["header"],
    )
    assert resumed.status_code == 202
    assert AgentRun._base_manager.filter(status__in=ACTIVE).count() == 3
    assert (
        other_waiting.events.filter(kind="interaction", text__contains="已收到").count()
        == 1
    )


@pytest.mark.parametrize("action", ["cancel", "reject"])
def test_full_slots_never_prevent_cancelling_or_rejecting_a_waiting_plan(
    setup_agent, action
):
    env = setup_agent
    run = waiting_question(env, review=action == "reject")
    for _ in range(3):
        make_run(env)
    changes = (
        {"answers": {"approval": "reject"}}
        if action == "reject"
        else {"action": "cancel", "answers": {}}
    )
    result, _ = respond(env, run, **changes)
    assert result.status_code == 200, result.content
    run.refresh_from_db()
    assert run.status == "cancelled" and run.cancel_requested
    assert AgentRun._base_manager.filter(status__in=ACTIVE).count() == 3


def test_finished_compute_waits_for_a_slot_then_resumes_once_without_losing_result(
    setup_agent,
):
    env = setup_agent
    env["user"].user_permissions.add(
        *Permission.objects.filter(codename="view_own_task")
    )
    run = make_run(env, status="waiting_compute")
    with project_scope(env["scope"]):
        algorithm = AlgorithmResource.objects.create(
            identifier="resume-result", name="结果续接", created_by=env["user"]
        )
        version = AlgorithmVersion.objects.create(
            algorithm=algorithm,
            version="1.0.0",
            status="published",
            manifest={},
            checksum="a" * 64,
        )
        task = ComputeTask.objects.create(
            owner=env["user"],
            version=version,
            name="已完成的真实任务记录",
            status="succeeded",
            idempotency_key="finished-result",
            request_hash="a" * 64,
        )
        run.execution_state = {
            "messages": [{"role": "user", "content": run.prompt}],
            "taskIds": [str(task.id)],
        }
        run.save(update_fields=["execution_state"])
    active = [make_run(env) for _ in range(3)]
    resume_compute()
    run.refresh_from_db()
    assert run.status == "waiting_compute" and "等待处理名额" in run.detail
    assert not run.evidence and run.execution_state["taskIds"] == [str(task.id)]
    AgentRun._base_manager.filter(pk=active[0].id).update(status="succeeded")
    resume_compute()
    resume_compute()
    run.refresh_from_db()
    assert run.status == "queued" and run.execution_state["taskIds"] == []
    assert len(run.evidence) == 1 and run.evidence[0]["tool"] == "get_compute_task"
    assert run.events.filter(kind="continuation").count() == 1
    assert AgentRun._base_manager.filter(status__in=ACTIVE).count() == 3


@pytest.mark.django_db(transaction=True)
def test_concurrent_mixed_mode_submissions_atomically_admit_exactly_three(setup_agent):
    env = setup_agent
    convos = [conversation(env, mode) for mode in ["chat", "agent", "chat", "agent"]]
    barrier = threading.Barrier(4)

    def attempt(convo):
        close_old_connections()
        try:
            user = get_user_model().objects.get(pk=env["user"].id)
            request = RequestFactory().post("/api/agent/conversations/unused/runs/")
            request.user = user
            barrier.wait(timeout=15)
            with project_scope(
                ProjectScope((convo.project_tag_id,), convo.project_tag_id, user.id)
            ):
                try:
                    result = submit_value(
                        request,
                        convo,
                        {
                            "model": "mock",
                            "prompt": "并发独立问题",
                            "idempotencyKey": "concurrent-question",
                        },
                        available_models=[
                            {
                                "alias": "mock",
                                "status": "online",
                                "contextWindowTokens": 32768,
                            }
                        ],
                    )
                    return result.status_code
                except (ApiProblem, ComputeError) as exc:
                    return exc.status
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(attempt, convos))
    assert sorted(statuses) == [202, 202, 202, 409]
    assert (
        AgentRun._base_manager.filter(owner=env["user"], status__in=ACTIVE).count() == 3
    )
