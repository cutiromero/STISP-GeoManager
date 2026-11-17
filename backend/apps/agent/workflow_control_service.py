"""The existing pause/resume semantics shared by pages and governed tools."""

from django.db import transaction
from django.db.models import F

from apps.compute.packages import ComputeError
from .models import AgentWorkflow, WORKFLOW_ACTIVE
from .policy import require_access
from .workflow import _authorize, validate_confirmed_plan
from .workflow_controls import locked_workflow


def control_workflow(
    user, identity, action, *, actor_kind="human", expected_epoch=None, request_id=None
):
    if action not in {"pause", "resume", "cancel"}:
        raise ComputeError("不支持的科研任务操作")
    require_access(user, "agent")
    workflow = AgentWorkflow.objects.filter(pk=identity, owner=user).first()
    if workflow is None:
        raise ComputeError("任务不存在或无权访问", 404)
    if isinstance(workflow.parameters.get("_businessFlow"), dict):
        from apps.business_flows.runtime import control_flow

        return control_flow(
            user,
            workflow,
            action,
            actor_kind=actor_kind,
            expected_epoch=expected_epoch,
            request_id=request_id,
        )
    with transaction.atomic():
        if not AgentWorkflow.objects.filter(pk=identity, owner=user).update(
            idempotency_key=F("idempotency_key")
        ):
            raise ComputeError("任务不存在或无权访问", 404)
        workflow = locked_workflow(identity)
        if (
            expected_epoch is not None
            and workflow.policy_snapshot.get("platformControlEpoch", 0)
            != expected_epoch
        ):
            raise ComputeError("任务有更新的用户决定，请重新读取后操作", 409)

        def record_control():
            workflow.policy_snapshot["platformControlEpoch"] = (
                workflow.policy_snapshot.get("platformControlEpoch", 0) + 1
            )
            workflow.save(update_fields=["policy_snapshot", "updated_at"])

        if action == "cancel":
            from .workflow_cancellation import stop_workflow

            before = workflow.status
            workflow = stop_workflow(workflow.pk, user.pk)
            if before != workflow.status:
                record_control()
            return workflow
        actor, policy = _authorize(workflow)
        if action == "pause":
            if workflow.status not in WORKFLOW_ACTIVE or workflow.cancel_requested:
                raise ComputeError("此科研任务当前不能暂停", 409)
            if workflow.pause_requested or workflow.status == "paused":
                return workflow
            workflow.pause_requested = True
            workflow.paused_from = workflow.status
            if workflow.status != "running":
                workflow.status, workflow.detail = "paused", "已暂停，可从当前步骤继续"
            else:
                workflow.detail = "正在暂停；当前步骤到达保存点后停止后续处理"
            workflow.save(
                update_fields=[
                    "pause_requested",
                    "paused_from",
                    "status",
                    "detail",
                    "updated_at",
                ]
            )
            record_control()
            return workflow
        if workflow.cancel_requested:
            raise ComputeError("已取消的科研任务不能继续", 409)
        if workflow.plan.get("deletedResources"):
            raise ComputeError(
                "该科研任务的历史数据已被删除，请重新选择数据后发起任务", 409
            )
        if workflow.plan.get("scenarioVersion"):
            from .demo_workflow import authorize_demo

            authorize_demo(workflow, actor, policy)
        elif workflow.plan.get("algorithmVersionId"):
            validate_confirmed_plan(workflow, actor, policy)
        if workflow.status != "paused":
            if (
                workflow.paused_from
                and not workflow.pause_requested
                and workflow.status in WORKFLOW_ACTIVE
            ):
                return workflow
            raise ComputeError("此科研任务当前没有可继续的暂停点", 409)
        continuation = workflow.paused_from
        if continuation not in {
            "queued",
            "running",
            "waiting_compute",
            "waiting_approval",
        }:
            raise ComputeError("暂停点无效，请重新创建任务", 409)
        workflow.status = "queued" if continuation == "running" else continuation
        if workflow.status != "waiting_approval":
            from .workflow_slots import require_compute_slot

            require_compute_slot(actor, workflow.pk)
        workflow.pause_requested = False
        workflow.detail = (
            "已继续，等待用户确认原审核计划"
            if continuation == "waiting_approval"
            else "已继续，将复用已有计算与结果接着处理"
        )
        workflow.save(
            update_fields=["status", "pause_requested", "detail", "updated_at"]
        )
        record_control()
        return workflow
