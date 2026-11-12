"""有界、可重入的节点工具执行；完整观察按本节点编号保存。"""

from copy import deepcopy
import json
import time

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.agent.models import AgentWorkflowStep
from apps.agent.provider import ModelError
from apps.agent.workflow_controls import locked_workflow
from apps.compute.packages import ComputeError
from .node_contracts import (
    MAX_TOOL_BYTES,
    MAX_FRAGMENT_BYTES,
    MAX_EVIDENCE_BYTES,
    recovery_contract,
)
from .state import binding, emit, persist, state, WorkflowControlChanged

ACTION_LABELS = {
    "read_evidence": "读取证据片段",
    "read_task_record": "回顾任务节点记录",
    "operator_catalog": "查询可用算子",
    "preflight_operator": "检查算子输入差距",
    "run_operator": "提交算子计算",
    "prepare_input": "请求资料衔接并等待审核",
    "ask_user": "向用户询问",
    "finish_node": "核验并交付节点成果",
}
REMEDIES = {
    "adjust_parameters",
    "complete_mapping",
    "convert_input",
    "replace_operator",
}
NO_RETRY = {"unrecoverable", "platform_error", "platform_failure"}
MAX_HISTORY = 24


class InputsPending(Exception):
    pass


class RemedyRejected(ComputeError):
    pass


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()


def node_configuration(workflow, node, loop):
    return {
        "versionId": node.get("algorithmVersionId"),
        "inputBindings": deepcopy(node.get("inputBindings", {})),
        "parameters": {
            **node.get("parameters", {}),
            **workflow.parameters.get("nodeParameters", {}).get(node["id"], {}),
            **loop.get("humanParameters", {}),
        },
    }


def node_defaults(workflow, node, loop):
    """Small exact preview; long/code values remain behind an evidence reference."""
    configured = node_configuration(workflow, node, loop)

    def preview(values, *, bindings=False):
        result = {}
        for key, value in values.items():
            if not bindings and (
                key.casefold() in {"code", "script", "sql"}
                or isinstance(value, (dict, list))
                or len(encoded(value)) > 240
            ):
                continue
            candidate = {**result, key: value}
            if len(encoded(candidate)) <= 1536:
                result = candidate
        return result

    parameters = preview(configured["parameters"])
    bindings = preview(configured["inputBindings"], bindings=True)
    return {
        "versionId": configured["versionId"],
        "configuredParameters": parameters,
        "parametersComplete": len(parameters) == len(configured["parameters"]),
        "parameterCount": len(configured["parameters"]),
        "inputBindings": bindings,
        "bindingsComplete": len(bindings) == len(configured["inputBindings"]),
        "bindingCount": len(configured["inputBindings"]),
        "evidenceId": "node-config-" + node["id"],
    }


def loop_state(item):
    return item.setdefault(
        "toolLoop",
        {
            "steps": 0,
            "modelCalls": 0,
            "operatorCalls": 0,
            "recoveries": 0,
            "elapsedSeconds": 0,
            "history": [],
            "evidence": {},
            "catalogIds": [],
            "remedies": [],
        },
    )


def observation(error):
    failure = deepcopy(getattr(error, "failure", None) or {})
    gaps = deepcopy(getattr(error, "gaps", None) or failure.get("gaps", []))
    failure.setdefault("code", gaps[0]["code"] if gaps else "OPERATOR_FAILED")
    failure.setdefault("remedy", gaps[0]["remedy"] if gaps else "human_review")
    failure["message"] = str(error)[:1000]
    failure["gaps"] = gaps[:32]
    return failure


def wait_recovery(workflow, node, item, failure, *, question=""):
    loop = loop_state(item)
    if loop.get("taskIds"):
        from apps.compute.models import ComputeTask

        for identity in ComputeTask.objects.filter(
            pk__in=loop["taskIds"],
            status__in=["failed", "cancelled"],
            owner_id=workflow.owner_id,
        ).values_list("id", flat=True):
            state(workflow).setdefault("recoveredFailures", {})[str(identity)] = node[
                "id"
            ]
    if failure.get("taskId"):
        state(workflow).setdefault("recoveredFailures", {})[failure["taskId"]] = node[
            "id"
        ]
    item["status"] = "waiting_recovery"
    explanations = {
        "adjust_parameters": "算子参数不符合当前资料或允许范围。",
        "complete_mapping": "算子所需的字段或类别对应尚未补齐。",
        "convert_input": "当前资料的格式、字段类型或坐标系不能直接使用。",
        "replace_data": "当前资料需要更换或补充。",
        "unrecoverable": "该算子无法自动恢复当前问题。",
        "human_review": "需要您确认资料或处理方式。",
    }
    prefix = (
        "计算服务发生故障，已停止自动重试。"
        if str(failure.get("code", "")).startswith("PLATFORM_")
        else explanations.get(failure.get("remedy"), "")
    )
    item["recovery"] = {
        "reason": (prefix + failure.get("message", "当前资料尚不能完成节点"))[:1000],
        "failure": failure,
        "question": question[:2000],
        "attempts": [row["summary"] for row in loop["history"] if row.get("remedy")][
            -6:
        ],
        "allowSkip": bool(node.get("allowSkip", False))
        and not item["human"]["required"],
        "options": [
            "retry_recovery",
            *(
                ["skip_node"]
                if node.get("allowSkip") and not item["human"]["required"]
                else []
            ),
            "cancel",
        ],
    }
    contract = node.get("contract")
    if contract and (
        loop["steps"] >= contract["maxSteps"]
        or loop["modelCalls"] >= contract["maxModelCalls"]
        or loop["elapsedSeconds"] >= contract["maxSeconds"]
    ):
        item["recovery"]["options"].remove("retry_recovery")
        item["recovery"]["reason"] += (
            " 本节点合同额度已用尽，恢复不会重置额度；请停止，或在定义允许时跳过。"
        )
    workflow.status, workflow.detail = (
        "waiting_approval",
        "节点等待恢复：" + item["recovery"]["reason"][:230],
    )
    emit(
        workflow,
        "system",
        node["id"],
        "recovery_required",
        workflow.detail,
        data={"code": failure.get("code"), "attempts": item["recovery"]["attempts"]},
    )


def observe_failure(workflow, node, item, failure):
    loop = loop_state(item)
    if item.get("computeTaskId"):
        from apps.compute.models import ComputeTask
        from apps.compute.services import _retry_inputs

        task = ComputeTask.objects.filter(
            pk=item["computeTaskId"],
            owner_id=workflow.owner_id,
            project_tag_id=workflow.project_tag_id,
        ).first()
        if task:
            loop["lastSubmission"] = {
                "versionId": task.version_id,
                "inputs": _retry_inputs(task),
                "parameters": deepcopy(task.parameters),
                "fieldMappings": deepcopy(task.field_mappings),
            }
        state(workflow).setdefault("recoveredFailures", {})[item["computeTaskId"]] = (
            node["id"]
        )
    loop["failure"] = deepcopy(failure)
    loop.pop("manualRetry", None)
    loop.pop("pending", None)
    item.pop("computeTaskId", None)
    loop.pop("taskId", None)
    if (
        failure.get("remedy") in NO_RETRY
        or str(failure.get("code", "")).startswith("PLATFORM_")
        or not binding(workflow).get("agentEnabled", True)
        or loop["recoveries"]
        >= node.get("contract", recovery_contract(node))["maxRecoveries"]
    ):
        wait_recovery(workflow, node, item, failure)
    else:
        workflow.status = "queued"
        emit(
            workflow,
            "executor",
            node["id"],
            "recovery_observed",
            "算子未完成，智能体将检查可用补救：" + failure["message"][:200],
        )


def visible_inputs(workflow, node, loop):
    from . import logic_nodes

    if logic_nodes.enabled(workflow):
        return logic_nodes.visible_inputs(workflow, node)
    from .input_adapters import logical_role

    specs = {
        row["key"]: row
        for row in binding(workflow)["definitionSnapshot"]["inputRequirements"]
    }
    values = {
        key: value
        for key, value in workflow.plan.get("inputs", {}).items()
        if logical_role(key, specs) in node["dataRoles"]
    }
    values.update(
        {
            "prepared:" + key: value
            for key, value in workflow.plan.get("preparedNodeInputs", {})
            .get(node["id"], {})
            .items()
        }
    )
    values.update(loop.get("upstreamInputs", {}))
    return values


def version_for(workflow, user, node, loop, identity, policy):
    from apps.compute.models import AlgorithmVersion
    from apps.compute.services import allowed_algorithms, agent_algorithm_allowed
    from apps.agent.demo_decisions import EDIT_CHECKS

    if not policy.get("operatorEnabled"):
        raise PermissionDenied("当前策略未允许算子工具")
    if type(identity) is not int or identity not in loop["catalogIds"]:
        raise ComputeError("只能使用本节点已查询目录中的算子版本")
    version = (
        AlgorithmVersion.objects.select_related("algorithm")
        .filter(
            pk=identity,
            status="published",
            algorithm__in=allowed_algorithms().filter(enabled=True),
        )
        .first()
    )
    if (
        not version
        or not agent_algorithm_allowed(version)
        or version.algorithm.identifier in EDIT_CHECKS
    ):
        raise PermissionDenied("算子未发布、已撤权或须通过专业人工审核链路")
    from . import logic_nodes

    if logic_nodes.enabled(workflow) and identity != node["algorithmVersionId"]:
        raise ComputeError("算子版本不属于本节点已确认科学配方，请重新确认计划")
    previous_id = (
        loop.get("failure", {}).get("versionId")
        or loop.get("lastSubmission", {}).get("versionId")
        or node.get("algorithmVersionId")
    )
    if loop.get("failure") and previous_id and previous_id != identity:
        previous = AlgorithmVersion.objects.get(pk=previous_id)
        before, after = (
            previous.manifest.get("capabilities", {}),
            version.manifest.get("capabilities", {}),
        )
        if not (
            set(before.get("operations", [])) & set(after.get("operations", []))
        ) or not set(before.get("dataTypes", [])) <= set(after.get("dataTypes", [])):
            raise ComputeError("替换算子没有声明等价操作能力和资料类型，需人工处理")
        original_outputs = {
            (row["key"], row["kind"])
            for row in previous.manifest["outputs"]
            if row.get("required", True)
        }
        if not original_outputs <= {
            (row["key"], row["kind"]) for row in version.manifest["outputs"]
        }:
            raise ComputeError("替换算子不能满足原有必需输出")
    return version


def submission(workflow, user, policy, node, loop, arguments):
    from apps.agent.workflow_resources import resolve_workflow_resource
    from apps.compute.preflight import expand_bindings
    from apps.agent.business_flow_operator_repair import _effective, _specs

    version = version_for(
        workflow, user, node, loop, arguments.get("versionId"), policy
    )
    inputs, parameters, mappings = (
        arguments.get("inputs", {}),
        arguments.get("parameters", {}),
        arguments.get("fieldMappings", {}),
    )
    if not all(isinstance(value, dict) for value in (inputs, parameters, mappings)):
        raise ComputeError("输入、参数与字段映射必须为对象")
    inputs = resolve_output_bindings(workflow, user, policy, node, loop, inputs)
    if len(encoded(arguments)) > MAX_TOOL_BYTES:
        raise ComputeError("工具参数超过8192字节")
    flat, _, input_specs = expand_bindings(version.manifest, inputs)
    permitted = set(visible_inputs(workflow, node, loop).values())
    for identity in flat.values():
        if type(identity) is not int or identity not in permitted:
            raise ComputeError("输入不属于本节点可见资料，不能扩大范围")
        resolve_workflow_resource(user, policy, identity, workflow)
    specs = {row["key"]: row for row in version.manifest["parameters"]}
    adjustable = {
        key
        for key, row in specs.items()
        if row.get("agent", {}).get("adjustable") is True
    }
    baseline = (
        node.get("parameters", {})
        if version.pk == node.get("algorithmVersionId")
        else {}
    )
    baseline = {
        **baseline,
        **workflow.parameters.get("nodeParameters", {}).get(node["id"], {}),
        **loop.get("humanParameters", {}),
    }
    from . import logic_nodes

    fixed_keys = set(parameters) - adjustable
    if fixed_keys:
        changed = [
            key
            for key in fixed_keys
            if key not in specs
            or key not in baseline
            or type(parameters[key]) is not type(baseline[key])
            or parameters[key] != baseline[key]
        ]
        if changed:
            raise ComputeError(
                "固定科学参数不能改变，需沿用已确认值：" + "、".join(sorted(changed))
            )
    parameters = {**baseline, **parameters}
    for input_spec in input_specs:
        selected = mappings.get(input_spec["key"], {})
        if not isinstance(selected, dict):
            raise ComputeError("字段映射必须为语义角色对象")
        for requirement in input_spec.get("fields", []):
            parameter = requirement.get("parameter")
            if (
                parameter
                and parameter not in adjustable
                and requirement["role"] in selected
                and selected[requirement["role"]]
                != parameters.get(parameter, specs[parameter].get("default"))
            ):
                raise ComputeError("字段映射不能修改未声明agent.adjustable的关联参数")
    _effective(
        parameters, [{**spec, "required": False} for spec in _specs(version.manifest)]
    )
    body = {
        "versionId": version.pk,
        "inputs": inputs,
        "parameters": parameters,
        "fieldMappings": mappings,
        "trial": False,
        "name": binding(workflow)["name"] + " · " + node["title"],
        "idempotencyKey": f"node-{workflow.pk}-{node['id']}-{loop['steps']}",
    }
    if logic_nodes.enabled(workflow):
        logic_nodes.check_submission(workflow, node, version, body)
    return version, body


def resolve_output_bindings(workflow, user, policy, node, loop, inputs):
    from apps.agent.compute_tools import authorized_task
    from apps.agent.workflow_resources import resolve_workflow_resource
    from apps.compute.models import ComputeOutput, ComputeImport
    from apps.compute.services import request_output_import
    from apps.compute.quality import require_automatic_quality

    visible = {
        row["id"]
        for parent in node["dependsOn"]
        for row in state(workflow)["nodes"][parent]
        .get("outputs", {})
        .get("evidence", [])
    }
    from . import logic_nodes
    from .execution_session import session

    if logic_nodes.enabled(workflow) and session(workflow):
        visible.update(
            f"output-{identity}"
            for identity in logic_nodes.ancestor_output_ids(workflow, node)
        )
    result = deepcopy(inputs)
    pending = False
    for key, reference in inputs.items():
        if not isinstance(reference, dict):
            continue
        identity = reference.get("outputId")
        if (
            set(reference) != {"outputId"}
            or type(identity) is not int
            or f"output-{identity}" not in visible
        ):
            raise ComputeError("输出输入绑定只能引用当前节点直接依赖的真实成果")
        output = ComputeOutput.objects.select_related("task").get(pk=identity)
        task = authorized_task(user, output.task_id, policy, workflow=workflow)
        if task.status != "succeeded":
            raise ComputeError("依赖结果尚未成功")
        require_automatic_quality(output)
        imported = ComputeImport.objects.filter(output=output).first()
        if imported is None:
            with transaction.atomic():
                current = locked_workflow(workflow.pk)
                if (
                    current.pause_requested
                    or current.cancel_requested
                    or current.policy_snapshot.get("businessFlowControlEpoch", 0)
                    != workflow.policy_snapshot.get("businessFlowControlEpoch", 0)
                ):
                    raise WorkflowControlChanged("用户控制已阻止准备依赖结果")
                imported = request_output_import(
                    user, output, request_source=f"workflow:{workflow.pk}"
                )
        if imported.status in {"failed", "deleted"}:
            raise ComputeError(
                "依赖成果准备未完成：" + (imported.error or imported.status)
            )
        if imported.status != "ready" or not imported.resource_id:
            pending = True
            continue
        resource = resolve_workflow_resource(
            user, policy, imported.resource_id, workflow
        )
        result[key] = resource.pk
        loop.setdefault("upstreamInputs", {})[f"output:{identity}"] = resource.pk
        consumed = state(workflow).setdefault("consumedOutputs", [])
        if identity not in consumed:
            consumed.append(identity)
    if pending:
        workflow.status = "waiting_compute"
        emit(
            workflow,
            "executor",
            node["id"],
            "preparing_inputs",
            "正在准备当前节点依赖的真实成果；不重复请求模型",
        )
        raise InputsPending()
    return result


def check_remedy(loop, arguments, action, contract):
    if not loop.get("failure"):
        return
    failure = loop["failure"]
    if failure.get("remedy") in NO_RETRY or failure["code"].startswith("PLATFORM_"):
        raise RemedyRejected("平台故障或不可恢复的错误不能自动重试")
    remedy = arguments.get("remedy")
    if not isinstance(remedy, str) or remedy not in REMEDIES:
        raise RemedyRejected("失败后的运行或转换须明确声明补救类别")
    if loop["recoveries"] >= contract["maxRecoveries"]:
        raise RemedyRejected("节点自恢复额度已用尽")
    if any(
        not isinstance(arguments.get(key, {}), dict)
        for key in ("parameters", "fieldMappings", "inputs")
    ):
        raise RemedyRejected("补救的输入、参数与字段映射必须为对象")
    previous = loop.get("lastSubmission", {})
    if remedy == "adjust_parameters" and not any(
        value != previous.get("parameters", {}).get(key)
        for key, value in arguments.get("parameters", {}).items()
    ):
        raise RemedyRejected("调整参数补救必须改变实际参数")
    if remedy == "complete_mapping" and not (
        any(
            value != previous.get("fieldMappings", {}).get(key, {}).get(role)
            for key, selected in arguments.get("fieldMappings", {}).items()
            if isinstance(selected, dict)
            for role, value in selected.items()
        )
        or arguments.get("inputs")
        and arguments["inputs"] != previous.get("inputs", {})
    ):
        raise RemedyRejected("补充映射补救必须改变字段映射或集合输入")
    if remedy == "replace_operator" and arguments.get("versionId") == previous.get(
        "versionId"
    ):
        raise RemedyRejected("替换补救必须选择不同算子")
    if action == "prepare_input" and remedy != "convert_input":
        raise RemedyRejected("资料衔接须声明convert_input")
    from .state import digest

    # Distinct parameters/mappings may need several attempts for the same error.
    # Compare effective proposals, not only the diagnostic category.
    proposal = {
        key: deepcopy(previous.get(key, {}))
        for key in ("inputs", "parameters", "fieldMappings")
    }
    proposal["versionId"] = arguments.get("versionId", previous.get("versionId"))
    for name in ("inputs", "parameters", "fieldMappings"):
        proposal[name].update(arguments.get(name, {}))
    key = failure["code"] + ":" + remedy + ":" + digest(proposal)
    if key in loop["remedies"]:
        raise RemedyRejected("同一错误的相同实际方案已经尝试过，不得重复")
    loop["remedies"].append(key)
    loop["recoveries"] += 1


def store_result(workflow, node, item, action, result, *, arguments=None):
    loop = loop_state(item)
    raw = encoded(result)
    if len(raw) > MAX_EVIDENCE_BYTES:
        raise ComputeError("工具完整结果超过96KiB安全上限")
    identity = f"node-tool-{node['id']}-{loop['steps']}"
    loop["evidence"][identity] = {
        "id": identity,
        "kind": "tool",
        "title": ACTION_LABELS.get(action, "被拒绝的工具动作"),
        "result": deepcopy(result),
    }
    preview = (
        result
        if len(raw) <= MAX_TOOL_BYTES
        else {
            "preview": raw[: MAX_TOOL_BYTES - 512].decode("utf-8", errors="ignore"),
            "truncated": True,
            "totalBytes": len(raw),
            "evidenceId": identity,
        }
    )
    if action == "operator_catalog" and len(raw) > MAX_TOOL_BYTES:
        offset = len(b'{"operators":[')
        entries = []
        for operator in result["operators"]:
            size = len(encoded(operator))
            entries.append(
                {
                    "versionId": operator["versionId"],
                    "name": operator["name"][:40],
                    "operations": operator.get("capabilities", {}).get(
                        "operations", []
                    ),
                    "offset": offset,
                    "length": size,
                }
            )
            offset += size + 1
        preview = {
            "operators": entries,
            "evidenceId": identity,
            "truncated": True,
            "totalBytes": len(raw),
            "message": "目录详情已登记；按本证据编号及条目的offset/length读取清单，单项最多4096字节",
        }
    while len(encoded(preview)) > MAX_TOOL_BYTES:
        if "operators" in preview:
            preview["operators"].pop()
            preview["omittedOperators"] = preview.get("omittedOperators", 0) + 1
        else:
            preview["preview"] = preview["preview"][
                : max(0, len(preview["preview"]) - 256)
            ]
    loop["lastObservation"] = {"evidenceId": identity, "result": preview}
    summary = (
        ACTION_LABELS.get(action, "被拒绝的工具动作")
        + "："
        + (
            str(result.get("message", result.get("summary", "结果已登记为证据")))[:180]
            if isinstance(result, dict)
            else "目录已返回"
        )
    )
    row = {
        "step": loop["steps"],
        "action": action,
        "evidenceId": identity,
        "summary": summary,
        "argumentKeys": sorted((arguments or {}).keys()),
        "parameterSummary": encoded((arguments or {}).get("parameters", {})).decode()[
            :500
        ],
        "resultBytes": len(raw),
        "remedy": (arguments or {}).get("remedy", ""),
        "modelCalls": loop["modelCalls"],
        "operatorCalls": loop["operatorCalls"],
        "elapsedSeconds": round(loop["elapsedSeconds"], 3),
    }
    row["usage"] = deepcopy(loop.get("lastAudit", {}).get("usage", {}))
    row["requestId"] = loop.get("lastAudit", {}).get("requestId", "")
    loop["history"] = [*loop["history"], row][-MAX_HISTORY:]
    from .main_loop import remember

    remember(workflow, node["id"], action, summary)
    loop.pop("pending", None)
    emit(workflow, "executor", node["id"], "node_tool_step", summary, data=row)


def completed_task(workflow, user, policy, node, item, loop):
    from . import logic_nodes

    if logic_nodes.enabled(workflow):
        return logic_nodes.completed_task(workflow, user, policy, node, item, loop)
    from apps.agent.compute_tools import authorized_task
    from apps.agent.compute_result_tools import read_output
    from .engine import stash_evidence
    from .state import parent_run

    task = authorized_task(user, loop["taskId"], policy, workflow=workflow)
    if task.status in {"queued", "validating", "running", "cancelling"}:
        workflow.status = "waiting_compute"
        return None
    if task.status != "succeeded":
        state(workflow).setdefault("recoveredFailures", {})[str(task.pk)] = node["id"]
        failure = {
            **(task.failure or {}),
            "message": (task.error or task.status)[:1000],
            "versionId": task.version_id,
        }
        failure.setdefault("code", "OPERATOR_FAILED")
        failure.setdefault("remedy", "human_review")
        loop["failure"] = failure
        return {"failure": failure, "message": "算子未完成：" + failure["message"]}
    rows = []
    for output in task.outputs.exclude(kind="archive")[:8]:
        result, _ = read_output(
            parent_run(workflow),
            user,
            policy,
            {"outputId": output.pk, "limit": 20},
            workflow=workflow,
        )
        row = {
            "id": f"output-{output.pk}",
            "kind": "output",
            "title": output.label or output.file_name,
            "result": result,
        }
        rows.append(row)
        loop["evidence"][row["id"]] = row
    if not rows:
        raise ComputeError("算子没有可读取的真实输出")
    existing = item.get("outputs", {}).get("evidence", [])
    item["outputs"] = {
        "taskId": str(task.pk),
        "evidence": [*existing, *stash_evidence(workflow, rows)],
    }
    loop.pop("failure", None)
    return {
        "status": "succeeded",
        "taskId": str(task.pk),
        "evidenceIds": [row["id"] for row in rows],
        "outputs": rows,
        "message": "算子计算成功，真实结果已读取",
    }


def finish(node, item, arguments, evidence):
    contract = node.get("contract") or recovery_contract(node)
    outputs = arguments.get("outputs", [])
    if (
        not isinstance(outputs, list)
        or len(outputs) > 8
        or any(
            not isinstance(row, dict)
            or set(row) != {"name", "semanticType", "evidenceId"}
            or any(
                not isinstance(value, str) or not value or len(value) > 160
                for value in row.values()
            )
            for row in outputs
        )
    ):
        raise ComputeError("必需输出须为名称、语义类型与真实证据编号的数组")
    by_name = {row["name"]: row for row in outputs if isinstance(row.get("name"), str)}
    if len(by_name) != len(outputs):
        raise ComputeError("节点输出名称不得重复")
    missing = [
        row["name"]
        for row in contract["requiredOutputs"]
        if row["name"] not in by_name
        or by_name[row["name"]].get("semanticType") != row["semanticType"]
    ]
    if missing:
        raise ComputeError("节点尚缺必需输出：" + "、".join(missing))
    actual = {row["id"]: row for row in evidence}
    own_outputs = {
        row["id"]
        for row in item.get("outputs", {}).get("evidence", [])
        if row.get("kind") == "output"
    }
    if (
        node.get("kind") == "operator" or node.get("algorithmVersionId")
    ) and not own_outputs:
        raise ComputeError("算子节点尚无本节点真实计算输出，不能直接交付")
    for row in outputs:
        if row["evidenceId"] in item.get("toolLoop", {}).get("invalidOutputIds", []):
            raise ComputeError(
                "该成果已被退回，须提交修订后的真实结果，不能直接重新交付"
            )
        source = actual.get(row.get("evidenceId"))
        if row["semanticType"] != "analysis" and row["evidenceId"] not in own_outputs:
            raise ComputeError(
                "算子节点必须交付本节点真实计算的输出，不能用上游成果代替执行"
            )
        if not source or (
            row["semanticType"] != "analysis" and source["kind"] != "output"
        ):
            raise ComputeError(
                "非分析输出须引用本节点真实成功算子的输出，不得以失败观察冒充成果"
            )
        if row["semanticType"] not in {"analysis", "operator_result"}:
            output = source.get("result", {}).get("output", {})
            semantic = output.get("metadata", {}).get("semanticType")
            if row["semanticType"] not in {output.get("kind"), semantic}:
                raise ComputeError("真实输出类型不符合合同语义：" + row["name"])
    summary = arguments.get("summary")
    citations = arguments.get("evidenceIds")
    limitations = arguments.get("limitations", [])
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 6000:
        raise ComputeError("节点结论须为非空且最多6000字符")
    if (
        not isinstance(citations, list)
        or not citations
        or any(not isinstance(value, str) or value not in actual for value in citations)
    ):
        raise ComputeError("节点引用缺失或不属于当前实际证据")
    if (
        not isinstance(limitations, list)
        or len(limitations) > 20
        or any(not isinstance(value, str) or len(value) > 1000 for value in limitations)
    ):
        raise ComputeError("节点限制说明无效")
    checks = arguments.get("acceptanceChecks", [])
    if (
        not isinstance(checks, list)
        or any(not isinstance(value, str) or len(value) > 1000 for value in checks)
        or len(checks) > 8
    ):
        raise ComputeError("验收说明须为最多8项的文字数组")
    # Self-repeating acceptance text proves nothing. Output bindings and real
    # evidence above, followed by configured review, establish completion.
    item["contractOutputs"] = deepcopy(outputs)
    return {
        "summary": summary.strip(),
        "findings": [],
        "limitations": limitations,
        "evidenceIds": citations,
    }


def execute_tool(
    workflow, user, policy, node, item, action, arguments, evidence, contract, guard
):
    from apps.agent.policy import fresh_user, require_access

    loop = loop_state(item)
    guard()
    user = fresh_user(workflow.owner_id)
    policy = require_access(user, "agent", workflow.model)
    if len(encoded(arguments)) > MAX_TOOL_BYTES:
        raise ComputeError("单个动作参数超过8192字节")
    if action == "read_task_record":
        from .execution_session import task_record

        result = task_record(
            workflow,
            arguments.get("nodeId"),
            offset=arguments.get("offset", 0),
            limit=arguments.get("limit", 8),
        )
        guard()
        return result
    if action == "read_evidence":
        rows = {row["id"]: row for row in [*evidence, *loop["evidence"].values()]}
        identity, offset, length = (
            arguments.get("evidenceId"),
            arguments.get("offset", 0),
            arguments.get("length", MAX_FRAGMENT_BYTES),
        )
        if identity == "node-config-" + node["id"] and node.get("kind") == "operator":
            rows[identity] = {"result": node_configuration(workflow, node, loop)}
        if not isinstance(identity, str) or identity not in rows:
            raise ComputeError("证据不属于本节点可见范围")
        if (
            type(offset) is not int
            or offset < 0
            or type(length) is not int
            or not 1 <= length <= MAX_FRAGMENT_BYTES
        ):
            raise ComputeError("片段偏移须非负，长度为1至4096字节")
        raw = encoded(rows[identity].get("result", rows[identity]))
        if offset > len(raw):
            raise ComputeError("证据片段超出实际范围")
        return {
            "evidenceId": identity,
            "offset": offset,
            "length": length,
            "totalBytes": len(raw),
            "text": raw[offset : offset + length].decode("utf-8", errors="ignore"),
        }
    if action == "operator_catalog":
        from apps.compute.operator_catalog import operator_catalog
        from . import logic_nodes

        if not policy.get("operatorEnabled"):
            raise PermissionDenied("当前策略未允许算子工具")
        limit = arguments.get("limit", 20)
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ComputeError("本节点目录每次最多20项")
        if any(
            arguments.get(key) is not None and not isinstance(arguments[key], str)
            for key in ("operation", "dataType", "keyword")
        ):
            raise ComputeError("目录筛选条件须为文字")
        rows = (
            logic_nodes.catalog_rows(workflow, user, policy, node, arguments)
            if logic_nodes.enabled(workflow)
            else operator_catalog(
                user,
                workflow.project_tag_id,
                operation=arguments.get("operation"),
                data_type=arguments.get("dataType"),
                keyword=arguments.get("keyword", ""),
                limit=limit,
                max_bytes=4096,
                version_id=arguments.get("versionId"),
                view=arguments.get("view", "execution"),
            )
        )
        loop["catalogIds"] = list(
            dict.fromkeys([*loop["catalogIds"], *[row["versionId"] for row in rows]])
        )[-100:]
        return {"operators": rows, "message": f"返回{len(rows)}个当前权限内可调用算子"}
    if action in {"preflight_operator", "run_operator", "prepare_input"}:
        from apps.compute.services import validate_submission, submit

        version, body = submission(workflow, user, policy, node, loop, arguments)
        if action == "preflight_operator":
            validate_submission(user, body)
            from .logic_nodes import submission_digest

            loop["preflightDigest"] = submission_digest(body)
            return {"valid": True, "gaps": [], "message": "预检通过，尚未提交计算"}
        from . import logic_nodes
        from .execution_session import session

        if (
            (logic_nodes.enabled(workflow) or session(workflow))
            and action == "run_operator"
            and loop.get("preflightDigest") != logic_nodes.submission_digest(body)
        ):
            raise ComputeError("须先对相同版本、输入、参数和字段映射完成预检，才能计算")
        if action == "run_operator":
            from .model_requests import operator_budget_wait

            if loop["operatorCalls"] >= contract["maxOperatorCalls"]:
                raise operator_budget_wait(
                    node["id"],
                    loop["operatorCalls"],
                    contract["maxOperatorCalls"],
                    scope="node",
                )
            if workflow.operator_steps >= workflow.max_operator_steps:
                raise operator_budget_wait(
                    node["id"], workflow.operator_steps, workflow.max_operator_steps
                )
        check_remedy(loop, arguments, action, contract)
        if action == "prepare_input":
            from .node_inputs import prepare

            if not workflow.plan.get("inputPreparationPolicy", {}).get("allowScripts"):
                raise ComputeError("本次运行未启用资料衔接脚本，不能绕过审核")
            from types import SimpleNamespace
            from apps.compute.preflight import expand_bindings

            flat, collections, specs = expand_bindings(version.manifest, body["inputs"])
            pseudo = {**node, "parameters": body["parameters"]}
            expanded_version = SimpleNamespace(
                manifest={**version.manifest, "inputs": specs}
            )
            forced = {
                row["input"]
                for row in loop.get("failure", {}).get("gaps", [])
                if row.get("remedy") == "convert_input"
            } or set(flat)
            loop["pending"]["collections"] = collections
            converted = prepare(
                workflow,
                user,
                policy,
                pseudo,
                expanded_version,
                flat,
                force_keys=forced,
            )
            if converted is None:
                loop["pending"]["preparing"] = True
                persist(workflow)
                return None
            loop.pop("failure", None)
            return {
                "inputs": collection_shape(converted, collections),
                "message": "资料衔接已完成或无需转换",
            }
        with transaction.atomic():
            current = locked_workflow(workflow.pk)
            if (
                current.cancel_requested
                or current.pause_requested
                or current.policy_snapshot.get("businessFlowControlEpoch", 0)
                != workflow.policy_snapshot.get("businessFlowControlEpoch", 0)
            ):
                raise WorkflowControlChanged("用户控制已阻止工具提交")
            guard()
            if not require_access(
                fresh_user(workflow.owner_id), "agent", workflow.model
            ).get("operatorEnabled"):
                raise PermissionDenied("算子提交前策略已撤销执行权限")
            if logic_nodes.enabled(workflow):
                from apps.agent.workflow import _authorize
                from apps.agent.demo_workflow import authorize_demo

                if current.plan_hash != workflow.plan_hash:
                    raise ComputeError("专业科学方案已变化，请重新核对后计算", 409)
                actor, current_policy = _authorize(current)
                authorize_demo(current, actor, current_policy)
                logic_nodes.revalidate_inputs(
                    current, actor, current_policy, node, body
                )
            task = submit(user, body)
            AgentWorkflowStep.objects.get_or_create(
                workflow=workflow,
                compute_task_id=task.pk,
                defaults={
                    "sequence": workflow.steps.count() + 1,
                    "kind": "submit_operator",
                    "status": "waiting",
                    "message": node["title"],
                },
            )
            loop["operatorCalls"] += 1
            workflow.operator_steps += 1
            loop["taskId"] = str(task.pk)
            loop.setdefault("taskIds", []).append(str(task.pk))
            loop["baseVersionId"] = version.pk
            loop["lastSubmission"] = deepcopy(body)
            loop["lastSubmission"]["parameters"] = deepcopy(task.parameters)
            loop["lastSubmission"]["fieldMappings"] = deepcopy(task.field_mappings)
            item["computeTaskId"] = str(task.pk)
            workflow.status = "waiting_compute"
            emit(
                workflow,
                "executor",
                node["id"],
                "operator_submitted",
                "智能体已提交算子，等待真实计算结果",
                data={
                    "step": loop["steps"],
                    "versionId": version.pk,
                    "operatorCalls": loop["operatorCalls"],
                    "parameterSummary": encoded(body["parameters"]).decode()[:500],
                },
            )
        return None
    if action == "ask_user":
        question = arguments.get("question")
        if (
            not isinstance(question, str)
            or not question.strip()
            or len(question) > 2000
        ):
            raise ComputeError("问题须为1至2000字符")
        wait_recovery(
            workflow,
            node,
            item,
            loop.get(
                "failure",
                {
                    "code": "QUESTION",
                    "message": "智能体需要确认资料含义",
                    "remedy": "human_review",
                },
            ),
            question=question,
        )
        return {"message": question}
    if action == "finish_node":
        return finish(node, item, arguments, [*evidence, *loop["evidence"].values()])
    raise ComputeError("未知节点工具")


def collection_shape(converted, collections):
    result = dict(converted)
    for key, rows in collections.items():
        result[key] = [
            {"resourceId": result.pop(row["key"]), "label": row["label"]}
            for row in rows
        ]
    return result


def advance_loop(workflow, user, policy, node, item, evidence, *, guard, callbacks):
    from apps.agent.business_flow_actions import request_action

    return advance_tool_execution(
        workflow,
        user,
        policy,
        node,
        item,
        evidence,
        guard=guard,
        callbacks=callbacks,
        requester=request_action,
    )


def advance_tool_execution(
    workflow, user, policy, node, item, evidence, *, guard, callbacks, requester
):
    """Execute tools and resume compute; the caller owns the model/agent loop."""
    from apps.agent.business_flow_actions import ActionFormatError
    from apps.agent.compute_tools import authorized_task

    loop = loop_state(item)
    contract = node.get("contract") or recovery_contract(node)
    guard()
    for task_id in loop.get("taskIds", []):
        authorized_task(user, task_id, policy, workflow=workflow)
    if item.get("recovery"):
        return None
    if (
        loop.get("failure")
        and loop["recoveries"] >= contract["maxRecoveries"]
        and not loop.get("taskId")
        and not loop.get("pending")
    ):
        wait_recovery(workflow, node, item, loop["failure"])
        return None
    if loop.get("taskId"):
        started = time.monotonic()
        try:
            result = completed_task(workflow, user, policy, node, item, loop)
            guard()
        except (ComputeError, ValidationError) as error:
            failure = observation(error)
            loop["failure"] = failure
            result = {"failure": failure, "message": failure["message"]}
        if result is None:
            return None
        loop["elapsedSeconds"] += time.monotonic() - started
        if loop["elapsedSeconds"] >= contract["maxSeconds"]:
            wait_recovery(
                workflow,
                node,
                item,
                {
                    "code": "NODE_LIMIT",
                    "remedy": "human_review",
                    "message": "读取实际计算结果时已达到本节点主动处理时限",
                },
            )
            return None
        loop.pop("taskId", None)
        try:
            store_result(
                workflow,
                node,
                item,
                "run_operator",
                result,
                arguments=loop.get("pending", {}).get("arguments"),
            )
        except ComputeError as error:
            wait_recovery(workflow, node, item, observation(error))
            return None
        if result.get("failure") and (
            result["failure"].get("remedy") in NO_RETRY
            or result["failure"]["code"].startswith("PLATFORM_")
        ):
            wait_recovery(workflow, node, item, result["failure"])
        return None
    if loop.get("pending", {}).get("preparing"):
        converted = workflow.plan.get("preparedNodeInputs", {}).get(node["id"], {})
        loop.pop("failure", None)
        converted = collection_shape(converted, loop["pending"].get("collections", {}))
        store_result(
            workflow,
            node,
            item,
            "prepare_input",
            {"inputs": converted, "message": "资料已通过现有衔接与审核机制准备完成"},
            arguments=loop["pending"]["arguments"],
        )
        return None
    remaining = contract["maxSeconds"] - loop["elapsedSeconds"]
    if (
        not loop.get("pending") and loop["steps"] >= contract["maxSteps"]
    ) or remaining < 1:
        wait_recovery(
            workflow,
            node,
            item,
            {
                "code": "NODE_LIMIT",
                "remedy": "human_review",
                "message": "节点步数或执行时限已用尽，已完成节点保留",
            },
        )
        return None
    started = time.monotonic()

    def checked():
        guard()
        if time.monotonic() - started >= remaining:
            raise ModelError("节点执行时限已用尽")

    def record(value):
        if value.get("status") == "requesting":
            identities = loop.setdefault("requestIds", [])
            if value["requestId"] not in identities:
                if loop["modelCalls"] >= contract["maxModelCalls"]:
                    from .model_requests import ModelCallBudgetExceeded

                    raise ModelCallBudgetExceeded(
                        "节点模型调用额度已用尽",
                        scope="node",
                        used=loop["modelCalls"],
                        limit=contract["maxModelCalls"],
                    )
                identities.append(value["requestId"])
                loop["modelCalls"] += 1
        callbacks["on_record"](value)

    try:
        if not loop.get("pending"):
            if (
                not binding(workflow).get("agentEnabled", True)
                or loop["modelCalls"] >= contract["maxModelCalls"]
            ):
                wait_recovery(
                    workflow,
                    node,
                    item,
                    loop.get(
                        "failure",
                        {
                            "code": "NODE_CALL_LIMIT",
                            "remedy": "human_review",
                            "message": "智能体未启用或节点模型调用额度已用尽",
                        },
                    ),
                )
                return None
            rows = [
                *evidence,
                *(
                    [
                        {
                            "id": "node-config-" + node["id"],
                            "kind": "plan",
                            "title": "当前节点的既有配置",
                            "summary": "默认版本、参数及输入绑定的只读配置引用；当前短预览见nodeDefaults，完整值按需读取。",
                        }
                    ]
                    if node.get("kind") == "operator"
                    else []
                ),
                *[
                    {
                        "id": row["id"],
                        "kind": row["kind"],
                        "title": row["title"],
                        "summary": "本节点工具证据，可按编号读取",
                    }
                    for row in loop["evidence"].values()
                ],
            ]
            response = requester(
                workflow,
                node,
                rows,
                contract,
                {
                    "step": loop["steps"] + 1,
                    "history": loop["history"],
                    "observation": loop.get("lastObservation"),
                    "failure": loop.get("failure"),
                    "visibleInputs": visible_inputs(workflow, node, loop),
                    "userAnswer": loop.get("userAnswer", ""),
                    "jsonFallback": loop.get("jsonFallback", False),
                    "formatFeedback": loop.get("formatFeedback", ""),
                    "revisionFeedback": item.get("feedback"),
                    "manualRecovery": bool(loop.get("manualRecovery")),
                    **(
                        {"nodeDefaults": node_defaults(workflow, node, loop)}
                        if node.get("kind") == "operator"
                        else {}
                    ),
                    "remaining": {
                        "steps": contract["maxSteps"] - loop["steps"],
                        "modelCalls": contract["maxModelCalls"] - loop["modelCalls"],
                        "operatorCalls": contract["maxOperatorCalls"]
                        - loop["operatorCalls"],
                    },
                },
                guard=checked,
                policy={
                    **policy,
                    "maxRunSeconds": max(
                        1, min(policy["maxRunSeconds"], int(remaining))
                    ),
                },
                on_record=record,
                on_progress=callbacks.get("on_progress"),
                on_thinking=callbacks.get("on_thinking"),
            )
            loop.pop("formatRetries", None)
            loop.pop("formatFeedback", None)
            loop["steps"] += 1
            loop["pending"] = {
                key: deepcopy(response[key]) for key in ("action", "arguments")
            }
            loop["lastAudit"] = response.get("audit", {})
            persist(workflow)
        action, arguments = loop["pending"]["action"], loop["pending"]["arguments"]
        if action not in contract["tools"]:
            raise ComputeError("该工具未在当前节点合同中授权")
        from . import logic_nodes

        if (
            logic_nodes.enabled(workflow)
            and action == "finish_node"
            and not loop.get("successfulTaskId")
        ):
            raise ComputeError("尚无真实成功算子结果，不能交付专业节点")
        result = execute_tool(
            workflow,
            user,
            policy,
            node,
            item,
            action,
            arguments,
            evidence,
            contract,
            checked,
        )
        if result is None:
            return None
        store_result(workflow, node, item, action, result, arguments=arguments)
        return result if action == "finish_node" else None
    except InputsPending:
        return None
    except ActionFormatError as error:
        if loop.get("formatRetries", 0) >= 1:
            wait_recovery(workflow, node, item, observation(error))
        else:
            loop["formatRetries"] = loop.get("formatRetries", 0) + 1
            loop["formatFeedback"] = str(error)
            emit(
                workflow,
                "executor",
                node["id"],
                "action_format_retry",
                "模型动作格式不符，将进行一次有界修正",
            )
        return None
    except (ComputeError, ValidationError) as error:
        failure = observation(error)
        if loop.get("pending"):
            action = loop["pending"]["action"]
            arguments = loop["pending"]["arguments"]
            if action in {
                "run_operator",
                "preflight_operator",
                "prepare_input",
            } and not isinstance(error, RemedyRejected):
                failure["versionId"] = arguments.get("versionId")
                loop["failure"] = failure
                loop.setdefault("lastSubmission", deepcopy(arguments))
            store_result(
                workflow,
                node,
                item,
                action,
                {"failure": failure, "message": str(error)[:1000]},
                arguments=arguments,
            )
            if failure.get("remedy") in NO_RETRY or failure["code"].startswith(
                "PLATFORM_"
            ):
                wait_recovery(workflow, node, item, failure)
        else:
            wait_recovery(workflow, node, item, failure)
        return None
    except ModelError as error:
        from apps.agent.config import registry

        if (
            registry()[workflow.model].native_tools
            and not loop.get("jsonFallback")
            and "时限" not in str(error)
        ):
            loop["jsonFallback"] = True
            emit(
                workflow,
                "executor",
                node["id"],
                "tool_protocol_fallback",
                "原生工具协议不稳定，改用受约束JSON动作；额度不重置",
            )
        else:
            wait_recovery(workflow, node, item, observation(error))
        return None
    finally:
        loop["elapsedSeconds"] += time.monotonic() - started
        persist(workflow)
