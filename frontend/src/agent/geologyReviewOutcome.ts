import type { AgentWorkflow } from "../api/generated/types.gen";

export function geologyReviewOutcome(
  workflow: AgentWorkflow | null | undefined,
) {
  if (workflow?.workflowType !== "geology_map_review") return null;
  const outcome = workflow.plan.reviewOutcome;
  if (
    !outcome ||
    typeof outcome !== "object" ||
    Array.isArray(outcome) ||
    !("kind" in outcome)
  )
    return null;
  return outcome.kind === "no_changes" || outcome.kind === "requires_evidence"
    ? outcome.kind
    : null;
}

export function geologyReviewOutcomeLabel(
  kind: "no_changes" | "requires_evidence",
) {
  return kind === "no_changes"
    ? "检查已完成，未修改地图"
    : "检查已完成，待补充证据";
}

export function geologyReviewOutcomeDescription(
  kind: "no_changes" | "requires_evidence",
) {
  return kind === "no_changes"
    ? "本轮规则检查未发现有依据的修改，待检查地质图保持不变。"
    : "本轮检查发现疑点，但现有证据不足以支持修改。请依据检查报告补充资料，待检查地质图保持不变。";
}

export function geologyReviewOriginalMapId(workflow: AgentWorkflow) {
  const inputs = workflow.plan.inputs;
  if (!inputs || typeof inputs !== "object" || !("initial_map" in inputs))
    return null;
  const id = inputs.initial_map;
  return typeof id === "number" && Number.isInteger(id) && id > 0 ? id : null;
}
