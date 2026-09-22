import gc
import weakref
from pathlib import Path
from threading import Event
from time import sleep
from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase

from apps.raster.models import RasterProcessingJob
from apps.raster.services import jobs as jobs_service
from apps.raster.services.exceptions import RasterJobError
from apps.raster.services.jobs import (
    RasterJob,
    _JOBS,
    _LAST_PERSIST,
    _LOCK,
    _HeavyTaskExecutor,
    _append_job,
    _create_job,
    _fail_job,
    _finish_job,
    _prune_job_caches_locked,
    _set_job_artifact,
    get_job,
    get_job_artifact_path,
    reconcile_interrupted_jobs,
    start_import_job,
    start_scan_job,
)


class RasterJobStateTests(SimpleTestCase):
    def setUp(self):
        with _LOCK:
            _JOBS.clear()
            _LAST_PERSIST.clear()
        self._restart_reconciled = jobs_service._RESTART_RECONCILED
        jobs_service._RESTART_RECONCILED = True

    def tearDown(self):
        with _LOCK:
            _JOBS.clear()
            _LAST_PERSIST.clear()
        jobs_service._RESTART_RECONCILED = self._restart_reconciled

    def test_job_append_caps_messages_and_never_reduces_progress(self):
        job = RasterJob(id="job-1", kind="render")

        for index in range(130):
            job.append(f"message {index}", index)
        job.append("old progress", 50)

        self.assertEqual(len(job.messages), 120)
        self.assertEqual(job.messages[0], "message 11")
        self.assertEqual(job.messages[-1], "old progress")
        self.assertEqual(job.progress_percent, 100)

    def test_append_job_parses_progress_from_message(self):
        job = _create_job("scan")

        _append_job(job.id, "扫描进度 60%")

        stored = get_job(job.id)
        self.assertEqual(stored.status, "running")
        self.assertEqual(stored.progress_percent, 60)
        self.assertEqual(stored.messages, ["扫描进度 60%"])

    def test_finish_job_marks_ready_with_result(self):
        job = _create_job("render")

        _finish_job(job.id, {"status": "ready"}, "ready")

        stored = get_job(job.id)
        self.assertEqual(stored.status, "ready")
        self.assertEqual(stored.progress_percent, 100)
        self.assertEqual(stored.result, {"status": "ready"})
        self.assertIsNotNone(stored.finished_at)

    def test_fail_job_records_error_and_message(self):
        job = _create_job("import")

        _fail_job(job.id, "GDAL 处理失败")

        stored = get_job(job.id)
        self.assertEqual(stored.status, "failed")
        self.assertEqual(stored.error, "GDAL 处理失败")
        self.assertIn("GDAL 处理失败", stored.messages)
        self.assertIsNotNone(stored.finished_at)

    def test_get_job_raises_for_missing_job(self):
        with self.assertRaisesRegex(RasterJobError, "任务不存在或已过期"):
            get_job("missing")

    def test_get_job_artifact_path_requires_ready_artifact(self):
        job = _create_job("export")

        with self.assertRaisesRegex(RasterJobError, "导出文件不存在或已过期"):
            get_job_artifact_path(job.id)

        _set_job_artifact(job.id, Path("/tmp/export.zip"))

        self.assertEqual(get_job_artifact_path(job.id), Path("/tmp/export.zip"))

    def test_import_job_cleans_uploaded_file_when_import_fails(self):
        with (
            patch(
                "apps.raster.services.importer.import_raster_file",
                side_effect=RuntimeError("预处理失败"),
            ),
            patch(
                "apps.raster.services.importer.cleanup_uploaded_import_files"
            ) as cleanup,
            patch(
                "apps.raster.services.jobs._submit_job",
                side_effect=self._run_job_inline,
            ),
        ):
            job = start_import_job(
                "/tmp/uploaded-raster.tif", cleanup_upload_on_failure=True
            )
            stored = self._wait_for_job(job.id)

        self.assertEqual(stored.status, "failed")
        cleanup.assert_called_once_with(Path("/tmp/uploaded-raster.tif"))

    def test_import_job_keeps_source_file_when_non_upload_import_fails(self):
        with (
            patch(
                "apps.raster.services.importer.import_raster_file",
                side_effect=RuntimeError("预处理失败"),
            ),
            patch(
                "apps.raster.services.importer.cleanup_uploaded_import_files"
            ) as cleanup,
            patch(
                "apps.raster.services.jobs._submit_job",
                side_effect=self._run_job_inline,
            ),
        ):
            job = start_import_job("/tmp/existing-raster.tif")
            stored = self._wait_for_job(job.id)

        self.assertEqual(stored.status, "failed")
        cleanup.assert_not_called()

    def test_scan_job_is_single_flight_while_queued_or_running(self):
        with patch("apps.raster.services.jobs._submit_job") as submit_job:
            first = start_scan_job(created_by_id=11)
            second = start_scan_job(created_by_id=22)

        self.assertIs(second, first)
        self.assertEqual(first.created_by_id, 11)
        submit_job.assert_called_once()

    def test_scan_result_keeps_only_summary_count(self):
        with (
            patch(
                "apps.raster.services.importer.scan_unprocessed_source_files",
                return_value=[object(), object()],
            ),
            patch(
                "apps.raster.services.jobs._submit_job",
                side_effect=self._run_job_inline,
            ),
        ):
            job = start_scan_job()

        self.assertEqual(get_job(job.id).result, {"count": 2})

    def test_queue_saturation_fails_job_and_cleans_rejected_upload(self):
        with (
            patch.object(
                jobs_service._HEAVY_TASK_EXECUTOR, "submit", return_value=False
            ),
            patch(
                "apps.raster.services.importer.cleanup_uploaded_import_files"
            ) as cleanup,
            patch("apps.raster.services.importer.import_raster_file") as importer,
        ):
            job = start_import_job(
                "/tmp/rejected-raster.tif", cleanup_upload_on_failure=True
            )

        stored = get_job(job.id)
        self.assertEqual(stored.status, "failed")
        self.assertIn("队列已满", stored.error)
        cleanup.assert_called_once_with(Path("/tmp/rejected-raster.tif"))
        importer.assert_not_called()

    def test_executor_start_failure_does_not_leave_queued_job(self):
        with (
            patch.object(
                jobs_service._HEAVY_TASK_EXECUTOR,
                "submit",
                side_effect=RuntimeError("thread start failed"),
            ),
            patch(
                "apps.raster.services.importer.cleanup_uploaded_import_files"
            ) as cleanup,
        ):
            job = start_import_job(
                "/tmp/start-failed.tif", cleanup_upload_on_failure=True
            )

        stored = get_job(job.id)
        self.assertEqual(stored.status, "failed")
        self.assertIn("无法启动", stored.error)
        cleanup.assert_called_once_with(Path("/tmp/start-failed.tif"))

    def test_database_connection_wrapper_failure_terminates_active_job(self):
        def execute_inline(target):
            target()
            return True

        with (
            patch.object(
                jobs_service._HEAVY_TASK_EXECUTOR,
                "submit",
                side_effect=execute_inline,
            ),
            patch(
                "apps.raster.services.jobs._run_with_database_connection",
                side_effect=RuntimeError("connection setup failed"),
            ),
            patch(
                "apps.raster.services.importer.cleanup_uploaded_import_files"
            ) as cleanup,
        ):
            job = start_import_job(
                "/tmp/connection-failed.tif", cleanup_upload_on_failure=True
            )

        stored = get_job(job.id)
        self.assertEqual(stored.status, "failed")
        self.assertIn("执行环境异常", stored.error)
        cleanup.assert_called_once_with(Path("/tmp/connection-failed.tif"))

    def test_connection_close_failure_does_not_overwrite_ready_or_cleanup(self):
        def execute_inline(target):
            target()
            return True

        def run_then_fail(runner):
            runner()
            raise RuntimeError("connection close failed")

        with (
            patch.object(
                jobs_service._HEAVY_TASK_EXECUTOR,
                "submit",
                side_effect=execute_inline,
            ),
            patch(
                "apps.raster.services.jobs._run_with_database_connection",
                side_effect=run_then_fail,
            ),
            patch(
                "apps.raster.services.importer.import_raster_file",
                return_value=object(),
            ),
            patch(
                "apps.raster.services.serializers.serialize_raster_dataset",
                return_value={"id": 1},
            ),
            patch(
                "apps.raster.services.importer.cleanup_uploaded_import_files"
            ) as cleanup,
        ):
            job = start_import_job(
                "/tmp/completed-raster.tif", cleanup_upload_on_failure=True
            )

        stored = get_job(job.id)
        self.assertEqual(stored.status, "ready")
        cleanup.assert_not_called()

    def test_terminal_cache_prunes_oldest_and_preserves_active_job(self):
        active = RasterJob(id="active", kind="import", status="running", started_at=1)
        oldest = RasterJob(
            id="oldest",
            kind="scan",
            status="ready",
            started_at=2,
            finished_at=10,
        )
        newest = RasterJob(
            id="newest",
            kind="render",
            status="failed",
            started_at=3,
            finished_at=20,
        )
        with _LOCK:
            _JOBS.update({job.id: job for job in (active, oldest, newest)})
            _LAST_PERSIST.update(
                {
                    "active": (25, 50),
                    "oldest": (10, 100),
                    "newest": (20, 100),
                }
            )
            with (
                patch.object(jobs_service, "JOB_CACHE_MAX_ENTRIES", 2),
                patch.object(jobs_service, "COMPLETED_JOB_TTL_SECONDS", 1_000),
            ):
                _prune_job_caches_locked(now=30)

        self.assertNotIn("oldest", _JOBS)
        self.assertNotIn("oldest", _LAST_PERSIST)
        self.assertIn("active", _JOBS)
        self.assertIn("active", _LAST_PERSIST)
        self.assertIn("newest", _JOBS)

    def test_terminal_cache_ttl_never_evicts_active_job(self):
        active = RasterJob(id="active", kind="scan", status="running", started_at=1)
        expired = RasterJob(
            id="expired",
            kind="scan",
            status="ready",
            started_at=1,
            finished_at=10,
        )
        with _LOCK:
            _JOBS.update({"active": active, "expired": expired})
            _LAST_PERSIST.update({"active": (1, 50), "expired": (10, 100)})
            with patch.object(jobs_service, "COMPLETED_JOB_TTL_SECONDS", 5):
                _prune_job_caches_locked(now=20)

        self.assertIn("active", _JOBS)
        self.assertIn("active", _LAST_PERSIST)
        self.assertNotIn("expired", _JOBS)
        self.assertNotIn("expired", _LAST_PERSIST)

    def test_restart_reconcile_retries_after_database_is_initialized(self):
        with patch.object(jobs_service, "_RESTART_RECONCILED", False):
            with patch.object(
                RasterProcessingJob._base_manager,
                "filter",
                side_effect=OperationalError("table is not ready"),
            ):
                self.assertFalse(reconcile_interrupted_jobs())
            self.assertFalse(jobs_service._RESTART_RECONCILED)

            with patch.object(
                RasterProcessingJob._base_manager, "filter"
            ) as filter_jobs:
                filter_jobs.return_value.update.return_value = 0
                self.assertTrue(reconcile_interrupted_jobs())
            self.assertTrue(jobs_service._RESTART_RECONCILED)

    @staticmethod
    def _run_job_inline(job, runner, **kwargs):
        runner()

    def _wait_for_job(self, job_id: str) -> RasterJob:
        for _ in range(50):
            job = get_job(job_id)
            if job.status in {"ready", "failed"}:
                return job
            sleep(0.01)
        return get_job(job_id)


class HeavyTaskExecutorTests(SimpleTestCase):
    def test_single_worker_has_bounded_waiting_queue(self):
        executor = _HeavyTaskExecutor(queue_size=1)
        running = Event()
        release = Event()
        queued_finished = Event()

        def blocking_task() -> None:
            running.set()
            release.wait(2)

        self.assertTrue(executor.submit(blocking_task))
        self.assertTrue(running.wait(1))
        self.assertTrue(executor.submit(queued_finished.set))
        self.assertFalse(executor.submit(lambda: None))

        release.set()
        self.assertTrue(queued_finished.wait(1))

    def test_idle_worker_releases_completed_task_payload(self):
        executor = _HeavyTaskExecutor(queue_size=1)

        class PayloadTask:
            def __call__(self) -> None:
                return None

        task = PayloadTask()
        task_reference = weakref.ref(task)
        self.assertTrue(executor.submit(task))
        executor._queue.join()

        del task
        gc.collect()
        self.assertIsNone(task_reference())
