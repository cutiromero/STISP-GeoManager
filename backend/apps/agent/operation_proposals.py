"""Bounded operation previews; model output never constitutes a user decision."""

from datetime import timedelta
import hashlib
import hmac
import json
from pathlib import Path
import uuid

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.audit.service import log_operation
from apps.catalog.models import DataResource, MapComposition, ResultArtifact
from apps.catalog.publication_commands import publication_target, publish
from apps.compute.packages import ComputeError
from apps.core.permissions import has_feature_perm
from apps.core.storage import app_path
from apps.projects.context import selected_project_id
from apps.raster.services.executor_identity import current_identity, alive
from .models import AgentAttachment, AgentOperation, AgentRun
from .policy import fresh_user, require_access

# Configuration: previews and imports are deliberately bounded, never server paths.
PREVIEW_TTL = timedelta(minutes=15)
MAX_PROPOSALS_PER_RUN = 8
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 5000


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def authorize(run, user, *, creating=False):
    actor = fresh_user(user.pk)
    policy = require_access(actor, "agent", run.model)
    if (
        run.owner_id != actor.pk
        or run.project_tag_id != selected_project_id()
        or run.conversation.mode != "agent"
    ):
        raise ComputeError("操作不属于当前用户或项目", 404)
    from .selections import check_history_evidence

    check_history_evidence(run, actor, policy)
    if run.cancel_requested or run.status in {"cancelled", "interrupted"}:
        if creating:
            raise ComputeError("本轮已停止，不能创建或确认新操作", 409)
    if creating and run.status != "running":
        raise ComputeError("只有执行中的Agent运行可以准备操作", 409)
    return actor, policy


def attachment_source(run, actor, identity):
    if identity not in run.attachment_ids:
        raise ComputeError("只能导入本轮明确附带的文件", 403)
    item = AgentAttachment.objects.filter(
        pk=identity, owner=actor, conversation_id=run.conversation_id
    ).first()
    if item is None or Path(item.name).suffix.lower() != ".csv":
        raise ComputeError(
            "当前导入工具仅支持本轮CSV附件；其他格式使用平台标准导入入口"
        )
    root = app_path("projects", str(run.project_tag_id), "agent-attachments").resolve()
    path = app_path(item.path)
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ComputeError("附件来源无法核实", 403)
    try:
        before = path.stat()
        if not 0 < before.st_size <= MAX_IMPORT_BYTES:
            raise ComputeError("CSV导入最多5MiB")
        with path.open("rb") as stream:
            raw = stream.read(MAX_IMPORT_BYTES + 1)
        after = path.stat()
    except OSError as error:
        raise ComputeError("附件文件不存在或无法读取", 404) from error
    if (
        before.st_mtime_ns != after.st_mtime_ns
        or len(raw) != item.size_bytes
        or hashlib.sha256(raw).hexdigest() != item.checksum
    ):
        raise ComputeError("附件文件已变化，请重新上传并预览", 409)
    return item, raw


def import_preview(run, actor, payload):
    from apps.catalog.importer import read_uploaded_table, validate_coordinate_columns

    if not has_feature_perm(actor, "catalog.add_dataresource"):
        raise ComputeError("没有新增资料权限", 403)
    policy = require_access(actor, "agent", run.model)
    if not policy.get("allowAttachments") or not policy.get("allowDocuments"):
        raise ComputeError("附件或文档读取未开启", 403)
    source, raw = attachment_source(run, actor, payload["attachmentId"])
    file = SimpleUploadedFile(source.name, raw, content_type="text/csv")
    frame = read_uploaded_table(file)
    if not 0 < len(frame) <= MAX_IMPORT_ROWS or len(frame.columns) > 200:
        raise ComputeError("导入限1至5000行、最多200列，请在标准导入页面处理更大资料")
    mode = payload["importMode"]
    if mode == "geographic":
        lon, lat = payload.get("longitudeColumn"), payload.get("latitudeColumn")
        if lon not in frame.columns or lat not in frame.columns or lon == lat:
            raise ComputeError("地理导入须指定不同的真实经度列和纬度列")
        issues = validate_coordinate_columns(frame, lon, lat)
        if any(
            item.blocking or item.code == "coordinate_uncertainty" for item in issues
        ):
            raise ComputeError(
                "坐标校验未通过，请在标准导入页面核对坐标，不能由Agent忽略问题"
            )
    from apps.catalog.importer import duplicate_target_for_display_name

    if duplicate_target_for_display_name(payload["name"]):
        raise ComputeError(
            "已有同名资料，请使用明确的新名称；该工具不覆盖或替换旧资料", 409
        )
    summary = {
        "title": "新增资料：" + payload["name"],
        "target": source.name,
        "scope": "当前项目，仅本人可见",
        "effect": f"新增独立{'地理' if mode == 'geographic' else '非地理'}数据表，{len(frame)}行、{len(frame.columns)}列；不修改附件和已有表",
        "details": [
            "字段：" + "、".join(map(str, frame.columns))[:1500],
            "坐标：EPSG:4326，经纬度按标准导入服务转换"
            if mode == "geographic"
            else "不生成地理坐标",
        ],
    }
    return (
        summary,
        {
            "attachmentId": source.pk,
            "checksum": source.checksum,
            "name": source.name,
            "size": len(raw),
            "rows": len(frame),
            "columns": list(frame.columns),
        },
        raw,
    )


def publication_preview(run, actor, payload):
    if payload["kind"] == "result" and "versionNumber" in payload:
        raise ComputeError("成果文件使用当前修订，不接受专题图版本号")
    item, version, groups, files = publication_target(
        actor,
        payload["kind"],
        payload["objectId"],
        payload.get("audienceGroupIds", []),
        payload.get("versionNumber"),
    )
    if item.owner_id != actor.pk:
        raise ComputeError("Agent只能准备发布本人的成果", 403)
    group_names = list(
        Group.objects.filter(pk__in=groups)
        .order_by("id")
        .values_list("name", flat=True)
    )
    summary = {
        "title": "发布成果：" + item.name,
        "target": item.name,
        "scope": "当前项目中具备查看权限的用户"
        if not groups
        else "当前项目角色：" + "、".join(group_names),
        "effect": "将指定成果设为已发布；不授予项目或原始资料访问权限",
        "details": [
            "对象修订：" + item.updated_at.isoformat(),
            "版本：" + str(version.version_number) if version else "成果文件当前修订",
        ],
    }
    file_ids = [
        (
            Path(path).name,
            app_path(path).stat().st_size,
            app_path(path).stat().st_mtime_ns,
        )
        for path in files
    ]
    binding = {
        "objectId": item.pk,
        "updatedAt": item.updated_at.isoformat(),
        "groups": groups,
        "groupNames": group_names,
        "files": file_ids,
        "versionId": version.pk if version else None,
    }
    return summary, binding, None


def share_preview(run, actor, payload):
    from apps.catalog.sharing import check_request, object_name
    from apps.catalog.share_access import validate_share

    kind, identity, recipient = check_request(payload)
    item = validate_share(kind, identity, actor, recipient, run.project_tag_id)
    owner_id = item.task.owner_id if kind == "compute_output" else item.owner_id
    if owner_id != actor.pk:
        raise ComputeError("Agent只能准备分享本人的对象", 403)
    name = object_name(kind, item)
    summary = {
        "title": "邀请分享：" + name,
        "target": name,
        "scope": "接收人：" + recipient.username,
        "effect": "发送只读分享邀请，等待对方接受；不授予项目或底层资料权限",
        "details": ["单个对象，不包含编辑或科学批准权限"],
    }
    if kind == "workspace":
        revision = [item.updated_at.isoformat(), digest(item.snapshot)]
    elif kind == "composition":
        revision = [
            item.updated_at.isoformat(),
            item.project.updated_at.isoformat(),
            list(
                item.versions.order_by("pk").values_list(
                    "pk", "version_number", "snapshot_checksum"
                )
            ),
        ]
    else:
        stat = app_path(item.path).stat()
        revision = [
            item.task.status,
            item.expired,
            item.path,
            stat.st_size,
            stat.st_mtime_ns,
            list(
                item.task.input_records.order_by("pk").values_list(
                    "resource_id", "checksum"
                )
            ),
        ]
    return (
        summary,
        {
            "objectId": identity,
            "kind": kind,
            "revision": revision,
            "recipientId": recipient.pk,
            "username": recipient.username,
        },
        None,
    )


def inspect(run, actor, kind, payload):
    from apps.catalog.importer import ImportDataError

    try:
        return {
            "import": import_preview,
            "publish": publication_preview,
            "share": share_preview,
        }[kind](run, actor, payload)
    except ImportDataError as error:
        raise ComputeError(str(error)) from error


def public(operation):
    status = operation.status
    if status == "pending" and operation.expires_at <= timezone.now():
        status = "expired"
    if status == "executing" and alive(operation.execution_identity) is False:
        AgentOperation.objects.filter(pk=operation.pk, status="executing").update(
            status="interrupted"
        )
        status = "interrupted"
    stopped = operation.run.cancel_requested or operation.run.status in {
        "cancelled",
        "interrupted",
    }
    return {
        "id": str(operation.pk),
        "runId": operation.run_id,
        "projectId": operation.project_tag_id,
        "kind": operation.kind,
        "status": status,
        "digest": operation.digest,
        "preview": operation.preview,
        "result": operation.result,
        "expiresAt": operation.expires_at.isoformat(),
        "createdAt": operation.created_at.isoformat(),
        "decidedAt": operation.decided_at.isoformat() if operation.decided_at else None,
        "canConfirm": status == "pending" and not stopped,
        "detail": "本轮已停止，不能执行待确认操作"
        if status == "pending" and stopped
        else "执行进程已结束，操作结果需核对，不能盲目重复提交"
        if status == "interrupted"
        else "已受理，正在执行；重复确认不会再次执行"
        if status == "executing"
        else "预览已过期，请重新准备"
        if status == "expired"
        else str(operation.result.get("error", {}).get("detail", ""))
        if status == "failed"
        else "",
    }


def read_operation(operation, user):
    actor, policy = authorize(operation.run, user)
    if operation.kind == "import":
        if operation.status == "confirmed":
            from apps.catalog.permissions import user_can_access

            resource = DataResource.objects.filter(
                pk=operation.result.get("resourceId"), status="active"
            ).first()
            if resource is None or not user_can_access(resource, actor):
                raise ComputeError("新增资料不存在或当前无权访问", 403)
        else:
            if (
                not has_feature_perm(actor, "catalog.add_dataresource")
                or not policy.get("allowAttachments")
                or not policy.get("allowDocuments")
            ):
                raise ComputeError("新增资料或附件访问权限已变化", 403)
            source = AgentAttachment.objects.filter(
                pk=operation.payload["attachmentId"],
                owner=actor,
                conversation_id=operation.run.conversation_id,
            ).first()
            if source is None:
                raise ComputeError("原附件不存在或无权访问", 404)
    else:
        _, binding, _ = inspect(operation.run, actor, operation.kind, operation.payload)
        if operation.status == "pending" and digest(binding) != operation.binding_hash:
            return {
                **public(operation),
                "status": "failed",
                "canConfirm": False,
                "detail": "对象、版本或范围已变化，请重新准备操作预览",
            }
    return public(operation)


def list_operation(operation, user):
    """An unavailable target must not reveal cached data or hide other cards."""
    try:
        return read_operation(operation, user)
    except (ComputeError, PermissionDenied):
        return {
            **public(operation),
            "status": "failed",
            "canConfirm": False,
            "preview": {
                "projectId": operation.project_tag_id,
                "title": "操作对象当前不可访问",
                "target": "对象已失效或访问权限已变化",
                "scope": "当前项目",
                "effect": "请核对对象与权限后重新准备操作",
                "details": [],
            },
            "result": {},
            "detail": "当前无法核对该操作；其他可用操作仍可分别处理",
        }


def prepare(run, user, kind, payload):
    actor, _ = authorize(run, user, creating=True)
    payload = dict(payload)
    for key in ("name", "username"):
        if key in payload:
            payload[key] = payload[key].strip()
            if not payload[key]:
                raise ComputeError("名称或用户名不能为空")
    request_hash = digest([kind, payload])
    previous = (
        AgentOperation.objects.filter(
            run=run,
            request_hash=request_hash,
            status__in=["executing", "confirmed", "interrupted"],
        )
        .order_by("-created_at")
        .first()
    )
    if previous and previous.status == "confirmed" and kind == "publish":
        model = ResultArtifact if payload["kind"] == "result" else MapComposition
        item = model.objects.filter(pk=payload["objectId"], owner=actor).first()
        if item is not None and item.updated_at.isoformat() != previous.result.get(
            "updatedAt"
        ):
            previous = None
    if previous and previous.status == "confirmed" and kind == "share":
        from apps.catalog.models import ShareInvitation

        if not ShareInvitation.objects.filter(
            pk=previous.result.get("invitationId"),
            sender=actor,
            status__in=["pending", "accepted"],
        ).exists():
            previous = None
    if previous:
        return read_operation(previous, actor)
    summary, binding, _ = inspect(run, actor, kind, payload)
    binding_hash = digest(binding)
    with transaction.atomic():
        if not AgentRun.objects.filter(
            pk=run.pk, status="running", cancel_requested=False
        ).update(heartbeat=F("heartbeat")):
            raise ComputeError("本轮已停止，未创建操作预览", 409)
        existing = (
            AgentOperation.objects.filter(
                run=run, request_hash=request_hash, binding_hash=binding_hash
            )
            .exclude(status__in=["rejected", "failed"])
            .order_by("-created_at")
            .first()
        )
        if existing and (
            existing.status != "pending" or existing.expires_at > timezone.now()
        ):
            return public(existing)
        if AgentOperation.objects.filter(run=run).count() >= MAX_PROPOSALS_PER_RUN:
            raise ComputeError("每轮最多准备8项操作，请缩小任务范围")
        identity = uuid.uuid4()
        expires = timezone.now() + PREVIEW_TTL
        value = {"projectId": run.project_tag_id, **summary}
        operation = AgentOperation.objects.create(
            id=identity,
            run=run,
            kind=kind,
            payload=payload,
            request_hash=request_hash,
            binding_hash=binding_hash,
            preview=value,
            expires_at=expires,
            digest=digest(
                [
                    str(identity),
                    actor.pk,
                    run.project_tag_id,
                    payload,
                    value,
                    binding_hash,
                    expires.isoformat(),
                ]
            ),
        )
    return public(operation)


def decide(operation, user, decision, expected_digest):
    """Only the CSRF-protected user API calls this; never registered as a tool."""
    run = AgentRun.objects.select_related("conversation").get(
        pk=operation.run_id, owner=user
    )
    actor, _ = authorize(run, user)
    if not isinstance(expected_digest, str) or not hmac.compare_digest(
        operation.digest, expected_digest
    ):
        raise ComputeError("预览凭据不一致，请重新读取操作", 409)
    if decision not in {"confirm", "reject"}:
        raise ComputeError("只支持confirm或reject")
    # Claim before effectful work. A crashed importer remains indeterminate and
    # cannot create duplicate external tables on a retried confirmation.
    with transaction.atomic():
        AgentOperation.objects.filter(pk=operation.pk).update(
            updated_at=F("updated_at")
        )
        operation.refresh_from_db()
        if operation.status in {"confirmed", "rejected"}:
            expected = "confirmed" if decision == "confirm" else "rejected"
            if operation.status != expected:
                raise ComputeError("该操作已有不同的真实用户决定", 409)
            return read_operation(operation, actor)
        if operation.status != "pending":
            return read_operation(operation, actor)
        if operation.expires_at <= timezone.now():
            raise ComputeError("预览已过期，请重新准备", 409)
        if run.cancel_requested or run.status in {"cancelled", "interrupted"}:
            raise ComputeError("本轮已停止，未执行待确认操作", 409)
        operation.status = "rejected" if decision == "reject" else "executing"
        operation.decided_by, operation.decided_at = actor, timezone.now()
        operation.execution_identity = (
            current_identity() if decision == "confirm" else {}
        )
        operation.save(
            update_fields=[
                "status",
                "decided_by",
                "decided_at",
                "execution_identity",
                "updated_at",
            ]
        )
    if decision == "reject":
        return public(operation)
    try:
        actor = fresh_user(actor.pk)
        require_access(actor, "agent", run.model)
        _, binding, raw = inspect(run, actor, operation.kind, operation.payload)
        if digest(binding) != operation.binding_hash:
            raise ComputeError("对象、来源或可见范围已有变化，请重新预览后决定", 409)
        with transaction.atomic():
            AgentOperation.objects.filter(pk=operation.pk).update(
                updated_at=F("updated_at")
            )
            current_run = AgentRun.objects.get(pk=run.pk)
            if current_run.cancel_requested or current_run.status in {
                "cancelled",
                "interrupted",
            }:
                raise ComputeError("本轮已停止，操作未执行", 409)
            actor = fresh_user(actor.pk)
            current_policy = require_access(actor, "agent", run.model)
            if operation.kind != "import":
                _, latest_binding, _ = inspect(
                    run, actor, operation.kind, operation.payload
                )
                if digest(latest_binding) != operation.binding_hash:
                    raise ComputeError("对象或分享范围已更新，请重新预览", 409)
            elif (
                not has_feature_perm(actor, "catalog.add_dataresource")
                or not current_policy.get("allowAttachments")
                or not current_policy.get("allowDocuments")
            ):
                raise ComputeError("新增资料或附件访问权限已撤销", 403)
            value = operation.payload
            if operation.kind == "import":
                from apps.catalog.importer import import_uploaded_table

                source = AgentAttachment.objects.get(
                    pk=value["attachmentId"], owner=actor
                )
                payload = {
                    **value,
                    "tableName": "agent_import_" + operation.pk.hex,
                    "domainType": "field_survey",
                    "duplicateConfirmed": False,
                }
                result = import_uploaded_table(
                    SimpleUploadedFile(source.name, raw, content_type="text/csv"),
                    payload,
                    actor,
                )
                resource = DataResource.objects.get(
                    pk=result["resourceId"], maintainer=actor
                )
                resource.owner_only = True
                resource.save(update_fields=["owner_only", "updated_at"])
                refs = {
                    "resourceId": resource.pk,
                    "importedRows": result["importedRows"],
                    "status": "active",
                }
            elif operation.kind == "publish":
                item = publish(
                    actor,
                    value["kind"],
                    value["objectId"],
                    value.get("audienceGroupIds", []),
                    version_number=value.get("versionNumber"),
                    expected_updated_at=binding["updatedAt"],
                )
                refs = {
                    "objectId": item.pk,
                    "kind": value["kind"],
                    "status": item.status,
                    "updatedAt": item.updated_at.isoformat(),
                }
            else:
                from apps.catalog.sharing import create_invitation

                invitation, _ = create_invitation(
                    actor, {**value, "idempotencyKey": "agent-" + operation.pk.hex}
                )
                refs = {
                    "kind": invitation.kind,
                    "invitationId": invitation.pk,
                    "objectId": invitation.object_id,
                    "status": invitation.status,
                }
            operation.status, operation.result = "confirmed", refs
            operation.save(update_fields=["status", "result", "updated_at"])
            log_operation(
                actor,
                "平台代办",
                "用户确认操作",
                "success",
                operation.preview["title"],
                target_type="agent_operation",
                target_code=str(operation.pk),
            )
    except Exception as error:
        from .tool_contract_runtime import failure

        AgentOperation.objects.filter(pk=operation.pk, status="executing").update(
            status="failed"
            if isinstance(error, (ComputeError, ValidationError))
            else "interrupted",
            result={"error": failure(error, operation.pk)},
            updated_at=timezone.now(),
        )
        raise
    return public(operation)


def list_targets(run, user, args):
    actor, _ = authorize(run, user)
    kind = args["kind"]
    offset, limit = args.get("offset", 0), args.get("limit", 10)
    if kind == "import_sources":
        query = AgentAttachment.objects.filter(
            pk__in=run.attachment_ids,
            owner=actor,
            conversation_id=run.conversation_id,
            name__iendswith=".csv",
        )
        items = [
            {"attachmentId": item.pk, "name": item.name, "sizeBytes": item.size_bytes}
            for item in query.order_by("pk")[offset : offset + limit]
        ]
    else:
        feature = (
            "catalog.view_resultartifact"
            if kind == "results"
            else "catalog.view_mapcomposition"
        )
        if not has_feature_perm(actor, feature):
            raise ComputeError("没有查看该类成果的权限", 403)
        model = ResultArtifact if kind == "results" else MapComposition
        query = model.objects.filter(owner=actor, name__icontains=args.get("query", ""))
        items = [
            {
                "objectId": item.pk,
                "name": item.name,
                "status": item.status,
                "updatedAt": item.updated_at.isoformat(),
                **(
                    {
                        "versions": list(
                            item.versions.order_by("-version_number").values_list(
                                "version_number", flat=True
                            )[:10]
                        )
                    }
                    if kind == "compositions"
                    else {}
                ),
            }
            for item in query.order_by("pk")[offset : offset + limit]
        ]
    total = query.count()
    return {
        "items": items,
        "total": total,
        "nextOffset": offset + limit if offset + limit < total else None,
    }


def append_operation_status(answer, run):
    pending = list(
        AgentOperation.objects.filter(
            run=run, status__in=["pending", "executing", "interrupted"]
        ).values_list("status", flat=True)[:8]
    )
    if not pending:
        return answer
    labels = []
    if "pending" in pending:
        labels.append("待确认操作尚未执行，请打开“平台操作”查看具体范围并决定")
    if "executing" in pending:
        labels.append("已确认操作仍在执行，暂不能认定完成")
    if "interrupted" in pending:
        labels.append("有操作结果尚待核对，不能盲目重复提交")
    return answer + "\n\n平台执行状态：" + "；".join(labels) + "。"


def reconcile_operations():
    rows = list(
        AgentOperation._base_manager.filter(status="executing").values(
            "pk", "execution_identity"
        )[:30]
    )
    owners = {}
    dead = []
    for row in rows:
        key = digest(row["execution_identity"])
        if key not in owners:
            owners[key] = alive(row["execution_identity"])
        if owners[key] is False:
            dead.append(row["pk"])
    if dead:
        AgentOperation._base_manager.filter(pk__in=dead, status="executing").update(
            status="interrupted", updated_at=timezone.now()
        )
