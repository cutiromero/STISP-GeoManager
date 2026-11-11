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

        nodes = binding(workflow)["definitionSnapshot"]["nodes"]
        node_id = (
            workflow.current_step
            if workflow.current_step in {node["id"] for node in nodes}
            else nodes[0]["id"]
        )
        node = state(workflow)["nodes"][node_id]
        node["executor"].update(status="preparing")
        if node.get("toolLoop") is None:
            node["executor"]["summary"] = message
        else:
            node["executor"]["progressMessage"] = message
        emit(workflow, "executor", node_id, "preparing_inputs", message)
    else:
        from apps.agent.demo_workflow import _save as persist

        persist(workflow)


def bind_prepared(workflow, entry, identity):
    if entry.get("nodeId"):
        workflow.plan.setdefault("preparedNodeInputs", {}).setdefault(
            entry["nodeId"], {}
        )[entry["nodeInputKey"]] = identity
    else:
        workflow.plan.setdefault("effectiveInputs", {})[entry["role"]] = identity
        if workflow.workflow_type == "business_flow":
            workflow.plan["inputs"][entry["role"]] = identity
    workflow.resource_ids = sorted(set(workflow.resource_ids) | {identity})


def advance_inputs(workflow, user, policy, *, confirmed_fields=None):
    """False means actual work is pending; a healthy ready plan is a pure reuse."""
    entries = workflow.plan.get("inputAdaptations", [])
    if not entries or workflow.plan.get("inputAdaptationComplete"):
        return True
    confirmed_fields = confirmed_fields or {}
    workflow.plan.setdefault("effectiveInputs", {})
    for entry in entries:
        check_pause(workflow)
        if workflow.cancel_requested:
            raise ComputeError("任务已停止，输入适配不会继续", 409)
        resource = resolve_workflow_resource(user, policy, entry["sourceId"], workflow)
        if resource.updated_at.isoformat() != entry["sourceRevision"]:
            raise ComputeError("输入资料已变化，请重新确认适配方案", 409)
        role = entry["role"]
        if entry["status"] == "direct":
            bind_prepared(workflow, entry, resource.pk)
            continue
        if (entry.get("script") or entry.get("scriptMode")) and not entry.get("taskId"):
            from .script_preparation import prepare

            if not prepare(workflow, user, policy, entry):
                return False
        if entry.get("resourceId"):
            prepared = resolve_workflow_resource(
                user, policy, entry["resourceId"], workflow
            )
            bind_prepared(workflow, entry, prepared.pk)
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
                        **(
                            {
                                "scriptInputs": entry.get("scriptInputs"),
                                "scriptSources": entry.get("sources"),
                            }
                            if entry.get("scriptMode")
                            else {}
                        ),
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
                bind_prepared(workflow, entry, prepared.pk)
                continue
            if any(key not in parameters for key in entry.get("missingParameters", [])):
                raise ComputeError("请先确认资料转换需要的字段：" + role)
            if workflow.operator_steps >= workflow.max_operator_steps:
                raise ComputeError("输入适配已达到本次任务的算子次数上限")
            loop = None
            if entry.get("nodeId") and workflow.parameters.get("_businessFlow"):
                from .state import state, binding
                from .node_contracts import recovery_contract

                node = next(
                    row
                    for row in binding(workflow)["definitionSnapshot"]["nodes"]
                    if row["id"] == entry["nodeId"]
                )
                loop = state(workflow)["nodes"][node["id"]].get("toolLoop")
                contract = node.get("contract") or recovery_contract(node)
                if (
                    loop is not None
                    and loop["operatorCalls"] >= contract["maxOperatorCalls"]
                ):
                    raise ComputeError("资料衔接已达到本节点算子调用上限")
                if loop is not None and loop["elapsedSeconds"] >= min(
                    contract["maxSeconds"], policy["maxRunSeconds"]
                ):
                    raise ComputeError("资料衔接已达到本节点主动处理时限")
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
                        "inputs": entry["scriptInputs"]
                        if entry.get("scriptMode")
                        else {entry["inputKey"]: resource.pk},
                        "parameters": parameters,
                        "idempotencyKey": f"adapt-{workflow.pk}-"
                        + hashlib.sha256(role.encode()).hexdigest()[:16]
                        + (
                            f"-s{entry['scriptAttempt']}"
                            if entry.get("scriptMode")
                            else ""
                        )
                        + (f"-n{loop['steps']}" if loop is not None else ""),
                    },
                )
                entry.update(
                    taskId=str(task.pk),
                    status="waiting_compute",
                    actualParameters=parameters,
                )
                workflow.operator_steps += 1
                if loop is not None:
                    loop["operatorCalls"] += 1
                    loop.setdefault("taskIds", []).append(str(task.pk))
                if entry.get("scriptMode"):
                    entry["scriptStatus"] = "running"
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
            if task.status == "failed" and workflow.plan.get(
                "inputPreparationPolicy", {}
            ).get("allowScripts"):
                from .script_preparation import fallback

                fallback(workflow, user, policy, entry, task.error)
                return False
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
                if entry.get("scriptMode"):
                    entry["scriptStatus"] = "registering"
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
        bind_prepared(workflow, entry, prepared.pk)
        if entry.get("scriptMode"):
            entry["scriptStatus"] = "completed"
            entry["scriptCurrent"].update(
                status="succeeded", taskId=str(task.pk), resourceId=prepared.pk
            )
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

            consumed = state(workflow).setdefault("consumedOutputs", [])
            if output.pk not in consumed:
                consumed.append(output.pk)
        workflow.status = "queued"
        _save(workflow, "输入适配已完成，继续已发布流程")
    workflow.plan["inputAdaptationComplete"] = True
    # The next model guard reads the durable plan, including direct bindings.
    # Freeze this transition before handing control to that model request.
    _save(workflow, "输入资料已准备好，继续已发布流程")
    return True
