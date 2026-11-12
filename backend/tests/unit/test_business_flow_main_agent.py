"""Short guidance and reference-only recall over one durable task identity."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.business_flows.builtins import geology_definition
from apps.business_flows.definitions import normalize_definition
from apps.business_flows.execution_session import (
    guidance,
    initialize,
    request_context,
    session,
    task_record,
)
from apps.business_flows.ledger import professional_ledger, size, MAX_LEDGER_BYTES
from apps.business_flows.logic_nodes import (
    check_submission,
    node_definition,
    visible_inputs,
)
from apps.business_flows.state import state
from apps.compute.packages import ComputeError
from django.core.exceptions import ValidationError


def task():
    definition = geology_definition(main_agent=True)
    workflow = SimpleNamespace(
        workflow_type="geology_generic",
        goal="依据真实岩性、构造与蚀变资料完成推理",
        parameters={
            "_businessFlow": {"definitionSnapshot": definition, "versionId": 7}
        },
        plan={"stages": [], "algorithms": {}},
    )
    initialize(workflow)
    return workflow


def test_same_executor_uses_only_current_skill_note_and_frozen_copy():
    workflow = task()
    frozen = session(workflow)
    frozen["skill"]["nodeInstructions"].update(
        check="当前检查说明", prospect="仅供远景节点的说明"
    )
    a = request_context(workflow, "check")
    b = request_context(workflow, "prospect")
    assert a["id"] == b["id"] and a["nodeId"] != b["nodeId"]
    assert "当前检查说明" in guidance(workflow, "check")
    assert "仅供远景节点的说明" not in guidance(workflow, "check")
    original = frozen["skill"]["instructions"]
    workflow.parameters["_businessFlow"]["definitionSnapshot"]["skill"][
        "instructions"
    ] = "其他发布版本"
    assert frozen["skill"]["instructions"] == original
    assert (
        request_context(workflow, "check", "reviewer")["actor"]
        == "independent_reviewer"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"instructions": "长" * 601},
        {"nodeInstructions": {"missing-node": "无对应节点"}},
        {"nodeInstructions": {"check": "长" * 301}},
        {"path": "/arbitrary/file.md"},
    ],
)
def test_skill_rejects_unbounded_or_unregistered_guidance(change):
    definition = geology_definition()
    definition["skill"].update(change)
    with pytest.raises(ValidationError):
        normalize_definition(definition)


def test_professional_memory_recalls_real_executor_summaries_without_file_bodies():
    workflow = task()
    values = state(workflow)
    for identity in ("check", "apply", "recheck", "relations", "prospect"):
        workflow.plan["stages"].append(
            {
                "name": identity,
                "status": "completed",
                "parameters": {"grid_resolution_m": 50},
                "results": [
                    {
                        "outputId": number,
                        "key": "statistics",
                        "checksum": "a" * 64,
                        "content": "不得自动装入上下文的文件正文" * 1000,
                    }
                    for number in range(20)
                ],
            }
        )
        values["nodes"][identity]["status"] = "succeeded"
        values["nodes"][identity]["executor"].update(
            summary="实际节点摘要" * 100, limitations=["有待核实的限制"]
        )
    ledger = professional_ledger(workflow)
    assert all(row["summary"] for row in ledger["entries"])
    assert size(ledger) <= MAX_LEDGER_BYTES
    assert all(
        len(row["outputs"]) <= 4 and row["outputCount"] == 20
        for row in ledger["entries"]
    )
    assert "文件正文" not in str(ledger)
    recalled = task_record(workflow, "check", offset=8, limit=4)
    assert [row["outputId"] for row in recalled["outputs"]] == [8, 9, 10, 11]
    assert recalled["nextOffset"] == 12
    assert "不得自动装入上下文的文件正文" not in str(recalled)
    assert recalled["parameters"] == {"grid_resolution_m": 50}
    for invalid in ("inputs", "other-workflow-node", None, []):
        with pytest.raises(ComputeError):
            task_record(workflow, invalid)


def test_new_session_accepts_data_bindings_but_protects_core_and_approval_inputs():
    workflow = task()
    workflow.plan.update(
        stageIndex=0,
        stages=[
            {
                "name": "check",
                "identifier": "geology-multi-check",
                "parameters": {"grid_resolution_m": 100},
            }
        ],
        algorithms={"geology-multi-check": {"versionId": 4, "checksum": "a" * 64}},
        uploadInputs={"lithology": 10},
    )
    state(workflow)["nodes"]["check"]["toolLoop"] = {
        "approvedInputs": {"lithology": 11, "rules": 12}
    }
    node = node_definition(workflow, workflow.plan["stages"][0])
    version = SimpleNamespace(pk=4, checksum="a" * 64, manifest={"schemaVersion": 2})
    body = {
        "inputs": {"lithology": 10, "rules": 12},
        "parameters": {"grid_resolution_m": 50},
        "fieldMappings": {},
    }
    assert 10 in visible_inputs(workflow, node).values()
    check_submission(workflow, node, version, body)
    with pytest.raises(ComputeError, match="批准|处置|规则"):
        check_submission(
            workflow, node, version, {**body, "inputs": {"lithology": 10, "rules": 99}}
        )
    with pytest.raises(ComputeError, match="版本"):
        check_submission(workflow, node, SimpleNamespace(pk=5), body)
    workflow.parameters["_businessFlow"].pop("executorSession")
    with pytest.raises(ComputeError):
        check_submission(workflow, node, version, body)
