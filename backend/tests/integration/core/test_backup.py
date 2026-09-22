import json
import sqlite3
import tempfile
import threading
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings

from apps.core.backup_service import (
    BackupRunConflictError,
    _sqlite_snapshot,
    start_backup_run,
    start_due_backup_runs,
)
from apps.core.config import load_project_config
from apps.core.initialization import ensure_superadmin_defaults
from apps.core.models import BackupRun


class BackupPermissionApiTests(TestCase):
    def test_backup_api_requires_builtin_superadmin_even_with_permission(self):
        user = get_user_model().objects.create_user(
            username="backup-direct-user", password="pass12345"
        )
        grant(user, ("core", "manage_data_backup"))
        self.client.force_login(user)

        response = self.client.get("/api/admin/backups/overview/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "数据备份属于系统级维护功能")

        me_response = self.client.get("/api/auth/me/")
        self.assertFalse(
            me_response.json()["user"]["permissions"]["canManageDataBackup"]
        )


class BackupLocalRunTests(TestCase):
    def test_sqlite_snapshot_connections_are_closed_before_cleanup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source.db"
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT)")
                connection.execute("INSERT INTO sample(name) VALUES ('poplar')")
                connection.commit()

            snapshot = _sqlite_snapshot(source, root)
            with closing(sqlite3.connect(snapshot)) as connection:
                self.assertEqual(
                    connection.execute("SELECT name FROM sample").fetchone()[0],
                    "poplar",
                )

            snapshot.unlink()
            self.assertFalse(snapshot.exists())

    def test_platform_overview_counts_logs_and_deduplicates_config_file(self):
        superadmin, _group = ensure_superadmin_defaults()
        self.client.force_login(superadmin)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app_root = root / "app"
            research_root = root / "research"
            config_path = app_root / "config" / "app.toml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                minimal_config_text(app_root, research_root),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))
            media_file = config.app_path("media", "note.txt")
            log_file = config.app_path("logs", "runtime.log")
            media_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            media_file.write_text("backup me", encoding="utf-8")
            log_file.write_text("log me", encoding="utf-8")

            with override_settings(
                PROJECT_CONFIG=config, PROGRAM_ROOT=Path("/opt/app")
            ):
                settings_response = self.client.post(
                    "/api/admin/backups/settings/",
                    data=json.dumps(
                        {
                            "plans": {
                                "platform": {
                                    "enabled": True,
                                    "dailyAt": "03:00",
                                    "target": "local",
                                    "retentionCount": 2,
                                    "includeLogs": True,
                                },
                                "research": {
                                    "enabled": False,
                                    "dailyAt": "02:00",
                                    "target": "local",
                                    "retentionCount": 2,
                                    "includeLogs": False,
                                },
                            },
                            "local": {"directory": ""},
                        }
                    ),
                    content_type="application/json",
                )
                self.assertEqual(settings_response.status_code, 200)

                response = self.client.get("/api/admin/backups/overview/")

            self.assertEqual(response.status_code, 200)
            platform_summary = next(
                item
                for item in response.json()["summaries"]
                if item["planType"] == "platform"
            )
            expected_size = (
                media_file.stat().st_size
                + log_file.stat().st_size
                + config_path.stat().st_size
            )
            self.assertEqual(platform_summary["fileCount"], 3)
            self.assertEqual(platform_summary["sizeBytes"], expected_size)

    def test_superadmin_can_save_local_plan_and_generate_backup_archive(self):
        superadmin, _group = ensure_superadmin_defaults()
        self.client.force_login(superadmin)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "app.toml"
            config_path.write_text(
                minimal_config_text(root / "app", root / "research"),
                encoding="utf-8",
            )
            config = load_project_config(config_path, program_root=Path("/opt/app"))
            config.app_path("media", "note.txt").write_text(
                "backup me", encoding="utf-8"
            )

            with override_settings(
                PROJECT_CONFIG=config, PROGRAM_ROOT=Path("/opt/app")
            ):
                response = self.client.post(
                    "/api/admin/backups/settings/",
                    data=json.dumps(
                        {
                            "plans": {
                                "platform": {
                                    "enabled": True,
                                    "dailyAt": "03:00",
                                    "target": "local",
                                    "retentionCount": 2,
                                    "includeLogs": False,
                                },
                                "research": {
                                    "enabled": False,
                                    "dailyAt": "02:00",
                                    "target": "local",
                                    "retentionCount": 2,
                                    "includeLogs": False,
                                },
                            },
                            "local": {"directory": ""},
                        }
                    ),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json()["plans"]["platform"]["target"], "local"
                )

                test_response = self.client.post(
                    "/api/admin/backups/targets/test/",
                    data=json.dumps({"targetType": "local"}),
                    content_type="application/json",
                )
                self.assertEqual(test_response.status_code, 200)
                self.assertEqual(test_response.json()["status"], "success")

                run = start_backup_run(
                    plan_type=BackupRun.PlanType.PLATFORM,
                    target_type=BackupRun.TargetType.LOCAL,
                    trigger=BackupRun.Trigger.MANUAL,
                    user=superadmin,
                    run_async=False,
                )

            run.refresh_from_db()
            self.assertEqual(run.status, BackupRun.Status.SUCCESS)
            self.assertTrue(Path(run.local_path).is_file())
            with ZipFile(run.local_path) as archive:
                names = archive.namelist()
                self.assertIn("manifest.json", names)
                self.assertIn("platform/media/note.txt", names)
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            self.assertEqual(manifest["planType"], "platform")
            self.assertGreaterEqual(manifest["fileCount"], 1)


class BackupSingleFlightTests(TransactionTestCase):
    reset_sequences = True

    def test_concurrent_same_plan_creates_one_queued_run(self):
        barrier = threading.Barrier(2)

        def start_one():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    return start_backup_run(
                        plan_type=BackupRun.PlanType.PLATFORM,
                        target_type=BackupRun.TargetType.LOCAL,
                        trigger=BackupRun.Trigger.MANUAL,
                        run_async=True,
                    )
                except BackupRunConflictError as exc:
                    return exc
            finally:
                connection.close()

        with (
            patch("apps.core.backup_service._ensure_target_configured"),
            patch("apps.core.backup_service._launch_backup_run"),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            results = list(executor.map(lambda _index: start_one(), range(2)))

        runs = [result for result in results if isinstance(result, BackupRun)]
        conflicts = [
            result for result in results if isinstance(result, BackupRunConflictError)
        ]
        self.assertEqual(len(runs), 1)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].active_run.id, runs[0].id)
        self.assertEqual(
            BackupRun.objects.filter(
                plan_type=BackupRun.PlanType.PLATFORM,
                status__in=(BackupRun.Status.QUEUED, BackupRun.Status.RUNNING),
            ).count(),
            1,
        )

    def test_api_returns_structured_conflict_and_archive_names_are_unique(self):
        superadmin, _group = ensure_superadmin_defaults()
        self.client.force_login(superadmin)
        payload = {
            "planType": BackupRun.PlanType.PLATFORM,
            "targetType": BackupRun.TargetType.LOCAL,
        }

        with (
            patch("apps.core.backup_service._ensure_target_configured"),
            patch("apps.core.backup_service._launch_backup_run"),
        ):
            first_response = self.client.post(
                "/api/admin/backups/runs/",
                data=json.dumps(payload),
                content_type="application/json",
            )
            conflict_response = self.client.post(
                "/api/admin/backups/runs/",
                data=json.dumps(payload),
                content_type="application/json",
            )
            first_run = BackupRun.objects.get(pk=first_response.json()["id"])
            first_run.status = BackupRun.Status.SUCCESS
            first_run.save(update_fields=["status", "updated_at"])
            second_response = self.client.post(
                "/api/admin/backups/runs/",
                data=json.dumps(payload),
                content_type="application/json",
            )

        self.assertEqual(first_response.status_code, 202)
        self.assertEqual(conflict_response.status_code, 409)
        self.assertEqual(
            conflict_response.json()["code"], "backup_run_conflict"
        )
        self.assertEqual(
            conflict_response.json()["activeRun"]["id"], first_run.id
        )
        self.assertEqual(second_response.status_code, 202)
        second_run = BackupRun.objects.get(pk=second_response.json()["id"])
        self.assertNotEqual(first_run.archive_name, second_run.archive_name)
        self.assertIn(f"-{first_run.id}-", first_run.archive_name)
        self.assertIn(f"-{second_run.id}-", second_run.archive_name)

    def test_scheduler_skips_plan_that_became_active_after_due_check(self):
        active_run = BackupRun.objects.create(
            plan_type=BackupRun.PlanType.PLATFORM,
            target_type=BackupRun.TargetType.LOCAL,
            trigger=BackupRun.Trigger.MANUAL,
        )
        plan = SimpleNamespace(target=BackupRun.TargetType.LOCAL)

        with (
            patch(
                "apps.core.backup_service.due_backup_plans",
                return_value=[(BackupRun.PlanType.PLATFORM, plan)],
            ),
            patch(
                "apps.core.backup_service.start_backup_run",
                side_effect=BackupRunConflictError(active_run),
            ),
        ):
            runs = start_due_backup_runs()

        self.assertEqual(runs, [])


def grant(user, *specs):
    for app_label, codename in specs:
        permission = Permission.objects.get(
            content_type__app_label=app_label, codename=codename
        )
        user.user_permissions.add(permission)


def minimal_config_text(business_root: Path, research_root: Path) -> str:
    business_text = business_root.as_posix()
    research_text = research_root.as_posix()
    return f"""
[runtime]
debug = true
allowed_hosts = ["*"]
csrf_trusted_origins = []
waitress_host = "127.0.0.1"
waitress_port = 8000
waitress_threads = 1
disable_catalog_startup_scan = true
disable_raster_startup_scan = true

[application.system]
name = "测试系统"
allow_registration = true

[application.storage]
app_data = "{business_text}"
research_data_root = "{research_text}"

[application.map]
default_center = [80.0, 41.5]
default_zoom = 4.5
default_basemap = "osm"
mapbox_access_token = ""

[application.limits]
upload_max_mb = 512
query_result_limit = 30000
max_raster_side_pixels = 10000

[application.raster]
symbolizer_timeout_seconds = 120
"""
