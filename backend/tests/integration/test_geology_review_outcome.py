"""Actual check outputs can conclude without inventing edits or approvals."""

# ruff: noqa: F811

import csv
import json
from unittest.mock import patch

import pytest

from apps.agent.demo_workflow import _save, advance_demo
from apps.agent.models import AgentWorkflow
from apps.compute.models import ComputeOutput, ComputeTask
from apps.compute.packages import checksum
from apps.core.storage import app_path
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401
from tests.integration.test_geology_map_review_workflow import (
    issue,
    review_case,  # noqa: F401
    waiting_suggestions,
)

pytestmark = pytest.mark.django_db


def checked(env, rows):
    workflow, edit, output = waiting_suggestions(env)
    workflow.plan.pop("modificationReview")
    workflow.plan["phase"] = "decide"
    for key in ("decision", "edits", "modificationsApproval"):
        edit.pop(key, None)
    edit["status"] = "pending"
    workflow.status = "queued"
    path = app_path(output.path)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(issue("a", "fill_gap", "complete"))
        )
        writer.writeheader()
        writer.writerows(rows)
    output.checksum, output.size_bytes = checksum(path), path.stat().st_size
    output.save()
    statistics = path.with_name("statistics.csv")
    statistics.write_text("mapped_area_m2,issue_count\n10000," + str(len(rows)) + "\n")
    stats = ComputeOutput.objects.create(
        task=output.task,
        key="statistics",
        label="检查统计",
        kind="table",
        file_name="statistics.csv",
        path=statistics.relative_to(app_path()).as_posix(),
        checksum=checksum(statistics),
        size_bytes=statistics.stat().st_size,
    )
    _save(workflow)
    return workflow, stats


@pytest.mark.parametrize("needs_evidence", [False, True])
def test_actual_check_finishes_with_model_readback_without_edit_or_approval(
    review_case, settings, needs_evidence
):
    env = review_case
    rows = (
        [issue("a", "fill_gap", "complete", status="needs_review")]
        if needs_evidence
        else []
    )
    workflow, stats = checked(env, rows)
    settings.AGENT_MODELS[0] = {**settings.AGENT_MODELS[0], "model_id": "qwen-test"}
    response = {
        "decision": {
            "problem": "核对本次地图检查结果",
            "findings": ["存在待补资料的疑点" if rows else "本轮规则未发现疑点"],
            "judgement": "尚未修改地图，按实际检查形成报告",
            "uncertainties": ["需要补充调查资料"] if rows else [],
            "nextAction": "finish",
            "algorithmReason": "实际检查不支持直接修改，无需提交修正算法",
            "evidenceRefs": [
                {"kind": "output", "id": str(stats.id)},
                {"kind": "knowledge", "id": str(env["entries"][0].id)},
            ],
            "resultSummary": "检查完成。尚未修改地图。",
        },
        "edits": [],
    }
    messages = []

    def stream(_model, actual_messages, *_args, **_kwargs):
        messages.append(actual_messages)
        return iter([json.dumps(response)])

    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=700),
        patch("apps.agent.demo_decisions.provider.stream", side_effect=stream),
    ):
        advance_demo(workflow.id)
    restored = AgentWorkflow.objects.get(pk=workflow.id)
    assert restored.status == "succeeded", restored.detail
    assert restored.plan["reviewOutcome"] == {
        "kind": "requires_evidence" if rows else "no_changes",
        "checkTaskId": str(stats.task_id),
    }
    assert restored.plan["finalDecision"]["resultSummary"] == "检查完成。尚未修改地图。"
    assert "modificationReview" not in restored.plan
    assert ComputeTask.objects.count() == 1
    assert all(stage["status"] == "skipped" for stage in restored.plan["stages"][2:])
    assert not restored.steps.filter(kind="modifications_approved").exists()
    assert len(messages) == 1
    payload = json.loads(messages[0][-1]["content"])
    assert payload["allowedAction"] == "finish"
    assert payload["reviewOutcome"] == restored.plan["reviewOutcome"]
    assert any(result["outputId"] == stats.id for result in payload["actualResults"])


def test_repairable_issue_keeps_original_user_approval_boundary(review_case):
    workflow, _stats = checked(
        review_case, [issue("a", "fill_gap", "complete", status="repairable")]
    )
    from apps.agent.geology_review_outcome import finish_without_edits

    finish_without_edits(workflow, review_case["owner"], review_case["policy"])
    assert "reviewOutcome" not in workflow.plan
    assert workflow.plan["stageIndex"] == 2
    assert ComputeTask.objects.count() == 1
