"""Real durable recovery decisions continue the original executor without approval."""

# ruff: noqa: F811
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied

from apps.agent import provider
from apps.agent.business_flow_context import ContextReviewRequired
from apps.business_flows import catalog, engine, runtime
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.execution_session import session, initialize
from apps.business_flows.model_recovery import guidance_context
from apps.business_flows.state import state
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401
from tests.integration.test_business_flow_runtime import flows  # noqa: F401
from tests.integration.test_business_flow_main_agent import install_model
from tests.integration.test_demo_decision_retry import ordinary_stage, run, retry_model  # noqa: F401

pytestmark = pytest.mark.efficiency


def create(env):
    definition = source_summary_definition(main_agent=True)
    definition["nodes"] = definition["nodes"][:1]
    definition["nodes"][0]["review"] = {"ai": True, "human": True, "maxRevisions": 0}
    _, version = catalog.register_flow(
        env["admin"],
        {
            "code": "recover-" + uuid4().hex[:10],
            "name": "原智能体恢复",
            "definition": definition,
        },
    )
    return runtime.start_flow(
        env["user"],
        version,
        {
            "model": "mock",
            "goal": "核对实际资料与局限",
            "inputs": {"source": env["resource"].pk},
            "idempotencyKey": uuid4().hex,
        },
    )


def advance_to_wait(workflow):
    for _ in range(12):
        engine.advance(workflow.pk)
        workflow.refresh_from_db()
        if workflow.status == "waiting_approval":
            return
    pytest.fail(workflow.detail)


def decide(env, workflow, decision, feedback=""):
    return runtime.decide_flow(
        env["user"],
        workflow,
        {
            "nodeId": "summarize",
            "decision": decision,
            "feedback": feedback,
            "revision": state(workflow)["revision"],
            "idempotencyKey": uuid4().hex,
        },
    )


def test_review_exhaustion_waits_for_guidance_and_preserves_executor_and_budgets(
    flows, monkeypatch
):
    env = flows
    calls = install_model(monkeypatch)
    normal = provider.stream
    rejected = []

    def stream(model, messages, maximum, guard, **options):
        packet = json.loads(messages[1]["content"])
        if "nodeContext" not in packet and not rejected:
            rejected.append(True)
            yield json.dumps(
                {
                    "decision": "request_changes",
                    "reason": "需解释资料局限",
                    "issues": [
                        {
                            "code": "LIMIT",
                            "message": "补充适用范围",
                            "evidenceIds": [packet["evidence"][0]["id"]],
                        }
                    ],
                    "repairInstructions": "只修正分析，保留实际资料。",
                    "evidenceIds": [r["id"] for r in packet["evidence"]],
                },
                ensure_ascii=False,
            )
            return
        yield from normal(model, messages, maximum, guard, **options)

    monkeypatch.setattr(provider, "stream", stream)
    with project_scope(env["scope"]):
        workflow = create(env)
        identity = session(workflow)["id"]
        advance_to_wait(workflow)
        item = state(workflow)["nodes"]["summarize"]
        assert item["contextRecovery"]["kind"] == "review_rejected"
        counter = item["toolLoop"]["modelCalls"]
        snapshot = deepcopy(workflow.parameters["_businessFlow"]["definitionSnapshot"])
        count = len(calls)
        engine.advance(workflow.pk)
        assert len(calls) == count  # An exhausted automatic cycle never spins.
        current = decide(
            env, workflow, "retry_context", "单位未提供，明确写为局限，不能猜测。"
        )
        assert state(current)["nodes"]["summarize"]["toolLoop"]["modelCalls"] == counter
        assert state(current)["nodes"]["summarize"]["human"]["status"] == "pending"
        advance_to_wait(current)
        assert state(current)["nodes"]["summarize"]["reviewer"]["decision"] == "accept"
        assert session(current)["id"] == identity
        assert current.parameters["_businessFlow"]["definitionSnapshot"] == snapshot
        assert current.operator_steps == 0
        assert state(current)["nodes"]["summarize"]["toolLoop"]["modelCalls"] > counter
        resumed = [r["packet"] for r in calls if r["packet"].get("recoveryGuidance")]
        assert resumed
        note_id = resumed[0]["recoveryGuidance"]["evidenceId"]
        note = next(row for row in resumed[0]["evidence"] if row["id"] == note_id)
        assert note["result"]["text"].startswith("单位未提供")
        assert (
            "instruction" not in resumed[0]["recoveryGuidance"]
        )  # No duplicated prompt body.
        assert (
            state(current)["recoveryNotes"][note_id]["result"]["source"]
            == "explicit_user"
        )
        reviewer_packets = [
            r["packet"] for r in calls if "nodeContext" not in r["packet"]
        ]
        assert any(
            any(e["id"] == note_id for e in p["evidence"]) for p in reviewer_packets
        )
        assert all(r["executionSession"]["id"] == identity for r in resumed)
        assert not guidance_context(current, "summarize", scope="workflow")
        with pytest.raises(PermissionDenied):
            runtime.decide_flow(env["other"], current, {"decision": "retry_context"})
        decide(env, current, "approve")
        for _ in range(4):
            engine.advance(current.pk)
            current.refresh_from_db()
        assert current.status == "succeeded"


def test_manual_revisions_can_continue_beyond_automatic_limit_without_new_executor(
    flows, monkeypatch
):
    env = flows
    install_model(monkeypatch)
    with project_scope(env["scope"]):
        workflow = create(env)
        identity = session(workflow)["id"]
        advance_to_wait(workflow)
        for index in range(2):
            workflow = decide(
                env,
                workflow,
                "request_changes",
                f"第{index + 1}次人工补充：补充实际资料的适用范围。",
            )
            advance_to_wait(workflow)
            item = state(workflow)["nodes"]["summarize"]
            assert item["attempt"] == index + 2
            assert item["human"]["status"] == "pending"
            assert item["reviewer"]["decision"] == "accept"
            assert session(workflow)["id"] == identity
        assert workflow.operator_steps == 0


def test_task_control_failure_receives_only_task_scoped_human_guidance(
    flows, monkeypatch
):
    env = flows
    calls = install_model(monkeypatch)
    normal = provider.stream
    failed = []

    def once(model, messages, maximum, guard, **options):
        packet = json.loads(messages[1]["content"])
        if (
            packet.get("nodeContext", {}).get("task", {}).get("phase") == "select_node"
            and not failed
        ):
            failed.append(True)
            raise provider.ModelError("模型连接暂时中断")
        yield from normal(model, messages, maximum, guard, **options)

    monkeypatch.setattr(provider, "stream", once)
    with project_scope(env["scope"]):
        workflow = create(env)
        advance_to_wait(workflow)
        recovery = state(workflow)["nodes"]["summarize"]["contextRecovery"]
        assert (
            recovery["kind"] == "model_request_error"
            and recovery["requestScope"] == "workflow"
        )
        workflow = decide(env, workflow, "retry_context", "先选择可执行的分析目标。")
        advance_to_wait(workflow)
        controls = [
            r["packet"]
            for r in calls
            if r["packet"].get("nodeContext", {}).get("task", {}).get("phase")
            == "select_node"
        ]
        assert (
            controls[0]["recoveryGuidance"]["instruction"] == "先选择可执行的分析目标。"
        )
        work = [
            r["packet"]
            for r in calls
            if r["packet"].get("nodeContext", {}).get("task", {}).get("phase") == "work"
        ]
        assert work and all("recoveryGuidance" not in p for p in work)


def test_finishing_request_recovery_does_not_restart_an_approved_node(
    flows, monkeypatch
):
    env = flows
    calls = install_model(monkeypatch)
    normal = provider.stream
    failed = []

    def once(model, messages, maximum, guard, **options):
        packet = json.loads(messages[1]["content"])
        if (
            packet.get("nodeContext", {}).get("task", {}).get("phase")
            == "finish_workflow"
            and not failed
        ):
            failed.append(True)
            raise provider.ModelError("任务结束请求暂时中断")
        yield from normal(model, messages, maximum, guard, **options)

    monkeypatch.setattr(provider, "stream", once)
    with project_scope(env["scope"]):
        workflow = create(env)
        advance_to_wait(workflow)
        workflow = decide(env, workflow, "approve")
        advance_to_wait(workflow)
        item = state(workflow)["nodes"]["summarize"]
        assert item["contextResumeStatus"] == "succeeded"
        assert item["human"]["status"] == "approved"
        before = item["toolLoop"]["modelCalls"]
        workflow = decide(env, workflow, "retry_context", "核对已完成目标后结束任务。")
        for _ in range(4):
            engine.advance(workflow.pk)
            workflow.refresh_from_db()
        assert workflow.status == "succeeded"
        assert state(workflow)["nodes"]["summarize"]["toolLoop"]["modelCalls"] == before


def test_professional_response_validation_exhaustion_waits_instead_of_failing(
    retry_model,
):
    workflow, stage, results = ordinary_stage()
    workflow.workflow_type = "business_flow"
    workflow.parameters = {
        "_businessFlow": {
            "definitionSnapshot": source_summary_definition(main_agent=True),
            "versionId": 1,
        }
    }
    initialize(workflow)
    with pytest.raises(ContextReviewRequired) as waiting:
        run(["invalid-json", "invalid-json"], workflow, stage, results)
    assert waiting.value.details["kind"] == "model_response_error"
    assert waiting.value.details["actor"] == "executor"
    assert len(stage["modelAttempts"]) == 2
    assert not stage.get("decision")


@pytest.mark.parametrize("name", ["adaptive-statistics", "recoverable-analysis"])
def test_reusable_templates_declare_one_executor_and_bounded_recovery(name):
    from apps.business_flows.definitions import normalize_definition

    path = Path(__file__).resolve().parents[3] / f"examples/business-flows/{name}.json"
    definition = normalize_definition(json.loads(path.read_text()))
    assert definition["executionMode"] == "main_agent"
    assert len(definition["skill"]["instructions"]) <= 600
