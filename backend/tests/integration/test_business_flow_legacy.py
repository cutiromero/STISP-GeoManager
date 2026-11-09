"""Actual independent reviewer requests preserve the established geology approvals."""

from copy import deepcopy
import json
from unittest.mock import Mock
from uuid import uuid4

import pytest

from apps.agent import business_flow_review as review
from apps.agent.models import AgentRun, AgentWorkflow, RunEvent
from apps.agent.policy import default_policy
from apps.business_flows import catalog, legacy
from apps.business_flows.builtins import builtin_flows
from apps.business_flows.state import digest, emit, initial_state, state
from apps.compute.packages import ComputeError
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401

# ruff: noqa: F811


@pytest.fixture
def legacy_flow(setup_agent, monkeypatch):
    env = setup_agent
    monkeypatch.setattr(review.provider, "model_window", lambda model: 32768)
    monkeypatch.setattr("apps.agent.context.count_tokens", lambda *args: 123)

    def create(*, max_revisions=1):
        declaration = deepcopy(builtin_flows()[0])
        for node in declaration["definition"]["nodes"]:
            if node["id"] in {"apply", "finish"}:
                node["review"]["maxRevisions"] = max_revisions
        with project_scope(env["scope"]):
            flow, version = catalog.register_flow(env["admin"], declaration)
            plan = {
                "phase": "review_modifications",
                "stageIndex": 0,
                "stages": [
                    {
                        "name": "apply",
                        "identifier": "geology-multi-apply",
                        "decision": {
                            "judgement": "初始建议",
                            "resultSummary": "8项真实问题",
                        },
                    }
                ],
                "fieldMappingReview": {"proposal": {"lithology": {"name": "岩性名称"}}},
            }
            workflow = AgentWorkflow.objects.create(
                owner=env["user"],
                model="mock",
                workflow_type="geology_generic",
                goal="实际地质资料检查",
                status="running",
                current_step="apply",
                idempotency_key=uuid4().hex,
                plan=plan,
                plan_hash=digest(plan),
                max_iterations=20,
            )
            run = AgentRun.objects.create(
                owner=env["user"],
                conversation=env["conversation"],
                model="mock",
                prompt=workflow.goal,
                status="waiting_compute",
                research_workflow=workflow,
                idempotency_key=uuid4().hex,
                knowledge_selection={
                    "mode": "none",
                    "domains": [],
                    "_contextRunIds": [],
                },
            )
            workflow.parameters = {
                "_businessFlow": {
                    "flowId": flow.pk,
                    "versionId": version.pk,
                    "name": flow.name,
                    "definitionSnapshot": deepcopy(version.definition),
                    "definitionHash": version.definition_hash,
                    "inputVersions": {},
                    "conversationId": env["conversation"].pk,
                    "runId": run.pk,
                    "reviewerModel": "mock",
                    "revision": 0,
                }
            }
            workflow.parameters["_businessFlow"]["state"] = initial_state(
                version.definition
            )
            workflow.save(update_fields=["parameters"])
        return workflow

    return {**env, "create": create}


def verdict(accept=True):
    return {
        "decision": "accept" if accept else "request_changes",
        "reason": "实际结果支持结论" if accept else "建议遗漏了例外边界",
        "issues": []
        if accept
        else [
            {
                "code": "missing_exception",
                "message": "说明哪些对象仍需人工裁定",
                "evidenceIds": ["node-result"],
            }
        ],
        "repairInstructions": ""
        if accept
        else "补充例外对象，保留人工批准范围后重新提交。",
        "evidenceIds": ["node-result"],
    }


def provider_sequence(monkeypatch, values):
    calls = []

    def streamed(model, messages, maximum, guard, **options):
        guard()
        packet = json.loads(messages[1]["content"])
        calls.append(
            {"messages": deepcopy(messages), "packet": packet, "options": options}
        )
        current = values[min(len(calls) - 1, len(values) - 1)]
        yield json.dumps(current, ensure_ascii=False)

    monkeypatch.setattr(review.provider, "stream", streamed)
    return calls


def review_stage(env, workflow, stage, initial, producer):
    with project_scope(env["scope"]):
        return legacy.review_decision(
            workflow,
            env["user"],
            default_policy(),
            stage,
            [{"counts": {"actualIssues": 8}, "source": "真实检查结果"}],
            initial,
            lambda: None,
            producer,
        )


def assert_no_human_approval(workflow):
    assert "modificationsApproval" not in json.dumps(workflow.plan)
    assert "fieldMappingConfirm" not in json.dumps(workflow.plan)
    assert not workflow.plan.get("confirmedMapping")
    assert state(workflow)["nodes"]["inputs"]["human"]["status"] == "pending"
    assert state(workflow)["nodes"]["apply"]["human"]["status"] == "pending"


def test_unbound_professional_workflow_never_calls_new_reviewer(
    legacy_flow, monkeypatch
):
    env = legacy_flow
    workflow = env["create"]()
    workflow.parameters = {}
    workflow.save(update_fields=["parameters"])
    calls = provider_sequence(monkeypatch, [verdict()])
    producer = Mock()
    initial = ({"judgement": "原执行结果"}, [])
    old_plan = deepcopy(workflow.plan)
    assert review_stage(env, workflow, {"name": "apply"}, initial, producer) is initial
    assert not calls
    producer.assert_not_called()
    workflow.refresh_from_db()
    assert workflow.plan == old_plan and workflow.parameters == {}


@pytest.mark.parametrize(
    "name,identifier,node_id",
    [("apply", "geology-multi-apply", "apply"), ("final_analysis", "finish", "finish")],
)
def test_real_independent_review_accepts_decisions_without_approving_people(
    legacy_flow, monkeypatch, name, identifier, node_id
):
    env = legacy_flow
    workflow = env["create"]()
    calls = provider_sequence(monkeypatch, [verdict()])
    producer = Mock()
    initial = (
        {"judgement": "8项问题均有实际依据", "resultSummary": "真实检查支持当前建议"},
        [],
    )
    previous_hash = workflow.plan_hash
    previous_plan = deepcopy(workflow.plan)
    result = review_stage(
        env, workflow, {"name": name, "identifier": identifier}, initial, producer
    )
    assert result is initial and len(calls) == 1
    producer.assert_not_called()
    assert calls[0]["packet"]["node"]["id"] == node_id
    assert [message["role"] for message in calls[0]["messages"]] == ["system", "user"]
    assert "tools" not in calls[0]["options"]
    assert calls[0]["packet"]["evidence"][0]["result"]["actualResults"][0][
        "counts"
    ] == {"actualIssues": 8}
    workflow.refresh_from_db()
    assert workflow.plan == previous_plan and workflow.plan_hash == previous_hash
    assert state(workflow)["nodes"][node_id]["reviewer"]["status"] == "passed"
    assert len(state(workflow)["nodes"][node_id]["attempts"]) == 1
    assert_no_human_approval(workflow)


def test_rejection_reaches_original_producer_and_is_reviewed_again(
    legacy_flow, monkeypatch
):
    env = legacy_flow
    workflow = env["create"]()
    calls = provider_sequence(monkeypatch, [verdict(False), verdict(True)])
    stage = workflow.plan["stages"][0]
    stage["modelAttempts"] = [
        {"requestSha256": "old-generation", "status": "accepted", "accepted": True}
    ]
    stage["modelBatches"] = [{"legacy": "old batch"}]
    initial = ({"judgement": "初始结果", "resultSummary": "尚未说明例外"}, [])
    repaired = (
        {"judgement": "修订结果", "resultSummary": "明确保留例外对象，等待人工批准"},
        [],
    )
    received = []

    def produce():
        received.append(deepcopy(stage["businessFlowFeedback"]))
        assert "modelAttempts" not in stage and "modelBatches" not in stage
        return repaired

    result = review_stage(env, workflow, stage, initial, produce)
    assert result is repaired and len(calls) == 2 and len(received) == 1
    assert received[0]["reason"] == verdict(False)["reason"]
    assert received[0]["repairInstructions"] == verdict(False)["repairInstructions"]
    assert received[0]["issues"][0]["code"] == "missing_exception"
    assert (
        calls[1]["packet"]["evidence"][0]["result"]["decision"]["judgement"]
        == "修订结果"
    )
    workflow.refresh_from_db()
    item = state(workflow)["nodes"]["apply"]
    assert item["attempt"] == 2 and item["reviewer"]["status"] == "passed"
    assert [event["kind"] for event in state(workflow)["events"]].count(
        "review_rejected"
    ) == 1
    assert [event["kind"] for event in state(workflow)["events"]].count(
        "revision_requested"
    ) == 1
    assert len(item["attempts"]) == 2
    assert_no_human_approval(workflow)


@pytest.mark.parametrize("maximum", [0, 1])
def test_professional_review_stops_at_published_repair_limit(
    legacy_flow, monkeypatch, maximum
):
    env = legacy_flow
    workflow = env["create"](max_revisions=maximum)
    calls = provider_sequence(monkeypatch, [verdict(False)])
    initial = ({"judgement": "保留当前真实结果", "resultSummary": "待修订"}, [])
    producer = Mock(return_value=initial)
    with pytest.raises(ComputeError, match="返修上限"):
        review_stage(env, workflow, {"name": "apply"}, initial, producer)
    assert len(calls) == maximum + 1 and producer.call_count == maximum
    workflow.refresh_from_db()
    assert state(workflow)["nodes"]["apply"]["reviewer"]["status"] == "rejected"
    assert_no_human_approval(workflow)


def test_no_ai_gate_is_executed_for_fixed_operator_or_input_nodes(
    legacy_flow, monkeypatch
):
    env = legacy_flow
    workflow = env["create"]()
    calls = provider_sequence(monkeypatch, [verdict()])
    producer = Mock()
    initial = ({"judgement": "实际算子结果"}, [])
    for identity in ["inputs", "check", "recheck", "relations", "prospect"]:
        assert (
            review_stage(env, workflow, {"name": identity}, initial, producer)
            is initial
        )
    assert not calls
    producer.assert_not_called()


def test_emit_and_projection_keep_legacy_approval_plan_and_hash_unchanged(legacy_flow):
    env = legacy_flow
    workflow = env["create"]()
    original = deepcopy(workflow.plan)
    original_hash = workflow.plan_hash
    with project_scope(env["scope"]):
        emit(workflow, "system", "inputs", "progress", "更新业务流可视状态")
        legacy.synchronize(workflow.pk)
        workflow.refresh_from_db()
        projection = legacy.projected_state(workflow)
    assert workflow.plan == original and workflow.plan_hash == original_hash
    assert "businessFlow" not in workflow.plan
    assert workflow.parameters["_businessFlow"]["state"]["revision"] >= 2
    assert projection["nodes"]["inputs"]["human"]["required"] is True
    assert projection["nodes"]["apply"]["human"]["required"] is True
    assert projection["nodes"]["check"]["reviewer"]["status"] == "not_required"
    assert (
        RunEvent.objects.filter(
            run_id=workflow.parameters["_businessFlow"]["runId"],
            kind="business_flow_state",
        ).count()
        == 2
    )


@pytest.mark.parametrize(
    "actual,expected",
    [
        ("review_mapping", "inputs"),
        ("review_plan", "inputs"),
        ("build_inputs", "inputs"),
        ("review_modifications", "apply"),
        ("final_analysis", "finish"),
        ("check", "check"),
        ("apply", "apply"),
    ],
)
def test_legacy_serialization_highlights_the_actual_canonical_node(
    legacy_flow, actual, expected
):
    from apps.business_flows.runtime import serialize_run

    env = legacy_flow
    workflow = env["create"]()
    workflow.current_step = actual
    workflow.save(update_fields=["current_step"])
    with project_scope(env["scope"]):
        result = serialize_run(env["user"], workflow)
    assert result["currentNode"] == expected
    workflow.refresh_from_db()
    assert workflow.current_step == actual


def test_accepted_legacy_candidate_is_not_reviewed_again_on_worker_reentry(
    legacy_flow, monkeypatch
):
    env = legacy_flow
    workflow = env["create"]()
    calls = provider_sequence(monkeypatch, [verdict(True)])
    initial = (
        {"judgement": "已核查的相同建议", "resultSummary": "当前实际证据支持建议"},
        [],
    )
    producer = Mock()
    first = review_stage(env, workflow, {"name": "apply"}, initial, producer)
    workflow.refresh_from_db()
    second = review_stage(env, workflow, {"name": "apply"}, deepcopy(initial), producer)
    assert first == second == initial
    assert len(calls) == 1
    producer.assert_not_called()
    workflow.refresh_from_db()
    assert state(workflow)["nodes"]["apply"]["attempt"] == 1
    assert len(state(workflow)["nodes"]["apply"]["attempts"]) == 1
    assert_no_human_approval(workflow)


def test_exhausted_legacy_rejection_is_not_reset_by_worker_reentry(
    legacy_flow, monkeypatch
):
    env = legacy_flow
    workflow = env["create"](max_revisions=0)
    calls = provider_sequence(monkeypatch, [verdict(False)])
    initial = ({"judgement": "未通过的相同建议", "resultSummary": "保留实际结果"}, [])
    producer = Mock()
    for _ in range(2):
        with pytest.raises(ComputeError, match="返修上限"):
            review_stage(env, workflow, {"name": "apply"}, deepcopy(initial), producer)
        workflow.refresh_from_db()
    assert len(calls) == 1
    producer.assert_not_called()
    assert state(workflow)["nodes"]["apply"]["attempt"] == 1
    assert_no_human_approval(workflow)


@pytest.mark.parametrize("producer_already_finished", [False, True])
def test_recovered_legacy_rejection_only_uses_remaining_revision_budget(
    legacy_flow, monkeypatch, producer_already_finished
):
    class InterruptedWorker(BaseException):
        pass

    env = legacy_flow
    workflow = env["create"](max_revisions=1)
    calls = provider_sequence(monkeypatch, [verdict(False)])
    initial = ({"judgement": "初版建议", "resultSummary": "尚待修订"}, [])
    interrupted = Mock(side_effect=InterruptedWorker())
    with pytest.raises(InterruptedWorker):
        review_stage(env, workflow, workflow.plan["stages"][0], initial, interrupted)
    workflow.refresh_from_db()
    assert state(workflow)["nodes"]["apply"]["attempt"] == 1
    repaired = (
        {"judgement": "返修后实际建议", "resultSummary": "修订后仍需核查的建议"},
        [],
    )
    producer = Mock(return_value=repaired)
    resumed_initial = repaired if producer_already_finished else initial
    with pytest.raises(ComputeError, match="返修上限"):
        review_stage(
            env, workflow, workflow.plan["stages"][0], resumed_initial, producer
        )
    workflow.refresh_from_db()
    assert len(calls) == 2
    assert producer.call_count == (0 if producer_already_finished else 1)
    assert state(workflow)["nodes"]["apply"]["attempt"] == 2
    assert state(workflow)["nodes"]["apply"]["reviewer"]["status"] == "rejected"
    assert_no_human_approval(workflow)
