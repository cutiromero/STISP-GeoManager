import hashlib
import json
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.agent.models import AgentRun, AgentWorkflow, AgentWorkflowStep, Conversation
from apps.catalog.models import DataResource, ShareInvitation, WorkspaceScene
from apps.compute.models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeTask,
    ComputeInput,
    ComputeOutput,
    ComputeImport,
)
from apps.core.storage import app_path, table_data_path
from apps.projects.context import project_scope
from .test_agent import setup_agent

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def generated(setup_agent, transactional_db):
    s = setup_agent
    s["user"].user_permissions.add(
        Permission.objects.get(
            content_type__app_label="catalog", codename="delete_dataresource"
        )
    )
    with project_scope(s["scope"]):
        algorithm = AlgorithmResource.objects.create(
            identifier="conversation-test", name="测试", created_by=s["user"]
        )
        version = AlgorithmVersion.objects.create(
            algorithm=algorithm, version="1", checksum="x", package_path="x"
        )
        task = ComputeTask.objects.create(
            owner=s["user"],
            version=version,
            name="任务",
            status="succeeded",
            idempotency_key="cleanup-task",
            request_hash="x",
        )
        ComputeInput.objects.create(task=task, key="source", resource=s["resource"])
        workflow = AgentWorkflow.objects.create(
            owner=s["user"],
            goal="test",
            model="mock",
            status="succeeded",
            idempotency_key="cleanup-workflow",
        )
        AgentWorkflowStep.objects.create(
            workflow=workflow, sequence=1, compute_task_id=task.pk
        )
        run = AgentRun.objects.create(
            conversation=s["conversation"],
            owner=s["user"],
            model="mock",
            status="succeeded",
            research_workflow=workflow,
            idempotency_key="cleanup-run",
        )
        source = table_data_path("original.txt")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("original")
        result_path = table_data_path("result.txt")
        result_path.write_text("result")
        resource = DataResource.objects.create(
            name="任务成果",
            code="conversation-result",
            data_type="document",
            file_format="TXT",
            storage_path="table/result.txt",
            maintainer=s["user"],
            is_compute_result=True,
            size_bytes=6,
        )
        relative = (
            f"projects/{s['project'].pk}/compute/outputs/{task.pk}/attempt/result.txt"
        )
        output_path = app_path(relative)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("result")
        output = ComputeOutput.objects.create(
            task=task,
            key="result",
            label="成果",
            kind="document",
            file_name="result.txt",
            path=relative,
            size_bytes=6,
            checksum=hashlib.sha256(b"result").hexdigest(),
        )
        ComputeImport.objects.create(
            output=output,
            requested_by=s["user"],
            resource=resource,
            status="ready",
            name="任务成果",
        )
        workflow.result_resource_ids = [resource.pk]
        workflow.save(update_fields=["result_resource_ids"])
    return {
        **s,
        "task": task,
        "workflow": workflow,
        "run": run,
        "result": resource,
        "output": output,
        "sourcePath": source,
        "resultPath": result_path,
        "outputPath": output_path,
    }


def preview(s):
    return s["client"].get(
        f"/api/agent/conversations/{s['conversation'].pk}/deletion-preview/",
        **s["header"],
    )


def remove(s, data=None):
    return s["client"].delete(
        f"/api/agent/conversations/{s['conversation'].pk}/",
        json.dumps(data or {}),
        content_type="application/json",
        **s["header"],
    )


def confirmed(s):
    response = preview(s)
    assert response.status_code == 200, response.content
    return {
        "deleteGeneratedData": True,
        "confirmationToken": response.json()["confirmationToken"],
    }


def test_default_deletion_preserves_generated_data(generated):
    s = generated
    response = remove(s)
    assert response.status_code == 200, response.content
    assert "cleanup" not in response.json()
    assert (
        s["sourcePath"].exists()
        and s["resultPath"].exists()
        and s["outputPath"].exists()
    )
    assert DataResource._base_manager.filter(pk=s["result"].pk).exists()


def test_opt_in_deletes_owned_outputs_and_keeps_originals_and_history(generated):
    s = generated
    p = preview(s).json()
    assert (p["resourceCount"], p["outputCount"], p["estimatedBytes"]) == (1, 1, 12)
    assert s["resultPath"].exists(), "preview must be read only"
    response = remove(s, confirmed(s))
    assert response.status_code == 200, response.content
    assert response.json()["cleanup"] == {
        "deletedResources": 1,
        "deletedOutputs": 1,
        "retainedResources": 0,
        "retainedOutputs": 0,
        "failedItems": 0,
    }
    assert not s["resultPath"].exists() and not s["outputPath"].exists()
    assert s["sourcePath"].exists()
    assert not DataResource._base_manager.filter(pk=s["result"].pk).exists()
    s["output"].refresh_from_db()
    assert s["output"].expired
    s["workflow"].refresh_from_db()
    assert (
        s["workflow"].plan["deletedResources"][0]["formerResourceId"] == s["result"].pk
    )
    assert ComputeTask._base_manager.filter(pk=s["task"].pk).exists()


@pytest.mark.parametrize("reference", ["conversation", "compute", "workspace"])
def test_data_used_elsewhere_is_retained(generated, reference):
    s = generated
    with project_scope(s["scope"]):
        if reference == "conversation":
            c = Conversation.objects.create(owner=s["user"], mode="agent")
            AgentRun.objects.create(
                conversation=c,
                owner=s["user"],
                model="mock",
                status="succeeded",
                resource_ids=[s["result"].pk],
                idempotency_key="other",
            )
        elif reference == "compute":
            other = ComputeTask.objects.create(
                owner=s["user"],
                version=s["task"].version,
                name="后续计算",
                status="succeeded",
                idempotency_key="other",
                request_hash="x",
            )
            ComputeInput.objects.create(task=other, key="source", resource=s["result"])
        else:
            WorkspaceScene.objects.create(
                owner=s["user"], name="工程", snapshot={"resourceIds": [s["result"].pk]}
            )
    p = preview(s).json()
    assert (p["resourceCount"], p["outputCount"], p["retainedCount"]) == (0, 0, 1)
    response = remove(s, confirmed(s))
    assert response.status_code == 200, response.content
    assert s["resultPath"].exists() and s["outputPath"].exists()


@pytest.mark.parametrize("change", ["revision", "reference"])
def test_stale_confirmation_does_not_delete_conversation(generated, change):
    s = generated
    value = confirmed(s)
    with project_scope(s["scope"]):
        if change == "revision":
            s["result"].updated_at = timezone.now()
            s["result"].save(update_fields=["updated_at"])
        else:
            WorkspaceScene.objects.create(
                owner=s["user"],
                name="新工程",
                snapshot={"resourceIds": [s["result"].pk]},
            )
    response = remove(s, value)
    assert response.status_code == 409, response.content
    assert Conversation._base_manager.filter(pk=s["conversation"].pk).exists()
    assert s["resultPath"].exists() and s["outputPath"].exists()


def test_requires_valid_token_and_existing_delete_permission(generated):
    s = generated
    assert (
        remove(
            s, {"deleteGeneratedData": True, "confirmationToken": "fake"}
        ).status_code
        == 409
    )
    s["user"].user_permissions.remove(
        Permission.objects.get(
            content_type__app_label="catalog", codename="delete_dataresource"
        )
    )
    p = preview(s).json()
    assert (p["resourceCount"], p["outputCount"], p["retainedCount"]) == (0, 0, 1)
    assert remove(s, confirmed(s)).status_code == 200
    assert s["resultPath"].exists() and s["outputPath"].exists()


@pytest.mark.parametrize("status", ["running", "waiting_compute", "waiting_review"])
def test_pending_runs_prevent_deletion(generated, status):
    s = generated
    value = confirmed(s)
    s["run"].status = status
    s["run"].save(update_fields=["status"])
    assert remove(s, value).status_code == 409
    assert s["outputPath"].exists()


def test_cleanup_failure_is_reported_without_deleting_protected_files(generated):
    s = generated
    value = confirmed(s)
    with patch(
        "apps.agent.conversation_cleanup.delete_resource",
        return_value={"status": "failed"},
    ):
        response = remove(s, value)
    assert response.status_code == 200
    assert response.json()["cleanup"]["failedItems"] == 1
    assert s["resultPath"].exists() and s["outputPath"].exists()


def test_preview_and_deletion_are_owner_and_project_scoped(generated):
    s = generated
    s["client"].force_login(s["admin"])
    assert preview(s).status_code == 404
    assert (
        remove(
            s, {"deleteGeneratedData": True, "confirmationToken": "fake"}
        ).status_code
        == 404
    )
    assert s["resultPath"].exists()


def test_unregistered_output_can_be_cleaned_without_touching_input(generated):
    s = generated
    with project_scope(s["scope"]):
        ComputeImport.objects.filter(output=s["output"]).delete()
    response = remove(s, confirmed(s))
    assert response.status_code == 200
    assert response.json()["cleanup"]["deletedOutputs"] == 1
    assert not s["outputPath"].exists()
    assert s["sourcePath"].exists() and s["resultPath"].exists()


def test_reference_added_after_confirmation_is_rechecked_during_cleanup(generated):
    from apps.agent.conversation_cleanup import cleanup_generated_data

    s = generated
    value = confirmed(s)

    def reuse_then_cleanup(plan, request):
        WorkspaceScene.objects.create(
            owner=s["user"],
            name="刚保存的工程",
            snapshot={"resourceIds": [s["result"].pk]},
        )
        return cleanup_generated_data(plan, request)

    with patch(
        "apps.agent.conversation_cleanup.cleanup_generated_data",
        side_effect=reuse_then_cleanup,
    ):
        response = remove(s, value)
    assert response.status_code == 200
    assert response.json()["cleanup"]["retainedResources"] == 1
    assert response.json()["cleanup"]["retainedOutputs"] == 1
    assert s["resultPath"].exists() and s["outputPath"].exists()


def test_client_cannot_expand_cleanup_scope(generated):
    s = generated
    value = {**confirmed(s), "resourceIds": [s["resource"].pk]}
    assert remove(s, value).status_code == 400
    assert s["sourcePath"].exists() and s["resultPath"].exists()


@pytest.mark.parametrize("status", ["queued", "running"])
def test_unregistered_output_is_retained_during_import(generated, status):
    s = generated
    with project_scope(s["scope"]):
        ComputeImport.objects.filter(output=s["output"]).update(
            resource=None, status=status
        )
    p = preview(s).json()
    assert p["outputCount"] == 0
    response = remove(s, confirmed(s))
    assert response.status_code == 200
    assert s["outputPath"].exists()


@pytest.mark.efficiency
def test_unrelated_conversation_count_does_not_add_per_run_queries(generated):
    s = generated
    with CaptureQueriesContext(connection) as baseline:
        assert preview(s).status_code == 200
    with project_scope(s["scope"]):
        other = Conversation.objects.create(owner=s["user"], mode="agent")
        AgentRun.objects.bulk_create(
            [
                AgentRun(
                    conversation=other,
                    owner=s["user"],
                    model="mock",
                    status="succeeded",
                    idempotency_key=f"unrelated-{i}",
                )
                for i in range(20)
            ]
        )
    with CaptureQueriesContext(connection) as expanded:
        result = preview(s)
    assert result.status_code == 200
    assert result.json()["resourceCount"] == 1
    assert len(expanded) <= len(baseline) + 2


def test_concurrent_already_deleted_conversation_returns_not_found(generated):
    s = generated
    conversation = s["conversation"]
    identity = conversation.pk
    conversation.delete()
    conversation.pk = identity
    with patch("apps.agent.views.own_conversation", return_value=conversation):
        response = remove(s)
    assert response.status_code == 404
    assert s["resultPath"].exists() and s["outputPath"].exists()


def test_shared_compute_output_and_its_imported_result_are_retained(generated):
    s = generated
    with project_scope(s["scope"]):
        ShareInvitation.objects.create(
            sender=s["user"],
            recipient=s["other"],
            kind=ShareInvitation.Kind.COMPUTE_OUTPUT,
            object_id=s["output"].pk,
            object_name="共享结果",
            request_key="share-cleanup",
            request_hash="test",
        )
    p = preview(s).json()
    assert (p["resourceCount"], p["outputCount"], p["retainedCount"]) == (0, 0, 1)
    assert remove(s, confirmed(s)).status_code == 200
    assert s["outputPath"].exists() and s["resultPath"].exists()
