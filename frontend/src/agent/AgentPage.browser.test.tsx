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
import { page, userEvent } from "vitest/browser";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import { ApiError } from "../api/client";
import type {
  AgentBootstrap,
  AgentConversationDetail,
  AgentRun,
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
    current: projectCode.current,
    projects: [
      {
        id: Number(projectCode.current),
        name: "公开",
        code: projectCode.value,
      },
    ],
  }),
}));
const projectCode = { value: "default", current: "1" };
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
  mode: "agent" as const,
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
function showAgent(mode: "chat" | "workbench" = "chat") {
  return render(
    <AntApp>
      <MemoryRouter initialEntries={[`/agent/${mode}`]}>
        <AgentPage />
      </MemoryRouter>
    </AntApp>,
  );
}

it("stops a streamed response in one click and retains received content", async () => {
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
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await waitFor(() => expect(cancel).toHaveBeenCalledExactlyOnceWith(5));
  await screen.findByRole("button", { name: "发送" });
  expect(screen.getByText("已生成部分回答")).toBeInTheDocument();
});

it("real answer preview arrives before terminal and is replaced by the verified final answer", async () => {
  const responding: AgentRun = { ...run(5, "预览本轮答复"), status: "running" };
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [responding],
  });
  let finish:
    | ((value: Awaited<ReturnType<typeof agentApi.poll>>) => void)
    | undefined;
  vi.spyOn(agentApi, "poll")
    .mockResolvedValueOnce({
      run: {
        ...responding,
        answerPreview: "**真实片段** [链接](https://example.test) <img src=x>",
      },
      events: [
        {
          id: 1,
          kind: "answer_preview",
          text: "内部快照不应单独显示",
          createdAt: "",
        },
      ],
      cursor: 1,
    })
    .mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
  showAgent();
  const preview = await screen.findByRole("region", { name: "答复增量预览" });
  expect(preview).toHaveTextContent("正在生成 · 内容将在完成后核验");
  expect(preview).toHaveTextContent(
    "真实片段 [链接](https://example.test) <img src=x>",
  );
  expect(within(preview).queryByRole("link")).not.toBeInTheDocument();
  expect(preview.querySelector("img")).toBeNull();
  expect(screen.queryByText("内部快照不应单独显示")).not.toBeInTheDocument();
  expect(screen.queryByText("已经核验的最终答复")).not.toBeInTheDocument();
  await waitFor(() => expect(finish).toBeDefined());
  await act(async () =>
    finish?.({
      run: {
        ...responding,
        status: "succeeded",
        answerPreview: "",
        answer: "**已经核验的最终答复**",
      },
      events: [],
      cursor: 2,
    }),
  );
  await screen.findByText("已经核验的最终答复");
  expect(
    screen.queryByRole("region", { name: "答复增量预览" }),
  ).not.toBeInTheDocument();
});

it.each(["failed", "cancelled", "interrupted"] as const)(
  "real answer preview restores %s partial text without claiming a complete answer",
  async (status) => {
    vi.mocked(agentApi.detail).mockResolvedValue({
      conversation,
      runs: [
        {
          ...run(5, "未完成的答复"),
          status,
          answerPreview: "实际收到的部分文字",
        },
      ],
    });
    const poll = vi.spyOn(agentApi, "poll");
    showAgent();
    const preview = await screen.findByRole("region", { name: "答复增量预览" });
    expect(preview).toHaveTextContent(
      "本轮已中断或停止；以下为尚未最终校验的部分答复",
    );
    expect(preview).toHaveTextContent("实际收到的部分文字");
    expect(poll).not.toHaveBeenCalled();
  },
);

it("real answer preview survives cancellation and a transient polling disconnect", async () => {
  const responding: AgentRun = {
    ...run(5, "取消前保留真实片段"),
    status: "running",
    answerPreview: "中断前的真实片段",
  };
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [responding],
  });
  vi.spyOn(agentApi, "poll").mockRejectedValue(
    new TypeError("预览连接暂时中断"),
  );
  vi.spyOn(agentApi, "cancel").mockResolvedValue({
    ...responding,
    status: "cancelled",
  });
  showAgent();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "预览连接暂时中断",
  );
  expect(
    screen.getByRole("region", { name: "答复增量预览" }),
  ).toHaveTextContent("中断前的真实片段");
  fireEvent.click(screen.getByRole("button", { name: "停止回答" }));
  await screen.findByText("本轮已中断或停止；以下为尚未最终校验的部分答复");
  expect(
    screen.getByRole("region", { name: "答复增量预览" }),
  ).toHaveTextContent("中断前的真实片段");
});

it("real thinking animation stops for answer preview, calculation and polling disconnect", async () => {
  const thinking: AgentRun = {
    ...run(5, "观察真实思考阶段"),
    status: "running",
    thinkingMode: "deep",
    thinkingText: "实际模型思考片段",
  };
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [thinking],
  });
  const pending: Array<
    (value: Awaited<ReturnType<typeof agentApi.poll>>) => void
  > = [];
  let fail: ((reason: unknown) => void) | undefined;
  vi.spyOn(agentApi, "poll").mockImplementation(
    () =>
      new Promise((resolve, reject) => {
        pending.push(resolve);
        fail = reject;
      }),
  );
  showAgent();
  const content = await screen.findByLabelText("模型思考内容");
  expect(content).toHaveClass("is-streaming");
  await waitFor(() => expect(pending).toHaveLength(1));
  await act(async () =>
    pending[0]!({
      run: { ...thinking, answerPreview: "实际答复片段" },
      events: [],
      cursor: 1,
    }),
  );
  expect(content).not.toHaveClass("is-streaming");
  expect(screen.getByText("模型思考过程")).toBeInTheDocument();
  expect(screen.queryByText("模型思考过程（生成中）")).not.toBeInTheDocument();
  expect(
    within(screen.getByLabelText("当前任务")).getByRole("status"),
  ).toHaveTextContent("正在组织回答");
  await waitFor(() => expect(pending).toHaveLength(2));
  await act(async () =>
    pending[1]!({
      run: { ...thinking, status: "waiting_compute" },
      events: [],
      cursor: 2,
    }),
  );
  expect(content).not.toHaveClass("is-streaming");
  expect(screen.queryByText("模型思考过程（生成中）")).not.toBeInTheDocument();
  expect(
    within(screen.getByLabelText("当前任务")).getByRole("status"),
  ).toHaveTextContent("算法正在计算");
  await waitFor(() => expect(pending).toHaveLength(3));
  await act(async () => pending[2]!({ run: thinking, events: [], cursor: 3 }));
  expect(content).toHaveClass("is-streaming");
  await waitFor(() => expect(pending).toHaveLength(4));
  await act(async () => fail?.(new TypeError("思考轮询断开")));
  await screen.findByText("思考轮询断开", { selector: ".ant-alert-title" });
  expect(
    within(screen.getByLabelText("当前任务")).getByRole("status"),
  ).toHaveTextContent("连接暂时中断，正在恢复");
  expect(
    within(screen.getByLabelText("当前任务")).getByRole("status"),
  ).toHaveAttribute("data-activity-state", "waiting");
  expect(content).not.toHaveClass("is-streaming");
  expect(screen.queryByText("模型思考过程（生成中）")).not.toBeInTheDocument();
  expect(content).toHaveTextContent("实际模型思考片段");
});

it("real answer preview is empty during a tool call and real reasoning remains visible on a computation turn", async () => {
  const toolRun: AgentRun = {
    ...computeRun({ ...computeIntent, status: "ready" }),
    thinkingMode: "deep",
    thinkingText: "真实的计算前思考",
    answer: "",
    answerPreview: "",
  };
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [toolRun],
  });
  showAgent("workbench");
  fireEvent.click(await screen.findByText("思考与处理过程"));
  expect(await screen.findByLabelText("模型思考内容")).toHaveTextContent(
    "真实的计算前思考",
  );
  expect(
    screen.queryByRole("region", { name: "答复增量预览" }),
  ).not.toBeInTheDocument();
});

it.each(["conversation", "project"] as const)(
  "real answer preview ignores a delayed old poll after switching %s",
  async (scope) => {
    const second = { ...conversation, id: 2, title: "第二个会话" };
    const pending: AgentRun = {
      ...run(5, "第一轮问题"),
      status: "running",
      answerPreview: "旧会话真实片段",
    };
    vi.mocked(agentApi.conversations).mockResolvedValue({
      items: [conversation, second],
    });
    vi.mocked(agentApi.detail).mockImplementation(async (id) =>
      id === 1
        ? { conversation, runs: [pending] }
        : {
            conversation: second,
            runs: [
              { ...run(8, "新会话问题", "新会话答复"), conversationId: 2 },
            ],
          },
    );
    let finish:
      | ((value: Awaited<ReturnType<typeof agentApi.poll>>) => void)
      | undefined;
    vi.spyOn(agentApi, "poll").mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const mounted = showAgent();
    await screen.findByText("旧会话真实片段");
    await waitFor(() => expect(finish).toBeDefined());
    if (scope === "conversation") {
      fireEvent.click(screen.getByRole("button", { name: /^第二个会话/ }));
      await screen.findByText("新会话答复");
    } else {
      projectCode.current = "2";
      vi.mocked(agentApi.conversations).mockResolvedValue({ items: [] });
      mounted.rerender(
        <AntApp>
          <MemoryRouter initialEntries={["/agent/chat"]}>
            <AgentPage />
          </MemoryRouter>
        </AntApp>,
      );
      await waitFor(() =>
        expect(screen.queryByText("旧会话真实片段")).not.toBeInTheDocument(),
      );
    }
    await act(async () =>
      finish?.({
        run: { ...pending, answerPreview: "旧请求迟到的片段" },
        events: [],
        cursor: 1,
      }),
    );
    expect(screen.queryByText("旧会话真实片段")).not.toBeInTheDocument();
    expect(screen.queryByText("旧请求迟到的片段")).not.toBeInTheDocument();
    if (scope === "conversation")
      expect(screen.getByText("新会话答复")).toBeInTheDocument();
    mounted.unmount();
  },
);

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
  projectCode.current = "1";
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
  vi.spyOn(agentApi, "computeTasks").mockResolvedValue({ items: [] });
  accessState.value = "confirmed";
  accessState.status = "ready";
  accessState.retry.mockReset();
  bootstrap.canManage = false;
  bootstrap.canAgent = true;
  bootstrap.canChat = false;
  bootstrap.allowAttachments = false;
  bootstrap.internetEnabled = false;
  bootstrap.workerOnline = true;
  bootstrap.runStreamingEnabled = false;
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
  [0, "deep", "low"],
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
    fireEvent.keyDown(slider, { key: "Home", keyCode: 36 });
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
  fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
    target: { value: "核查霞石与石英的适用条件" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() =>
    expect(agentApi.submit).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        knowledgeSelection: { mode: "manual", domains: ["geology"] },
      }),
    ),
  );
});

it("shows the authorization message and hides tool controls for a restricted account", async () => {
  bootstrap.canAgent = false;
  bootstrap.canChat = false;
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
    const trigger = await screen.findByRole("button", { name: "调整思考强度" });
    expect(trigger).toHaveTextContent("标准");
    fireEvent.click(trigger);
    const slider = await screen.findByRole("slider", { name: "思考强度" });
    fireEvent.keyDown(slider, { key: "End", keyCode: 35 });
    await waitFor(() => expect(trigger).toHaveTextContent("深度"));
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
    fireEvent.click(screen.getByRole("button", { name: "调整思考强度" }));
    const slider = await screen.findByRole("slider", { name: "思考强度" });
    await waitFor(() => expect(slider).toBeVisible());
    for (const label of ["轻量", "标准", "深度"])
      expect(screen.getByText(label, { exact: true })).toBeVisible();
    if (effort === "low") {
      fireEvent.keyDown(slider, { key: "Home", keyCode: 36 });
      fireEvent.keyUp(slider, { key: "Home", keyCode: 36 });
    } else fireEvent.keyDown(slider, { key: "End", keyCode: 35 });
    if (effort === "medium")
      fireEvent.keyDown(slider, { key: "ArrowLeft", keyCode: 37 });
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

it("retains a single workspace for a chat-only account without granting agent access", async () => {
  bootstrap.canAgent = false;
  bootstrap.canChat = true;
  const chat = { ...conversation, mode: "chat" as const };
  vi.mocked(agentApi.conversations).mockResolvedValue({ items: [chat] });
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation: chat,
    runs: [run(1, "旧问题")],
  });
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
      JSON.parse(localStorage.getItem("agent-layout:99:agent") ?? "null"),
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
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "关闭会话列表" }),
      ).toHaveFocus(),
    );
    expect(main).toHaveAttribute("inert");
    expect(sidebar.getBoundingClientRect().width).toBeLessThan(
      window.innerWidth,
    );
    fireEvent.click(screen.getByRole("button", { name: "关闭会话列表" }));
    await waitFor(() => expect(sidebar).not.toBeVisible());
    fireEvent.click(history);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "关闭会话列表" }),
      ).toHaveFocus(),
    );
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(sidebar).not.toBeVisible());
    await waitFor(() => expect(history).toHaveFocus());
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
      "agent-layout:99:agent",
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

it("hides an empty completed thinking panel without inventing reasoning", async () => {
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
  expect(screen.queryByText("模型思考过程")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("模型思考内容")).not.toBeInTheDocument();
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
  expect(await screen.findByRole("alert")).toHaveTextContent("连接暂时中断");
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

function prepareFirstTurnTitleRefresh() {
  projectCode.value = "02";
  const first = { ...conversation, mode: "agent" as const, title: "你好" };
  const responding = { ...run(31, "你好"), status: "running" as const };
  vi.mocked(agentApi.conversations).mockResolvedValue({ items: [first] });
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation: first,
    runs: [responding],
  });
  vi.spyOn(agentApi, "poll").mockResolvedValue({
    run: {
      ...responding,
      status: "succeeded",
      answer: "你好，有什么可以帮您？",
    },
    events: [],
    cursor: 0,
  });
  vi.spyOn(agentApi, "activeWorkflow").mockResolvedValue({ item: null });
  return first;
}

it("conversation title refresh shows a delayed greeting summary without a geology template and stops after four metadata reads", async () => {
  vi.useFakeTimers();
  try {
    const first = prepareFirstTurnTitleRefresh();
    let title = first.title;
    vi.mocked(agentApi.conversations).mockImplementation(async () => ({
      items: [{ ...first, title }],
    }));
    const mounted = showAgent("workbench");
    await act(async () => vi.advanceTimersByTimeAsync(200));
    expect(screen.getByText("你好，有什么可以帮您？")).toBeVisible();
    expect(screen.queryByText(/岩性·构造·蚀变检查/)).not.toBeInTheDocument();
    const initialReads = vi.mocked(agentApi.conversations).mock.calls.length;
    await act(async () => vi.advanceTimersByTimeAsync(7000));
    expect(
      document.querySelector(".agent-conversation-heading strong"),
    ).toHaveTextContent("你好");
    title = "问候与交流";
    await act(async () => vi.advanceTimersByTimeAsync(3000));
    expect(screen.getByRole("button", { name: /^问候与交流/ })).toBeVisible();
    expect(
      document.querySelector(".agent-conversation-heading strong"),
    ).toHaveTextContent("问候与交流");
    expect(agentApi.conversations).toHaveBeenCalledTimes(initialReads + 4);
    expect(agentApi.detail).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTimeAsync(20000));
    expect(agentApi.conversations).toHaveBeenCalledTimes(initialReads + 4);
    mounted.unmount();
  } finally {
    vi.useRealTimers();
  }
});

it("conversation title refresh ignores an in-flight greeting title after switching conversations", async () => {
  vi.useFakeTimers();
  try {
    const first = prepareFirstTurnTitleRefresh();
    const second = { ...first, id: 2, title: "另一会话" };
    let completeTitle:
      | ((value: Awaited<ReturnType<typeof agentApi.conversations>>) => void)
      | undefined;
    vi.mocked(agentApi.conversations)
      .mockResolvedValueOnce({ items: [first, second] })
      .mockResolvedValueOnce({ items: [first, second] })
      .mockImplementation(
        () =>
          new Promise((resolve) => {
            completeTitle = resolve;
          }),
      );
    vi.mocked(agentApi.detail).mockImplementation(async (id) => ({
      conversation: id === 1 ? first : second,
      runs:
        id === 1
          ? [{ ...run(31, "你好"), status: "running" }]
          : [{ ...run(32, "其他研究", "另一会话的回答"), conversationId: 2 }],
    }));
    const mounted = showAgent("workbench");
    await act(async () => vi.advanceTimersByTimeAsync(200));
    await act(async () => vi.advanceTimersByTimeAsync(1500));
    expect(completeTitle).toBeTypeOf("function");
    fireEvent.click(screen.getByRole("button", { name: /^另一会话/ }));
    await act(async () => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("另一会话的回答")).toBeVisible();
    await act(async () =>
      completeTitle?.({
        items: [{ ...first, title: "迟到的旧会话标题" }, second],
      }),
    );
    await act(async () => vi.advanceTimersByTimeAsync(20000));
    expect(screen.queryByText("迟到的旧会话标题")).not.toBeInTheDocument();
    expect(
      document.querySelector(".agent-conversation-heading strong"),
    ).toHaveTextContent("另一会话");
    expect(agentApi.conversations).toHaveBeenCalledTimes(3);
    mounted.unmount();
  } finally {
    vi.useRealTimers();
  }
});

it("conversation title refresh stops immediately after the server title changes", async () => {
  vi.useFakeTimers();
  try {
    const first = prepareFirstTurnTitleRefresh();
    let title = first.title;
    vi.mocked(agentApi.conversations).mockImplementation(async () => ({
      items: [{ ...first, title }],
    }));
    const mounted = showAgent("workbench");
    await act(async () => vi.advanceTimersByTimeAsync(200));
    const initialReads = vi.mocked(agentApi.conversations).mock.calls.length;
    await act(async () => vi.advanceTimersByTimeAsync(1500));
    title = "问候与交流";
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    expect(screen.getByRole("button", { name: /^问候与交流/ })).toBeVisible();
    expect(
      document.querySelector(".agent-conversation-heading strong"),
    ).toHaveTextContent("问候与交流");
    await act(async () => vi.advanceTimersByTimeAsync(20000));
    expect(agentApi.conversations).toHaveBeenCalledTimes(initialReads + 2);
    mounted.unmount();
  } finally {
    vi.useRealTimers();
  }
});

it("conversation title refresh preserves a manual rename against an in-flight automatic title", async () => {
  vi.useFakeTimers();
  try {
    const first = prepareFirstTurnTitleRefresh();
    let completeTitle:
      | ((value: Awaited<ReturnType<typeof agentApi.conversations>>) => void)
      | undefined;
    vi.mocked(agentApi.conversations)
      .mockResolvedValueOnce({ items: [first] })
      .mockResolvedValueOnce({ items: [first] })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            completeTitle = resolve;
          }),
      )
      .mockResolvedValue({ items: [{ ...first, title: "我的研究记录" }] });
    vi.spyOn(agentApi, "update").mockResolvedValue({
      ...first,
      title: "我的研究记录",
    });
    const mounted = showAgent("workbench");
    await act(async () => vi.advanceTimersByTimeAsync(200));
    await act(async () => vi.advanceTimersByTimeAsync(1500));
    fireEvent.click(screen.getByRole("button", { name: "重命名" }));
    await act(async () => vi.advanceTimersByTimeAsync(0));
    const dialog = screen.getByRole("dialog", { name: "重命名会话" });
    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: { value: "我的研究记录" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "OK" }));
    await act(async () => vi.advanceTimersByTimeAsync(0));
    await act(async () =>
      completeTitle?.({
        items: [{ ...first, title: "问候与交流" }],
      }),
    );
    await act(async () => vi.advanceTimersByTimeAsync(20000));
    expect(
      document.querySelector(".agent-conversation-heading strong"),
    ).toHaveTextContent("我的研究记录");
    expect(
      screen.queryByRole("button", { name: /^问候与交流/ }),
    ).not.toBeInTheDocument();
    expect(agentApi.update).toHaveBeenCalledExactlyOnceWith(1, {
      title: "我的研究记录",
    });
    expect(agentApi.conversations).toHaveBeenCalledTimes(4);
    mounted.unmount();
  } finally {
    vi.useRealTimers();
  }
});

it("conversation title refresh cancels pending metadata reads after switching projects", async () => {
  vi.useFakeTimers();
  try {
    prepareFirstTurnTitleRefresh();
    const mounted = showAgent("workbench");
    await act(async () => vi.advanceTimersByTimeAsync(200));
    const initialReads = vi.mocked(agentApi.conversations).mock.calls.length;
    projectCode.current = "2";
    vi.mocked(agentApi.conversations).mockResolvedValue({ items: [] });
    mounted.rerender(
      <AntApp>
        <MemoryRouter initialEntries={["/agent/workbench"]}>
          <AgentPage />
        </MemoryRouter>
      </AntApp>,
    );
    await act(async () => vi.advanceTimersByTimeAsync(20000));
    expect(agentApi.conversations).toHaveBeenCalledTimes(initialReads + 1);
    expect(
      screen.queryByText("你好，有什么可以帮您？"),
    ).not.toBeInTheDocument();
    expect(
      document.querySelector(".agent-conversation-heading strong"),
    ).toHaveTextContent("智能体");
    mounted.unmount();
  } finally {
    vi.useRealTimers();
  }
});

it.each(["later turn", "failed first turn"])(
  "conversation title refresh adds no requests for a %s",
  async (scenario) => {
    vi.useFakeTimers();
    try {
      const first = prepareFirstTurnTitleRefresh();
      const responding = { ...run(31, "你好"), status: "running" as const };
      if (scenario === "later turn")
        vi.mocked(agentApi.detail).mockResolvedValue({
          conversation: first,
          runs: [run(30, "上一轮"), responding],
        });
      if (scenario === "failed first turn")
        vi.mocked(agentApi.poll).mockResolvedValue({
          run: { ...responding, status: "failed" },
          events: [],
          cursor: 0,
        });
      const mounted = showAgent("workbench");
      await act(async () => vi.advanceTimersByTimeAsync(200));
      const initialReads = vi.mocked(agentApi.conversations).mock.calls.length;
      await act(async () => vi.advanceTimersByTimeAsync(20000));
      expect(agentApi.conversations).toHaveBeenCalledTimes(initialReads);
      mounted.unmount();
    } finally {
      vi.useRealTimers();
    }
  },
);

async function submitEffortQuestion() {
  fireEvent.change(screen.getByRole("textbox", { name: "输入消息" }), {
    target: { value: "核对本次思考强度" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(agentApi.submit).toHaveBeenCalledOnce());
}

function rerenderAgent(mounted: ReturnType<typeof showAgent>) {
  mounted.rerender(
    <AntApp>
      <MemoryRouter initialEntries={["/agent/workbench"]}>
        <AgentPage />
      </MemoryRouter>
    </AntApp>,
  );
}

it("logic effort defaults to explicit deep medium without touching the slider", async () => {
  projectCode.value = "02";
  localStorage.setItem("agent-thinking:99:agent", "fast");
  showAgent("workbench");
  await screen.findByText("旧问题");
  expect(
    screen.getByRole("button", { name: "调整思考强度" }),
  ).toHaveTextContent("标准");
  await submitEffortQuestion();
  expect(agentApi.submit).toHaveBeenCalledWith(
    1,
    expect.objectContaining({
      thinkingMode: "deep",
      reasoningEffort: "medium",
    }),
  );
});

it("logic effort restores deep medium when the user chooses the default strength", async () => {
  projectCode.value = "02";
  showAgent("workbench");
  await screen.findByText("旧问题");
  const control = screen.getByRole("button", { name: "调整思考强度" });
  fireEvent.click(control);
  fireEvent.keyDown(await screen.findByRole("slider", { name: "思考强度" }), {
    key: "Home",
    keyCode: 36,
  });
  expect(control).toHaveTextContent("轻量");
  fireEvent.click(screen.getByRole("button", { name: "使用默认强度" }));
  expect(control).toHaveTextContent("标准");
  fireEvent.click(control);
  await submitEffortQuestion();
  expect(agentApi.submit).toHaveBeenCalledWith(
    1,
    expect.objectContaining({
      thinkingMode: "deep",
      reasoningEffort: "medium",
    }),
  );
});

it.each(["low", "medium", "xhigh"] as const)(
  "logic chat preserves selected %s effort through asynchronous bootstrap recovery without legacy intake",
  async (effort) => {
    projectCode.value = "02";
    vi.spyOn(agentApi, "restoreLogicConfiguration").mockResolvedValue({
      configuration: {
        resourceIds: [],
        roles: {},
        fieldMapping: {},
        prompt: "沿用已确认的分析设置",
        reasoningEffort: effort,
      },
      unavailableResourceIds: [],
      items: [],
    });
    vi.spyOn(agentApi, "activeWorkflow").mockResolvedValue({ item: null });
    const mounted = showAgent("workbench");
    await screen.findByText("旧问题");
    const control = screen.getByRole("button", { name: "调整思考强度" });
    fireEvent.click(control);
    const slider = await screen.findByRole("slider", { name: "思考强度" });
    fireEvent.keyDown(slider, { key: "Home", keyCode: 36 });
    for (
      let step = 0;
      step < ["low", "medium", "xhigh"].indexOf(effort);
      step++
    )
      fireEvent.keyDown(slider, { key: "ArrowRight", keyCode: 39 });
    fireEvent.click(control);
    expect(agentApi.restoreLogicConfiguration).not.toHaveBeenCalled();
    const label = { low: "轻量", medium: "标准", xhigh: "深度" }[effort];
    expect(
      screen.getByRole("button", { name: "调整思考强度" }),
    ).toHaveTextContent(label);
    accessState.value = "unknown";
    accessState.status = "error";
    rerenderAgent(mounted);
    accessState.value = "confirmed";
    accessState.status = "ready";
    rerenderAgent(mounted);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "调整思考强度" }),
      ).toHaveTextContent(label),
    );
    await submitEffortQuestion();
    expect(agentApi.submit).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        thinkingMode: "deep",
        reasoningEffort: effort,
      }),
    );
  },
);

it.each(["policy", "model"])(
  "logic effort uses fast mode without an effort when disabled by the %s",
  async (disabledBy) => {
    projectCode.value = "02";
    const priorModels = bootstrap.models;
    const priorThinking = bootstrap.thinkingEnabled;
    try {
      if (disabledBy === "policy") bootstrap.thinkingEnabled = false;
      else
        bootstrap.models = priorModels.map((model) => ({
          ...model,
          supportsThinking: false,
        }));
      showAgent("workbench");
      await screen.findByText("旧问题");
      expect(
        screen.queryByRole("button", { name: "调整思考强度" }),
      ).not.toBeInTheDocument();
      await submitEffortQuestion();
      expect(agentApi.submit).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          thinkingMode: "fast",
          reasoningEffort: undefined,
        }),
      );
    } finally {
      bootstrap.models = priorModels;
      bootstrap.thinkingEnabled = priorThinking;
    }
  },
);

it("offers the pending review card instead of an ineffective send button", async () => {
  const waiting = waitingQuestion();
  waiting.status = "waiting_review";
  waiting.interaction = {
    ...waiting.interaction!,
    kind: "review",
    title: "请审核处置建议",
  };
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [waiting],
  });
  const answer = vi.spyOn(agentApi, "answerInteraction");
  showAgent();
  await screen.findByRole("region", { name: "等待您审核的问题" });
  const action = screen.getByRole("button", { name: "查看审核项" });
  expect(action).toBeEnabled();
  expect(
    screen.queryByRole("button", { name: "提交回答" }),
  ).not.toBeInTheDocument();
  fireEvent.click(action);
  expect(screen.getByRole("textbox", { name: /红光波段/ })).toHaveFocus();
  expect(answer).not.toHaveBeenCalled();
  expect(agentApi.submit).not.toHaveBeenCalled();
});

it.each([
  [1366, 768],
  [375, 812],
])(
  "keeps primary controls and native conversation drawer usable at %sx%s",
  async (width, height) => {
    await page.viewport(width, height);
    try {
      showAgent("workbench");
      await screen.findByText("旧问题");
      const send = screen.getByRole("button", { name: "发送" });
      const box = send.getBoundingClientRect();
      expect(box.bottom).toBeLessThanOrEqual(height);
      expect(box.right).toBeLessThanOrEqual(width);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
      if (width < 900) {
        fireEvent.click(screen.getByRole("button", { name: /^会\s*话$/ }));
        const close = await screen.findByRole("button", {
          name: "关闭会话列表",
        });
        await waitFor(() => expect(close).toHaveFocus());
        for (let i = 0; i < 12; i++) await userEvent.keyboard("{Tab}");
        expect(
          document.activeElement?.closest(".agent-history-drawer"),
        ).not.toBeNull();
        await page.screenshot({
          path: `../../test-results/agent-ui-drawer-${width}.png`,
        });
        await userEvent.keyboard("{Escape}");
        await waitFor(() => expect(close).not.toBeVisible());
      }
      await page.screenshot({
        path: `../../test-results/agent-ui-workspace-${width}.png`,
      });
    } finally {
      await page.viewport(1600, 900);
    }
  },
);

it("keeps thinking controls usable when browser preference storage is blocked", async () => {
  const read = Storage.prototype.getItem,
    write = Storage.prototype.setItem;
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(function (key) {
    if (key.startsWith("agent-thinking:"))
      throw new DOMException("blocked", "SecurityError");
    return read.call(this, key);
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(
    function (key, value) {
      if (key.startsWith("agent-thinking:"))
        throw new DOMException("blocked", "SecurityError");
      write.call(this, key, value);
    },
  );
  showAgent();
  await screen.findByText("旧问题");
  await submitEffortQuestion();
  expect(agentApi.submit).toHaveBeenCalledWith(
    1,
    expect.objectContaining({ thinkingMode: "deep" }),
  );
});

it("keeps a new draft when the initial conversation list returns late", async () => {
  let finish!: (
    value: Awaited<ReturnType<typeof agentApi.conversations>>,
  ) => void;
  vi.mocked(agentApi.conversations).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  showAgent();
  await waitFor(() => expect(agentApi.conversations).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByRole("button", { name: /新建会话/ }));
  await act(async () => finish({ items: [conversation] }));
  await waitFor(() =>
    expect(screen.getByRole("textbox", { name: "输入消息" })).toBeEnabled(),
  );
  expect(agentApi.detail).not.toHaveBeenCalled();
  expect(screen.queryByText("旧问题")).not.toBeInTheDocument();
});

it.each(["default", "02", "demo-geology-reasoning", "ecology-private"])(
  "uses the same compact agent interface and automatic discovery in project %s",
  async (code) => {
    projectCode.value = code;
    bootstrap.canChat = true;
    bootstrap.allowAttachments = true;
    const { container } = showAgent("workbench");
    await screen.findByText("旧问题");
    expect(container.querySelector(".agent-mode-nav")).toBeNull();
    for (const name of [
      "快速对话",
      "科研智能体",
      "选择数据",
      "调用算法",
      "知识库",
      "MH-workflow",
      "深度思考",
    ])
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "业务流" })).toBeVisible();
    expect(screen.getByRole("button", { name: "上传文档" })).toBeVisible();
    expect(
      screen.getByRole("button", { name: "调整思考强度" }),
    ).toHaveTextContent("标准");
    expect(agentApi.resources).not.toHaveBeenCalled();
    await submitEffortQuestion();
    expect(agentApi.submit).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        thinkingMode: "deep",
        reasoningEffort: "medium",
        dataSelectionMode: "auto",
        resourceIds: [],
        algorithmSelectionMode: "auto",
        algorithmVersionIds: [],
        knowledgeSelection: { mode: "auto", domains: [] },
      }),
    );
    if (code === "default")
      await page.screenshot({
        path: "../../test-results/unified-agent-desktop.png",
      });
  },
);

it("shows both historical conversation types in one sidebar and preserves their permissions", async () => {
  bootstrap.canChat = true;
  const chat = {
    ...conversation,
    id: 2,
    mode: "chat" as const,
    title: "原普通会话",
    updatedAt: "2026-11-13",
  };
  vi.mocked(agentApi.conversations).mockImplementation(async (mode) => ({
    items: mode === "agent" ? [conversation] : [chat],
  }));
  vi.mocked(agentApi.detail).mockImplementation(async (id) => ({
    conversation: id === 2 ? chat : conversation,
    runs: [
      {
        ...run(id, id === 2 ? "原普通问题" : "原科研问题"),
        conversationId: id,
      },
    ],
  }));
  showAgent("chat");
  await screen.findByText("原普通问题");
  expect(screen.getByRole("button", { name: /^历史会话/ })).toBeVisible();
  expect(screen.getByRole("button", { name: /^原普通会话/ })).toBeVisible();
  expect(agentApi.conversations).toHaveBeenCalledWith("agent", "", false);
  expect(agentApi.conversations).toHaveBeenCalledWith("chat", "", false);
  fireEvent.click(screen.getByRole("button", { name: /^历史会话/ }));
  await screen.findByText("原科研问题");
  expect(screen.queryByText("原普通问题")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "科研智能体" }),
  ).not.toBeInTheDocument();
});

it("uses automatic discovery after reopening a turn with legacy manual restrictions", async () => {
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation,
    runs: [
      {
        ...run(1, "原手选问题"),
        resourceIds: [10],
        dataSelectionMode: "manual",
        algorithmSelectionMode: "manual",
        algorithmVersionIds: [4],
        knowledgeSelection: { mode: "none", domains: [] },
      },
    ],
  });
  showAgent();
  await screen.findByText("原手选问题");
  await submitEffortQuestion();
  expect(agentApi.submit).toHaveBeenCalledWith(
    1,
    expect.objectContaining({
      resourceIds: [],
      dataSelectionMode: "auto",
      algorithmVersionIds: [],
      algorithmSelectionMode: "auto",
      knowledgeSelection: { mode: "auto", domains: [] },
    }),
  );
});

it("creates an agent conversation from the legacy chat URL when agent access is available", async () => {
  vi.mocked(agentApi.conversations).mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "create").mockResolvedValue(conversation);
  showAgent("chat");
  await screen.findByText("这个项目里有哪些可用资料？");
  await submitEffortQuestion();
  expect(agentApi.create).toHaveBeenCalledExactlyOnceWith("agent");
});

it("keeps the shared composer usable on a 390px screen without candidate selectors", async () => {
  await page.viewport(390, 844);
  try {
    bootstrap.allowAttachments = true;
    const { container } = showAgent("workbench");
    await screen.findByText("旧问题");
    for (const name of ["业务流", "上传文档", "调整思考强度", "发送"]) {
      const bounds = screen
        .getByRole("button", { name })
        .getBoundingClientRect();
      expect(bounds.left).toBeGreaterThanOrEqual(0);
      expect(bounds.right).toBeLessThanOrEqual(391);
    }
    expect(container.querySelector(".agent-mode-nav")).toBeNull();
    await page.screenshot({
      path: "../../test-results/unified-agent-mobile.png",
    });
  } finally {
    await page.viewport(1600, 900);
  }
});
