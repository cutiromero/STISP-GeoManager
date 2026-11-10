"""Execute a frozen input plan through the existing compute/import queues."""

from copy import deepcopy
import hashlib
import json

from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.agent.compute_tools import authorized_task
from apps.agent.workflow import step
from apps.agent.workflow_controls import check_pause, locked_workflow
from apps.agent.workflow_resources import resolve_workflow_resource
from apps.compute.models import AlgorithmVersion, ComputeImport
from apps.compute.packages import ComputeError
from apps.compute.quality import require_automatic_quality
from apps.compute.services import (
    allowed_algorithms,
    agent_algorithm_allowed,
    request_output_import,
    submit,
)


def _save(workflow, message):
    workflow.detail = message
    if workflow.workflow_type == "business_flow":
        from .state import emit, binding, state

        node_id = binding(workflow)["definitionSnapshot"]["nodes"][0]["id"]
        node = state(workflow)["nodes"][node_id]
        node["executor"].update(status="preparing", summary=message)
        emit(workflow, "executor", node_id, "preparing_inputs", message)
    else:
        from apps.agent.demo_workflow import _save as persist

        persist(workflow)


def advance_inputs(workflow, user, policy, *, confirmed_fields=None):
    """False means actual work is pending; a healthy ready plan is a pure reuse."""
    entries = workflow.plan.get("inputAdaptations", [])
    if not entries or workflow.plan.get("inputAdaptationComplete"):
        return True
    confirmed_fields = confirmed_fields or {}
    effective = workflow.plan.setdefault("effectiveInputs", {})
    for entry in entries:
        check_pause(workflow)
        if workflow.cancel_requested:
            raise ComputeError("任务已停止，输入适配不会继续", 409)
        resource = resolve_workflow_resource(user, policy, entry["sourceId"], workflow)
        if resource.updated_at.isoformat() != entry["sourceRevision"]:
            raise ComputeError("输入资料已变化，请重新确认适配方案", 409)
        role = entry["role"]
        if entry["status"] == "direct":
            effective[role] = resource.pk
            continue
        if entry.get("resourceId"):
            prepared = resolve_workflow_resource(
                user, policy, entry["resourceId"], workflow
            )
            effective[role] = prepared.pk
            continue
        if entry["status"] not in {
            "convert",
            "needs_parameters",
            "waiting_compute",
            "waiting_import",
        }:
            raise ComputeError("输入适配尚未选择可执行的转换工具：" + role)
        if not policy.get("operatorEnabled", False):
            raise PermissionDenied("当前策略未允许调用资料转换算子")
        version = (
            AlgorithmVersion.objects.select_related("algorithm")
            .filter(
                pk=entry.get("versionId"),
                algorithm__enabled=True,
                algorithm__in=allowed_algorithms(),
                status="published",
            )
            .first()
        )
        if (
            not version
            or version.checksum != entry["checksum"]
            or not agent_algorithm_allowed(version)
        ):
            raise PermissionDenied("冻结的输入适配算子已不可用或无权调用")
        if not entry.get("taskId"):
            parameters = deepcopy(entry.get("parameters", {}))
            for parameter, semantic in entry.get("fieldTargets", {}).items():
                chosen = confirmed_fields.get(role, {}).get(semantic)
                if chosen:
                    parameters[parameter] = chosen
            signature = hashlib.sha256(
                json.dumps(
                    {
                        "source": resource.pk,
                        "revision": entry["sourceRevision"],
                        "version": version.pk,
                        "checksum": version.checksum,
                        "parameters": parameters,
                        "output": entry["outputKey"],
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
            entry["preparationSignature"] = signature
            shared = next(
                (
                    other
                    for other in entries
                    if other is not entry
                    and other.get("preparationSignature") == signature
                    and other.get("resourceId")
                ),
                None,
            )
            if shared:
                prepared = resolve_workflow_resource(
                    user, policy, shared["resourceId"], workflow
                )
                entry.update(
                    status="ready",
                    resourceId=prepared.pk,
                    taskId=shared["taskId"],
                    outputId=shared["outputId"],
                    actualParameters=parameters,
                )
                effective[role] = prepared.pk
                if workflow.workflow_type == "business_flow":
                    workflow.plan["inputs"][role] = prepared.pk
                continue
            if any(key not in parameters for key in entry.get("missingParameters", [])):
                raise ComputeError("请先确认资料转换需要的字段：" + role)
            if workflow.operator_steps >= workflow.max_operator_steps:
                raise ComputeError("输入适配已达到本次任务的算子次数上限")
            with transaction.atomic():
                current = locked_workflow(workflow.pk)
                check_pause(current)
                if current.cancel_requested or current.policy_snapshot.get(
                    "businessFlowControlEpoch", 0
                ) != workflow.policy_snapshot.get("businessFlowControlEpoch", 0):
                    raise ComputeError("任务控制状态已变化，未提交新的转换计算", 409)
                task = submit(
                    user,
                    {
                        "name": "输入适配 · " + entry["sourceName"][:100],
                        "versionId": version.pk,
                        "inputs": {entry["inputKey"]: resource.pk},
                        "parameters": parameters,
                        "idempotencyKey": f"adapt-{workflow.pk}-"
                        + hashlib.sha256(role.encode()).hexdigest()[:16],
                    },
                )
                entry.update(
                    taskId=str(task.pk),
                    status="waiting_compute",
                    actualParameters=parameters,
                )
                workflow.operator_steps += 1
                workflow.status = "waiting_compute"
                step(
                    workflow,
                    "submit_operator",
                    message="正在转换输入资料：" + entry["sourceName"],
                    compute_task_id=task.pk,
                    action={
                        "phase": "input_adaptation",
                        "role": role,
                        "versionId": version.pk,
                        "parameters": parameters,
                    },
                    input_refs={
                        "resourceId": resource.pk,
                        "revision": entry["sourceRevision"],
                    },
                )
                _save(workflow, "输入适配 · " + version.algorithm.name)
            return False
        task = authorized_task(user, entry["taskId"], policy, workflow=workflow)
        if task.status in {"queued", "validating", "running", "cancelling"}:
            return False
        if task.status != "succeeded":
            raise ComputeError("输入转换未能完成：" + task.error[:250])
        output = task.outputs.filter(
            key=entry["outputKey"], kind=entry["targetType"]
        ).first()
        if output is None:
            raise ComputeError("适配算子未提供已声明的目标输出")
        require_automatic_quality(output)
        imported = ComputeImport.objects.filter(output=output).first()
        if imported is None:
            with transaction.atomic():
                current = locked_workflow(workflow.pk)
                check_pause(current)
                if current.cancel_requested:
                    raise ComputeError("任务已停止，未准备新的派生资料", 409)
                imported = request_output_import(
                    user, output, request_source=f"workflow:{workflow.pk}"
                )
                entry["status"] = "waiting_import"
                _save(workflow, "输入转换已完成，正在登记本次任务的派生资料")
        if imported.status in {"failed", "deleted"}:
            raise ComputeError("输入转换结果准备失败：" + imported.error[:200])
        if imported.status != "ready" or not imported.resource_id:
            return False
        prepared = resolve_workflow_resource(
            user, policy, imported.resource_id, workflow
        )
        if prepared.data_type != entry["targetType"]:
            raise ComputeError("真实适配结果类型不符合本次输入规范")
        marker = f"workflow-working:{workflow.pk}:input-adapter:{role}"
        if prepared.source != marker or not prepared.owner_only:
            prepared.source = marker
            prepared.owner_only = True
            prepared.save(update_fields=["source", "owner_only", "updated_at"])
        entry.update(status="ready", resourceId=prepared.pk, outputId=output.pk)
        effective[role] = prepared.pk
        workflow.resource_ids = sorted(set(workflow.resource_ids) | {prepared.pk})
        step(
            workflow,
            "input_adapted",
            compute_task_id=task.pk,
            message=entry["sourceName"] + "已转换为" + entry["targetType"],
            input_refs={"resourceId": resource.pk, "revision": entry["sourceRevision"]},
            output_refs={
                "resourceIds": [prepared.pk],
                "outputIds": [output.pk],
                "role": role,
            },
        )
        if workflow.workflow_type == "business_flow":
            from .state import state

            state(workflow).setdefault("consumedOutputs", []).append(output.pk)
            workflow.plan["inputs"][role] = prepared.pk
        workflow.status = "queued"
        _save(workflow, "输入适配已完成，继续已发布流程")
    workflow.plan["inputAdaptationComplete"] = True
    return True
