import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentBootstrap,
  AgentRun,
  AgentWorkflow,
} from "../api/generated/types.gen";
import AgentPage from "./AgentPage";

vi.mock("../components/WorkspaceHeader", () => ({
  default: () => (
    <header
      style={{ position: "absolute", top: 8, left: 8, right: 8, height: 50 }}
    >
      STISP
    </header>
  ),
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { id: 99, permissions: {} } }),
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({
    current: "1",
    projects: [{ id: 1, name: "公开" }],
  }),
}));
vi.mock("./useAgentBootstrap", () => ({ useAgentBootstrap: () => bootstrap }));

const bootstrap: AgentBootstrap = {
  canChat: true,
  canAgent: true,
  canManage: false,
  thinkingEnabled: true,
  defaultReasoningEffort: "low",
  internetEnabled: false,
  allowAttachments: false,
  workerOnline: true,
  defaultChatModel: "mock",
  defaultAgentModel: "mock",
  capabilities: [],
  models: [
    {
      alias: "mock",
      name: "Mock",
      allowAgent: true,
      contextWindowTokens: 32768,
      supportsThinking: true,
      supportsVision: false,
      status: "online",
      checkedAt: "",
    },
  ],
};
const conversation = {
  id: 1,
  projectId: 1,
  mode: "chat" as const,
  title: "历史会话",
  archived: false,
  createdAt: "2026-09-24",
  updatedAt: "2026-09-24",
};
function run(id: number, prompt: string, answer = ""): AgentRun {
  return {
    id,
    conversationId: 1,
    model: "mock",
    status: "succeeded",
    prompt,
    answer,
    detail: "",
    evidence: [],
    attachments: [],
    contextTruncated: false,
    createdAt: "2026-09-24",
    updatedAt: "2026-09-24",
  };
}
function workflow(status: AgentWorkflow["status"]): AgentWorkflow {
  return {
    id: "workflow-1",
    projectId: 1,
    workflowType: "research_processing",
    goal: "分析研究区影像",
    model: "mock",
    status,
    detail: "计划已生成",
    currentStep: "plan",
    iteration: 1,
    operatorSteps: 0,
    maxIterations: 3,
    maxOperatorSteps: 3,
    executeOperators: false,
    resourceIds: [10],
    algorithmVersionId: 7,
    parameters: {},
    resultIds: [],
    evidence: [],
    runtime: "worker",
    steps: [],
    createdAt: "2026-09-24",
    updatedAt: "2026-09-24",
    plan: { algorithm: "NDVI", inputNames: { image: "研究区影像" } },
    planHash: "frozen-plan",
    importResults: true,
    resultResourceIds: [],
  };
}
function showAgent(mode: "chat" | "workbench" = "chat") {
  return render(
    <AntApp>
      <MemoryRouter initialEntries={[`/agent/${mode}`]}>
        <AgentPage />
      </MemoryRouter>
    </AntApp>,
  );
}
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
  bootstrap.canManage = false;
  bootstrap.canAgent = true;
  bootstrap.canChat = true;
  bootstrap.allowAttachments = false;
  bootstrap.internetEnabled = false;
  bootstrap.workerOnline = true;
  bootstrap.budgets = {
    enabled: true,
    tier: "standard",
    defaultProfile: "normal",
    maxPromptCharacters: 10000,
    limits: {
      contextWindowTokens: 32768,
      maxOutputTokens: 16384,
      maxRunSeconds: 1800,
    },
    profiles: ["normal", "materials", "reasoning"].map((budgetProfile) => ({
      budgetProfile: budgetProfile as "normal" | "materials" | "reasoning",
      tier: "standard",
      contextWindowTokens: 32768,
      maxOutputTokens: 8192,
      maxRunSeconds: 1800,
      reasoningEffort: "low",
      requestedMaxOutputTokens: null,
    })),
  };
  vi.spyOn(agentApi, "conversations").mockResolvedValue({
    items: [conversation],
  });
  vi.spyOn(agentApi, "detail").mockResolvedValue({
    conversation,
    runs: [run(1, "旧问题", "很长的历史回答。\n".repeat(180))],
  });
  vi.spyOn(agentApi, "resources").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "workflows").mockResolvedValue({ items: [] });
  vi.spyOn(computeApi, "algorithms").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(computeApi, "inputs").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(agentApi, "submit").mockImplementation(async (_id, input) =>
    run(2, input.prompt),
  );
});

it("prefills a knowledge handoff without sending it automatically", async () => {
  render(
    <AntApp>
      <MemoryRouter
        initialEntries={[
          {
            pathname: "/agent/workbench",
            state: {
              query: "核查霞石与石英的适用条件",
              knowledgeEntryIds: [12],
            },
          },
        ]}
      >
        <AgentPage />
      </MemoryRouter>
    </AntApp>,
  );
  await waitFor(() =>
    expect(screen.getByRole("textbox", { name: "输入消息" })).toHaveValue(
      "核查霞石与石英的适用条件",
    ),
  );
  expect(agentApi.submit).not.toHaveBeenCalled();
});

it.each(["chat", "workbench"])(
  "%s sends the selected effort and reveals a new question when scrolled up",
  async (mode) => {
    const { container } = render(
      <AntApp>
        <MemoryRouter initialEntries={[`/agent/${mode}`]}>
          <AgentPage />
        </MemoryRouter>
      </AntApp>,
    );
    await screen.findByText("旧问题");
    expect(
      screen.queryByText("回答由本地模型生成，请核对重要信息"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "调整思考强度" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("深度思考", { exact: true }));
    const trigger = await screen.findByRole("button", { name: "调整思考强度" });
    expect(trigger).toHaveTextContent("轻量");
    fireEvent.click(trigger);
    const slider = await screen.findByRole("slider", { name: "思考强度" });
    fireEvent.keyDown(slider, { key: "End", keyCode: 35 });
    await waitFor(() => expect(trigger).toHaveTextContent("深入"));
    fireEvent.click(trigger);
    const box = container.querySelector<HTMLDivElement>(".agent-messages")!;
    box.scrollTop = 0;
    expect(box.scrollHeight).toBeGreaterThan(box.clientHeight + 250);
    fireEvent.change(
      screen.getByPlaceholderText("输入问题，Enter 发送，Shift+Enter 换行"),
      { target: { value: "最新问题" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /发送/ }));
    await waitFor(() =>
      expect(
        container.querySelector('[data-run-id="2"] .agent-user-message'),
      ).toHaveTextContent("最新问题"),
    );
    const question = container.querySelector(
      '[data-run-id="2"] .agent-user-message',
    )!;
    expect(agentApi.submit).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        thinkingMode: "deep",
        reasoningEffort: "xhigh",
      }),
    );
    await waitFor(() => {
      const bounds = question.getBoundingClientRect();
      expect(box.scrollTop).toBeGreaterThan(0);
      expect(bounds.top).toBeGreaterThanOrEqual(
        box.getBoundingClientRect().top,
      );
      expect(bounds.bottom).toBeLessThanOrEqual(
        box.getBoundingClientRect().bottom,
      );
    });
  },
);

it("restores administrator default and hides the effort control in fast mode", async () => {
  render(
    <AntApp>
      <MemoryRouter initialEntries={["/agent/chat"]}>
        <AgentPage />
      </MemoryRouter>
    </AntApp>,
  );
  await screen.findByText("旧问题");
  fireEvent.click(screen.getByText("深度思考", { exact: true }));
  fireEvent.click(await screen.findByRole("button", { name: "调整思考强度" }));
  fireEvent.keyDown(await screen.findByRole("slider"), {
    key: "End",
    keyCode: 35,
  });
  fireEvent.click(screen.getByRole("button", { name: "使用默认强度" }));
  expect(
    screen.getByRole("button", { name: "调整思考强度" }),
  ).toHaveTextContent("轻量");
  fireEvent.click(screen.getByText("深度思考", { exact: true }));
  expect(
    screen.queryByRole("button", { name: "调整思考强度" }),
  ).not.toBeInTheDocument();
  fireEvent.change(
    screen.getByPlaceholderText("输入问题，Enter 发送，Shift+Enter 换行"),
    { target: { value: "快速问题" } },
  );
  fireEvent.click(screen.getByRole("button", { name: /发送/ }));
  await waitFor(() =>
    expect(agentApi.submit).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        thinkingMode: "fast",
        reasoningEffort: undefined,
      }),
    ),
  );
});

it.each([false, true])(
  "keeps per-answer sources readable without run details for any role (%s)",
  async (manager) => {
    bootstrap.canManage = manager;
    const saved = run(1, "旧问题", "回答引用 [证据 1]");
    saved.generationParameters = {
      inputTokens: 146,
      contextWindowTokens: 262144,
      maxOutputTokens: 65536,
    };
    saved.evidence = [
      {
        id: 1,
        resourceId: 10,
        name: "样本影像",
        tool: "describe_resource",
        result: { name: "样本影像", count: 12 },
        recordedAt: "2026-09-27",
      },
    ];
    vi.mocked(agentApi.detail).mockResolvedValue({
      conversation,
      runs: [saved],
    });
    const { container } = render(
      <AntApp>
        <MemoryRouter initialEntries={["/agent/workbench"]}>
          <AgentPage />
        </MemoryRouter>
      </AntApp>,
    );
    await screen.findByText("旧问题");
    expect(container.querySelector(".agent-evidence")).toBeNull();
    expect(screen.queryByText("管理员未开启")).not.toBeInTheDocument();
    expect(
      screen.queryByText("本轮参数", { exact: false }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("spinbutton", { name: "本次生成上限" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("数据来源与分析"));
    fireEvent.click(await screen.findByText("样本影像"));
    await waitFor(() => expect(screen.getByText("数量")).toBeVisible());
    expect(screen.queryByText("describe_resource")).not.toBeInTheDocument();
    expect(screen.queryByText("运行详情")).not.toBeInTheDocument();
    expect(screen.queryByText(/本轮参数/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "模型与回答设置" }));
    if (manager) {
      fireEvent.click(screen.getByText("高级设置"));
      await waitFor(() =>
        expect(
          screen.getByRole("spinbutton", { name: "本次生成上限" }),
        ).toBeVisible(),
      );
    } else {
      expect(screen.queryByText("高级设置")).not.toBeInTheDocument();
      expect(screen.queryByText("工具调用详情")).not.toBeInTheDocument();
    }
  },
);

it("hides unavailable agent navigation and enables deep thinking for long reasoning", async () => {
  bootstrap.canAgent = false;
  render(
    <AntApp>
      <MemoryRouter initialEntries={["/agent/chat"]}>
        <AgentPage />
      </MemoryRouter>
    </AntApp>,
  );
  await screen.findByText("旧问题");
  expect(
    screen.queryByRole("button", { name: "数据智能体" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "模型与回答设置" }));
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "分析方案" }));
  fireEvent.click(
    await screen.findByText("长推理", {
      selector: ".ant-select-item-option-content",
    }),
  );
  expect(
    await screen.findByRole("button", { name: "调整思考强度" }),
  ).toBeVisible();
  fireEvent.change(
    screen.getByPlaceholderText("输入问题，Enter 发送，Shift+Enter 换行"),
    { target: { value: "推理问题" } },
  );
  fireEvent.click(screen.getByRole("button", { name: /发送/ }));
  await waitFor(() =>
    expect(agentApi.submit).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        thinkingMode: "deep",
        budgetProfile: "reasoning",
        maxOutputTokens: undefined,
      }),
    ),
  );
});

it("drags the sidebar and input, stops on cancel, and remembers their sizes", async () => {
  vi.spyOn(HTMLElement.prototype, "setPointerCapture").mockImplementation(
    () => {},
  );
  const first = showAgent();
  await screen.findByText("旧问题");
  const sidebarHandle = screen.getByRole("separator", {
    name: "调整会话侧栏宽度",
  });
  const inputHandle = screen.getByRole("separator", { name: "调整输入框高度" });
  fireEvent.pointerDown(sidebarHandle, {
    button: 0,
    pointerId: 1,
    clientX: 260,
  });
  fireEvent.pointerMove(sidebarHandle, { pointerId: 1, clientX: 340 });
  fireEvent.pointerUp(sidebarHandle, { pointerId: 1 });
  expect(
    screen
      .getByRole("complementary", { name: "会话侧栏" })
      .getBoundingClientRect().width,
  ).toBe(340);
  fireEvent.pointerDown(inputHandle, { button: 0, pointerId: 2, clientY: 500 });
  fireEvent.pointerMove(inputHandle, { pointerId: 2, clientY: 420 });
  await waitFor(() =>
    expect(inputHandle).toHaveAttribute("aria-valuenow", "144"),
  );
  fireEvent.pointerCancel(inputHandle, { pointerId: 2 });
  fireEvent.pointerMove(inputHandle, { pointerId: 2, clientY: 200 });
  expect(
    screen.getByRole("textbox", { name: "输入消息" }).getBoundingClientRect()
      .height,
  ).toBe(144);
  expect(agentApi.submit).not.toHaveBeenCalled();
  await waitFor(() =>
    expect(
      JSON.parse(localStorage.getItem("agent-layout:99:chat") ?? "null"),
    ).toEqual({ sidebar: 340, input: 144 }),
  );
  first.unmount();
  showAgent();
  expect(
    screen.getByRole("separator", { name: "调整会话侧栏宽度" }),
  ).toHaveAttribute("aria-valuenow", "340");
  expect(
    screen.getByRole("textbox", { name: "输入消息" }).getBoundingClientRect()
      .height,
  ).toBe(144);
  fireEvent.doubleClick(
    screen.getByRole("separator", { name: "调整输入框高度" }),
  );
  expect(
    screen.getByRole("textbox", { name: "输入消息" }).getBoundingClientRect()
      .height,
  ).toBe(64);
});

it("supports keyboard resizing within bounds and preserves a readable conversation", async () => {
  const { container } = showAgent("workbench");
  await screen.findByText("旧问题");
  const sidebarHandle = screen.getByRole("separator", {
    name: "调整会话侧栏宽度",
  });
  const inputHandle = screen.getByRole("separator", { name: "调整输入框高度" });
  expect(sidebarHandle).toHaveAttribute("tabindex", "0");
  expect(sidebarHandle).toHaveAttribute("aria-orientation", "vertical");
  expect(inputHandle).toHaveAttribute("aria-orientation", "horizontal");
  fireEvent.keyDown(sidebarHandle, { key: "Home" });
  fireEvent.keyDown(sidebarHandle, { key: "ArrowLeft" });
  expect(sidebarHandle).toHaveAttribute("aria-valuenow", "216");
  fireEvent.keyDown(sidebarHandle, { key: "ArrowRight" });
  expect(sidebarHandle).toHaveAttribute("aria-valuenow", "232");
  fireEvent.keyDown(inputHandle, { key: "End" });
  fireEvent.keyDown(inputHandle, { key: "ArrowUp" });
  expect(inputHandle.getAttribute("aria-valuenow")).toBe(
    inputHandle.getAttribute("aria-valuemax"),
  );
  const messages = container.querySelector<HTMLElement>(".agent-messages")!;
  expect(messages.getBoundingClientRect().height).toBeGreaterThanOrEqual(120);
  expect(
    screen.getByRole("textbox", { name: "输入消息" }).getBoundingClientRect()
      .bottom,
  ).toBeLessThanOrEqual(window.innerHeight);
  fireEvent.keyDown(inputHandle, { key: "Home" });
  fireEvent.keyDown(inputHandle, { key: "ArrowUp", shiftKey: true });
  expect(inputHandle).toHaveAttribute("aria-valuenow", "96");
  fireEvent.keyDown(sidebarHandle, { key: "Enter" });
  expect(sidebarHandle).toHaveAttribute("aria-valuenow", "260");
});

it("keeps narrow screens usable with a dismissible sidebar and bounded input", async () => {
  try {
    localStorage.setItem(
      "agent-layout:99:agent",
      JSON.stringify({ sidebar: 400, input: 320 }),
    );
    const { container } = showAgent("workbench");
    await screen.findByText("旧问题");
    expect(
      screen.getByRole("separator", { name: "调整会话侧栏宽度" }),
    ).toHaveAttribute("aria-valuenow", "400");
    await page.viewport(390, 844);
    await waitFor(() =>
      expect(
        screen.queryByRole("separator", { name: "调整会话侧栏宽度" }),
      ).toBeNull(),
    );
    const input = screen.getByRole("textbox", { name: "输入消息" });
    const handle = screen.getByRole("separator", { name: "调整输入框高度" });
    expect(input.getBoundingClientRect().height).toBeLessThanOrEqual(270);
    fireEvent.keyDown(handle, { key: "Home" });
    const main = container.querySelector<HTMLElement>(".agent-main")!;
    expect(main.scrollWidth).toBeLessThanOrEqual(main.clientWidth);
    const history = screen.getByRole("button", { name: /^会\s*话$/ });
    fireEvent.click(history);
    const sidebar = screen.getByRole("complementary", { name: "会话侧栏" });
    expect(sidebar).toBeVisible();
    expect(screen.getByRole("button", { name: "关闭会话列表" })).toHaveFocus();
    expect(main).toHaveAttribute("inert");
    expect(sidebar.getBoundingClientRect().width).toBeLessThan(
      window.innerWidth,
    );
    fireEvent.click(screen.getByRole("button", { name: "关闭会话列表" }));
    expect(sidebar).not.toBeVisible();
    fireEvent.click(history);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(sidebar).not.toBeVisible();
    expect(history).toHaveFocus();
    fireEvent.change(input, { target: { value: "窄屏问题" } });
    fireEvent.click(screen.getByRole("button", { name: /发送/ }));
    await waitFor(() =>
      expect(agentApi.submit).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ prompt: "窄屏问题" }),
      ),
    );
  } finally {
    await page.viewport(1600, 900);
  }
});

it.each([
  [1366, 768],
  [1024, 600],
])(
  "keeps workflow drafts and maximum input usable at %s by %s",
  async (width, height) => {
    await page.viewport(width, height);
    try {
      const { container } = showAgent("workbench");
      await screen.findByText("旧问题");
      const handle = screen.getByRole("separator", { name: "调整输入框高度" });
      fireEvent.keyDown(handle, { key: "End" });
      const main = container.querySelector<HTMLElement>(".agent-main")!;
      const messages = container.querySelector<HTMLElement>(".agent-messages")!;
      const composer = container.querySelector<HTMLElement>(".agent-composer")!;
      await waitFor(() => {
        expect(main.scrollHeight).toBeLessThanOrEqual(main.clientHeight + 1);
        expect(composer.getBoundingClientRect().bottom).toBeLessThanOrEqual(
          main.getBoundingClientRect().bottom,
        );
        expect(messages.getBoundingClientRect().height).toBeGreaterThanOrEqual(
          height <= 600 ? 80 : 120,
        );
        expect(main.getBoundingClientRect().top).toBeGreaterThan(
          screen.getByRole("banner").getBoundingClientRect().bottom,
        );
      });
      const expectWithin = (element: HTMLElement, area: HTMLElement) => {
        const bounds = element.getBoundingClientRect();
        const areaBounds = area.getBoundingClientRect();
        expect(bounds.top).toBeGreaterThanOrEqual(areaBounds.top - 1);
        expect(bounds.bottom).toBeLessThanOrEqual(areaBounds.bottom + 1);
      };
      fireEvent.click(screen.getByRole("button", { name: /科研工作流/ }));
      const goal = await screen.findByRole("textbox", { name: "工作流目标" });
      const drawer = document.querySelector<HTMLElement>(
        ".agent-workflow-drawer .ant-drawer-body",
      )!;
      await waitFor(() => {
        goal.scrollIntoView({ block: "nearest" });
        expectWithin(goal, drawer);
      });
      fireEvent.change(goal, { target: { value: "核查研究区数据" } });
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      await waitFor(() => expect(goal).not.toBeVisible());
      fireEvent.click(screen.getByRole("button", { name: /科研工作流/ }));
      await waitFor(() => expect(goal).toBeVisible());
      expect(screen.getByRole("textbox", { name: "工作流目标" })).toHaveValue(
        "核查研究区数据",
      );
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      await waitFor(() => expect(goal).not.toBeVisible());
      fireEvent.click(screen.getByRole("button", { name: "模型与回答设置" }));
      const profile = screen.getByRole("combobox", { name: "分析方案" });
      expectWithin(
        profile,
        document.querySelector<HTMLElement>(".agent-settings-panel")!,
      );
      fireEvent.mouseDown(profile);
      fireEvent.click(
        await screen.findByText("长材料", {
          selector: ".ant-select-item-option-content",
        }),
      );
      fireEvent.click(screen.getByRole("button", { name: "模型与回答设置" }));
      fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
        target: { value: "低高度窗口问题" },
      });
      const sendButton = screen.getByRole("button", { name: /发送/ });
      sendButton.scrollIntoView({ block: "nearest" });
      expectWithin(sendButton, composer);
      expectWithin(sendButton, main);
      fireEvent.click(sendButton);
      await waitFor(() =>
        expect(agentApi.submit).toHaveBeenCalledWith(
          1,
          expect.objectContaining({
            prompt: "低高度窗口问题",
            budgetProfile: "materials",
          }),
        ),
      );
    } finally {
      await page.viewport(1600, 900);
    }
  },
);

it("starts with a compact composer and keeps settings behind controls", async () => {
  const { container } = showAgent("workbench");
  await screen.findByText("旧问题");
  expect(
    screen.getByRole("textbox", { name: "输入消息" }).getBoundingClientRect()
      .height,
  ).toBe(64);
  expect(screen.queryByRole("combobox", { name: "选择模型" })).toBeNull();
  expect(screen.queryByRole("combobox", { name: "限定数据资源" })).toBeNull();
  expect(screen.queryByRole("textbox", { name: "工作流目标" })).toBeNull();
  const main = container.querySelector<HTMLElement>(".agent-main")!;
  const messages = container.querySelector<HTMLElement>(".agent-messages")!;
  expect(messages.clientHeight).toBeGreaterThan(main.clientHeight * 0.6);
});

it.each([96, 176, 240])(
  "preserves a valid saved input height of %s",
  async (input) => {
    localStorage.setItem(
      "agent-layout:99:chat",
      JSON.stringify({ sidebar: 280, input }),
    );
    showAgent();
    await screen.findByText("旧问题");
    expect(
      screen.getByRole("textbox", { name: "输入消息" }).getBoundingClientRect()
        .height,
    ).toBe(input);
  },
);

it("keeps pending approval visible while the drawer is closed and confirms the frozen plan", async () => {
  vi.mocked(agentApi.workflows).mockResolvedValue({
    items: [workflow("running")],
  });
  vi.spyOn(agentApi, "workflow").mockResolvedValue(
    workflow("waiting_approval"),
  );
  vi.spyOn(agentApi, "confirmWorkflow").mockResolvedValue(
    workflow("succeeded"),
  );
  showAgent("workbench");
  await screen.findByText("旧问题");
  expect(screen.queryByRole("dialog")).toBeNull();
  const pending = await screen.findByRole("button", {
    name: /科研工作流.*待确认/,
  });
  expect(agentApi.workflow).toHaveBeenCalledWith("workflow-1");
  fireEvent.click(pending);
  fireEvent.click(
    await screen.findByRole("button", { name: "确认执行并自动入库" }),
  );
  await waitFor(() =>
    expect(agentApi.confirmWorkflow).toHaveBeenCalledWith(
      "workflow-1",
      "frozen-plan",
    ),
  );
  await waitFor(() => expect(screen.queryByText("待确认")).toBeNull());
});

it("submits resources, internet and an attachment selected from the tools menu", async () => {
  bootstrap.allowAttachments = true;
  bootstrap.internetEnabled = true;
  vi.mocked(agentApi.resources).mockResolvedValue({
    items: [
      { id: 10, name: "研究区影像", dataType: "raster", description: "" },
    ],
  });
  vi.spyOn(agentApi, "uploadAttachment").mockResolvedValue({
    id: 5,
    fileName: "资料.txt",
    mediaType: "text/plain",
    sizeBytes: 8,
    kind: "document",
    previewUrl: "",
    extractedText: "测试资料",
    createdAt: "2026-09-24",
  });
  showAgent("workbench");
  await screen.findByText("旧问题");
  fireEvent.click(screen.getByRole("button", { name: "工具与数据" }));
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "限定数据资源" }));
  fireEvent.click(
    await screen.findByText("研究区影像", {
      selector: ".ant-select-item-option-content",
    }),
  );
  fireEvent.click(screen.getByRole("switch", { name: "联网检索" }));
  const file = new File(["测试资料"], "资料.txt", { type: "text/plain" });
  fireEvent.change(
    document.querySelector<HTMLInputElement>('input[type="file"]')!,
    { target: { files: [file] } },
  );
  await screen.findByText("资料.txt", {
    selector: ".agent-attachments-row .ant-tag",
  });
  expect(agentApi.uploadAttachment).toHaveBeenCalledWith(
    1,
    expect.objectContaining({ name: "资料.txt" }),
  );
  fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
    target: { value: "结合资料分析研究区" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() =>
    expect(agentApi.submit).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        resourceIds: [10],
        attachmentIds: [5],
        internetEnabled: true,
      }),
    ),
  );
});

it("shows an error with a retry action without exposing run details", async () => {
  const failed = {
    ...run(1, "重试问题"),
    status: "failed" as const,
    detail: "数据处理未完成，请重试",
  };
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [failed],
  });
  showAgent("workbench");
  expect(await screen.findByText("数据处理未完成，请重试")).toBeVisible();
  expect(screen.queryByText("运行详情")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /重\s*试/ }));
  await waitFor(() =>
    expect(agentApi.submit).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ prompt: "重试问题" }),
    ),
  );
});

it("creates one conversation when the first action uploads multiple documents", async () => {
  bootstrap.allowAttachments = true;
  vi.mocked(agentApi.conversations).mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "create").mockResolvedValue({ ...conversation, id: 8 });
  vi.spyOn(agentApi, "uploadAttachment").mockImplementation(
    async (_id, file) => ({
      id: file.name === "首份资料.txt" ? 6 : 7,
      fileName: file.name,
      mediaType: "text/plain",
      sizeBytes: 8,
      kind: "document",
      previewUrl: "",
      extractedText: "首份资料",
      createdAt: "2026-09-24",
    }),
  );
  showAgent();
  fireEvent.click(screen.getByRole("button", { name: "工具与数据" }));
  fireEvent.change(
    document.querySelector<HTMLInputElement>('input[type="file"]')!,
    {
      target: {
        files: [
          new File(["首份资料"], "首份资料.txt", { type: "text/plain" }),
          new File(["另一份资料"], "第二份资料.txt", { type: "text/plain" }),
        ],
      },
    },
  );
  await screen.findByText("首份资料.txt", {
    selector: ".agent-attachments-row .ant-tag",
  });
  await screen.findByText("第二份资料.txt", {
    selector: ".agent-attachments-row .ant-tag",
  });
  expect(agentApi.create).toHaveBeenCalledOnce();
  expect(agentApi.uploadAttachment).toHaveBeenCalledTimes(2);
  expect(agentApi.uploadAttachment).toHaveBeenCalledWith(
    8,
    expect.objectContaining({ name: "首份资料.txt" }),
  );
  fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
    target: { value: "解读资料" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() =>
    expect(agentApi.submit).toHaveBeenCalledWith(
      8,
      expect.objectContaining({ attachmentIds: [6, 7] }),
    ),
  );
});
