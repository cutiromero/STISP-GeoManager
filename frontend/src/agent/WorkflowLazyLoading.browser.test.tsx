import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type { AgentWorkflow } from "../api/generated/types.gen";
import WorkflowPanel from "./WorkflowPanel";

const scenes = [
  {
    scenario: "geology_map_review" as const,
    projectId: 1,
    projectName: "公开",
    title: "地质检查",
  },
  {
    scenario: "ecology_investigation" as const,
    projectId: 1,
    projectName: "公开",
    title: "生态分析",
  },
];
const saved = (scenario = "geology_map_review"): AgentWorkflow => ({
  id: "saved-map-check",
  projectId: 1,
  workflowType: scenario,
  goal: "已保存的地图检查",
  model: "configured",
  status: "waiting_approval",
  detail: "请核对计划",
  currentStep: "review_plan",
  iteration: 0,
  operatorSteps: 0,
  maxIterations: 8,
  maxOperatorSteps: 12,
  executeOperators: false,
  resourceIds: [],
  algorithmVersionId: null,
  parameters: {},
  resultIds: [],
  evidence: [],
  runtime: "durable",
  steps: [],
  createdAt: "2026-11-03",
  updatedAt: "2026-11-03",
  planHash: "saved-hash",
  importResults: true,
  resultResourceIds: [],
  plan: {
    phase: "review_plan",
    inputs: {},
    knowledgeSelection: { mode: "auto", domains: [] },
  },
});
const summary = (items: AgentWorkflow[] = []) => ({
  items,
  total: items.length,
  offset: 0,
  limit: 30,
  hasMore: false,
});

beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.removeItem("workflow-session:76:1");
  sessionStorage.removeItem("workflow-session:76:1:geology_map_review");
  vi.spyOn(agentApi, "researchDemoSummaries").mockResolvedValue({
    items: scenes,
  });
  vi.spyOn(agentApi, "researchDemos").mockImplementation(
    async ({ scenario } = {}) => ({
      items: scenes
        .filter((item) => item.scenario === scenario)
        .map((item) => ({
          ...item,
          prompt: "检查资料",
          available: true,
          sampleNature: "demonstration_case" as const,
          preset: { inputs: {}, parameters: {} },
        })),
    }),
  );
  vi.spyOn(agentApi, "bootstrap").mockResolvedValue({
    knowledgeDomains: [],
  } as never);
  vi.spyOn(agentApi, "resources").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "workflowHistory").mockResolvedValue(summary());
  vi.spyOn(agentApi, "workflows").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "workflow").mockResolvedValue(saved());
  vi.spyOn(computeApi, "algorithms").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(computeApi, "inputs").mockResolvedValue({ items: [], total: 0 });
});
afterEach(() => {
  sessionStorage.removeItem("workflow-session:76:1");
  sessionStorage.removeItem("workflow-session:76:1:geology_map_review");
});
const panel = (open = true) => (
  <App>
    <MemoryRouter>
      <WorkflowPanel
        model="configured"
        resourceIds={[]}
        userId={76}
        embedded
        open={open}
      />
    </MemoryRouter>
  </App>
);
async function choose(label: string, value: string) {
  const field = await screen.findByRole("combobox", { name: label });
  await waitFor(() => expect(field).toBeEnabled());
  fireEvent.mouseDown(field);
  fireEvent.click(
    await screen.findByText(value, {
      selector: ".ant-select-item-option-content",
    }),
  );
}

it("does no closed work and initially loads only lightweight scene names", async () => {
  const view = render(panel(false));
  await new Promise((resolve) => setTimeout(resolve, 30));
  expect(agentApi.researchDemoSummaries).not.toHaveBeenCalled();
  expect(agentApi.workflowHistory).not.toHaveBeenCalled();
  expect(agentApi.workflows).not.toHaveBeenCalled();
  expect(computeApi.inputs).not.toHaveBeenCalled();
  view.rerender(panel(true));
  await waitFor(() =>
    expect(agentApi.researchDemoSummaries).toHaveBeenCalledOnce(),
  );
  await screen.findByText(
    "选择研究场景后加载本项目资料和您在该场景下的历史任务。",
  );
  expect(agentApi.researchDemos).not.toHaveBeenCalled();
  expect(agentApi.resources).not.toHaveBeenCalled();
  expect(agentApi.workflowHistory).not.toHaveBeenCalled();
  expect(computeApi.algorithms).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("textbox", { name: "工作流目标" }),
  ).not.toBeInTheDocument();
  await choose("研究场景", "地质检查");
  await waitFor(() =>
    expect(agentApi.workflowHistory).toHaveBeenCalledWith({
      workflowType: "geology_map_review",
      offset: 0,
      limit: 30,
      signal: expect.any(AbortSignal),
    }),
  );
  expect(agentApi.workflows).not.toHaveBeenCalled();
  expect(agentApi.researchDemos).toHaveBeenCalledWith({
    scenario: "geology_map_review",
    signal: expect.any(AbortSignal),
  });
  expect(computeApi.inputs).toHaveBeenCalledOnce();
});

it("loads a selected history detail instead of automatically expanding completed history", async () => {
  vi.mocked(agentApi.workflowHistory).mockResolvedValue(summary([saved()]));
  render(panel());
  await choose("研究场景", "地质检查");
  await screen.findByRole("combobox", { name: "历史工作流" });
  expect(agentApi.workflow).not.toHaveBeenCalled();
  await choose("历史工作流", "已保存的地图检查");
  await screen.findByRole("button", { name: "确认执行" });
  expect(agentApi.workflow).toHaveBeenCalledWith("saved-map-check", {
    signal: expect.any(AbortSignal),
  });
});

it("shows loading and discards the late history response after changing scenes", async () => {
  let finish: (value: ReturnType<typeof summary>) => void = () => {};
  vi.mocked(agentApi.workflowHistory).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  render(panel());
  await choose("研究场景", "地质检查");
  await screen.findByText("正在加载当前场景的资料与历史…");
  const oldSignal = vi.mocked(agentApi.workflowHistory).mock.calls[0]![0]
    .signal!;
  await choose("研究场景", "生态分析");
  await waitFor(() => expect(oldSignal.aborted).toBe(true));
  finish(summary([saved()]));
  await waitFor(() =>
    expect(agentApi.workflowHistory).toHaveBeenCalledTimes(2),
  );
  expect(
    screen.queryByRole("combobox", { name: "历史工作流" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "确认执行" }),
  ).not.toBeInTheDocument();
});

it("cancels an old detail and never allows it to replace a newly selected scene", async () => {
  let finish: (value: AgentWorkflow) => void = () => {};
  vi.mocked(agentApi.workflowHistory).mockResolvedValueOnce(summary([saved()]));
  vi.mocked(agentApi.workflow).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  render(panel());
  await choose("研究场景", "地质检查");
  await choose("历史工作流", "已保存的地图检查");
  await screen.findByText("正在恢复所选任务…");
  const oldSignal = vi.mocked(agentApi.workflow).mock.calls[0]![1]!.signal!;
  await choose("研究场景", "生态分析");
  expect(oldSignal.aborted).toBe(true);
  finish(saved());
  await waitFor(() =>
    expect(agentApi.workflowHistory).toHaveBeenCalledTimes(2),
  );
  expect(
    (screen.getByRole("textbox", { name: "工作流目标" }) as HTMLTextAreaElement)
      .value,
  ).toContain("植被变化");
  expect(
    screen.queryByRole("button", { name: "确认执行" }),
  ).not.toBeInTheDocument();
});

it("restores only the user's remembered task when opened, then keeps it across closing", async () => {
  sessionStorage.setItem("workflow-session:76:1", "geology_map_review");
  sessionStorage.setItem(
    "workflow-session:76:1:geology_map_review",
    "saved-map-check",
  );
  const view = render(panel(false));
  expect(agentApi.workflow).not.toHaveBeenCalled();
  view.rerender(panel(true));
  await screen.findByRole("button", { name: "确认执行" });
  expect(agentApi.workflow).toHaveBeenCalledOnce();
  view.rerender(panel(false));
  expect(
    screen.queryByRole("button", { name: "确认执行" }),
  ).not.toBeInTheDocument();
  view.rerender(panel(true));
  await screen.findByRole("button", { name: "确认执行" });
  await waitFor(() => expect(agentApi.workflow).toHaveBeenCalledTimes(2));
});

it("rechecks a reopened approval and replaces a stale cached status with the server status", async () => {
  sessionStorage.setItem("workflow-session:76:1", "geology_map_review");
  sessionStorage.setItem(
    "workflow-session:76:1:geology_map_review",
    "saved-map-check",
  );
  vi.mocked(agentApi.workflow)
    .mockResolvedValueOnce(saved())
    .mockResolvedValue({
      ...saved(),
      status: "paused",
      detail: "另一页面已暂停任务",
    });
  const view = render(panel());
  await screen.findByRole("button", { name: "确认执行" });
  view.rerender(panel(false));
  expect(agentApi.workflow).toHaveBeenCalledOnce();
  view.rerender(panel(true));
  await screen.findByText("另一页面已暂停任务");
  expect(agentApi.workflow).toHaveBeenCalledTimes(2);
  expect(
    screen.queryByRole("button", { name: "确认执行" }),
  ).not.toBeInTheDocument();
});

it("stops polling when closed and refreshes the same running task on reopening", async () => {
  sessionStorage.setItem("workflow-session:76:1", "geology_map_review");
  sessionStorage.setItem(
    "workflow-session:76:1:geology_map_review",
    "saved-map-check",
  );
  const running = { ...saved(), status: "running" as const };
  vi.mocked(agentApi.workflow).mockResolvedValue(running);
  const view = render(panel());
  await waitFor(() => expect(agentApi.workflow).toHaveBeenCalledTimes(2));
  view.rerender(panel(false));
  const calls = vi.mocked(agentApi.workflow).mock.calls.length;
  await new Promise((resolve) => setTimeout(resolve, 1700));
  expect(agentApi.workflow).toHaveBeenCalledTimes(calls);
  view.rerender(panel(true));
  await waitFor(() =>
    expect(
      vi.mocked(agentApi.workflow).mock.calls.length,
    ).toBeGreaterThanOrEqual(calls + 1),
  );
  expect(vi.mocked(agentApi.workflow).mock.calls.at(-1)![0]).toBe(
    "saved-map-check",
  );
});
