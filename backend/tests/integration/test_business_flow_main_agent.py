"""One executor survives milestones, human waiting and subsequent skill releases."""

from copy import deepcopy
import json
from uuid import uuid4

import pytest
from apps.agent import provider

from apps.business_flows import catalog, engine, runtime
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.state import state
from apps.business_flows.node_trace import node_trace
from apps.projects.context import project_scope
from tests.integration.test_business_flow_runtime import flows  # noqa: F401
from tests.integration.test_agent import setup_agent  # noqa: F401

# ruff: noqa: F811
pytestmark = pytest.mark.efficiency


def install_model(monkeypatch):
    calls = []
    monkeypatch.setattr(provider, "model_window", lambda *_: 32768)
    monkeypatch.setattr(provider, "count_tokens", lambda *_args, **_kw: 1000)

    def response(model, messages, maximum, guard, **options):
        guard()
        packet = json.loads(messages[1]["content"])
        calls.append({"packet": packet, "messages": deepcopy(messages)})
        if "nodeContext" in packet:
            context = packet["nodeContext"]
            phase = context["task"]["phase"]
            if phase == "select_node":
                result = {
                    "action": "start_node",
                    "arguments": {"nodeId": context["task"]["readyNodes"][-1]["id"]},
                }
            elif phase == "finish_workflow":
                result = {
                    "action": "finish_workflow",
                    "arguments": {"summary": "已完成任务及真实成果核查"},
                }
            else:
                refs = [row["id"] for row in packet["evidence"]]
                contract = context["contract"]
                result = {
                    "action": "finish_node",
                    "arguments": {
                        "summary": "依据实际资料形成有来源的分析",
                        "outputs": [
                            {**row, "evidenceId": refs[0]}
                            for row in contract["requiredOutputs"]
                        ],
                        "evidenceIds": refs,
                        "limitations": [],
                        "acceptanceChecks": contract["acceptance"],
                    },
                }
        else:
            result = {
                "decision": "accept",
                "reason": "当前实际证据支持结果",
                "evidenceIds": [row["id"] for row in packet["evidence"]],
            }
        yield json.dumps(result, ensure_ascii=False)

    monkeypatch.setattr(provider, "stream", response)
    monkeypatch.setattr(
        "apps.agent.business_flow_actions.request_action",
        lambda *_a, **_k: pytest.fail("任务主循环不得调用节点执行智能体"),
    )
    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node",
        lambda *_a, **_k: pytest.fail("任务主循环不得派生节点分析智能体"),
    )
    return calls


def test_executor_continues_after_human_wait_with_frozen_skill(flows, monkeypatch):
    env = flows
    calls = install_model(monkeypatch)
    definition = source_summary_definition(main_agent=True)
    definition["skill"]["instructions"] = "依据实际资料逐节点梳理，保留引用与局限。"
    definition["nodes"][0]["review"].update(ai=True, human=True, maxRevisions=1)
    definition["nodes"][1].update(
        kind="agent", instruction="依据前序已核验结果完成综合说明。"
    )
    with project_scope(env["scope"]):
        flow, version = catalog.register_flow(
            env["admin"],
            {
                "code": "main-" + uuid4().hex[:8],
                "name": "持续执行验收",
                "definition": definition,
            },
        )
        workflow = runtime.start_flow(
            env["user"],
            version,
            {
                "model": "mock",
                "goal": "逐步解释真实资料并复核",
                "inputs": {"source": env["resource"].pk},
                "idempotencyKey": uuid4().hex,
            },
        )
        identity = runtime.serialize_run(env["user"], workflow)["mainAgent"]["id"]
        engine.advance(workflow.pk)
        workflow.refresh_from_db()
        assert (
            workflow.parameters["_businessFlow"]["executorSession"]["loop"][
                "activeNodeId"
            ]
            == "summarize"
        )
        runtime.control_flow(env["user"], workflow, "pause")
        workflow.refresh_from_db()
        before = len(calls)
        engine.advance(workflow.pk)
        assert len(calls) == before
        runtime.control_flow(env["user"], workflow, "resume")
        workflow.refresh_from_db()
        for _ in range(8):
            engine.advance(workflow.pk)
            workflow.refresh_from_db()
            if workflow.status == "waiting_approval":
                break
        assert workflow.status == "waiting_approval", workflow.detail
        changed = deepcopy(definition)
        changed["skill"]["instructions"] = (
            "仅用于后来新任务的技能，不能覆盖运行中任务。"
        )
        _, newer = catalog.publish_version(env["admin"], flow, changed)
        assert newer.pk != version.pk
        runtime.decide_flow(
            env["user"],
            workflow,
            {
                "nodeId": "summarize",
                "revision": state(workflow)["revision"],
                "decision": "approve",
                "idempotencyKey": uuid4().hex,
            },
        )
        for _ in range(12):
            engine.advance(workflow.pk)
            workflow.refresh_from_db()
            if workflow.status == "succeeded":
                break
        assert workflow.status == "succeeded", workflow.detail
        assert (
            runtime.serialize_run(env["user"], workflow)["mainAgent"]["id"] == identity
        )
        assert state(workflow)["ledger"]["entries"][0]["summary"]
        root_trace = node_trace(env["user"], workflow, "_main")
        assert all(
            row["role"] == "executor" and row["executorSessionId"] == identity
            for row in root_trace["requests"]
        )
        assert any(row["nodeId"] == "_main" for row in root_trace["requests"])
    assert {row["packet"]["executionSession"]["id"] for row in calls} == {identity}
    assert {row["packet"]["executionSession"]["actor"] for row in calls} == {
        "main_executor",
        "independent_reviewer",
    }
    assert all("后来新任务" not in row["messages"][0]["content"] for row in calls)
    records = list(
        workflow.steps.filter(kind="model_activity", action__actor="executor")
    )
    assert len(records) >= 2
    assert {row.action["executorSessionId"] for row in records} == {identity}


def test_main_executor_selects_legal_milestones_and_rejects_future_nodes(
    flows, monkeypatch
):
    calls = install_model(monkeypatch)
    definition = source_summary_definition(main_agent=True)
    a = deepcopy(definition["nodes"][0])
    a["id"] = "first"
    b = deepcopy(a)
    b["id"] = "second"
    finish = definition["nodes"][1]
    finish["dependsOn"] = ["first", "second"]
    definition["nodes"] = [a, b, finish]
    with project_scope(flows["scope"]):
        _, version = catalog.register_flow(
            flows["admin"],
            {
                "code": "route-" + uuid4().hex[:8],
                "name": "主执行路由验证",
                "definition": definition,
            },
        )
        workflow = runtime.start_flow(
            flows["user"],
            version,
            {
                "model": "mock",
                "goal": "完成全部目标",
                "inputs": {"source": flows["resource"].pk},
                "idempotencyKey": uuid4().hex,
            },
        )
        for _ in range(20):
            engine.advance(workflow.pk)
            workflow.refresh_from_db()
            if workflow.status == "succeeded":
                break
        assert workflow.status == "succeeded", workflow.detail
    starts = [
        row["packet"]["nodeContext"]["task"]["readyNodes"][-1]["id"]
        for row in calls
        if row["packet"].get("nodeContext", {}).get("task", {}).get("phase")
        == "select_node"
    ]
    assert starts == ["second", "first", "finish"]
    assert (
        workflow.parameters["_businessFlow"]["executorSession"]["loop"]["completed"]
        is True
    )
