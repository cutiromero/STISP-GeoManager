"""桩模型驱动真实业务流、算子准入与资料衔接队列。"""

from copy import deepcopy
import json
import sqlite3
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
import pytest

from apps.agent import provider
from apps.agent.models import AgentPolicy
from apps.agent.policy import default_policy
from apps.business_flows import catalog, engine, runtime
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.node_contracts import normalize_contract, TOOLS, LIMITS
from apps.business_flows.node_loop import loop_state, execute_tool, check_remedy
from apps.business_flows.state import state
from apps.catalog.models import DataResource
from apps.compute.models import ComputeTask
from apps.compute.packages import ComputeError
from apps.core.storage import table_data_path
from apps.projects.context import project_scope
from tests.integration.test_compute import setup_compute
from tests.integration.test_business_flow_operator_runtime import operators, finish_task
from tests.integration.test_input_script_preparation_runtime import (
    scripts,
    finish as finish_bridge,
)

__all__ = ["setup_compute", "operators", "scripts"]

pytestmark = pytest.mark.efficiency


def contract(**changes):
    return normalize_contract(
        {
            "goal": "选择统计算子并读取真实结果",
            "acceptance": ["读取真实成功结果"],
            "requiredOutputs": [
                {"name": "statistics", "semanticType": "operator_result"}
            ],
            "tools": sorted(TOOLS),
            "maxSteps": 12,
            "maxModelCalls": 12,
            **changes,
        }
    )


def upgrade(env, *, collection=False):
    version = env["version"]
    manifest = deepcopy(version.manifest)
    manifest.update(
        schemaVersion=2,
        capabilities={
            "summary": "表格统计",
            "operations": ["statistics"],
            "dataTypes": ["table"],
        },
    )
    for parameter in manifest["parameters"]:
        parameter["agent"] = {"adjustable": True, "advice": "依据资料实际字段调整"}
        if parameter["key"] in {"group", "value"}:
            parameter["default"] = "region" if parameter["key"] == "group" else "value"
    manifest["parameters"].append(
        {
            "key": "threshold",
            "label": "覆盖阈值",
            "type": "number",
            "required": False,
            "default": 0.5,
            "min": 0,
            "max": 1,
            "agent": {"adjustable": True},
        }
    )
    manifest["inputs"][0].update(
        fields=[
            {
                "role": "group_name",
                "description": "分组名称",
                "types": ["string"],
                "required": True,
                "parameter": "group",
            },
            {
                "role": "value",
                "description": "待统计值",
                "types": ["number"],
                "required": True,
                "parameter": "value",
            },
        ],
        crs={"mode": "any"},
    )
    if collection:
        manifest["inputs"].append(
            {
                "key": "minerals",
                "kind": "table",
                "label": "矿物类别",
                "required": False,
                "repeat": {"min": 0, "max": 20, "labelRequired": True},
                "fields": [],
                "crs": {"mode": "any"},
            }
        )
    version.manifest = manifest
    version.save(update_fields=["manifest"])


def create(
    env,
    *,
    node_contract=None,
    agent=True,
    multiple=False,
    human=False,
    allow_skip=False,
    prefix=False,
    ai=False,
    consumer=False,
):
    definition = source_summary_definition()
    definition["inputRequirements"][0]["multiple"] = multiple
    definition["inputPreparation"] = {"allowScripts": True, "reviewScripts": True}
    definition["nodes"][0].update(
        id="calculate",
        title="自适应统计",
        contract=node_contract or contract(),
        allowSkip=allow_skip,
        review={"ai": ai, "human": human, "maxRevisions": 1 if ai else 0},
    )
    definition["nodes"][1]["dependsOn"] = ["calculate"]
    if consumer:
        definition["nodes"][1] = {
            "id": "finish",
            "kind": "operator",
            "title": "消费具名合同成果",
            "description": "只使用已交付的真实输出",
            "dataRoles": [],
            "dependsOn": ["calculate"],
            "algorithmVersionId": env["version"].pk,
            "parameters": env["body"]["parameters"],
            "inputBindings": {
                "table": {"nodeId": "calculate", "outputKey": "statistics"}
            },
            "review": {"ai": False, "human": False, "maxRevisions": 0},
        }
    if prefix:
        definition["nodes"][0]["dependsOn"] = ["baseline"]
        definition["nodes"].insert(
            0,
            {
                "id": "baseline",
                "title": "前置规范",
                "description": "已核对前置流程规范",
                "kind": "result",
                "dependsOn": [],
                "dataRoles": [],
                "review": {"ai": False, "human": False, "maxRevisions": 0},
            },
        )
    with project_scope(env["scope"]):
        _, version = catalog.register_flow(
            env["admin"],
            {
                "code": "tools-" + uuid4().hex[:8],
                "name": "自适应节点",
                "definition": definition,
            },
        )
        workflow = runtime.start_flow(
            env["owner"],
            version,
            {
                "model": "mock",
                "inputs": {"source": env["resource"].pk},
                "agentEnabled": agent,
                "idempotencyKey": uuid4().hex,
            },
        )
    return workflow


def install(monkeypatch, answers):
    calls = []
    monkeypatch.setattr(provider, "model_window", lambda model: 32768)
    monkeypatch.setattr(provider, "count_tokens", lambda *args, **kwargs: 1000)

    def stream(model, messages, maximum, guard, **options):
        guard()
        packet = json.loads(messages[1]["content"])
        calls.append({"packet": packet, "options": options})
        answer = answers.pop(0)
        if callable(answer):
            answer = answer(packet)
        options["on_usage"]({"prompt_tokens": 1000, "completion_tokens": 50})
        yield (
            json.dumps(answer, ensure_ascii=False)
            if not isinstance(answer, str)
            else answer
        )

    monkeypatch.setattr(provider, "stream", stream)
    return calls


def action(name, **arguments):
    return {"action": name, "arguments": arguments}


def submit_args(env, **changes):
    return {
        "versionId": env["version"].pk,
        "inputs": {"table": env["resource"].pk},
        "parameters": {},
        **changes,
    }


def finish_action(packet):
    output = next(
        row["id"] for row in packet["evidence"] if row["id"].startswith("output-")
    )
    return action(
        "finish_node",
        summary="已读取真实统计结果",
        outputs=[
            {
                "name": "statistics",
                "semanticType": "operator_result",
                "evidenceId": output,
            }
        ],
        evidenceIds=[output],
        limitations=[],
        acceptanceChecks=["读取真实成功结果"],
    )


def advance(env, workflow, count=1):
    for _ in range(count):
        engine.advance(workflow.pk)
        workflow.refresh_from_db()
        assert workflow.status != "failed", (
            workflow.detail,
            state(workflow)["nodes"]["calculate"],
        )
    return state(workflow)["nodes"]["calculate"]


def finish_flow(env, workflow):
    advance(env, workflow, 3)
    assert workflow.status == "succeeded", workflow.detail


def test_node_elapsed_budget_does_not_reuse_single_request_timeout(
    operators, monkeypatch
):
    env = operators
    upgrade(env)
    workflow = create(env)
    loop = loop_state(state(workflow)["nodes"]["calculate"])
    loop["elapsedSeconds"] = default_policy()["maxRunSeconds"] + 1
    workflow.save(update_fields=["plan"])
    calls = install(monkeypatch, [action("operator_catalog", operation="statistics")])
    item = advance(env, workflow)
    assert len(calls) == 1 and item["status"] != "waiting_recovery"


def test_last_allowed_recovery_still_collects_its_successful_result(
    operators, monkeypatch
):
    env = operators
    upgrade(env)
    workflow = create(env, node_contract=contract(maxRecoveries=1))
    arguments = submit_args(env)
    install(
        monkeypatch,
        [
            action("operator_catalog", operation="statistics"),
            action("run_operator", **arguments),
            action(
                "run_operator",
                **submit_args(
                    env,
                    parameters={"threshold": 0.6},
                    remedy="adjust_parameters",
                ),
            ),
            finish_action,
        ],
    )
    item = advance(env, workflow, 2)
    with project_scope(env["scope"]):
        ComputeTask.objects.filter(pk=item["computeTaskId"]).update(
            status="failed",
            error="需要调整参数",
            failure={"code": "BOUNDS", "remedy": "adjust_parameters"},
        )
    item = advance(env, workflow, 2)
    assert item["toolLoop"]["recoveries"] == 1
    finish_task(env, item["computeTaskId"], "RECOVERED")
    item = advance(env, workflow)
    assert not item.get("recovery")
    advance(env, workflow)
    finish_flow(env, workflow)


def test_format_repair_is_available_again_after_a_valid_action(operators, monkeypatch):
    env = operators
    workflow = create(env)
    calls = install(
        monkeypatch,
        [
            "bad-json",
            action("operator_catalog", operation="statistics"),
            "another-bad-json",
            action("ask_user", question="请确认资料用途"),
        ],
    )
    item = advance(env, workflow, 4)
    assert len(calls) == 4
    assert item["recovery"]["question"] == "请确认资料用途"


def test_different_field_names_recovered_by_semantic_mapping(operators, monkeypatch):
    env = operators
    upgrade(env)
    with project_scope(env["scope"]):
        with sqlite3.connect(table_data_path("data.sqlite")) as connection:
            connection.execute("ALTER TABLE samples RENAME COLUMN region TO district")
            connection.execute("ALTER TABLE samples RENAME COLUMN value TO measured")
    workflow = create(env)
    arguments = submit_args(env)
    repaired = {
        **arguments,
        "fieldMappings": {"table": {"group_name": "district", "value": "measured"}},
        "remedy": "complete_mapping",
    }
    calls = install(
        monkeypatch,
        [
            action("operator_catalog", operation="statistics"),
            action("preflight_operator", **arguments),
            action("run_operator", **repaired),
            finish_action,
        ],
    )
    item = advance(env, workflow, 3)
    task_id = item["computeTaskId"]
    with project_scope(env["scope"]):
        task = ComputeTask.objects.get(pk=task_id)
        assert task.field_mappings["table"]["group_name"] == "district"
        assert task.parameters["value"] == "measured"
    finish_task(env, task_id, "MAPPED")
    advance(env, workflow)
    finish_flow(env, workflow)
    assert (
        calls[2]["packet"]["nodeContext"]["failure"]["gaps"][0]["remedy"]
        == "complete_mapping"
    )


def test_extra_mineral_uses_open_named_collection(operators, monkeypatch):
    env = operators
    upgrade(env, collection=True)
    workflow = create(env, multiple=True)
    arguments = submit_args(
        env,
        inputs={
            "table": env["resource"].pk,
            "minerals": [
                {"resourceId": env["resource"].pk, "label": label}
                for label in ["赤铁矿", "绿泥石", "新增高岭石"]
            ],
        },
    )
    install(
        monkeypatch,
        [
            action("operator_catalog"),
            action("run_operator", **arguments),
            finish_action,
        ],
    )
    item = advance(env, workflow, 2)
    assert item.get("computeTaskId"), json.dumps(item, ensure_ascii=False)
    with project_scope(env["scope"]):
        task = ComputeTask.objects.get(pk=item["computeTaskId"])
        assert [row["label"] for row in task.input_collections["minerals"]][
            -1
        ] == "新增高岭石"
    finish_task(env, item["computeTaskId"], "OPEN")
    advance(env, workflow)
    finish_flow(env, workflow)


def test_out_of_range_failure_changes_declared_parameter(operators, monkeypatch):
    env = operators
    upgrade(env)
    workflow = create(env)
    install(
        monkeypatch,
        [
            action("operator_catalog"),
            action("run_operator", **submit_args(env, parameters={"threshold": 99})),
            action(
                "run_operator",
                **submit_args(
                    env, parameters={"threshold": 0.25}, remedy="adjust_parameters"
                ),
            ),
            finish_action,
        ],
    )
    item = advance(env, workflow, 2)
    assert not item.get("computeTaskId") and item["toolLoop"]["failure"]
    item = advance(env, workflow)
    with project_scope(env["scope"]):
        assert (
            ComputeTask.objects.get(pk=item["computeTaskId"]).parameters["threshold"]
            == 0.25
        )
    finish_task(env, item["computeTaskId"], "PARAMETER")
    advance(env, workflow)
    finish_flow(env, workflow)


def test_unrecoverable_wait_and_replacement_resume_same_node(operators, monkeypatch):
    env = operators
    upgrade(env)
    workflow = create(env, prefix=True)
    answers = [
        action("operator_catalog"),
        action("run_operator", **submit_args(env)),
        lambda packet: action(
            "run_operator",
            **submit_args(
                env, inputs={"table": packet["nodeContext"]["visibleInputs"]["source"]}
            ),
        ),
        finish_action,
    ]
    install(monkeypatch, answers)
    advance(env, workflow)
    assert state(workflow)["nodes"]["baseline"]["status"] == "succeeded"
    item = advance(env, workflow, 2)
    with project_scope(env["scope"]):
        task = ComputeTask.objects.get(pk=item["computeTaskId"])
        task.status, task.error, task.failure = (
            "failed",
            "资料内容不适用",
            {"code": "UNSUITABLE_DATA", "remedy": "unrecoverable"},
        )
        task.save()
    item = advance(env, workflow)
    assert (
        workflow.status == "waiting_approval" and item["status"] == "waiting_recovery"
    )
    with project_scope(env["scope"]):
        replacement = DataResource.objects.create(
            name="更换数据",
            code="replacement",
            data_type="table",
            file_format="SQLITE",
            storage_path="samples",
            item_count=3,
        )
        before = deepcopy(state(workflow)["nodes"]["baseline"])
        payload = {
            "nodeId": "calculate",
            "revision": state(workflow)["revision"],
            "decision": "retry_recovery",
            "feedback": "换用已核实数据",
            "recoveryInputs": {"source": replacement.pk},
            "idempotencyKey": uuid4().hex,
        }
        workflow = runtime.decide_flow(env["owner"], workflow, payload)
        assert runtime.decide_flow(env["owner"], workflow, payload).pk == workflow.pk
        assert state(workflow)["nodes"]["baseline"] == before
    item = advance(env, workflow)
    finish_task(env, item["computeTaskId"], "REPLACED")
    advance(env, workflow)
    finish_flow(env, workflow)


def test_text_format_requests_existing_script_and_review(scripts, monkeypatch):
    env = scripts
    monkeypatch.setattr(
        "tests.integration.test_input_script_preparation_runtime.CODE",
        'import pandas as pd\ndef run(context):\n    data = pd.read_csv(context.input_path("source_document_1"),sep=";")\n    data.to_csv(context.output_path("prepared.csv"),index=False)\n',
    )
    with project_scope(env["scope"]):
        runtime.control_flow(env["owner"], env["workflow"], "cancel")
        path = table_data_path("foreign-format.txt")
        path.write_text("region;converted_value\nA;2\nB;8\n")
        env["resource"] = DataResource.objects.create(
            name="分号文本",
            code="foreign-text",
            data_type="document",
            file_format="TXT",
            storage_path="foreign-format.txt",
            item_count=2,
        )
    upgrade(env)
    manifest = env["version"].manifest
    next(row for row in manifest["parameters"] if row["key"] == "value")["default"] = (
        "converted_value"
    )
    manifest["inputs"][0]["fields"][1]["types"] = ["number", "string"]
    env["version"].save(update_fields=["manifest"])
    workflow = create(env)
    env["workflow"] = workflow
    reviewed = []

    def review(*args, **kwargs):
        reviewed.append(True)
        return {
            "decision": "accept",
            "reason": "只转换格式并保留数值",
            "issues": [],
            "repairInstructions": "",
            "evidenceIds": [row["id"] for row in args[3]],
        }

    monkeypatch.setattr("apps.agent.input_script_model.review", review)
    install(
        monkeypatch,
        [
            action("operator_catalog", operation="statistics"),
            action("preflight_operator", **submit_args(env)),
            action("prepare_input", **submit_args(env, remedy="convert_input")),
            lambda packet: action(
                "run_operator",
                **submit_args(
                    env,
                    inputs={
                        "table": packet["nodeContext"]["observation"]["result"][
                            "inputs"
                        ]["table"]
                    },
                ),
            ),
            finish_action,
        ],
    )
    advance(env, workflow, 3)
    advance(env, workflow)
    assert workflow.status == "waiting_compute", workflow.detail
    output = finish_bridge(env)
    advance(env, workflow)
    from apps.compute.models import ComputeImport
    from apps.compute.worker import process_import, task_scope

    with project_scope(env["scope"]):
        record = ComputeImport.objects.get(output=output)
        with task_scope(output.task):
            process_import(record)
    item = advance(env, workflow, 2)
    assert reviewed and env["calls"], "必须复用现有脚本生成及独立审核"
    assert item.get("computeTaskId"), item.get("toolLoop", {}).get("lastObservation")
    finish_task(env, item["computeTaskId"], "CONVERTED")
    advance(env, workflow)
    finish_flow(env, workflow)


@pytest.mark.parametrize(
    "changes",
    [
        *[{key: limits[1] + 1} for key, limits in LIMITS.items()],
        {"tools": ["shell"]},
        {"requiredOutputs": []},
        {"acceptance": []},
        {"unexpected": True},
    ],
)
def test_contract_rejects_unbounded_or_unknown_fields(changes):
    with pytest.raises(ValidationError):
        contract(**changes)


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("read_evidence", {"evidenceId": "other-node"}),
        ("read_evidence", {"evidenceId": "visible", "length": 4097}),
        ("operator_catalog", {"limit": 21}),
        ("preflight_operator", {"versionId": -1}),
        ("run_operator", {"versionId": -1}),
        ("prepare_input", {"versionId": -1}),
        ("ask_user", {"question": ""}),
        ("finish_node", {"summary": "伪造成功", "outputs": []}),
    ],
)
def test_each_tool_enforces_scope_or_limit(operators, tool, arguments):
    env = operators
    workflow = create(env)
    item = state(workflow)["nodes"]["calculate"]
    node = workflow.parameters["_businessFlow"]["definitionSnapshot"]["nodes"][0]
    with project_scope(env["scope"]), pytest.raises((ComputeError, PermissionDenied)):
        execute_tool(
            workflow,
            env["owner"],
            default_policy(),
            node,
            item,
            tool,
            arguments,
            [
                {
                    "id": "visible",
                    "kind": "analysis",
                    "title": "当前",
                    "result": {"value": 1},
                }
            ],
            node["contract"],
            lambda: None,
        )


@pytest.mark.parametrize(
    "limit", ["maxSteps", "maxModelCalls", "maxSeconds", "maxOperatorCalls"]
)
def test_loop_limits_wait_instead_of_failing(operators, monkeypatch, limit):
    env = operators
    upgrade(env)
    workflow = create(env)
    item = state(workflow)["nodes"]["calculate"]
    loop = loop_state(item)
    node = workflow.parameters["_businessFlow"]["definitionSnapshot"]["nodes"][0]
    if limit == "maxOperatorCalls":
        loop["operatorCalls"] = node["contract"][limit]
        loop["catalogIds"] = [env["version"].pk]
        install(
            monkeypatch,
            [
                action("run_operator", **submit_args(env)),
                action("ask_user", question="算子额度不足，请停止或调整任务"),
            ],
        )
    else:
        key = {
            "maxSteps": "steps",
            "maxModelCalls": "modelCalls",
            "maxSeconds": "elapsedSeconds",
        }[limit]
        loop[key] = node["contract"][limit]
        install(monkeypatch, [])
    workflow.save(update_fields=["plan"])
    item = advance(env, workflow, 2 if limit == "maxOperatorCalls" else 1)
    assert (
        workflow.status == "waiting_approval" and item["status"] == "waiting_recovery"
    )


def test_format_retry_once_and_whitelist(operators, monkeypatch):
    env = operators
    workflow = create(env)
    calls = install(monkeypatch, ["not json", "still not json"])
    item = advance(env, workflow, 2)
    assert len(calls) == 2 and item["status"] == "waiting_recovery"
    assert item["toolLoop"]["modelCalls"] == 2


def test_large_catalog_keeps_all_returned_versions_and_byte_ranges(operators):
    from apps.business_flows.node_loop import store_result, encoded

    env = operators
    workflow = create(env)
    node = workflow.parameters["_businessFlow"]["definitionSnapshot"]["nodes"][0]
    item = state(workflow)["nodes"]["calculate"]
    loop = loop_state(item)
    loop["steps"] = 1
    operators_result = [
        {
            "versionId": index,
            "name": "测试目录算子",
            "capabilities": {"operations": ["statistics"]},
            "description": "语义" * 400,
        }
        for index in range(1, 21)
    ]
    with project_scope(env["scope"]):
        store_result(
            workflow, node, item, "operator_catalog", {"operators": operators_result}
        )
        preview = loop["lastObservation"]["result"]
        assert len(preview["operators"]) == 20 and len(encoded(preview)) <= 8192
        selected = preview["operators"][-1]
        fragment = execute_tool(
            workflow,
            env["owner"],
            default_policy(),
            node,
            item,
            "read_evidence",
            {
                "evidenceId": preview["evidenceId"],
                "offset": selected["offset"],
                "length": selected["length"],
            },
            [],
            node["contract"],
            lambda: None,
        )
        assert json.loads(fragment["text"]) == operators_result[-1]


def test_recovery_does_not_repeat_same_error_remedy():
    loop = {
        "failure": {"code": "BOUNDS", "remedy": "adjust_parameters"},
        "lastSubmission": {"parameters": {"threshold": 99}},
        "recoveries": 0,
        "remedies": [],
    }
    arguments = {"parameters": {"threshold": 0.5}, "remedy": "adjust_parameters"}
    check_remedy(loop, arguments, "run_operator", contract())
    with pytest.raises(ComputeError, match="不得重复"):
        check_remedy(loop, arguments, "run_operator", contract())
    check_remedy(
        loop,
        {"parameters": {"threshold": 0.6}, "remedy": "adjust_parameters"},
        "run_operator",
        contract(),
    )
    assert loop["recoveries"] == 2


@pytest.mark.parametrize(
    "remedy,changes",
    [
        ("adjust_parameters", {"parameters": {}}),
        ("adjust_parameters", {"parameters": {"threshold": 0.5}}),
        ("adjust_parameters", {"parameters": []}),
        ("complete_mapping", {"fieldMappings": {}}),
        (
            "complete_mapping",
            {"fieldMappings": {"table": {"group_name": "region"}}},
        ),
        ("complete_mapping", {"inputs": {"table": 42}}),
    ],
)
def test_unchanged_effective_remedy_is_rejected_without_spending(remedy, changes):
    loop = {
        "failure": {"code": "BOUNDS", "remedy": remedy},
        "lastSubmission": {
            "parameters": {"threshold": 0.5, "group": "region"},
            "fieldMappings": {"table": {"group_name": "region", "value": "value"}},
            "inputs": {"table": 42},
        },
        "recoveries": 0,
        "remedies": [],
    }
    with pytest.raises(ComputeError):
        check_remedy(loop, {"remedy": remedy, **changes}, "run_operator", contract())
    assert loop["recoveries"] == 0 and loop["remedies"] == []


def test_mapping_cannot_modify_nonadjustable_linked_parameter(operators, monkeypatch):
    env = operators
    upgrade(env)
    next(row for row in env["version"].manifest["parameters"] if row["key"] == "group")[
        "agent"
    ]["adjustable"] = False
    env["version"].save(update_fields=["manifest"])
    workflow = create(env)
    calls = install(
        monkeypatch,
        [
            action("operator_catalog"),
            action(
                "run_operator",
                **submit_args(env, fieldMappings={"table": {"group_name": "value"}}),
            ),
            action("ask_user", question="请确认不可调字段参数"),
        ],
    )
    item = advance(env, workflow, 3)
    assert item["status"] == "waiting_recovery"
    assert (
        "agent.adjustable"
        in calls[2]["packet"]["nodeContext"]["observation"]["result"]["message"]
    )
    with project_scope(env["scope"]):
        assert not ComputeTask.objects.exists()


def test_professional_parameter_restatement_keeps_fixed_values_immutable(operators):
    from apps.business_flows import logic_nodes
    from apps.business_flows.node_loop import submission

    env = operators
    upgrade(env)
    version = env["version"]
    version.manifest["parameters"].append(
        {
            "key": "fixed_value",
            "label": "固定参数",
            "type": "string",
            "default": "original",
            "required": False,
            "agent": {"adjustable": False},
        }
    )
    version.save(update_fields=["manifest"])
    workflow = create(env)
    workflow.workflow_type = "geology_generic"
    workflow.parameters["_businessFlow"]["nodeExecution"] = logic_nodes.EXECUTION_MODE
    parameters = {
        row["key"]: row["default"]
        for row in version.manifest["parameters"]
        if "default" in row
    }
    parameters.update(env["body"]["parameters"])
    stage = {
        "name": "calculate",
        "identifier": version.algorithm.identifier,
        "parameters": parameters,
    }
    workflow.plan.update(
        stages=[stage],
        stageIndex=0,
        algorithms={
            version.algorithm.identifier: {
                "versionId": version.pk,
                "checksum": version.checksum,
            }
        },
    )
    workflow.save(update_fields=["workflow_type", "parameters", "plan"])
    node = logic_nodes.node_definition(workflow, stage)
    item = state(workflow)["nodes"]["calculate"]
    loop = loop_state(item)
    loop.update(catalogIds=[version.pk], approvedInputs={"table": env["resource"].pk})
    arguments = {
        "versionId": version.pk,
        "inputs": loop["approvedInputs"],
        "parameters": {"fixed_value": "original"},
    }
    with project_scope(env["scope"]):
        policy = {**default_policy(), "operatorEnabled": True}
        _, body = submission(workflow, env["owner"], policy, node, loop, arguments)
        assert body["parameters"]["fixed_value"] == "original"
        for value in ["changed", 1, None]:
            with pytest.raises(ComputeError, match="固定科学参数"):
                submission(
                    workflow,
                    env["owner"],
                    policy,
                    node,
                    loop,
                    {**arguments, "parameters": {"fixed_value": value}},
                )
    assert not ComputeTask.objects.exists()


def test_restart_pending_action_does_not_request_another_model(operators, monkeypatch):
    env = operators
    workflow = create(env)
    loop = loop_state(state(workflow)["nodes"]["calculate"])
    loop.update(
        steps=1,
        pending=action(
            "read_evidence", evidenceId="resource-" + str(env["resource"].pk), length=32
        ),
    )
    workflow.save(update_fields=["plan"])
    calls = install(monkeypatch, [])
    item = advance(env, workflow)
    assert not calls and item["toolLoop"]["history"][-1]["action"] == "read_evidence"


@pytest.mark.parametrize("control", ["pause", "cancel", "revoke"])
def test_pause_cancel_revocation_stop_next_tool(operators, monkeypatch, control):
    env = operators
    workflow = create(env)
    calls = install(
        monkeypatch,
        [action("read_evidence", evidenceId="resource-" + str(env["resource"].pk))],
    )
    advance(env, workflow)
    with project_scope(env["scope"]):
        if control == "revoke":
            policy = default_policy()
            policy["workflowEnabled"] = False
            AgentPolicy.objects.filter(pk=1).update(value=policy)
        else:
            workflow = runtime.control_flow(env["owner"], workflow, control)
    advance(env, workflow)
    assert len(calls) == 1 and workflow.status in {"paused", "cancelled", "interrupted"}


def test_context_budget_applies_on_every_loop_request(operators, monkeypatch):
    env = operators
    workflow = create(env)
    calls = install(
        monkeypatch,
        [action("read_evidence", evidenceId="resource-" + str(env["resource"].pk))],
    )
    advance(env, workflow)
    monkeypatch.setattr(provider, "count_tokens", lambda *args, **kwargs: 1000000)
    item = advance(env, workflow)
    assert len(calls) == 1 and item["status"] == "waiting_context"


def test_disabled_agent_failed_old_operator_waits_without_model(operators, monkeypatch):
    env = operators
    workflow = env["create"](ai=False)
    workflow.parameters["_businessFlow"]["agentEnabled"] = False
    workflow.save(update_fields=["parameters"])
    calls = install(monkeypatch, [])
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    with project_scope(env["scope"]):
        task = ComputeTask.objects.get(
            pk=state(workflow)["nodes"]["calculate"]["computeTaskId"]
        )
        task.status, task.error = "failed", "来源无效"
        task.save()
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    assert (
        workflow.status == "waiting_approval"
        and state(workflow)["nodes"]["calculate"]["status"] == "waiting_recovery"
        and not calls
    )


def test_native_mode_and_bounded_json_fallback(operators, monkeypatch, settings):
    env = operators
    settings.AGENT_MODELS[0]["native_tools"] = True
    workflow = create(env)
    calls = install(monkeypatch, [action("ask_user", question="请说明字段语义")])
    original = provider.stream
    attempts = []

    def stream(*args, **kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise provider.ModelError("原生工具协议不稳定")
        yield from original(*args, **kwargs)

    monkeypatch.setattr(provider, "stream", stream)
    item = advance(env, workflow, 2)
    assert attempts[0]["tools"] and "tools" not in attempts[1]
    assert item["status"] == "waiting_recovery" and item["toolLoop"]["modelCalls"] == 2
    assert len(calls) == 1


def test_pending_compute_restart_does_not_resubmit(operators, monkeypatch):
    env = operators
    upgrade(env)
    workflow = create(env)
    calls = install(
        monkeypatch,
        [action("operator_catalog"), action("run_operator", **submit_args(env))],
    )
    item = advance(env, workflow, 2)
    task_id = item["computeTaskId"]
    item = advance(env, workflow, 3)
    with project_scope(env["scope"]):
        assert ComputeTask.objects.count() == 1
    assert item["computeTaskId"] == task_id and len(calls) == 2


def test_unadjustable_parameter_and_out_of_scope_resource_are_observations(
    operators, monkeypatch
):
    env = operators
    upgrade(env)
    next(
        row for row in env["version"].manifest["parameters"] if row["key"] == "method"
    )["agent"]["adjustable"] = False
    env["version"].save(update_fields=["manifest"])
    workflow = create(env)
    calls = install(
        monkeypatch,
        [
            action("operator_catalog"),
            action("run_operator", **submit_args(env, parameters={"method": "sum"})),
            action("preflight_operator", **submit_args(env, inputs={"table": 999999})),
            action("ask_user", question="请更换当前节点资料"),
        ],
    )
    item = advance(env, workflow, 4)
    observations = [call["packet"]["nodeContext"].get("observation") for call in calls]
    assert "agent.adjustable" in observations[2]["result"]["message"]
    assert "不能扩大范围" in observations[3]["result"]["message"]
    assert item["status"] == "waiting_recovery"
    with project_scope(env["scope"]):
        assert not ComputeTask.objects.exists()


def test_user_skip_is_revision_bound_and_never_approves(operators, monkeypatch):
    env = operators
    workflow = create(env, allow_skip=True)
    install(monkeypatch, [action("ask_user", question="本节点无法确定，是否跳过？")])
    advance(env, workflow)
    payload = {
        "nodeId": "calculate",
        "decision": "skip_node",
        "feedback": "明确跳过",
        "revision": state(workflow)["revision"],
        "idempotencyKey": uuid4().hex,
    }
    with project_scope(env["scope"]):
        with pytest.raises(ComputeError):
            runtime.decide_flow(
                env["owner"], workflow, {**payload, "revision": payload["revision"] - 1}
            )
        workflow = runtime.decide_flow(env["owner"], workflow, payload)
    assert state(workflow)["nodes"]["calculate"]["status"] == "skipped"
    assert state(workflow)["nodes"]["calculate"]["human"]["status"] != "approved"
    advance(env, workflow, 2)
    assert workflow.status == "succeeded"


def test_human_gate_cannot_be_skipped_and_answer_does_not_approve(
    operators, monkeypatch
):
    env = operators
    workflow = create(env, allow_skip=True, human=True)
    install(monkeypatch, [action("ask_user", question="请说明单位")])
    item = advance(env, workflow)
    assert item["recovery"]["allowSkip"] is False
    payload = {
        "nodeId": "calculate",
        "decision": "skip_node",
        "feedback": "跳过",
        "revision": state(workflow)["revision"],
        "idempotencyKey": uuid4().hex,
    }
    with project_scope(env["scope"]), pytest.raises(ComputeError):
        runtime.decide_flow(env["owner"], workflow, payload)
    with project_scope(env["scope"]):
        workflow = runtime.decide_flow(
            env["owner"],
            workflow,
            {**payload, "decision": "retry_recovery", "feedback": "单位是米"},
        )
    assert state(workflow)["nodes"]["calculate"]["human"]["status"] == "pending"


def test_finish_missing_output_is_returned_to_model(operators, monkeypatch):
    env = operators
    workflow = create(env)
    calls = install(
        monkeypatch,
        [
            action(
                "finish_node",
                summary="已完成",
                outputs=[],
                evidenceIds=[],
                limitations=[],
                acceptanceChecks=["读取真实成功结果"],
            ),
            action("ask_user", question="还没有实际计算成果，需要补充数据"),
        ],
    )
    item = advance(env, workflow, 2)
    assert (
        "statistics"
        in calls[1]["packet"]["nodeContext"]["observation"]["result"]["message"]
    )
    assert item["status"] == "waiting_recovery"


@pytest.mark.parametrize(
    "remedy,code",
    [("unrecoverable", "BAD_DATA"), ("adjust_parameters", "PLATFORM_TIMEOUT")],
)
def test_nonretryable_failures_never_ask_model_again(
    operators, monkeypatch, remedy, code
):
    env = operators
    upgrade(env)
    workflow = create(env)
    calls = install(
        monkeypatch,
        [action("operator_catalog"), action("run_operator", **submit_args(env))],
    )
    item = advance(env, workflow, 2)
    with project_scope(env["scope"]):
        task = ComputeTask.objects.get(pk=item["computeTaskId"])
        task.status, task.failure = "failed", {"code": code, "remedy": remedy}
        task.save()
    item = advance(env, workflow, 2)
    assert item["status"] == "waiting_recovery" and len(calls) == 2


def test_catalog_replacement_requires_equivalent_capabilities(operators, monkeypatch):
    from apps.business_flows.node_loop import version_for
    from apps.compute.models import AlgorithmVersion

    env = operators
    upgrade(env)
    workflow = create(env)
    loop = loop_state(state(workflow)["nodes"]["calculate"])
    node = workflow.parameters["_businessFlow"]["definitionSnapshot"]["nodes"][0]
    loop["failure"] = {
        "code": "BAD_PARAMETERS",
        "remedy": "adjust_parameters",
        "versionId": env["version"].pk,
    }
    replacement = AlgorithmVersion.objects.create(
        algorithm=env["version"].algorithm,
        version="9.0.0",
        manifest=deepcopy(env["version"].manifest),
        package_path=env["version"].package_path,
        checksum=env["version"].checksum,
        runtime_digest=env["version"].runtime_digest,
        status="published",
    )
    loop["catalogIds"] = [replacement.pk]
    with project_scope(env["scope"]):
        assert (
            version_for(
                workflow,
                env["owner"],
                node,
                loop,
                replacement.pk,
                {**default_policy(), "operatorEnabled": True},
            ).pk
            == replacement.pk
        )
        replacement.manifest["capabilities"]["operations"] = ["map"]
        replacement.save(update_fields=["manifest"])
        with pytest.raises(ComputeError, match="等价"):
            version_for(
                workflow,
                env["owner"],
                node,
                loop,
                replacement.pk,
                {**default_policy(), "operatorEnabled": True},
            )


def test_contract_named_output_feeds_real_downstream_operator(operators, monkeypatch):
    from apps.compute.models import ComputeImport
    from apps.compute.quality import quality_metadata
    from apps.compute.worker import process_import, task_scope

    env = operators
    upgrade(env)
    env["version"].manifest["inputs"][0]["fields"][1]["types"] = ["number", "string"]
    env["version"].save(update_fields=["manifest"])
    workflow = create(env, consumer=True)
    install(
        monkeypatch,
        [
            action("operator_catalog"),
            action("run_operator", **submit_args(env)),
            finish_action,
        ],
    )
    item = advance(env, workflow, 2)
    output = finish_task(env, item["computeTaskId"], "UPSTREAM")
    output.metadata.update(
        quality_metadata(
            {
                "version": 1,
                "status": "passed",
                "summary": "实际表格成果",
                "metrics": {},
                "knowledgeFacts": {},
            }
        )
    )
    output.save(update_fields=["metadata"])
    advance(env, workflow, 3)
    with project_scope(env["scope"]):
        imported = ComputeImport.objects.get(output=output)
        with task_scope(output.task):
            process_import(imported)
    advance(env, workflow)
    consumer_task = state(workflow)["nodes"]["finish"]["computeTaskId"]
    assert consumer_task != item["computeTaskId"]
    finish_task(env, consumer_task, "CONSUMED")
    advance(env, workflow, 2)
    assert workflow.status == "succeeded", workflow.detail


def test_reviewer_receives_actual_tool_observation_not_only_success_claim(
    operators, monkeypatch
):
    env = operators
    upgrade(env)
    workflow = create(env, ai=True)
    seen = []

    def accepted(packet):
        observed = [
            row for row in packet["evidence"] if row.get("result", {}).get("outputs")
        ]
        assert (
            observed
            and observed[0]["result"]["outputs"][0]["result"]["checkedChecksum"]
        )
        seen.extend(observed)
        return {
            "decision": "accept",
            "reason": "已核对实际结果",
            "issues": [],
            "repairInstructions": "",
            "evidenceIds": [row["id"] for row in packet["evidence"]],
        }

    install(
        monkeypatch,
        [
            action("operator_catalog"),
            action("run_operator", **submit_args(env)),
            finish_action,
            accepted,
        ],
    )
    item = advance(env, workflow, 2)
    finish_task(env, item["computeTaskId"], "REVIEWED")
    advance(env, workflow)
    finish_flow(env, workflow)
    assert seen


def test_old_operator_user_replacement_does_not_reset_recovery_budgets(
    operators, monkeypatch
):
    env = operators
    workflow = env["create"](ai=False)
    workflow.parameters["_businessFlow"]["agentEnabled"] = False
    workflow.save(update_fields=["parameters"])
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    with project_scope(env["scope"]):
        task = ComputeTask.objects.get(
            pk=state(workflow)["nodes"]["calculate"]["computeTaskId"]
        )
        task.status, task.error = "failed", "数据不可用"
        task.save()
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    loop = state(workflow)["nodes"]["calculate"]["toolLoop"]
    assert loop["lastSubmission"]["parameters"] == task.parameters
    assert loop["lastSubmission"]["fieldMappings"] == task.field_mappings
    assert loop["lastSubmission"]["versionId"] == task.version_id
    loop.update(modelCalls=3, recoveries=2, elapsedSeconds=9)
    workflow.save(update_fields=["plan"])
    with project_scope(env["scope"]):
        workflow = runtime.decide_flow(
            env["owner"],
            workflow,
            {
                "nodeId": "calculate",
                "decision": "retry_recovery",
                "feedback": "已核实资料",
                "revision": state(workflow)["revision"],
                "idempotencyKey": uuid4().hex,
            },
        )
    saved = state(workflow)["nodes"]["calculate"]["toolLoop"]
    assert (saved["modelCalls"], saved["recoveries"], saved["elapsedSeconds"]) == (
        3,
        2,
        9,
    )
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    with project_scope(env["scope"]):
        assert ComputeTask.objects.count() == 2
