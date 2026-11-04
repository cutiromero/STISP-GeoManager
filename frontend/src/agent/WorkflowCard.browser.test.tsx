import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { agentApi } from "../api/agent";
import { reviewWorkflow } from "../map/geologyReview.testFixtures";
import WorkflowCard from "./WorkflowCard";
import ResearchIntentCard from "./ResearchIntentCard";
import type { AgentRun, AgentResearchIntent } from "../api/generated/types.gen";

vi.mock("../api/agent", () => ({
  agentApi: { workflow: vi.fn(), poll: vi.fn() },
}));
vi.mock("./WorkflowResults", () => ({
  default: () => <div>完整步骤与模型交互</div>,
  workflowMapResourceIds: (workflow: { resultResourceIds: number[] }) =>
    workflow.resultResourceIds,
}));
beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.useRealTimers());

it("完成的研究历史只发一次card请求，不补读原run或定时轮询", async () => {
  vi.useFakeTimers();
  const workflow = {
    ...reviewWorkflow(true),
    status: "succeeded" as const,
    plan: { ...reviewWorkflow(true).plan, phase: "completed" },
    view: "card" as const,
    steps: [],
    evidence: [],
  };
  const researchIntent: AgentResearchIntent = {
    originRunId: 12,
    revision: "r1",
    scenario: "geology_generic",
    status: "succeeded",
    goal: "检查地质资料",
    message: "完成",
    questions: [],
    inputs: {},
    parameters: {},
    inputSummary: [],
    workflowId: workflow.id,
  };
  const run: AgentRun & { researchIntent: AgentResearchIntent } = {
    id: 12,
    conversationId: 4,
    model: "mock",
    status: "succeeded",
    prompt: "检查",
    answer: "完成",
    detail: "",
    evidence: [],
    attachments: [],
    contextTruncated: false,
    createdAt: "2026-11-04",
    updatedAt: "2026-11-04",
    researchIntent,
  };
  vi.mocked(agentApi.workflow).mockResolvedValue(workflow);
  render(
    <MemoryRouter>
      <ResearchIntentCard run={run} onChanged={vi.fn()} />
    </MemoryRouter>,
  );
  await act(() => vi.advanceTimersByTimeAsync(0));
  expect(agentApi.workflow).toHaveBeenCalledExactlyOnceWith(workflow.id, {
    view: "card",
  });
  expect(screen.getByRole("region", { name: "工作流进度卡片" })).toBeVisible();
  await act(() => vi.advanceTimersByTimeAsync(30000));
  expect(agentApi.workflow).toHaveBeenCalledOnce();
  expect(agentApi.poll).not.toHaveBeenCalled();
});

it("完成卡片不预取过程、计算或报告，展开才请求完整详情", async () => {
  const detail = reviewWorkflow(true);
  const card = {
    ...detail,
    view: "card" as const,
    stepCount: 24,
    steps: [],
    evidence: [],
    modificationReview: undefined,
  };
  vi.mocked(agentApi.workflow).mockResolvedValue(detail);
  render(
    <MemoryRouter>
      <WorkflowCard workflow={card} />
    </MemoryRouter>,
  );
  expect(agentApi.workflow).not.toHaveBeenCalled();
  expect(screen.queryByText("完整步骤与模型交互")).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: /查看过程、证据与模型交互/ }),
  );
  await waitFor(() =>
    expect(screen.getByText("完整步骤与模型交互")).toBeTruthy(),
  );
  expect(agentApi.workflow).toHaveBeenCalledExactlyOnceWith(detail.id, {
    signal: expect.any(AbortSignal),
  });
  fireEvent.click(screen.getByRole("button", { name: "收起明细" }));
  expect(screen.queryByText("完整步骤与模型交互")).toBeNull();
});

it.each(["geology_generic", "geology_multi_element_reasoning"])(
  "%s的对比链接在新标签保留项目和工作流",
  (workflowType) => {
    const workflow = {
      ...reviewWorkflow(true),
      workflowType,
      view: "card" as const,
      resultResourceIds: [201],
      plan: {
        phase: "completed",
        stages: [
          {
            name: "prospect",
            outputs: [{ key: "after_zones", kind: "vector", resourceId: 201 }],
          },
        ],
      },
      steps: [],
      evidence: [],
    };
    render(
      <MemoryRouter>
        <WorkflowCard workflow={workflow} />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "在地理工作台对比成果图层" });
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener");
    const url = new URL(link.getAttribute("href")!, location.origin);
    expect(url.searchParams.get("geologyCompare")).toBe(workflow.id);
    expect(url.searchParams.get("projectTagId")).toBe(
      String(workflow.projectId),
    );
    expect(url.searchParams.has("token")).toBe(false);
    expect(screen.getByRole("region", { name: "工作流进度卡片" })).toBeTruthy();
  },
);
