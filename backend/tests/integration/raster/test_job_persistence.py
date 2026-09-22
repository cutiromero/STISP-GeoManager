import tempfile
from datetime import timedelta
from pathlib import Path
from time import sleep
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase, TransactionTestCase
from django.utils import timezone

from apps.raster.models import RasterProcessingJob
from apps.raster.services import jobs as jobs_service
from apps.raster.services.jobs import (
    _JOBS,
    _LAST_PERSIST,
    _LOCK,
    _cleanup_one_expired_export_artifact,
    _create_job,
    _finish_job,
    _set_job_artifact,
    get_job,
    reconcile_interrupted_jobs,
    start_export_job,
)


class RasterJobPersistenceTests(TestCase):
    def setUp(self):
        with _LOCK:
            _JOBS.clear()
            _LAST_PERSIST.clear()

    def tearDown(self):
        with _LOCK:
            _JOBS.clear()
            _LAST_PERSIST.clear()

    def test_job_can_be_reloaded_after_memory_cache_is_cleared(self):
        job = _create_job("import")
        self.assertTrue(RasterProcessingJob.objects.filter(pk=job.id).exists())

        with _LOCK:
            _JOBS.clear()

        restored = get_job(job.id)
        self.assertEqual(restored.id, job.id)
        self.assertEqual(restored.stage, "queued")

    def test_active_cached_job_refreshes_from_newer_persisted_state(self):
        job = _create_job("import")
        RasterProcessingJob.objects.filter(pk=job.id).update(
            status="ready",
            stage="ready",
            progress_percent=100,
            result={"status": "ready"},
        )

        restored = get_job(job.id)

        self.assertEqual(restored.status, "ready")
        self.assertEqual(restored.progress_percent, 100)
        self.assertEqual(restored.result, {"status": "ready"})

    def test_evicted_ready_job_can_be_reloaded_from_database(self):
        job = _create_job("render")
        _finish_job(job.id, {"styleHash": "style-1"}, "ready")

        with _LOCK:
            _JOBS.clear()
            _LAST_PERSIST.clear()

        restored = get_job(job.id)

        self.assertEqual(restored.status, "ready")
        self.assertEqual(restored.progress_percent, 100)
        self.assertEqual(restored.result, {"styleHash": "style-1"})

    def test_reconcile_marks_queued_and_running_jobs_interrupted(self):
        queued = RasterProcessingJob.objects.create(
            id="queued-before-restart", kind="import", status="queued"
        )
        running = RasterProcessingJob.objects.create(
            id="running-before-restart", kind="scan", status="running"
        )
        ready = RasterProcessingJob.objects.create(
            id="ready-before-restart", kind="render", status="ready"
        )

        with patch.object(jobs_service, "_RESTART_RECONCILED", False):
            self.assertTrue(reconcile_interrupted_jobs())

        queued.refresh_from_db()
        running.refresh_from_db()
        ready.refresh_from_db()
        self.assertEqual(queued.status, "failed")
        self.assertEqual(running.status, "failed")
        self.assertIn("服务进程已重启", queued.error)
        self.assertIsNotNone(running.finished_at)
        self.assertEqual(ready.status, "ready")

    def test_reconcile_does_not_fail_current_process_active_job(self):
        current = RasterProcessingJob.objects.create(
            id="current-process-job", kind="import", status="running"
        )
        with _LOCK:
            _JOBS[current.id] = jobs_service._load_persisted_job(current.id)

        with patch.object(jobs_service, "_RESTART_RECONCILED", False):
            self.assertTrue(reconcile_interrupted_jobs())

        current.refresh_from_db()
        self.assertEqual(current.status, "running")

    def test_unreconciled_persisted_active_job_is_not_cached_as_current(self):
        stale = RasterProcessingJob.objects.create(
            id="stale-active-job", kind="scan", status="running"
        )

        with patch(
            "apps.raster.services.jobs.reconcile_interrupted_jobs",
            return_value=False,
        ):
            restored = get_job(stale.id)

        self.assertEqual(restored.status, "running")
        self.assertNotIn(stale.id, _JOBS)

        with patch.object(jobs_service, "_RESTART_RECONCILED", False):
            self.assertTrue(reconcile_interrupted_jobs())
        stale.refresh_from_db()
        self.assertEqual(stale.status, "failed")


class RasterExportArtifactLifecycleTests(TransactionTestCase):
    def setUp(self):
        with _LOCK:
            _JOBS.clear()
            _LAST_PERSIST.clear()

    def tearDown(self):
        with _LOCK:
            _JOBS.clear()
            _LAST_PERSIST.clear()

    def test_download_file_is_deleted_and_record_cleared_when_stream_closes(self):
        from apps.catalog.views import export_job_download

        artifact = self._new_artifact(b"zip-content")
        job = _create_job("export")
        _set_job_artifact(job.id, artifact)
        _finish_job(job.id, {"filename": "export.zip"}, "ready")
        request = RequestFactory().get(
            f"/api/catalog/export/jobs/{job.id}/download/"
        )
        request.user = SimpleNamespace(
            id=99,
            is_authenticated=True,
            is_superuser=False,
        )

        with (
            patch("apps.catalog.views.has_feature_perm", return_value=True),
            patch("apps.catalog.views.log_operation"),
        ):
            response = export_job_download(request, job.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"zip-content")
        self.assertTrue(artifact.exists())

        response.close()

        self.assertFalse(artifact.exists())
        self.assertEqual(get_job(job.id).artifact_path, "")
        self.assertEqual(
            RasterProcessingJob.objects.get(pk=job.id).artifact_path,
            "",
        )

    def test_export_failure_after_artifact_creation_deletes_single_artifact(self):
        created_artifacts: list[Path] = []
        original_set_job_artifact = _set_job_artifact

        def write_export(*args, output_path: Path, **kwargs) -> Path:
            output_path.write_bytes(b"zip-content")
            return output_path

        def capture_artifact(job_id: str, artifact: Path) -> None:
            created_artifacts.append(artifact)
            self.addCleanup(artifact.unlink, missing_ok=True)
            original_set_job_artifact(job_id, artifact)

        with (
            patch(
                "apps.catalog.export.export_layers_zip_to_path",
                side_effect=write_export,
            ),
            patch(
                "apps.raster.services.jobs._set_job_artifact",
                side_effect=capture_artifact,
            ),
            patch(
                "apps.raster.services.jobs._finish_job",
                side_effect=RuntimeError("任务结果持久化失败"),
            ),
            patch(
                "apps.raster.services.jobs._submit_job",
                side_effect=self._run_job_inline,
            ),
        ):
            job = start_export_job(
                items=[],
                epsg=4326,
                reproject=True,
                clip_geometry=None,
                vector_format="geojson",
            )
            stored = self._wait_for_job(job.id)

        self.assertEqual(stored.status, "failed")
        self.assertEqual(len(created_artifacts), 1)
        self.assertFalse(created_artifacts[0].exists())
        self.assertEqual(stored.artifact_path, "")
        self.assertEqual(
            RasterProcessingJob.objects.get(pk=job.id).artifact_path,
            "",
        )

    def test_export_write_failure_deletes_partially_written_artifact(self):
        created_artifacts: list[Path] = []

        def fail_after_partial_write(*args, output_path: Path, **kwargs) -> Path:
            created_artifacts.append(output_path)
            self.addCleanup(output_path.unlink, missing_ok=True)
            output_path.write_bytes(b"partial")
            raise OSError("导出磁盘写入失败")

        with (
            patch(
                "apps.catalog.export.export_layers_zip_to_path",
                side_effect=fail_after_partial_write,
            ),
            patch(
                "apps.raster.services.jobs._submit_job",
                side_effect=self._run_job_inline,
            ),
        ):
            job = start_export_job(
                items=[],
                epsg=4326,
                reproject=True,
                clip_geometry=None,
                vector_format="geojson",
            )
            stored = self._wait_for_job(job.id)

        self.assertEqual(stored.status, "failed")
        self.assertEqual(len(created_artifacts), 1)
        self.assertFalse(created_artifacts[0].exists())
        self.assertEqual(stored.artifact_path, "")
        self.assertEqual(
            RasterProcessingJob.objects.get(pk=job.id).artifact_path,
            "",
        )

    def test_ttl_cleanup_removes_only_oldest_expired_artifact(self):
        now = timezone.now()
        oldest_artifact = self._new_artifact(b"oldest")
        next_artifact = self._new_artifact(b"next")
        RasterProcessingJob.objects.create(
            id="expired-oldest",
            kind="export",
            status="ready",
            stage="ready",
            progress_percent=100,
            artifact_path=str(oldest_artifact),
            finished_at=now - timedelta(days=3),
        )
        RasterProcessingJob.objects.create(
            id="expired-next",
            kind="export",
            status="ready",
            stage="ready",
            progress_percent=100,
            artifact_path=str(next_artifact),
            finished_at=now - timedelta(days=2),
        )

        cleaned_job_id = _cleanup_one_expired_export_artifact(now=now)

        self.assertEqual(cleaned_job_id, "expired-oldest")
        self.assertFalse(oldest_artifact.exists())
        self.assertTrue(next_artifact.exists())
        self.assertEqual(
            RasterProcessingJob.objects.get(pk="expired-oldest").artifact_path,
            "",
        )
        self.assertEqual(
            RasterProcessingJob.objects.get(pk="expired-next").artifact_path,
            str(next_artifact),
        )

    def _new_artifact(self, content: bytes) -> Path:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as output:
            output.write(content)
            artifact = Path(output.name)
        self.addCleanup(artifact.unlink, missing_ok=True)
        return artifact

    def _wait_for_job(self, job_id: str):
        for _ in range(200):
            job = get_job(job_id)
            if job.status in {"ready", "failed"}:
                return job
            sleep(0.01)
        return get_job(job_id)

    @staticmethod
    def _run_job_inline(job, runner, **kwargs):
        runner()
