"""Shared execution semantics and bounded validation work across flow modes."""

from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
import pytest

from apps.agent.policy import default_policy
from apps.business_flows import catalog, runtime
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.definitions import normalize_definition
from apps.business_flows.main_loop import compile_node
from apps.business_flows.node_loop import (
    advance_tool_execution,
    execute_tool,
    loop_state,
)
from apps.business_flows.state import state, parent_run
from apps.compute.models import AlgorithmVersion, ComputeTask, ComputeOutput
from apps.compute.packages import ComputeError
from apps.core.storage import app_path
from apps.projects.context import project_scope
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_business_flow_operator_runtime import (  # noqa: F401
    operators,
    finish_task,
    review_stub,
)
from tests.integration.test_business_flow_node_tools import (
    action,
    advance,
    create,
    contract,
    install,
    submit_args,
    upgrade,
)

# ruff: noqa: F811
pytestmark = pytest.mark.efficiency


def main_workflow(env, *, ai=False):
    definition = source_summary_definition(main_agent=True)
    definition["nodes"] = [
        {
            "id": "calculate",
            "title": "统计实际资料",
            "kind": "operator",
            "description": "依据实际统计形成分析",
            "dataRoles": [],
            "dependsOn": [],
            "algorithmVersionId": env["version"].pk,
            "parameters": deepcopy(env["body"]["parameters"]),
            "inputBindings": {"table": {"role": "source"}},
            "review": {"ai": ai, "human": False, "maxRevisions": 1},
        }
    ]
    with project_scope(env["scope"]):
        _, version = catalog.register_flow(
            env["admin"],
            {
                "code": "consistent-" + uuid4().hex[:8],
                "name": "统一执行",
                "definition": definition,
            },
        )
        return runtime.start_flow(
            env["owner"],
            version,
            {
                "model": "mock",
                "inputs": {"source": env["resource"].pk},
                "idempotencyKey": uuid4().hex,
            },
        )


def tool(env, workflow, name, arguments):
    node = compile_node(
        workflow.parameters["_businessFlow"]["definitionSnapshot"]["nodes"][0]
    )
    item = state(workflow)["nodes"][node["id"]]
    loop = loop_state(item)
    loop["catalogIds"] = [env["version"].pk]
    loop["steps"] += 1
    with project_scope(env["scope"]):
        return execute_tool(
            workflow,
            env["owner"],
            default_policy(),
            node,
            item,
            name,
            arguments,
            [],
            node["contract"],
            lambda: None,
        )


def collect(env, workflow):
    node = compile_node(
        workflow.parameters["_businessFlow"]["definitionSnapshot"]["nodes"][0]
    )
    item = state(workflow)["nodes"][node["id"]]
    with project_scope(env["scope"]):
        advance_tool_execution(
            workflow,
            env["owner"],
            default_policy(),
            node,
            item,
            [],
            guard=lambda: None,
            callbacks={},
            requester=lambda *_a, **_k: pytest.fail(
                "collection does not request a model"
            ),
        )
    return item


def test_main_explicit_role_binding_works_and_changed_input_invalidates_preflight(
    operators,
):
    env = operators
    workflow = main_workflow(env)
    arguments = submit_args(env)
    assert tool(env, workflow, "preflight_operator", arguments)["valid"]
    env["resource"].save(update_fields=["updated_at"])
    with pytest.raises(ComputeError, match="预检"):
        tool(env, workflow, "run_operator", arguments)
    assert not ComputeTask.objects.exists()
    assert tool(env, workflow, "preflight_operator", arguments)["valid"]
    tool(env, workflow, "run_operator", arguments)
    assert ComputeTask.objects.count() == 1


def test_effective_preflight_accepts_explicit_and_implicit_defaults(operators):
    env = operators
    upgrade(env)
    workflow = main_workflow(env)
    explicit = submit_args(
        env,
        parameters={"threshold": 0.5},
        fieldMappings={
            "table": {"group_name": "region", "value": "value"},
        },
    )
    assert tool(env, workflow, "preflight_operator", explicit)["valid"]
    tool(env, workflow, "run_operator", submit_args(env))
    item = state(workflow)["nodes"]["calculate"]
    finish_task(env, item["computeTaskId"], "CANONICAL")
    collect(env, workflow)
    reused = tool(env, workflow, "run_operator", explicit)
    assert reused["taskId"] == item["computeTaskId"]
    assert item["toolLoop"]["recoveries"] == 0
    assert ComputeTask.objects.count() == workflow.operator_steps == 1


def test_missing_preflight_recovers_without_changing_scientific_plan(
    operators, monkeypatch
):
    env = operators
    upgrade(env)
    workflow = main_workflow(env)
    install(
        monkeypatch,
        [
            action("start_node", nodeId="calculate"),
            action("operator_catalog"),
            action("run_operator", **submit_args(env)),
            action("preflight_operator", **submit_args(env)),
            action("run_operator", **submit_args(env)),
        ],
    )
    item = advance(env, workflow, 3)
    loop = item["toolLoop"]
    assert loop["lastObservation"]["result"]["failure"]["code"] == "PREFLIGHT_REQUIRED"
    assert not loop.get("failure") and loop["recoveries"] == 0
    assert not ComputeTask.objects.exists()
    advance(env, workflow, 2)
    assert ComputeTask.objects.count() == workflow.operator_steps == 1
    assert loop_state(state(workflow)["nodes"]["calculate"])["recoveries"] == 0


def test_live_record_with_stale_preflight_failure_keeps_budget_and_resumes(operators):
    env = operators
    upgrade(env)
    workflow = main_workflow(env)
    item = state(workflow)["nodes"]["calculate"]
    loop = loop_state(item)
    loop.update(
        modelCalls=21,
        recoveries=2,
        failure={
            "code": "OPERATOR_FAILED",
            "action": "run_operator",
            "remedy": "human_review",
            "message": "须先对相同版本、输入、参数和字段映射完成预检，才能计算",
        },
    )
    loop["history"] = [
        {"step": 3, "action": "run_operator", "summary": "原前置条件诊断"}
    ]
    tool(env, workflow, "preflight_operator", submit_args(env))
    tool(env, workflow, "run_operator", submit_args(env))
    assert ComputeTask.objects.count() == 1
    assert loop["modelCalls"] == 21 and loop["recoveries"] == 2
    assert len(loop["history"]) == 1 and not loop.get("failure")


def test_failed_live_preflight_does_not_spend_recovery_or_leave_a_task(operators):
    env = operators
    upgrade(env)
    workflow = main_workflow(env)
    arguments = submit_args(env, parameters={"threshold": 0.5})
    tool(env, workflow, "preflight_operator", arguments)
    loop = loop_state(state(workflow)["nodes"]["calculate"])
    loop["failure"] = {
        "code": "BOUNDS",
        "remedy": "adjust_parameters",
        "message": "原计算失败",
    }
    loop["lastSubmission"] = arguments
    changed = submit_args(
        env, parameters={"threshold": 0.6}, remedy="adjust_parameters"
    )
    from apps.compute.packages import PreflightRequired

    with pytest.raises(PreflightRequired):
        tool(env, workflow, "run_operator", changed)
    assert loop["recoveries"] == 0 and not loop["remedies"]
    assert loop["failure"]["code"] == "BOUNDS" and not ComputeTask.objects.exists()


def test_recovery_can_replace_an_explicitly_bound_role(operators):
    from apps.business_flows.node_loop import wait_recovery
    from apps.catalog.models import DataResource

    env = operators
    workflow = main_workflow(env)
    node = compile_node(
        workflow.parameters["_businessFlow"]["definitionSnapshot"]["nodes"][0]
    )
    item = state(workflow)["nodes"]["calculate"]
    workflow.current_step = "calculate"
    with project_scope(env["scope"]):
        replacement = DataResource.objects.get(pk=env["resource"].pk)
        replacement.pk = None
        replacement.code = "replacement-source"
        replacement.save()
        wait_recovery(
            workflow,
            node,
            item,
            {"code": "INPUT_INVALID", "remedy": "replace_data", "message": "替换资料"},
        )
        runtime.decide_flow(
            env["owner"],
            workflow,
            {
                "nodeId": "calculate",
                "decision": "retry_recovery",
                "revision": state(workflow)["revision"],
                "idempotencyKey": uuid4().hex,
                "recoveryInputs": {"source": replacement.pk},
            },
        )
    workflow.refresh_from_db()
    assert workflow.plan["inputs"]["source"] == replacement.pk
    assert state(workflow)["nodes"]["calculate"]["human"]["status"] != "approved"


@pytest.mark.parametrize("damage", ["expired", "missing", "tampered", "checksum"])
def test_success_reuse_rechecks_real_output_without_resubmitting(operators, damage):
    env = operators
    upgrade(env)
    workflow = create(env)
    arguments = submit_args(env)
    tool(env, workflow, "run_operator", arguments)
    item = state(workflow)["nodes"]["calculate"]
    output = finish_task(env, item["computeTaskId"], "REAL")
    collect(env, workflow)
    if damage == "expired":
        output.expired = True
        output.save(update_fields=["expired"])
    elif damage == "checksum":
        output.checksum = "0" * 64
        output.save(update_fields=["checksum"])
    elif damage == "missing":
        app_path(output.path).unlink()
    else:
        app_path(output.path).write_text("region,value\nFAKE,999\n")
    with pytest.raises(ComputeError):
        tool(env, workflow, "run_operator", arguments)
    assert ComputeTask.objects.count() == 1
    assert workflow.operator_steps == 1


def test_changed_source_does_not_reuse_old_success(operators):
    env = operators
    upgrade(env)
    workflow = create(env)
    arguments = submit_args(env)
    tool(env, workflow, "run_operator", arguments)
    item = state(workflow)["nodes"]["calculate"]
    first = item["computeTaskId"]
    finish_task(env, first, "OLD")
    collect(env, workflow)
    env["resource"].save(update_fields=["updated_at"])
    tool(env, workflow, "run_operator", arguments)
    assert item["computeTaskId"] != first
    assert ComputeTask.objects.count() == 2


def test_fixed_operator_cannot_switch_core_version(operators):
    env = operators
    workflow = main_workflow(env)
    other = AlgorithmVersion.objects.get(pk=env["version"].pk)
    other.pk = None
    other.version = "9.9.9"
    other.save()
    item = state(workflow)["nodes"]["calculate"]
    loop_state(item)["catalogIds"] = [other.pk]
    node = compile_node(
        workflow.parameters["_businessFlow"]["definitionSnapshot"]["nodes"][0]
    )
    with project_scope(env["scope"]), pytest.raises(ComputeError, match="冻结"):
        from apps.business_flows.node_loop import submission

        submission(
            workflow,
            env["owner"],
            {"operatorEnabled": True},
            node,
            item["toolLoop"],
            {**submit_args(env), "versionId": other.pk},
        )


def test_bulk_collection_authorizes_task_twice_for_nine_outputs(operators):
    from apps.agent import compute_result_tools

    env = operators
    upgrade(env)
    workflow = create(env)
    tool(env, workflow, "run_operator", submit_args(env))
    item = state(workflow)["nodes"]["calculate"]
    output = finish_task(env, item["computeTaskId"], "ONE")
    for index in range(8):
        ComputeOutput.objects.create(
            task=output.task,
            key=f"extra_{index}",
            label=f"表{index}",
            kind=output.kind,
            file_name=output.file_name,
            path=output.path,
            checksum=output.checksum,
            size_bytes=output.size_bytes,
            metadata=output.metadata,
        )
    with (
        project_scope(env["scope"]),
        patch.object(
            compute_result_tools,
            "authorized_task",
            wraps=compute_result_tools.authorized_task,
        ) as checks,
    ):
        rows = compute_result_tools.read_task_outputs(
            parent_run(workflow),
            env["owner"],
            default_policy(),
            output.task,
            workflow=workflow,
        )
        assert len(rows) == 9
        assert checks.call_count == 2
    collected = collect(env, workflow)
    assert len(collected["outputs"]["evidence"]) == 9


def test_bulk_read_checks_revocation_after_reading(operators, monkeypatch):
    from apps.agent import compute_result_tools

    env = operators
    upgrade(env)
    workflow = create(env)
    tool(env, workflow, "run_operator", submit_args(env))
    item = state(workflow)["nodes"]["calculate"]
    output = finish_task(env, item["computeTaskId"], "READ")
    original = compute_result_tools._read_output

    def read(*args):
        result = original(*args)
        resource = env["resource"]
        resource.owner_only, resource.maintainer = True, env["outsider"]
        resource.save(update_fields=["owner_only", "maintainer", "updated_at"])
        return result

    monkeypatch.setattr(compute_result_tools, "_read_output", read)
    with project_scope(env["scope"]), pytest.raises(PermissionDenied):
        compute_result_tools.read_task_outputs(
            parent_run(workflow),
            env["owner"],
            default_policy(),
            output.task,
            workflow=workflow,
        )


def test_declared_ancestor_contract_output_uses_real_import_queue(operators):
    from apps.business_flows.node_loop import resolve_output_bindings, InputsPending
    from apps.compute.models import ComputeImport
    from apps.compute.worker import process_import, task_scope

    env = operators
    upgrade(env)
    workflow = create(env)
    tool(env, workflow, "run_operator", submit_args(env))
    item = state(workflow)["nodes"]["calculate"]
    output = finish_task(env, item["computeTaskId"], "ANCESTOR")
    collect(env, workflow)
    item["status"] = "succeeded"
    item["contractOutputs"] = [
        {
            "name": "statistics",
            "semanticType": "operator_result",
            "evidenceId": f"output-{output.pk}",
        }
    ]
    state(workflow)["nodes"]["middle"] = {"status": "succeeded", "outputs": {}}
    consumer = {
        "id": "finish",
        "dependsOn": ["middle"],
        "dataRoles": [],
        "inputBindings": {"table": {"nodeId": "calculate", "outputKey": "statistics"}},
    }
    inputs = {"table": {"outputId": output.pk}}
    loop = loop_state(state(workflow)["nodes"]["finish"])
    workflow.save(update_fields=["plan"])
    with project_scope(env["scope"]):
        with pytest.raises(InputsPending):
            resolve_output_bindings(
                workflow, env["owner"], default_policy(), consumer, loop, inputs
            )
        record = ComputeImport.objects.get(output=output)
        with task_scope(output.task):
            process_import(record)
        record.refresh_from_db()
        assert record.status == "ready", record.error
        assert resolve_output_bindings(
            workflow, env["owner"], default_policy(), consumer, loop, inputs
        ) == {"table": record.resource_id}
        assert ComputeTask.objects.count() == 1


@pytest.mark.parametrize("mode", ["revision", "repack"])
def test_main_operator_review_revises_text_without_recomputing(
    operators, monkeypatch, mode
):
    env = operators
    workflow = main_workflow(env, ai=True)
    calls = []
    normal = review_stub(calls, 1 if mode == "revision" else 0)
    repacked = []

    def review(*args, **kwargs):
        if mode == "repack" and not repacked:
            from apps.agent.business_flow_context import ContextReviewRequired

            repacked.append(True)
            raise ContextReviewRequired(
                {
                    "nodeId": "calculate",
                    "level": 4,
                    "reason": "审核窗口较小",
                    "requiresExecutionRepack": True,
                    "reviewContextBudget": {
                        "maxContextTokens": 10000,
                        "maxContextBytes": 80000,
                    },
                    "evidence": [],
                }
            )
        return normal(*args, **kwargs)

    monkeypatch.setattr("apps.agent.business_flow_review.review_node", review)

    def delivered(packet):
        identity = next(
            row["id"] for row in packet["evidence"] if row["id"].startswith("output-")
        )
        return action(
            "finish_node",
            summary="真实统计与局限说明",
            evidenceIds=[identity],
            outputs=[
                {
                    "name": "result",
                    "semanticType": "operator_result",
                    "evidenceId": identity,
                }
            ],
        )

    install(
        monkeypatch,
        [
            action("start_node", nodeId="calculate"),
            action("operator_catalog"),
            action("preflight_operator", **submit_args(env)),
            action("run_operator", **submit_args(env)),
            delivered,
            delivered,
        ],
    )
    item = advance(env, workflow, 4)
    finish_task(env, item["computeTaskId"], "RETAINED")
    item = advance(env, workflow, 3)
    assert item["status"] == "succeeded", workflow.detail
    assert item["attempt"] == (2 if mode == "revision" else 1)
    assert len(calls) == (2 if mode == "revision" else 1)
    assert ComputeTask.objects.count() == 1


@pytest.mark.parametrize(
    "missing", ["preflight_operator", "operator_catalog", "run_operator", "budget"]
)
def test_main_contract_cannot_publish_an_unexecutable_output(missing):
    definition = source_summary_definition(main_agent=True)
    configured = contract()
    if missing == "budget":
        configured["maxOperatorCalls"] = 0
    else:
        configured["tools"].remove(missing)
    definition["nodes"][0]["contract"] = configured
    with pytest.raises(ValidationError):
        normalize_definition(definition)
