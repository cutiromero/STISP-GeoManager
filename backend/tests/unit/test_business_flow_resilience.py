"""Completion follows evidence; compression preserves facts and task ownership."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.agent.business_flow_context import (
    ContextReviewRequired,
    encode,
    prepare_packet,
    project_evidence,
)
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.model_requests import (
    admit,
    ModelCallBudgetExceeded,
    request_limit,
)
from apps.business_flows.node_loop import finish
from apps.business_flows.state import state


def request_packet():
    return {
        "node": {"id": "analyse", "instruction": "依据实际证据分析"},
        "evidence": [
            {
                "id": "approved-inputs",
                "kind": "analysis",
                "title": "实际输入",
                "result": {"parameters": {"red": 3, "nir": 5}, "count": 12},
            }
        ],
        "ledger": {"entries": [], "unresolved": []},
        "contextNotice": [],
        "nodeContext": {
            "task": {
                "history": [
                    {
                        "nodeId": str(i),
                        "action": "read_evidence",
                        "summary": str(i) + "先前的长行动说明" * 100,
                    }
                    for i in range(24)
                ]
            },
            "observation": {"evidenceId": "latest", "result": {"count": 12}},
        },
    }


def test_history_compacts_without_an_extra_model_and_keeps_latest_observation():
    packet = request_packet()
    original = deepcopy(packet)
    actual, _, audit = prepare_packet(
        packet,
        "主执行继续任务",
        None,
        {
            "maxContextTokens": 1500,
            "maxContextBytes": 192 * 1024,
            "maxOutputTokens": 512,
        },
        32768,
        direct_ids={"approved-inputs"},
        summarize=lambda *args: pytest.fail("历史整理不应额外请求模型"),
        checked=lambda: None,
        measurements=SimpleNamespace(
            cache={},
            measure=lambda messages, checked: (
                sum(len(row["content"]) for row in messages) // 2
            ),
        ),
    )
    assert audit["level"] == 1
    assert len(actual["nodeContext"]["task"]["history"]) == 4
    assert (
        actual["nodeContext"]["observation"] == original["nodeContext"]["observation"]
    )
    assert actual["evidence"] == original["evidence"] and packet == original


def test_scientific_facts_and_approved_parameters_survive_projection():
    evidence = [
        {
            "id": "source",
            "kind": "analysis",
            "title": "实际结果",
            "result": {
                "verifiedReportFacts": {str(i): i for i in range(100)},
                "parameters": {str(i): i for i in range(100)},
                "conditions": ["适用条件" + str(i) for i in range(50)],
                "decision": {"findings": ["完整分析" * 500]},
                "sample": list(range(100)),
            },
        }
    ]
    actual, notices = project_evidence(evidence)
    for key in ("verifiedReportFacts", "parameters", "conditions", "decision"):
        assert actual[0]["result"][key] == evidence[0]["result"][key]
    assert len(actual[0]["result"]["sample"]) == 10 and notices


def test_protected_facts_are_never_replaced_by_lossy_batch_summary():
    packet = request_packet()
    packet["nodeContext"] = {}
    packet["evidence"][0]["result"]["parameters"] = {"mapping": "重要参数" * 2000}
    with pytest.raises(ContextReviewRequired):
        prepare_packet(
            packet,
            "继续任务",
            None,
            {
                "maxContextTokens": 500,
                "maxContextBytes": 192 * 1024,
                "maxOutputTokens": 512,
            },
            32768,
            direct_ids=set(),
            checked=lambda: None,
            summarize=lambda *args: pytest.fail("批准依据不可交给有损归纳"),
            measurements=SimpleNamespace(
                cache={},
                measure=lambda messages, checked: len(encode(messages)) // 2,
            ),
        )


def test_task_control_uses_task_budget_without_spending_completed_node_budget():
    definition = source_summary_definition()
    identity = definition["nodes"][0]["id"]
    workflow = SimpleNamespace(
        workflow_type="business_flow",
        current_step=identity,
        plan={},
        max_iterations=64,
        parameters={"_businessFlow": {"definitionSnapshot": definition}},
    )
    loop = state(workflow)["nodes"][identity]["toolLoop"] = {
        "modelCalls": 32,
        "requestIds": [],
    }
    admit(workflow, "finish-whole-task", node_scoped=False)
    assert loop["modelCalls"] == 32
    assert state(workflow)["requestedIds"] == ["finish-whole-task"]
    with pytest.raises(ModelCallBudgetExceeded):
        admit(workflow, "another-node-request")


def test_default_task_budget_reserves_required_routing_for_long_flows():
    definition = {
        "executionMode": "main_agent",
        "nodes": [{"id": str(i)} for i in range(32)],
    }
    assert request_limit({"maxSteps": 32}, definition) == 97
    assert request_limit({"maxSteps": 32}, definition) > 32 * 2 + 1
    assert request_limit({"maxSteps": 0}, definition) == 256
    assert request_limit({"maxSteps": 128}, definition) == 256
    assert request_limit({"maxSteps": 32}) == 64


def test_preparation_keeps_request_timeout_separate_from_elapsed_node_time(monkeypatch):
    from apps.business_flows import script_preparation

    definition = source_summary_definition()
    identity = definition["nodes"][0]["id"]
    workflow = SimpleNamespace(
        workflow_type="business_flow",
        plan={},
        parameters={"_businessFlow": {"definitionSnapshot": definition}},
    )
    state(workflow)["nodes"][identity]["toolLoop"] = {"elapsedSeconds": 601}
    monkeypatch.setattr("apps.business_flows.state.persist", lambda *args: None)
    captured = []
    monkeypatch.setattr(
        script_preparation, "_prepare", lambda w, u, p, e: captured.append(p) or True
    )
    assert script_preparation.prepare(
        workflow, None, {"maxRunSeconds": 600}, {"nodeId": identity}
    )
    assert captured[0]["maxRunSeconds"] == 600


@pytest.mark.parametrize("checks", [None, ["根据实际统计完成核对"]])
def test_completion_does_not_require_verbatim_self_attestation(checks):
    node = {
        "contract": {
            "requiredOutputs": [{"name": "result", "semanticType": "analysis"}],
            "acceptance": ["必须依据本次实际证据作出分析"],
        }
    }
    arguments = {
        "summary": "实际分析",
        "evidenceIds": ["actual"],
        "limitations": [],
        "outputs": [
            {"name": "result", "semanticType": "analysis", "evidenceId": "actual"}
        ],
    }
    if checks is not None:
        arguments["acceptanceChecks"] = checks
    result = finish(node, {}, arguments, [{"id": "actual", "kind": "analysis"}])
    assert result["summary"] == "实际分析"
