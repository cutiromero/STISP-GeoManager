"""真实地质算子对照：节点工具改变调度，不改变已批准的科学结果。"""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from django.utils import timezone

from apps.agent import provider
from apps.agent.models import AgentPolicy
from apps.agent.workflow import run_workflow, resume_waiting
from apps.business_flows import catalog, runtime
from apps.business_flows.builtins import builtin_flows
from apps.business_flows.state import state
from apps.compute.data import candidate
from apps.compute.packages import checksum
from apps.compute.models import ComputeTask, ComputeImport, RuntimeLease
from apps.compute.worker import process_import
from apps.core.storage import app_path
from tests.integration.test_logic_reasoning_journey import (
    register_rules,
    register_operators,
    system_references,
    native_task,
    post,
)
from tests.unit.test_geology_multi_algorithms import fixture, read

pytest_plugins = ["tests.integration.test_generic_chat"]
pytestmark = [pytest.mark.django_db, pytest.mark.efficiency]

# Configuration: both paths use identical fixture files, rules and approvals.
MAX_ADVANCES = 180
EFFORT = "medium"


@pytest.mark.parametrize("name", ["check", "apply", "relations", "prospect"])
def test_execution_catalog_keeps_input_contract_and_fits_node_read_budget(name):
    from apps.compute.operator_catalog import compact_description
    from apps.compute.packages import validate_manifest
    from apps.business_flows.node_contracts import (
        MAX_EVIDENCE_BYTES,
        MAX_FRAGMENT_BYTES,
    )

    source = (
        Path(__file__).resolve().parents[3]
        / f"examples/compute/geology-multi-{name}/operator.yaml"
    )
    manifest = validate_manifest(json.loads(source.read_text()))
    version = SimpleNamespace(
        pk=17,
        manifest=manifest,
        version=manifest["version"],
        algorithm=SimpleNamespace(
            identifier=manifest["identifier"], name=manifest["name"]
        ),
    )
    full = compact_description(version, MAX_EVIDENCE_BYTES)
    execution = compact_description(version, MAX_EVIDENCE_BYTES, view="execution")
    assert execution["inputs"] == full["inputs"]
    assert execution["parameters"] == full["parameters"]
    assert execution["errors"] == full["errors"]
    assert {(row["key"], row["kind"]) for row in execution["outputs"]} == {
        (row["key"], row["kind"]) for row in full["outputs"]
    }
    assert execution["fullContractLookup"] == {"versionId": 17, "view": "full"}
    assert execution["truncated"] is False
    size = len(
        json.dumps(execution, ensure_ascii=False, separators=(",", ":")).encode()
    )
    reads = (size + MAX_FRAGMENT_BYTES - 1) // MAX_FRAGMENT_BYTES
    assert 4 + reads + 1 <= 12  # Catalog, preflight, run, finish, and one repair.


def node_action(packet, *, mapping_failure=False):
    context = packet["nodeContext"]
    approved = next(
        row["result"] for row in packet["evidence"] if row["id"] == "approved-inputs"
    )
    history = [row["action"] for row in context["history"]]
    arguments = {key: approved[key] for key in ("versionId", "inputs")}
    arguments["parameters"] = {}  # The manifest/frozen defaults remain effective.
    arguments["fieldMappings"] = {}
    if mapping_failure and packet["node"]["id"] == "check" and context.get("failure"):
        arguments["fieldMappings"] = {"lithology": {"feature_id": "feature_id"}}
    if "operator_catalog" not in history:
        answer = {
            "action": "operator_catalog",
            "arguments": {"keyword": approved["identifier"]},
        }
    elif "preflight_operator" not in history or (
        context.get("failure")
        and history[-1] == "preflight_operator"
        and not context.get("observation", {}).get("result", {}).get("valid")
    ):
        if (
            mapping_failure
            and packet["node"]["id"] == "check"
            and "preflight_operator" not in history
        ):
            arguments["fieldMappings"] = {"lithology": {"feature_id": "不存在"}}
        answer = {"action": "preflight_operator", "arguments": arguments}
    elif "run_operator" not in history:
        if context.get("failure"):
            arguments["remedy"] = "complete_mapping"
        answer = {"action": "run_operator", "arguments": arguments}
    else:
        outputs = [
            row["id"] for row in packet["evidence"] if row["id"].startswith("output-")
        ]
        assert outputs, context
        output = outputs[0]
        answer = {
            "action": "finish_node",
            "arguments": {
                "summary": "已核对登记版本、输入与完整统计",
                "outputs": [
                    {
                        "name": "result",
                        "semanticType": "operator_result",
                        "evidenceId": output,
                    }
                ],
                "evidenceIds": [output],
                "limitations": ["对象处置与质量审核沿用原批准边界"],
                "acceptanceChecks": context["contract"]["acceptance"],
            },
        }
    return answer


def install_model(monkeypatch, *, mapping_failure=False):
    calls = []
    monkeypatch.setattr(provider, "model_window", lambda model: 32768)
    monkeypatch.setattr(provider, "count_tokens", lambda *args, **kwargs: 1000)
    monkeypatch.setattr("apps.agent.context.count_tokens", lambda *args: 1000)

    def stream(model, messages, maximum, guard, **options):
        guard()
        packet = json.loads(messages[1]["content"])
        calls.append((deepcopy(packet), options))
        options["on_thinking"]("正在核对本节点实际输入、预检诊断与统计依据。")
        if "nodeContext" not in packet:
            answer = {
                "decision": "accept",
                "reason": "实际完整统计支持结论，处置范围仍由用户确认",
                "issues": [],
                "repairInstructions": "",
                "evidenceIds": [row["id"] for row in packet["evidence"]],
            }
        else:
            answer = node_action(packet, mapping_failure=mapping_failure)
        yield json.dumps(answer, ensure_ascii=False)

    monkeypatch.setattr(provider, "stream", stream)
    return calls


def run_to_completion(env, workflow):
    for _ in range(MAX_ADVANCES):
        RuntimeLease.objects.filter(name="worker").update(heartbeat=timezone.now())
        workflow.refresh_from_db()
        assert workflow.status not in {"failed", "interrupted", "cancelled"}, (
            workflow.detail
        )
        if workflow.status == "succeeded":
            return workflow
        if workflow.status == "waiting_approval":
            assert not any(
                item.get("recovery") or item.get("contextRecovery")
                for item in state(workflow)["nodes"].values()
            ), (workflow.detail, state(workflow))
            value = {"planHash": workflow.plan_hash}
            if workflow.plan["phase"] == "review_mapping":
                value.update(
                    fieldMapping={
                        row["role"]: {
                            target["key"]: target.get("field")
                            for target in row["targets"]
                        }
                        for row in workflow.plan["fieldMappingReview"]["roles"]
                    },
                    executeAfterMapping=True,
                )
            elif workflow.plan["phase"] == "review_modifications":
                value["selectedSuggestionIds"] = [
                    row["id"]
                    for row in workflow.plan["modificationReview"]["suggestions"]
                    if row["status"] == "suggested"
                ]
            response = post(env, f"/api/agent/workflows/{workflow.pk}/confirm/", value)
            assert response.status_code == 200, response.content
        else:
            for task in ComputeTask.objects.filter(owner=env["owner"], status="queued"):
                native_task(task)
            for record in ComputeImport.objects.filter(status="queued"):
                process_import(record)
                record.refresh_from_db()
                assert record.status == "ready", record.error
            if workflow.status == "waiting_compute":
                resume_waiting()
            else:
                run_workflow(workflow.pk)
    pytest.fail(f"流程未完成：{workflow.status} {workflow.detail}")


def compare_science(before, after):
    counts = {"table": 0, "vector": 0, "raster": 0}
    for old_stage, new_stage in zip(
        before.plan["stages"], after.plan["stages"], strict=True
    ):
        assert old_stage["name"] == new_stage["name"]
        old_task, new_task = [
            ComputeTask.objects.get(pk=stage["taskId"])
            for stage in (old_stage, new_stage)
        ]
        assert old_task.version_id == new_task.version_id
        assert old_task.parameters == new_task.parameters
        old = {row.key: row for row in old_task.outputs.all()}
        new = {row.key: row for row in new_task.outputs.all()}
        assert old.keys() == new.keys()
        for key, output in old.items():
            left, right = app_path(output.path), app_path(new[key].path)
            if output.kind == "table":
                assert read(left) == read(right), (old_stage["name"], key)
            elif output.kind == "vector":
                a, b = gpd.read_file(left), gpd.read_file(right)
                assert a.crs == b.crs and len(a) == len(b)
                assert a.drop(columns="geometry").equals(b.drop(columns="geometry")), (
                    key
                )
                assert all(
                    x.equals_exact(y, 1e-6)
                    for x, y in zip(a.geometry, b.geometry, strict=True)
                ), key
            elif output.kind == "raster":
                with rasterio.open(left) as a, rasterio.open(right) as b:
                    assert (a.crs, a.transform, a.nodata) == (
                        b.crs,
                        b.transform,
                        b.nodata,
                    )
                    np.testing.assert_array_equal(a.read(), b.read())
                    np.testing.assert_array_equal(a.read_masks(), b.read_masks())
            else:
                continue
            counts[output.kind] += 1
    return counts


@pytest.mark.parametrize("mapping_failure", [False, True])
def test_seven_nodes_match_original_science_with_real_operators(
    generic, tmp_path, monkeypatch, settings, mapping_failure
):
    from apps.projects.context import ProjectScope, project_scope

    settings.AGENT_MODELS[0]["qwen"] = True
    # Match the real account's existing configuration: zero means unlimited.
    policy = {**generic["policy"], "maxSteps": 0, "maxIterations": 20}
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": policy})
    generic["project"].code = "02"
    generic["project"].save(update_fields=["code"])
    monkeypatch.setattr("apps.compute.services.candidate", candidate)
    context, _ = fixture(tmp_path)
    register_rules(generic, context)
    register_operators(generic)
    source_checksums = {path: checksum(path) for path in context.inputs.values()}
    roles = system_references(generic, context)
    calls = install_model(monkeypatch, mapping_failure=mapping_failure)
    scope = ProjectScope(
        (generic["project"].pk,), generic["project"].pk, generic["owner"].pk
    )
    with project_scope(scope):
        _, version = catalog.register_flow(generic["admin"], builtin_flows()[0])
        results = []
        for adaptive in (False, True):
            workflow = runtime.start_flow(
                generic["owner"],
                version,
                {
                    "model": "mock",
                    "goal": "按相同规则核对岩性构造蚀变并生成远景与报告",
                    "reasoningEffort": EFFORT,
                    "inputs": roles,
                    "parameters": {"uploadBatchId": generic["batch"]},
                    "agentEnabled": adaptive,
                    "idempotencyKey": uuid4().hex,
                },
            )
            # A batch belongs to one workflow; rebuild the same catalog references.
            if adaptive is False:
                results.append(run_to_completion(generic, workflow))
                from apps.agent.workflow_uploads import add_catalog_references

                generic["batch"] = uuid4().hex
                add_catalog_references(
                    generic["owner"],
                    generic["project"].pk,
                    generic["batch"],
                    list(roles.values()),
                )
            else:
                results.append(run_to_completion(generic, workflow))
        old, new = results
        assert new.max_iterations == 256
        assert new.plan["modelCallBudget"]["minimumStageRequests"] == 23
        counts = compare_science(old, new)
        assert {path: checksum(path) for path in source_checksums} == source_checksums
        assert all(counts.values())
        for node_id in ("check", "apply", "recheck", "relations", "prospect"):
            item = state(new)["nodes"][node_id]
            assert "统计依据" in item["executor"]["thinking"]
            loop = item["toolLoop"]
            assert loop["finished"] and loop["operatorCalls"] == 1
            expected_actions = [
                "operator_catalog",
                "preflight_operator",
                "run_operator",
                "finish_node",
            ]
            if mapping_failure and node_id == "check":
                expected_actions.insert(2, "preflight_operator")
                assert loop["recoveries"] == 1
            assert [row["action"] for row in loop["history"]] == expected_actions
            assert loop["modelCalls"] == len(expected_actions)
        tool_calls = [options for packet, options in calls if "nodeContext" in packet]
        assert len(tool_calls) == (21 if mapping_failure else 20)
        assert all(
            row["thinking"] is True and row["reasoning_effort"] == EFFORT
            for row in tool_calls
        )
        report = post(generic, f"/api/agent/workflows/{new.pk}/report/", {})
        assert report.status_code in {200, 201}, report.content
        print("scientific parity:", counts, "model tool calls:", len(tool_calls))
