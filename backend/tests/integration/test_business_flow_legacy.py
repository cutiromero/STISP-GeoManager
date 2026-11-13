"""Actual independent reviewer requests preserve the established geology approvals."""

from copy import deepcopy
import json
from unittest.mock import Mock
from uuid import uuid4

import pytest

from apps.agent import business_flow_review as review
from apps.agent.business_flow_context import ContextReviewRequired
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
            [
                {
                    "outputId": 17,
                    "taskId": "fixture-check",
                    "key": "statistics",
                    "kind": "table",
                    "checksum": "fixture-source",
                    "rows": [{"actualIssues": 8}],
                    "rowCount": 1,
                    "counts": {"actualIssues": 8},
                    "source": "真实检查结果",
                }
            ],
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


def test_wrong_review_reference_is_diagnosed_without_rerunning_the_producer(
    legacy_flow, monkeypatch
):
    env = legacy_flow
    workflow = env["create"]()
    stage = workflow.plan["stages"][0]
    invalid = {**verdict(), "evidenceIds": ["output-17"]}
    calls = provider_sequence(monkeypatch, [invalid, verdict()])
    producer = Mock()
    initial = (stage["decision"], [])
    result = review_stage(env, workflow, stage, initial, producer)
    assert result is initial and len(calls) == 2
    producer.assert_not_called()
    feedback = calls[1]["packet"]["revisionFeedback"]
    assert feedback["availableEvidenceIds"] == ["node-result"]
    assert feedback["requiredEvidenceIds"] == ["node-result"]
    assert "引用" in feedback["diagnostic"]
    assert calls[0]["packet"]["evidence"] == calls[1]["packet"]["evidence"]
    assert_no_human_approval(workflow)


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
    with pytest.raises(ContextReviewRequired, match="例外|建议"):
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


def test_public_actor_omits_private_structured_decision_without_changing_saved_evidence(
    legacy_flow,
):
    from apps.business_flows import runtime

    env = legacy_flow
    workflow = env["create"]()
    private = {"judgement": "完整判断", "resultSummary": "实际结果"}
    state(workflow)["nodes"]["apply"]["executor"]["decision"] = deepcopy(private)
    with project_scope(env["scope"]):
        output = runtime.serialize_run(env["user"], workflow)
    actor = next(node for node in output["nodes"] if node["nodeId"] == "apply")[
        "executor"
    ]
    assert "decision" not in actor
    assert state(workflow)["nodes"]["apply"]["executor"]["decision"] == private


def test_independent_review_keeps_counts_and_source_digest_without_coordinate_transport():
    rows = [
        {
            "feature_id": str(i),
            "rule_id": "R1",
            "status": "repairable",
            "value": i,
            "geometry_json": json.dumps(
                {"type": "Polygon", "coordinates": [[[j, j] for j in range(5000)]]}
            ),
        }
        for i in range(20)
    ]
    original = deepcopy(rows)
    packet = legacy.compact_review_packet(
        {"judgement": "需按实际对象核对"},
        rows,
        [
            {
                "outputId": 7,
                "taskId": "owned",
                "key": "issues",
                "checksum": "source-sha",
                "rows": rows,
            }
        ],
    )
    assert len(json.dumps(packet).encode()) < 20000
    assert packet["proposal"]["rowCount"] == 20
    assert packet["proposal"]["rowsDigest"] == digest(rows)
    assert packet["proposal"]["geometryStoredInOriginal"] is True
    assert sum(group["count"] for group in packet["proposal"]["groups"]) == 20
    assert packet["actualResults"][0]["checksum"] == "source-sha"
    assert packet["actualResults"][0]["rows"]["sampleRows"][3]["value"] == 3
    assert rows == original


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
        with pytest.raises(ContextReviewRequired, match="例外|建议"):
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
    with pytest.raises(ContextReviewRequired, match="例外|建议"):
        review_stage(
            env, workflow, workflow.plan["stages"][0], resumed_initial, producer
        )
    workflow.refresh_from_db()
    assert len(calls) == 2
    assert producer.call_count == (0 if producer_already_finished else 1)
    assert state(workflow)["nodes"]["apply"]["attempt"] == 2
    assert state(workflow)["nodes"]["apply"]["reviewer"]["status"] == "rejected"
    assert_no_human_approval(workflow)


@pytest.mark.efficiency
def test_final_review_uses_complete_report_facts_quality_and_frozen_approval_scope(
    legacy_flow,
):
    env = legacy_flow
    workflow = env["create"]()
    quality = {
        "status": "needs_review",
        "issues": ["待专家复核"],
        "metrics": {"count": 20},
    }

    def output(identity, task, key, rows):
        return {
            "outputId": identity,
            "taskId": task,
            "key": key,
            "kind": "table",
            "checksum": f"sha-{identity}",
            "rows": rows,
            "rowCount": len(rows),
            "scope": "all",
            "metadata": {"qualityCheck": deepcopy(quality)},
        }

    initial = output(
        1,
        "check-task",
        "issues",
        [
            {
                "element": "lithology",
                "rule_id": "R1",
                "status": "suggested",
                "feature_id": str(i),
            }
            for i in range(20)
        ],
    )
    changes = output(
        2,
        "apply-task",
        "changes",
        [
            {
                "element": "lithology",
                "rule_id": "R1",
                "action": "downweight",
                "actual_changed": "1",
            }
            for _ in range(11)
        ],
    )
    recheck = output(
        3,
        "recheck-task",
        "issues",
        [
            {"rule_id": "R1", "status": "retained", "feature_id": str(i)}
            for i in range(9)
        ],
    )
    workflow.plan["stages"] = [
        {"name": "check", "taskId": "check-task", "results": [initial]},
        {"name": "apply", "taskId": "apply-task", "results": [changes]},
        {"name": "recheck", "taskId": "recheck-task", "results": [recheck]},
    ]
    workflow.plan["modificationReview"] = {
        "proposalHash": "frozen-proposal",
        "approvedSuggestionIds": ["selected"],
        "suggestions": [
            {
                "id": "selected",
                "element": "lithology",
                "ruleId": "R1",
                "action": "downweight",
                "featureId": "object-1",
                "status": "suggested",
                "ruleRefs": [],
                "observations": {},
            }
        ],
    }
    results = [initial, changes, recheck]
    originals = deepcopy((workflow.plan, workflow.evidence, results))
    signature = digest(
        {"decision": {"judgement": "保留待复核项"}, "edits": [], "evidence": results}
    )
    packet = legacy.compact_review_packet(
        {"judgement": "保留待复核项"},
        [],
        results,
        workflow=workflow,
        node_id="finish",
        candidate_digest=signature,
    )
    facts = packet["verifiedReportFacts"]
    assert facts["initialIssueCount"] == 20
    assert facts["initialIssuesByElement"] == {"lithology": 20}
    assert facts["recheckRemainingIssueCount"] == 9
    assert facts["executedDispositionCount"] == 11
    assert facts["executedActions"]["downweight"] == 11
    assert packet["modificationReview"]["approvedCount"] == 1
    assert packet["modificationReview"]["proposalHash"] == "frozen-proposal"
    assert all(
        item["qualityCheck"]["status"] == "needs_review"
        for item in packet["qualityEvidence"]
    )
    assert packet["candidateDigest"] == signature
    assert (workflow.plan, workflow.evidence, results) == originals
    assert len(json.dumps(packet).encode()) < 20000


def test_professional_review_budget_wait_retries_without_approving_science(
    legacy_flow, monkeypatch
):
    from apps.agent.business_flow_context import ContextReviewRequired
    from apps.agent.demo_workflow import _pause
    from apps.business_flows import runtime

    env = legacy_flow
    workflow = env["create"]()
    stage = workflow.plan["stages"][0]
    calls = provider_sequence(monkeypatch, [verdict()])
    monkeypatch.setattr("apps.agent.context.count_tokens", lambda *args: 50000)
    with project_scope(env["scope"]):
        with pytest.raises(ContextReviewRequired) as waiting:
            review_stage(env, workflow, stage, (stage["decision"], []), Mock())
        assert not calls
        stage["contextBudgetReview"] = waiting.value.details
        _pause(workflow, stage, str(waiting.value))
        legacy.synchronize(workflow.pk)
        workflow.refresh_from_db()
        public = runtime.serialize_run(env["user"], workflow)
        item = next(row for row in public["nodes"] if row["nodeId"] == "apply")
        assert item["status"] == "waiting_context"
        assert (
            item["contextRecovery"]["afterTokens"]
            > item["contextRecovery"]["inputBudgetTokens"]
        )
        assert workflow.steps.filter(
            kind="workflow_diagnostic", error_code="budget"
        ).exists()
        value = {
            "nodeId": "apply",
            "decision": "retry_context",
            "revision": state(workflow)["revision"],
            "idempotencyKey": uuid4().hex,
        }
        with pytest.raises(ComputeError, match="不能跳过"):
            runtime.decide_flow(
                env["user"], workflow, {**value, "skipEvidenceIds": ["node-result"]}
            )
        current = runtime.decide_flow(env["user"], workflow, value)
        assert current.status == "queued"
        assert not stage.get("modificationsApproval")
        assert state(current)["nodes"]["apply"]["human"]["status"] == "pending"
        assert runtime.decide_flow(env["user"], current, value).pk == current.pk


def test_professional_review_protocol_wait_preserves_results_and_retries_only_review(
    legacy_flow, monkeypatch
):
    from apps.agent.business_flow_context import ContextReviewRequired
    from apps.agent.demo_workflow import _pause
    from apps.business_flows import runtime

    env = legacy_flow
    workflow = env["create"]()
    stage = workflow.plan["stages"][0]
    producer = Mock()

    def no_body(*args, **kwargs):
        yield from ()

    monkeypatch.setattr(review.provider, "stream", no_body)
    with project_scope(env["scope"]):
        with pytest.raises(ContextReviewRequired) as waiting:
            review_stage(env, workflow, stage, (stage["decision"], []), producer)
        assert waiting.value.details["kind"] == "model_protocol_error"
        stage["contextBudgetReview"] = waiting.value.details
        _pause(workflow, stage, str(waiting.value))
        legacy.synchronize(workflow.pk)
        workflow.refresh_from_db()
        assert workflow.steps.filter(
            kind="workflow_diagnostic", error_code="model_protocol"
        ).exists()
        current = runtime.decide_flow(
            env["user"],
            workflow,
            {
                "nodeId": "apply",
                "decision": "retry_context",
                "revision": state(workflow)["revision"],
                "idempotencyKey": uuid4().hex,
            },
        )
        provider_sequence(monkeypatch, [verdict()])
        actual = current.plan["stages"][0]
        assert (
            review_stage(env, current, actual, (actual["decision"], []), producer)[0]
            == actual["decision"]
        )
        producer.assert_not_called()
        assert not actual.get("modificationsApproval")


def final_protocol_wait(env, status, *, duplicate=False):
    workflow = env["create"]()
    for row in workflow.plan["stages"]:
        row["status"] = "completed"
    workflow.plan["stageIndex"] = len(workflow.plan["stages"])
    final = {
        "name": "final_analysis",
        "identifier": "finish",
        "status": "needs_review",
        "contextBudgetReview": {
            "kind": "model_protocol_error",
            "nodeId": "finish",
            "level": 0,
            "evidence": [],
            "reason": "审核引用需修正",
        },
        "modelAttempts": [
            {"accepted": True, "response": '{"decision":{"findings":["已保存分析"]}}'}
        ],
        "modelRequestPayload": {
            "goal": workflow.goal,
            "executionState": {"currentStage": {"planStatus": None}},
        },
    }
    workflow.plan.update(
        finalStage=final, phase="review_results", actualModelCallCount=2
    )
    if duplicate:
        copied = deepcopy(final)
        copied.pop("contextBudgetReview")
        copied["status"] = "pending"
        copied["modelBudgetHistory"] = [{"previousRetry": "保留原恢复审计"}]
        workflow.plan["stages"].append(copied)
    workflow.status, workflow.current_step = status, "final_analysis"
    workflow.save(update_fields=["plan", "status", "current_step"])
    return workflow


@pytest.mark.parametrize(
    "status,history_only",
    [("waiting_approval", False), ("failed", False), ("failed", True)],
)
@pytest.mark.parametrize("duplicate", [False, True])
def test_final_review_resumes_through_public_decision_without_reexecuting_science(
    legacy_flow, status, duplicate, history_only
):
    from apps.business_flows import runtime

    env = legacy_flow
    workflow = final_protocol_wait(env, status, duplicate=duplicate)
    if history_only:
        final = workflow.plan["finalStage"]
        final.setdefault("modelBudgetHistory", []).append(
            {"contextBudgetReview": final.pop("contextBudgetReview")}
        )
        workflow.save(update_fields=["plan"])
    scientific = deepcopy(workflow.plan["stages"][: workflow.plan["stageIndex"]])
    human = deepcopy(state(workflow)["nodes"]["apply"]["human"])
    with project_scope(env["scope"]):
        public = runtime.serialize_run(env["user"], workflow)
        node = next(row for row in public["nodes"] if row["nodeId"] == "finish")
        assert public["status"] == status and node["status"] == "waiting_context"
        current = runtime.decide_flow(
            env["user"],
            workflow,
            {
                "nodeId": "finish",
                "decision": "retry_context",
                "revision": public["revision"],
                "idempotencyKey": uuid4().hex,
            },
        )
        assert current.status == "queued"
        assert current.plan["stages"] == scientific
        assert current.plan["actualModelCallCount"] == 2
        assert current.plan["finalStage"]["modelAttempts"][-1]["accepted"] is True
        assert current.plan["finalStage"].get("status") is None
        assert not current.plan["finalStage"].get("contextBudgetReview")
        if duplicate:
            assert {"previousRetry": "保留原恢复审计"} in current.plan["finalStage"][
                "modelBudgetHistory"
            ]
        assert state(current)["nodes"]["apply"]["human"] == human
        assert not current.steps.filter(kind="submit_operator").exists()


@pytest.mark.parametrize("conflict", ["request", "response"])
def test_conflicting_final_stage_copies_are_not_silently_merged(legacy_flow, conflict):
    from apps.business_flows import runtime

    env = legacy_flow
    workflow = final_protocol_wait(env, "failed", duplicate=True)
    if conflict == "request":
        workflow.plan["stages"][-1]["modelRequestPayload"]["goal"] = "另一任务的请求"
    else:
        workflow.plan["stages"][-1]["modelAttempts"][-1]["response"] = "另一份分析"
    workflow.save(update_fields=["plan"])
    original = deepcopy(workflow.plan)
    with (
        project_scope(env["scope"]),
        pytest.raises(ComputeError, match="保存请求不一致"),
    ):
        runtime.decide_flow(
            env["user"],
            workflow,
            {
                "nodeId": "finish",
                "decision": "retry_context",
                "revision": state(workflow)["revision"],
                "idempotencyKey": uuid4().hex,
            },
        )
    workflow.refresh_from_db()
    assert workflow.status == "failed" and workflow.plan == original


def test_failed_review_without_an_accepted_response_has_no_recovery_bypass(legacy_flow):
    from apps.business_flows import runtime

    env = legacy_flow
    workflow = final_protocol_wait(env, "failed")
    workflow.plan["finalStage"]["modelAttempts"][-1]["accepted"] = False
    workflow.save(update_fields=["plan"])
    with project_scope(env["scope"]), pytest.raises(ComputeError):
        runtime.decide_flow(
            env["user"],
            workflow,
            {
                "nodeId": "finish",
                "decision": "retry_context",
                "revision": state(workflow)["revision"],
                "idempotencyKey": uuid4().hex,
            },
        )
    workflow.refresh_from_db()
    assert workflow.status == "failed"


def test_reference_tail_rejection_can_be_rechecked_via_public_decision(legacy_flow):
    from apps.business_flows import runtime

    env = legacy_flow
    workflow = final_protocol_wait(env, "failed")
    final = workflow.plan["finalStage"]
    final.pop("contextBudgetReview")
    final["modelRequestPayload"]["executionState"]["currentRun"] = {
        "latestStatisticsOutputIds": [999]
    }
    final["modelAttempts"][-1].update(
        accepted=False,
        status="rejected",
        truncated=False,
        validationError="判断必须引用最近一次实际计算统计",
        response=json.dumps(
            {
                "decision": {
                    "evidenceRefs": [
                        {"kind": "knowledge", "id": str(index)} for index in range(31)
                    ]
                    + [{"kind": "output", "id": "999"}]
                }
            }
        ),
    )
    workflow.save(update_fields=["plan"])
    audit = deepcopy(final["modelAttempts"])
    before = deepcopy(workflow.plan["stages"])
    with project_scope(env["scope"]):
        public = runtime.serialize_run(env["user"], workflow)
        node = next(row for row in public["nodes"] if row["nodeId"] == "finish")
        assert node["status"] == "waiting_context"
        current = runtime.decide_flow(
            env["user"],
            workflow,
            {
                "nodeId": "finish",
                "decision": "retry_context",
                "revision": public["revision"],
                "idempotencyKey": uuid4().hex,
            },
        )
    assert current.status == "queued"
    assert current.plan["stages"] == before
    assert current.plan["finalStage"]["modelAttempts"] == audit
    assert current.plan["actualModelCallCount"] == 2
    assert current.plan["finalStage"].get("status") is None


@pytest.mark.parametrize(
    "blocked", ["cancel", "response", "decision", "running", "newer_diagnostic"]
)
def test_historical_review_diagnostic_does_not_reopen_other_states(
    legacy_flow, blocked
):
    from apps.business_flows import runtime

    env = legacy_flow
    workflow = final_protocol_wait(env, "failed")
    final = workflow.plan["finalStage"]
    final["modelBudgetHistory"] = [
        {"contextBudgetReview": final.pop("contextBudgetReview")}
    ]
    if blocked == "cancel":
        workflow.cancel_requested = True
    elif blocked == "response":
        final["modelAttempts"][-1]["response"] = ""
    elif blocked == "decision":
        final["decision"] = {"judgement": "审核已完成"}
    elif blocked == "newer_diagnostic":
        final["modelBudgetHistory"].append(
            {"contextBudgetReview": {"kind": "input_window"}}
        )
    else:
        workflow.status = "running"
    workflow.save(update_fields=["plan", "status", "cancel_requested"])
    with project_scope(env["scope"]):
        public = runtime.serialize_run(env["user"], workflow)
        node = next(row for row in public["nodes"] if row["nodeId"] == "finish")
        assert not node.get("contextRecovery")
        with pytest.raises(ComputeError):
            runtime.decide_flow(
                env["user"],
                workflow,
                {
                    "nodeId": "finish",
                    "decision": "retry_context",
                    "revision": public["revision"],
                    "idempotencyKey": uuid4().hex,
                },
            )


@pytest.mark.parametrize("direct_error", [False, True])
def test_compute_failure_waits_and_retries_original_scientific_stage(
    legacy_flow, direct_error
):
    from apps.business_flows import runtime
    from apps.compute.models import AlgorithmResource, AlgorithmVersion, ComputeTask

    env = legacy_flow
    workflow = env["create"]()
    with project_scope(env["scope"]):
        algorithm = AlgorithmResource.objects.create(
            identifier="legacy-recovery-check",
            name="原科学算子",
            created_by=env["admin"],
        )
        version = AlgorithmVersion.objects.create(
            algorithm=algorithm,
            version="1.0.0",
            manifest={},
            checksum="a" * 64,
            package_path="unused-test.zip",
            status="published",
        )
        task = ComputeTask.objects.create(
            name="原阶段失败任务",
            owner=env["user"],
            version=version,
            status="failed",
            error="输入资料不适用",
            failure={"code": "BAD_DATA", "remedy": "replace_data"},
            idempotency_key=uuid4().hex,
        )
        workflow.plan["stages"][0]["taskId"] = str(task.pk)
        workflow.status, workflow.detail = (
            "running" if direct_error else "failed",
            "本步计算未成功：输入资料不适用",
        )
        workflow.save(update_fields=["plan", "status", "detail"])
        scientific = deepcopy(workflow.plan)
        if direct_error:
            from apps.business_flows.failure_handoff import handoff_exception

            handoff_exception(workflow, ComputeError(workflow.detail))
        legacy.synchronize(workflow.pk)
        workflow.refresh_from_db()
        public = runtime.serialize_run(env["user"], workflow)
        item = next(row for row in public["nodes"] if row["nodeId"] == "apply")
        assert (
            workflow.status == "waiting_approval"
            and item["status"] == "waiting_recovery"
        )
        assert workflow.plan == scientific
        payload = {
            "nodeId": "apply",
            "revision": state(workflow)["revision"],
            "decision": "retry_recovery",
            "feedback": "重试原科学阶段",
            "idempotencyKey": uuid4().hex,
        }
        with pytest.raises(ComputeError, match="原审核链路"):
            runtime.decide_flow(
                env["user"], workflow, {**payload, "recoveryInputs": {"lithology": 9}}
            )
        with pytest.raises(ComputeError, match="不可跳过"):
            runtime.decide_flow(
                env["user"], workflow, {**payload, "decision": "skip_node"}
            )
        current = runtime.decide_flow(env["user"], workflow, payload)
        assert (
            current.status == "queued"
            and current.plan["stageIndex"] == scientific["stageIndex"]
        )
        assert (
            current.plan["stages"][0]["decision"] == scientific["stages"][0]["decision"]
        )
        assert current.plan["phase"] == scientific["phase"]
        assert not current.plan["stages"][0].get("taskId")
        assert state(current)["nodes"]["apply"]["human"]["status"] != "approved"
        assert runtime.decide_flow(env["user"], current, payload).pk == current.pk


@pytest.mark.parametrize(
    "kind", ["input_window", "operator_call_limit", "model_protocol_error"]
)
def test_initial_input_wait_resumes_without_a_scientific_stage(
    legacy_flow, monkeypatch, kind
):
    from apps.agent import demo_workflow
    from apps.agent.business_flow_context import ContextReviewRequired
    from apps.agent.models import AgentPolicy
    from apps.business_flows import runtime

    env = legacy_flow
    workflow = env["create"]()
    workflow.plan.update(phase="prepare", stages=[], actualModelCallCount=2)
    workflow.current_step = "prepare"
    workflow.operator_steps = workflow.max_operator_steps = 16
    workflow.execute_operators = False
    workflow.save(
        update_fields=[
            "plan",
            "current_step",
            "operator_steps",
            "max_operator_steps",
            "execute_operators",
        ]
    )

    def prepare(*args):
        raise ContextReviewRequired(
            {
                "nodeId": "inputs",
                "kind": kind,
                "level": 0,
                "evidence": [],
                "budgetScope": "task",
                "reason": "输入准备需要调整允许额度",
                **(
                    {"usedOperatorCalls": 16, "limit": 16}
                    if kind == "operator_call_limit"
                    else {}
                ),
            }
        )

    monkeypatch.setattr(demo_workflow, "prepare_demo", prepare)
    demo_workflow.advance_demo(workflow.pk)
    workflow.refresh_from_db()
    with project_scope(env["scope"]):
        public = runtime.serialize_run(env["user"], workflow)
        assert (
            workflow.status == "waiting_approval" and public["currentNode"] == "inputs"
        )
        inputs = next(row for row in public["nodes"] if row["nodeId"] == "inputs")
        assert (
            inputs["status"] == "waiting_context"
            and inputs["contextRecovery"]["kind"] == kind
        )
        assert inputs["contextRecovery"]["reason"][:100] in workflow.detail
        if kind == "operator_call_limit":
            assert "提高允许调用额度" in workflow.detail
            assert "收紧资料范围" not in workflow.detail
        elif kind == "model_protocol_error":
            assert "重试本次审核" in workflow.detail
            assert workflow.steps.filter(
                kind="workflow_diagnostic", error_code="model_protocol"
            ).exists()
        if kind == "operator_call_limit":
            AgentPolicy.objects.update_or_create(
                pk=1, defaults={"value": {**default_policy(), "maxOperatorSteps": 32}}
            )
        current = runtime.decide_flow(
            env["user"],
            workflow,
            {
                "nodeId": "inputs",
                "decision": "retry_context",
                "revision": state(workflow)["revision"],
                "idempotencyKey": uuid4().hex,
            },
        )
        assert current.status == "queued" and current.plan["phase"] == "prepare"
        assert (
            current.plan["stages"] == [] and current.plan["actualModelCallCount"] == 2
        )
        assert current.operator_steps == 16
        assert state(current)["nodes"]["inputs"]["human"]["status"] != "approved"
        assert not state(current)["nodes"]["inputs"].get("contextRecovery")
        resumed = []
        monkeypatch.setattr(
            demo_workflow,
            "prepare_demo",
            lambda *args: resumed.append(args[0].plan["phase"]),
        )
        demo_workflow.advance_demo(current.pk)
        assert resumed == ["prepare"]


def test_approval_statistics_preserves_all_dimensions_areas_pixels_and_approval_binding():
    from apps.agent.geology_multi_results import approval_statistics

    original = {
        "proposalHash": "original",
        "approvalScopeDigest": "approved-members",
        "approvedCount": 9,
        "suggestionCount": 12,
        "sourceOutputs": [{"outputId": 3}],
        "groups": [
            {
                "element": "alteration",
                "ruleId": "A-1",
                "action": "exclude",
                "mineral": mineral,
                "rockGroup": "碳酸盐岩",
                "boundary": "inside",
                "count": 2,
                "approvedCount": approved,
                "areaM2": 10,
                "pixelCount": 4,
            }
            for mineral, approved in [("方解石", 2), ("方解石", 1), ("绿泥石", 0)]
        ],
        "suggestions": [{"id": "not_reaudited"}],
    }
    saved = deepcopy(original)
    value = approval_statistics(original)
    assert original == saved
    assert (
        value["proposalHash"] == "original"
        and value["approvalScopeDigest"] == "approved-members"
    )
    assert value["sourceOutputs"] == original["sourceOutputs"]
    assert len(value["groups"]) == 2
    assert value["groups"][0]["count"] == 4 and value["groups"][0]["approvedCount"] == 3
    assert value["groups"][0]["areaM2"] == 20 and value["groups"][0]["pixelCount"] == 8
    assert sum(row["pixelCount"] for row in value["groups"]) == 12
    assert "suggestions" not in value
