import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { agentApi } from "../api/agent";
import type {
  AgentBootstrap,
  AgentConversation,
  AgentResearchIntent,
  AgentRun,
  AgentWorkflow,
  AgentWorkflowUpload,
} from "../api/generated/types.gen";
import { reviewWorkflow } from "../map/geologyReview.testFixtures";
import AgentPage from "./AgentPage";

vi.mock("../components/WorkspaceHeader", () => ({
  default: () => <header>STISP</header>,
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { id: 99, permissions: {} } }),
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({
    current: "1",
    projects: [{ id: 1, name: "逻辑推理", code: projectCode }],
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

let projectCode = "02";
const bootstrap: AgentBootstrap = {
  canAgent: true,
  canChat: true,
  canManage: false,
  thinkingEnabled: false,
  internetEnabled: false,
  allowAttachments: false,
  workerOnline: true,
  defaultAgentModel: "mock",
  defaultChatModel: "mock",
  capabilities: [],
  models: [
    {
      alias: "mock",
      name: "模拟模型",
      status: "online",
      allowAgent: true,
      supportsThinking: false,
      supportsVision: false,
      contextWindowTokens: 32768,
      checkedAt: "",
    },
  ],
};
const conversation: AgentConversation = {
  id: 44,
  projectId: 1,
  mode: "agent",
  title: "本次逻辑推理",
  archived: false,
  createdAt: "",
  updatedAt: "",
};
const upload: AgentWorkflowUpload = {
  id: "upload-1",
  batchId: "a".repeat(32),
  resourceId: 812,
  name: "地质图",
  fileName: "地质图.geojson",
  dataType: "vector",
  sizeBytes: 512,
  roleHint: "lithology",
  workflowId: null,
  createdAt: "",
  profile: {
    kind: "vector",
    crs: "EPSG:4326",
    geometryTypes: ["Polygon"],
    featureCount: 4,
    bounds: [97, 35, 98, 36],
    bandCount: null,
    width: null,
    height: null,
    warnings: [],
    fields: [
      { name: "DCMC", type: "text", samples: ["八宝山组"], distinctCount: 1 },
    ],
  },
};
let workflow: AgentWorkflow;
let intent: AgentResearchIntent;
let runs: AgentRun[];
const chatRun = (): AgentRun => ({
  id: runs.length + 1,
  conversationId: 44,
  model: "mock",
  status: "succeeded",
  prompt: "检查上传资料并比较远景区",
  answer: intent.message,
  detail: "",
  evidence: [],
  attachments: [],
  interaction: null,
  interactionHistory: [],
  contextTruncated: false,
  createdAt: "",
  updatedAt: "",
  researchIntent: structuredClone(intent),
});
function show() {
  return render(
    <App>
      <MemoryRouter initialEntries={["/agent/workbench"]}>
        <AgentPage />
      </MemoryRouter>
    </App>,
  );
}
function syncIntent() {
  intent = {
    ...intent,
    revision: `${workflow.planHash}:${workflow.status}`,
    status:
      workflow.status === "queued"
        ? "planning"
        : workflow.status === "waiting_compute"
          ? "running"
          : workflow.status === "paused"
            ? "running"
            : workflow.status === "interrupted"
              ? "failed"
              : workflow.status,
    workflowId: workflow.id,
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
  projectCode = "02";
  runs = [];
  workflow = {
    ...reviewWorkflow(),
    projectId: 1,
    workflowType: "geology_generic",
    status: "waiting_approval",
    planHash: "fields-v1",
    modificationReview: undefined,
    resourceIds: [812],
    plan: {
      phase: "review_mapping",
      inputs: {},
      stages: [],
      fieldMappingReview: {
        confirmed: false,
        modelMode: "mock",
        questions: [],
        roles: [
          {
            role: "lithology",
            label: "地质图",
            resourceId: 812,
            fileName: "地质图.geojson",
            fields: upload.profile.fields.map((field) => field.name),
            targets: [
              {
                key: "name",
                label: "地层名称",
                required: true,
                field: "DCMC",
                reason: "按字段名推荐",
              },
            ],
          },
        ],
      },
    },
  };
  intent = {
    originRunId: 1,
    revision: "roles-v1",
    scenario: "geology_generic",
    status: "clarifying",
    goal: "检查上传资料并比较远景区",
    message: "请核对资料角色",
    questions: [
      {
        key: "upload_812",
        label: "第1份：地质图.geojson",
        kind: "choice",
        required: true,
        options: [
          { value: "lithology", label: "地质图" },
          { value: "coverage", label: "研究区范围" },
          { value: "skip", label: "不使用" },
        ],
      },
    ],
    inputs: {},
    parameters: { roleAnswers: { upload_812: "lithology" } },
    inputSummary: [],
    workflowId: null,
  };
  vi.spyOn(agentApi, "conversations").mockImplementation(async () => ({
    items: runs.length ? [conversation] : [],
  }));
  vi.spyOn(agentApi, "create").mockResolvedValue(conversation);
  vi.spyOn(agentApi, "detail").mockImplementation(async () => ({
    conversation,
    runs: structuredClone(runs),
  }));
  vi.spyOn(agentApi, "resources").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "researchDemoSummaries").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "workflowUploads").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "activeWorkflow").mockResolvedValue({
    item: null,
    parked: [],
  });
  vi.spyOn(agentApi, "restoreLogicConfiguration").mockResolvedValue({
    configuration: null,
    items: [],
    unavailableResourceIds: [],
  });
  vi.spyOn(agentApi, "uploadWorkflowBatch").mockResolvedValue({
    items: [upload],
    errors: [],
  });
  vi.spyOn(agentApi, "recognizeWorkflowRoles").mockResolvedValue({
    items: [],
    source: "rules",
    questions: [],
  });
  vi.spyOn(agentApi, "submit").mockImplementation(async () => {
    const next = chatRun();
    runs.push(next);
    return next;
  });
  vi.spyOn(agentApi, "workflow").mockImplementation(async (_id, options) =>
    options?.view === "card"
      ? {
          ...structuredClone(workflow),
          view: "card",
          steps: [],
          evidence: [],
          modificationReview: undefined,
          plan: { phase: workflow.plan.phase, stages: workflow.plan.stages },
          stepCount: 3,
        }
      : structuredClone(workflow),
  );
  vi.spyOn(agentApi, "poll").mockImplementation(async () => {
    syncIntent();
    const next = { ...runs[0]!, researchIntent: structuredClone(intent) };
    return { run: next, events: [], cursor: 0 };
  });
  vi.spyOn(agentApi, "updateResearchIntent").mockImplementation(
    async (_id, value) => {
      if (value.action === "answer") {
        intent = {
          ...intent,
          questions: [],
          parameters: {},
          workflowId: workflow.id,
        };
        syncIntent();
        const next = chatRun();
        runs.push(next);
        return next;
      }
      workflow = {
        ...workflow,
        status: "running",
        planHash: "executing",
        plan: { ...workflow.plan, phase: "decide" },
      };
      syncIntent();
      return { ...runs[0]!, researchIntent: structuredClone(intent) };
    },
  );
  vi.spyOn(agentApi, "confirmWorkflow").mockImplementation(
    async (_id, _hash, value) => {
      if (value?.fieldMapping)
        workflow = {
          ...workflow,
          planHash: "plan-v1",
          plan: {
            ...workflow.plan,
            phase: "review_plan",
            fieldMappingReview: undefined,
          },
        };
      else
        workflow = {
          ...workflow,
          status: "running",
          planHash: "recheck",
          plan: { ...workflow.plan, phase: "decide" },
        };
      return structuredClone(workflow);
    },
  );
});
afterEach(() => sessionStorage.clear());

it.each([
  [1461, 812, 7],
  [360, 800, 7],
  [1461, 812, 40],
  [360, 800, 40],
])(
  "%ipx×%ipx：%i 份资料及复用提示不挤出输入框和发送按钮",
  async (width, height, count) => {
    await page.viewport(width, height);
    const items = Array.from({ length: count }, (_, index) => ({
      ...upload,
      id: `catalog-${812 + index}`,
      resourceId: 812 + index,
      fileName: `第${index + 1}份地质调查资料与矿物识别结果.geojson`,
      source: "catalog" as const,
    }));
    vi.mocked(agentApi.restoreLogicConfiguration).mockResolvedValue({
      configuration: {
        resourceIds: items.map((item) => item.resourceId),
        roles: { lithology: 812 },
        fieldMapping: { lithology: { name: "DCMC" } },
        prompt: "沿用上次的检查要求",
        reasoningEffort: "low",
      },
      items,
      unavailableResourceIds: [],
    });
    const mounted = show();
    try {
      fireEvent.click(
        await screen.findByRole("button", { name: /(^|\s)逻辑推理$/ }),
      );
      await screen.findByText("沿用上次已确认的角色和字段");
      const input = screen.getByRole("textbox", { name: "输入消息" });
      const send = screen.getByRole("button", { name: "发送" });
      const assertInViewport = (element: HTMLElement) => {
        expect(element).toBeVisible();
        const bounds = element.getBoundingClientRect();
        expect(bounds.width).toBeGreaterThan(0);
        expect(bounds.height).toBeGreaterThan(0);
        expect(bounds.top).toBeGreaterThanOrEqual(0);
        expect(bounds.bottom).toBeLessThanOrEqual(height);
        expect(bounds.left).toBeGreaterThanOrEqual(0);
        expect(bounds.right).toBeLessThanOrEqual(width);
        const composer = document
          .querySelector(".agent-composer")!
          .getBoundingClientRect();
        expect(bounds.top).toBeGreaterThanOrEqual(composer.top);
        expect(bounds.bottom).toBeLessThanOrEqual(composer.bottom);
        expect(
          element.contains(
            document.elementFromPoint(
              bounds.left + bounds.width / 2,
              bounds.top + bounds.height / 2,
            ),
          ),
        ).toBe(true);
      };
      assertInViewport(input);
      assertInViewport(send);
      const files = document.querySelector<HTMLElement>(".agent-logic-files")!;
      expect(files.scrollHeight).toBeGreaterThan(files.clientHeight);
      files.scrollTop = files.scrollHeight;
      const context = document.querySelector<HTMLElement>(
        ".agent-composer-context",
      )!;
      context.scrollTop = context.scrollHeight;
      assertInViewport(input);
      assertInViewport(send);
      context.scrollTop = 0;
      fireEvent.click(screen.getByRole("button", { name: "收起" }));
      expect(
        screen.getByRole("button", { name: `已选 ${count} 份资料 · 展开` }),
      ).toBeVisible();
      assertInViewport(input);
      assertInViewport(send);
      expect(input).toHaveValue("沿用上次的检查要求");
    } finally {
      mounted.unmount();
      await page.viewport(1600, 900);
    }
  },
);

it("360px 输入区恢复服务端配置，收起保留选择且发送显式复用请求", async () => {
  await page.viewport(360, 800);
  vi.mocked(agentApi.restoreLogicConfiguration).mockResolvedValue({
    configuration: {
      resourceIds: [812],
      roles: { lithology: 812 },
      fieldMapping: { lithology: { name: "DCMC" } },
      prompt: "沿用上次的检查要求",
      reasoningEffort: "low",
    },
    items: [{ ...upload, source: "catalog" }],
    unavailableResourceIds: [],
  });
  const mounted = show();
  try {
    const trigger = await screen.findByRole("button", {
      name: /(^|\s)逻辑推理$/,
    });
    expect(trigger).not.toHaveTextContent("执行失败");
    fireEvent.click(trigger);
    await screen.findByText("沿用上次已确认的角色和字段");
    const input = screen.getByPlaceholderText(
      "输入问题，Enter 发送，Shift+Enter 换行",
    );
    expect(input).toHaveValue("沿用上次的检查要求");
    const panel = screen.getByRole("region", { name: "上传本次资料" });
    expect(panel.getBoundingClientRect().right).toBeLessThanOrEqual(360);
    fireEvent.click(screen.getByRole("button", { name: "收起" }));
    fireEvent.click(
      screen.getByRole("button", { name: "已选 1 份资料 · 展开" }),
    );
    expect(agentApi.restoreLogicConfiguration).toHaveBeenCalledTimes(1);
    expect(screen.getByText(upload.fileName)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() =>
      expect(agentApi.submit).toHaveBeenCalledWith(
        44,
        expect.objectContaining({
          prompt: "沿用上次的检查要求",
          reuseConfirmedConfiguration: true,
          thinkingMode: "fast",
        }),
      ),
    );
  } finally {
    mounted.unmount();
    await page.viewport(1600, 900);
  }
});

it("收起资料不删除引用，清空作为独立操作解除系统数据引用", async () => {
  vi.mocked(agentApi.restoreLogicConfiguration).mockResolvedValue({
    configuration: {
      resourceIds: [812],
      roles: { lithology: 812 },
      fieldMapping: { lithology: { name: "DCMC" } },
      prompt: "核对系统资料",
      reasoningEffort: "low",
    },
    items: [{ ...upload, source: "catalog" }],
    unavailableResourceIds: [],
  });
  vi.spyOn(agentApi, "deleteWorkflowUpload").mockResolvedValue(undefined);
  const mounted = show();
  try {
    fireEvent.click(
      await screen.findByRole("button", { name: /(^|\s)逻辑推理$/ }),
    );
    await screen.findByText(upload.fileName);
    fireEvent.click(screen.getByRole("button", { name: "收起" }));
    expect(agentApi.deleteWorkflowUpload).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "已选 1 份资料 · 展开" }),
    );
    fireEvent.click(screen.getByRole("button", { name: /清\s*空/ }));
    await waitFor(() =>
      expect(agentApi.deleteWorkflowUpload).toHaveBeenCalledWith(upload.id),
    );
    await waitFor(() =>
      expect(screen.queryByText(upload.fileName)).not.toBeInTheDocument(),
    );
    expect(
      screen.queryByText("沿用上次已确认的角色和字段"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "选择系统数据" })).toBeVisible();
  } finally {
    mounted.unmount();
  }
});

it("逻辑推理入口显示计算任务所属对话与查看入口，停放任务不提示阻塞", async () => {
  vi.mocked(agentApi.activeWorkflow).mockResolvedValue({
    item: {
      id: "computing-workflow",
      goal: "核对另一区地质图",
      workflowType: "geology_generic",
      status: "running",
      updatedAt: "2026-11-05T08:00:00Z",
      projectId: 3,
      conversationId: 42,
      conversationTitle: "另一区复查",
    },
    parked: [
      {
        id: "parked-workflow",
        goal: "等待旧结果确认",
        workflowType: "geology_generic",
        status: "waiting_approval",
        updatedAt: "2026-11-04T08:00:00Z",
        projectId: 3,
      },
    ],
  });
  const mounted = show();
  try {
    fireEvent.click(
      await screen.findByRole("button", { name: /(^|\s)逻辑推理$/ }),
    );
    expect(
      await screen.findByText("正在计算或排队：核对另一区地质图"),
    ).toBeVisible();
    expect(screen.getByText(/对话：另一区复查/)).toBeVisible();
    expect(
      screen.getByText("已停放，不阻挡新任务：等待旧结果确认"),
    ).toBeVisible();
    expect(screen.getAllByRole("button", { name: "查看" })).toHaveLength(2);
  } finally {
    mounted.unmount();
  }
});

it("沿用配置的对话卡片仍要求本次计划确认，并提供一键重新核对", async () => {
  workflow.plan = {
    ...workflow.plan,
    reusedConfiguration: true,
    phase: "review_plan",
  };
  workflow.status = "waiting_approval";
  syncIntent();
  runs = [chatRun()];
  const mounted = show();
  try {
    await screen.findByText("沿用上次已确认的角色和字段");
    expect(screen.getByRole("button", { name: "确认执行" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "修改角色和字段" }));
    await waitFor(() =>
      expect(agentApi.updateResearchIntent).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          action: "answer",
          answer: "修改角色和字段",
          answers: {},
        }),
      ),
    );
  } finally {
    mounted.unmount();
  }
});

it("逻辑项目在当前对话从ZIP上传走到批准，恢复历史并保留成果地图入口", async () => {
  const mounted = show();
  fireEvent.click(
    await screen.findByRole("button", { name: /(^|\s)逻辑推理$/ }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "上传文件/ZIP" })).toBeEnabled(),
  );
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
  fireEvent.change(input, {
    target: {
      files: [
        new File(["fixture"], "本次资料.zip", { type: "application/zip" }),
      ],
    },
  });
  await screen.findByText(/已选 1 份资料/);
  expect(agentApi.recognizeWorkflowRoles).not.toHaveBeenCalled();
  fireEvent.change(
    screen.getByPlaceholderText("输入问题，Enter 发送，Shift+Enter 换行"),
    { target: { value: "检查上传资料并比较远景区" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await screen.findByRole("combobox", { name: "第1份：地质图.geojson" });
  expect(agentApi.submit).toHaveBeenCalledWith(
    44,
    expect.objectContaining({
      uploadBatchId: expect.stringMatching(/^[a-f0-9]{32}$/),
    }),
  );
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "继续分析" }));
  const fields = await screen.findByRole("region", { name: "确认字段含义" });
  fireEvent.click(within(fields).getByRole("button", { name: /确认/ }));
  fireEvent.click(await screen.findByRole("button", { name: "确认执行" }));
  await waitFor(() =>
    expect(agentApi.updateResearchIntent).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ action: "confirm" }),
    ),
  );
  const review = reviewWorkflow().modificationReview!;
  workflow = {
    ...workflow,
    status: "waiting_approval",
    planHash: "suggestions-v1",
    plan: { ...workflow.plan, phase: "review_modifications" },
    modificationReview: {
      ...review,
      suggestions: review.suggestions.map((item, index) => ({
        ...item,
        kind: "multi_element",
        element: index ? "structure" : "lithology",
        action: "set_code",
        status: "suggested",
      })),
    },
  };
  await screen.findByRole(
    "region",
    { name: "多要素检查建议" },
    { timeout: 5000 },
  );
  const group = screen
    .getByText(/岩性 \/ .* \/ 改代号/, { selector: "summary" })
    .closest("details")!;
  fireEvent.click(group.querySelector("summary")!);
  const first = await screen.findByText("岩性 / 填补内部漏填");
  const object = first.closest("details")!;
  fireEvent.click(object.querySelector("summary")!);
  fireEvent.click(within(object).getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "批准所选操作并继续" }));
  fireEvent.click(await screen.findByRole("button", { name: "批准并继续" }));
  await waitFor(() =>
    expect(agentApi.confirmWorkflow).toHaveBeenCalledWith(
      workflow.id,
      "suggestions-v1",
      expect.objectContaining({ selectedSuggestionIds: ["suggest-gap"] }),
    ),
  );
  workflow = {
    ...workflow,
    status: "succeeded",
    planHash: "done",
    detail: "复查与远景区比较完成",
    resultResourceIds: [201, 202],
    plan: {
      ...workflow.plan,
      phase: "completed",
      stages: [
        {
          name: "prospect",
          outputs: [
            { key: "before_zones", kind: "vector", resourceId: 201 },
            { key: "after_zones", kind: "vector", resourceId: 202 },
          ],
        },
      ],
    },
  };
  syncIntent();
  runs = runs.map((item) => ({
    ...item,
    researchIntent: structuredClone(intent),
  }));
  mounted.unmount();
  vi.mocked(agentApi.workflow).mockClear();
  vi.mocked(agentApi.poll).mockClear();
  show();
  const link = await screen.findByRole("link", {
    name: "在地理工作台对比成果图层",
  });
  expect(link).toHaveAttribute(
    "href",
    `/map?geologyCompare=${workflow.id}&projectTagId=1`,
  );
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener");
  expect(
    screen.getByRole("region", { name: "工作流进度卡片" }),
  ).toHaveTextContent("已保存 2 项成果");
  expect(agentApi.workflow).toHaveBeenCalledExactlyOnceWith(workflow.id, {
    view: "card",
  });
  expect(agentApi.poll).not.toHaveBeenCalled();
  await new Promise((resolve) => setTimeout(resolve, 2100));
  expect(agentApi.workflow).toHaveBeenCalledOnce();
  expect(agentApi.poll).not.toHaveBeenCalled();
});

it("其他项目仍保留MH-workflow入口，不显示对话内资料上传", async () => {
  projectCode = "default";
  show();
  expect(
    await screen.findByRole("button", { name: /MH-workflow/ }),
  ).toBeVisible();
  expect(screen.queryByRole("button", { name: /(^|\s)逻辑推理$/ })).toBeNull();
  expect(agentApi.workflowUploads).not.toHaveBeenCalled();
});
