"""Authorized compute tools and durable, non-blocking result follow-up."""

import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.compute.access import project_id, task_access, require_actor
from apps.compute.models import ComputeTask, ComputeOutput, ComputeImport
from apps.compute.services import ACTIVE, ComputeError, request_output_import
from apps.compute.serializers import output_data, task_data
from apps.compute.quality import require_automatic_quality
from apps.projects.context import ProjectScope, project_scope
from .models import AgentComputeFollowup, AgentRun, AgentWorkflow, AgentWorkflowStep
from .policy import fresh_user, require_access
from .selections import require_task_selection
from .resource_discovery import discovery_scope


@discovery_scope()
def authorized_task(
    user, task_id, policy_value, *, run=None, workflow=None, history=False
):
    from .resource_discovery import resolve_acl_resource, resolve_discoverable_resource
    from .deleted_resources import TERMINAL, readable_receipt

    try:
        task_id = uuid.UUID(str(task_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("taskId 必须是计算任务 UUID；不能用作 outputId") from exc
    task = (
        ComputeTask.objects.select_related("owner", "version__algorithm")
        .filter(pk=task_id)
        .first()
    )
    if task is None:
        raise PermissionDenied("任务不存在或无权访问")
    task_access(task, user)
    if not history:
        if task.trial:
            raise PermissionDenied("算法试运行不属于当前业务计算范围")
        if run is not None:
            saved_run = AgentRun.objects.filter(
                pk=run.pk, owner=user, project_tag_id=task.project_tag_id
            ).first()
            if saved_run is None:
                raise PermissionDenied("计算任务与当前运行归属不一致")
            if workflow is None and saved_run.research_workflow_id:
                linked = saved_run.research_workflow
                if linked.steps.filter(compute_task_id=task.id).exists():
                    workflow = linked
            if (
                workflow is None
                and not AgentComputeFollowup.objects.filter(
                    task=task,
                    run__conversation_id=saved_run.conversation_id,
                    run__owner=user,
                    run__project_tag_id=task.project_tag_id,
                ).exists()
            ):
                raise PermissionDenied("计算任务未绑定到当前会话")
        if workflow is not None:
            workflow = AgentWorkflow.objects.filter(
                pk=workflow.pk, owner=user, project_tag_id=task.project_tag_id
            ).first()
            if (
                workflow is None
                or not workflow.steps.filter(compute_task_id=task.id).exists()
                or task.owner_id != workflow.owner_id
            ):
                raise PermissionDenied("计算任务未绑定到当前工作流")
        elif AgentWorkflowStep.objects.filter(compute_task_id=task.id).exists() or (
            task.outputs.filter(
                import_record__request_source__startswith="workflow:"
            ).exists()
        ):
            raise PermissionDenied("工作流过程计算仅允许在真实绑定任务内读取")
    for item in task.input_records.all():
        if item.resource_id is None:
            removed = item.snapshot.get("deletedResource", {})
            if task.status in TERMINAL and readable_receipt(
                removed,
                user,
                policy_value,
                task.project_tag_id,
                removed.get("formerResourceId"),
            ):
                continue
            raise PermissionDenied("计算输入已删除，请重新选择数据后发起计算")
        if history:
            resolve_acl_resource(user, policy_value, item.resource_id, active=False)
        elif workflow is not None:
            from .workflow_resources import resolve_workflow_resource

            resolve_workflow_resource(user, policy_value, item.resource_id, workflow)
        else:
            resolve_discoverable_resource(user, policy_value, item.resource_id)
    return task


def compact_task(task):
    return {
        "taskId": str(task.id),
        "versionId": task.version_id,
        "name": task.name,
        "status": task.status,
        "stage": task.stage,
        "progress": task.progress,
        "error": task.error,
        "checkedAt": timezone.now().isoformat(),
        "outputs": [output_data(output) for output in task.outputs.all()],
        "detail": "此为当前真实状态。taskId 是 UUID，outputId 是 outputs 中的整数 id。",
    }


def query_task(run, user, p, args):
    task = authorized_task(user, args.get("taskId"), p, run=run)
    require_task_selection(run, task)
    result = compact_task(task)
    followup = AgentComputeFollowup.objects.filter(task=task).first()
    if followup:
        result.update(
            autoImport=followup.auto_import,
            trackingStatus=followup.status,
            trackingDetail=followup.detail,
        )
    return result, [(None, result)]


def list_tasks(run, user, p, args):
    require_actor(user, project_id(), "view_own_task")
    query = args.get("query", "")
    if not isinstance(query, str) or len(query) > 160:
        raise ValidationError("query 必须为不超过160字的文字")
    from .resource_discovery import workflow_task_ids

    workflow_imports = ComputeImport.objects.filter(
        request_source__startswith="workflow:"
    ).values("output__task_id")
    tasks = (
        ComputeTask.objects.filter(owner=user, trial=False, name__icontains=query)
        .exclude(pk__in=workflow_task_ids())
        .exclude(pk__in=workflow_imports)
        .order_by("-created_at")[:10]
    )
    result = {"items": []}
    for task in tasks:
        try:
            task = authorized_task(user, task.id, p)
            require_task_selection(run, task)
        except (PermissionDenied, ComputeError):
            continue
        result["items"].append(compact_task(task))
    return result, [(None, result)]


def track(run, task, *, auto_import=False, keys=None, name=""):
    item, _ = AgentComputeFollowup.objects.get_or_create(
        task=task, defaults={"run": run}
    )
    if auto_import:
        # Repeating a request updates its durable intent, never duplicates an import.
        item.auto_import = True
        item.run = run
        item.output_keys = keys or []
        item.import_name = name
        item.status = "waiting_compute"
        item.detail = "计算完成后将自动申请结果入库"
        item.save()
    return item


def import_result(run, user, p, args):
    from .tools import _check_special_capability, TOOLS

    _check_special_capability(TOOLS["import_compute_result"], p)
    task_id, output_id = args.get("taskId"), args.get("outputId")
    if (task_id is None) == (output_id is None):
        raise ValidationError("请传入 taskId 或 outputId 其中一项")
    keys = args.get("outputKeys", [])
    if (
        not isinstance(keys, list)
        or len(keys) > 30
        or any(not isinstance(k, str) for k in keys)
    ):
        raise ValidationError("outputKeys 必须为输出 key 数组")
    if output_id is not None:
        if type(output_id) is not int or output_id < 1:
            raise ValidationError("outputId 必须为真实输出的正整数 ID，不能填 taskId")
        output = ComputeOutput.objects.filter(
            pk=output_id, task__project_tag_id=project_id()
        ).first()
        if output is None:
            raise PermissionDenied("结果不存在或无权访问")
        task_id, keys = output.task_id, [output.key]
    task = authorized_task(user, task_id, p, run=run)
    require_task_selection(run, task)
    require_actor(user, task.project_tag_id, "catalog.add_dataresource")
    name = args.get("name", "")
    if not isinstance(name, str) or len(name) > 160:
        raise ValidationError("name 必须为不超过160字的文字")
    declared = {
        item["key"]
        for item in task.version.manifest.get("outputs", [])
        if item.get("kind") != "archive"
    }
    if not declared or set(keys) - declared:
        raise ValidationError("请选择算法声明的可入库输出；压缩包须分别导入")
    if task.status not in (*ACTIVE, "succeeded"):
        raise ValidationError("任务未成功，不能申请结果入库")
    if task.status == "succeeded":
        for output in task.outputs.exclude(kind="archive"):
            if not keys or output.key in keys:
                require_automatic_quality(output)
    item = track(run, task, auto_import=True, keys=keys, name=name.strip())
    if task.status == "succeeded":
        for output in task.outputs.exclude(kind="archive"):
            if keys and output.key not in keys:
                continue
            record = ComputeImport.objects.filter(
                output=output, status__in=["queued", "failed"]
            ).first()
            if record:
                request_output_import(
                    user, output, record.name, request_source=f"agent_run:{run.id}"
                )
    advance(item, user, p, task)
    result = compact_task(task)
    result.update(autoImport=True, trackingStatus=item.status, detail=item.detail)
    return result, [(None, result)]


def advance(item, user, p, task):
    if item.auto_import and not p.get("operatorEnabled", False):
        raise PermissionDenied("算子及自动入库权限已关闭")
    if task.status in ACTIVE:
        item.status = "waiting_compute"
        item.detail = (
            "计算中；完成后自动入库"
            if item.auto_import
            else "计算中，状态由平台自动更新"
        )
    elif task.status != "succeeded":
        item.status, item.detail = "failed", "计算未成功：" + task.status
    elif not item.auto_import:
        item.status, item.detail = "completed", "计算完成，可查看结果或申请入库"
    else:
        if not p.get("operatorEnabled", False):
            raise PermissionDenied("算子及自动入库权限已关闭")
        require_actor(user, task.project_tag_id, "catalog.add_dataresource")
        outputs = list(task.outputs.exclude(kind="archive"))
        if item.output_keys:
            outputs = [output for output in outputs if output.key in item.output_keys]
        if (
            not outputs
            or item.output_keys
            and {o.key for o in outputs} != set(item.output_keys)
        ):
            raise ComputeError("所选输出缺失，未自动入库")
        records = []
        for output in outputs:
            require_automatic_quality(output)
        for output in outputs:
            record = ComputeImport.objects.filter(output=output).first()
            if record is None:
                suffix = " " + output.label if len(outputs) > 1 else ""
                record = request_output_import(
                    user,
                    output,
                    (item.import_name + suffix)[:160] if item.import_name else "",
                    request_source=f"agent_run:{item.run_id}",
                )
            records.append(record)
        if any(record.status == "failed" for record in records):
            item.status, item.detail = "failed", "结果入库失败；可查看结果后重试入库"
        elif all(record.status == "ready" for record in records):
            item.status, item.detail = "completed", f"{len(records)} 项结果已入库"
        else:
            item.status, item.detail = "waiting_import", "计算完成，正在入库"
    item.save(update_fields=["status", "detail", "updated_at"])


@discovery_scope()
def validate_import_intent(record):
    """Check automatic intent again at import start and before publication."""
    record.refresh_from_db(fields=["request_source"])
    if not record.request_source:
        return
    require_automatic_quality(record.output)
    from .models import AgentRun, AgentWorkflow
    from .workflow import _authorize

    try:
        kind, identity = record.request_source.split(":", 1)
        if kind == "agent_run":
            run = AgentRun._base_manager.filter(
                pk=identity,
                owner=record.requested_by,
                project_tag_id=record.output.task.project_tag_id,
            ).first()
            if run is None or run.cancel_requested:
                raise PermissionDenied("智能体运行已取消，自动入库已停止")
            item = AgentComputeFollowup.objects.filter(
                run=run, task=record.output.task, auto_import=True
            ).first()
            if item is None or item.status in {"blocked", "failed"}:
                raise PermissionDenied("自动入库意图已失效")
            user = fresh_user(run.owner_id)
            p = require_access(user, "agent", run.model)
        elif kind == "workflow":
            workflow = AgentWorkflow._base_manager.filter(
                pk=identity,
                owner=record.requested_by,
                project_tag_id=record.output.task.project_tag_id,
            ).first()
            paused_input_preparation = bool(
                workflow is not None
                and workflow.workflow_type == "business_flow"
                and workflow.status == "paused"
                and workflow.paused_from == "waiting_compute"
                and workflow.parameters.get("_businessFlow")
                and workflow.plan.get("businessFlow", {})
                .get("nodes", {})
                .get(workflow.current_step, {})
                .get("inputPreparation")
                == "waiting"
            )
            if (
                workflow is None
                or workflow.cancel_requested
                or workflow.status != "waiting_compute"
                and not paused_input_preparation
            ):
                raise PermissionDenied("工作流已停止，自动入库已取消")
            if not workflow.steps.filter(
                compute_task_id=record.output.task_id
            ).exists():
                raise PermissionDenied("入库结果不属于此工作流")
            user, p = _authorize(workflow)
        else:
            raise PermissionDenied("无法识别自动入库来源")
        if not p.get("operatorEnabled", False):
            raise PermissionDenied("智能体自动入库权限已关闭")
        authorized_task(
            user,
            record.output.task_id,
            p,
            run=run if kind == "agent_run" else None,
            workflow=workflow if kind == "workflow" else None,
        )
    except (PermissionDenied, ValidationError, ValueError) as exc:
        raise ComputeError(str(exc), 403) from exc


def resume_followups():
    for item in AgentComputeFollowup.objects.filter(
        status__in=["waiting_compute", "waiting_import"]
    ).select_related("run", "task")[:30]:
        run = item.run
        with project_scope(
            ProjectScope((run.project_tag_id,), run.project_tag_id, run.owner_id)
        ):
            try:
                user = fresh_user(run.owner_id)
                p = require_access(user, "agent", run.model)
                if run.cancel_requested:
                    raise PermissionDenied("本轮已取消，自动后续处理已停止")
                task = authorized_task(user, item.task_id, p, run=run)
                advance(item, user, p, task)
            except (PermissionDenied, ValidationError, ComputeError) as exc:
                item.status, item.detail = "blocked", str(exc)[:300]
                item.save(update_fields=["status", "detail", "updated_at"])


def run_tasks(run, user, p):
    ids = set(str(i) for i in run.compute_followups.values_list("task_id", flat=True))
    # Existing conversations can acquire live cards from their historical evidence.
    for ev in run.evidence:
        result = ev.get("result", {})
        if isinstance(result, dict) and isinstance(result.get("taskId"), str):
            ids.add(result["taskId"])
    items = []
    for task_id in sorted(ids)[:30]:
        try:
            task = authorized_task(user, task_id, p, run=run, history=True)
            require_task_selection(run, task)
        except (PermissionDenied, ValidationError, ComputeError):
            continue
        followup = AgentComputeFollowup.objects.filter(task=task).first()
        items.append(
            {
                "task": task_data(task),
                "autoImport": bool(followup and followup.auto_import),
                "trackingStatus": followup.status if followup else "untracked",
                "detail": followup.detail if followup else "从计算中心读取当前状态",
            }
        )
    return {"items": items}
