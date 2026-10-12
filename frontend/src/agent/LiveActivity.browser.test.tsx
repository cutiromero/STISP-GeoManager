import { fireEvent, render, screen } from "@testing-library/react";
import { App } from "antd";
import { expect, it } from "vitest";
import type {
  AgentWorkflow,
  AgentWorkflowStep,
} from "../api/generated/types.gen";
import LiveActivity from "./LiveActivity";
import ThinkingStream from "./ThinkingStream";
import WorkflowDecisionTimeline from "./WorkflowDecisionTimeline";
import { runActivity, workflowActivity } from "./agentActivity";
import { computeIntent, computeRun } from "./computeFlow.testFixtures";
import "./agent.css";

function workflow(status: AgentWorkflow["status"]): AgentWorkflow {
  return {
    id: "workflow-live",
    projectId: 1,
    workflowType: "ecology_investigation",
    goal: "分析植被变化",
    model: "qwen",
    status,
    detail: "核对实际统计",
    currentStep: "review_plan",
    iteration: 2,
    operatorSteps: 1,
    maxIterations: 8,
    maxOperatorSteps: 12,
    executeOperators: true,
    resourceIds: [10],
    algorithmVersionId: null,
    parameters: {},
    resultIds: [],
    evidence: [],
    runtime: "worker",
    steps: [],
    createdAt: "",
    updatedAt: "",
    plan: {
      phase: "decide",
      stageIndex: 0,
      stages: [
        {
          identifier: "ndvi-change",
          modelAttempts: [
            { status: "requesting", response: "unverified-json-never-show" },
          ],
        },
      ],
    },
    planHash: "verified",
    importResults: true,
    resultResourceIds: [],
  };
}
function step(id: number): AgentWorkflowStep {
  return {
    id,
    sequence: id,
    kind: "analysis_decision",
    status: "succeeded",
    message: "已经核对资料",
    action: {},
    inputRefs: {},
    outputRefs: {},
    metrics: {},
    computeTaskId: "",
    errorCode: "",
    startedAt: "",
    finishedAt: "",
    decision: {
      problem: `判断 ${id}`,
      findings: [`实际统计发现 ${id}`],
      judgement: `当前结论 ${id}`,
      algorithmReason: "依据波段定义选择指数计算",
      resultSummary: "实际算得变化范围",
      uncertainties: ["待补充调查资料"],
      nextAction: "finish",
      evidenceRefs: [],
      modelMode: "real",
      modelName: "Qwen",
    },
  };
}

it("uses actual phase and model request, then stops motion for review and completion", () => {
  const running = workflow("running");
  expect(workflowActivity(running)).toMatchObject({
    state: "working",
    label: "模型正在分析",
  });
  const mounted = render(<LiveActivity activity={workflowActivity(running)} />);
  expect(screen.getByRole("status")).toHaveAttribute(
    "data-activity-state",
    "working",
  );
  expect(
    document.querySelector(".agent-activity-mark.is-working"),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("unverified-json-never-show"),
  ).not.toBeInTheDocument();
  mounted.rerender(
    <LiveActivity activity={workflowActivity(workflow("waiting_approval"))} />,
  );
  expect(screen.getByRole("status")).toHaveTextContent("等待您确认");
  expect(
    document.querySelector(".agent-activity-mark.is-working"),
  ).not.toBeInTheDocument();
  expect(
    document.querySelector(".agent-activity-track"),
  ).not.toBeInTheDocument();
  mounted.rerender(
    <LiveActivity activity={workflowActivity(workflow("succeeded"))} />,
  );
  expect(screen.getByRole("status")).toHaveAttribute(
    "data-activity-state",
    "complete",
  );
  expect(screen.getByRole("status")).toHaveTextContent("研究已完成");
  for (const status of ["failed", "cancelled", "interrupted"] as const)
    expect(workflowActivity(workflow(status)).state).toBe("stopped");
  expect(workflowActivity(workflow("waiting_compute")).label).toBe(
    "算法正在计算",
  );
  mounted.rerender(
    <LiveActivity activity={workflowActivity(workflow("paused"))} />,
  );
  expect(screen.getByRole("status")).toHaveTextContent("科研任务已暂停");
  expect(
    document.querySelector(".agent-activity-mark.is-working"),
  ).not.toBeInTheDocument();
  expect(workflowActivity({ ...running, pauseRequested: true }).label).toBe(
    "正在保存进度并暂停",
  );
});

it("keeps a research task active after its initial chat run finishes", () => {
  const run = computeRun();
  run.computeIntent = undefined;
  run.researchIntent = {
    originRunId: 8,
    revision: "v1",
    scenario: "ecology_investigation",
    status: "running",
    goal: "分析变化",
    message: "计算已开始",
    questions: [],
    inputs: {},
    parameters: {},
    workflowId: "actual",
    inputSummary: [],
  };
  expect(run.status).toBe("succeeded");
  expect(runActivity(run).state).toBe("working");
  run.researchIntent.status = "waiting_approval";
  expect(runActivity(run).state).toBe("waiting");
});

it("follows verified compute progress instead of keeping submitted calculations waiting", () => {
  const run = computeRun({
    ...computeIntent,
    status: "submitted",
    taskId: "verified-task",
  });
  expect(run.status).toBe("succeeded");
  expect(runActivity(run)).toMatchObject({
    state: "working",
    label: "正在读取计算进度",
  });
  for (const state of ["working", "complete", "stopped"] as const) {
    const activity = { state, label: "真实计算状态", detail: "实际任务回执" };
    expect(runActivity(run, [], activity)).toBe(activity);
  }
  run.computeIntent!.status = "collecting";
  expect(
    runActivity(run, [], {
      state: "complete",
      label: "旧计算完成",
      detail: "",
    }),
  ).toMatchObject({ state: "waiting", label: "等待选择计算参数" });
});

it("reveals only newly verified decisions and restores old explanations without replay", () => {
  const first = step(1);
  const mounted = render(
    <App>
      <WorkflowDecisionTimeline steps={[first]} />
    </App>,
  );
  const original = document.querySelector('[data-step-id="1"]');
  expect(original).not.toHaveClass("is-new-decision");
  mounted.rerender(
    <App>
      <WorkflowDecisionTimeline steps={[{ ...first }, step(2)]} />
    </App>,
  );
  expect(document.querySelector('[data-step-id="1"]')).toBe(original);
  const added = document.querySelector('[data-step-id="2"]');
  expect(added).toHaveClass("is-new-decision");
  expect(screen.getByText("实际统计发现 2")).toBeInTheDocument();
  mounted.rerender(
    <App>
      <WorkflowDecisionTimeline steps={[{ ...first }, step(2)]} />
    </App>,
  );
  expect(document.querySelector('[data-step-id="2"]')).toBe(added);
  mounted.unmount();
  render(
    <App>
      <WorkflowDecisionTimeline steps={[first, step(2)]} />
    </App>,
  );
  expect(document.querySelectorAll(".is-new-decision")).toHaveLength(0);
});

it("retains long streamed reasoning, stable old lines and stops the trailing cursor", () => {
  const text = [
    "最早的真实证据",
    ...Array.from({ length: 120 }, (_, n) => `已核对记录 ${n}`),
  ].join("\n");
  const mounted = render(<ThinkingStream text={text} working />);
  const first = screen.getByText("最早的真实证据");
  const reading = screen.getByLabelText("模型思考内容");
  reading.scrollTop = 0;
  fireEvent.scroll(reading);
  expect(document.querySelectorAll(".agent-thinking-line.is-new")).toHaveLength(
    0,
  );
  mounted.rerender(<ThinkingStream text={`${text}\n最新返回的说明`} working />);
  expect(screen.getByText("最早的真实证据")).toBe(first);
  expect(screen.getByText("最新返回的说明")).toHaveClass("is-new");
  expect(document.querySelectorAll(".agent-thinking-line")).toHaveLength(122);
  expect(reading.scrollTop).toBe(0);
  expect(document.querySelector(".agent-stream-cursor")).toBeInTheDocument();
  mounted.rerender(
    <ThinkingStream text={`${text}\n最新返回的说明`} working={false} />,
  );
  expect(
    document.querySelector(".agent-stream-cursor"),
  ).not.toBeInTheDocument();
  expect(screen.getByText("最早的真实证据")).toBeInTheDocument();
});

it("honors the browser motion preference while retaining status and real text", () => {
  const mounted = render(
    <>
      <LiveActivity activity={workflowActivity(workflow("running"))} />
      <ThinkingStream text="" working />
    </>,
  );
  mounted.rerender(
    <>
      <LiveActivity activity={workflowActivity(workflow("running"))} />
      <ThinkingStream text="模型实际返回的说明" working />
    </>,
  );
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (import.meta.env.MODE === "motion-reduced") expect(reduced).toBe(true);
  const label = document.querySelector(".agent-activity-label")!;
  const mark = document.querySelector(".agent-activity-mark.is-working")!;
  expect(screen.getByText("模型实际返回的说明")).toBeInTheDocument();
  expect(getComputedStyle(label).animationName).toBe(
    reduced ? "none" : "agent-light-drift",
  );
  expect(getComputedStyle(mark, "::before").animationName).toBe(
    reduced ? "none" : "agent-activity-orbit",
  );
  if (reduced) {
    expect(
      getComputedStyle(screen.getByText("模型实际返回的说明")).animationName,
    ).toBe("none");
    expect(
      getComputedStyle(screen.getByText("模型实际返回的说明")).opacity,
    ).toBe("1");
  }
});
