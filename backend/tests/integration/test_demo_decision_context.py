"""Context deduplication preserves complete persisted and freshly read evidence."""

# ruff: noqa: F811

import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.agent.demo_decisions import decide, decision_payload
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
        stages=[
            {"taskId": "old-task", "decision": decision()},
            {"taskId": "new-task", "decision": decision()},
        ],
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
