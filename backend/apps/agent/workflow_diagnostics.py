"""通过既有步骤与详情通道记录可操作的中断原因。"""

from django.core.exceptions import PermissionDenied

LABELS = {
    "budget": ("预算", "收紧资料范围或调整本次生成预留后重新分析；不批准任何科研处置"),
    "model_protocol": (
        "模型响应",
        "查看本节点思考、实际响应和诊断后重新分析",
    ),
    "operator": ("算子失败", "查看计算中心该任务的错误和质量报告，修正输入后重试"),
    "data": ("数据不符", "核对资料版本与实际检查结果，重新检查后再确认"),
    "permission": ("权限", "请项目管理员恢复必要资料权限后继续"),
    "timeout": ("超时", "检查模型或计算服务状态后重试；已有结果保留"),
}


def category(error):
    from .business_flow_context import ContextReviewRequired
    from .context import InputBudgetError
    from .provider import ModelError

    if isinstance(error, PermissionDenied):
        return "permission"
    if isinstance(error, (InputBudgetError, ContextReviewRequired)):
        return "budget"
    message = str(error)
    if any(word in message for word in ("超时", "时限", "timeout")):
        return "timeout"
    if "生成" in message and "token" in message.lower() and "上限" in message:
        return "budget"
    if isinstance(error, ModelError):
        return "model_protocol"
    if any(word in message for word in ("预算", "token", "额度")):
        return "budget"
    if any(word in message for word in ("JSON", "响应", "模型", "决策", "引用")):
        return "model_protocol"
    if any(word in message for word in ("计算未成功", "算子", "计算中心")):
        return "operator"
    return "data"


def record_issue(workflow, kind, reason, *, waiting=False):
    from .workflow import step

    label, next_action = LABELS[kind]
    diagnostic = {
        "category": kind,
        "reason": str(reason),
        "nextAction": next_action,
        "nodeId": workflow.current_step,
        "recoverable": waiting,
    }
    step(
        workflow,
        "workflow_diagnostic",
        status="succeeded" if waiting else "failed",
        message=f"[{label}] {reason}；下一步：{next_action}",
        action={"diagnostic": diagnostic},
        error_code=kind,
    )
    brief = str(reason)[:160]
    workflow.detail = (
        f"{brief}；[{label}] 下一步：{next_action}"
        if str(reason).startswith("结果入库失败")
        else f"[{label}] {brief}；下一步：{next_action}"
    )[:300]
    return diagnostic
