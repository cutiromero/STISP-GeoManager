"""Finish an actual check without inventing an edit when none is supported."""

from apps.compute.packages import ComputeError

from .compute_tools import authorized_task
from .demo_results import read_results
from .workflow import step


def finish_without_edits(workflow, user, policy):
    if workflow.workflow_type != "geology_map_review":
        return
    stages = workflow.plan["stages"]
    index = workflow.plan["stageIndex"]
    if index >= len(stages) or stages[index].get("name") != "edit":
        return
    if "modificationReview" in workflow.plan or stages[index].get("taskId"):
        return
    check = next((item for item in stages if item["name"] == "check"), None)
    if not check or check.get("status") != "completed" or not check.get("taskId"):
        return
    task = authorized_task(user, check["taskId"], policy, workflow=workflow)
    results = read_results(workflow, user, policy, task)
    issues = [item for item in results if item["key"] == "issues"]
    if len(issues) != 1 or issues[0].get("scope") != "all":
        raise ComputeError("实际问题清单不完整，不能判断是否需要修改")
    rows = issues[0]["rows"]
    if any(row.get("status") == "repairable" for row in rows):
        return
    if any(row.get("status") != "needs_review" for row in rows):
        raise ComputeError("实际问题状态无法识别，请核对检查输出")
    remaining = stages[index:]
    if any(item.get("taskId") for item in remaining):
        raise ComputeError("已有修正或复核任务，不能改为仅检查")
    outcome = {
        "kind": "requires_evidence" if rows else "no_changes",
        "checkTaskId": str(task.id),
    }
    for item in remaining:
        item.update(status="skipped", skipReason=outcome["kind"])
    workflow.plan.update(reviewOutcome=outcome, stageIndex=len(stages))
    workflow.detail = (
        "检查发现疑点但证据不足，正在整理补充资料建议，尚未修改地图"
        if rows
        else "实际检查未发现本轮规则支持的修改，正在整理检查报告"
    )
    step(workflow, "check_only_outcome", message=workflow.detail, action=outcome)
