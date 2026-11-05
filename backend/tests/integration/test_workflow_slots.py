import json
import uuid

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from apps.agent.models import AgentRun, AgentWorkflow, Conversation
from apps.agent.workflow_creation import create_workflow
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_workflow_pause import prepared, control

pytestmark = pytest.mark.django_db
pytest_plugins = ["tests.integration.test_demo_workflow"]


def create(env, status):
    return AgentWorkflow.objects.create(
        owner=env["owner"],
        model="mock",
        goal="等待地质图复查",
        idempotency_key=uuid.uuid4().hex,
        status=status,
    )


@pytest.mark.parametrize("status", ["waiting_approval", "paused"])
def test_parked_workflows_coexist_and_do_not_block_creation(demo, status):
    with project_scope(
        ProjectScope((demo["project"].id,), demo["project"].id, demo["owner"].id)
    ):
        parked = [create(demo, status), create(demo, status)]
        fresh = create_workflow(
            demo["owner"],
            demo["project"].id,
            {
                "goal": "开始新的分析",
                "model": "mock",
                "idempotencyKey": uuid.uuid4().hex,
            },
        )
        assert fresh.status == "queued"
        for workflow in parked:
            workflow.refresh_from_db()
            assert workflow.status == status
        with pytest.raises(IntegrityError), transaction.atomic():
            create(demo, "running")


@pytest.mark.parametrize("status", ["queued", "running", "waiting_compute"])
def test_computing_creation_conflict_identifies_task_and_conversation(demo, status):
    with project_scope(
        ProjectScope((demo["project"].id,), demo["project"].id, demo["owner"].id)
    ):
        blocker = create(demo, status)
        conversation = Conversation.objects.create(
            owner=demo["owner"], mode="agent", title="研究区复查"
        )
        AgentRun.objects.create(
            owner=demo["owner"],
            conversation=conversation,
            model="mock",
            idempotency_key="source-run",
            research_workflow=blocker,
            status="succeeded",
        )
        response = demo["client"].post(
            "/api/agent/workflows/",
            json.dumps(
                {
                    "goal": "新任务",
                    "model": "mock",
                    "idempotencyKey": uuid.uuid4().hex,
                }
            ),
            content_type="application/json",
            HTTP_X_PROJECT_ID=str(demo["project"].id),
        )
        assert response.status_code == 409, response.content
        detail = response.json()["detail"]
        assert str(blocker.id) in detail and "研究区复查" in detail and "查看" in detail
        summary = (
            demo["client"]
            .get(
                "/api/agent/workflows/active/",
                HTTP_X_PROJECT_ID=str(demo["project"].id),
            )
            .json()
        )
        assert summary["item"]["conversationId"] == conversation.id
        assert summary["parked"] == []


@pytest.mark.parametrize("continuation", ["queued", "running", "waiting_compute"])
def test_parked_confirmation_and_resume_preserve_state_on_conflict_then_succeed(
    demo, continuation
):
    workflow = prepared(demo, execute=False)
    assert control(demo, workflow, "pause").json()["status"] == "paused"
    AgentWorkflow.objects.filter(pk=workflow.id).update(paused_from=continuation)
    with project_scope(
        ProjectScope((demo["project"].id,), demo["project"].id, demo["owner"].id)
    ):
        blocker = create(demo, "queued")
    response = control(demo, workflow, "resume")
    assert response.status_code == 409 and str(blocker.id) in response.json()["detail"]
    workflow.refresh_from_db()
    assert workflow.status == "paused" and workflow.pause_requested
    AgentWorkflow.objects.filter(pk=workflow.id).update(paused_from="waiting_approval")
    assert control(demo, workflow, "resume").json()["status"] == "waiting_approval"
    headers = {"HTTP_X_PROJECT_ID": str(demo["project"].id)}
    body = json.dumps({"planHash": workflow.plan_hash})
    response = demo["client"].post(
        f"/api/agent/workflows/{workflow.id}/confirm/",
        body,
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 409 and str(blocker.id) in response.json()["detail"]
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval" and not workflow.execute_operators
    assert control(demo, blocker, "cancel").status_code == 200
    response = demo["client"].post(
        f"/api/agent/workflows/{workflow.id}/confirm/",
        body,
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "queued"


def test_reject_and_cancel_parked_tasks_do_not_require_compute_slot(demo):
    workflow = prepared(demo, execute=False)
    with project_scope(
        ProjectScope((demo["project"].id,), demo["project"].id, demo["owner"].id)
    ):
        blocker = create(demo, "queued")
        parked = create(demo, "paused")
    response = demo["client"].post(
        f"/api/agent/workflows/{workflow.id}/confirm/",
        json.dumps({"planHash": workflow.plan_hash, "decision": "reject"}),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(demo["project"].id),
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "cancelled"
    assert control(demo, parked, "cancel").json()["status"] == "cancelled"
    blocker.refresh_from_db()
    assert blocker.status == "queued" and not blocker.cancel_requested


@pytest.mark.django_db(transaction=True)
def test_slot_migration_preserves_old_parked_data_and_allows_new_work(demo):
    before = ("agent", "0021_logic_configuration")
    after = ("agent", "0022_parked_workflow_slots")
    executor = MigrationExecutor(connection)
    try:
        executor.migrate([before])
        historical = executor.loader.project_state([before]).apps.get_model(
            "agent", "AgentWorkflow"
        )
        old = historical.objects.create(
            owner_id=demo["owner"].id,
            project_tag_id=demo["project"].id,
            model="mock",
            goal="旧复查确认",
            status="waiting_approval",
            idempotency_key="before-migration",
            plan={
                "phase": "review_results",
                "reviewOutputs": [{"key": "lithology", "outputId": 23}],
            },
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            historical.objects.create(
                owner_id=demo["owner"].id,
                project_tag_id=demo["project"].id,
                model="mock",
                goal="旧约束",
                status="queued",
                idempotency_key="old-conflict",
            )
        executor = MigrationExecutor(connection)
        executor.migrate([after])
        persisted = AgentWorkflow._base_manager.get(pk=old.id)
        assert persisted.goal == "旧复查确认" and persisted.status == "waiting_approval"
        assert persisted.plan == old.plan
        with project_scope(
            ProjectScope((demo["project"].id,), demo["project"].id, demo["owner"].id)
        ):
            create(demo, "paused")
            assert create(demo, "queued").status == "queued"
    finally:
        MigrationExecutor(connection).migrate([after])
