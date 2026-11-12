"""中断分类与下一步通过已有详情和步骤字段呈现。"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied

from apps.agent.business_flow_context import ContextReviewRequired
from apps.agent.context import InputBudgetError
from apps.agent.provider import ModelError
from apps.agent.workflow_diagnostics import category, record_issue, context_next_action
from apps.compute.packages import ComputeError


@pytest.mark.parametrize(
    "error,expected",
    [
        (PermissionDenied("资料不可用"), "permission"),
        (ContextReviewRequired({"nodeId": "apply", "level": 3}), "budget"),
        (InputBudgetError("没有足够输入空间"), "budget"),
        (ModelError("模型窗口服务不可用"), "model_protocol"),
        (ModelError("无法核实模型窗口或输入 token 数，请稍后重试"), "model_protocol"),
        (ModelError("JSON响应无效"), "model_protocol"),
        (ComputeError("独立审核模型未返回结果正文，未予通过"), "model_protocol"),
        (ModelError("思考与正文已达到本次生成 token 上限"), "budget"),
        (ComputeError("计算未成功"), "operator"),
        (ComputeError("实际检查结果已变化"), "data"),
        (ModelError("模型请求超时"), "timeout"),
    ],
)
def test_failure_category_matches_actionable_boundary(error, expected):
    assert category(error) == expected


@pytest.mark.parametrize("prefix", ["实际检查结果已变化", "结果入库失败"])
def test_long_failure_retains_next_action_and_full_private_reason(prefix):
    workflow = SimpleNamespace(current_step="recheck", detail="")
    reason = prefix + "，完整诊断" * 200
    with patch("apps.agent.workflow.step") as step:
        diagnostic = record_issue(workflow, "data", reason)
    assert len(workflow.detail) <= 300
    assert "下一步" in workflow.detail
    assert diagnostic["nextAction"] in workflow.detail
    assert diagnostic["reason"] == reason
    assert step.call_args.kwargs["action"]["diagnostic"] == diagnostic
    assert step.call_args.kwargs["error_code"] == "data"
    if prefix == "结果入库失败":
        assert workflow.detail.startswith(prefix)


@pytest.mark.parametrize(
    "kind", ["model_call_limit", "operator_call_limit", "model_protocol_error"]
)
def test_context_wait_uses_its_actual_recovery_action_in_persisted_diagnostics(kind):
    workflow = SimpleNamespace(current_step="inputs", detail="")
    action = context_next_action({"kind": kind, "budgetScope": "task"})
    with patch("apps.agent.workflow.step"):
        diagnostic = record_issue(
            workflow, "budget", "实际等待原因", waiting=True, next_action=action
        )
    assert diagnostic["nextAction"] in workflow.detail
    assert "收紧资料范围" not in workflow.detail
    assert (
        "重试本次审核" if kind == "model_protocol_error" else "提高允许调用额度"
    ) in workflow.detail
