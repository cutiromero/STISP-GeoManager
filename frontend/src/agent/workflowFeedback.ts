import type { AgentWorkflow } from "../api/generated/types.gen";

export const workflowStatusLabels: Record<AgentWorkflow["status"], string> = {
  queued: "等待处理",
  running: "正在分析",
  waiting_compute: "正在计算与保存",
  waiting_approval: "等待您审核",
  succeeded: "研究已完成",
  failed: "执行失败",
  cancelled: "已停止",
  interrupted: "访问条件变化，已中断",
  paused: "已暂停",
};

const stageLabels: Record<string, string> = {
  early_ndvi: "前期植被指数计算",
  late_ndvi: "后期植被指数计算",
  change: "植被变化分析",
  priority: "调查优先区分析",
  initial_check: "初始地图检查",
  geometry: "地图几何修复",
  check: "修复后地图检查",
  edit: "依据证据修正地图",
  recheck: "最终地图复查",
  final_analysis: "整理结论与报告",
  review_plan: "核对执行计划",
  wait_operator: "算法计算",
  wait_import: "结果入库",
  finalize: "整理成果",
};

export function workflowStageLabel(workflow: AgentWorkflow): string {
  if (workflow.plan.phase === "review_modifications") return "等待用户批准";
  if (workflow.workflowType === "geology_map_review") {
    const names: Record<string, string> = {
      expert_knowledge: "查阅专家知识",
      check: "正在检查地图",
      edit: "正在修正地图",
      recheck: "复核修正后地质图",
      final_analysis: "整理检查报告",
    };
    const stages = Array.isArray(workflow.plan.stages)
      ? workflow.plan.stages
      : [];
    const stage =
      stages[Number(workflow.plan.stageIndex)] ?? workflow.plan.finalStage;
    if (
      stage &&
      typeof stage === "object" &&
      "name" in stage &&
      stage.name === "edit"
    ) {
      const edit = stage as Record<string, unknown>;
      if (!edit.taskId) return "形成修正建议";
      if (edit.status === "completed") return "已修正地图";
      return ["failed", "paused", "cancelled", "interrupted"].includes(
        workflow.status,
      )
        ? "地图修正"
        : "正在修正地图";
    }
    if (
      stage &&
      typeof stage === "object" &&
      "name" in stage &&
      names[String(stage.name)]
    )
      return names[String(stage.name)]!;
  }
  if (workflow.plan.phase === "review_plan") return "核对执行计划";
  const stages = Array.isArray(workflow.plan.stages)
    ? workflow.plan.stages
    : [];
  const index = Number(workflow.plan.stageIndex);
  const value = stages[index] ?? workflow.plan.finalStage;
  const stage =
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  return (
    stageLabels[String(stage.name)] ??
    stageLabels[workflow.currentStep] ??
    (workflow.executeOperators ? "分析与执行" : "匹配资料与算法")
  );
}

export function workflowNextAction(workflow: AgentWorkflow): string {
  switch (workflow.status) {
    case "paused":
      return workflow.pausedFrom === "waiting_approval"
        ? "点击“继续任务”回到审核，确认后才会执行后续步骤。"
        : "点击“继续任务”从已保存位置接着处理；已提交的计算可能已经完成。";
    case "failed":
      return "先查看上述失败原因和已生成文件，调整资料或设置后重新发起任务。原任务记录会保留。";
    case "interrupted":
      return "检查当前项目权限、资料或算法是否仍可使用；恢复访问条件后重新发起任务。";
    case "cancelled":
      return "后续步骤已停止，已有计算与文件保留；需要继续研究时可重新发起任务。";
    case "waiting_approval":
      if (workflow.plan.phase === "review_modifications")
        return "查看发现的问题和专家知识，选择批准的建议；平台仅修正您批准的范围。";
      return workflow.plan.phase === "review_results" ||
        (Array.isArray(workflow.plan.reviewOutputs) &&
          workflow.plan.reviewOutputs.length)
        ? "查看候选成果与审核原因，填写审核意见后选择通过并继续，或不通过并停止。"
        : "核对资料、算法和参数，确认后开始执行。";
    default:
      return "";
  }
}

export function workflowExecutionNote(workflow: AgentWorkflow): string {
  const stages = Array.isArray(workflow.plan.stages)
    ? workflow.plan.stages
    : [];
  const value =
    stages[Number(workflow.plan.stageIndex)] ?? workflow.plan.finalStage;
  const stage =
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  const attempts = Array.isArray(stage.modelAttempts)
    ? stage.modelAttempts
    : [];
  const last = attempts[attempts.length - 1];
  const attempt =
    last && typeof last === "object" && !Array.isArray(last)
      ? (last as Record<string, unknown>)
      : {};
  if (
    workflow.status === "failed" &&
    !stage.taskId &&
    attempt.requested === true &&
    !attempt.response
  )
    return "本步模型分析没有保存完整响应，尚未提交本步算法计算。";
  const saved = stages.filter(
    (value) =>
      value &&
      typeof value === "object" &&
      "status" in value &&
      value.status === "completed",
  ).length;
  return ["failed", "interrupted", "cancelled"].includes(workflow.status) &&
    saved
    ? `已有 ${saved} 个阶段完成，已生成的计算文件仍可在下方查看或下载。`
    : "";
}
