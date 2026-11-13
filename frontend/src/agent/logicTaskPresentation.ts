import type { AgentWorkflow } from "../api/generated/types.gen";
import { record } from "../map/geologyReviewData";

export const logicPhases = ["核对资料", "检查与测量", "处理与复核", "生成成果"];
const active = ["queued", "running", "waiting_compute"];

export function logicPhase(workflow: AgentWorkflow) {
  if (workflow.status === "succeeded") return 4;
  const phase = workflow.plan.phase;
  if (
    !workflow.executeOperators ||
    ["review_mapping", "review_plan", "build_inputs", "inputs_ready"].includes(
      String(phase),
    )
  )
    return 0;
  const stages = Array.isArray(workflow.plan.stages)
    ? workflow.plan.stages.map(record)
    : [];
  const stage = stages[Number(workflow.plan.stageIndex)];
  if (stage?.name === "check") return 1;
  if (
    ["apply", "recheck", "relations", "prospect"].includes(String(stage?.name))
  )
    return 2;
  return workflow.currentStep === "finalize" ||
    (Number(workflow.plan.stageIndex) >= stages.length && stages.length > 0)
    ? 3
    : 1;
}

export function logicRunning(workflow: AgentWorkflow) {
  return active.includes(workflow.status) && !workflow.pauseRequested;
}

export function logicStatus(workflow: AgentWorkflow) {
  if (workflow.pauseRequested && workflow.status !== "paused")
    return "正在暂停";
  const labels: Record<string, string> = {
    queued: "等待处理",
    running: "进行中",
    waiting_compute: "进行中",
    waiting_approval: "待你确认",
    paused: "已暂停",
    succeeded: "已完成",
    cancelled: "已停止",
    failed: "执行失败",
    interrupted: "已中断",
  };
  return labels[workflow.status] ?? workflow.status;
}

export function logicStageNames(workflow: AgentWorkflow) {
  const stages = Array.isArray(workflow.plan.stages)
    ? workflow.plan.stages.map(record)
    : [];
  const names: Record<string, string> = {
    check: "三要素检查",
    apply: "规则处置",
    recheck: "处理后复查",
    relations: "构造交汇",
    prospect: "前后远景比较",
  };
  return Object.fromEntries(
    stages
      .filter((s) => typeof s.taskId === "string")
      .map((s) => [String(s.taskId), names[String(s.name)] ?? String(s.name)]),
  );
}

export function logicCurrentTitle(workflow: AgentWorkflow) {
  if (workflow.pauseRequested && workflow.status !== "paused")
    return "正在保存进度并暂停";
  if (workflow.status === "paused") return "任务已暂停";
  if (workflow.status === "cancelled") return "后续处理已停止";
  if (workflow.status === "failed") return "任务未能完成";
  if (workflow.status === "interrupted") return "访问条件发生变化，任务已中断";
  if (workflow.status === "queued") return "正在排队，等待执行资源";
  if (workflow.status === "succeeded") return "处理结果与待核查事项";
  if (workflow.status === "waiting_approval")
    return workflow.plan.phase === "review_mapping"
      ? "核对这批资料，确认后开始分析"
      : workflow.plan.phase === "review_modifications"
        ? "审阅本次处置范围"
        : "需要你核对后继续";
  if (logicPhase(workflow) === 0) return "正在准备分析资料";
  if (/入库|保存.*成果/.test(workflow.detail)) return "正在保存计算成果";
  const names: Record<string, string> = {
    check: "正在检查岩性、构造与蚀变",
    apply: "正在执行本次授权的处置",
    recheck: "正在复查处理结果",
    relations: "正在核验构造交汇",
    prospect: "正在比较前后远景",
  };
  const stages = Array.isArray(workflow.plan.stages)
    ? workflow.plan.stages.map(record)
    : [];
  return (
    names[String(stages[Number(workflow.plan.stageIndex)]?.name)] ??
    "正在整理结论与报告"
  );
}

export function logicTasks(workflow: AgentWorkflow) {
  const stages = Array.isArray(workflow.plan.stages)
    ? workflow.plan.stages.map(record)
    : [];
  return stages.map((s) => String(s.taskId ?? "")).filter(Boolean);
}

export function logicOutputIds(workflow: AgentWorkflow) {
  const clean = (
    Array.isArray(workflow.plan.stages) ? workflow.plan.stages.map(record) : []
  ).some((s) =>
    (Array.isArray(s.outputs) ? s.outputs.map(record) : []).some(
      (o) => o.key === "final_faults",
    ),
  );
  return (
    Array.isArray(workflow.plan.stages) ? workflow.plan.stages.map(record) : []
  )
    .flatMap((stage) =>
      (Array.isArray(stage.outputs) ? stage.outputs.map(record) : [])
        .filter(
          (o) =>
            !(
              clean &&
              stage.name === "apply" &&
              ["faults", "alterations"].includes(String(o.key))
            ),
        )
        .map((o) => Number(o.outputId)),
    )
    .filter(Number.isSafeInteger);
}
