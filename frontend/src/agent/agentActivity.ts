import type {
  AgentEvent,
  AgentRun,
  AgentWorkflow,
} from "../api/generated/types.gen";

export type LiveActivity = {
  state: "working" | "waiting" | "complete" | "stopped";
  label: string;
  detail: string;
};

const actions: Record<string, string> = {
  "raster-ndvi": "计算植被指数",
  "ndvi-change": "提取植被变化",
  "ecology-priority": "分析调查优先区",
  "geology-check": "核查地质规则与证据",
  "vector-geometry-repair": "修复地图几何",
  "geology-edit": "修正地质填图",
  "geology-age-check": "核查地层时代与辞书条件",
  "geology-age-edit": "修正地层时代录入",
  finish: "整理分析报告与建议",
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function workflowActivity(workflow: AgentWorkflow): LiveActivity {
  const { status, plan, detail } = workflow;
  if (status === "paused")
    return { state: "waiting", label: "科研任务已暂停", detail };
  if (status === "waiting_approval")
    return { state: "waiting", label: "等待您确认", detail };
  if (status === "succeeded")
    return { state: "complete", label: "研究已完成", detail };
  if (["failed", "cancelled", "interrupted"].includes(status))
    return {
      state: "stopped",
      label:
        status === "failed"
          ? "执行失败"
          : status === "interrupted"
            ? "访问条件变化，已中断"
            : "任务已停止",
      detail,
    };
  if (workflow.pauseRequested)
    return { state: "waiting", label: "正在保存进度并暂停", detail };
  if (status === "queued")
    return { state: "working", label: "等待研究任务开始", detail };
  const stages = Array.isArray(plan.stages) ? plan.stages : [];
  const index = typeof plan.stageIndex === "number" ? plan.stageIndex : -1;
  const stage = record(
    index >= 0 && index < stages.length ? stages[index] : plan.finalStage,
  );
  const attempts = Array.isArray(stage.modelAttempts)
    ? stage.modelAttempts
    : [];
  const requesting =
    !stage.decision &&
    record(attempts[attempts.length - 1]).status === "requesting";
  const stageLabel = actions[String(stage.identifier)] ?? "分析资料与计算结果";
  if (status === "waiting_compute" || plan.phase === "waiting_compute")
    return {
      state: "working",
      label:
        workflow.currentStep === "wait_import"
          ? "正在保存计算成果"
          : "算法正在计算",
      detail: detail || stageLabel,
    };
  const modelActivity = workflow.modelActivity;
  if (modelActivity && !["complete", "failed"].includes(modelActivity.status)) {
    const labels = {
      requesting: "等待模型响应",
      thinking: "模型正在思考",
      responding: "正在接收模型响应",
      validating: "正在校验模型响应",
      complete: "本阶段模型分析已完成",
      failed: "本阶段模型请求失败",
    };
    return {
      state: "working",
      label: labels[modelActivity.status],
      detail: `已接收响应正文 ${modelActivity.outputChars} 字符`,
    };
  }
  if (requesting)
    return { state: "working", label: "模型正在分析", detail: stageLabel };
  return {
    state: "working",
    label: plan.phase === "decide" ? "正在分析下一步" : "正在推进研究",
    detail: detail || stageLabel,
  };
}

export function runActivity(
  run: AgentRun,
  events: AgentEvent[] = [],
  computeActivity?: LiveActivity,
  pollFailure?: string,
): LiveActivity {
  if (run.businessFlow) {
    const flow = run.businessFlow;
    const node = flow.nodes.find((item) => item.nodeId === flow.currentNode);
    const title =
      flow.definitionSnapshot.nodes.find((item) => item.id === flow.currentNode)
        ?.title ?? flow.name;
    if (flow.status === "succeeded")
      return { state: "complete", label: "业务流已完成", detail: title };
    if (["failed", "cancelled", "interrupted"].includes(flow.status))
      return {
        state: "stopped",
        label: flow.status === "cancelled" ? "业务流已停止" : "业务流需要处理",
        detail: node?.reviewer.reason || run.detail,
      };
    if (flow.status === "paused")
      return { state: "waiting", label: "业务流已暂停", detail: title };
    if (flow.status === "waiting_approval")
      return { state: "waiting", label: "业务流等待您决定", detail: title };
    return {
      state: "working",
      label:
        node?.status === "reviewing"
          ? "独立审核智能体正在核对"
          : node?.status === "revising"
            ? "执行智能体正在返修"
            : "执行智能体正在按流程处理",
      detail: title,
    };
  }

  if (["waiting_input", "waiting_review"].includes(run.status))
    return {
      state: "waiting",
      label: run.status === "waiting_review" ? "等待您审核" : "等待您回答",
      detail: run.interaction?.reason ?? run.detail,
    };
  if (run.status === "waiting_compute")
    return {
      state: "working",
      label: "算法正在计算",
      detail: run.detail || "完成后继续读取结果并分析",
    };
  const intent = run.researchIntent;
  if (intent) {
    if (["clarifying", "waiting_approval"].includes(intent.status))
      return {
        state: "waiting",
        label: intent.status === "clarifying" ? "等待您补充" : "等待您确认",
        detail: intent.message,
      };
    if (intent.status === "succeeded")
      return { state: "complete", label: "研究已完成", detail: intent.message };
    if (["failed", "cancelled"].includes(intent.status))
      return {
        state: "stopped",
        label: intent.status === "failed" ? "执行失败" : "任务已停止",
        detail: intent.message,
      };
    return {
      state: "working",
      label: intent.status === "planning" ? "正在分析任务" : "正在推进研究",
      detail: intent.message,
    };
  }
  if (["failed", "cancelled", "interrupted"].includes(run.status))
    return { state: "stopped", label: "本轮已结束", detail: run.detail };
  if (run.computeIntent && !["queued", "running"].includes(run.status)) {
    const compute = run.computeIntent;
    if (compute.status === "submitted")
      return (
        computeActivity ?? {
          state: "working",
          label: "正在读取计算进度",
          detail: compute.message,
        }
      );
    return {
      state: ["blocked", "superseded", "cancelled"].includes(compute.status)
        ? "stopped"
        : "waiting",
      label:
        compute.status === "collecting"
          ? "等待选择计算参数"
          : compute.status === "ready"
            ? "等待开始计算"
            : "请查看计算设置",
      detail: compute.message,
    };
  }
  if (run.status === "succeeded")
    return { state: "complete", label: "回答已完成", detail: "" };
  if (!["queued", "running"].includes(run.status))
    return { state: "stopped", label: "本轮已结束", detail: run.detail };
  if (pollFailure)
    return {
      state: "waiting",
      label: "连接暂时中断，正在恢复",
      detail: pollFailure,
    };
  const last = events[events.length - 1];
  const tool = last?.kind.startsWith("tool_");
  return {
    state: "working",
    label:
      run.status === "queued"
        ? "正在等待模型"
        : tool
          ? "正在查阅资料与处理数据"
          : run.thinkingText && !run.answer && !run.answerPreview
            ? "正在思考"
            : "正在组织回答",
    detail: run.detail || "",
  };
}
