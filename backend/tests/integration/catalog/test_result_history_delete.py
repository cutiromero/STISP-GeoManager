import json
from unittest.mock import patch

from apps.agent.models import (
    AgentComputeFollowup,
    AgentCheckpoint,
    AgentWorkflow,
    AgentWorkflowStep,
    AgentRun,
    Conversation,
)
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from apps.audit.models import OperationLog
from apps.catalog.models import (
    DataResource,
    DictionaryItem,
    ResultArtifact,
    WorkspaceScene,
)
from apps.compute.models import ComputeImport, ComputeInput, ComputeOutput
from apps.compute.serializers import output_data, task_data
from apps.compute.services import task_action
from apps.compute.packages import ComputeError
from apps.projects.context import ProjectScope, project_scope

from .test_resource_delete import ResourceDeleteFixture


class HistoricalResultDeletionTests(ResourceDeleteFixture):
    def preview(self, ids):
        return self.client.post(
            "/api/catalog/resources/delete-preview/",
            json.dumps({"resourceIds": ids}),
            content_type="application/json",
            HTTP_X_PROJECT_ID="1",
        )

    def confirmed_delete(self, ids, token):
        return self.client.post(
            "/api/catalog/resources/delete/",
            json.dumps(
                {
                    "resourceIds": ids,
                    "confirmed": True,
                    "historyConfirmationToken": token,
                }
            ),
            content_type="application/json",
            HTTP_X_PROJECT_ID="1",
        )

    def workflow(self, item, status="succeeded"):
        return AgentWorkflow.objects.create(
            owner=self.user,
            goal="历史纠偏",
            model="test",
            idempotency_key=f"delete-{item.id}",
            resource_ids=[item.id],
            result_resource_ids=[item.id],
            plan={"inputs": {"map": item.id}, "report": "保留历史结论"},
            plan_hash="approved-plan-hash",
            status=status,
        )

    def test_confirmation_detaches_terminal_history_and_keeps_evidence(self):
        item = self.resource(is_compute_result=True, source="compute-output:sample")
        task = self.task(item)
        workflow = self.workflow(item)
        step = AgentWorkflowStep.objects.create(
            workflow=workflow, sequence=1, input_refs={"resourceId": item.id}
        )
        checkpoint = AgentCheckpoint.objects.create(
            workflow=workflow,
            node="report",
            state={"resourceId": item.id},
            state_hash="x",
        )
        output = ComputeOutput.objects.create(
            task=task,
            key="out",
            label="结果",
            kind="table",
            file_name="out.csv",
            path="out.csv",
            size_bytes=1,
            checksum="real-checksum",
        )
        record = ComputeImport.objects.create(
            output=output,
            requested_by=self.user,
            name=item.name,
            resource=item,
            status="ready",
        )
        preview = self.preview([item.id]).json()
        self.assertEqual(preview["items"][0]["status"], "confirmation_required")
        self.assertEqual(preview["items"][0]["historyReferenceCount"], 3)
        self.assertTrue(DataResource.objects.filter(pk=item.id).exists())
        self.assertEqual(self.delete([item.id]).json()["deletedCount"], 0)
        result = self.confirmed_delete([item.id], preview["confirmationToken"]).json()
        self.assertEqual(result["deletedIds"], [item.id])
        self.assertFalse(DataResource.objects.filter(pk=item.id).exists())
        record.refresh_from_db()
        workflow.refresh_from_db()
        entry = ComputeInput.objects.get(task=task)
        self.assertIsNone(entry.resource_id)
        self.assertEqual(entry.snapshot["deletedResource"]["name"], item.name)
        self.assertEqual(entry.snapshot["deletedResource"]["source"], item.source)
        self.assertEqual((record.status, record.resource_id), ("deleted", None))
        self.assertEqual(workflow.resource_ids, [])
        self.assertEqual(workflow.result_resource_ids, [])
        self.assertEqual(workflow.plan["deletedResources"][0]["status"], "deleted")
        self.assertEqual(workflow.plan_hash, "approved-plan-hash")
        step.refresh_from_db()
        checkpoint.refresh_from_db()
        self.assertEqual(step.input_refs, {"resourceId": item.id})
        self.assertEqual(checkpoint.state, {"resourceId": item.id})
        self.assertTrue(ComputeOutput.objects.filter(pk=output.id).exists())
        self.assertIn(item.source, OperationLog.objects.get(target_id=item.id).message)
        self.assertIsNone(task_data(task)["inputs"][0]["resourceId"])
        self.assertEqual(output_data(output)["importStatus"], "deleted")
        self.assertEqual(output_data(output)["mapUrl"], "")
        self.assertEqual(
            self.confirmed_delete([item.id], preview["confirmationToken"]).json()[
                "items"
            ][0]["status"],
            "not_found",
        )
        self.assertEqual(OperationLog.objects.filter(target_id=item.id).count(), 1)

    def test_active_compute_or_workflow_is_never_detached(self):
        item = self.resource(is_compute_result=True)
        task = self.task(item)
        task.status = "running"
        task.save()
        preview = self.preview([item.id]).json()
        self.assertEqual(preview["items"][0]["status"], "blocked")
        self.assertEqual(
            self.confirmed_delete([item.id], preview["confirmationToken"]).json()[
                "deletedCount"
            ],
            0,
        )
        task.status = "succeeded"
        task.save()
        workflow = self.workflow(item, status="waiting_approval")
        preview = self.preview([item.id]).json()
        self.assertEqual(preview["items"][0]["status"], "blocked")
        self.assertEqual(
            self.confirmed_delete([item.id], preview["confirmationToken"]).json()[
                "deletedCount"
            ],
            0,
        )
        workflow.refresh_from_db()
        self.assertEqual(workflow.resource_ids, [item.id])

    def test_original_upload_history_keeps_protection(self):
        item = self.resource()
        self.task(item)
        self.workflow(item)
        preview = self.preview([item.id]).json()
        self.assertEqual(preview["items"][0]["status"], "blocked")
        self.assertEqual(
            self.confirmed_delete([item.id], preview["confirmationToken"]).json()[
                "deletedCount"
            ],
            0,
        )

    def test_reference_changes_require_new_preview(self):
        item = self.resource(is_compute_result=True)
        self.task(item)
        preview = self.preview([item.id]).json()
        self.workflow(item)
        result = self.confirmed_delete([item.id], preview["confirmationToken"]).json()
        self.assertEqual(result["items"][0]["status"], "blocked")
        self.assertIn("已变化", result["items"][0]["detail"])
        self.assertTrue(ComputeInput.objects.filter(resource=item).exists())

    def test_expired_tampered_and_changed_selection_tokens_fail(self):
        item = self.resource(is_compute_result=True)
        self.task(item)
        token = self.preview([item.id]).json()["confirmationToken"]
        self.assertEqual(self.confirmed_delete([item.id], token + "x").status_code, 409)
        self.assertEqual(
            self.confirmed_delete([item.id, 12345], token).status_code, 409
        )
        with patch("django.core.signing.time.time", return_value=10**12):
            self.assertEqual(self.confirmed_delete([item.id], token).status_code, 409)
        self.assertTrue(DataResource.objects.filter(pk=item.id).exists())

    def test_shared_workflow_batch_is_not_invalidated_by_its_first_deletion(self):
        first = self.resource("first", is_compute_result=True)
        second = self.resource("second", is_compute_result=True)
        workflow = self.workflow(first)
        workflow.resource_ids.append(second.id)
        workflow.save()
        token = self.preview([first.id, second.id]).json()["confirmationToken"]
        result = self.confirmed_delete([first.id, second.id], token).json()
        self.assertEqual(result["deletedIds"], [first.id, second.id])
        workflow.refresh_from_db()
        self.assertEqual(len(workflow.plan["deletedResources"]), 2)

    def test_saved_map_and_result_remain_hard_protected(self):
        item = self.resource(is_compute_result=True)
        self.workflow(item)
        workspace = WorkspaceScene.objects.create(
            owner=self.user,
            name="保留工程",
            kind="project",
            snapshot={"resourceId": item.id},
        )
        preview = self.preview([item.id]).json()
        self.assertEqual(preview["items"][0]["status"], "blocked")
        self.assertEqual(
            self.confirmed_delete([item.id], preview["confirmationToken"]).json()[
                "deletedCount"
            ],
            0,
        )
        workspace.delete()
        category = DictionaryItem.objects.create(
            dict_type="data_category", code="result-history", name="成果"
        )
        artifact = ResultArtifact.objects.create(
            name="已发布成果", owner=self.user, category=category
        )
        artifact.related_resources.add(item)
        self.assertEqual(
            self.preview([item.id]).json()["items"][0]["status"], "blocked"
        )

    def test_deleted_input_cannot_retry(self):
        item = self.resource(is_compute_result=True)
        task = self.task(item)
        task.status = "failed"
        task.save()
        token = self.preview([item.id]).json()["confirmationToken"]
        self.assertEqual(
            self.confirmed_delete([item.id], token).json()["deletedCount"], 1
        )
        with project_scope(ProjectScope((1,), 1)):
            with patch("apps.compute.access.task_access"):
                with self.assertRaisesRegex(ComputeError, "已删除"):
                    task_action(task, self.user, "retry")

    def test_cleanup_and_audit_roll_back_on_storage_error(self):
        item = self.resource(is_compute_result=True)
        self.task(item)
        workflow = self.workflow(item)
        token = self.preview([item.id]).json()["confirmationToken"]
        with patch(
            "apps.catalog.resource_management.ResourceStorageDeletion",
            side_effect=OSError("unavailable"),
        ):
            self.assertEqual(
                self.confirmed_delete([item.id], token).json()["items"][0]["status"],
                "failed",
            )
        workflow.refresh_from_db()
        self.assertTrue(ComputeInput.objects.filter(resource=item).exists())
        self.assertNotIn("deletedResources", workflow.plan)
        self.assertEqual(OperationLog.objects.filter(target_id=item.id).count(), 0)

    def test_preview_respects_login_delete_privacy_and_token_owner(self):
        item = self.resource(is_compute_result=True, owner_only=True)
        self.task(item)
        token = self.preview([item.id]).json()["confirmationToken"]
        self.client.logout()
        self.assertEqual(self.preview([item.id]).status_code, 401)
        other = get_user_model().objects.create_user(
            "other-cleanup", password="pass12345"
        )
        self.client.force_login(other)
        self.assertEqual(self.preview([item.id]).status_code, 403)
        other.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="catalog", codename="delete_dataresource"
            )
        )
        response = self.preview([item.id]).json()
        self.assertEqual(response["items"][0]["status"], "not_found")
        self.assertIsNone(response["items"][0]["name"])
        self.assertEqual(response["items"][0]["historyReferenceCount"], 0)
        self.assertEqual(self.confirmed_delete([item.id], token).status_code, 409)

    def test_active_import_and_new_live_reference_block_previously_reviewed_deletion(
        self,
    ):
        item = self.resource(is_compute_result=True)
        task = self.task(item)
        token = self.preview([item.id]).json()["confirmationToken"]
        task.status = "queued"
        task.save()
        result = self.confirmed_delete([item.id], token).json()["items"][0]
        self.assertEqual(result["status"], "blocked")
        task.status = "succeeded"
        task.save()
        output = ComputeOutput.objects.create(
            task=task,
            key="queued",
            label="out",
            kind="table",
            file_name="out.csv",
            path="out.csv",
            size_bytes=1,
            checksum="x",
        )
        ComputeImport.objects.create(
            output=output,
            requested_by=self.user,
            name=item.name,
            resource=item,
            status="running",
        )
        preview = self.preview([item.id]).json()
        self.assertEqual(preview["items"][0]["status"], "blocked")
        self.assertIn("尚未结束", preview["items"][0]["detail"])

    def test_waiting_conversation_is_still_a_live_dependency(self):
        item = self.resource(is_compute_result=True)
        self.task(item)
        conversation = Conversation.objects.create(owner=self.user, mode="agent")
        run = AgentRun.objects.create(
            owner=self.user,
            conversation=conversation,
            model="test",
            prompt="继续分析",
            idempotency_key="cleanup-waiting",
            status="waiting_input",
            resource_ids=[item.id],
        )
        preview = self.preview([item.id]).json()
        self.assertEqual(preview["items"][0]["status"], "blocked")
        self.assertIn("等待继续", preview["items"][0]["detail"])
        run.status = "cancelled"
        run.save()
        self.assertEqual(
            self.preview([item.id]).json()["items"][0]["status"],
            "confirmation_required",
        )

    def test_previously_blocked_or_inaccessible_selection_is_not_silently_added(self):
        item = self.resource(is_compute_result=True)
        task = self.task(item)
        task.status = "running"
        task.save()
        token = self.preview([item.id]).json()["confirmationToken"]
        task.status = "succeeded"
        task.save()
        result = self.confirmed_delete([item.id], token).json()["items"][0]
        self.assertEqual(result["status"], "blocked")
        self.assertIn("未列入", result["detail"])
        self.assertTrue(ComputeInput.objects.filter(resource=item).exists())

    def test_ready_output_stays_protected_during_model_continuation(self):
        original = self.resource(code="original")
        result = self.resource(code="result", is_compute_result=True)
        task = self.task(original)
        output = ComputeOutput.objects.create(
            task=task,
            key="output",
            label="结果",
            kind="table",
            file_name="out.csv",
            path="out.csv",
            size_bytes=1,
            checksum="x",
        )
        ComputeImport.objects.create(
            output=output,
            requested_by=self.user,
            name=result.name,
            resource=result,
            status="ready",
        )
        conversation = Conversation.objects.create(owner=self.user, mode="agent")
        run = AgentRun.objects.create(
            owner=self.user,
            conversation=conversation,
            model="test",
            prompt="解释结果",
            idempotency_key="continue-reading",
            status="running",
        )
        AgentComputeFollowup.objects.create(run=run, task=task, status="completed")
        preview = self.preview([result.id]).json()["items"][0]
        self.assertEqual(preview["status"], "blocked")
        self.assertIn("智能体", preview["detail"])
        run.status = "succeeded"
        run.save(update_fields=["status"])
        self.assertEqual(
            self.preview([result.id]).json()["items"][0]["status"],
            "confirmation_required",
        )
