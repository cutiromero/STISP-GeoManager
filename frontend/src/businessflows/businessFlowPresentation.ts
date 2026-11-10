import type {
  BusinessFlowEvent,
  BusinessFlowNode,
  BusinessFlowNodeState,
  BusinessFlowRun,
} from "../api/generated/types.gen";

export const completedFlowNodes = new Set([
  "succeeded",
  "completed",
  "approved",
  "skipped",
]);
export const flowStateLabels: Record<string, string> = {
  pending: "尚未开始",
  queued: "等待执行",
  running: "执行中",
  executing: "执行中",
  executed: "处理完成",
  reviewing: "独立审核中",
  waiting_review: "独立审核中",
  waiting_human: "等待您决定",
  waiting_approval: "等待您决定",
  waiting_compute: "算子计算中",
  repairing: "返工中",
  revising: "返工中",
  succeeded: "已完成",
  completed: "已完成",
  approved: "已通过",
  failed: "未完成",
  rejected: "需要返工",
  skipped: "已跳过",
  cancelled: "已停止",
  paused: "已暂停",
  interrupted: "已中断",
};

export function nodeStageProgress(
  node: BusinessFlowNode,
  value?: BusinessFlowNodeState,
) {
  const execution = node.kind !== "human";
  const ai = node.review.ai;
  const human = Boolean(
    node.review.human || node.kind === "human" || value?.human.required,
  );
  const succeeded = Boolean(value && completedFlowNodes.has(value.status));
  const executionDone =
    execution &&
    Boolean(
      succeeded ||
      (value &&
        (["succeeded", "completed", "executed"].includes(
          value.executor.status,
        ) ||
          [
            "executed",
            "reviewing",
            "waiting_human",
            "waiting_approval",
          ].includes(value.status))),
    );
  const reviewDone =
    ai &&
    Boolean(
      succeeded ||
      (value &&
        (["passed", "accepted", "succeeded", "completed"].includes(
          value.reviewer.status,
        ) ||
          value.reviewer.decision === "accept")),
    );
  const humanDone =
    human &&
    Boolean(
      succeeded ||
      (value && ["approved", "completed"].includes(value.human.status)),
    );
  return {
    total: Number(execution) + Number(ai) + Number(human),
    done: Number(executionDone) + Number(reviewDone) + Number(humanDone),
    executionDone,
    reviewDone,
    humanDone,
  };
}

export function businessFlowProgress(flow: BusinessFlowRun) {
  let total = 0,
    done = 0;
  const states = new Map(flow.nodes.map((node) => [node.nodeId, node]));
  for (const node of flow.definitionSnapshot.nodes) {
    const progress = nodeStageProgress(node, states.get(node.id));
    total += progress.total;
    done += progress.done;
  }
  return {
    percent:
      flow.status === "succeeded"
        ? 100
        : Math.min(99, total ? Math.round((done * 100) / total) : 0),
    total,
    done,
    completedNodes:
      flow.status === "succeeded"
        ? flow.definitionSnapshot.nodes.length
        : flow.nodes.filter((node) => completedFlowNodes.has(node.status))
            .length,
  };
}

/** A return is drawn only when a persisted rejection identifies its node. */
export function businessFlowReturn(
  events: readonly BusinessFlowEvent[],
  state?: BusinessFlowNodeState,
) {
  if (!state) return undefined;
  const related = events.filter((event) => event.nodeId === state.nodeId);
  const rejection = [...related]
    .reverse()
    .find(
      (event) =>
        (event.actor === "human" && event.kind === "request_changes") ||
        (event.actor === "reviewer" && event.kind === "review_rejected"),
    );
  if (!rejection) return undefined;
  const resolved =
    completedFlowNodes.has(state.status) ||
    related.some(
      (event) =>
        event.id > rejection.id &&
        (rejection.actor === "human"
          ? event.actor === "human" &&
            ["approve", "human_approved"].includes(event.kind)
          : event.actor === "reviewer" &&
            ["review_accepted", "review_passed"].includes(event.kind)),
    );
  const label: [string, string] =
    state.status === "skipped"
      ? ["返工已跳过", "Revision skipped"]
      : !resolved
        ? ["退回此节点", "Returned here"]
        : completedFlowNodes.has(state.status) || rejection.actor === "human"
          ? ["返工后通过", "Passed after revision"]
          : ["返工已复审", "Re-reviewed"];
  return { event: rejection, resolved, label };
}
