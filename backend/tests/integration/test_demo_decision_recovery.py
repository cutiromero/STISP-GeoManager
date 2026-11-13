"""Recover complete accepted replies after interrupted persistence, without resending."""

# ruff: noqa: F811

import copy
import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.utils import timezone

from apps.agent.demo_decisions import decide
from apps.agent.demo_workflow import advance_demo, confirm_demo, prepare_demo
from apps.agent.demo_results import EDIT_FIELDS
from apps.agent.models import AgentWorkflow
from apps.agent.policy import default_policy
from apps.agent.workflow import step
from apps.agent.workflow_worker import claim, recover
from apps.catalog.models import DataResource
from apps.compute.models import ComputeTask
from apps.compute.packages import ComputeError
from apps.knowledge.models import KnowledgeEntry
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_decision_retry import (
    ordinary_stage,
    retry_model,  # noqa: F401
    run,
)
from tests.integration.test_demo_edit_context import geology, model_response
from tests.integration.test_demo_workflow import demo, scenario  # noqa: F401


def saved_response(*, retry=False, edit=False):
    workflow, stage, results = geology() if edit else ordinary_stage()
    edits = (
        [{key: results[0]["rows"][1][key] for key in (*EDIT_FIELDS, "reason")}]
        if edit
        else []
    )
    action = stage["identifier"]
    valid = model_response(action, edits)
    raws = ["invalid-json", valid] if retry else [valid]
    outcome, _ = run(raws, workflow, stage, results)
    workflow.max_iterations = workflow.iteration = len(raws)
    workflow.plan["actualModelCallCount"] = len(raws)
    return workflow, stage, results, outcome


def replay(workflow, stage, results, *, guard=lambda: None):
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window") as window,
        patch("apps.agent.context.count_tokens") as tokens,
        patch("apps.agent.demo_decisions.provider.stream") as stream,
    ):
        try:
            return decide(workflow, None, default_policy(), stage, results, guard)
        finally:
            window.assert_not_called()
            tokens.assert_not_called()
            stream.assert_not_called()


def reordered(value):
    if isinstance(value, dict):
        return {key: reordered(item) for key, item in reversed(value.items())}
    if isinstance(value, list):
        return [reordered(item) for item in value]
    return value


def many_reference_reply():
    workflow, stage, results = ordinary_stage()
    workflow.evidence = [
        {"id": index, "revision": 1, "title": f"适用知识{index}"}
        for index in range(1, 32)
    ]
    value = model_response(stage["identifier"], [])
    value["decision"]["evidenceRefs"] = [
        {"kind": "knowledge", "id": str(row["id"]), "revision": 1}
        for row in workflow.evidence
    ] + [{"kind": "output", "id": "102"}]
    return workflow, stage, results, json.dumps(value, ensure_ascii=False)


def test_latest_statistics_after_thirty_authorized_references_are_preserved(
    retry_model,
):
    workflow, stage, results, raw = many_reference_reply()
    (decision, _), requests = run([raw], workflow, stage, results)
    assert len(requests) == 1
    assert len(decision["evidenceRefs"]) == 32
    assert decision["evidenceRefs"][-1]["id"] == "102"
    wrong = json.loads(raw)
    wrong["decision"]["evidenceRefs"][-1]["id"] = "unprovided-output"
    with pytest.raises(ComputeError, match="并非本次授权"):
        from apps.agent.demo_decisions import _validate_response, evidence_refs

        _validate_response(
            json.dumps(wrong),
            workflow,
            stage,
            results,
            evidence_refs(workflow, [], results),
        )


def test_historical_reference_trim_revalidates_saved_reply_without_model_request(
    retry_model,
):
    from apps.agent import demo_decisions

    workflow, stage, results, raw = many_reference_reply()
    validate = demo_decisions.validate_decision

    def old_trim(*args, **kwargs):
        decision = validate(*args, **kwargs)
        decision["evidenceRefs"] = decision["evidenceRefs"][:30]
        return decision

    with patch.object(demo_decisions, "validate_decision", side_effect=old_trim):
        with pytest.raises(ComputeError, match="最近一次实际计算统计"):
            run(["invalid-json", raw], workflow, stage, results)
    workflow.max_iterations = workflow.iteration = 2
    workflow.plan["actualModelCallCount"] = 2
    audit = copy.deepcopy(stage["modelAttempts"])
    assert demo_decisions.can_revalidate_reference_tail(stage)
    decision, edits = replay(workflow, stage, results)
    assert len(decision["evidenceRefs"]) == 32 and not edits
    assert stage["modelAttempts"] == audit
    assert (
        stage["recoveredResponseState"]
        == "reference_tail_revalidated_without_new_request"
    )
    assert workflow.plan["actualModelCallCount"] == 2
    workflow.goal = "科研任务已改变"
    with pytest.raises(ComputeError, match="已有模型请求记录"):
        replay(workflow, stage, results)


def test_recorded_platform_normalization_error_revalidates_without_a_special_cap(
    retry_model,
):
    from apps.agent import demo_decisions

    workflow, stage, results, raw = many_reference_reply()
    value = json.loads(raw)
    value["decision"]["evidenceRefs"] = value["decision"]["evidenceRefs"][:10] + [
        {"kind": "output", "id": "102"}
    ]
    raw = json.dumps(value, ensure_ascii=False)
    validate = demo_decisions.validate_decision

    def corrupt_normalization(*args, **kwargs):
        result = validate(*args, **kwargs)
        result["evidenceRefs"] = result["evidenceRefs"][:-1]
        return result

    with patch.object(
        demo_decisions, "validate_decision", side_effect=corrupt_normalization
    ):
        with pytest.raises(ComputeError, match="最近一次实际计算统计"):
            run([raw, raw], workflow, stage, results)
    workflow.max_iterations = workflow.iteration = 2
    workflow.plan["actualModelCallCount"] = 2
    assert not demo_decisions.can_revalidate_reference_tail(stage)
    assert demo_decisions.can_revalidate_saved_response(stage)
    audit = copy.deepcopy(stage["modelAttempts"])
    result, _ = replay(workflow, stage, results)
    assert result["evidenceRefs"][-1]["id"] == "102"
    assert stage["modelAttempts"] == audit
    assert (
        stage["recoveredResponseState"]
        == "platform_validation_rechecked_without_new_request"
    )


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("edit", [False, True])
def test_equal_fresh_results_with_different_key_order_replay_exact_saved_request(
    retry, edit, retry_model
):
    workflow, stage, results, original = saved_response(retry=retry, edit=edit)
    stage["modelRequestPayload"] = copy.deepcopy(stage["modelRequestPayload"])
    audit = copy.deepcopy(stage["modelAttempts"])
    fresh = reordered(results)
    assert fresh == results
    assert list(fresh[0]) != list(results[0])
    assert replay(workflow, stage, fresh) == original
    assert stage["modelAttempts"] == audit
    fresh[0]["rows"][1]["new_value"] = "实际结果已改变"
    with pytest.raises(ComputeError, match="本步已有模型请求记录"):
        replay(workflow, stage, fresh)


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("edit", [False, True])
def test_complete_accepted_response_recovers_with_no_new_request(
    retry, edit, retry_model
):
    workflow, stage, results, original = saved_response(retry=retry, edit=edit)
    audit = copy.deepcopy(stage["modelAttempts"])
    assert replay(workflow, stage, results) == original
    assert stage["modelAttempts"] == audit
    assert stage["recoveredModelAttempt"] == len(audit)
    assert workflow.plan["actualModelCallCount"] == workflow.iteration == len(audit)


def test_configured_output_above_4096_recovers_without_new_request(retry_model):
    workflow, stage, results, original = saved_response()
    audit = copy.deepcopy(stage["modelAttempts"])
    assert audit[0]["outputLimit"] == default_policy()["maxOutputTokens"]
    assert audit[0]["outputLimit"] > 4096
    assert replay(workflow, stage, results) == original
    assert stage["modelAttempts"] == audit
    assert stage["recoveredModelAttempt"] == 1


@pytest.mark.parametrize("original_status", [None, "pending"])
def test_review_retry_reuses_accepted_response_with_original_scheduler_hint(
    retry_model, original_status
):
    from apps.business_flows.legacy import _resume_stage_status

    workflow, stage, results = ordinary_stage()
    if original_status is None:
        stage.pop("status", None)
    else:
        stage["status"] = original_status
    original, _ = run(
        [model_response(stage["identifier"], [])], workflow, stage, results
    )
    workflow.max_iterations = workflow.iteration = 1
    workflow.plan["actualModelCallCount"] = 1
    audit = copy.deepcopy(stage["modelAttempts"])
    stage["status"] = "needs_review"
    _resume_stage_status(stage)
    assert replay(workflow, stage, results) == original
    assert stage["modelAttempts"] == audit
    assert workflow.plan["actualModelCallCount"] == 1
    workflow.goal = "实际科研目标已改变"
    with pytest.raises(ComputeError, match="已有模型请求记录"):
        replay(workflow, stage, results)


def test_main_executor_history_does_not_invalidate_a_saved_current_step_reply(
    retry_model,
):
    from apps.business_flows.builtins import source_summary_definition
    from apps.business_flows.execution_session import initialize, session

    workflow, stage, results = ordinary_stage()
    workflow.workflow_type = "business_flow"
    workflow.parameters = {
        "_businessFlow": {
            "definitionSnapshot": source_summary_definition(main_agent=True),
            "versionId": 1,
        }
    }
    initialize(workflow)
    original, _ = run(
        [model_response(stage["identifier"], [])], workflow, stage, results
    )
    workflow.max_iterations = workflow.iteration = 1
    workflow.plan["actualModelCallCount"] = 1
    assert len(session(workflow)["loop"]["history"]) == 1
    assert replay(workflow, stage, results) == original
    assert len(session(workflow)["loop"]["history"]) == 1
    workflow.goal = "实际目标已经改变"
    with pytest.raises(ComputeError, match="已有模型请求记录"):
        replay(workflow, stage, results)


def test_resolved_human_guidance_does_not_invalidate_its_saved_response(retry_model):
    from apps.business_flows.builtins import source_summary_definition
    from apps.business_flows.execution_session import initialize
    from apps.business_flows.state import state

    workflow, stage, results = ordinary_stage()
    workflow.workflow_type = "business_flow"
    workflow.parameters = {
        "_businessFlow": {
            "definitionSnapshot": source_summary_definition(main_agent=True),
            "versionId": 1,
        }
    }
    initialize(workflow)
    stage["name"] = "summarize"
    item = state(workflow)["nodes"]["summarize"]
    item["recoveryGuidance"] = {
        "instruction": "明确已读取资料的范围",
        "diagnostic": "核对引用",
        "actor": "executor",
        "scope": "node",
    }
    original, _ = run(
        [model_response(stage["identifier"], [])], workflow, stage, results
    )
    workflow.max_iterations = workflow.iteration = 1
    workflow.plan["actualModelCallCount"] = 1
    item.pop("recoveryGuidance")
    assert replay(workflow, stage, results) == original


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("budget_level", [1, 2, 3, 4])
def test_budgeted_first_request_recovers_exact_projection_without_network(
    retry, budget_level, retry_model
):
    workflow, stage, results = ordinary_stage()
    results[0]["rows"] = [
        {**results[0]["rows"][0], "feature_id": f"object-{index}"}
        for index in range(120)
    ]
    answer = model_response(stage["identifier"], [])
    raws = ["invalid-json", answer] if retry else [answer]

    def measure(model, messages, *options):
        from apps.agent.decision_budget import ROW_LIMITS

        if len(messages) > 2:
            return 1200
        payload = json.loads(messages[1]["content"])
        return (
            800
            if len(payload["actualResults"][0]["rows"]) <= ROW_LIMITS[budget_level]
            else 49904
        )

    outcome, requests = run(raws, workflow, stage, results, tokens=measure)
    workflow.max_iterations = workflow.iteration = len(raws)
    workflow.plan["actualModelCallCount"] = len(raws)
    assert stage["modelAttempts"][0]["budgetLevel"] == budget_level
    assert stage["modelAttempts"][0]["inputTokens"] == 800
    assert len(requests) == len(raws)
    stage["modelRequestPayload"] = copy.deepcopy(stage["modelRequestPayload"])
    assert replay(workflow, stage, reordered(results)) == outcome


@pytest.mark.parametrize("level", [-1, 5, True])
def test_invalid_projection_level_cannot_recover_a_saved_reply(level, retry_model):
    workflow, stage, results, _ = saved_response()
    stage["modelAttempts"][0]["budgetLevel"] = level
    with pytest.raises(ComputeError, match="本步已有模型请求记录"):
        replay(workflow, stage, results)


@pytest.mark.parametrize("retry", [False, True])
def test_saved_complete_response_is_revalidated_after_pause_without_new_request(
    retry, retry_model
):
    workflow, stage, results, original = saved_response(retry=retry)
    latest = stage["modelAttempts"][-1]
    latest["status"] = "response_received"
    latest.pop("accepted")
    audit = copy.deepcopy(stage["modelAttempts"])
    assert replay(workflow, stage, results) == original
    assert stage["modelAttempts"] == audit
    assert stage["recoveredResponseState"] == "validated_without_new_request"
    assert workflow.plan["actualModelCallCount"] == len(audit)


def test_received_response_with_invalid_evidence_never_submits_or_calls_model(
    retry_model,
):
    workflow, stage, results, _ = saved_response()
    latest = stage["modelAttempts"][-1]
    latest["status"] = "response_received"
    latest.pop("accepted")
    value = json.loads(latest["response"])
    value["decision"]["evidenceRefs"] = [{"kind": "output", "id": "fake"}]
    latest["response"] = json.dumps(value)
    with pytest.raises(ComputeError, match="本次授权"):
        replay(workflow, stage, results)


def test_request_without_saved_response_explains_missing_analysis_and_keeps_audit(
    retry_model,
):
    workflow, stage, results, _ = saved_response()
    latest = stage["modelAttempts"][-1]
    latest["status"] = "requesting"
    latest.pop("accepted")
    latest.pop("response")
    before = copy.deepcopy(stage)
    with pytest.raises(ComputeError, match="完整分析响应未保存.*本步尚未提交计算"):
        replay(workflow, stage, results)
    assert stage == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "requesting"),
        ("status", "rejected"),
        ("accepted", False),
        ("requested", False),
        ("response", ""),
        ("response", None),
        ("requestSha256", "wrong"),
        ("modelId", "another-model"),
        ("attempt", True),
        ("outputLimit", 999999),
        ("inputTokens", 999999),
        ("inputLimit", 999999),
        ("contentBytes", 0),
        ("window", 512),
        ("truncated", True),
        ("feedback", "unexpected-feedback"),
    ],
)
def test_incomplete_or_inconsistent_audit_stops_without_network(
    field, value, retry_model
):
    workflow, stage, results, _ = saved_response()
    stage["modelAttempts"][-1][field] = value
    original = copy.deepcopy(stage)
    with pytest.raises(ComputeError, match="本步已有模型请求记录"):
        replay(workflow, stage, results)
    assert stage == original


@pytest.mark.parametrize("field", ["modelRequestPayload", "modelRequestInstruction"])
def test_changed_saved_request_refuses_recovery(field, retry_model):
    workflow, stage, results, _ = saved_response()
    stage[field] = "changed"
    with pytest.raises(ComputeError, match="本步已有模型请求记录"):
        replay(workflow, stage, results)


@pytest.mark.parametrize(
    "budget", ["calls_zero", "calls_over", "iteration_zero", "iteration_over"]
)
def test_invalid_budget_refuses_recovery(budget, retry_model):
    workflow, stage, results, _ = saved_response()
    if budget.startswith("calls"):
        workflow.plan["actualModelCallCount"] = 0 if budget.endswith("zero") else 2
    else:
        workflow.iteration = 0 if budget.endswith("zero") else 2
    with pytest.raises(ComputeError, match="本步已有模型请求记录"):
        replay(workflow, stage, results)


@pytest.mark.parametrize("changed", ["knowledge", "results", "roles"])
def test_current_complete_payload_must_match_saved_payload(changed, retry_model):
    workflow, stage, results, _ = saved_response()
    if changed == "knowledge":
        workflow.evidence = [{"id": 42, "revision": 2, "title": "修订知识"}]
    elif changed == "results":
        results[0]["rows"][1]["new_value"] = "changed"
    else:
        stage["bindings"]["features"] = "different-source"
    with pytest.raises(ComputeError, match="本步已有模型请求记录"):
        replay(workflow, stage, results)


@pytest.mark.parametrize("invalid", ["reference", "edits"])
def test_accepted_marker_does_not_replace_response_validation(invalid, retry_model):
    workflow, stage, results, _ = saved_response()
    value = json.loads(stage["modelAttempts"][-1]["response"])
    if invalid == "reference":
        value["decision"]["evidenceRefs"] = [{"kind": "output", "id": "fake"}]
    else:
        value["edits"] = [{"feature_id": "fake"}]
    stage["modelAttempts"][-1]["response"] = json.dumps(value)
    with pytest.raises(ComputeError, match="本次授权|不得提前提交"):
        replay(workflow, stage, results)


@pytest.mark.parametrize("changed", ["previous_response", "feedback", "call_count"])
def test_repaired_reply_requires_complete_original_retry_chain(changed, retry_model):
    workflow, stage, results, _ = saved_response(retry=True)
    if changed == "previous_response":
        stage["modelAttempts"][0]["response"] = "changed-invalid-json"
    elif changed == "feedback":
        stage["modelAttempts"][1]["feedback"] = "changed-feedback"
    else:
        workflow.plan["actualModelCallCount"] = 1
    with pytest.raises(ComputeError, match="本步已有模型请求记录"):
        replay(workflow, stage, results)


def test_real_accepted_response_cannot_switch_to_mock(retry_model, settings):
    workflow, stage, results, _ = saved_response()
    settings.AGENT_MODELS[0] = {**settings.AGENT_MODELS[0], "model_id": "mock-demo"}
    with pytest.raises(ComputeError, match="本步已有模型请求记录"):
        replay(workflow, stage, results)


@pytest.mark.parametrize(
    "retry,changed",
    [(False, None), (True, None), (False, "input"), (False, "knowledge")],
)
def test_accepted_persistence_failure_recovers_durably_or_stops_on_changed_evidence(
    retry, changed, demo, settings
):
    workflow = scenario(demo)
    knowledge = None
    if changed == "knowledge":
        knowledge = KnowledgeEntry.objects.create(
            title="NDVI 物候与植被核对",
            domain="arid_ecology",
            status="published",
            project_tag_id=demo["project"].id,
            statement="植被指数变化应结合物候记录。",
        )
        workflow.plan["knowledgeSelection"] = {
            "mode": "manual",
            "domains": ["arid_ecology"],
        }
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    workflow.max_iterations = 2 if retry else 1
    workflow.save(update_fields=["max_iterations"])
    settings.AGENT_MODELS[0] = {**settings.AGENT_MODELS[0], "model_id": "qwen-fixture"}
    valid = model_response("raster-ndvi", [])
    valid["decision"]["evidenceRefs"] = [
        {"kind": "resource", "id": str(demo["inputs"]["early_image"])}
    ]
    if knowledge:
        assert workflow.evidence and workflow.evidence[0]["id"] == knowledge.id
        valid["decision"]["evidenceRefs"].append(
            {"kind": "knowledge", "id": str(knowledge.id), "revision": 1}
        )
    raws = iter(["invalid-json", json.dumps(valid)] if retry else [json.dumps(valid)])

    def fail_decision_save(current, kind, **kwargs):
        if kind == "analysis_decision":
            raise OperationalError("database is locked")
        return step(current, kind, **kwargs)

    with (
        patch("apps.agent.demo_workflow.step", side_effect=fail_decision_save),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=800),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=lambda *a, **kw: iter([next(raws)]),
        ) as stream,
        pytest.raises(OperationalError, match="database is locked"),
    ):
        advance_demo(workflow.id)
    workflow.refresh_from_db()
    stage = workflow.plan["stages"][0]
    attempt_count = 2 if retry else 1
    assert stream.call_count == attempt_count
    assert stage["modelAttempts"][-1]["status"] == "accepted"
    assert not stage.get("decision") and not stage.get("taskId")
    assert (
        workflow.iteration == 1
        and workflow.plan["actualModelCallCount"] == attempt_count
    )
    assert workflow.steps.filter(kind="analysis_model_attempt").count() == attempt_count
    assert not workflow.steps.filter(kind="analysis_decision").exists()
    assert not ComputeTask.objects.exists()
    AgentWorkflow.objects.filter(pk=workflow.id).update(
        heartbeat=timezone.now() - timedelta(seconds=91)
    )
    recover()
    assert claim() == workflow.id
    if changed == "input":
        DataResource.objects.filter(pk=demo["inputs"]["early_image"]).update(
            status="disabled"
        )
    elif changed == "knowledge":
        KnowledgeEntry.objects.filter(pk=knowledge.id).update(revision=2)
    with (
        patch("apps.agent.demo_decisions.provider.model_window") as window,
        patch("apps.agent.context.count_tokens") as tokens,
        patch("apps.agent.demo_decisions.provider.stream") as stream,
    ):
        advance_demo(workflow.id)
        workflow.refresh_from_db()
        if changed:
            assert workflow.status == "interrupted"
            assert not ComputeTask.objects.exists()
            assert not workflow.steps.filter(kind="analysis_decision").exists()
        else:
            assert workflow.status == "waiting_compute"
            assert workflow.plan["stages"][0]["recoveredModelAttempt"] == attempt_count
            assert ComputeTask.objects.count() == 1
            assert workflow.steps.filter(kind="analysis_decision").count() == 1
            advance_demo(workflow.id)
            assert ComputeTask.objects.count() == 1
            assert workflow.steps.filter(kind="analysis_decision").count() == 1
        window.assert_not_called()
        tokens.assert_not_called()
        stream.assert_not_called()
    workflow.refresh_from_db()
    assert (
        workflow.iteration == 1
        and workflow.plan["actualModelCallCount"] == attempt_count
    )
    assert workflow.steps.filter(kind="analysis_model_attempt").count() == attempt_count
