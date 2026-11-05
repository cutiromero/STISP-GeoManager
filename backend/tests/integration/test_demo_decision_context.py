"""Context deduplication preserves complete persisted and freshly read evidence."""

# ruff: noqa: F811

import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.agent.demo_decisions import decide, decision_payload
from apps.agent.decision_budget import BudgetReviewRequired
from apps.compute.packages import ComputeError
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo, scenario  # noqa: F401

pytestmark = pytest.mark.django_db


def decision():
    return {
        "problem": "两期生态调查",
        "findings": ["旧统计的完整发现说明"],
        "judgement": "A区优先调查",
        "uncertainties": ["原因需调查核实"],
        "nextAction": "ecology-priority",
        "algorithmReason": "完整调查表与实际统计共同支持排序",
        "evidenceRefs": [{"kind": "output", "id": "1"}],
        "resultSummary": "旧统计摘要保持完整",
        "modelMode": "real",
        "modelName": "已保存的模型名称",
    }


def output(identity, task, offset):
    return {
        "outputId": identity,
        "taskId": task,
        "key": "statistics",
        "checksum": str(identity) * 64,
        "metadata": {"qualityCheck": {"status": "passed", "metrics": {"rows": 100}}},
        "rows": [
            {"zone_id": str(index), "priority_rank": str(index + offset)}
            for index in range(100)
        ],
        "columns": ["zone_id", "priority_rank"],
        "rowCount": 100,
        "scope": "all",
    }


def previous_analysis(old):
    return {
        "workflowId": "old-workflow",
        "oldDecision": decision(),
        "actualResults": [copy.deepcopy(old)],
        "oldContext": {"resourceId": 10, "revision": "old-revision"},
        "newContext": {"resourceId": 11, "revision": "new-revision"},
        "oldContextChecksum": "a" * 64,
        "newContextChecksum": "b" * 64,
        "addedEvidence": [{"zone_id": "B", "evidence_id": "E2", "source": "新增调查"}],
    }


def test_real_request_dedupes_history_without_changing_complete_rows_or_plan(
    demo, settings
):
    settings.AGENT_MODELS = [
        {
            "alias": "mock",
            "name": "provider测试",
            "model_id": "qwen-fixture",
            "base_url": "http://127.0.0.1:19100/v1",
            "agent": True,
        }
    ]
    workflow = scenario(demo)
    old, new = output(1, "old-task", 1), output(2, "new-task", 2)
    workflow.plan.update(
        algorithms={},
        stages=[{"taskId": "new-task", "decision": decision()}],
        previousAnalysis=previous_analysis(old),
    )
    workflow.save()
    original_plan = copy.deepcopy(workflow.plan)
    results = [old, new]
    original_results = copy.deepcopy(results)
    answer = {
        **decision(),
        "nextAction": "finish",
        "evidenceRefs": [{"kind": "output", "id": "2"}],
    }
    answer.pop("modelMode")
    answer.pop("modelName")
    with (
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=400),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            return_value=iter([json.dumps({"decision": answer, "edits": []})]),
        ) as stream,
    ):
        decide(
            workflow,
            demo["owner"],
            demo["policy"],
            {"name": "final_analysis", "identifier": "finish"},
            results,
            lambda: None,
        )
    payload = json.loads(stream.call_args.args[1][-1]["content"])
    assert payload["actualResults"] == original_results
    assert [len(item["rows"]) for item in payload["actualResults"]] == [100, 100]
    assert "actualResults" not in payload["previousAnalysis"]
    assert payload["previousAnalysis"]["actualResultOutputIds"] == [1]
    execution = payload["executionState"]
    assert execution["currentStage"] == {
        "kind": "final_analysis",
        "state": "analysis_ready",
        "planStatus": None,
        "taskId": None,
        "actualResultOutputIds": [],
    }
    assert execution["previousAnalysis"] == {
        "taskIds": ["old-task"],
        "actualResultOutputIds": [1],
    }
    assert execution["currentRun"] == {
        "submittedTaskIds": ["new-task"],
        "actualResultOutputIds": [2],
        "latestResultTaskId": "new-task",
        "latestStatisticsOutputIds": [2],
    }
    assert execution["unassignedResultOutputIds"] == []
    assert "findings" not in payload["previousAnalysis"]["oldDecision"]
    assert all("findings" not in item for item in payload["previousDecisions"])
    for key, value in decision().items():
        if key != "findings":
            assert payload["previousAnalysis"]["oldDecision"][key] == value
            assert all(item[key] == value for item in payload["previousDecisions"])
    for key in (
        "oldContext",
        "newContext",
        "oldContextChecksum",
        "newContextChecksum",
        "addedEvidence",
    ):
        assert (
            payload["previousAnalysis"][key] == original_plan["previousAnalysis"][key]
        )
    assert results == original_results
    assert workflow.plan == original_plan
    workflow.refresh_from_db()
    assert workflow.plan == original_plan
    assert workflow.plan["previousAnalysis"]["actualResults"][0]["rows"] == old["rows"]
    assert (
        workflow.plan["previousAnalysis"]["oldDecision"]["findings"]
        == decision()["findings"]
    )


def planned_update(old):
    stage = {
        "name": "observation_ranking",
        "identifier": "rank-observations",
        "status": "pending",
        "outputs": [],
        "bindings": {"context": "observations", "change": "previous_change"},
    }
    previous = previous_analysis(old)
    previous["addedEvidence"] = [
        {
            "zone_id": f"任意区域{index}",
            "evidence_id": f"新增观测{index}",
            "observation": "实际采样信息",
        }
        for index in range(100)
    ]
    workflow = SimpleNamespace(
        goal="根据实际新增观测更新调查排序",
        evidence=[],
        plan={
            "stages": [stage],
            "algorithms": {stage["identifier"]: {"versionId": 77}},
            "previousAnalysis": previous,
        },
    )
    return workflow, stage


def test_unsubmitted_update_separates_old_results_from_planned_calculation():
    old = output(101, "earlier-run", 9)
    workflow, stage = planned_update(old)
    context = [
        {
            "role": "observations",
            "resourceId": 11,
            "title": "新增实测观测资料",
            "rows": workflow.plan["previousAnalysis"]["addedEvidence"],
        }
    ]
    saved = copy.deepcopy(workflow.plan)
    payload = decision_payload(workflow, stage, context, [old])
    execution = payload["executionState"]
    assert execution["currentStage"] == {
        "kind": "calculation",
        "state": "not_submitted",
        "planStatus": "pending",
        "taskId": None,
        "actualResultOutputIds": [],
    }
    assert execution["currentRun"] == {
        "submittedTaskIds": [],
        "actualResultOutputIds": [],
        "latestResultTaskId": None,
        "latestStatisticsOutputIds": [],
    }
    assert execution["previousAnalysis"] == {
        "taskIds": ["earlier-run"],
        "actualResultOutputIds": [101],
    }
    assert payload["actualResults"] == [old]
    assert len(payload["actualResults"][0]["rows"]) == 100
    assert payload["inputRoles"] == context
    assert len(payload["previousAnalysis"]["addedEvidence"]) == 100
    assert workflow.plan == saved


def test_current_stage_results_and_previous_current_steps_have_distinct_sources():
    old = output(101, "earlier-run", 9)
    workflow, stage = planned_update(old)
    workflow.plan["stages"].insert(
        0, {"name": "first_current_step", "taskId": "first-task", "status": "completed"}
    )
    stage.update(taskId="second-task", status="running")
    first = output(102, "first-task", 3)
    unrelated = output(105, "unassigned-task", 4)
    results = [old, first, unrelated]
    payload = decision_payload(workflow, stage, [], results)
    execution = payload["executionState"]
    assert execution["currentStage"]["state"] == "submitted"
    assert execution["currentStage"]["actualResultOutputIds"] == []
    assert execution["currentRun"]["latestResultTaskId"] == "first-task"
    assert execution["currentRun"]["latestStatisticsOutputIds"] == [102]
    assert execution["unassignedResultOutputIds"] == [105]
    second = output(103, "second-task", 5)
    second_layer = {**output(104, "second-task", 5), "key": "updated_layer"}
    results.extend([second, second_layer])
    saved_results = copy.deepcopy(results)
    execution = decision_payload(workflow, stage, [], results)["executionState"]
    assert execution["currentStage"] == {
        "kind": "calculation",
        "state": "results_available",
        "planStatus": "running",
        "taskId": "second-task",
        "actualResultOutputIds": [103, 104],
    }
    assert execution["currentRun"] == {
        "submittedTaskIds": ["first-task", "second-task"],
        "actualResultOutputIds": [102, 103, 104],
        "latestResultTaskId": "second-task",
        "latestStatisticsOutputIds": [103],
    }
    assert execution["previousAnalysis"]["actualResultOutputIds"] == [101]
    assert results == saved_results


@pytest.mark.parametrize("action", ["rank-observations", "request_review"])
def test_real_update_context_retains_execution_action_and_genuine_review(
    action, demo, settings
):
    settings.AGENT_MODELS = [
        {
            "alias": "mock",
            "name": "provider测试",
            "model_id": "qwen-fixture",
            "base_url": "http://127.0.0.1:19100/v1",
            "agent": True,
        }
    ]
    old = output(101, "earlier-run", 9)
    planned, stage = planned_update(old)
    workflow = scenario(demo)
    workflow.plan = planned.plan
    workflow.evidence = []
    answer = {
        **decision(),
        "nextAction": action,
        "evidenceRefs": [{"kind": "output", "id": "101"}],
    }
    answer.pop("modelMode")
    answer.pop("modelName")
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=400),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            return_value=iter([json.dumps({"decision": answer, "edits": []})]),
        ) as stream,
    ):
        result, _ = decide(
            workflow, demo["owner"], demo["policy"], stage, [old], lambda: None
        )
    assert result["nextAction"] == action
    instruction = stream.call_args.args[1][0]["content"]
    assert "本步算法尚未提交" in instruction
    assert "新增观测尚未应用到旧结果" in instruction
    assert "通过allowedAction提交实际计算" in instruction
    assert "真正的资料缺失、矛盾或质量问题仍可request_review" in instruction
    assert "其本身无需taskId" in instruction
    assert "本轮最新实际统计" in instruction
    payload = json.loads(stream.call_args.args[1][-1]["content"])
    assert payload["executionState"]["currentStage"]["state"] == "not_submitted"
    assert payload["actualResults"] == [old]


def test_update_budget_checks_complete_evidence_without_sampling(demo, settings):
    settings.AGENT_MODELS = [
        {
            "alias": "mock",
            "name": "provider测试",
            "model_id": "qwen-fixture",
            "base_url": "http://127.0.0.1:19100/v1",
            "agent": True,
        }
    ]
    old = output(101, "earlier-run", 9)
    planned, stage = planned_update(old)
    workflow = scenario(demo)
    workflow.plan = planned.plan
    workflow.evidence = []
    original_plan = copy.deepcopy(workflow.plan)
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=100000) as tokens,
        patch("apps.agent.demo_decisions.provider.stream") as stream,
        pytest.raises(BudgetReviewRequired, match="必要证据"),
    ):
        decide(workflow, demo["owner"], demo["policy"], stage, [old], lambda: None)
    stream.assert_not_called()
    payload = stage["modelRequestPayload"]
    assert payload["actualResults"] == [old]
    assert len(payload["actualResults"][0]["rows"]) == 100
    assert len(payload["previousAnalysis"]["addedEvidence"]) == 100
    assert payload["executionState"]["currentRun"]["actualResultOutputIds"] == []
    preserved = copy.deepcopy(workflow.plan)
    for item in preserved["stages"]:
        for key in (
            "contextBudgetReview",
            "modelRequestPayload",
            "modelRequestInstruction",
        ):
            item.pop(key, None)
    assert preserved == original_plan
    assert tokens.call_count == 5


@pytest.mark.parametrize("changed", ["missing", "row", "checksum", "metadata"])
def test_request_refuses_to_remove_old_results_unless_complete_read_matches(changed):
    old = output(1, "old-task", 1)
    results = [copy.deepcopy(old)]
    if changed == "missing":
        results = []
    elif changed == "row":
        results[0]["rows"][-1]["priority_rank"] = "changed"
    elif changed == "checksum":
        results[0]["checksum"] = "c" * 64
    else:
        results[0]["metadata"]["qualityCheck"]["status"] = "needs_review"
    workflow = SimpleNamespace(
        plan={"stages": [], "previousAnalysis": previous_analysis(old)}
    )
    original_plan, original_results = (
        copy.deepcopy(workflow.plan),
        copy.deepcopy(results),
    )
    with pytest.raises(ComputeError, match="完整读取结果不一致"):
        decision_payload(
            workflow, {"name": "final_analysis", "identifier": "finish"}, [], results
        )
    assert workflow.plan == original_plan
    assert results == original_results
