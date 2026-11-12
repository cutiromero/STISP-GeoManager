"""人工恢复复用现有决定接口，绝不写入科研批准。"""

from copy import deepcopy

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.agent.workflow_controls import locked_workflow
from apps.agent.workflow_slots import require_compute_slot
from apps.compute.packages import ComputeError
from .state import binding, state, digest, emit


def decide_recovery(user, workflow, value):
    from .runtime import authorize, canonical_current_node, _inputs
    from .node_loop import encoded, loop_state

    key = value.get("idempotencyKey")
    if (
        not isinstance(key, str)
        or not 8 <= len(key) <= 80
        or not isinstance(value.get("feedback", ""), str)
        or len(value.get("feedback", "")) > 4000
        or value.get("decision") not in {"retry_recovery", "skip_node"}
        or set(value)
        - {
            "nodeId",
            "revision",
            "decision",
            "feedback",
            "idempotencyKey",
            "recoveryInputs",
            "recoveryParameters",
        }
    ):
        raise ValidationError("节点恢复决定格式无效")
    fingerprint = digest(value)
    with transaction.atomic():
        current = locked_workflow(workflow.pk)
        policy = authorize(user, current)
        values = state(current)
        receipts = values.setdefault("decisions", {})
        if key in receipts:
            if receipts[key] != fingerprint:
                raise ComputeError("恢复决定幂等键冲突", 409)
            return current
        node_id = canonical_current_node(current)
        item = values["nodes"].get(node_id)
        if (
            current.status != "waiting_approval"
            or value.get("nodeId") != node_id
            or str(value.get("revision")) != str(values["revision"])
            or not item
            or item.get("status") != "waiting_recovery"
            or not item.get("recovery")
        ):
            raise ComputeError("该节点不在当前恢复等待版本，请刷新", 409)
        definition = binding(current)["definitionSnapshot"]
        node = next(row for row in definition["nodes"] if row["id"] == node_id)
        if value["decision"] == "skip_node":
            if (
                current.workflow_type != "business_flow"
                or not item["recovery"].get("allowSkip")
                or item["human"]["required"]
            ):
                raise ComputeError("该节点不可跳过，人工审核不得由恢复决定代替", 409)
            if value.get("recoveryInputs") or value.get("recoveryParameters"):
                raise ValidationError("跳过节点不能同时变更输入或参数")
            item.update(
                status="skipped",
                executor={
                    "status": "skipped",
                    "summary": "用户跳过本节点：" + value.get("feedback", ""),
                },
            )
        elif current.workflow_type != "business_flow":
            if value.get("recoveryInputs") or value.get("recoveryParameters"):
                raise ComputeError(
                    "专业流程的资料和参数须通过原审核链路调整；此处仅重试原阶段或停止",
                    409,
                )
            stage = current.plan["stages"][current.plan["stageIndex"]]
            from . import logic_nodes

            if logic_nodes.enabled(current):
                if "retry_recovery" not in item["recovery"]["options"]:
                    raise ComputeError("节点额度已用尽，不能通过重试重置额度", 409)
                loop = loop_state(item)
                loop["userAnswer"] = value.get("feedback", "")
                loop.pop("pending", None)
                loop.pop("taskId", None)
            else:
                if stage.get("taskId") != item["recovery"].get("taskId"):
                    raise ComputeError("专业阶段失败任务已变化", 409)
                stage.pop("taskId", None)
            item["status"] = "executing"
            from apps.agent.workflow import _state_hash

            current.plan_hash = _state_hash(current.plan)
        else:
            replacements = value.get("recoveryInputs", {})
            parameters = value.get("recoveryParameters", {})
            if (
                not isinstance(replacements, dict)
                or not isinstance(parameters, dict)
                or len(encoded(value)) > 16 * 1024
            ):
                raise ValidationError("恢复资料与参数须为有界对象")
            from .input_adapters import logical_role

            specs = {row["key"]: row for row in definition["inputRequirements"]}
            if any(
                logical_role(role, specs) not in node["dataRoles"]
                for role in replacements
            ):
                raise ComputeError("只能更换当前节点可见的资料角色", 409)
            if replacements:
                inputs, revisions, planned = _inputs(
                    user,
                    definition,
                    {"inputs": {**current.plan["inputs"], **replacements}},
                    policy,
                )
                current.plan["inputs"] = inputs
                binding(current)["inputVersions"] = revisions
                current.resource_ids = sorted(
                    set(current.resource_ids) | set(inputs.values())
                )
                current.plan.setdefault("preparedNodeInputs", {}).pop(node_id, None)
                current.plan["inputAdaptations"] = [
                    row
                    for row in current.plan.get("inputAdaptations", [])
                    if row.get("nodeId") != node_id
                ]
                for row in planned["items"]:
                    if row["role"] in replacements:
                        current.plan["inputAdaptations"] = [
                            previous
                            for previous in current.plan["inputAdaptations"]
                            if previous["role"] != row["role"]
                        ]
                        current.plan["inputAdaptations"].append(
                            {
                                key: value
                                for key, value in row.items()
                                if key not in {"fields", "candidates"}
                            }
                        )
                current.plan.pop("inputAdaptationComplete", None)
            loop = loop_state(item)
            if parameters:
                from apps.compute.models import AlgorithmVersion
                from apps.agent.business_flow_operator_repair import _effective, _specs

                version_id = loop.get("baseVersionId") or node.get("algorithmVersionId")
                if not version_id:
                    raise ComputeError(
                        "尚未选择算子，请先回答问题，由智能体选择后再调整参数"
                    )
                version = AlgorithmVersion.objects.get(pk=version_id)
                _effective(
                    {
                        **node.get("parameters", {}),
                        **loop.get("humanParameters", {}),
                        **parameters,
                    },
                    _specs(version.manifest),
                )
                loop["humanParameters"] = {
                    **loop.get("humanParameters", {}),
                    **parameters,
                }
            loop["userAnswer"] = value.get("feedback", "")
            loop.pop("pending", None)
            loop.pop("taskId", None)
            if replacements or parameters:
                loop.pop("failure", None)
                loop.pop("lastObservation", None)
                loop["evidence"] = {}
                item["outputs"] = {}
            item.pop("computeTaskId", None)
            item.pop("executionContextId", None)
            item["executor"] = {"status": "pending"}
            item["reviewer"] = {
                "status": "pending" if node["review"]["ai"] else "not_required"
            }
            item["status"] = "executing"
            if node["kind"] == "operator":
                item["recoveryHistory"] = deepcopy(loop["history"])
                item["recoveryRevision"] = item.get("recoveryRevision", 0) + 1
                if parameters:
                    current.parameters.setdefault("nodeParameters", {}).setdefault(
                        node_id, {}
                    ).update(parameters)
                loop["manualRetry"] = True
            elif (
                loop["steps"] >= node["contract"]["maxSteps"]
                or loop["modelCalls"] >= node["contract"]["maxModelCalls"]
                or loop["elapsedSeconds"]
                >= min(node["contract"]["maxSeconds"], policy["maxRunSeconds"])
            ):
                raise ComputeError(
                    "本节点执行预算已用尽，不能通过人工重试重置额度；请跳过（若允许）或停止",
                    409,
                )
        item.pop("recovery", None)
        require_compute_slot(user, current.pk)
        receipts[key] = fingerprint
        current.status, current.detail = (
            "queued",
            "已保留完成节点，将从当前节点继续；未批准科研结果",
        )
        current.policy_snapshot["businessFlowControlEpoch"] = (
            current.policy_snapshot.get("businessFlowControlEpoch", 0) + 1
        )
        current.save(
            update_fields=[
                "plan",
                "plan_hash",
                "parameters",
                "resource_ids",
                "status",
                "detail",
                "policy_snapshot",
                "updated_at",
            ]
        )
        emit(current, "human", node_id, "recovery_retry", current.detail)
        return current
