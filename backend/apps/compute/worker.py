"""Durable database queue. One global heavy-work slot with fenced attempts."""

import json
import logging
import shutil
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import timedelta

from django.db import OperationalError, close_old_connections, transaction
from django.utils import timezone

from apps.core.heavy_work import heavy_work
from apps.core.storage import app_path
from apps.projects.context import ProjectScope, project_scope
from .access import require_actor
from .config import config
from .data import freeze_input, import_output, inspect_output
from .models import (
    ComputeTask,
    ComputeAttempt,
    ComputeOutput,
    ComputeImport,
    RuntimeLease,
)
from .packages import ComputeError, checksum, inspect_package
from .failures import generic_failure
from .quality import quality_metadata, read_quality_report
from .runtime import execute, inspect_runtime, stop_container, stop_native
from .services import ACTIVE, check_live_task

logger = logging.getLogger(__name__)
_last_cleanup = 0.0
IMPORT_BUSY_BACKOFF = (0.2, 0.5, 1.0)
IMPORT_BATCH_SIZE = 8
IMPORT_BATCH_SECONDS = 5.0


@contextmanager
def task_scope(task):
    with project_scope(
        ProjectScope((task.project_tag_id,), task.project_tag_id, task.owner_id)
    ):
        yield


def pulse(detail=None):
    values = {"heartbeat": timezone.now()}
    if detail is not None:
        values["detail"] = detail
    # A single write avoids upgrading a stale SQLite read transaction while
    # the background heartbeat and queue loop update the same lease.
    lease = RuntimeLease.objects.filter(name="worker")
    if not lease.update(**values):
        _, created = RuntimeLease.objects.get_or_create(name="worker", defaults=values)
        if not created:
            lease.update(**values)


def run_task(task):
    token = uuid.uuid4().hex
    if not ComputeTask.objects.filter(pk=task.pk, status="queued").update(
        status="validating",
        attempt_token=token,
        heartbeat=timezone.now(),
        started_at=timezone.now(),
        stage="固定输入并检查数据",
        progress=5,
        failure={},
    ):
        return
    task.refresh_from_db()
    attempt = ComputeAttempt.objects.create(
        task=task,
        token=token,
        container_name="gm-compute-" + token,
        runtime_digest=task.version.runtime_digest,
    )
    root = app_path("cache", "compute", str(task.id), token)
    root.mkdir(parents=True, exist_ok=False)
    inputs = root / "inputs"
    package = root / "algorithm"
    results = root / "results"
    for folder in (inputs, package, results):
        folder.mkdir()
    last_beat = [0.0]
    last_authorization = [0.0]
    preparation_started = time.monotonic()
    preparation_counts = {
        "materializedInputs": 0,
        "reusedInputs": 0,
        "copyOnWriteInputs": 0,
        "copiedInputs": 0,
    }

    def heartbeat(force=False, verify_inputs=False):
        if not force and time.monotonic() - last_beat[0] < 2:
            return
        last_beat[0] = time.monotonic()
        close_old_connections()
        live = ComputeTask.objects.get(pk=task.pk)
        if live.attempt_token != token or live.status not in ("validating", "running"):
            raise ComputeError("计算已取消或本次执行已失效")
        if verify_inputs or time.monotonic() - last_authorization[0] >= 2:
            check_live_task(task)
            last_authorization[0] = time.monotonic()
        ComputeTask.objects.filter(pk=task.pk, attempt_token=token).update(
            heartbeat=timezone.now()
        )
        pulse()

    destination = None

    def report_progress(stage, progress):
        ComputeTask.objects.filter(
            pk=task.pk, attempt_token=token, status="running"
        ).update(stage=stage, progress=progress)

    heartbeat.progress = report_progress
    try:
        heartbeat(True, verify_inputs=True)
        archive = app_path(task.version.package_path)
        if checksum(archive) != task.version.checksum:
            raise ComputeError("算法包校验失败，请管理员重新上传新版本")
        manifest = inspect_package(archive, package)
        if manifest != task.version.manifest:
            raise ComputeError("算法包与固定清单不一致")
        context = {
            "inputs": {},
            "parameters": task.parameters,
            "fieldMappings": task.field_mappings,
            "inputCollections": task.input_collections,
        }
        if (
            manifest.get("runtime") == "python-data-script-v1"
            or manifest.get("schemaVersion") == 2
        ):
            context["manifest"] = manifest
        total = 0
        for item in task.input_records.select_related("resource"):
            heartbeat(True)
            prepared = freeze_input(item, inputs)
            counts = prepared.pop("preparation")
            preparation_counts[
                "reusedInputs" if counts["reused"] else "materializedInputs"
            ] += 1
            preparation_counts[
                "copyOnWriteInputs"
                if counts["copyMethod"] == "copy_on_write"
                else "copiedInputs"
            ] += 1
            context["inputs"][item.key] = prepared
            total += item.snapshot["sizeBytes"]
            if total > config().input_mb * 1024**2:
                raise ComputeError("全部输入快照超过任务总大小限制")
        (inputs / "context.json").write_text(
            json.dumps(context, ensure_ascii=False), encoding="utf-8"
        )
        heartbeat(True, verify_inputs=True)
        preparation_seconds = time.monotonic() - preparation_started
        ComputeTask.objects.filter(
            pk=task.pk, attempt_token=token, status="validating"
        ).update(status="running", stage="隔离环境正在计算", progress=30)
        algorithm_started = time.monotonic()
        execute(attempt, package, inputs, results, manifest, heartbeat)
        algorithm_seconds = time.monotonic() - algorithm_started
        heartbeat(True, verify_inputs=True)
        validation_started = time.monotonic()
        ComputeTask.objects.filter(
            pk=task.pk, attempt_token=token, status="running"
        ).update(stage="检查并登记结果", progress=85)
        output_rows = []
        quality = quality_metadata(read_quality_report(results, manifest))
        script_contract = None
        if manifest.get("runtime") == "python-data-script-v1":
            from .script_contracts import read_contract

            script_contract = read_contract(manifest, task.parameters)
        for spec in manifest["outputs"]:
            path = results / spec["file"]
            if not path.exists() and not spec["required"]:
                continue
            metadata = (
                inspect_output(path, spec["kind"], contract=script_contract)
                if script_contract is not None
                else inspect_output(path, spec["kind"])
            )
            metadata.update(quality)
            heartbeat(True)
            output_rows.append((spec, path, metadata, checksum(path)))
        if not output_rows:
            raise ComputeError("算法没有产生任何可用结果")
        execution_metrics = {
            **preparation_counts,
            "inputPreparationSeconds": round(preparation_seconds, 6),
            "algorithmSeconds": round(algorithm_seconds, 6),
            "outputValidationSeconds": round(time.monotonic() - validation_started, 6),
        }
        for _, _, metadata, _ in output_rows:
            metadata["executionMetrics"] = execution_metrics
        destination = app_path(
            "projects",
            str(task.project_tag_id),
            "compute",
            "outputs",
            str(task.id),
            token,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        results.replace(destination)
        # CAS before output rows in one short transaction: cancelled/late work cannot publish.
        with transaction.atomic():
            if not ComputeTask.objects.filter(
                pk=task.pk, attempt_token=token, status="running"
            ).update(
                status="succeeded",
                stage="计算完成",
                progress=100,
                finished_at=timezone.now(),
                unread=True,
            ):
                raise ComputeError("计算已取消，结果未发布")
            check_live_task(task)
            for spec, path, metadata, digest in output_rows:
                final = destination / path.name
                ComputeOutput.objects.create(
                    task=task,
                    key=spec["key"],
                    label=spec["label"],
                    kind=spec["kind"],
                    file_name=path.name,
                    path=str(final.relative_to(app_path())).replace("\\", "/"),
                    size_bytes=final.stat().st_size,
                    checksum=digest,
                    metadata=metadata,
                )
            attempt.status = "succeeded"
    except Exception as exc:
        live = ComputeTask.objects.get(pk=task.pk)
        status = "cancelled" if live.status == "cancelling" else "failed"
        message = (
            str(exc)
            if isinstance(exc, ComputeError)
            else "数据准备、算法执行或结果检查失败；请检查输入格式，管理员可在服务日志中查看原因"
        )
        if not isinstance(exc, ComputeError):
            logger.exception("Compute task %s failed", task.pk)
        ComputeTask.objects.filter(
            pk=task.pk, attempt_token=token, status__in=ACTIVE
        ).update(
            status=status,
            stage="已取消" if status == "cancelled" else "计算失败",
            error=message,
            failure={}
            if status == "cancelled"
            else getattr(exc, "failure", None)
            or generic_failure("PLATFORM_VALIDATION"),
            finished_at=timezone.now(),
            unread=True,
        )
        attempt.status = status
        if destination and destination.exists():
            shutil.rmtree(destination)
    finally:
        attempt.finished_at = timezone.now()
        attempt.save(update_fields=["status", "finished_at"])
        shutil.rmtree(root, ignore_errors=True)


def recover():
    # Called only while holding both worker ownership and the global heavy-work lock.
    for task in ComputeTask.objects.filter(
        status__in=("validating", "running", "cancelling")
    ):
        attempt = task.attempts.order_by("-id").first()
        if attempt:
            if config().mode == "native":
                stop_native(app_path("cache", "compute", str(task.id), attempt.token))
            else:
                stop_container(attempt.container_name)
            attempt.status = "interrupted"
            attempt.finished_at = timezone.now()
            attempt.save(update_fields=["status", "finished_at"])
        retry = (
            task.status != "cancelling"
            and task.version.manifest.get("deterministic")
            and task.attempts.count() < 2
        )
        task.status = (
            "queued"
            if retry
            else ("cancelled" if task.status == "cancelling" else "interrupted")
        )
        task.stage = "上次执行中断，等待重新执行" if retry else "执行已中断，可重试"
        task.attempt_token = ""
        task.finished_at = None if retry else timezone.now()
        task.failure = (
            generic_failure("PLATFORM_INTERRUPTED")
            if task.status == "interrupted"
            else {}
        )
        task.save(
            update_fields=["status", "stage", "attempt_token", "finished_at", "failure"]
        )
    ComputeImport.objects.filter(status="running").update(
        status="queued", error="上次入库中断，正在恢复"
    )


def clean_expired(*, force=False):
    from apps.agent.geology_generic import MULTI_FAMILY
    from apps.agent.models import AgentWorkflowStep

    global _last_cleanup
    if not force and time.monotonic() - _last_cleanup < 60:
        return
    _last_cleanup = time.monotonic()
    cutoff = timezone.now() - timedelta(days=config().retention_days)
    retained_tasks = AgentWorkflowStep.objects.filter(
        workflow__workflow_type__in=MULTI_FAMILY,
        compute_task_id__isnull=False,
    ).values("compute_task_id")
    for output in (
        ComputeOutput.objects.filter(expired=False, created_at__lt=cutoff)
        .exclude(import_record__status__in=("queued", "running"))
        .exclude(task_id__in=retained_tasks)[:50]
    ):
        path = app_path(output.path)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Result cleanup deferred for output %s", output.id)
            continue
        output.expired = True
        output.save(update_fields=["expired"])
    # Scratch is private cache and can be removed after interrupted attempts.
    scratch = app_path("cache", "compute")
    if scratch.exists():
        for directory in scratch.glob("*/*"):
            if (
                directory.is_dir()
                and not directory.is_symlink()
                and directory.stat().st_mtime < time.time() - 86400
            ):
                target = app_path(str(directory.relative_to(app_path())))
                shutil.rmtree(target, ignore_errors=True)

    from .input_versions import clean_versions
    from .result_reads import clean_read_indexes
    from .gpu_runtime import clean_stage_caches

    try:
        clean_versions(config().input_mb * 1024**2, config().retention_days)
        clean_read_indexes(config().input_mb * 1024**2, config().retention_days)
        clean_stage_caches(cutoff.timestamp())
    except (OSError, ComputeError):
        logger.warning("Input version cache cleanup deferred")


def _sqlite_contention(exc):
    """Use SQLite result codes, including BUSY_SNAPSHOT; never error wording."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, (OperationalError, sqlite3.OperationalError)):
            code = getattr(exc, "sqlite_errorcode", 0)
            if code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                return True
        exc = exc.__cause__
    return False


def process_import(record):
    from apps.agent.compute_tools import validate_import_intent

    # The worker still owns the heavy-work lock during this bounded retry loop.
    # Each attempt reuses storage_key, refreshes intent/permissions and claims the
    # same queue row; a successful partial import never creates another layer.
    for attempt in range(len(IMPORT_BUSY_BACKOFF) + 1):
        if not ComputeImport.objects.filter(pk=record.pk, status="queued").update(
            status="running", heartbeat=timezone.now()
        ):
            return
        try:
            record = ComputeImport.objects.select_related(
                "output__task__version__algorithm", "requested_by"
            ).get(pk=record.pk)
            require_actor(
                record.requested_by,
                record.output.task.project_tag_id,
                "catalog.add_dataresource",
            )
            validate_import_intent(record)
            resource = import_output(record)
            record.refresh_from_db()
            if record.status == "failed":
                return
            ComputeImport.objects.filter(pk=record.pk).update(
                status="ready", resource=resource, error="", heartbeat=timezone.now()
            )
            if (
                record.output.task.version.algorithm.identifier
                == "landcover-unet-infer"
            ):
                from apps.ecology.landcover import register_import

                register_import(record.pk)
            return
        except Exception as exc:
            busy = _sqlite_contention(exc)
            if busy and attempt < len(IMPORT_BUSY_BACKOFF):
                if not ComputeImport.objects.filter(
                    pk=record.pk, status="running"
                ).update(
                    status="queued",
                    error="入库数据库暂忙，正在自动重试；无需重新计算",
                    heartbeat=timezone.now(),
                ):
                    return
                logger.warning(
                    "Compute import %s database busy; retry %s/%s",
                    record.pk,
                    attempt + 1,
                    len(IMPORT_BUSY_BACKOFF),
                )
                time.sleep(IMPORT_BUSY_BACKOFF[attempt])
                continue
            message = (
                "入库数据库持续繁忙，自动重试已用完；可重试入库，无需重新计算"
                if busy
                else str(exc)
                if isinstance(exc, ComputeError)
                else "结果入库失败，请检查数据条件并重试；无需重新计算"
            )
            if not isinstance(exc, ComputeError):
                logger.exception("Compute import %s failed", record.pk)
            ComputeImport.objects.filter(pk=record.pk).update(
                status="failed", error=message, heartbeat=timezone.now()
            )
            return


def worker_tick(*, recovered=False):
    state = inspect_runtime()
    pulse(state)
    with project_scope(None), heavy_work(wait=False) as acquired:
        if not acquired:
            return recovered
        if not recovered:
            if (
                not state["ready"]
                and ComputeTask.objects.filter(
                    status__in=("validating", "running", "cancelling")
                ).exists()
            ):
                return False
            recover()
            recovered = True
        clean_expired()
        items = list(
            ComputeImport.objects.filter(status="queued")
            .select_related("output__task__version__algorithm", "requested_by")
            .order_by("id")[:IMPORT_BATCH_SIZE]
        )
        if items:
            started = time.monotonic()
            for item in items:
                with task_scope(item.output.task):
                    process_import(item)
                if time.monotonic() - started >= IMPORT_BATCH_SECONDS:
                    break
            return recovered
        if state["ready"]:
            task = (
                ComputeTask.objects.filter(status="queued")
                .select_related("version__algorithm", "owner")
                .order_by("created_at")
                .first()
            )
            if task:
                with task_scope(task):
                    run_task(task)
    return recovered
