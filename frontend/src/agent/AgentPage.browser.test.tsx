import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import { ApiError } from "../api/client";
import type {
  AgentBootstrap,
  AgentConversationDetail,
  AgentRun,
  AgentWorkflow,
} from "../api/generated/types.gen";
import AgentPage from "./AgentPage";
import type { AgentBootstrapStatus } from "./useAgentBootstrap";
import {
  computeIntent,
  computeRun,
  liveComputeTask,
} from "./computeFlow.testFixtures";

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
    projects: [{ id: 1, name: "公开", code: projectCode.value }],
  }),
}));
const projectCode = { value: "default" };
vi.mock("./useAgentBootstrap", () => ({
  useAgentBootstrapState: () => ({
    bootstrap: accessState.value === "confirmed" ? bootstrap : null,
    status: accessState.status,
    error: "权限服务暂时不可用",
    retry: accessState.retry,
  }),
}));
const accessState = {
  value: "confirmed" as "confirmed" | "unknown",
  status: "ready" as AgentBootstrapStatus,
  retry: vi.fn(),
};

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

it("requires confirmation before stopping a streamed response", async () => {
  const responding = {
    ...run(5, "分析影像", "已生成部分回答"),
    status: "running" as const,
  };
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [responding],
  });
  vi.spyOn(agentApi, "poll").mockResolvedValue({
    run: responding,
    events: [],
    cursor: 0,
  });
  const cancel = vi
    .spyOn(agentApi, "cancel")
    .mockResolvedValue({ ...responding, status: "cancelled" });
  showAgent();
  fireEvent.click(await screen.findByRole("button", { name: "停止回答" }));
  const dialog = await screen.findByRole("dialog", { name: "停止这次回答？" });
  expect(cancel).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole("button", { name: "继续回答" }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(cancel).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "停止回答" }));
  fireEvent.click(
    within(await screen.findByRole("dialog")).getByRole("button", {
      name: "停止回答",
    }),
  );
  await waitFor(() => expect(cancel).toHaveBeenCalledExactlyOnceWith(5));
  await screen.findByRole("button", { name: "发送" });
  expect(screen.getByText("已生成部分回答")).toBeInTheDocument();
});

it("restores the parameter card and starts a real task from the same conversation turn", async () => {
  vi.spyOn(agentApi, "detail").mockResolvedValue({
    conversation,
    runs: [computeRun({ ...computeIntent, parameters: { red: 3, nir: 8 } })],
  });
  const updated = computeRun({
    ...computeIntent,
    status: "submitted",
    parameters: { red: 3, nir: 8 },
    taskId: liveComputeTask().id,
    planRevision: "submitted-plan",
  });
  const submitIntent = vi
    .spyOn(agentApi, "updateComputeIntent")
    .mockResolvedValue(updated);
  const task = liveComputeTask("succeeded");
  vi.spyOn(agentApi, "computeTasks").mockResolvedValue({
    items: [
      { task, autoImport: false, trackingStatus: "completed", detail: "" },
    ],
  });
  showAgent("workbench");
  const start = await screen.findByRole("button", { name: "开始计算" });
  await page.screenshot({
    path: "../../test-results/agent-compute-config.png",
  });
  fireEvent.click(start);
  await screen.findByText("计算完成，结果已保存。");
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("当前任务")).getByRole("status"),
    ).toHaveAttribute("data-activity-state", "complete"),
  );
  expect(submitIntent).toHaveBeenCalledWith(
    8,
    expect.objectContaining({
      parameters: { red: 3, nir: 8 },
      autoImport: false,
    }),
  );
  expect(agentApi.submit).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("region", { name: "计算配置" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "在地理工作台查看" }),
  ).toBeInTheDocument();
  await page.screenshot({
    path: "../../test-results/agent-compute-complete.png",
  });
});

it("immediately tracks an automatic task returned from explicit bands in the input", async () => {
  const intent = {
    ...computeIntent,
    status: "submitted" as const,
    parameters: { red: 3, nir: 8 },
    missingParameters: [],
    taskId: liveComputeTask().id,
  };
  vi.spyOn(agentApi, "submit").mockResolvedValue({
    ...computeRun(intent),
    prompt: "计算NDVI，红光第三波段，近红外第八波段",
  });
  vi.spyOn(agentApi, "computeTasks").mockResolvedValue({
    items: [
      {
        task: liveComputeTask("succeeded"),
        autoImport: false,
        trackingStatus: "completed",
        detail: "",
      },
    ],
  });
  showAgent("workbench");
  await screen.findByText("旧问题");
  fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
    target: { value: "计算NDVI，红光第三波段，近红外第八波段" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await screen.findByText("计算完成，结果已保存。");
  expect(agentApi.submit).toHaveBeenCalledOnce();
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("当前任务")).getByRole("status"),
    ).toHaveTextContent("计算已完成"),
  );
  expect(
    screen.queryByRole("region", { name: "计算配置" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByText("运行详情", { exact: true }),
  ).not.toBeInTheDocument();
});

it("uses the live report instead of the initial queued answer and retains later status answers", async () => {
  const initial = {
    ...computeRun({
      ...computeIntent,
      status: "submitted",
      taskId: liveComputeTask().id,
      parameters: { red: 3, nir: 8 },
      missingParameters: [],
    }),
    answer: "计算已提交，当前等待计算资源（0%）。",
  };
  const followup = run(9, "跑完了吗", "已完成，结果可以在下方查看。");
  vi.spyOn(agentApi, "detail").mockResolvedValue({
    conversation,
    runs: [initial, followup],
  });
  vi.spyOn(agentApi, "computeTasks").mockResolvedValue({
    items: [
      {
        task: liveComputeTask("succeeded"),
        autoImport: false,
        trackingStatus: "completed",
        detail: "",
      },
    ],
  });
  showAgent("workbench");
  await screen.findByText("计算完成，结果已保存。");
  expect(screen.queryByText(/当前等待计算资源/)).not.toBeInTheDocument();
  expect(screen.getByText(followup.answer)).toBeVisible();
});
beforeEach(() => {
  projectCode.value = "default";
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
  accessState.value = "confirmed";
  accessState.status = "ready";
  accessState.retry.mockReset();
  bootstrap.canManage = false;
  bootstrap.canAgent = true;
  bootstrap.canChat = true;
  bootstrap.allowAttachments = false;
  bootstrap.internetEnabled = false;
  bootstrap.workerOnline = true;
  bootstrap.algorithmOptions = [
    {
      versionId: 4,
      algorithmId: 1,
      name: "NDVI植被指数",
      version: "1.0.0",
      description: "植被指数",
    },
    {
      versionId: 5,
      algorithmId: 2,
      name: "NDWI水体指数",
      version: "1.0.0",
      description: "水体指数",
    },
  ];
  bootstrap.knowledgeDomains = [
    {
      id: "remote_sensing",
      label: "遥感基础",
      description: "遥感方法",
      count: 12,
    },
    {
      id: "pipelines",
      label: "油气管道相关",
      description: "管道监测",
      count: 12,
    },
    {
      id: "geology",
      label: "遥感地质填图逻辑推理",
      description: "地质知识",
      count: 60,
    },
    {
      id: "arid_ecology",
      label: "干旱区生态安全治理",
      description: "生态安全",
      count: 12,
    },
  ];
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
  vi.spyOn(agentApi, "researchDemoSummaries").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "workflowHistory").mockImplementation(
    async ({ workflowType }) => {
      const items = (await agentApi.workflows()).items.filter(
        (item) => item.workflowType === workflowType,
      );
      return {
        items,
        total: items.length,
        offset: 0,
        limit: 30,
        hasMore: false,
      };
    },
  );
  vi.spyOn(agentApi, "prepareWorkflowReport").mockResolvedValue({
    fileName: "MH-workflow报告.md",
    label: "MH-workflow报告",
    contentType: "text/markdown",
    sizeBytes: 300,
    checksum: "verified-report",
    previewUrl: "/api/agent/workflows/workflow-1/report/preview/",
    downloadUrl: "/api/agent/workflows/workflow-1/report/download/",
    resourceId: null,
    resourceName: "",
    resourceLocation: "",
    canDownload: true,
    canImport: true,
  });
  vi.spyOn(computeApi, "algorithms").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(computeApi, "inputs").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(agentApi, "submit").mockImplementation(async (_id, input) =>
    run(2, input.prompt),
  );
});

it.each([
  [0, "fast", undefined],
  [1, "deep", "medium"],
  [2, "deep", "xhigh"],
])(
  "logic project uses effort slider at %s without a deep-thinking switch",
  async (index, mode, effort) => {
    projectCode.value = "02";
    showAgent("workbench");
    await screen.findByText("旧问题");
    const control = screen.getByRole("button", { name: "调整思考强度" });
    expect(
      screen.queryByRole("combobox", { name: "思考" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "深度思考" }),
    ).not.toBeInTheDocument();
    fireEvent.click(control);
    const slider = await screen.findByRole("slider", { name: "思考强度" });
    for (let step = 0; step < index; step++)
      fireEvent.keyDown(slider, { key: "ArrowRight", keyCode: 39 });
    fireEvent.click(control);
    fireEvent.change(
      screen.getByPlaceholderText("输入问题，Enter 发送，Shift+Enter 换行"),
      { target: { value: "核对思考档位" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /发送/ }));
    await waitFor(() =>
      expect(agentApi.submit).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          thinkingMode: mode,
          reasoningEffort: effort,
        }),
      ),
    );
  },
);

it("synchronizes running calculation and terminal status without a second polling request", async () => {
  const task = liveComputeTask("running");
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [
      computeRun({ ...computeIntent, status: "submitted", taskId: task.id }),
    ],
  });
  const computeTasks = vi
    .spyOn(agentApi, "computeTasks")
    .mockResolvedValueOnce({
      items: [
        {
          task,
          autoImport: false,
          trackingStatus: "waiting_compute",
          detail: "",
        },
      ],
    })
    .mockResolvedValue({
      items: [
        {
          task: liveComputeTask("succeeded"),
          autoImport: false,
          trackingStatus: "completed",
          detail: "",
        },
      ],
    });
  showAgent("workbench");
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("当前任务")).getByRole("status"),
    ).toHaveTextContent("算法正在计算"),
  );
  await waitFor(
    () =>
      expect(
        within(screen.getByLabelText("当前任务")).getByRole("status"),
      ).toHaveAttribute("data-activity-state", "complete"),
    { timeout: 5000 },
  );
  expect(computeTasks).toHaveBeenCalledTimes(2);
  expect(
    screen
      .getByRole("button", { name: /^历史会话/ })
      .querySelector(".is-complete"),
  ).toBeInTheDocument();
  expect(
    screen.getByLabelText("当前任务").querySelector(".agent-activity-track"),
  ).not.toBeInTheDocument();
});

it("synchronizes automatic import progress and restores completion after remount", async () => {
  const importing = liveComputeTask("succeeded");
  importing.outputs[0].importStatus = "running";
  const imported = liveComputeTask("succeeded");
  imported.outputs[0].importStatus = "ready";
  imported.outputs[0].resourceId = 163;
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [
      computeRun({
        ...computeIntent,
        status: "submitted",
        taskId: importing.id,
        autoImport: true,
      }),
    ],
  });
  const computeTasks = vi
    .spyOn(agentApi, "computeTasks")
    .mockResolvedValueOnce({
      items: [
        {
          task: importing,
          autoImport: true,
          trackingStatus: "waiting_import",
          detail: "",
        },
      ],
    })
    .mockResolvedValue({
      items: [
        {
          task: imported,
          autoImport: true,
          trackingStatus: "completed",
          detail: "",
        },
      ],
    });
  const mounted = showAgent("workbench");
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("当前任务")).getByRole("status"),
    ).toHaveTextContent("正在保存计算成果"),
  );
  await waitFor(
    () =>
      expect(
        within(screen.getByLabelText("当前任务")).getByRole("status"),
      ).toHaveTextContent("计算与入库已完成"),
    { timeout: 5000 },
  );
  expect(computeTasks).toHaveBeenCalledTimes(2);
  mounted.unmount();
  showAgent("workbench");
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("当前任务")).getByRole("status"),
    ).toHaveAttribute("data-activity-state", "complete"),
  );
  expect(computeTasks).toHaveBeenCalledTimes(3);
});

it("ignores an old computation response after switching conversations", async () => {
  const second = { ...conversation, id: 2, title: "另一会话" };
  vi.mocked(agentApi.conversations).mockResolvedValue({
    items: [conversation, second],
  });
  vi.mocked(agentApi.detail).mockImplementation(async (id) => ({
    conversation: id === 1 ? conversation : second,
    runs:
      id === 1
        ? [
            computeRun({
              ...computeIntent,
              status: "submitted",
              taskId: liveComputeTask().id,
            }),
          ]
        : [{ ...run(20, "另一问题", "另一回答"), conversationId: 2 }],
  }));
  let resolveOld!: (
    value: Awaited<ReturnType<typeof agentApi.computeTasks>>,
  ) => void;
  vi.spyOn(agentApi, "computeTasks").mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveOld = resolve;
      }),
  );
  showAgent("workbench");
  await waitFor(() => expect(agentApi.computeTasks).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByRole("button", { name: /^另一会话/ }));
  await screen.findByText("另一回答");
  resolveOld({
    items: [
      {
        task: liveComputeTask("succeeded"),
        autoImport: true,
        trackingStatus: "completed",
        detail: "",
      },
    ],
  });
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("当前任务")).getByRole("status"),
    ).toHaveTextContent("回答已完成"),
  );
  expect(screen.queryByText("计算与入库已完成")).not.toBeInTheDocument();
});

it("shows a later calculation instead of an older completed research task", async () => {
  const earlier = {
    ...run(7, "研究旧资料"),
    researchIntent: {
      originRunId: 7,
      revision: "saved",
      scenario: "ecology_investigation" as const,
      status: "succeeded" as const,
      goal: "已完成的旧研究",
      message: "研究完成",
      questions: [],
      inputs: {},
      parameters: {},
      workflowId: null,
      inputSummary: [],
    },
  };
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [
      earlier,
      computeRun({
        ...computeIntent,
        status: "submitted",
        taskId: liveComputeTask().id,
      }),
    ],
  });
  vi.spyOn(agentApi, "computeTasks").mockResolvedValue({
    items: [
      {
        task: liveComputeTask("succeeded"),
        autoImport: false,
        trackingStatus: "completed",
        detail: "",
      },
    ],
  });
  showAgent("workbench");
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("当前任务")).getByRole("status"),
    ).toHaveTextContent("计算已完成"),
  );
  expect(
    within(screen.getByLabelText("当前任务")).queryByText("研究已完成"),
  ).not.toBeInTheDocument();
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
              knowledgeSelection: { mode: "manual", domains: ["geology"] },
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
  await screen.findByText("旧问题");
  fireEvent.click(screen.getByRole("button", { name: "知识库" }));
  expect(screen.getByRole("radio", { name: "手选分区" })).toBeChecked();
  expect(
    screen.getByText("遥感地质填图逻辑推理", {
      selector: ".ant-select-selection-item-content",
    }),
  ).toBeInTheDocument();
});

it("shows the authorization message and hides tool controls for a restricted account", async () => {
  bootstrap.canAgent = false;
  showAgent("workbench");
  expect(
    await screen.findByText("当前账号未获准使用此功能，请联系超级管理员。"),
  ).toBeVisible();
  for (const name of ["调用算法", "选择数据", "知识库"])
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  expect(agentApi.resources).not.toHaveBeenCalled();
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
      screen.getByRole("button", { name: "调整思考强度" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText("逻辑推理", { exact: true }));
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

it.each([
  ["chat", "low"],
  ["chat", "medium"],
  ["chat", "xhigh"],
  ["workbench", "low"],
  ["workbench", "medium"],
  ["workbench", "xhigh"],
] as const)(
  "%s enables reasoning with the selected %s effort",
  async (mode, effort) => {
    bootstrap.allowAttachments = true;
    vi.mocked(agentApi.detail).mockResolvedValue({
      conversation,
      runs: [
        run(1, "旧问题", "可以结合项目中的数据、算法和专家知识继续分析。"),
      ],
    });
    showAgent(mode);
    await screen.findByText("旧问题");
    const reasoning = screen.getByRole("button", { name: /逻辑推理/ });
    expect(reasoning).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "调整思考强度" }));
    const slider = await screen.findByRole("slider", { name: "思考强度" });
    await waitFor(() => expect(slider).toBeVisible());
    for (const label of ["轻量", "标准", "深入"])
      expect(screen.getByText(label, { exact: true })).toBeVisible();
    expect(reasoning).toHaveAttribute("aria-pressed", "false");
    if (effort === "low") {
      fireEvent.keyDown(slider, { key: "Home", keyCode: 36 });
      fireEvent.keyUp(slider, { key: "Home", keyCode: 36 });
    } else fireEvent.keyDown(slider, { key: "End", keyCode: 35 });
    if (effort === "medium")
      fireEvent.keyDown(slider, { key: "ArrowLeft", keyCode: 37 });
    await waitFor(() =>
      expect(reasoning).toHaveAttribute("aria-pressed", "true"),
    );
    if (effort === "medium") {
      await waitFor(() =>
        expect(slider.closest(".ant-popover")!.className).not.toMatch(
          /(?:-enter|-appear|-leave)/,
        ),
      );
      await page.screenshot({
        path: `../../test-results/agent-${mode}-effort-levels.png`,
      });
    }
    fireEvent.click(screen.getByRole("button", { name: "调整思考强度" }));
    fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
      target: { value: "分析研究资料" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() =>
      expect(agentApi.submit).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          thinkingMode: "deep",
          reasoningEffort: effort,
          budgetProfile: "normal",
          maxOutputTokens: undefined,
        }),
      ),
    );
  },
);

it("restores administrator default and keeps the effort choices visible without enabling reasoning on open", async () => {
  render(
    <AntApp>
      <MemoryRouter initialEntries={["/agent/chat"]}>
        <AgentPage />
      </MemoryRouter>
    </AntApp>,
  );
  await screen.findByText("旧问题");
  fireEvent.click(screen.getByText("逻辑推理", { exact: true }));
  fireEvent.click(await screen.findByRole("button", { name: "调整思考强度" }));
  fireEvent.keyDown(await screen.findByRole("slider"), {
    key: "End",
    keyCode: 35,
  });
  fireEvent.click(screen.getByRole("button", { name: "使用默认强度" }));
  expect(
    screen.getByRole("button", { name: "调整思考强度" }),
  ).toHaveTextContent("轻量");
  fireEvent.click(screen.getByText("逻辑推理", { exact: true }));
  fireEvent.click(screen.getByRole("button", { name: "调整思考强度" }));
  await waitFor(() =>
    expect(screen.getByRole("slider", { name: "思考强度" })).toBeVisible(),
  );
  expect(screen.getByText("选择强度将开启逻辑推理。")).toBeVisible();
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

it.each(["chat", "workbench"] as const)(
  "%s uses the backend model and profile instead of a saved local model choice",
  async (mode) => {
    const previousModels = bootstrap.models;
    bootstrap.models = [
      ...previousModels,
      { ...previousModels[0], alias: "old-choice", name: "旧本机选择" },
    ];
    bootstrap.budgets!.defaultProfile = "materials";
    localStorage.setItem(
      `agent-model:99:${mode === "workbench" ? "agent" : "chat"}`,
      "old-choice",
    );
    try {
      showAgent(mode);
      await screen.findByText("旧问题");
      fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
        target: { value: "按项目默认配置分析" },
      });
      fireEvent.click(screen.getByRole("button", { name: "发送" }));
      await waitFor(() =>
        expect(agentApi.submit).toHaveBeenCalledWith(
          1,
          expect.objectContaining({
            model: "mock",
            budgetProfile: "materials",
            maxOutputTokens: undefined,
          }),
        ),
      );
    } finally {
      bootstrap.models = previousModels;
    }
  },
);

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
    fireEvent.click(screen.getByRole("button", { name: "调整思考强度" }));
    expect(screen.queryByText("高级设置")).not.toBeInTheDocument();
    if (!manager)
      expect(screen.queryByText("工具调用详情")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "选择模型" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "分析方案" })).toBeNull();
    expect(
      screen.queryByRole("spinbutton", { name: "本次生成上限" }),
    ).toBeNull();
  },
);

it("hides unavailable agent navigation and starts reasoning from the effort choice using the backend profile", async () => {
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
    screen.queryByRole("button", { name: "科研智能体" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "调整思考强度" }));
  fireEvent.keyDown(await screen.findByRole("slider", { name: "思考强度" }), {
    key: "End",
    keyCode: 35,
  });
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
        reasoningEffort: "xhigh",
        budgetProfile: "normal",
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
    ).toEqual({ sidebar: 340, input: 144, workflow: 720 }),
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

it("keeps both allowed conversation modes visible when the history sidebar is hidden", async () => {
  await page.viewport(390, 844);
  try {
    showAgent("workbench");
    await screen.findByText("旧问题");
    const sidebar = screen.getByRole("complementary", {
      hidden: true,
    });
    expect(sidebar).not.toBeVisible();
    const quick = screen.getByRole("button", { name: "快速对话" });
    expect(quick).toBeVisible();
    fireEvent.click(quick);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "快速对话" })).toHaveAttribute(
        "aria-current",
        "page",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "科研智能体" }));
    await screen.findByRole("button", { name: /MH-workflow/ });
    expect(screen.getByRole("button", { name: "科研智能体" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("button", { name: "快速对话" })).toBeVisible();
  } finally {
    await page.viewport(1600, 900);
  }
});

it("resizes the workflow from its left edge and restores its saved width", async () => {
  vi.spyOn(HTMLElement.prototype, "setPointerCapture").mockImplementation(
    () => {},
  );
  const first = showAgent("workbench");
  await screen.findByText("旧问题");
  fireEvent.click(screen.getByRole("button", { name: /MH-workflow/ }));
  const handle = await screen.findByRole("separator", {
    name: "调整工作流宽度",
  });
  fireEvent.pointerDown(handle, { button: 0, pointerId: 9, clientX: 880 });
  fireEvent.pointerMove(handle, { pointerId: 9, clientX: 720 });
  fireEvent.pointerUp(handle, { pointerId: 9 });
  await waitFor(() => expect(handle).toHaveAttribute("aria-valuenow", "880"));
  const drawer = document.querySelector<HTMLElement>(
    ".agent-workflow-drawer .ant-drawer-content-wrapper",
  )!;
  expect(drawer.getBoundingClientRect().width).toBe(880);
  await waitFor(() =>
    expect(
      JSON.parse(localStorage.getItem("agent-layout:99:agent") ?? "null")
        .workflow,
    ).toBe(880),
  );
  first.unmount();
  showAgent("workbench");
  fireEvent.click(await screen.findByRole("button", { name: /MH-workflow/ }));
  const restored = await screen.findByRole("separator", {
    name: "调整工作流宽度",
  });
  expect(restored).toHaveAttribute("aria-valuenow", "880");
  fireEvent.keyDown(restored, { key: "ArrowLeft" });
  expect(restored).toHaveAttribute("aria-valuenow", "896");
  fireEvent.doubleClick(restored);
  expect(restored).toHaveAttribute("aria-valuenow", "720");
});

it("loads only scene names on opening workflow and reuses the selected draft", async () => {
  showAgent("workbench");
  await screen.findByText("旧问题");
  expect(computeApi.inputs).not.toHaveBeenCalled();
  expect(computeApi.algorithms).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "快速对话" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "快速对话" })).toHaveAttribute(
      "aria-current",
      "page",
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "科研智能体" }));
  await screen.findByRole("button", { name: /MH-workflow/ });
  expect(computeApi.inputs).not.toHaveBeenCalled();
  expect(computeApi.algorithms).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /MH-workflow/ }));
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: "研究场景" })).toBeEnabled(),
  );
  expect(computeApi.inputs).not.toHaveBeenCalled();
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "研究场景" }));
  fireEvent.click(
    await screen.findByText("通用科研计算", {
      selector: ".ant-select-item-option-content",
    }),
  );
  await waitFor(() => expect(computeApi.inputs).toHaveBeenCalledOnce());
  await waitFor(() =>
    expect(screen.getByRole("textbox", { name: "工作流目标" })).toBeEnabled(),
  );
  fireEvent.change(screen.getByRole("textbox", { name: "工作流目标" }), {
    target: { value: "保持这份草稿" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  fireEvent.click(screen.getByRole("button", { name: /MH-workflow/ }));
  await screen.findByRole("textbox", { name: "工作流目标" });
  expect(screen.getByRole("textbox", { name: "工作流目标" })).toHaveValue(
    "保持这份草稿",
  );
  expect(computeApi.inputs).toHaveBeenCalledOnce();
  expect(computeApi.algorithms).toHaveBeenCalledOnce();
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
      fireEvent.click(screen.getByRole("button", { name: /MH-workflow/ }));
      await waitFor(() =>
        expect(
          screen.getByRole("combobox", { name: "研究场景" }),
        ).toBeEnabled(),
      );
      fireEvent.mouseDown(screen.getByRole("combobox", { name: "研究场景" }));
      fireEvent.click(
        await screen.findByText("通用科研计算", {
          selector: ".ant-select-item-option-content",
        }),
      );
      let goal = await screen.findByRole("textbox", { name: "工作流目标" });
      await waitFor(() => expect(goal).toBeEnabled());
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
      fireEvent.click(screen.getByRole("button", { name: /MH-workflow/ }));
      goal = await screen.findByRole("textbox", { name: "工作流目标" });
      await waitFor(() => expect(goal).toBeVisible());
      expect(screen.getByRole("textbox", { name: "工作流目标" })).toHaveValue(
        "核查研究区数据",
      );
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      await waitFor(() => expect(goal).not.toBeVisible());
      fireEvent.click(screen.getByRole("button", { name: "调整思考强度" }));
      const effort = await screen.findByRole("slider", { name: "思考强度" });
      expectWithin(
        effort,
        document.querySelector<HTMLElement>(".agent-reasoning-settings")!,
      );
      fireEvent.keyDown(effort, { key: "End", keyCode: 35 });
      fireEvent.click(screen.getByRole("button", { name: "调整思考强度" }));
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
            thinkingMode: "deep",
            reasoningEffort: "xhigh",
            budgetProfile: "normal",
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

it("restores the explicit pending task on open and retains its status after closing", async () => {
  sessionStorage.setItem("workflow-session:99:1", "research_processing");
  sessionStorage.setItem(
    "workflow-session:99:1:research_processing",
    "workflow-1",
  );
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
  expect(agentApi.workflow).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /MH-workflow/ }));
  await screen.findByRole("button", { name: "确认执行" });
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  const pending = await screen.findByRole("button", {
    name: /MH-workflow.*等待您审核/,
  });
  expect(agentApi.workflow).toHaveBeenCalledWith("workflow-1", {
    signal: expect.any(AbortSignal),
  });
  fireEvent.click(pending);
  fireEvent.click(await screen.findByRole("button", { name: "确认执行" }));
  await waitFor(() =>
    expect(agentApi.confirmWorkflow).toHaveBeenCalledWith(
      "workflow-1",
      "frozen-plan",
    ),
  );
  await waitFor(() => expect(screen.queryByText("待确认")).toBeNull());
});

it("submits selected resources and a document while keeping system settings out of the composer", async () => {
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
  fireEvent.click(screen.getByRole("button", { name: "选择数据" }));
  fireEvent.click(
    within(screen.getByRole("radiogroup", { name: "数据选择方式" })).getByRole(
      "radio",
      { name: "手动选择" },
    ),
  );
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "限定数据资源" }));
  fireEvent.click(
    await screen.findByText("研究区影像", {
      selector: ".ant-select-item-option-content",
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "选择数据" }));
  await waitFor(() =>
    expect(
      screen.queryByRole("radiogroup", { name: "数据选择方式" }),
    ).not.toBeInTheDocument(),
  );
  fireEvent.click(screen.getByRole("button", { name: "调整思考强度" }));
  await waitFor(() =>
    expect(screen.getByRole("slider", { name: "思考强度" })).toBeVisible(),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("slider").closest(".ant-popover")!.className,
    ).not.toMatch(/(?:-enter|-appear|-leave)/),
  );
  expect(screen.queryByRole("switch", { name: "联网检索" })).toBeNull();
  expect(screen.queryByRole("combobox", { name: "选择模型" })).toBeNull();
  expect(screen.queryByRole("combobox", { name: "分析方案" })).toBeNull();
  expect(screen.queryByText("高级设置")).not.toBeInTheDocument();
  const upload = screen.getByRole("button", { name: /上传文档/ });
  const algorithm = screen.getByRole("button", { name: "调用算法" });
  for (const property of [
    "height",
    "borderRadius",
    "fontSize",
    "backgroundColor",
    "color",
  ] as const) {
    expect(getComputedStyle(upload)[property]).toBe(
      getComputedStyle(algorithm)[property],
    );
  }
  await page.screenshot({
    path: "../../test-results/agent-composer-effort-desktop.png",
  });
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
        internetEnabled: false,
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

it("submits manual algorithm, data and multiple knowledge zones through explicit buttons", async () => {
  bootstrap.algorithmOptions = Array.from({ length: 4 }, (_, index) => ({
    versionId: index + 4,
    algorithmId: index + 1,
    name: `分析算法${index + 1}`,
    version: "1.0.0",
    description: "已发布算法",
  }));
  vi.mocked(agentApi.resources).mockResolvedValue({
    items: Array.from({ length: 4 }, (_, index) => ({
      id: index + 10,
      name: `研究区影像${index + 1}`,
      dataType: "raster" as const,
      description: "",
    })),
  });
  showAgent("workbench");
  await screen.findByText("旧问题");
  fireEvent.click(screen.getByRole("button", { name: "调用算法" }));
  fireEvent.click(
    within(screen.getByRole("radiogroup", { name: "算法选择方式" })).getByRole(
      "radio",
      { name: "手动选择" },
    ),
  );
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "选择调用算法" }));
  for (let index = 1; index <= 4; index++) {
    fireEvent.click(
      await screen.findByText(`分析算法${index} / 1.0.0`, {
        selector: ".ant-select-item-option-content",
      }),
    );
  }
  fireEvent.click(screen.getByRole("button", { name: "选择数据" }));
  fireEvent.click(
    within(screen.getByRole("radiogroup", { name: "数据选择方式" })).getByRole(
      "radio",
      { name: "手动选择" },
    ),
  );
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "限定数据资源" }));
  for (let index = 1; index <= 4; index++) {
    fireEvent.click(
      await screen.findByText(`研究区影像${index}`, {
        selector: ".ant-select-item-option-content",
      }),
    );
  }
  fireEvent.click(screen.getByRole("button", { name: "知识库" }));
  fireEvent.click(screen.getByRole("radio", { name: "手选分区" }));
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "选择知识分区" }));
  fireEvent.click(
    await screen.findByText("遥感基础", {
      selector: ".ant-select-item-option-content",
    }),
  );
  fireEvent.click(
    await screen.findByText("干旱区生态安全治理", {
      selector: ".ant-select-item-option-content",
    }),
  );
  fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
    target: { value: "分析这张影像的NDVI" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() =>
    expect(agentApi.submit).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        algorithmSelectionMode: "manual",
        algorithmVersionIds: [4, 5, 6, 7],
        dataSelectionMode: "manual",
        resourceIds: [10, 11, 12, 13],
        knowledgeSelection: {
          mode: "manual",
          domains: ["remote_sensing", "arid_ecology"],
        },
      }),
    ),
  );
});

it.each([
  ["自动筛选", "auto"],
  ["全部知识库", "all"],
  ["不参考知识库", "none"],
])(
  "persists the %s knowledge mode in the submitted turn",
  async (label, mode) => {
    showAgent("workbench");
    await screen.findByText("旧问题");
    fireEvent.click(screen.getByRole("button", { name: "知识库" }));
    fireEvent.click(screen.getByRole("radio", { name: label }));
    fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
      target: { value: "分析当前数据" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() =>
      expect(agentApi.submit).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          knowledgeSelection: { mode, domains: [] },
          algorithmSelectionMode: "auto",
          dataSelectionMode: "auto",
          resourceIds: [],
        }),
      ),
    );
  },
);

it("restores saved tool choices from the latest server turn after reopening", async () => {
  const saved = {
    ...run(2, "保存的选择"),
    resourceIds: [10],
    dataSelectionMode: "manual" as const,
    algorithmSelectionMode: "manual" as const,
    algorithmVersionIds: [4],
    knowledgeSelection: {
      mode: "manual" as const,
      domains: ["arid_ecology" as const],
    },
  };
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [run(1, "旧问题"), saved],
  });
  vi.mocked(agentApi.resources).mockResolvedValue({
    items: [
      { id: 10, name: "研究区影像", dataType: "raster", description: "" },
    ],
  });
  const first = showAgent("workbench");
  await screen.findByText("保存的选择");
  first.unmount();
  showAgent("workbench");
  await screen.findByText("保存的选择");
  fireEvent.click(screen.getByRole("button", { name: "知识库" }));
  expect(screen.getByRole("radio", { name: "手选分区" })).toBeChecked();
  await waitFor(() =>
    expect(
      screen.getByText("干旱区生态安全治理", {
        selector: ".ant-select-selection-item-content",
      }),
    ).toBeVisible(),
  );
  fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
    target: { value: "继续分析" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() =>
    expect(agentApi.submit).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        algorithmSelectionMode: "manual",
        algorithmVersionIds: [4],
        dataSelectionMode: "manual",
        resourceIds: [10],
        knowledgeSelection: saved.knowledgeSelection,
      }),
    ),
  );
});

it.each([
  ["自动筛选", "auto"],
  ["全部知识库", "all"],
  ["不参考知识库", "none"],
])(
  "clears manual restrictions when changing knowledge to %s and other tools to automatic",
  async (label, mode) => {
    vi.mocked(agentApi.detail).mockResolvedValue({
      conversation,
      runs: [
        {
          ...run(1, "已手选的任务"),
          resourceIds: [10],
          dataSelectionMode: "manual",
          algorithmSelectionMode: "manual",
          algorithmVersionIds: [4],
          knowledgeSelection: { mode: "manual", domains: ["arid_ecology"] },
        },
      ],
    });
    showAgent("workbench");
    await screen.findByText("已手选的任务");
    fireEvent.click(screen.getByRole("button", { name: "调用算法" }));
    fireEvent.click(
      within(
        screen.getByRole("radiogroup", { name: "算法选择方式" }),
      ).getByRole("radio", { name: "自动筛选" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "选择数据" }));
    fireEvent.click(
      within(
        screen.getByRole("radiogroup", { name: "数据选择方式" }),
      ).getByRole("radio", { name: "自动筛选" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "知识库" }));
    fireEvent.click(
      within(
        screen.getByRole("radiogroup", { name: "知识库参考方式" }),
      ).getByRole("radio", { name: label }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
      target: { value: "重新自动分析" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() =>
      expect(agentApi.submit).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          algorithmSelectionMode: "auto",
          algorithmVersionIds: [],
          dataSelectionMode: "auto",
          resourceIds: [],
          knowledgeSelection: { mode, domains: [] },
        }),
      ),
    );
  },
);

it("asks for a manual selection before creating a run", async () => {
  showAgent("workbench");
  await screen.findByText("旧问题");
  fireEvent.click(screen.getByRole("button", { name: "调用算法" }));
  fireEvent.click(
    within(screen.getByRole("radiogroup", { name: "算法选择方式" })).getByRole(
      "radio",
      { name: "手动选择" },
    ),
  );
  fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
    target: { value: "计算NDVI" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(
    await screen.findByText("请选择至少一个算法，或切换为自动筛选。"),
  ).toBeVisible();
  expect(agentApi.submit).not.toHaveBeenCalled();
});

it("keeps all three tool buttons and knowledge selection inside a 390px screen", async () => {
  await page.viewport(390, 844);
  try {
    const { container } = showAgent("workbench");
    await screen.findByText("旧问题");
    for (const name of ["调用算法", "选择数据", "知识库"]) {
      const button = screen.getByRole("button", { name });
      expect(button).toBeVisible();
      expect(button.getBoundingClientRect().right).toBeLessThanOrEqual(390);
    }
    fireEvent.click(screen.getByRole("button", { name: "知识库" }));
    fireEvent.click(screen.getByRole("radio", { name: "手选分区" }));
    const panel = document.querySelector(".agent-selection-panel")!;
    expect(panel.getBoundingClientRect().right).toBeLessThanOrEqual(390);
    expect(
      container.querySelector(".agent-composer")!.getBoundingClientRect().width,
    ).toBeLessThanOrEqual(390);
    await waitFor(() =>
      expect(panel.closest(".ant-popover")!.className).not.toMatch(
        /(?:-enter|-appear|-leave)/,
      ),
    );
    expect(panel.getBoundingClientRect().left).toBeGreaterThanOrEqual(0);
    await page.screenshot({
      path: "../../test-results/agent-knowledge-zones-mobile.png",
    });
  } finally {
    await page.viewport(1600, 900);
  }
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

it("keeps all saved reasoning when the incremental event window is shorter", async () => {
  const text = [
    "最初已经核实的数据依据",
    ...Array.from({ length: 110 }, (_, n) => `逐条核对记录 ${n}`),
    "当前最新的分析",
  ].join("\n");
  const activeRun: AgentRun = {
    ...run(19, "分析研究数据"),
    status: "running",
    thinkingMode: "deep",
    thinkingText: text,
  };
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [activeRun],
  });
  vi.spyOn(agentApi, "poll").mockResolvedValue({
    run: activeRun,
    cursor: 100,
    events: [
      {
        id: 100,
        kind: "thinking",
        text: "当前最新的分析",
        data: {},
        createdAt: "",
      },
    ],
  });
  showAgent();
  await screen.findByText("最初已经核实的数据依据");
  expect(screen.getByLabelText("模型思考内容")).toHaveTextContent(
    "逐条核对记录 0",
  );
  expect(screen.getByLabelText("模型思考内容")).toHaveTextContent(
    "当前最新的分析",
  );
  expect(
    within(screen.getByLabelText("当前任务")).getByText("正在思考"),
  ).toBeVisible();
  await page.screenshot({
    path: "../../test-results/agent-live-thinking-desktop.png",
  });
});

it("explains a completed deep run without inventing reasoning", async () => {
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [
      {
        ...run(20, "统计计算成果", "已根据当前项目目录完成统计。"),
        thinkingMode: "deep",
        thinkingText: "",
      },
    ],
  });
  showAgent();
  await screen.findByText("已根据当前项目目录完成统计。");
  fireEvent.click(screen.getByText("模型思考过程"));
  await screen.findByText(
    "已开启逻辑推理，本次未收到可展示的思考内容。请查看下方实际答复与工具结果。",
  );
  expect(screen.queryByText(/未保存到思考片段/)).not.toBeInTheDocument();
});

function waitingQuestion(): AgentRun {
  return {
    ...run(88, "请处理这张影像"),
    status: "waiting_input",
    detail: "等待您回答",
    interaction: {
      questionId: "band-question",
      revision: 1,
      kind: "input",
      title: "请补充光谱波段",
      reason: "已读取影像有8个波段，但没有光谱名称。",
      status: "pending",
      createdAt: "2026-10-16",
      questions: [
        {
          key: "red",
          label: "红光波段",
          type: "text",
          required: true,
        },
      ],
    },
    interactionHistory: [],
  };
}

it("restores a waiting question and shows matching sidebar and conversation states", async () => {
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [waitingQuestion()],
  });
  showAgent();
  await screen.findByRole("region", { name: "等待您回答的问题" });
  expect(
    within(screen.getByLabelText("当前任务")).getByText("等待您回答"),
  ).toBeVisible();
  expect(screen.queryByText("已完成")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "重试" }),
  ).not.toBeInTheDocument();
  expect(agentApi.submit).not.toHaveBeenCalled();
});

it("sends a free-text answer to the original run and resumes it without a new turn", async () => {
  const waiting = waitingQuestion();
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [waiting],
  });
  const continued = {
    ...waiting,
    status: "queued" as const,
    interaction: null,
  };
  const answer = vi
    .spyOn(agentApi, "answerInteraction")
    .mockResolvedValue(continued);
  vi.spyOn(agentApi, "poll").mockResolvedValue({
    run: continued,
    events: [],
    cursor: 0,
  });
  showAgent();
  await screen.findByRole("region", { name: "等待您回答的问题" });
  fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
    target: { value: "红光第3波段，近红外第8波段，只预览结果" },
  });
  fireEvent.click(screen.getByRole("button", { name: "提交回答" }));
  await waitFor(() =>
    expect(answer).toHaveBeenCalledExactlyOnceWith(
      88,
      expect.objectContaining({
        action: "answer",
        questionId: "band-question",
        revision: 1,
        answers: {},
        text: "红光第3波段，近红外第8波段，只预览结果",
      }),
    ),
  );
  expect(agentApi.submit).not.toHaveBeenCalled();
  await screen.findByRole("button", { name: "停止回答" });
  expect(screen.queryByRole("region", { name: "等待您回答的问题" })).toBeNull();
});

it("gives the current question priority over the legacy parameter form", async () => {
  vi.mocked(agentApi.conversations).mockResolvedValue({
    items: [{ ...conversation, mode: "agent" }],
  });
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation: { ...conversation, mode: "agent" },
    runs: [{ ...waitingQuestion(), computeIntent }],
  });
  showAgent("workbench");
  await screen.findByRole("region", { name: "等待您回答的问题" });
  expect(screen.queryByText("确认参数并运行")).not.toBeInTheDocument();
  expect(agentApi.submit).not.toHaveBeenCalled();
});

it("shows the model interpretation after the same run reads the actual output", async () => {
  vi.mocked(agentApi.conversations).mockResolvedValue({
    items: [{ ...conversation, mode: "agent" }],
  });
  const completed = computeRun({
    ...computeIntent,
    status: "submitted",
    taskId: "verified-task",
  });
  completed.answer =
    "实际输出的平均植被指数为0.42，建议结合同时期降水资料进一步核查。";
  completed.evidence = [
    {
      id: 7,
      tool: "read_compute_output",
      resourceId: null,
      name: "计算结果",
      recordedAt: "2026-10-16",
      result: { output: { id: 8 }, bands: [{ mean: 0.42 }] },
    },
  ];
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation: { ...conversation, mode: "agent" },
    runs: [completed],
  });
  showAgent("workbench");
  await screen.findByText(completed.answer);
});

it("removes recovered workflow activity when agent permission is revoked", async () => {
  sessionStorage.setItem("workflow-session:99:1", "research_processing");
  sessionStorage.setItem(
    "workflow-session:99:1:research_processing",
    "workflow-1",
  );
  vi.spyOn(agentApi, "workflow").mockResolvedValue({
    ...workflow("running"),
    goal: "撤权后不可保留的研究任务",
  });
  vi.mocked(agentApi.workflows).mockResolvedValue({
    items: [{ ...workflow("running"), goal: "撤权后不可保留的研究任务" }],
  });
  const mounted = showAgent("workbench");
  fireEvent.click(await screen.findByRole("button", { name: /MH-workflow/ }));
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("当前任务")).getByText("正在推进研究"),
    ).toBeInTheDocument(),
  );
  bootstrap.canAgent = false;
  try {
    mounted.rerender(
      <AntApp>
        <MemoryRouter initialEntries={["/agent/workbench"]}>
          <AgentPage />
        </MemoryRouter>
      </AntApp>,
    );
    await screen.findByText("当前账号未获准使用此功能，请联系超级管理员。");
    expect(screen.queryByLabelText("当前任务")).not.toBeInTheDocument();
    expect(
      screen.queryByText("撤权后不可保留的研究任务"),
    ).not.toBeInTheDocument();
    expect(
      document.querySelector(".agent-activity-mark.is-working"),
    ).not.toBeInTheDocument();
  } finally {
    bootstrap.canAgent = true;
  }
});

it("keeps unknown and failed permission checks distinct from denied access", async () => {
  accessState.value = "unknown";
  accessState.status = "loading";
  const mounted = showAgent();
  expect(screen.queryByText(/当前账号未获准/)).not.toBeInTheDocument();
  expect(agentApi.conversations).not.toHaveBeenCalled();
  const rerender = () =>
    mounted.rerender(
      <AntApp>
        <MemoryRouter initialEntries={["/agent/chat"]}>
          <AgentPage />
        </MemoryRouter>
      </AntApp>,
    );
  accessState.status = "error";
  rerender();
  fireEvent.click(await screen.findByRole("button", { name: "重试连接" }));
  expect(accessState.retry).toHaveBeenCalledOnce();
  expect(screen.queryByText(/当前账号未获准/)).not.toBeInTheDocument();
  accessState.value = "confirmed";
  accessState.status = "ready";
  rerender();
  await screen.findByText("旧问题");
});

it.each(["unauthenticated", "forbidden"] as const)(
  "shows the correct message for an explicit %s state",
  async (status) => {
    accessState.value = "unknown";
    accessState.status = status;
    showAgent();
    if (status === "unauthenticated") {
      expect(
        await screen.findByText("登录状态已失效，请重新登录。"),
      ).toBeVisible();
      expect(screen.queryByText(/当前账号未获准/)).not.toBeInTheDocument();
    } else {
      expect(await screen.findByText(/当前账号未获准/)).toBeVisible();
      expect(screen.queryByText(/登录状态已失效/)).not.toBeInTheDocument();
    }
  },
);

it("preserves the conversation, pending prompt and access after a concurrency rejection", async () => {
  vi.mocked(agentApi.submit).mockRejectedValueOnce(
    new ApiError("最多同时处理3个问题，请稍后再试", 409),
  );
  showAgent();
  await screen.findByText("旧问题");
  const input = screen.getByRole("textbox", { name: "输入消息" });
  fireEvent.change(input, { target: { value: "第四个问题" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await screen.findByText("最多同时处理3个问题，请稍后再试");
  expect(input).toHaveValue("第四个问题");
  expect(screen.getByText("旧问题")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^历史会话/ })).toBeInTheDocument();
  expect(screen.queryByText(/当前账号未获准/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "发送" })).toBeEnabled();
});

it("retains streamed history after a connection failure and resumes polling", async () => {
  const responding = {
    ...run(5, "正在处理的问题", "已有的部分回答"),
    status: "running" as const,
  };
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [responding],
  });
  const poll = vi
    .spyOn(agentApi, "poll")
    .mockRejectedValueOnce(new TypeError("连接暂时中断"))
    .mockResolvedValue({
      run: { ...responding, status: "succeeded", answer: "恢复连接后的回答" },
      events: [],
      cursor: 1,
    });
  showAgent();
  await screen.findByText("连接暂时中断");
  expect(screen.getByText("正在处理的问题")).toBeInTheDocument();
  expect(screen.getByText("已有的部分回答")).toBeInTheDocument();
  expect(screen.queryByText(/当前账号未获准/)).not.toBeInTheDocument();
  await screen.findByText("恢复连接后的回答", {}, { timeout: 5000 });
  expect(poll).toHaveBeenCalledTimes(2);
});

it("removes restricted conversation content after an explicit poll authorization failure", async () => {
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [
      { ...run(5, "撤权后隐藏的问题", "撤权后隐藏的回答"), status: "running" },
    ],
  });
  vi.spyOn(agentApi, "poll").mockRejectedValue(
    new ApiError("当前会话访问权限已撤销", 403),
  );
  showAgent();
  await screen.findByText("当前会话访问权限已撤销");
  expect(screen.queryByText("撤权后隐藏的问题")).not.toBeInTheDocument();
  expect(screen.queryByText("撤权后隐藏的回答")).not.toBeInTheDocument();
});

it("does not share a running conversation lock between quick chat and research windows", async () => {
  const research = {
    ...conversation,
    id: 2,
    mode: "agent" as const,
    title: "科研会话",
  };
  const responding = {
    ...run(5, "快速对话正在回答", "已有回答"),
    status: "running" as const,
  };
  vi.mocked(agentApi.conversations).mockImplementation(async (mode) => ({
    items: [mode === "chat" ? conversation : research],
  }));
  vi.mocked(agentApi.detail).mockImplementation(async (id) =>
    id === 1
      ? { conversation, runs: [responding] }
      : {
          conversation: research,
          runs: [{ ...run(6, "科研历史"), conversationId: 2 }],
        },
  );
  vi.spyOn(agentApi, "poll").mockResolvedValue({
    run: responding,
    events: [],
    cursor: 0,
  });
  const chat = showAgent();
  const agent = showAgent("workbench");
  await within(chat.container).findByText("快速对话正在回答");
  await within(agent.container).findByText("科研历史");
  expect(
    within(chat.container).getByRole("button", { name: "停止回答" }),
  ).toBeEnabled();
  const input = within(agent.container).getByRole("textbox", {
    name: "输入消息",
  });
  fireEvent.change(input, { target: { value: "另一个会话的独立问题" } });
  fireEvent.click(
    within(agent.container).getByRole("button", { name: "发送" }),
  );
  await waitFor(() =>
    expect(agentApi.submit).toHaveBeenCalledWith(
      2,
      expect.objectContaining({ prompt: "另一个会话的独立问题" }),
    ),
  );
  expect(
    within(chat.container).getByText("快速对话正在回答"),
  ).toBeInTheDocument();
});

it("allows a new conversation while another one runs without submitting twice to the current conversation", async () => {
  const responding = {
    ...run(5, "原会话仍在处理"),
    status: "running" as const,
  };
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [responding],
  });
  vi.spyOn(agentApi, "poll").mockResolvedValue({
    run: responding,
    events: [],
    cursor: 0,
  });
  vi.spyOn(agentApi, "create").mockResolvedValue({
    ...conversation,
    id: 3,
    title: "新会话",
  });
  showAgent();
  await screen.findByRole("button", { name: "停止回答" });
  expect(
    screen.queryByRole("button", { name: "发送" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /新建会话/ }));
  const input = screen.getByRole("textbox", { name: "输入消息" });
  fireEvent.change(input, { target: { value: "新会话问题" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() =>
    expect(agentApi.submit).toHaveBeenCalledExactlyOnceWith(
      3,
      expect.objectContaining({ prompt: "新会话问题" }),
    ),
  );
});

it("keeps history visible when the model is offline", async () => {
  const original = bootstrap.models[0].status;
  bootstrap.models[0].status = "offline";
  try {
    showAgent();
    await screen.findByText("旧问题");
    expect(screen.queryByText(/当前账号未获准/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
  } finally {
    bootstrap.models[0].status = original;
  }
});

it("does not repeatedly fetch full conversation history while idle", async () => {
  vi.useFakeTimers();
  try {
    const mounted = showAgent();
    await act(async () => vi.advanceTimersByTimeAsync(200));
    expect(screen.getByText("旧问题")).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(45000));
    expect(agentApi.detail).toHaveBeenCalledTimes(1);
    expect(screen.getByText("旧问题")).toBeInTheDocument();
    mounted.unmount();
  } finally {
    vi.useRealTimers();
  }
});

it.each([undefined, null, { items: [] }, [null]])(
  "retains confirmed messages when reopened history has malformed runs %j and retries the same conversation",
  async (invalidRuns) => {
    vi.mocked(agentApi.detail)
      .mockResolvedValueOnce({
        conversation,
        runs: [run(1, "已确认问题", "已确认回答")],
      })
      .mockResolvedValueOnce({
        conversation,
        runs: invalidRuns,
      } as unknown as AgentConversationDetail)
      .mockResolvedValue({
        conversation,
        runs: [run(1, "已确认问题", "恢复后的真实回答")],
      });
    showAgent();
    await screen.findByText("已确认回答");
    fireEvent.click(screen.getByRole("button", { name: /^历史会话/ }));
    await screen.findByText("暂时无法加载所选历史");
    expect(screen.getByText("已确认问题")).toBeVisible();
    expect(screen.getByText("已确认回答")).toBeVisible();
    expect(screen.queryByText("有什么想讨论的？")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载异常诊断" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "重试加载历史" }));
    await screen.findByText("恢复后的真实回答");
    expect(agentApi.detail).toHaveBeenNthCalledWith(3, 1);
    expect(screen.queryByText("暂时无法加载所选历史")).not.toBeInTheDocument();
  },
);

it("shows a recoverable first-load failure instead of pretending malformed history is an empty conversation", async () => {
  vi.mocked(agentApi.detail)
    .mockResolvedValueOnce({
      conversation,
      messages: [{ prompt: "错误字段" }],
    } as unknown as AgentConversationDetail)
    .mockResolvedValue({
      conversation,
      runs: [run(1, "原始历史问题", "原始历史回答")],
    });
  showAgent();
  await screen.findByText("暂时无法加载所选历史");
  expect(screen.queryByText("有什么想讨论的？")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "重试加载历史" }));
  await screen.findByText("原始历史回答");
});

it("keeps the current chat when another history fails and ignores an older recovery response", async () => {
  const second = { ...conversation, id: 2, title: "另一历史" };
  vi.mocked(agentApi.conversations).mockResolvedValue({
    items: [conversation, second],
  });
  let completeOld: ((value: AgentConversationDetail) => void) | undefined;
  vi.mocked(agentApi.detail)
    .mockResolvedValueOnce({
      conversation,
      runs: [run(1, "当前问题", "当前回答")],
    })
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          completeOld = resolve;
        }),
    )
    .mockResolvedValueOnce({
      conversation,
      runs: [run(1, "当前问题", "最新当前回答")],
    });
  showAgent();
  await screen.findByText("当前回答");
  fireEvent.click(screen.getByRole("button", { name: /^另一历史/ }));
  expect(screen.getByText("当前回答")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /^历史会话/ }));
  await screen.findByText("最新当前回答");
  await act(async () =>
    completeOld?.({
      conversation: second,
      runs: [{ ...run(2, "迟到问题", "迟到回答"), conversationId: 2 }],
    }),
  );
  expect(screen.getByText("最新当前回答")).toBeVisible();
  expect(screen.queryByText("迟到回答")).not.toBeInTheDocument();
});

it("retains the last answer when a running task poll has an invalid payload and permits an immediate retry", async () => {
  const responding = {
    ...run(5, "处理中问题", "已保存部分回答"),
    status: "running" as const,
  };
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [responding],
  });
  vi.spyOn(agentApi, "poll")
    .mockResolvedValueOnce({
      run: null,
      events: null,
      cursor: 1,
    } as unknown as Awaited<ReturnType<typeof agentApi.poll>>)
    .mockResolvedValue({
      run: { ...responding, status: "succeeded", answer: "计算完毕的回答" },
      events: [],
      cursor: 2,
    });
  showAgent();
  await screen.findByRole("button", { name: "重试更新回答" });
  expect(screen.getByText("已保存部分回答")).toBeVisible();
  expect(screen.getByText("处理中问题")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "重试更新回答" }));
  await screen.findByText("计算完毕的回答");
  expect(agentApi.poll).toHaveBeenCalledTimes(2);
});

it.each([403, 404])(
  "hides the unavailable current history after an explicit %i response",
  async (status) => {
    vi.mocked(agentApi.detail)
      .mockResolvedValueOnce({
        conversation,
        runs: [run(1, "不再可读的问题", "不再可读的回答")],
      })
      .mockRejectedValueOnce(new ApiError("该会话已不可访问", status));
    showAgent();
    await screen.findByText("不再可读的回答");
    fireEvent.click(screen.getByRole("button", { name: /^历史会话/ }));
    await screen.findByText("该会话已不可访问");
    expect(screen.queryByText("不再可读的回答")).not.toBeInTheDocument();
    expect(screen.queryByText("不再可读的问题")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "重试加载历史" }),
    ).not.toBeInTheDocument();
  },
);

it("silently retains current messages when history recovery is aborted", async () => {
  vi.mocked(agentApi.detail)
    .mockResolvedValueOnce({
      conversation,
      runs: [run(1, "已保存问题", "已保存回答")],
    })
    .mockRejectedValueOnce(
      new DOMException("Navigation cancelled", "AbortError"),
    );
  showAgent();
  await screen.findByText("已保存回答");
  fireEvent.click(screen.getByRole("button", { name: /^历史会话/ }));
  await waitFor(() => expect(agentApi.detail).toHaveBeenCalledTimes(2));
  expect(screen.getByText("已保存回答")).toBeVisible();
  expect(screen.queryByText("暂时无法加载所选历史")).not.toBeInTheDocument();
});

it("does not repopulate conversation titles from a list request started before access was revoked", async () => {
  vi.useFakeTimers();
  try {
    let completeList:
      | ((value: Awaited<ReturnType<typeof agentApi.conversations>>) => void)
      | undefined;
    vi.mocked(agentApi.conversations)
      .mockResolvedValueOnce({ items: [conversation] })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            completeList = resolve;
          }),
      );
    vi.mocked(agentApi.detail)
      .mockResolvedValueOnce({
        conversation,
        runs: [run(1, "授权时的问题", "授权时的回答")],
      })
      .mockRejectedValueOnce(new ApiError("会话访问权限已撤销", 403));
    const mounted = showAgent();
    await act(async () => vi.advanceTimersByTimeAsync(200));
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索会话" }), {
      target: { value: "历史" },
    });
    await act(async () => vi.advanceTimersByTimeAsync(200));
    fireEvent.click(screen.getByRole("button", { name: /^历史会话/ }));
    await act(async () => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("会话访问权限已撤销")).toBeVisible();
    await act(async () => completeList?.({ items: [conversation] }));
    expect(
      screen.queryByRole("button", { name: /^历史会话/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("授权时的回答")).not.toBeInTheDocument();
    mounted.unmount();
  } finally {
    vi.useRealTimers();
  }
});
