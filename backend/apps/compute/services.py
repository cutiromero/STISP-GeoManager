import hashlib
import json
import math
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import DataResource
from apps.catalog.permissions import user_can_access
from apps.core.display_text import display_text
from .access import permission, project_id, require_actor
from .config import config
from .data import candidate
from .models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeTask,
    ComputeInput,
    RuntimeLease,
)
from .packages import ComputeError, clean_text

ACTIVE = ("queued", "validating", "running", "cancelling")


def runtime_state(user):
    from .access import PERMISSIONS

    lease = RuntimeLease.objects.filter(pk="worker").first()
    online = bool(
        lease
        and lease.heartbeat
        and lease.heartbeat > timezone.now() - timedelta(seconds=30)
    )
    runtime = lease.detail if online else {}
    available = bool(online and runtime.get("ready"))
    cfg = config()
    permissions = {p: permission(user, p) for p in PERMISSIONS}
    permissions.update(
        download_outputs=permission(user, "catalog.export_dataresource"),
        import_outputs=permission(user, "catalog.add_dataresource"),
    )
    return {
        "available": available,
        "workerOnline": online,
        "detail": "计算环境就绪"
        if available
        else runtime.get("detail", "计算工作进程尚未启动，请联系管理员"),
        "runtimes": [runtime] if runtime else [],
        "limits": {
            "userQueued": cfg.user_queue,
            "globalQueued": cfg.global_queue,
            "inputMiB": cfg.input_mb,
            "outputMiB": cfg.output_mb,
            "timeoutSeconds": cfg.timeout_seconds,
            "retentionDays": cfg.retention_days,
        },
        "permissions": permissions,
    }


def allowed_algorithms():
    # Explicit public-tool reuse, independent of private input/output managers.
    return AlgorithmResource._base_manager.filter(
        project_tag_id__in={1, project_id()}, project_tag__is_active=True
    )


def agent_algorithm_allowed(version):
    """Missing flags retain legacy published algorithm behavior."""
    return version.manifest.get("agent", {}).get("enabled", True) is True


def request_output_import(user, output, name="", *, request_source=""):
    from .access import task_access
    from .models import ComputeImport
    from apps.audit.service import log_operation

    task_access(output.task, user)
    require_actor(user, output.task.project_tag_id, "catalog.add_dataresource")
    if output.task.status != "succeeded":
        raise ComputeError("计算任务尚未成功完成")
    if output.expired or output.kind == "archive":
        raise ComputeError("结果已过期或为多文件压缩包，不能自动入库")
    if request_source:
        from .quality import require_automatic_quality

        require_automatic_quality(output)
    explicit_name = name not in ("", None)
    legacy_default_name = output.task.name + " · " + output.label
    if not explicit_name:
        # An output has a stable, unique ID even when tasks and labels repeat.
        # Keep it outside the clipped human-readable part of a long name.
        suffix = f" [{output.task_id.hex[:8]}/{output.id}]"
        name = display_text(legacy_default_name)[: 160 - len(suffix)].rstrip() + suffix
    else:
        name = display_text(name)
    name = clean_text(name, 160, "入库名称")
    with transaction.atomic():
        record, created = ComputeImport.objects.get_or_create(
            output=output,
            defaults={
                "name": name,
                "requested_by": user,
                "request_source": request_source,
            },
        )
        if not created and record.status == "deleted":
            raise ComputeError(
                "该入库结果已由用户删除；如需恢复，可下载尚未过期的计算输出后重新导入。",
                409,
            )
        if not created and record.status in {"queued", "failed"}:
            record.status, record.error = "queued", ""
            if not explicit_name and record.name not in {
                legacy_default_name,
                display_text(legacy_default_name),
            }:
                # Omitted names preserve an earlier custom name. Legacy automatic
                # names are upgraded so a duplicate-name failure can be retried.
                name = display_text(record.name)
            record.requested_by, record.name = user, name
            record.request_source = request_source
            record.save(
                update_fields=[
                    "status",
                    "error",
                    "requested_by",
                    "name",
                    "request_source",
                ]
            )
    if created:
        log_operation(
            user,
            "compute",
            "import",
            "success",
            target_type="compute_output",
            target_id=output.id,
            message=name,
        )
    return record


def validate_submission(user, body):
    require_actor(user, project_id(), "submit_task", "core.browse_data")
    name = clean_text(body.get("name"), 160, "任务名称")
    key = clean_text(body.get("idempotencyKey"), 80, "幂等键")
    if type(body.get("versionId")) is not int:
        raise ComputeError("请选择算法版本")
    version = (
        AlgorithmVersion.objects.select_related("algorithm")
        .filter(
            pk=body["versionId"],
            algorithm__in=allowed_algorithms(),
            algorithm__enabled=True,
        )
        .first()
    )
    trial = body.get("trial", False)
    if type(trial) is not bool:
        raise ComputeError("trial 必须为布尔值")
    if not version or version.status == "archived":
        raise ComputeError("算法版本不存在、已停用或无权使用", 404)
    if trial:
        if (
            not permission(user, "manage_algorithms")
            or version.algorithm.project_tag_id != project_id()
        ):
            raise ComputeError("只能在所属项目内由算法维护者试运行", 403)
    elif version.status != "published":
        raise ComputeError("请使用已发布算法版本", 400)
    inputs = body.get("inputs")
    params = body.get("parameters")
    if not isinstance(inputs, dict) or not isinstance(params, dict):
        raise ComputeError("inputs 与 parameters 必须为对象")
    manifest = version.manifest
    if set(inputs) - {item["key"] for item in manifest["inputs"]} or set(params) - {
        p["key"] for p in manifest["parameters"]
    }:
        raise ComputeError("输入或参数包含未声明字段")
    resources = []
    metadata = {}
    for spec in manifest["inputs"]:
        rid = inputs.get(spec["key"])
        if rid is None and not spec["required"]:
            continue
        if type(rid) is not int:
            raise ComputeError("请选择输入数据：" + spec["label"])
        resource = DataResource.objects.filter(
            pk=rid, status="active", project_tag_id=project_id()
        ).first()
        if not resource:
            raise ComputeError("输入数据不存在、已停用或不属于当前项目", 404)
        if not user_can_access(resource, user):
            raise ComputeError("输入数据不存在、已停用或无权访问", 404)
        if resource.data_type != spec["kind"]:
            raise ComputeError(spec["label"] + "的数据类型不符合算法要求")
        info = candidate(resource)
        if info["sizeBytes"] > config().input_mb * 1024**2:
            raise ComputeError("输入超过平台大小限制")
        if info["bands"] < spec.get("minBands", 0):
            raise ComputeError(spec["label"] + "的波段数量不足")
        if spec.get("geometryTypes") and not set(info["geometryTypes"]) <= set(
            spec["geometryTypes"]
        ):
            raise ComputeError(spec["label"] + "的几何类型不匹配")
        metadata[spec["key"]] = info
        resources.append((spec["key"], resource, info))
    normalized = {}
    for p in manifest["parameters"]:
        when = p.get("when")
        if when and normalized.get(when["key"]) != when["equals"]:
            continue
        value = params.get(p["key"], p.get("default"))
        if value is None:
            if p["required"]:
                raise ComputeError("请填写参数：" + p["label"])
            continue
        kind = p["type"]
        if kind in {"number", "integer", "band"}:
            if (
                type(value) not in {int, float}
                or not math.isfinite(value)
                or (kind != "number" and type(value) is not int)
            ):
                raise ComputeError(
                    p["label"]
                    + "必须是有效数字"
                    + ("（整数）" if kind != "number" else "")
                )
            if value < p.get("min", -math.inf) or value > p.get("max", math.inf):
                raise ComputeError(p["label"] + "超出允许范围")
        elif kind == "boolean":
            if type(value) is not bool:
                raise ComputeError(p["label"] + "必须为布尔值")
        elif not isinstance(value, str) or len(value) > 2000:
            raise ComputeError(p["label"] + "必须为不超过2000字的文字")
        if kind == "enum" and value not in p["choices"]:
            raise ComputeError(p["label"] + "不在选项内")
        if kind in {"field", "band"}:
            source = metadata.get(p["input"])
            if (
                not source
                or (kind == "field" and value not in source["fields"])
                or (kind == "band" and not 1 <= value <= source["bands"])
            ):
                raise ComputeError(p["label"] + "不属于选中的数据")
        normalized[p["key"]] = value
    canonical = {
        "name": name,
        "versionId": version.id,
        "inputs": inputs,
        "parameters": normalized,
        "trial": trial,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return {
        "name": name,
        "key": key,
        "version": version,
        "parameters": normalized,
        "resources": resources,
        "digest": digest,
        "trial": trial,
    }


def submit(user, body, retry_of=None):
    data = validate_submission(user, body)
    existing = ComputeTask.objects.filter(
        owner=user, idempotency_key=data["key"]
    ).first()
    if existing:
        if existing.request_hash != data["digest"]:
            raise ComputeError("幂等键已用于其他请求，请重新提交", 409)
        return existing
    if not runtime_state(user)["available"]:
        raise ComputeError(
            "隔离计算环境未就绪，当前无法提交计算。请联系管理员完成部署。", 503
        )
    cfg = config()
    with transaction.atomic():
        # Acquire SQLite write reservation before queue counts and insertion.
        RuntimeLease.objects.filter(pk="queue").update(heartbeat=timezone.now())
        existing = ComputeTask.objects.filter(
            owner=user, idempotency_key=data["key"]
        ).first()
        if existing:
            if existing.request_hash != data["digest"]:
                raise ComputeError("幂等键冲突", 409)
            return existing
        if (
            ComputeTask._base_manager.filter(status="queued").count()
            >= cfg.global_queue
            or ComputeTask._base_manager.filter(status="queued", owner=user).count()
            >= cfg.user_queue
        ):
            raise ComputeError("计算等待队列已满，请等待现有任务完成", 409)
        version = data["version"]
        if not version.runtime_digest:
            runtime = RuntimeLease.objects.get(pk="worker").detail
            AlgorithmVersion.objects.filter(pk=version.pk, runtime_digest="").update(
                runtime_digest=runtime["imageDigest"]
            )
            version.refresh_from_db()
        task = ComputeTask.objects.create(
            name=data["name"],
            owner=user,
            version=version,
            parameters=data["parameters"],
            idempotency_key=data["key"],
            request_hash=data["digest"],
            trial=data["trial"],
            retry_of=retry_of,
        )
        ComputeInput.objects.bulk_create(
            [
                ComputeInput(
                    task=task,
                    key=key,
                    resource=r,
                    snapshot={**info, "updatedAt": r.updated_at.isoformat()},
                )
                for key, r, info in data["resources"]
            ]
        )
    return task


def check_live_task(task):
    user = get_user_model().objects.get(pk=task.owner_id)
    require_actor(user, task.project_tag_id, "submit_task", "core.browse_data")
    version = AlgorithmVersion.objects.select_related("algorithm").get(
        pk=task.version_id
    )
    if (
        not version.algorithm.enabled
        or version.status == "archived"
        or (not task.trial and version.status != "published")
    ):
        raise ComputeError("算法或版本已停用，计算已停止")
    if task.trial:
        require_actor(user, task.project_tag_id, "manage_algorithms")
    for record in task.input_records.select_related("resource"):
        if (
            record.resource is None
            or record.resource.project_tag_id != task.project_tag_id
            or record.resource.status != "active"
        ):
            raise ComputeError("输入数据已停用，计算已停止")


def task_action(task, user, action):
    from .access import task_access

    task_access(task, user)
    if action == "read":
        task.unread = False
        task.save(update_fields=["unread"])
    elif action == "cancel":
        require_actor(
            user,
            task.project_tag_id,
            "manage_tasks" if task.owner_id != user.id else "cancel_own_task",
        )
        ComputeTask.objects.filter(pk=task.pk, status="queued").update(
            status="cancelled", stage="已取消", finished_at=timezone.now(), unread=True
        )
        ComputeTask.objects.filter(
            pk=task.pk, status__in=("validating", "running")
        ).update(status="cancelling", stage="正在停止计算")
        task.refresh_from_db()
    elif action == "retry":
        if task.status not in {"failed", "interrupted", "cancelled"}:
            raise ComputeError("仅失败、中断或取消的任务可以重试", 409)
        if task.input_records.filter(resource__isnull=True).exists():
            raise ComputeError("历史输入数据已删除，请重新选择数据创建任务。", 409)
        return submit(
            user,
            {
                "name": task.name,
                "versionId": task.version_id,
                "inputs": {r.key: r.resource_id for r in task.input_records.all()},
                "parameters": task.parameters,
                "trial": task.trial,
                "idempotencyKey": uuid.uuid4().hex,
            },
            retry_of=task,
        )
    else:
        raise ComputeError("不支持该任务操作")
    return task
