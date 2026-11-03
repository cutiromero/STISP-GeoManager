import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentBootstrap,
  AgentResearchIntent,
  AgentRun,
  AgentWorkflow,
} from "../api/generated/types.gen";
import AgentPage from "./AgentPage";
import { liveComputeTask } from "./computeFlow.testFixtures";
import { workflowReport } from "./workflowReport.testFixtures";

vi.mock("../components/WorkspaceHeader", () => ({
  default: () => <header>STISP</header>,
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { id: 99, permissions: {} } }),
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({
    current: "1",
    projects: [{ id: 1, name: "演示项目" }],
  }),
}));
vi.mock("./useAgentBootstrap", () => ({
  useAgentBootstrapState: () => ({
    bootstrap,
    status: "ready",
    error: "",
    retry: vi.fn(),
  }),
}));
const bootstrap: AgentBootstrap = {
  canAgent: true,
  canChat: true,
  canManage: false,
  thinkingEnabled: true,
  internetEnabled: false,
  allowAttachments: false,
  workerOnline: true,
  defaultAgentModel: "qwen27b",
  defaultChatModel: "qwen27b",
  capabilities: [],
  models: [
    {
      alias: "qwen27b",
      name: "Qwen 真实模型",
      status: "online",
      allowAgent: true,
      supportsThinking: true,
      supportsVision: false,
      contextWindowTokens: 32768,
      checkedAt: "",
    },
  ],
};
const oldConversation = {
  id: 1,
  projectId: 1,
  mode: "agent" as const,
  title: "之前的会话",
  archived: false,
  createdAt: "",
  updatedAt: "",
};
const newConversation = { ...oldConversation, id: 22, title: "植被变化调查" };
function intent(extra: Partial<AgentResearchIntent> = {}): AgentResearchIntent {
  return {
    originRunId: 101,
    revision: "clarification-v1",
    scenario: "ecology_investigation",
    status: "clarifying",
    goal: "解释变化并安排调查",
    message: "您希望如何选择调查优先区？",
    questions: [
      {
        key: "priority",
        label: "调查排序方式",
        kind: "choice",
        required: true,
        options: [
          {
            value: "evidence",
            label: "结合观测与实际统计",
            description: "同时核对数据质量",
          },
        ],
      },
    ],
    inputs: { early_image: 10 },
    parameters: {},
    workflowId: null,
    inputSummary: [
      {
        role: "early_image",
        label: "前期影像",
        resourceId: 10,
        name: "模拟前期影像",
        sourceNote: "模拟资料",
      },
    ],
    ...extra,
  };
}
function run(id = 101, extra: Partial<AgentRun> = {}): AgentRun {
  return {
    id,
    conversationId: 22,
    model: "qwen27b",
    status: "succeeded",
    prompt: "请分析两期植被变化并保存调查成果",
    answer: "已经找到模拟影像与可用算法。",
    detail: "",
    evidence: [],
    attachments: [],
    contextTruncated: false,
    createdAt: "",
    updatedAt: "",
    researchIntent: intent(),
    ...extra,
  };
}
function workflow(
  status: AgentWorkflow["status"] = "succeeded",
): AgentWorkflow {
  return {
    id: "workflow-actual",
    projectId: 1,
    workflowType: "ecology_investigation",
    goal: "解释变化并安排调查",
    model: "qwen27b",
    status,
    detail: "已读取真实计算统计，形成调查建议",
    currentStep: "done",
    iteration: 2,
    operatorSteps: 4,
    maxIterations: 8,
    maxOperatorSteps: 12,
    executeOperators: true,
    resourceIds: [10],
    algorithmVersionId: null,
    parameters: {},
    resultIds: [],
    evidence: [],
    runtime: "worker",
    plan: {
      stages: [{ outputs: [{ kind: "vector", resourceId: 204 }] }],
      inputNames: { early_image: "模拟前期影像" },
    },
    planHash: "current-plan",
    importResults: true,
    resultResourceIds: [204],
    createdAt: "",
    updatedAt: "",
    steps: [
      {
        id: 1,
        sequence: 1,
        kind: "analysis_decision",
        status: "succeeded",
        message: "调查建议已形成",
        action: {},
        inputRefs: {},
        outputRefs: {},
        metrics: {},
        computeTaskId: "actual-task",
        errorCode: "",
        startedAt: "",
        finishedAt: "",
        decision: {
          problem: "需要调查哪些变化？",
          findings: ["共同有效覆盖率为 80%"],
          judgement: "缺资料区优先补充观测，变化区安排调查",
          uncertainties: ["模拟资料用于演示"],
          algorithmReason: "使用分区统计核对变化",
          resultSummary: "实际计算得到 4 个分区",
          nextAction: "finish",
          evidenceRefs: [{ kind: "output", id: "stat", title: "statistics" }],
          modelMode: "real",
          modelName: "Qwen 真实模型",
        },
      },
    ],
  };
}
function LocationState() {
  const location = useLocation();
  return (
    <output aria-label="导航状态">{JSON.stringify(location.state)}</output>
  );
}
function show(state?: object) {
  return render(
    <AntApp>
      <MemoryRouter initialEntries={[{ pathname: "/agent/workbench", state }]}>
        <AgentPage />
        <LocationState />
      </MemoryRouter>
    </AntApp>,
  );
}
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(agentApi, "prepareWorkflowReport").mockResolvedValue(
    workflowReport(),
  );
  localStorage.clear();
  sessionStorage.clear();
  vi.spyOn(agentApi, "conversations").mockResolvedValue({
    items: [oldConversation],
  });
  vi.spyOn(agentApi, "create").mockResolvedValue(newConversation);
  vi.spyOn(agentApi, "resources").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "bootstrap").mockResolvedValue(bootstrap);
  vi.spyOn(agentApi, "workflows").mockResolvedValue({ items: [] });
  vi.spyOn(computeApi, "algorithms").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(computeApi, "inputs").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(agentApi, "detail").mockResolvedValue({
    conversation: newConversation,
    runs: [run()],
  });
  vi.spyOn(agentApi, "submit").mockResolvedValue(run());
  vi.spyOn(agentApi, "poll").mockResolvedValue({
    run: run(),
    cursor: 0,
    events: [],
  });
  vi.spyOn(agentApi, "workflow").mockResolvedValue(workflow());
  vi.spyOn(computeApi, "task").mockResolvedValue(liveComputeTask("succeeded"));
});

it("shows a live research cursor, pauses for approval and restores without replaying decisions", async () => {
  let currentIntent = intent({
    status: "running",
    questions: [],
    workflowId: "workflow-actual",
  });
  let currentWorkflow: AgentWorkflow = {
    ...workflow("running"),
    currentStep: "review_plan",
    detail: "已完成变化统计，模型正在读取结果",
    plan: {
      phase: "decide",
      stageIndex: 0,
      stages: [
        {
          identifier: "ecology-priority",
          modelAttempts: [
            { status: "requesting", response: "未经校验的JSON响应" },
          ],
        },
      ],
    },
  };
  vi.mocked(agentApi.detail).mockImplementation(async () => ({
    conversation: newConversation,
    runs: [run(101, { researchIntent: currentIntent })],
  }));
  vi.mocked(agentApi.poll).mockImplementation(async () => ({
    run: run(101, { researchIntent: currentIntent }),
    cursor: 0,
    events: [],
  }));
  vi.mocked(agentApi.workflow).mockImplementation(async () => currentWorkflow);
  const mounted = show();
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("当前任务")).getByText("模型正在分析"),
    ).toBeVisible(),
  );
  expect(
    document.querySelector(
      ".agent-sidebar-task .agent-activity-mark.is-working",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText("未经校验的JSON响应")).not.toBeInTheDocument();
  expect(document.querySelectorAll(".is-new-decision")).toHaveLength(0);
  await page.screenshot({
    path: "../../test-results/agent-live-research-desktop.png",
  });
  await page.viewport(390, 844);
  try {
    const activity = screen
      .getByLabelText("科研任务")
      .querySelector(".agent-activity")!;
    await waitFor(() =>
      expect(activity.getBoundingClientRect().right).toBeLessThanOrEqual(390),
    );
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390);
    await page.screenshot({
      path: "../../test-results/agent-live-research-mobile.png",
    });
  } finally {
    await page.viewport(1600, 900);
  }
  currentIntent = {
    ...currentIntent,
    status: "waiting_approval",
    revision: "review-2",
  };
  currentWorkflow = {
    ...currentWorkflow,
    status: "waiting_approval",
    detail: "请审核实际计算成果",
  };
  await waitFor(
    () =>
      expect(
        within(screen.getByLabelText("当前任务")).getByText("等待您确认"),
      ).toBeVisible(),
    { timeout: 5000 },
  );
  expect(
    document.querySelector(
      ".agent-sidebar-task .agent-activity-mark.is-working",
    ),
  ).not.toBeInTheDocument();
  const review = screen.getByLabelText("科研任务");
  expect(
    review.querySelector(".agent-activity.is-working"),
  ).not.toBeInTheDocument();
  currentIntent = { ...currentIntent, status: "succeeded", revision: "done-3" };
  currentWorkflow = {
    ...currentWorkflow,
    status: "succeeded",
    currentStep: "done",
    detail: "报告和成果已保存",
  };
  await waitFor(
    () =>
      expect(
        within(screen.getByLabelText("当前任务")).getByText("研究已完成"),
      ).toBeVisible(),
    { timeout: 5000 },
  );
  expect(
    document.querySelector(".agent-sidebar-task .agent-activity-track"),
  ).not.toBeInTheDocument();
  mounted.unmount();
  show();
  fireEvent.click(await screen.findByText(/查看分析过程/));
  await screen.findByLabelText("分析说明与决策依据");
  expect(document.querySelectorAll(".is-new-decision")).toHaveLength(0);
  expect(
    document.querySelector(
      ".agent-sidebar-task .agent-activity-mark.is-working",
    ),
  ).not.toBeInTheDocument();
});

it("starts in a new conversation once, consumes the entry state, and restores on refresh", async () => {
  sessionStorage.setItem("agent-conversation:99:1:agent", "1");
  const mounted = show({
    researchDemo: {
      scenario: "ecology_investigation",
      projectId: 1,
      prompt: "使用模拟两期影像和预设，分析植被变化并保存成果",
      token: "launch-once-123",
    },
  });
  await screen.findByLabelText("科研任务");
  expect(agentApi.create).toHaveBeenCalledTimes(1);
  expect(agentApi.submit).toHaveBeenCalledWith(
    22,
    expect.objectContaining({
      demoScenario: "ecology_investigation",
      idempotencyKey: "launch-once-123",
      prompt: "使用模拟两期影像和预设，分析植被变化并保存成果",
      model: "qwen27b",
    }),
  );
  expect(agentApi.detail).not.toHaveBeenCalled();
  expect(screen.getByLabelText("导航状态")).toHaveTextContent("null");
  expect(sessionStorage.getItem("agent-conversation:99:1:agent")).toBe("22");
  mounted.unmount();
  vi.mocked(agentApi.conversations).mockResolvedValue({
    items: [newConversation, oldConversation],
  });
  show();
  await screen.findByLabelText("科研任务");
  expect(agentApi.detail).toHaveBeenCalledWith(22);
  expect(agentApi.create).toHaveBeenCalledTimes(1);
  expect(agentApi.submit).toHaveBeenCalledTimes(1);
});

it("accepts an online selection plus free explanation, continues and shows actual decisions and maps", async () => {
  const next = run(102, {
    prompt: "我选结合观测",
    researchIntent: intent({
      revision: "started-v2",
      status: "running",
      questions: [],
      workflowId: "workflow-actual",
    }),
  });
  vi.spyOn(agentApi, "updateResearchIntent").mockResolvedValue(next);
  vi.mocked(agentApi.poll).mockResolvedValue({
    run: {
      ...next,
      researchIntent: intent({
        revision: "done-v3",
        status: "succeeded",
        questions: [],
        workflowId: "workflow-actual",
      }),
    },
    events: [],
    cursor: 0,
  });
  show();
  fireEvent.click(await screen.findByRole("button", { name: "继续分析" }));
  await screen.findByText("请回答必填问题，或在补充说明中告诉智能体您的选择。");
  expect(agentApi.updateResearchIntent).not.toHaveBeenCalled();
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "调查排序方式" }));
  fireEvent.click(
    await screen.findByText("结合观测与实际统计", {
      selector: ".ant-select-item-option-content div",
    }),
  );
  fireEvent.change(screen.getByRole("textbox", { name: "补充说明" }), {
    target: { value: "质量不足处请单列补资料。" },
  });
  fireEvent.click(screen.getByRole("button", { name: "继续分析" }));
  fireEvent.click(await screen.findByText(/查看分析过程/));
  await screen.findByLabelText("分析说明与决策依据");
  expect(agentApi.updateResearchIntent).toHaveBeenCalledWith(101, {
    action: "answer",
    revision: "clarification-v1",
    answers: { priority: "evidence" },
    answer: "质量不足处请单列补资料。",
  });
  expect(screen.getAllByLabelText("科研任务")).toHaveLength(1);
  expect(
    within(screen.getByLabelText("研究结论")).getByText(
      "实际计算得到 4 个分区",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "在地理工作台对比成果图层" }),
  ).toHaveAttribute("href", "/map?resources=204&projectTagId=1");
  fireEvent.click(screen.getByText(/查看分析过程/));
  await page.screenshot({
    path: "../../test-results/research-chat-demo-desktop.png",
  });
});

it("parses a normal chat reply as an answer to the active clarification", async () => {
  vi.spyOn(agentApi, "updateResearchIntent").mockResolvedValue(
    run(102, {
      prompt: "按实际变化和观测排序",
      researchIntent: intent({ status: "planning", questions: [] }),
    }),
  );
  show();
  await screen.findByLabelText("科研任务");
  fireEvent.change(
    screen.getByPlaceholderText("输入问题，Enter 发送，Shift+Enter 换行"),
    { target: { value: "按实际变化和观测排序" } },
  );
  fireEvent.click(screen.getByRole("button", { name: /发送/ }));
  await waitFor(() =>
    expect(agentApi.updateResearchIntent).toHaveBeenCalledWith(101, {
      action: "answer",
      revision: "clarification-v1",
      answer: "按实际变化和观测排序",
    }),
  );
  expect(agentApi.submit).not.toHaveBeenCalled();
});

it("pauses the research task after confirmation and resumes into review without bypassing approval", async () => {
  const currentIntent = intent({
    status: "running",
    questions: [],
    workflowId: "workflow-actual",
  });
  let currentWorkflow = workflow("running");
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation: newConversation,
    runs: [run(101, { researchIntent: currentIntent })],
  });
  vi.mocked(agentApi.poll).mockResolvedValue({
    run: run(101, { researchIntent: currentIntent }),
    events: [],
    cursor: 0,
  });
  vi.mocked(agentApi.workflow).mockImplementation(async () => currentWorkflow);
  const pause = vi
    .spyOn(agentApi, "pauseWorkflow")
    .mockImplementation(async () => {
      currentWorkflow = {
        ...currentWorkflow,
        status: "paused",
        pausedFrom: "waiting_approval",
      };
      return currentWorkflow;
    });
  const resume = vi
    .spyOn(agentApi, "resumeWorkflow")
    .mockImplementation(async () => {
      currentWorkflow = {
        ...currentWorkflow,
        status: "waiting_approval",
        plan: { ...currentWorkflow.plan, reviewOutputs: [31] },
      };
      return currentWorkflow;
    });
  const confirm = vi.spyOn(agentApi, "confirmWorkflow");
  show();
  const task = await screen.findByLabelText("科研任务");
  fireEvent.click(
    await within(task).findByRole("button", { name: "暂停任务" }),
  );
  expect(pause).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole("button", { name: "确认暂停" }));
  await within(task).findByRole("button", { name: "继续任务" });
  expect(pause).toHaveBeenCalledWith("workflow-actual");
  fireEvent.click(within(task).getByRole("button", { name: "继续任务" }));
  await within(task).findByRole("button", { name: "审核通过并继续" });
  expect(resume).toHaveBeenCalledWith("workflow-actual");
  expect(confirm).not.toHaveBeenCalled();
  expect(agentApi.submit).not.toHaveBeenCalled();
});

it("restores an actual review, waits for explicit approval and uses its current revision", async () => {
  vi.spyOn(agentApi, "updateResearchIntent");
  const reviewIntent = intent({
    status: "waiting_approval",
    questions: [],
    workflowId: "workflow-actual",
    revision: "review-current",
  });
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation: newConversation,
    runs: [
      run(101, { researchIntent: { ...reviewIntent, revision: "old-plan" } }),
    ],
  });
  vi.mocked(agentApi.poll).mockResolvedValue({
    run: run(101, { researchIntent: reviewIntent }),
    events: [],
    cursor: 0,
  });
  vi.mocked(agentApi.workflow).mockResolvedValue({
    ...workflow("waiting_approval"),
    plan: { reviewOutputs: [{ label: "几何修复审核" }] },
  });
  vi.spyOn(agentApi, "confirmWorkflow").mockResolvedValue(workflow("running"));
  show();
  const button = await screen.findByRole("button", { name: "审核通过并继续" });
  expect(agentApi.updateResearchIntent).not.toHaveBeenCalled();
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("科研任务")).getAllByText("等待您审核")
        .length,
    ).toBeGreaterThan(0),
  );
  fireEvent.change(screen.getByRole("textbox", { name: "审核意见" }), {
    target: { value: "核对完成，保留原质量提示" },
  });
  fireEvent.click(button);
  fireEvent.click(await screen.findByRole("button", { name: "确认通过" }));
  await waitFor(() =>
    expect(agentApi.confirmWorkflow).toHaveBeenCalledWith(
      "workflow-actual",
      "current-plan",
      {
        decision: "approve",
        feedback: "核对完成，保留原质量提示",
      },
    ),
  );
});

it("keeps clarification usable on a phone without horizontal overflow", async () => {
  await page.viewport(390, 844);
  show();
  await screen.findByRole("combobox", { name: "调查排序方式" });
  const card = screen.getByLabelText("科研任务");
  expect(card.getBoundingClientRect().width).toBeLessThanOrEqual(390);
  expect(card.scrollWidth).toBeLessThanOrEqual(card.clientWidth + 1);
  await page.screenshot({
    path: "../../test-results/research-chat-demo-phone.png",
  });
  await page.viewport(1600, 900);
});

it("keeps the latest chat workflow state when an older failed task arrives later", async () => {
  const oldIntent = intent({
    status: "failed",
    workflowId: "older-flow",
    questions: [],
  });
  const currentIntent = intent({
    originRunId: 102,
    status: "running",
    workflowId: "current-flow",
    questions: [],
    goal: "当前正在分析的任务",
  });
  let finishOld: (value: AgentWorkflow) => void = () => {};
  const oldResponse = new Promise<AgentWorkflow>((resolve) => {
    finishOld = resolve;
  });
  const current = {
    ...workflow("running"),
    id: "current-flow",
    detail: "正在读取本次证据",
    plan: {
      phase: "decide",
      stageIndex: 0,
      stages: [
        {
          identifier: "ecology-priority",
          modelAttempts: [{ status: "requesting" }],
        },
      ],
    },
  };
  vi.mocked(agentApi.detail).mockResolvedValue({
    conversation: newConversation,
    runs: [
      run(101, { researchIntent: oldIntent }),
      run(102, { researchIntent: currentIntent }),
    ],
  });
  vi.mocked(agentApi.workflow).mockImplementation(async (id) =>
    id === "older-flow" ? oldResponse : current,
  );
  vi.mocked(agentApi.poll).mockImplementation(async (id) => ({
    run: run(id, { researchIntent: id === 101 ? oldIntent : currentIntent }),
    events: [],
    cursor: 0,
  }));
  show();
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("当前任务")).getByText("模型正在分析"),
    ).toBeVisible(),
  );
  finishOld({ ...workflow("failed"), id: "older-flow", detail: "旧任务失败" });
  await screen.findByText("旧任务失败");
  expect(
    within(screen.getByLabelText("当前任务")).getByText("模型正在分析"),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: /MH-workflow.*正在分析/ }),
  ).toBeVisible();
});
