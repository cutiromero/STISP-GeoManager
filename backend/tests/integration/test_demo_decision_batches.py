"""Real decision assembly reviews every member through bounded provider requests."""

# ruff: noqa: F811

import copy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.agent.decision_budget import (
    BudgetReviewRequired,
    assert_visible_edits,
    project_payload,
)
from apps.agent.demo_decisions import decide
from apps.agent.demo_decision_batches import plan_batches
from apps.agent.demo_results import read_output
from apps.agent.geology_multi_review import (
    assess_edits,
    proposal,
    validate_alteration_actions,
)
from apps.agent.policy import default_policy
from apps.compute.packages import ComputeError
from tests.integration.test_decision_input_budget import expand
from tests.integration.test_demo_decision_retry import retry_model  # noqa: F401


def scenario(count=257):
    stage = {"name": "apply", "identifier": "geology-multi-apply", "parameters": {}}
    entry = {
        "id": 200,
        "revision": 3,
        "title": "实际地区试用规则",
        "conditions": ["逐对象面积实测且边界关系已核实"],
        "exceptions": ["边界不明确则保留人工核查"],
        "sources": [{"title": "实测记录", "locator": "1"}],
        "trialBinding": {"ruleId": "L-01", "ruleVersion": "trial-1"},
        "ruleConfig": {"area_m2": {"lt": 1000}},
    }
    workflow = SimpleNamespace(
        model="online-fixture",
        workflow_type="geology_multi_element_reasoning",
        goal="对完整实际对象逐项提出有据建议",
        evidence=[entry],
        iteration=1,
        max_iterations=99,
        plan={
            "stages": [
                {
                    "name": "check",
                    "identifier": "geology-multi-check",
                    "taskId": "task",
                },
                stage,
            ],
            "algorithms": {},
            "trialRuleBindings": [{"id": 200, "revision": 3, **entry["trialBinding"]}],
            "actualModelCallCount": 0,
        },
    )
    rows = [
        {
            "issue_id": f"issue-{index}",
            "feature_id": f"object-{index}",
            "element": "lithology",
            "rule_id": "L-01",
            "rule_version": "trial-1",
            "snapshot_hash": "a" * 64,
            "allowed_actions_json": '["set_code","review","keep"]',
            "suggested_action": "set_code",
            "status": "suggested",
            "target_code": "T3",
            "conditions": "面积和边界均须满足",
            "exceptions": "边界不明确保持原样",
            "measurements_json": json.dumps({"area_m2": index + 1}),
            "reason": "已实际测量，待按知识核对",
            "geometry_json": '{"type":"Polygon","coordinates":[[[90,30],[91,30],[91,31],[90,31],[90,30]]]}',
        }
        for index in range(count)
    ]
    results = [
        {
            "key": "issues",
            "outputId": 1,
            "taskId": "task",
            "checksum": "c" * 64,
            "rows": rows,
        },
        {
            "key": "statistics",
            "outputId": 2,
            "taskId": "task",
            "checksum": "d" * 64,
            "rows": [{"objects": count}],
        },
    ]
    return workflow, stage, results


def provider_fixture(requests, seen, fail_at=None, disposition=None):
    def stream(model, messages, output, guard, **options):
        requests.append(copy.deepcopy(messages))
        if fail_at == len(requests):
            raise ComputeError("流式连接中断")
        payload = json.loads(messages[1]["content"])
        payload = expand(payload, payload.get("contextDefinitions", {}))
        assert output == 2000
        assert payload["modelBatch"]["completeMembers"] is True
        groups = payload["actualResults"][0]["groups"]
        for group in groups:
            assert len(group["samples"]) == group["count"]
            for row in group["samples"]:
                row = {**group.get("memberCommon", {}), **row}
                assert "geometry_json" not in row
                assert (
                    row["conditions"]
                    and row["exceptions"]
                    and group["memberSource"]["checksum"]
                )
                seen.append(row["issue_id"])
        value = {
            "decision": {
                "problem": "逐成员检视本批真实证据",
                "findings": ["本批实测值及边界满足试用条件"],
                "judgement": "提交本批有据建议",
                "uncertainties": ["人工批准后方可执行"],
                "nextAction": "geology-multi-apply",
                "algorithmReason": "核对本批全部成员及规则例外",
                "evidenceRefs": [
                    {"kind": "output", "id": "2"},
                    {"kind": "knowledge", "id": "200", "revision": 3},
                ],
                "resultSummary": "仅提出本批范围的建议",
            },
            "edits": [
                {
                    "group_id": group["group_id"],
                    "disposition": disposition
                    or ("suggested" if group["status"] == "suggested" else "review"),
                    "excluded_issue_ids": [],
                    "reason": "核对本批各对象测量与知识条件，例外保留",
                }
                for group in groups
            ],
        }
        if disposition == "omit":
            value["edits"] = []
        return iter([json.dumps(value, ensure_ascii=False)])

    return stream


def run(workflow, stage, results, requests, seen, *, fail_at=None, disposition=None):
    def record(attempt):
        if attempt["status"] == "requesting":
            if workflow.plan["actualModelCallCount"] >= workflow.max_iterations:
                attempt.update(status="budget_blocked", accepted=False)
                raise ComputeError("已达到场景真实模型请求次数上限")
            workflow.plan["actualModelCallCount"] += 1
            attempt["requested"] = True

    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch(
            "apps.agent.context.count_tokens",
            side_effect=lambda model, messages, *args: (
                sum(len(item["content"].encode()) for item in messages) // 4 + 64
            ),
        ),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=provider_fixture(requests, seen, fail_at, disposition),
        ),
    ):
        return decide(
            workflow, None, default_policy(), stage, results, lambda: None, record
        )


@pytest.mark.parametrize("count,expected_batches", [(257, 3), (541, 5)])
def test_all_members_are_reviewed_once_and_same_group_expands_only_current_scope(
    retry_model,
    count,
    expected_batches,
):
    workflow, stage, results = scenario(count)
    original = copy.deepcopy(results)
    requests, seen = [], []
    decision, edits = run(workflow, stage, results, requests, seen)
    assert len(requests) == expected_batches and workflow.plan[
        "actualModelCallCount"
    ] == len(requests)
    assert len(seen) == len(set(seen)) == len(edits) == count
    assert {item["issue_id"] for item in edits} == {
        row["issue_id"] for row in results[0]["rows"]
    }
    assert stage["modelBatches"]["coveredMemberCount"] == count
    for index, batch in enumerate(stage["modelBatches"]["batches"], 1):
        assert len(batch["stage"]["edits"]) == batch["end"] - batch["start"]
        for attempt in batch["stage"]["modelAttempts"]:
            assert attempt["batchIndex"] == index
            assert attempt["inputTokens"] <= attempt["inputLimit"] == 15000
            assert attempt["outputLimit"] == 2000 and attempt["truncated"] is False
    assert decision["nextAction"] == "geology-multi-apply" and results == original
    recovered = run(workflow, stage, results, requests, seen)
    assert recovered == (decision, edits)
    assert workflow.plan["actualModelCallCount"] == len(requests)
    assert len(seen) == count


def test_requested_interrupted_batch_is_not_sent_again(retry_model):
    workflow, stage, results = scenario()
    requests, seen = [], []
    with pytest.raises(ComputeError, match="流式连接中断"):
        run(workflow, stage, results, requests, seen, fail_at=2)
    assert stage["modelBatches"]["cursor"] == 1
    with pytest.raises(ComputeError, match="完整分析响应未保存"):
        run(workflow, stage, results, requests, seen)
    assert len(requests) == workflow.plan["actualModelCallCount"] == 2


def test_source_change_and_completed_edit_tampering_stop_before_new_request(
    retry_model,
):
    workflow, stage, results = scenario(5)
    requests, seen = [], []
    run(workflow, stage, results, requests, seen)
    stage["modelBatches"]["batches"][0]["stage"]["edits"][0]["target_code"] = "forged"
    with pytest.raises(ComputeError, match="实际模型响应不一致"):
        run(workflow, stage, results, requests, seen)
    results[0]["rows"][-1]["measurements_json"] = '{"area_m2":9999}'
    with pytest.raises(ComputeError, match="已变化"):
        run(workflow, stage, results, requests, seen)
    assert len(requests) == 1


def test_generic_large_tables_are_bounded_from_first_request_with_complete_source_identity():
    workflow, stage, results = scenario(5000)
    payload = {"actualResults": results, "knowledge": [], "inputRoles": []}
    original = copy.deepcopy(payload)
    projected = project_payload(payload, 0)
    assert len(projected["actualResults"][0]["rows"]) <= 40
    summary = projected["evidenceProjection"][0]
    assert summary["inputCount"] == 5000 and summary["omittedCount"] > 4900
    assert summary["sourceSha256"] and summary["coverage"] == "shown_items_only"
    shown = {row["issue_id"] for row in projected["actualResults"][0]["rows"]}
    unseen = next(row for row in results[0]["rows"] if row["issue_id"] not in shown)
    with pytest.raises(ValueError, match="未在本次.*模型证据中展示"):
        assert_visible_edits([{"issue_id": unseen["issue_id"]}], projected)
    assert payload == original


def test_unrequested_budget_block_resumes_after_explicit_budget_adjustment(retry_model):
    workflow, stage, results = scenario(257)
    workflow.max_iterations = 1
    requests, seen = [], []
    with pytest.raises(BudgetReviewRequired, match="进度和审计已保留"):
        run(workflow, stage, results, requests, seen)
    assert stage["modelBatches"]["cursor"] == 1
    assert len(requests) == 1
    workflow.max_iterations = 99
    stage.pop("contextBudgetReview")
    decision, edits = run(workflow, stage, results, requests, seen)
    assert len(edits) == len(seen) == len(set(seen)) == 257
    assert len(requests) == workflow.plan["actualModelCallCount"]
    assert (
        stage["modelBatches"]["batches"][1]["stage"]["unrequestedBudgetAttempts"][0][
            "requested"
        ]
        is False
    )


def test_held_objects_in_separate_batches_are_covered_without_becoming_edits(
    retry_model,
):
    workflow, stage, results = scenario(257)
    results[0]["rows"][0]["status"] = "review"
    results[0]["rows"][128]["status"] = "exception"
    requests, seen = [], []
    _, edits = run(workflow, stage, results, requests, seen)
    assert len(seen) == len(set(seen)) == 257
    assert len(edits) == 255
    assert not {"issue-0", "issue-128"}.intersection(item["issue_id"] for item in edits)


@pytest.mark.parametrize("count", [101, 10000, 10001])
def test_large_generic_result_is_read_completely_with_a_hard_source_limit(
    tmp_path, count
):
    source = tmp_path / "actual.csv"
    source.write_text(
        "object_id,value\n" + "".join(f"o{i},{i}\n" for i in range(count))
    )
    output = SimpleNamespace(
        id=1,
        task_id="task",
        path="actual.csv",
        expired=False,
        key="statistics",
        kind="table",
        checksum=hashlib.sha256(source.read_bytes()).hexdigest(),
        metadata={},
    )
    workflow = SimpleNamespace(owner_id=1, workflow_type="ecology_change", steps=Mock())
    workflow.steps.filter.return_value.exists.return_value = True
    task = SimpleNamespace(id="task", owner_id=1, status="succeeded")
    with (
        patch("apps.agent.demo_results.authorized_task", return_value=task),
        patch("apps.agent.demo_results.app_path", return_value=source),
    ):
        if count > 10000:
            with pytest.raises(ComputeError, match="超过10000行"):
                read_output(workflow, None, {}, output)
        else:
            result = read_output(workflow, None, {}, output)
            assert len(result["rows"]) == result["rowCount"] == count
            assert result["checksum"] == output.checksum and result["scope"] == "all"
            assert (
                len(
                    project_payload({"actualResults": [result]}, 0)["actualResults"][0][
                        "rows"
                    ]
                )
                == 40
            )


def raster_scenario(count=541):
    workflow, stage, results = scenario(count)
    workflow.evidence[0]["trialBinding"]["ruleId"] = "A-05"
    workflow.plan["trialRuleBindings"][0]["ruleId"] = "A-05"
    workflow.plan["algorithms"] = {
        "geology-multi-check": {
            "manifest": {"outputs": [{"key": "alteration_summary"}]}
        }
    }
    summaries = []
    for index, row in enumerate(results[0]["rows"]):
        row.update(
            element="alteration",
            feature_id=f"AG-{index}",
            rule_id="A-05",
            target_code="",
            suggested_action="downweight",
            allowed_actions_json='["keep","downweight","exclude","review"]',
            measurements_json=json.dumps(
                {
                    "raster_protocol": "alteration-pixels-v1",
                    "pixel_count": 100 + index,
                    "area_m2": 1000 + index,
                    "mineral": "chlorite",
                    "rock_group": "siliciclastic",
                    "boundary": "interior",
                }
            ),
        )
        summaries.append(
            {
                "rule_id": "A-05",
                "rule_version": "trial-1",
                "knowledge_id": 200,
                "knowledge_revision": 3,
                "mineral": "chlorite",
                "rock_group": "siliciclastic",
                "boundary": "interior",
                "suggested_action": "downweight",
                "status": "suggested",
                "unit_code": f"unit-{index}",
                "pixel_count": 100 + index,
                "area_m2": 1000 + index,
                "component_count": 1,
            }
        )
    results.append(
        {
            "key": "alteration_summary",
            "outputId": 3,
            "taskId": "task",
            "checksum": "e" * 64,
            "rows": summaries,
        }
    )
    return workflow, stage, results


@pytest.mark.parametrize("count,expected_batches", [(1, 1), (541, 5)])
def test_every_raster_unit_is_explicitly_reviewed_and_only_scoped_edits_expand(
    retry_model, count, expected_batches
):
    workflow, stage, results = raster_scenario(count)
    requests, seen = [], []
    decision, edits = run(workflow, stage, results, requests, seen)
    assert len(requests) == expected_batches
    assert len(edits) == len(seen) == len(set(seen)) == count
    assert all(
        item["action"] == "downweight" and item["weight"] == 0.5 for item in edits
    )
    assert stage["modelBatches"]["coveredMemberCount"] == count
    review, rows = proposal(workflow, {"decision": decision, "edits": edits}, results)
    assert len(rows) == count
    assert all(item["origin"] == "model_reviewed" for item in review["suggestions"])
    recovered = run(workflow, stage, results, requests, seen)
    assert recovered == (decision, edits) and len(requests) == expected_batches


@pytest.mark.parametrize("disposition", ["keep", "reject", "review"])
def test_raster_keep_reject_and_review_are_never_refilled_from_operator_candidate(
    retry_model, disposition
):
    workflow, stage, results = raster_scenario(9)
    requests, seen = [], []
    decision, edits = run(
        workflow, stage, results, requests, seen, disposition=disposition
    )
    review, rows = proposal(workflow, {"decision": decision, "edits": edits}, results)
    assert len(seen) == 9
    if disposition == "keep":
        assert len(rows) == 9 and all(
            row["action"] == "keep" and row["weight"] == 1 for row in rows
        )
        assert all(
            item["action"] == "keep" and item["origin"] == "model_reviewed"
            for item in review["suggestions"]
        )
    else:
        assert edits == rows == review["suggestions"] == []


def test_omitted_raster_group_fails_explicit_coverage_and_never_creates_suggestions(
    retry_model,
):
    workflow, stage, results = raster_scenario(9)
    requests, seen = [], []
    with pytest.raises(ComputeError, match="尚未明确处置"):
        run(workflow, stage, results, requests, seen, disposition="omit")
    assert len(requests) == 2 and stage["modelBatches"]["cursor"] == 0
    review, rows = proposal(
        workflow, {"edits": [], "decision": {"evidenceRefs": []}}, results
    )
    assert rows == review["suggestions"] == []


def test_raster_user_override_obeys_snapshot_actions_and_preserves_model_choice(
    retry_model,
):
    workflow, stage, results = raster_scenario(1)
    results[0]["rows"][0]["allowed_actions_json"] = '["keep","downweight","review"]'
    decision, edits = run(workflow, stage, results, [], [], disposition="keep")
    review, rows = proposal(workflow, {"decision": decision, "edits": edits}, results)
    selected = {review["suggestions"][0]["id"]}
    assert review["suggestions"][0]["action"] == "keep"
    with pytest.raises(ComputeError, match="允许动作"):
        validate_alteration_actions(review, selected, {"AG-0": "exclude"})
    assert validate_alteration_actions(review, selected, {"AG-0": "downweight"}) == {
        "AG-0": "downweight"
    }


@pytest.mark.parametrize("tokens_per_member,expected_batches", [(20, 3), (200, 5)])
def test_preflight_packs_with_production_token_gate_without_generation_and_execution_matches_plan(
    retry_model,
    tokens_per_member,
    expected_batches,
):
    workflow, stage, results = raster_scenario(257)
    policy = default_policy()

    def tokenizer(model, messages, *args):
        payload = json.loads(messages[1]["content"])
        value = expand(payload, payload.get("contextDefinitions", {}))
        return 4000 + tokens_per_member * value["modelBatch"]["memberCount"]

    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch("apps.agent.context.count_tokens", side_effect=tokenizer),
        patch("apps.agent.demo_decisions.provider.stream") as stream,
    ):
        plan = plan_batches(
            workflow, None, policy, stage, results, lambda: None, context=[]
        )
    stream.assert_not_called()
    assert len(plan["batches"]) == expected_batches
    assert workflow.plan["actualModelCallCount"] == 0 and "modelBatches" not in stage
    assert all(
        item["inputTokens"] <= item["inputLimit"] == 15000 for item in plan["batches"]
    )
    stage["modelBatches"] = {
        "sourceSha256": plan["sourceSha256"],
        "memberCount": plan["memberCount"],
        "cursor": 0,
        "batches": [],
        "preflight": plan,
        "status": "planned",
    }
    requests, seen = [], []

    def record(attempt):
        if attempt["status"] == "requesting":
            workflow.plan["actualModelCallCount"] += 1
            attempt["requested"] = True

    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch("apps.agent.context.count_tokens", side_effect=tokenizer),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=provider_fixture(requests, seen),
        ),
    ):
        _, edits = decide(workflow, None, policy, stage, results, lambda: None, record)
    assert len(requests) == workflow.plan["actualModelCallCount"] == expected_batches
    assert len(edits) == len(seen) == len(set(seen)) == 257
    assert [
        batch["stage"]["modelAttempts"][0]["requestSha256"]
        for batch in stage["modelBatches"]["batches"]
    ] == [item["requestSha256"] for item in plan["batches"]]


def test_irreducible_preflight_preserves_parent_input_review_audit_without_generation(
    retry_model,
):
    workflow, stage, results = raster_scenario(1)
    with (
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch("apps.agent.context.count_tokens", return_value=20000),
        patch("apps.agent.demo_decisions.provider.stream") as stream,
        pytest.raises(BudgetReviewRequired),
    ):
        plan_batches(
            workflow, None, default_policy(), stage, results, lambda: None, context=[]
        )
    stream.assert_not_called()
    assert stage["contextBudgetReview"]["kind"] == "input_budget"
    assert stage["contextBudgetReview"]["requested"] is False
    assert stage["modelRequestPayload"]["modelBatch"]["memberCount"] == 1
    assert stage["modelRequestInstruction"] and "modelAttempts" not in stage


def test_bounded_error_display_cannot_hide_an_unreviewed_raster_unit():
    workflow, stage, results = raster_scenario(1)
    edits = [
        {
            "issue_id": f"missing-{i}",
            "action": "downweight",
            "target_code": "",
            "weight": 0.5,
            "reason": "无效对象",
        }
        for i in range(100)
    ]
    edits.append(
        {
            "issue_id": "issue-0",
            "action": "downweight",
            "target_code": "",
            "weight": 2,
            "reason": "非法权重",
        }
    )
    rows, assessment = assess_edits(
        edits, results, model_payload={"actualResults": results}
    )
    assert not rows and len(assessment["errors"]) <= 30
    assert not any(error.get("issue_id") == "issue-0" for error in assessment["errors"])
    assert assessment["unreviewedRasterCount"] == 1
