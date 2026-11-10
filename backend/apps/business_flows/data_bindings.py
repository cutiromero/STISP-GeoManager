"""Feed actual upstream outputs through the existing controlled import queue."""

from apps.agent.compute_tools import authorized_task
from django.db import transaction
from apps.agent.workflow_controls import locked_workflow
from apps.agent.workflow_resources import resolve_workflow_resource
from apps.compute.models import ComputeImport
from apps.compute.packages import ComputeError
from apps.compute.quality import require_automatic_quality
from apps.compute.services import request_output_import
from .state import emit, state, WorkflowControlChanged


class InputQualityRejected(ComputeError):
    pass


def prepare_inputs(workflow, user, policy, node, version, available):
    result = {}
    pending = []
    node_states = state(workflow)["nodes"]
    specs = {item["key"]: item for item in version.manifest["inputs"]}
    actual_types = {}
    explicit = node.get("inputBindings", {})
    if set(explicit) - set(specs):
        raise ComputeError("业务流输入绑定不属于当前算子的清单")
    for key, binding in explicit.items():
        if "role" in binding:
            identity = workflow.plan["inputs"].get(binding["role"])
            if identity is None:
                from .input_adapters import logical_role

                requirements = {
                    item["key"]: item
                    for item in workflow.parameters["_businessFlow"][
                        "definitionSnapshot"
                    ]["inputRequirements"]
                }
                collection = [
                    value
                    for key, value in workflow.plan["inputs"].items()
                    if logical_role(key, requirements) == binding["role"]
                ]
                if len(collection) > 1:
                    if workflow.plan.get("inputPreparationPolicy", {}).get(
                        "allowScripts"
                    ):
                        result[key] = collection
                        continue
                    raise ComputeError(
                        "算子端口需要单份规范资料；当前流程未启用多份来源衔接"
                    )
                identity = collection[0] if collection else None
            if identity is None and not specs[key].get("required", True):
                continue
            if identity is None:
                raise ComputeError("缺少业务流角色：" + binding["role"])
            result[key] = identity
            continue
        source = node_states[binding["nodeId"]]
        if source["status"] != "succeeded" or not source.get("outputs", {}).get(
            "taskId"
        ):
            raise ComputeError("上游节点尚未通过全部审核，不能提供计算输入")
        if "contractOutputs" in source:
            from apps.compute.models import ComputeOutput

            declared = next(
                (
                    row
                    for row in source["contractOutputs"]
                    if row["name"] == binding["outputKey"]
                ),
                None,
            )
            visible = {row["id"] for row in source["outputs"].get("evidence", [])}
            identity = declared.get("evidenceId", "") if declared else ""
            if (
                identity not in visible
                or not identity.startswith("output-")
                or not identity[7:].isdigit()
            ):
                raise ComputeError("上游合同没有交付该具名真实成果")
            output = (
                ComputeOutput.objects.select_related("task")
                .filter(pk=int(identity[7:]))
                .first()
            )
            if output is not None:
                authorized_task(user, output.task_id, policy, workflow=workflow)
        else:
            task = authorized_task(
                user, source["outputs"]["taskId"], policy, workflow=workflow
            )
            output = task.outputs.filter(key=binding["outputKey"]).first()
        if output is None or (
            output.kind != specs[key]["kind"]
            and not workflow.plan.get("inputPreparationPolicy", {}).get("allowScripts")
        ):
            raise ComputeError("上游结果不存在或类型不符合下游算子输入")
        try:
            require_automatic_quality(output)
        except ComputeError as error:
            raise InputQualityRejected(str(error), error.status) from error
        imported = ComputeImport.objects.filter(output=output).first()
        if imported is None:
            with transaction.atomic():
                current = locked_workflow(workflow.pk)
                if (
                    current.cancel_requested
                    or current.pause_requested
                    or current.policy_snapshot.get("businessFlowControlEpoch", 0)
                    != workflow.policy_snapshot.get("businessFlowControlEpoch", 0)
                ):
                    raise WorkflowControlChanged("用户控制已阻止下一次资料准备")
                workflow.status, workflow.detail = (
                    "waiting_compute",
                    "正在通过计算中心准备上游结果，完成后继续当前节点",
                )
                node_states[node["id"]]["inputPreparation"] = "waiting"
                imported = request_output_import(
                    user, output, request_source=f"workflow:{workflow.pk}"
                )
                emit(
                    workflow,
                    "executor",
                    node["id"],
                    "preparing_inputs",
                    workflow.detail,
                )
        if imported.status in {"failed", "deleted"}:
            raise ComputeError(
                "上游结果准备失败：" + (imported.error or imported.status)
            )
        if imported.status != "ready" or not imported.resource_id:
            pending.append(binding["nodeId"])
            continue
        resource = resolve_workflow_resource(
            user, policy, imported.resource_id, workflow
        )
        result[key] = resource.pk
        consumed = state(workflow).setdefault("consumedOutputs", [])
        if output.pk not in consumed:
            consumed.append(output.pk)
    if pending:
        item = node_states[node["id"]]
        message = "正在通过计算中心准备上游结果，完成后继续当前节点"
        if item.get("inputPreparation") != "waiting":
            item["inputPreparation"] = "waiting"
            workflow.status, workflow.detail = "waiting_compute", message
            emit(workflow, "executor", node["id"], "preparing_inputs", message)
        return None
    for key, spec in specs.items():
        if key in result:
            continue
        chosen = available.get(key)
        if chosen is None:
            available_ids = {
                identity
                for values in available.values()
                for identity in (values if isinstance(values, list) else [values])
            }
            for identity in available_ids - actual_types.keys():
                actual_types[identity] = resolve_workflow_resource(
                    user, policy, identity, workflow
                ).data_type
            candidates = {
                identity
                for identity in available_ids
                if actual_types[identity] == spec["kind"]
            }
            if len(candidates) == 1:
                chosen = next(iter(candidates))
            elif len(available) == 1 and workflow.plan.get(
                "inputPreparationPolicy", {}
            ).get("allowScripts"):
                chosen = next(iter(available.values()))
        if chosen is not None:
            result[key] = chosen
        elif spec.get("required", True):
            raise ComputeError("算子输入无法唯一匹配：" + key)
    node_states[node["id"]].pop("inputPreparation", None)
    from .node_inputs import prepare

    return prepare(workflow, user, policy, node, version, result)
