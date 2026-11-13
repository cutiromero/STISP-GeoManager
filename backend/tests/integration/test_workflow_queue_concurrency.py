"""A long model call must not monopolize the durable workflow scheduler."""

import threading
from collections import Counter

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections

from apps.agent import workflow_worker
from apps.agent.models import AgentWorkflow, AgentRuntime


@pytest.mark.django_db(transaction=True)
@pytest.mark.efficiency
@pytest.mark.parametrize("long_status", ["queued", "waiting_compute"])
def test_another_user_starts_while_a_workflow_or_compute_resume_waits_for_model(
    monkeypatch, long_status
):
    first_user = get_user_model().objects.create(username="long_model")
    second_user = get_user_model().objects.create(username="other_task")
    first = AgentWorkflow.objects.create(
        owner=first_user, goal="长模型响应", status=long_status, idempotency_key="long"
    )
    entered, second_started, release, stop = (threading.Event() for _ in range(4))
    calls = Counter()
    errors = []

    def task(workflow_id):
        calls[workflow_id] += 1
        if workflow_id == first.pk:
            entered.set()
            assert release.wait(10)
        else:
            second_started.set()
            assert release.wait(10)

    monkeypatch.setattr(workflow_worker, "run_workflow", task)
    monkeypatch.setattr(
        workflow_worker, "resume_waiting", lambda *, workflow_id=None: task(workflow_id)
    )

    def serve():
        try:
            workflow_worker.serve(stop)
        except Exception as error:
            errors.append(error)
        finally:
            close_old_connections()

    worker = threading.Thread(target=serve)
    worker.start()
    try:
        assert entered.wait(6)
        second = AgentWorkflow.objects.create(
            owner=second_user, goal="其他用户的任务", idempotency_key="second"
        )
        assert second_started.wait(6), "长模型调用挡住了其他用户的排队任务"
        assert not release.is_set()
        assert calls == {first.pk: 1, second.pk: 1}
    finally:
        stop.set()
        release.set()
        worker.join(6)
    assert not worker.is_alive() and not errors
    assert AgentRuntime.objects.filter(name="workflow-worker").exists()
