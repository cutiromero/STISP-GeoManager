"""Final approval statements must match actual scope; one model correction stays audited."""

# ruff: noqa: F811

import copy
import json
from unittest.mock import patch

import pytest

from apps.agent.demo_decisions import (
    _repair_feedback,
    _validate_final_review_report,
    decide,
)
from apps.agent.demo_results import read_output
from apps.agent.demo_workflow import confirm_demo
from apps.agent.workflow import step
from apps.compute.models import ComputeOutput, ComputeTask
from apps.compute.packages import ComputeError, checksum
from apps.core.storage import app_path
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_decision_retry import responses
from tests.integration.test_demo_review_context import reviewed_geometry  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401


def states(*, approval="approved", kind="vector"):
    return {
        "resultReviews": [
            {
                "stage": "arbitrary_repair",
                "taskId": "actual-task",
                "outputId": 404,
                "key": "candidate",
                "kind": kind,
                "originalQualityStatus": "needs_review",
                "approvalStatus": approval,
                "humanReviewStepSequences": [17] if approval == "approved" else [],
            }
        ]
    }


def report():
    return {
        "problem": "检查并修复地图，需要审核时请问我",
        "findings": ["候选结果经用户批准继续处理，原质量标记保留"],
        "judgement": "本次修复候选已由用户批准继续处理，后续检查完成",
        "uncertainties": [
            "低置信记录需补充调查，降维片段对后续空间分析的适用性需专业复核"
        ],
        "resultSummary": "修复候选已由用户确认，成果已保存；无效原面积不能证明修复无损",
    }


def numbered_states():
    execution = states()
    original = execution["resultReviews"][0]
    execution["resultReviews"].extend(
        [{**original, "outputId": 405}, {**original, "outputId": 406}]
    )
    execution["resultReviews"].extend(
        [
            {
                **original,
                "outputId": 407,
                "kind": "archive",
                "approvalStatus": "reference_only",
                "humanReviewStepSequences": [],
            },
            {
                **original,
                "outputId": 408,
                "originalQualityStatus": "passed",
                "approvalStatus": "not_required",
                "humanReviewStepSequences": [],
            },
        ]
    )
    return execution


@pytest.mark.parametrize(
    "field", ["findings", "judgement", "resultSummary", "uncertainties"]
)
def test_current_waiting_statement_rejected_despite_positive_ack(field):
    value = report()
    wrong = "对象K17几何已修复，但降维片段仍需人工审核"
    value[field] = [wrong] if field in {"findings", "uncertainties"} else wrong
    with pytest.raises(ComputeError, match="仍将.*待审核"):
        _validate_final_review_report(value, {"identifier": "finish"}, states())


@pytest.mark.parametrize(
    "phrase",
    [
        "候选结果等待用户批准",
        "几何候选尚未由用户批准",
        "修复候选未经用户确认",
        "用户尚未批准几何候选",
        "降维片段需审核",
        "修复结果还需要用户确认",
    ],
)
def test_waiting_and_negative_current_approval_variants_are_rejected(phrase):
    value = report()
    value["findings"] = [phrase]
    with pytest.raises(ComputeError, match="待审核"):
        _validate_final_review_report(value, {"identifier": "finish"}, states())


@pytest.mark.parametrize(
    "text",
    [
        "本次修复已完成",
        "并非用户已批准修复候选",
        "不能说用户已确认候选结果",
        "用户尚未批准",
        "用户已确认输入参数",
        "用户已批准计划。候选修复面有效。",
        "用户已批准计划且候选有效",
        "修复候选有效且用户已批准参数",
        "用户已批准修复计划",
        "用户已确认几何修复参数",
    ],
)
def test_missing_or_negated_scope_ack_cannot_count_as_approval(text):
    value = report()
    value["judgement"] = value["resultSummary"] = text
    with pytest.raises(ComputeError, match="未明确说明"):
        _validate_final_review_report(value, {"identifier": "finish"}, states())


@pytest.mark.parametrize(
    "phrase",
    [
        "原候选需人工审核，现已由用户批准继续处理",
        "修复候选已由用户批准，低置信接触记录需补充调查",
        "降维片段后续空间分析适用性需专业复核",
        "原始面积基准不可靠，不能用0%变化证明无损",
        "修复结果的现场适用性仍需人工审核",
        "F04仍需人工审核，几何修复候选已由用户批准继续处理",
        "归档保持原样，修复候选已由用户批准",
    ],
)
def test_history_professional_review_and_scientific_limits_are_preserved(phrase):
    value = report()
    value["findings"].append(phrase)
    original = copy.deepcopy(value)
    _validate_final_review_report(value, {"identifier": "finish"}, states())
    assert value == original


@pytest.mark.parametrize(
    "phrase",
    [
        "所有结果已由用户批准",
        "归档审计附件已由用户确认",
        "用户已批准全部修复成果及归档，工作流完成。",
        "用户已批准所有结果",
        "用户已确认归档审计附件",
    ],
)
def test_approval_cannot_expand_to_all_results_or_archive(phrase):
    value = report()
    value["findings"].append(phrase)
    with pytest.raises(ComputeError, match="扩大"):
        _validate_final_review_report(value, {"identifier": "finish"}, states())


@pytest.mark.parametrize(
    "mode", ["no_approval", "pending", "archive", "nonfinal", "partial"]
)
def test_contract_only_applies_to_fully_approved_current_final_results(mode):
    execution = states()
    stage = {"identifier": "finish"}
    if mode == "no_approval":
        execution["resultReviews"] = []
    elif mode == "pending":
        execution = states(approval="pending")
    elif mode == "archive":
        execution = states(kind="archive", approval="reference_only")
    elif mode == "partial":
        execution["resultReviews"].extend(states(approval="pending")["resultReviews"])
    else:
        stage["identifier"] = "geology-check"
    wrong = {
        **report(),
        "judgement": "修复候选仍需人工审核",
        "resultSummary": "尚未完成审核",
    }
    _validate_final_review_report(wrong, stage, execution)


@pytest.mark.parametrize(
    "phrase",
    [
        "修复候选已由用户批准，仍需人工审核",
        "几何修复算法执行后，F05几何已修复，但包含降维片段，需人工审核；其余5个要素几何未变。",
        "修复面已生成，用户尚未批准",
        "修复面已生成，但需人工审核",
    ],
)
def test_candidate_scope_follows_elliptical_review_clauses(phrase):
    value = report()
    value["findings"] = [phrase]
    with pytest.raises(ComputeError, match="待审核"):
        _validate_final_review_report(value, {"identifier": "finish"}, states())


@pytest.mark.parametrize(
    "phrase",
    [
        "修复候选已由用户批准，F04仍需人工审核",
        "修复候选已由用户批准，低置信调查记录仍需人工审核",
        "修复面已生成。需人工审核的低置信调查记录保留",
        "修复候选已由用户批准，用户尚未批准其他低置信记录",
    ],
)
def test_explicit_new_subject_and_sentence_end_stop_scope_inheritance(phrase):
    value = report()
    value["findings"] = [phrase]
    _validate_final_review_report(value, {"identifier": "finish"}, states())


@pytest.mark.parametrize(
    "phrase",
    [
        "平台不再等待用户审核该几何候选",
        "几何候选无需人工审核",
        "修复结果不需用户批准",
        "候选不需要用户确认",
        "候选不必再等待人工审核",
        "几何候选无需再等待用户批准",
    ],
)
def test_direct_negation_of_waiting_review_is_not_a_pending_status(phrase):
    value = report()
    value["findings"].append(phrase)
    _validate_final_review_report(value, {"identifier": "finish"}, states())


@pytest.mark.parametrize(
    "phrase",
    [
        "不能说无需人工审核该几何候选",
        "几何候选并非不再等待用户审核",
        "不是不需要人工确认修复结果",
        "没有说不再等待用户批准几何候选",
        "不能认定不需用户确认该修复结果",
        "几何候选不得不等待用户审核",
        "几何候选不可以不等待用户审核",
        "几何候选不可不等待用户审核",
        "候选无需人工审核，但修复面仍需人工审核",
        "修复面仍需人工审核，候选无需人工审核",
    ],
)
def test_negation_cannot_mask_double_negation_or_another_pending_statement(phrase):
    value = report()
    value["findings"].append(phrase)
    with pytest.raises(ComputeError, match="待审核"):
        _validate_final_review_report(value, {"identifier": "finish"}, states())


def test_actual_corrected_finding_distinguishes_approval_and_original_quality():
    value = report()
    value["findings"] = [
        "几何修复阶段已完成自相交修复，修复后6个要素均有效。"
        "其中一个要素因包含降维片段，原始质量标记为needs_review，"
        "但该组输出已由用户批准继续处理，平台不再等待用户审核该几何候选；"
        "地学真实性及降维片段影响仍需后续专业复核。"
    ]
    _validate_final_review_report(value, {"identifier": "finish"}, states())


@pytest.mark.parametrize(
    "phrase",
    [
        "几何修复候选输出（404, 405, 406）已由用户批准继续处理",
        "修复候选结果(404,405,406)已由用户批准继续处理",
        "用户已批准修复候选输出（404, 405, 406）继续处理",
        "用户已批准几何候选输出(404,405,406)继续处理",
        "候选输出（404，405、406）已由用户确认",
        "候选输出[404,405,406]已由用户批准",
        "修复候选输出【404,405,406】已由用户批准",
        "修复候选输出（outputIds=404, 405, 406）已由用户批准",
        "几何候选输出（输出编号：404,405,406）已由用户批准",
        "修复地图（404）已由用户批准继续处理",
        "用户已批准修复候选输出（404,405）继续处理",
    ],
)
def test_approval_annotations_stay_in_one_clause_and_bind_real_output_subset(phrase):
    value = report()
    value["judgement"] = value["resultSummary"] = phrase
    _validate_final_review_report(value, {"identifier": "finish"}, numbered_states())


@pytest.mark.parametrize(
    "field", ["findings", "judgement", "resultSummary", "uncertainties"]
)
@pytest.mark.parametrize(
    "phrase",
    [
        "几何修复候选输出（404,999）已由用户批准",
        "用户已批准几何修复候选输出（404,999）继续处理",
        "修复候选输出（404,407）已由用户批准",
        "用户已批准修复候选输出（404,408）继续处理",
    ],
)
def test_other_positive_ack_cannot_mask_unknown_archive_or_unapproved_output_ids(
    field, phrase
):
    value = report()
    value[field] = [phrase] if field in {"findings", "uncertainties"} else phrase
    with pytest.raises(ComputeError, match="未批准或归档输出"):
        _validate_final_review_report(
            value, {"identifier": "finish"}, numbered_states()
        )


@pytest.mark.parametrize(
    "phrase",
    [
        "用户已批准计划（候选结果404）",
        "计划（候选结果）已由用户批准",
        "用户已批准修复计划（404,405,406）",
        "修复参数（404,405）已由用户确认",
        "修复候选输出（404,405)已由用户批准",
        "修复候选输出（404,405已由用户批准",
    ],
)
def test_annotation_does_not_turn_plan_parameters_or_malformed_objects_into_approval(
    phrase,
):
    value = report()
    value["judgement"] = value["resultSummary"] = phrase
    with pytest.raises(ComputeError, match="未明确说明"):
        _validate_final_review_report(
            value, {"identifier": "finish"}, numbered_states()
        )


def test_actual_numbered_approval_keeps_scope_limits_and_separate_followup():
    value = report()
    value["resultSummary"] = (
        "几何修复候选输出（404, 405, 406）已由用户批准继续处理，"
        "原needs_review标记保留，批准不扩展至归档或全部结果。"
        "F04待现场核实，降维片段仍需专业复核。"
    )
    _validate_final_review_report(value, {"identifier": "finish"}, numbered_states())


@pytest.mark.parametrize("mode", ["nonfinal", "no_review", "pending", "archive"])
def test_ordinary_feedback_does_not_invent_user_approval(mode):
    execution = states()
    stage = {"identifier": "finish"}
    if mode == "nonfinal":
        stage["identifier"] = "ecology-priority"
    elif mode == "no_review":
        execution["resultReviews"] = []
    elif mode == "pending":
        execution = states(approval="pending")
    else:
        execution = states(kind="archive", approval="reference_only")
    execution["currentRun"] = {"latestStatisticsOutputIds": [919]}
    payload = {"executionState": execution, "editTask": {}}
    text = _repair_feedback(
        stage, payload, ComputeError("判断必须引用最近一次实际计算统计")
    )
    feedback = json.loads(text)
    assert set(feedback) == {
        "validationError",
        "allowedAction",
        "latestStatisticsOutputIds",
        "editTask",
        "instruction",
    }
    assert feedback["latestStatisticsOutputIds"] == [919]
    assert (
        _repair_feedback(
            stage, copy.deepcopy(payload), ComputeError(feedback["validationError"])
        )
        == text
    )


def model_context(env):
    workflow = env["review_workflow"]
    confirm_demo(workflow, env["owner"], env["policy"], workflow.plan_hash)
    workflow.refresh_from_db()
    stage = {"name": "final_analysis", "identifier": "finish"}
    task = ComputeTask.objects.get(pk=workflow.plan["stages"][1]["taskId"])
    path = app_path("outputs", str(task.id), "final-statistics.csv")
    path.write_text(
        "issue_count,remaining_review\n1,low_confidence\n", encoding="utf-8"
    )
    output = ComputeOutput.objects.create(
        task=task,
        key="statistics",
        kind="table",
        file_name=path.name,
        path=str(path.relative_to(app_path())),
        size_bytes=path.stat().st_size,
        checksum=checksum(path),
        metadata={"qualityCheck": {"status": "passed"}},
    )
    results = copy.deepcopy(workflow.plan["stages"][1]["results"])
    results.append(read_output(workflow, env["owner"], env["policy"], output))
    answer = {
        "decision": {
            **report(),
            "nextAction": "finish",
            "algorithmReason": "已批准候选的后续检查完成",
            "evidenceRefs": [{"kind": "output", "id": str(output.id)}],
        },
        "edits": [],
    }
    answer["decision"]["findings"].append("平台不再等待用户审核该几何候选")
    reviewed_ids = [
        str(item["outputId"])
        for item in workflow.plan["stages"][1]["results"]
        if item["kind"] != "archive"
    ]
    answer["decision"]["resultSummary"] = (
        "修复候选输出（"
        + ", ".join(reviewed_ids)
        + "）已由用户批准继续处理，原质量标记保留"
    )
    return workflow, stage, results, answer


@pytest.mark.parametrize("outcome", ["corrected", "still_wrong", "recover"])
def test_real_provider_feedback_is_bounded_and_preserves_actual_calculations(
    reviewed_geometry, settings, outcome
):
    env = reviewed_geometry
    workflow, stage, results, valid = model_context(env)
    settings.AGENT_MODELS[0] = {**settings.AGENT_MODELS[0], "model_id": "qwen-fixture"}
    wrong = copy.deepcopy(valid)
    wrong["decision"]["findings"] = ["对象K17几何修复后含降维片段，需人工审核"]
    wrong["decision"]["judgement"] = "修改和检查完成，修复几何需人工审核降维片段"
    wrong["decision"]["resultSummary"] = "修复结果需审核降维片段，低置信记录保留待复核"
    before_results, before_plan = copy.deepcopy(results), copy.deepcopy(workflow.plan)
    tasks = ComputeTask.objects.count()
    requests = []
    captured = []
    raws = [wrong, wrong if outcome == "still_wrong" else valid]
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=800),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=responses(raws, requests),
        ),
    ):
        if outcome == "still_wrong":
            with pytest.raises(ComputeError, match="待审核"):
                decide(
                    workflow,
                    env["owner"],
                    env["policy"],
                    stage,
                    results,
                    lambda: None,
                    lambda a: captured.append(copy.deepcopy(a)),
                )
        else:
            decision, edits = decide(
                workflow,
                env["owner"],
                env["policy"],
                stage,
                results,
                lambda: None,
                lambda a: captured.append(copy.deepcopy(a)),
            )
            assert not edits and decision["judgement"] == valid["decision"]["judgement"]
    assert len(requests) == 2 and requests[1][:2] == requests[0]
    feedback = json.loads(requests[1][-1]["content"])
    scope = feedback["approvedResultScope"]
    assert {item["key"] for item in scope} == {"repaired", "repair_summary"}
    assert all(
        item["humanReviewStepSequences"]
        == [workflow.steps.get(kind="human_review").sequence]
        for item in scope
    )
    assert "后续专业复核" in feedback["reviewInstruction"]
    assert [a["status"] for a in captured] == [
        "requesting",
        "rejected",
        "requesting",
        "rejected" if outcome == "still_wrong" else "accepted",
    ]
    assert stage["modelAttempts"][0]["response"] == json.dumps(
        wrong, ensure_ascii=False
    )
    assert results == before_results and workflow.plan == before_plan
    assert ComputeTask.objects.count() == tasks
    if outcome == "recover":
        workflow.plan["actualModelCallCount"] = 2
        workflow.iteration = 1
        for attempt in stage["modelAttempts"]:
            attempt["requested"] = True
        step(workflow, "analysis_model_attempt", action={"accepted": True})
        original_attempts = copy.deepcopy(stage["modelAttempts"])
        with (
            patch("apps.agent.demo_decisions.resource_context", return_value=[]),
            patch("apps.agent.demo_decisions.provider.model_window") as window,
            patch("apps.agent.context.count_tokens") as tokens,
            patch("apps.agent.demo_decisions.provider.stream") as stream,
        ):
            recovered, _ = decide(
                workflow, env["owner"], env["policy"], stage, results, lambda: None
            )
        assert recovered == decision
        assert stage["modelAttempts"] == original_attempts
        assert workflow.plan["actualModelCallCount"] == 2 and workflow.iteration == 1
        window.assert_not_called()
        tokens.assert_not_called()
        stream.assert_not_called()
