import sqlite3
import tempfile
from dataclasses import replace
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings

from apps.agent.models import AgentWorkflow, AgentWorkflowStep
from apps.catalog.models import DataResource
from apps.core.development_storage import clean_generated_data, original_state
from apps.core.storage import table_data_path


class DevelopmentStorageTests(TransactionTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.override = override_settings(
            PROJECT_CONFIG=replace(
                settings.PROJECT_CONFIG,
                app_data=root / "app",
                research_data_root=root / "research",
            )
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = get_user_model().objects.create_user("development-original-owner")

    def resource(self, name, *, generated=False, **values):
        return DataResource.objects.create(
            name=name,
            code=name,
            maintainer=self.user,
            data_type="table",
            file_format="SQLITE",
            storage_path=name,
            is_compute_result=generated,
            **values,
        )

    def test_generated_tables_deleted_while_original_table_and_shared_alias_survive(
        self,
    ):
        original = self.resource("original_values")
        generated = self.resource("calculated_values", generated=True)
        alias = self.resource("original_alias", generated=True)
        alias.storage_path = "original_values"
        alias.save(update_fields=["storage_path"])
        database = table_data_path("data.sqlite")
        database.parent.mkdir(parents=True)
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE original_values (name TEXT,value REAL)")
            db.execute("INSERT INTO original_values VALUES (?,?)", ("原始观测", 0.0))
            db.execute("CREATE TABLE calculated_values (value REAL)")
            db.execute("INSERT INTO calculated_values VALUES (100)")
        before = original_state()
        result = clean_generated_data()
        self.assertEqual(before, original_state())
        self.assertTrue(DataResource.objects.filter(pk=original.pk).exists())
        self.assertFalse(
            DataResource.objects.filter(pk__in=[generated.pk, alias.pk]).exists()
        )
        with sqlite3.connect(database) as db:
            self.assertEqual(
                db.execute("SELECT * FROM original_values").fetchall(),
                [("原始观测", 0.0)],
            )
            self.assertIsNone(
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='calculated_values'"
                ).fetchone()
            )
        self.assertEqual(result["rawResourcesKept"], 1)

    def test_protected_original_file_not_unlinked_even_if_reused_by_generated_resource(
        self,
    ):
        path = table_data_path("user_input.txt")
        path.parent.mkdir(parents=True)
        path.write_text("用户上传原件")
        generated = DataResource.objects.create(
            name="calculated",
            code="calculated",
            maintainer=self.user,
            data_type="document",
            storage_path="user_input.txt",
            is_compute_result=True,
        )
        result = clean_generated_data([path])
        self.assertFalse(DataResource.objects.filter(pk=generated.pk).exists())
        self.assertEqual(path.read_text(), "用户上传原件")
        self.assertIn(str(path), result["sharedOriginalFilesKept"])

    def test_running_workflow_blocks_cleanup_before_any_mutation(self):
        generated = self.resource("calculated_values", generated=True)
        AgentWorkflow.objects.create(
            owner=self.user,
            goal="正在计算",
            model="test",
            idempotency_key="active",
            status="running",
        )
        with self.assertRaisesMessage(ValueError, "仍有执行任务"):
            clean_generated_data()
        self.assertTrue(DataResource.objects.filter(pk=generated.pk).exists())

    def test_compaction_preserves_human_goal_and_parameters(self):
        workflow = AgentWorkflow.objects.create(
            owner=self.user,
            goal="用户指定零值应保留",
            model="test",
            idempotency_key="completed",
            status="succeeded",
            parameters={"threshold": 0},
            plan={"copiedPixels": list(range(1000))},
        )
        step = AgentWorkflowStep.objects.create(
            workflow=workflow,
            sequence=1,
            kind="compute",
            status="succeeded",
            action={"copiedFeatures": list(range(1000))},
        )
        clean_generated_data()
        workflow.refresh_from_db()
        step.refresh_from_db()
        self.assertEqual(workflow.goal, "用户指定零值应保留")
        self.assertEqual(workflow.parameters, {"threshold": 0})
        self.assertNotIn("copiedPixels", workflow.plan)
        self.assertEqual(step.action, {})
