import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { agentApi } from "../api/agent";
import type {
  AgentActiveWorkflow,
  AgentWorkflow,
} from "../api/generated/types.gen";
import ActiveWorkflowNotice from "./ActiveWorkflowNotice";

const item: AgentActiveWorkflow = {
  id: "old-task",
  goal: "核对旧地质图。继续执行。",
  workflowType: "research_processing",
  status: "paused",
  updatedAt: "2026-11-04T08:00:00Z",
  projectId: 2,
};
const saved: AgentWorkflow = {
  id: item.id,
  projectId: 2,
  goal: item.goal,
  workflowType: item.workflowType,
  model: "mock",
  status: "paused",
  detail: "在安全边界暂停",
  currentStep: "",
  iteration: 0,
  operatorSteps: 0,
  maxIterations: 12,
  maxOperatorSteps: 12,
  executeOperators: false,
  resourceIds: [],
  algorithmVersionId: null,
  parameters: {},
  plan: {},
  planHash: "",
  importResults: false,
  resultIds: [],
  resultResourceIds: [],
  evidence: [],
  steps: [],
  runtime: "durable",
  createdAt: item.updatedAt,
  updatedAt: item.updatedAt,
};
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(agentApi, "activeWorkflow").mockResolvedValue({ item });
  vi.spyOn(agentApi, "workflow").mockResolvedValue(saved);
  vi.spyOn(agentApi, "cancelWorkflow").mockResolvedValue({
    ...saved,
    status: "cancelled",
  });
});

it("shows blocking task identity and uses the target project for viewing and confirmed cancellation", async () => {
  render(<ActiveWorkflowNotice projectId="1" refreshKey="" />);
  await screen.findByText("已有活动任务：核对旧地质图");
  expect(
    screen.getByText(/场景：通用科研计算；状态：已暂停；更新时间：/),
  ).toBeVisible();
  const view = screen.getByRole("button", { name: "查看" });
  expect(view.textContent).toBe("查看");
  expect(screen.getByRole("button", { name: "取消该任务" }).textContent).toBe(
    "取消该任务",
  );
  fireEvent.click(view);
  await screen.findByText("在安全边界暂停");
  expect(agentApi.workflow).toHaveBeenCalledWith(item.id, {
    projectTagId: "2",
  });
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  fireEvent.click(screen.getByRole("button", { name: "取消该任务" }));
  await screen.findByText("确定取消该任务？");
  expect(agentApi.cancelWorkflow).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "保留任务" }));
  expect(agentApi.cancelWorkflow).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "取消该任务" }));
  vi.mocked(agentApi.activeWorkflow).mockResolvedValue({ item: null });
  fireEvent.click(await screen.findByRole("button", { name: "确认取消" }));
  await waitFor(() =>
    expect(agentApi.cancelWorkflow).toHaveBeenCalledWith(
      item.id,
      undefined,
      "2",
    ),
  );
  await waitFor(() =>
    expect(
      screen.queryByText("已有活动任务：核对旧地质图"),
    ).not.toBeInTheDocument(),
  );
});

it("reports failed cancellation without losing the blocking task", async () => {
  vi.mocked(agentApi.cancelWorkflow).mockRejectedValue(
    new Error("无权访问目标项目"),
  );
  render(<ActiveWorkflowNotice projectId="1" refreshKey="conflict" />);
  fireEvent.click(await screen.findByRole("button", { name: "取消该任务" }));
  fireEvent.click(await screen.findByRole("button", { name: "确认取消" }));
  await screen.findByText("无权访问目标项目");
  expect(screen.getByText("已有活动任务：核对旧地质图")).toBeVisible();
});
