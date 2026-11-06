import type { AgentWorkflowStep } from "../api/generated/types.gen";

const mainKinds = new Set([
  "field_mapping_confirmed",
  "working_copies",
  "modifications_approved",
  "no_modifications",
  "collect_results",
  "finalize",
]);

const kindNames: Record<string, string> = {
  model_activity: "模型分析进度",
  analysis_model_attempt: "模型响应校验",
  analysis_decision: "分析判断",
  field_mapping: "资料与字段建议",
  field_mapping_confirmed: "资料与字段已确认",
  working_copies: "准备分析资料",
  demo_plan: "分析安排",
  review_feedback: "用户确认记录",
  human_review: "人工复核记录",
  modification_suggestions: "处置建议",
  modifications_approved: "已批准处置范围",
  no_modifications: "无需修改原始资料",
  approved_changes_fixed: "固定已批准的处置",
  submit_operator: "提交算法计算",
  automatic_stage: "按已确认安排自动计算",
  read_results: "核验计算输出",
  collect_results: "计算成果已就绪",
  finalize: "生成综合报告",
};

export function mainWorkflowSteps(steps: AgentWorkflowStep[]) {
  return steps.filter(
    (step) =>
      Boolean(step.decision) ||
      (mainKinds.has(step.kind) && Boolean(step.message.trim())) ||
      (Boolean(step.errorCode) && step.kind !== "analysis_model_attempt"),
  );
}

export function workflowStepTitle(
  step: AgentWorkflowStep,
  taskNames: Record<string, string> = {},
) {
  if (step.decision?.problem.trim()) return step.decision.problem;
  if (step.kind === "collect_results" && taskNames[step.computeTaskId])
    return `${taskNames[step.computeTaskId]}：成果已就绪`;
  const value = step.outputRefs.modelActivity;
  const activity =
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  if (step.kind === "model_activity" && typeof activity.stage === "string")
    return `模型分析：${activity.stage}`;
  return step.message.trim() || kindNames[step.kind] || "运行记录";
}

export function modelAttemptRetried(
  step: AgentWorkflowStep,
  steps: AgentWorkflowStep[],
) {
  if (
    step.status !== "failed" ||
    typeof step.action.stage !== "string" ||
    !["model_activity", "analysis_model_attempt"].includes(step.kind)
  )
    return false;
  return steps.some(
    (later) =>
      later.sequence > step.sequence &&
      later.kind === step.kind &&
      later.status === "succeeded" &&
      later.action.stage === step.action.stage &&
      later.action.batchIndex === step.action.batchIndex,
  );
}
