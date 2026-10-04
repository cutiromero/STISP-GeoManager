"""Durable database queue. One global heavy-work slot with fenced attempts."""

import json
import logging
import shutil
import time
import uuid
from contextlib import contextmanager
from datetime import timedelta

from django.db import close_old_connections, transaction
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
from .quality import quality_metadata, read_quality_report
from .runtime import execute, inspect_runtime, stop_container, stop_native
from .services import ACTIVE, check_live_task

logger = logging.getLogger(__name__)
_last_cleanup = 0.0


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

    def heartbeat(force=False):
        if not force and time.monotonic() - last_beat[0] < 2:
            return
        last_beat[0] = time.monotonic()
        close_old_connections()
        live = ComputeTask.objects.get(pk=task.pk)
        if live.attempt_token != token or live.status not in ("validating", "running"):
            raise ComputeError("计算已取消或本次执行已失效")
        check_live_task(task)
        ComputeTask.objects.filter(pk=task.pk, attempt_token=token).update(
            heartbeat=timezone.now()
        )
        pulse()

    destination = None
    try:
        heartbeat(True)
        archive = app_path(task.version.package_path)
        if checksum(archive) != task.version.checksum:
            raise ComputeError("算法包校验失败，请管理员重新上传新版本")
        manifest = inspect_package(archive, package)
        if manifest != task.version.manifest:
            raise ComputeError("算法包与固定清单不一致")
        context = {"inputs": {}, "parameters": task.parameters}
        total = 0
        for item in task.input_records.select_related("resource"):
            heartbeat(True)
            context["inputs"][item.key] = freeze_input(item, inputs)
            total += item.snapshot["sizeBytes"]
            if total > config().input_mb * 1024**2:
                raise ComputeError("全部输入快照超过任务总大小限制")
        (inputs / "context.json").write_text(
            json.dumps(context, ensure_ascii=False), encoding="utf-8"
        )
        heartbeat(True)
        ComputeTask.objects.filter(
            pk=task.pk, attempt_token=token, status="validating"
        ).update(status="running", stage="隔离环境正在计算", progress=30)
        execute(attempt, package, inputs, results, manifest, heartbeat)
        heartbeat(True)
        ComputeTask.objects.filter(
            pk=task.pk, attempt_token=token, status="running"
        ).update(stage="检查并登记结果", progress=85)
        output_rows = []
        quality = quality_metadata(read_quality_report(results, manifest))
        for spec in manifest["outputs"]:
            path = results / spec["file"]
            if not path.exists() and not spec["required"]:
                continue
            metadata = inspect_output(path, spec["kind"])
            metadata.update(quality)
            heartbeat(True)
            output_rows.append((spec, path, metadata, checksum(path)))
        if not output_rows:
            raise ComputeError("算法没有产生任何可用结果")
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
        task.save(update_fields=["status", "stage", "attempt_token", "finished_at"])
    ComputeImport.objects.filter(status="running").update(
        status="queued", error="上次入库中断，正在恢复"
    )


def clean_expired(*, force=False):
    global _last_cleanup
    if not force and time.monotonic() - _last_cleanup < 60:
        return
    _last_cleanup = time.monotonic()
    cutoff = timezone.now() - timedelta(days=config().retention_days)
    for output in ComputeOutput.objects.filter(
        expired=False, created_at__lt=cutoff
    ).exclude(import_record__status__in=("queued", "running"))[:50]:
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


def process_import(record):
    from apps.agent.compute_tools import validate_import_intent

    if not ComputeImport.objects.filter(pk=record.pk, status="queued").update(
        status="running", heartbeat=timezone.now()
    ):
        return
    try:
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
        # import_output may return an already committed resource after interruption.
        ComputeImport.objects.filter(pk=record.pk).update(
            status="ready", resource=resource, error="", heartbeat=timezone.now()
        )
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, ComputeError)
            else "结果入库失败，请检查数据条件并重试；无需重新计算"
        )
        if not isinstance(exc, ComputeError):
            logger.exception("Compute import %s failed", record.pk)
        ComputeImport.objects.filter(pk=record.pk).update(
            status="failed", error=message, heartbeat=timezone.now()
        )


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
        item = (
            ComputeImport.objects.filter(status="queued")
            .select_related("output__task__version__algorithm", "requested_by")
            .order_by("id")
            .first()
        )
        if item:
            with task_scope(item.output.task):
                process_import(item)
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
