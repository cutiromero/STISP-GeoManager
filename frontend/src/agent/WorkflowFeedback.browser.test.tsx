import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { computeApi } from "../api/compute";
import type { AgentWorkflow } from "../api/generated/types.gen";
import { liveComputeTask } from "./computeFlow.testFixtures";
import WorkflowResults from "./WorkflowResults";
import "./agent.css";

function workflow(status: AgentWorkflow["status"] = "failed"): AgentWorkflow {
  return {
    id: "saved-research",
    projectId: 3,
    workflowType: "geology_correction",
    goal: "核对地图",
    model: "qwen",
    status,
    detail: "完整分析响应未保存；本步尚未提交计算。请重新发起分析。",
    currentStep: "review_plan",
    iteration: 1,
    operatorSteps: 0,
    maxIterations: 8,
    maxOperatorSteps: 12,
    executeOperators: true,
    resourceIds: [],
    algorithmVersionId: null,
    parameters: {},
    resultIds: [],
    evidence: [],
    runtime: "worker",
    steps: [],
    createdAt: "",
    updatedAt: "",
    importResults: true,
    resultResourceIds: [],
    planHash: "frozen",
    plan: {
      phase: "decide",
      stageIndex: 0,
      stages: [
        {
          name: "initial_check",
          identifier: "geology-check",
          modelAttempts: [{ status: "requesting", requested: true }],
        },
      ],
    },
  };
}

beforeEach(() => vi.restoreAllMocks());

it("shows a failed model stage, actual reason and next action without a working cursor", async () => {
  const restart = vi.fn();
  render(
    <App>
      <MemoryRouter>
        <WorkflowResults workflow={workflow()} onRestart={restart} />
      </MemoryRouter>
    </App>,
  );
  expect(screen.getByText("初始地图检查")).toBeVisible();
  expect(screen.getByText(/完整分析响应未保存/)).toBeVisible();
  expect(screen.getByText(/原任务记录会保留/)).toBeVisible();
  expect(
    screen.getByText("本步模型分析没有保存完整响应，尚未提交本步算法计算。"),
  ).toBeVisible();
  expect(
    document.querySelector(".agent-activity-mark.is-working"),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "调整后重新发起" }));
  expect(restart).toHaveBeenCalledOnce();
  await page.screenshot({
    path: "../../test-results/workflow-failure-feedback.png",
  });
});

it("shows why a task is paused and offers resume at the original approval gate", () => {
  const resume = vi.fn();
  const saved = {
    ...workflow("paused"),
    pausedFrom: "waiting_approval" as const,
    detail: "用户已暂停，审核计划已保存",
  };
  render(
    <App>
      <MemoryRouter>
        <WorkflowResults workflow={saved} onResume={resume} />
      </MemoryRouter>
    </App>,
  );
  expect(screen.getByText(/回到审核，确认后才会执行/)).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "确认执行" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "继续任务" }));
  expect(resume).toHaveBeenCalledOnce();
});

it("keeps successful calculation outputs downloadable when final model analysis fails", async () => {
  const task = liveComputeTask("succeeded");
  task.outputs[0]!.downloadUrl = "/api/compute/outputs/30/download/";
  vi.spyOn(computeApi, "task").mockResolvedValue(task);
  const saved = workflow();
  saved.plan = {
    phase: "decide",
    stageIndex: 1,
    stages: [{ name: "edit", taskId: task.id }],
    finalStage: { name: "final_analysis" },
  };
  saved.detail = "算法均已完成，但最终报告校验失败。";
  saved.steps = [
    {
      id: 1,
      sequence: 1,
      kind: "submit_operator",
      status: "succeeded",
      message: "实际计算完成",
      computeTaskId: task.id,
      action: {},
      inputRefs: {},
      outputRefs: {},
      metrics: {},
      errorCode: "",
      startedAt: "",
      finishedAt: "",
    },
  ];
  render(
    <App>
      <MemoryRouter>
        <WorkflowResults workflow={saved} />
      </MemoryRouter>
    </App>,
  );
  expect(screen.getByText("整理结论与报告")).toBeVisible();
  await screen.findByText("ndvi.tif");
  expect(screen.getByRole("button", { name: "下载" })).toBeVisible();
});

it("requires explicit rejection confirmation and preserves the submitted feedback on refresh", async () => {
  const review = vi.fn();
  const saved = workflow("waiting_approval");
  saved.plan = {
    ...saved.plan,
    phase: "review_results",
    reviewOutputs: [],
    reviewReason: "证据需人工核验",
  };
  saved.detail = "证据需人工核验";
  const mounted = render(
    <App>
      <MemoryRouter>
        <WorkflowResults workflow={saved} onReview={review} />
      </MemoryRouter>
    </App>,
  );
  const reject = screen.getByRole("button", { name: "不通过并停止" });
  expect(reject).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox", { name: "审核意见" }), {
    target: { value: "调查资料不足，需要补充实测" },
  });
  await waitFor(() => expect(reject).toBeEnabled());
  await page.screenshot({
    path: "../../test-results/workflow-review-feedback.png",
  });
  fireEvent.click(reject);
  expect(review).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole("button", { name: "确认不通过" }));
  await waitFor(() =>
    expect(review).toHaveBeenCalledWith("reject", "调查资料不足，需要补充实测"),
  );
  saved.status = "cancelled";
  saved.detail = "审核未通过，已停止后续处理；候选成果与审核意见保留";
  saved.steps = [
    {
      id: 2,
      sequence: 2,
      kind: "review_feedback",
      status: "succeeded",
      message: "用户审核未通过",
      action: { decision: "reject", feedback: "调查资料不足，需要补充实测" },
      inputRefs: {},
      outputRefs: {},
      metrics: {},
      computeTaskId: "",
      errorCode: "",
      startedAt: "",
      finishedAt: "",
    },
  ];
  mounted.rerender(
    <App>
      <MemoryRouter>
        <WorkflowResults workflow={saved} onReview={review} />
      </MemoryRouter>
    </App>,
  );
  expect(screen.getByText(/已保存的审核意见/).parentElement).toHaveTextContent(
    "调查资料不足，需要补充实测",
  );
  expect(screen.queryByLabelText("人工审核反馈")).not.toBeInTheDocument();
});
