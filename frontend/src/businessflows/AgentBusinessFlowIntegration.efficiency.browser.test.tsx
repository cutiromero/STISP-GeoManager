import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import type {
  AgentBootstrap,
  AgentRun,
  BusinessFlowRun,
} from "../api/generated/types.gen";
import { agentApi } from "../api/agent";
import { businessFlowsApi } from "../api/businessFlows";
import AgentPage from "../agent/AgentPage";
import { businessFlowRun, geologySpec } from "./businessFlow.testFixtures";
import platformStyles from "../styles.css?inline";

vi.mock("../components/WorkspaceHeader", () => ({
  default: () => <header>STISP</header>,
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { id: 99, permissions: {} } }),
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({
    current: "1",
    projects: [{ id: 1, name: "当前项目", code: "default" }],
  }),
}));
vi.mock("../agent/useAgentBootstrap", () => ({
  useAgentBootstrapState: () => ({
    bootstrap,
    status: "ready",
    error: "",
    retry: vi.fn(),
  }),
}));
vi.mock("./BusinessFlowLaunch", () => ({
  default: ({ onStarted }: { onStarted: (flow: BusinessFlowRun) => void }) => (
    <button onClick={() => onStarted(flow())}>启动已发布业务流</button>
  ),
}));
const bootstrap: AgentBootstrap = {
  canAgent: true,
  canChat: true,
  canManage: false,
  workerOnline: true,
  thinkingEnabled: false,
  runStreamingEnabled: true,
  internetEnabled: false,
  allowAttachments: false,
  capabilities: [],
  defaultAgentModel: "mock",
  defaultChatModel: "mock",
  models: [
    {
      alias: "mock",
      name: "Mock",
      status: "online",
      supportsThinking: false,
      supportsVision: false,
      allowAgent: true,
      contextWindowTokens: 32768,
      checkedAt: "",
    },
  ],
};
const conversation = {
  id: 31,
  projectId: 1,
  mode: "agent" as const,
  title: "业务任务",
  archived: false,
  createdAt: "",
  updatedAt: "",
};
const flow = (value: Partial<BusinessFlowRun> = {}) =>
  businessFlowRun({ projectId: 1, ...value });
function run(value = flow()): AgentRun {
  return {
    id: 41,
    conversationId: 31,
    model: "mock",
    prompt: "按流程处理",
    answer: "",
    status:
      value.status === "waiting_approval"
        ? "waiting_review"
        : "waiting_compute",
    detail: "流程当前状态",
    resourceIds: [],
    evidence: [],
    attachments: [],
    contextTruncated: false,
    createdAt: "",
    updatedAt: "",
    businessFlow: value,
  };
}
beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.spyOn(agentApi, "conversations").mockResolvedValue({
    items: [conversation],
  });
  vi.spyOn(agentApi, "detail").mockResolvedValue({
    conversation,
    runs: [run()],
  });
  vi.spyOn(agentApi, "resources").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "stream").mockImplementation(
    (_id, _callback, signal) =>
      new Promise((resolve) => {
        signal?.addEventListener("abort", () => resolve(), { once: true });
      }),
  );
});
function show(state?: unknown) {
  return render(
    <App>
      <MemoryRouter initialEntries={[{ pathname: "/agent/workbench", state }]}>
        <AgentPage />
      </MemoryRouter>
    </App>,
  );
}

it("renders the flow as one real task and does not invent a generic answer confirmation", async () => {
  show();
  await screen.findByRole("region", { name: "业务流工作状态" });
  expect(screen.getByRole("button", { name: "批准当前节点" })).toBeEnabled();
  expect(
    screen.queryByRole("button", { name: "提交回答" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
  expect(agentApi.stream).not.toHaveBeenCalled();
  expect(agentApi.resources).not.toHaveBeenCalled();
  expect(screen.queryByText("流程当前状态")).not.toBeInTheDocument();
});

it("reveals a human decision in a narrow scroller and preserves subsequent manual reading", async () => {
  render(
    <>
      <style>{`
        .agent-messages { position: fixed; top: 0; left: 0; height: 340px;
          width: 360px; flex: none; padding: 8px; overflow-y: auto; }
        .business-flow-actors { min-height: 600px; }
        .business-flow-activity-events { min-height: 600px; }
      `}</style>
      <App>
        <MemoryRouter initialEntries={["/agent/workbench"]}>
          <AgentPage />
        </MemoryRouter>
      </App>
    </>,
  );
  const button = await screen.findByRole("button", { name: "批准当前节点" });
  const box = document.querySelector<HTMLElement>(".agent-messages")!;
  await waitFor(() => {
    const frame = box.getBoundingClientRect();
    const bounds = button.getBoundingClientRect();
    expect(bounds.top).toBeGreaterThanOrEqual(frame.top);
    expect(bounds.bottom).toBeLessThanOrEqual(frame.bottom);
    expect(box.scrollTop).toBeGreaterThan(0);
  });
  await act(async () => {
    box.scrollTop = 0;
    fireEvent.scroll(box);
    box.style.width = "375px";
    await new Promise((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(resolve)),
    );
  });
  expect(box.scrollTop).toBe(0);
});
it("a human decision resumes the existing parent through SSE without submitting again", async () => {
  const next = flow({ status: "queued", revision: 5 });
  next.nodes[0]!.human.status = "approved";
  next.nodes[0]!.status = "succeeded";
  vi.spyOn(businessFlowsApi, "decide").mockResolvedValue(next);
  const submit = vi.spyOn(agentApi, "submit");
  show();
  await screen.findByRole("region", { name: "业务流工作状态" });
  fireEvent.click(screen.getByRole("button", { name: "批准当前节点" }));
  await waitFor(() => expect(agentApi.stream).toHaveBeenCalledOnce());
  expect(submit).not.toHaveBeenCalled();
  expect(vi.mocked(agentApi.stream).mock.calls[0]?.[0]).toBe(41);
});
it("the composer stop uses the durable flow control and clears old actor content", async () => {
  const active = flow({ status: "running" });
  active.nodes[0]!.status = "executing";
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [run(active)],
  });
  const cancelled = flow({
    status: "cancelled",
    revision: 9,
    events: [],
    nodes: active.nodes.map((node) => ({
      ...node,
      status: node.status === "executing" ? "cancelled" : node.status,
      executor: { status: "unavailable" },
      reviewer: { status: "unavailable" },
      outputs: {},
      human: { ...node.human, reason: "" },
    })),
  });
  const stop = vi
    .spyOn(businessFlowsApi, "cancel")
    .mockResolvedValue(cancelled);
  const plainStop = vi.spyOn(agentApi, "cancel");
  show();
  await screen.findByRole("button", { name: "停止回答" });
  await act(async () =>
    fireEvent.click(screen.getByRole("button", { name: "停止回答" })),
  );
  expect(stop).toHaveBeenCalledOnce();
  expect(plainStop).not.toHaveBeenCalled();
  await waitFor(() =>
    expect(
      screen.queryByText("执行结果已核对真实资料。"),
    ).not.toBeInTheDocument(),
  );
});
it("catalog handoff opens launch preparation then restores the exact persisted flow conversation", async () => {
  vi.mocked(agentApi.conversations).mockResolvedValue({ items: [] });
  show({
    businessFlowLaunch: {
      definitionId: 2,
      versionId: 21,
      title: "项目资料审阅",
      goal: "按版本分析资料",
    },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "启动已发布业务流" }),
  );
  await screen.findByRole("region", { name: "业务流工作状态" });
  expect(agentApi.detail).toHaveBeenCalledWith(31);
  expect(sessionStorage.getItem("agent-conversation:99:1:agent")).toBe("31");
  expect(
    screen.queryByRole("button", { name: "启动已发布业务流" }),
  ).not.toBeInTheDocument();
});

it.each([
  [1440, 1000],
  [1024, 768],
  [390, 844],
])(
  "keeps live workflow progress to the right and usable at %sx%s without extra reads",
  async (width, height) => {
    await page.viewport(width, height);
    try {
      const value = flow({
        definitionSnapshot: geologySpec,
        name: "岩性—构造—蚀变综合推理",
        currentNode: "apply",
        status: "running",
      });
      value.nodes = geologySpec.nodes.map((node, index) => ({
        nodeId: node.id,
        status: index < 2 ? "succeeded" : index === 2 ? "executing" : "pending",
        attempt: index === 2 ? 2 : index < 2 ? 1 : 0,
        executor: {
          status: index < 2 ? "succeeded" : index === 2 ? "running" : "pending",
          answer:
            index === 2
              ? "正在依据审批反馈补充构造关系与蚀变分布的对应证据。"
              : undefined,
        },
        reviewer: { status: "pending" },
        human: {
          required: node.review.human,
          status: index < 2 ? "approved" : "pending",
          reason: "",
        },
        outputs: {},
      }));
      value.events = [
        {
          id: 3,
          actor: "human",
          nodeId: "apply",
          kind: "request_changes",
          status: "queued",
          message: "请补充构造线与蚀变分布的对应依据，再提交审批。",
          createdAt: "2026-11-10T00:02:00Z",
        },
      ];
      vi.mocked(agentApi.detail).mockResolvedValue({
        conversation,
        runs: [run(value)],
      });
      render(<style>{platformStyles}</style>);
      show();
      const monitor = await screen.findByRole("complementary", {
        name: "业务流实时进度",
      });
      const main = document.querySelector<HTMLElement>(".agent-main")!;
      if (width >= 1200) {
        expect(monitor.getBoundingClientRect().left).toBeGreaterThanOrEqual(
          main.getBoundingClientRect().right,
        );
      } else {
        await page.screenshot({
          path: `../../test-results/business-flow-monitor-collapsed-${width}.png`,
        });
        fireEvent.click(
          within(monitor).getByRole("button", { name: "展开流程进度" }),
        );
      }
      expect(within(monitor).getByText("退回此节点")).toBeVisible();
      expect(within(monitor).getByText("执行中 · 第 2 次")).toBeVisible();
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
      expect(monitor.getBoundingClientRect().right).toBeLessThanOrEqual(width);
      const reads = vi.mocked(agentApi.detail).mock.calls.length;
      await page.screenshot({
        path: `../../test-results/business-flow-monitor-${width}.png`,
      });
      if (width >= 1200) {
        fireEvent.click(
          within(monitor).getByRole("button", { name: "展开流程全图" }),
        );
        const dialog = await screen.findByRole("dialog");
        await waitFor(() =>
          expect(
            Math.abs(dialog.getBoundingClientRect().right - width),
          ).toBeLessThanOrEqual(1),
        );
        expect(
          within(dialog).getByRole("region", {
            name: "业务流程图，可缩放",
          }),
        ).toBeVisible();
        await waitFor(() =>
          expect(
            dialog.querySelectorAll(".flow-return-links path"),
          ).toHaveLength(1),
        );
        await page.screenshot({
          path: "../../test-results/business-flow-return-diagram.png",
        });
      }
      expect(agentApi.detail).toHaveBeenCalledTimes(reads);
      expect(agentApi.resources).not.toHaveBeenCalled();
    } finally {
      await page.viewport(1600, 900);
    }
  },
);
