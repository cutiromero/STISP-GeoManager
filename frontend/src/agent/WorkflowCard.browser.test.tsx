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
  default: ({ detailsExpanded }: { detailsExpanded: boolean }) => (
    <div hidden={!detailsExpanded} inert={!detailsExpanded}>
      <span>完整步骤与模型交互</span>
      <details>
        <summary>测试证据</summary>证据内容
      </details>
      <details>
        <summary>默认收起证据</summary>其他证据内容
      </details>
    </div>
  ),
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
  expect(screen.getByText("完整步骤与模型交互")).not.toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: /查看过程、证据与模型交互/ }),
  );
  await waitFor(() =>
    expect(screen.getByText("完整步骤与模型交互")).toBeTruthy(),
  );
  expect(agentApi.workflow).toHaveBeenCalledExactlyOnceWith(detail.id, {
    signal: expect.any(AbortSignal),
    view: "inspection",
    part: "steps",
  });
  fireEvent.click(screen.getByRole("button", { name: "收起明细" }));
  expect(screen.getByText("完整步骤与模型交互")).not.toBeVisible();
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
    const link = screen.getByRole("link", { name: "打开独立对比页" });
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener");
    const url = new URL(link.getAttribute("href")!, location.origin);
    expect(url.searchParams.get("geologyReview")).toBe(workflow.id);
    expect(url.searchParams.has("geologyCompare")).toBe(false);
    expect(url.searchParams.get("projectTagId")).toBe(
      String(workflow.projectId),
    );
    expect(url.searchParams.has("token")).toBe(false);
    expect(screen.getByRole("region", { name: "工作流进度卡片" })).toBeTruthy();
  },
);

it("多次轮询、阶段推进和card/full切换保留详情节点、折叠状态及滚动", async () => {
  const detail = reviewWorkflow();
  const card = { ...detail, view: "card" as const, updatedAt: "poll-0" };
  vi.mocked(agentApi.workflow).mockResolvedValue(detail);
  const view = render(
    <MemoryRouter>
      <div data-testid="scroll" style={{ height: 90, overflow: "auto" }}>
        <WorkflowCard workflow={card} />
        <div style={{ height: 800 }} />
      </div>
    </MemoryRouter>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: /查看过程、证据与模型交互/ }),
  );
  const summary = await screen.findByText("测试证据");
  const evidence = summary.closest("details")!;
  const collapsed = screen.getByText("默认收起证据").closest("details")!;
  fireEvent.click(summary);
  const scroll = screen.getByTestId("scroll");
  const settleLayout = () =>
    act(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
  await settleLayout();
  scroll.scrollTop = 30;
  expect(scroll.scrollTop).toBe(30);
  for (let index = 1; index <= 3; index += 1) {
    let resolve: (value: typeof detail) => void = () => {};
    vi.mocked(agentApi.workflow).mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    view.rerender(
      <MemoryRouter>
        <div data-testid="scroll" style={{ height: 90, overflow: "auto" }}>
          <WorkflowCard workflow={{ ...card, updatedAt: `poll-${index}` }} />
          <div style={{ height: 800 }} />
        </div>
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(agentApi.workflow).toHaveBeenCalledTimes(index + 1),
    );
    await settleLayout();
    expect(screen.getByText("测试证据").closest("details")).toBe(evidence);
    expect(evidence.open).toBe(true);
    expect(collapsed.open).toBe(false);
    expect(scroll.scrollTop).toBe(30);
    await act(async () => resolve({ ...detail, planHash: `stage-${index}` }));
    await settleLayout();
    expect(evidence.open).toBe(true);
    expect(collapsed.open).toBe(false);
    expect(scroll.scrollTop).toBe(30);
  }
  view.rerender(
    <MemoryRouter>
      <div data-testid="scroll" style={{ height: 90, overflow: "auto" }}>
        <WorkflowCard
          workflow={{ ...detail, status: "succeeded", planHash: "finished" }}
        />
        <div style={{ height: 800 }} />
      </div>
    </MemoryRouter>,
  );
  await settleLayout();
  expect(screen.getByText("测试证据").closest("details")).toBe(evidence);
  expect(evidence.open).toBe(true);
  expect(collapsed.open).toBe(false);
  expect(scroll.scrollTop).toBe(30);
  fireEvent.click(screen.getByRole("button", { name: "收起明细" }));
  fireEvent.click(
    screen.getByRole("button", { name: /查看过程、证据与模型交互/ }),
  );
  expect(screen.getByText("测试证据").closest("details")).toBe(evidence);
  expect(evidence.open).toBe(true);
  fireEvent.click(summary);
  await settleLayout();
  expect(evidence.open).toBe(false);
});
