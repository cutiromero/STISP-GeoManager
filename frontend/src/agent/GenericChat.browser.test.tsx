import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
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
function CurrentPath() {
  return <output data-testid="current-path">{useLocation().pathname}</output>;
}
function show() {
  return render(
    <App>
      <MemoryRouter initialEntries={["/agent/workbench"]}>
        <Routes>
          <Route path="/agent/workbench" element={<AgentPage />} />
          <Route path="/business-flows" element={<h1>业务流目录</h1>} />
        </Routes>
        <CurrentPath />
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
          plan: {
            phase: workflow.plan.phase,
            stages: workflow.plan.stages,
            reusedConfiguration: workflow.plan.reusedConfiguration,
            fieldMappingReview: workflow.plan.fieldMappingReview,
          },
          stepCount: 3,
        }
      : { ...structuredClone(workflow), view: options?.view ?? "full" },
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
          status: value.executeAfterMapping ? "queued" : "waiting_approval",
          executeOperators: Boolean(value.executeAfterMapping),
          planHash: "plan-v1",
          plan: {
            ...workflow.plan,
            phase: value.executeAfterMapping ? "build_inputs" : "review_plan",
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

it("逻辑项目仅通过业务流入口发起新任务，历史直接入口不再加载", async () => {
  show();
  const entry = await screen.findByRole("button", {
    name: "从业务流开始逻辑推理",
    exact: true,
  });
  expect(
    screen.queryByRole("button", { name: /(^|\s)逻辑推理$/ }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "上传本次资料" }),
  ).not.toBeInTheDocument();
  expect(agentApi.restoreLogicConfiguration).not.toHaveBeenCalled();
  fireEvent.click(entry);
  await waitFor(() =>
    expect(screen.getByTestId("current-path")).toHaveTextContent(
      "/business-flows",
    ),
  );
  expect(agentApi.submit).not.toHaveBeenCalled();
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
    expect(screen.getByRole("button", { name: "确认并继续" })).toBeVisible();
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

it("资料确认直接显示本次模型角色判断及具体依据", async () => {
  intent.questions = [];
  intent.inputSummary = [
    {
      role: "lithology",
      label: "地质图",
      resourceId: 812,
      name: "本次岩性图",
      sourceNote: "系统数据引用",
      roleSource: "model",
      roleReason: "矢量面包含地层名称与代号，作为岩性资料",
    },
  ];
  syncIntent();
  runs = [chatRun()];
  const mounted = show();
  try {
    expect(await screen.findByText("模型角色判断")).toBeVisible();
    expect(screen.getByText(/矢量面包含地层名称与代号/)).toBeVisible();
    expect(screen.getByRole("button", { name: "确认并开始" })).toBeEnabled();
  } finally {
    mounted.unmount();
  }
});

it("历史逻辑任务恢复字段确认、批准和成果地图，不依赖已移除的启动入口", async () => {
  workflow.updatedAt = "2026-11-05T00:00:00Z";
  intent.questions = [];
  syncIntent();
  runs = [chatRun()];
  const mounted = show();
  const fields = await screen.findByRole("region", { name: "确认字段含义" });
  fireEvent.click(within(fields).getByRole("button", { name: "确认并开始" }));
  await waitFor(() =>
    expect(agentApi.confirmWorkflow).toHaveBeenCalledWith(
      workflow.id,
      expect.any(String),
      expect.objectContaining({
        executeAfterMapping: true,
        fieldMapping: expect.any(Object),
      }),
    ),
  );
  expect(
    screen.queryByRole("button", { name: "确认执行" }),
  ).not.toBeInTheDocument();
  const review = reviewWorkflow().modificationReview!;
  workflow = {
    ...workflow,
    status: "waiting_approval",
    planHash: "suggestions-v1",
    updatedAt: "2026-11-05T00:00:01Z",
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
  expect(agentApi.workflow).toHaveBeenCalledWith(workflow.id, {
    signal: expect.any(AbortSignal),
    view: "inspection",
    part: "suggestions",
  });
  expect(screen.getByRole("tab", { name: "过程与依据" })).toBeVisible();
  const group = screen
    .getByText(/岩性 \/ .* \/ 改代号/, { selector: "summary" })
    .closest("details")!;
  fireEvent.click(group.querySelector("summary")!);
  const first = await screen.findByText("岩性 / 填补内部漏填");
  const object = first.closest("details")!;
  fireEvent.click(object.querySelector("summary")!);
  // Model suggestions start selected; the user only approves.
  expect(within(object).getByRole("checkbox")).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "批准所选操作并继续" }));
  await waitFor(() =>
    expect(agentApi.confirmWorkflow).toHaveBeenCalledWith(
      workflow.id,
      "suggestions-v1",
      expect.objectContaining({
        selectedSuggestionIds: ["suggest-gap", "suggest-age"],
      }),
    ),
  );
  workflow = {
    ...workflow,
    status: "succeeded",
    planHash: "done",
    updatedAt: "2026-11-05T00:00:02Z",
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
    name: "查看前后对比",
  });
  expect(link).toHaveAttribute(
    "href",
    `/map?geologyReview=${workflow.id}&projectTagId=1`,
  );
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener");
  expect(
    screen.getByRole("region", { name: "工作流进度卡片" }),
  ).toHaveTextContent("处理结果与待核查事项");
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
