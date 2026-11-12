"""专业科学骨架上的节点工具执行；科研批准仍由原服务保存。"""

from copy import deepcopy

from apps.compute.packages import ComputeError
from .state import binding, state, persist, emit, digest

# Configuration: preserve the approved scientific recipe and bound each actor.
EXECUTION_MODE = "geology_node_tools_v1"
TOOLS = [
    "operator_catalog",
    "read_evidence",
    "preflight_operator",
    "run_operator",
    "ask_user",
    "finish_node",
]


def enabled(workflow):
    return (
        workflow.workflow_type == "geology_generic"
        and workflow.parameters.get("_businessFlow", {}).get("nodeExecution")
        == EXECUTION_MODE
    )


def current_stage(workflow, node_id):
    stage = workflow.plan["stages"][workflow.plan["stageIndex"]]
    if stage["name"] != node_id or stage["identifier"] == "finish":
        raise ComputeError("工具动作不属于当前专业计算阶段")
    return stage


def stage_inputs(workflow, user, policy, stage):
    from apps.agent.demo_workflow import _inputs
    from apps.agent.geology_multi_review import create_approved_changes

    if stage["name"] == "apply":
        if not stage.get("modificationsApproval"):
            raise ComputeError("处置范围尚未获批，不能调用修正算子")
        if not workflow.plan.get("approved_changes"):
            workflow.plan["approved_changes"] = create_approved_changes(
                workflow, user, policy, stage
            ).pk
            persist(workflow)
    return _inputs(workflow, stage)


def node_definition(workflow, stage):
    node = deepcopy(
        next(
            row
            for row in binding(workflow)["definitionSnapshot"]["nodes"]
            if row["id"] == stage["name"]
        )
    )
    fixed = workflow.plan["algorithms"][stage["identifier"]]
    node.update(
        kind="agent",
        algorithmVersionId=fixed["versionId"],
        parameters=deepcopy(stage["parameters"]),
        instruction=(
            "查询本节点已登记算子后选择版本，按approved-inputs绑定输入并填写参数；必须先预检相同方案再运行。"
            "科学配方、输入来源与批准处置范围已冻结；不能为减少报错改变阈值、网格、规则或对象范围。"
            "失败依据code/remedy/gaps修正字段映射；涉及科学配方或更换资料须ask_user，不能自行批准。"
            "真实计算成功后读取statistics证据，再finish_node交付；质量复核仍由原专业服务执行。"
        ),
        contract={
            "goal": node["title"],
            "acceptance": [
                "已查询登记版本并按冻结科学配方预检",
                "真实计算成功且已读取统计，未代替科研批准",
            ],
            "requiredOutputs": [{"name": "result", "semanticType": "operator_result"}],
            "tools": TOOLS,
            "maxSteps": 24,
            "maxModelCalls": 12,
            "maxOperatorCalls": 3,
            "maxRecoveries": 3,
            "maxSeconds": 600,
        },
    )
    return node


def visible_inputs(workflow, node):
    return deepcopy(
        state(workflow)["nodes"][node["id"]]["toolLoop"].get("approvedInputs", {})
    )


def check_submission(workflow, node, version, body):
    stage = current_stage(workflow, node["id"])
    fixed = workflow.plan["algorithms"][stage["identifier"]]
    if version.pk != fixed["versionId"] or version.checksum != fixed["checksum"]:
        raise ComputeError("该版本不属于已确认科学配方，请重新确认计划后更换版本")
    if version.manifest.get("schemaVersion") != 2:
        raise ComputeError("该地质算子仍为旧清单，请先登记并验证第2版语义清单")
    if body["inputs"] != visible_inputs(workflow, node):
        raise ComputeError("输入须逐端口绑定已确认资料及真实上游成果，不能替换科研范围")
    if body["parameters"] != stage["parameters"]:
        raise ComputeError("科学参数与已确认配方不一致，请保留原值或请求用户重新确认")
    # Canonical fields were confirmed before working copies were created. A
    # semantic mapping may restate them, but cannot silently swap their meaning.
    specs = {row["key"]: row for row in version.manifest["inputs"]}
    for port, mapping in body["fieldMappings"].items():
        roles = {row["role"]: row for row in specs.get(port, {}).get("fields", [])}
        if any(
            role not in roles or value != roles[role].get("legacyName", role)
            for role, value in mapping.items()
        ):
            raise ComputeError("字段映射与已确认的规范字段不一致，请回资料确认阶段处理")


def submission_digest(body):
    return digest(
        {
            key: body[key]
            for key in ("versionId", "inputs", "parameters", "fieldMappings")
        }
    )


def revalidate_inputs(workflow, user, policy, node, body):
    """Recheck the original approval receipt at the actual write boundary."""
    from apps.agent.demo_workflow import _inputs
    from apps.agent.geology_multi_review import create_approved_changes

    stage = current_stage(workflow, node["id"])
    if stage["name"] == "apply":
        resource = create_approved_changes(workflow, user, policy, stage)
        if workflow.plan.get("approved_changes") != resource.pk:
            raise ComputeError("获批处置输入已变化，不能沿用先前预检")
    if body["inputs"] != _inputs(workflow, stage):
        raise ComputeError("实际输入与当前专业科学方案不一致，不能提交计算")


def catalog_rows(workflow, user, policy, node, arguments):
    from apps.compute.models import AlgorithmVersion
    from apps.compute.services import allowed_algorithms, agent_algorithm_allowed
    from apps.compute.operator_catalog import compact_description
    from .node_contracts import MAX_EVIDENCE_BYTES

    stage = current_stage(workflow, node["id"])
    fixed = workflow.plan["algorithms"][stage["identifier"]]
    version = (
        AlgorithmVersion.objects.select_related("algorithm")
        .filter(
            pk=fixed["versionId"],
            status="published",
            algorithm__enabled=True,
            algorithm__in=allowed_algorithms(),
        )
        .first()
    )
    if (
        not policy.get("operatorEnabled")
        or not version
        or not agent_algorithm_allowed(version)
        or version.checksum != fixed["checksum"]
    ):
        raise ComputeError("本节点登记算子不可用或权限已变化")
    identity = arguments.get("versionId")
    if identity is not None and (type(identity) is not int or identity != version.pk):
        raise ComputeError("只能查询本节点已确认的算子版本")
    description = compact_description(version, MAX_EVIDENCE_BYTES - 1024)
    if description["truncated"]:
        raise ComputeError("登记算子语义清单超过节点可读范围，请补齐可调用清单")
    return [description]


def completed_task(workflow, user, policy, node, item, loop):
    from apps.agent.compute_tools import authorized_task
    from apps.agent.demo_results import read_results

    task = authorized_task(user, loop["taskId"], policy, workflow=workflow)
    if task.status in {"queued", "validating", "running", "cancelling"}:
        workflow.status = "waiting_compute"
        return None
    if task.status != "succeeded":
        failure = {
            **(task.failure or {}),
            "message": (task.error or task.status)[:1000],
            "versionId": task.version_id,
            "taskId": str(task.pk),
        }
        failure.setdefault("code", "OPERATOR_FAILED")
        failure.setdefault("remedy", "human_review")
        loop["failure"] = failure
        state(workflow).setdefault("recoveredFailures", {})[str(task.pk)] = node["id"]
        return {"failure": failure, "message": failure["message"]}
    stage = current_stage(workflow, node["id"])
    # Reuse the complete, checksum-bound scientific read later used by approval
    # and collection. The model receives full statistics rather than issue samples.
    if not stage.get("results") or any(
        row.get("taskId") != str(task.pk) for row in stage["results"]
    ):
        stage["results"] = read_results(workflow, user, policy, task)
    results = stage["results"]
    statistics = [row for row in results if row["key"] == "statistics"]
    if not statistics:
        raise ComputeError("真实算子缺少必需statistics成果，不能交付节点")
    rows = []
    for result in statistics:
        identity = f"output-{result['outputId']}"
        row = {
            "id": identity,
            "kind": "output",
            "title": node["title"] + "完整统计",
            "result": deepcopy(result),
        }
        loop["evidence"][identity] = row
        rows.append(row)
    item["outputs"] = {"taskId": str(task.pk), "evidence": rows}
    loop["successfulTaskId"] = str(task.pk)
    loop.pop("failure", None)
    return {
        "status": "succeeded",
        "taskId": str(task.pk),
        "outputs": rows,
        "message": "真实计算已完成，完整统计已读取；质量与处置批准仍按原流程核对",
    }


def advance(workflow, user, policy, stage):
    from .engine import _callbacks, live_guard
    from .node_loop import advance_loop, loop_state
    from apps.agent.demo_workflow import _collect_stage, _save
    from apps.agent.compute_tools import authorized_task

    node = node_definition(workflow, stage)
    item = state(workflow)["nodes"][node["id"]]
    loop = loop_state(item)
    if not loop.get("approvedInputs"):
        loop["approvedInputs"] = stage_inputs(workflow, user, policy, stage)
    if not loop.get("finished"):
        workflow.status = "running"
        item["status"] = "executing"
        _save(workflow)
        evidence = [
            {
                "id": "approved-inputs",
                "kind": "analysis",
                "title": "已确认的科学配方与输入来源",
                "result": {
                    "inputs": loop["approvedInputs"],
                    "parameters": stage["parameters"],
                    "identifier": stage["identifier"],
                    "versionId": node["algorithmVersionId"],
                    "approvalRecorded": bool(stage.get("modificationsApproval")),
                    "scope": "版本与科学参数沿用已确认配方；查询目录后按实际清单填写，不得扩大处置范围",
                },
            }
        ]
        result = advance_loop(
            workflow,
            user,
            policy,
            node,
            item,
            evidence,
            guard=live_guard(workflow),
            callbacks=_callbacks(workflow, node, "executor"),
        )
        if result is None:
            if workflow.status == "running":
                workflow.status = "queued"
            _save(workflow)
            return
        if not loop.get("successfulTaskId"):
            raise ComputeError("节点没有真实成功计算，不能结束")
        loop["finished"] = True
        item["executor"].update(status="succeeded", model=workflow.model, **result)
        stage.update(
            taskId=loop["successfulTaskId"],
            inputs=deepcopy(loop["approvedInputs"]),
            executionMode="agent_tools",
        )
        stage["modelDispatchRecorded"] = bool(
            loop.get("lastAudit", {}).get("requested")
        ) and not loop.get("lastAudit", {}).get(
            "modelId", "mock"
        ).casefold().startswith("mock")
        stage["status"] = "waiting_compute"
        workflow.status = "waiting_compute"
        workflow.plan["phase"] = "waiting_compute"
        emit(workflow, "executor", node["id"], "node_delivered", result["summary"])
    task = authorized_task(user, stage["taskId"], policy, workflow=workflow)
    _collect_stage(workflow, user, policy, stage, task)
