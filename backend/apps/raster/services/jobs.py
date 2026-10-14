from __future__ import annotations

from contextvars import copy_context

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Callable

from django.db import (
    OperationalError,
    ProgrammingError,
    close_old_connections,
    connection,
)
from django.utils import timezone

from apps.raster.services.progress import (
    normalize_progress_text,
    parse_progress_percent,
)


@dataclass
class RasterJob:
    id: str
    kind: str
    status: str = "queued"
    stage: str = "queued"
    progress_percent: int = 0
    messages: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str = ""
    artifact_path: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    created_by_id: int | None = None
    project_tag_id: int = 1

    def append(self, message: str, percent: int | None = None) -> None:
        text = normalize_progress_text(message)
        if text:
            self.messages.append(text)
            self.messages = self.messages[-120:]
        if percent is not None:
            self.progress_percent = max(self.progress_percent, min(100, percent))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "stage": self.stage,
            "progressPercent": self.progress_percent,
            "messages": self.messages,
            "result": self.result,
            "error": self.error,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }


_JOBS: dict[str, RasterJob] = {}
_LOCK = threading.RLock()
_LAST_PERSIST: dict[str, tuple[float, int]] = {}
_RESTART_RECONCILE_LOCK = threading.Lock()
_RESTART_RECONCILED = False

HEAVY_TASK_QUEUE_SIZE = 4
COMPLETED_JOB_TTL_SECONDS = 6 * 60 * 60
JOB_CACHE_MAX_ENTRIES = 256
EXPORT_ARTIFACT_TTL_SECONDS = 24 * 60 * 60
HEAVY_TASK_QUEUE_FULL_MESSAGE = "后台栅格任务队列已满，请稍后重试"
RESTART_INTERRUPTED_MESSAGE = "服务进程已重启，任务未能继续执行，请重新提交"

logger = logging.getLogger(__name__)


class _HeavyTaskExecutor:
    """One worker with a hard cap on waiting memory-heavy tasks."""

    def __init__(self, *, queue_size: int) -> None:
        self._queue: queue.Queue[Callable[[], None]] = queue.Queue(maxsize=queue_size)
        self._start_lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def submit(self, target: Callable[[], None]) -> bool:
        self._ensure_worker()
        try:
            context = copy_context()
            self._queue.put_nowait(lambda: context.run(target))
        except queue.Full:
            return False
        return True

    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        with self._start_lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._run,
                name="raster-heavy-worker",
                daemon=True,
            )
            self._worker.start()

    def _run(self) -> None:
        while True:
            target = self._queue.get()
            try:
                from apps.core.heavy_work import heavy_work

                with heavy_work():
                    target()
            except Exception:
                logger.exception("未捕获的栅格后台任务异常")
            finally:
                # Do not let the idle worker retain the last task closure and
                # its potentially large export/import payload.
                del target
                self._queue.task_done()


_HEAVY_TASK_EXECUTOR = _HeavyTaskExecutor(queue_size=HEAVY_TASK_QUEUE_SIZE)


class _DeleteOnCloseFile:
    def __init__(self, file_object: BinaryIO, on_close: Callable[[], None]) -> None:
        self._file_object = file_object
        self._on_close = on_close
        self._closed = False

    def read(self, *args, **kwargs):
        return self._file_object.read(*args, **kwargs)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._file_object.close()
        finally:
            self._on_close()

    @property
    def closed(self) -> bool:
        return self._closed

    def __getattr__(self, name: str):
        return getattr(self._file_object, name)


def reconcile_interrupted_jobs() -> bool:
    """Fail jobs that cannot survive a process restart.

    The successful flag is deliberately not set when the database schema is not
    ready, so migrations and test-database creation can retry on first use.
    """

    global _RESTART_RECONCILED
    if _RESTART_RECONCILED:
        return True
    with _RESTART_RECONCILE_LOCK:
        if _RESTART_RECONCILED:
            return True
        from apps.raster.models import RasterProcessingJob

        now = timezone.now()
        with _LOCK:
            current_process_job_ids = tuple(_JOBS)
        try:
            # Process restart recovery must cover stale jobs in every project.
            interrupted = RasterProcessingJob._base_manager.filter(
                status__in=(
                    RasterProcessingJob.Status.QUEUED,
                    RasterProcessingJob.Status.RUNNING,
                )
            )
            if current_process_job_ids:
                interrupted = interrupted.exclude(pk__in=current_process_job_ids)
            interrupted.update(
                status=RasterProcessingJob.Status.FAILED,
                stage=RasterProcessingJob.Status.FAILED,
                error=RESTART_INTERRUPTED_MESSAGE,
                finished_at=now,
                updated_at=now,
            )
        except (OperationalError, ProgrammingError):
            return False
        except Exception:
            # SimpleTestCase and partially initialized test databases can reject
            # ORM access before tables are available. First real use will retry.
            return False
        _RESTART_RECONCILED = True
        return True


def _prune_job_caches_locked(*, now: float | None = None) -> None:
    current_time = time.time() if now is None else now
    terminal_jobs = [
        (job.finished_at or job.started_at, job_id)
        for job_id, job in _JOBS.items()
        if job.status not in {"queued", "running"}
    ]
    expired_ids = {
        job_id
        for completed_at, job_id in terminal_jobs
        if current_time - completed_at >= COMPLETED_JOB_TTL_SECONDS
    }

    remaining_count = len(_JOBS) - len(expired_ids)
    overflow = max(0, remaining_count - JOB_CACHE_MAX_ENTRIES)
    if overflow:
        oldest_terminal_ids = [
            job_id for _, job_id in sorted(terminal_jobs) if job_id not in expired_ids
        ]
        expired_ids.update(oldest_terminal_ids[:overflow])

    for job_id in expired_ids:
        _JOBS.pop(job_id, None)
        _LAST_PERSIST.pop(job_id, None)

    active_job_ids = {
        job_id for job_id, job in _JOBS.items() if job.status in {"queued", "running"}
    }
    for job_id, (last_persisted_at, _) in list(_LAST_PERSIST.items()):
        if job_id not in _JOBS or (
            job_id not in active_job_ids
            and current_time - last_persisted_at >= COMPLETED_JOB_TTL_SECONDS
        ):
            _LAST_PERSIST.pop(job_id, None)

    overflow = max(0, len(_LAST_PERSIST) - JOB_CACHE_MAX_ENTRIES)
    if overflow:
        evictable_persist_entries = sorted(
            (
                (job_id, state)
                for job_id, state in _LAST_PERSIST.items()
                if job_id not in active_job_ids
            ),
            key=lambda item: (item[1][0], item[0]),
        )
        for job_id, _ in evictable_persist_entries[:overflow]:
            _LAST_PERSIST.pop(job_id, None)


def _create_job(
    kind: str,
    created_by_id: int | None = None,
    *,
    reconcile_restart: bool = True,
    input_refs: list[dict[str, int]] | None = None,
) -> RasterJob:
    if reconcile_restart:
        reconcile_interrupted_jobs()
    from apps.projects.context import selected_project_id

    job = RasterJob(
        id=uuid.uuid4().hex,
        kind=kind,
        created_by_id=created_by_id,
        project_tag_id=selected_project_id(),
        result={"inputRefs": input_refs} if input_refs is not None else None,
    )
    with _LOCK:
        _prune_job_caches_locked()
        _JOBS[job.id] = job
        _prune_job_caches_locked()
    try:
        _persist_job(job, force=True, require_persisted=input_refs is not None)
    except Exception:
        with _LOCK:
            _JOBS.pop(job.id, None)
            _LAST_PERSIST.pop(job.id, None)
        from apps.raster.services.exceptions import RasterJobError

        logger.exception("Raster job input reference persistence failed")
        raise RasterJobError("任务登记失败，数据库暂不可用，请稍后重试") from None
    return job


def _set_job_running(
    job_id: str, message: str, percent: int, stage: str = "running"
) -> None:
    from apps.projects.context import require_live_membership

    require_live_membership()
    with _LOCK:
        job = _JOBS[job_id]
        job.status = "running"
        job.stage = stage
        job.append(message, percent)
        _persist_job(job, force=True)


def _append_job(job_id: str, message: str) -> None:
    from apps.projects.context import require_live_membership

    require_live_membership()
    cleaned = normalize_progress_text(message)
    percent = parse_progress_percent(cleaned)
    with _LOCK:
        job = _JOBS[job_id]
        job.status = "running"
        job.stage = _stage_from_message(cleaned, job.stage)
        job.append(cleaned, percent)
        _persist_job(job)


def _finish_job(job_id: str, result: dict[str, Any], status: str) -> None:
    from apps.projects.context import require_live_membership

    require_live_membership()
    with _LOCK:
        job = _JOBS[job_id]
        job.status = status
        job.stage = status
        job.progress_percent = 100
        job.result = result
        job.finished_at = time.time()
        _persist_job(job, force=True)
        _prune_job_caches_locked()


def _set_job_artifact(job_id: str, path: Path) -> None:
    with _LOCK:
        _JOBS[job_id].artifact_path = str(path)
        _persist_job(_JOBS[job_id], force=True)


def _fail_job(job_id: str, error: str) -> None:
    with _LOCK:
        job = _JOBS[job_id]
        job.status = "failed"
        job.stage = "failed"
        job.error = error
        job.append(error)
        job.finished_at = time.time()
        _persist_job(job, force=True)
        _prune_job_caches_locked()


def _fail_job_if_active(job_id: str, error: str) -> bool:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or job.status not in {"queued", "running"}:
            return False
        _fail_job(job_id, error)
        return True


def get_job(job_id: str) -> RasterJob:
    from apps.raster.services.exceptions import RasterJobError
    from apps.projects.context import current_scope
    from apps.raster.models import RasterProcessingJob

    if (
        current_scope.get() is not None
        and not RasterProcessingJob.objects.filter(pk=job_id).exists()
    ):
        raise RasterJobError("任务不存在或无权访问")
    restart_reconciled = reconcile_interrupted_jobs()
    with _LOCK:
        _prune_job_caches_locked()
        cached = _JOBS.get(job_id)
        if cached and cached.status in {"ready", "failed"}:
            return cached
    persisted = _load_persisted_job(job_id)
    if persisted:
        if not restart_reconciled and persisted.status in {"queued", "running"}:
            # Until restart reconciliation succeeds, an active database row
            # may belong to the previous process. Do not let it enter the
            # in-process single-flight/cache state permanently.
            return persisted
        with _LOCK:
            cached = _JOBS.get(job_id)
            if cached and not _persisted_job_is_newer(cached, persisted):
                return cached
            _JOBS[persisted.id] = persisted
            _prune_job_caches_locked()
        return persisted
    if cached:
        return cached
    raise RasterJobError("任务不存在或已过期")


def _run_with_database_connection(target) -> None:
    close_old_connections()
    try:
        target()
    finally:
        connection.close()


def _submit_job(
    job: RasterJob,
    runner: Callable[[], None],
    *,
    on_rejected: Callable[[], None] | None = None,
) -> None:
    def fail_submission(error: str) -> None:
        if not _fail_job_if_active(job.id, error):
            return
        if on_rejected is not None:
            try:
                on_rejected()
            except Exception:
                logger.exception("栅格任务拒绝后清理失败：%s", job.id)

    def execute() -> None:
        from apps.projects.context import ProjectScope, current_scope, project_scope

        try:
            if current_scope.get() is None:
                with project_scope(
                    ProjectScope(
                        (job.project_tag_id,), job.project_tag_id, job.created_by_id
                    )
                ):
                    _run_with_database_connection(runner)
            else:
                _run_with_database_connection(runner)
        except Exception as exc:
            logger.exception("栅格后台任务执行环境异常：%s", job.id)
            fail_submission(f"后台任务执行环境异常：{exc}")

    try:
        accepted = _HEAVY_TASK_EXECUTOR.submit(execute)
    except Exception as exc:
        logger.exception("栅格后台任务无法启动：%s", job.id)
        fail_submission(f"后台任务无法启动：{exc}")
        return
    if accepted:
        return
    fail_submission(HEAVY_TASK_QUEUE_FULL_MESSAGE)


def start_import_job(
    source_path: str,
    name: str = "",
    cleanup_upload_on_failure: bool = False,
    *,
    source_manifest: list[dict[str, Any]] | None = None,
    source_checksum_sha256: str = "",
    raster_kind: str = "imagery",
    resampling: str = "bilinear",
    default_rules: dict[str, Any] | None = None,
    uploader_id: int | None = None,
    access_group_ids: list[int] | None = None,
    category_code: str = "",
    created_by_id: int | None = None,
) -> RasterJob:
    from apps.raster.services.importer import (
        cleanup_uploaded_import_files,
        import_raster_file,
    )
    from apps.raster.services.serializers import serialize_raster_dataset
    from pathlib import Path

    job = _create_job("import", created_by_id=created_by_id)
    source = Path(source_path)

    def runner() -> None:
        try:
            _set_job_running(job.id, "开始导入栅格文件", 2, "validating")
            dataset = import_raster_file(
                source,
                name=name,
                progress=lambda text: _append_job(job.id, text),
                source_manifest=source_manifest,
                source_checksum_sha256=source_checksum_sha256,
                raster_kind=raster_kind,
                resampling=resampling,
                requested_default_rules=default_rules,
                uploader_id=uploader_id,
                access_group_ids=access_group_ids,
                category_code=category_code,
            )
            _finish_job(job.id, serialize_raster_dataset(dataset), "ready")
        except Exception as exc:
            if cleanup_upload_on_failure:
                try:
                    cleanup_uploaded_import_files(source)
                except Exception as cleanup_exc:
                    _append_job(job.id, f"失败文件清理未完成：{cleanup_exc}")
            _fail_job(job.id, str(exc))

    _submit_job(
        job,
        runner,
        on_rejected=(
            lambda: (
                cleanup_uploaded_import_files(source)
                if cleanup_upload_on_failure
                else None
            )
        ),
    )
    return job


def start_scan_job(created_by_id: int | None = None) -> RasterJob:
    from apps.raster.services.importer import scan_unprocessed_source_files
    from apps.projects.context import selected_project_id

    project_id = selected_project_id()

    reconcile_interrupted_jobs()
    with _LOCK:
        _prune_job_caches_locked()
        active_job = next(
            (
                candidate
                for candidate in _JOBS.values()
                if candidate.kind == "scan"
                and candidate.project_tag_id == project_id
                and candidate.status in {"queued", "running"}
            ),
            None,
        )
        if active_job is not None:
            return active_job
        job = _create_job(
            "scan",
            created_by_id=created_by_id,
            reconcile_restart=False,
        )

    def runner() -> None:
        try:
            _set_job_running(job.id, "开始扫描栅格源数据目录", 1)
            datasets = scan_unprocessed_source_files(
                progress=lambda text: _append_job(job.id, text)
            )
            _finish_job(
                job.id,
                {
                    "count": len(datasets),
                },
                "ready",
            )
        except Exception as exc:
            _fail_job(job.id, str(exc))

    _submit_job(job, runner)
    return job


def start_render_job(
    *,
    layer_id: int | None,
    dataset_id: int | None,
    rules: dict[str, Any] | None,
    created_by_id: int | None = None,
) -> RasterJob:
    from apps.catalog.models import MapLayer
    from apps.raster.models import RasterDataset
    from apps.raster.services.exceptions import RasterJobError, RasterRenderError
    from apps.raster.services.importer import dataset_for_layer
    from apps.raster.services.renderer import (
        build_static_xyz_tile_pyramid,
        register_tile_style,
    )

    refs = {
        key: value
        for key, value in {"layerId": layer_id, "datasetId": dataset_id}.items()
        if type(value) is int and value > 0
    }
    try:
        job = _create_job("render", created_by_id=created_by_id, input_refs=[refs])
    except RasterJobError as exc:
        raise RasterRenderError(str(exc)) from exc

    def runner() -> None:
        try:
            _set_job_running(job.id, "准备栅格符号化", 5)
            layer = MapLayer.objects.filter(pk=layer_id).first() if layer_id else None
            dataset = (
                RasterDataset.objects.filter(pk=dataset_id).first()
                if dataset_id
                else None
            )
            if dataset is None and layer is not None:
                dataset = dataset_for_layer(layer)
            if dataset is None:
                raise RasterRenderError("未找到可渲染的栅格数据集")
            render_rules = rules or (
                layer.raster_rules
                if layer and layer.raster_rules
                else dataset.default_rules
            )
            result = register_tile_style(dataset, render_rules)
            if dataset.raster_kind == RasterDataset.RasterKind.CATEGORICAL:
                _set_job_running(
                    job.id,
                    "生成 LUCC 最近邻静态瓦片金字塔",
                    10,
                    "tile-pyramid",
                )

                def report_pyramid_progress(done: int, total: int, zoom: int) -> None:
                    percent = 10 + round(done * 85 / max(1, total))
                    _set_job_running(
                        job.id,
                        f"LUCC 静态瓦片 z{zoom}：{done}/{total}",
                        percent,
                        "tile-pyramid",
                    )

                pyramid = build_static_xyz_tile_pyramid(
                    dataset,
                    str(result["styleHash"]),
                    progress=report_pyramid_progress,
                )
                if pyramid and pyramid.reused:
                    _set_job_running(
                        job.id,
                        "已复用完整 LUCC 静态瓦片金字塔",
                        95,
                        "tile-pyramid",
                    )
            _finish_job(job.id, result, "ready")
        except Exception as exc:
            _fail_job(job.id, str(exc))

    _submit_job(job, runner)
    return job


def start_export_job(
    *,
    items: list[dict[str, Any]],
    epsg: int | None,
    reproject: bool,
    clip_geometry: dict[str, Any] | None,
    vector_format: str,
    created_by_id: int | None = None,
) -> RasterJob:
    from tempfile import NamedTemporaryFile

    from apps.catalog.export import ExportError, export_layers_zip_to_path
    from apps.raster.services.exceptions import RasterJobError

    _cleanup_one_expired_export_artifact()
    input_refs = [
        {
            key: value
            for key, value in item.items()
            if key in {"resourceId", "layerId", "datasetId"}
            and type(value) is int
            and value > 0
        }
        for item in items
    ]
    try:
        job = _create_job("export", created_by_id=created_by_id, input_refs=input_refs)
    except RasterJobError as exc:
        raise ExportError(str(exc)) from exc

    def runner() -> None:
        artifact: Path | None = None
        try:
            _set_job_running(job.id, "准备导出数据", 1)
            with NamedTemporaryFile(
                prefix=f"layers-export-{job.id}-", suffix=".zip", delete=False
            ) as output:
                artifact = Path(output.name)
            export_layers_zip_to_path(
                items,
                epsg,
                output_path=artifact,
                reproject=reproject,
                clip_geometry=clip_geometry,
                vector_format=vector_format,
                progress=lambda text: _append_job(job.id, text),
            )
            _set_job_artifact(job.id, artifact)
            _finish_job(
                job.id,
                {
                    "filename": f"layers-export-{time.strftime('%Y%m%d%H%M%S')}.zip",
                    "downloadUrl": f"/api/catalog/export/jobs/{job.id}/download/",
                },
                "ready",
            )
        except Exception as exc:
            if artifact is not None:
                _delete_job_artifact(job.id, artifact)
            _fail_job(job.id, str(exc))

    _submit_job(job, runner)
    return job


def get_job_artifact_path(job_id: str) -> Path:
    from apps.raster.services.exceptions import RasterJobError

    job = get_job(job_id)
    if not job.artifact_path:
        raise RasterJobError("导出文件不存在或已过期")
    artifact = Path(job.artifact_path)
    if _job_artifact_is_expired(job):
        _delete_job_artifact(job.id, artifact)
        raise RasterJobError("导出文件不存在或已过期")
    return artifact


def open_job_artifact_for_download(job_id: str) -> _DeleteOnCloseFile:
    from apps.raster.services.exceptions import RasterJobError

    artifact = get_job_artifact_path(job_id)
    try:
        file_object = artifact.open("rb")
    except FileNotFoundError as exc:
        _delete_job_artifact(job_id, artifact)
        raise RasterJobError("导出文件不存在或已过期") from exc
    except OSError as exc:
        raise RasterJobError("导出文件暂时无法读取") from exc
    return _DeleteOnCloseFile(
        file_object,
        lambda: _delete_job_artifact(job_id, artifact),
    )


def _job_artifact_is_expired(
    job: RasterJob,
    *,
    now: float | None = None,
) -> bool:
    completed_at = job.finished_at or job.started_at
    return (now if now is not None else time.time()) - completed_at >= (
        EXPORT_ARTIFACT_TTL_SECONDS
    )


def _cleanup_one_expired_export_artifact(*, now=None) -> str | None:
    from apps.raster.models import RasterProcessingJob

    current_time = now or timezone.now()
    cutoff = current_time - timedelta(seconds=EXPORT_ARTIFACT_TTL_SECONDS)
    try:
        expired = (
            RasterProcessingJob.objects.filter(
                kind="export",
                finished_at__isnull=False,
                finished_at__lte=cutoff,
            )
            .exclude(artifact_path="")
            .order_by("finished_at", "id")
            .first()
        )
    except Exception:
        return None
    if expired is None:
        return None
    artifact = Path(expired.artifact_path)
    if not _delete_job_artifact(expired.id, artifact):
        return None
    return expired.id


def _delete_job_artifact(job_id: str, expected_path: Path) -> bool:
    try:
        expected_path.unlink(missing_ok=True)
    except OSError:
        return False
    _clear_job_artifact_record(job_id, expected_path)
    return True


def _clear_job_artifact_record(job_id: str, expected_path: Path) -> None:
    from apps.raster.models import RasterProcessingJob

    expected = str(expected_path)
    try:
        RasterProcessingJob.objects.filter(
            pk=job_id,
            artifact_path=expected,
        ).update(artifact_path="")
    except Exception:
        pass
    with _LOCK:
        cached = _JOBS.get(job_id)
        if cached is not None and cached.artifact_path == expected:
            cached.artifact_path = ""


def _persist_job(
    job: RasterJob, *, force: bool = False, require_persisted: bool = False
) -> None:
    from apps.raster.models import RasterProcessingJob

    now = time.time()
    with _LOCK:
        last_time, last_percent = _LAST_PERSIST.get(job.id, (0.0, -1))
    if not force and now - last_time < 2 and job.progress_percent - last_percent < 5:
        return
    attempts = 3 if force else 1
    for attempt in range(attempts):
        try:
            RasterProcessingJob.objects.update_or_create(
                pk=job.id,
                defaults={
                    "project_tag_id": job.project_tag_id,
                    "kind": job.kind,
                    "status": job.status,
                    "stage": job.stage,
                    "progress_percent": job.progress_percent,
                    "messages": list(job.messages),
                    "result": job.result,
                    "error": job.error,
                    "artifact_path": job.artifact_path,
                    "created_by_id": job.created_by_id,
                    "finished_at": datetime.fromtimestamp(
                        job.finished_at, tz=timezone.get_current_timezone()
                    )
                    if job.finished_at
                    else None,
                },
            )
            with _LOCK:
                _LAST_PERSIST[job.id] = (now, job.progress_percent)
                _prune_job_caches_locked(now=now)
            return
        except OperationalError:
            if attempt + 1 >= attempts:
                if require_persisted:
                    raise
                # 任务热状态仍保留在内存，数据库短暂繁忙不能中断 GDAL 处理。
                return
            close_old_connections()
            time.sleep(0.05 * (attempt + 1))
        except Exception:
            if require_persisted:
                raise
            return


def _load_persisted_job(job_id: str) -> RasterJob | None:
    from apps.raster.models import RasterProcessingJob

    try:
        record = RasterProcessingJob.objects.filter(pk=job_id).first()
    except Exception:
        return None
    if record is None:
        return None
    return RasterJob(
        id=record.id,
        kind=record.kind,
        status=record.status,
        stage=record.stage,
        progress_percent=record.progress_percent,
        messages=list(record.messages or []),
        result=record.result,
        error=record.error,
        artifact_path=record.artifact_path,
        started_at=record.started_at.timestamp(),
        finished_at=record.finished_at.timestamp() if record.finished_at else None,
        created_by_id=record.created_by_id,
        project_tag_id=record.project_tag_id,
    )


def _persisted_job_is_newer(cached: RasterJob, persisted: RasterJob) -> bool:
    status_rank = {"queued": 0, "running": 1, "ready": 2, "failed": 2}
    cached_rank = status_rank.get(cached.status, 0)
    persisted_rank = status_rank.get(persisted.status, 0)
    if persisted_rank != cached_rank:
        return persisted_rank > cached_rank
    if persisted.progress_percent != cached.progress_percent:
        return persisted.progress_percent > cached.progress_percent
    return len(persisted.messages) > len(cached.messages)


def _stage_from_message(message: str, current: str) -> str:
    lowered = message.lower()
    if "gdalinfo" in lowered or "校验" in message:
        return "validating"
    if "gdalwarp" in lowered or "预处理" in message:
        return "preprocessing"
    if "导入完成" in message or "登记" in message:
        return "publishing"
    return current or "running"
