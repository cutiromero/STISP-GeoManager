import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import type {
  AgentBootstrap,
  AgentWorkflowUpload,
} from "../api/generated/types.gen";
import { agentApi } from "../api/agent";
import { businessFlowsApi } from "../api/businessFlows";
import AgentPage from "../agent/AgentPage";
import { genericRoles } from "../agent/GenericWorkflowUploads";
import BusinessFlowLaunch from "./BusinessFlowLaunch";
import {
  geologyDetail,
  businessFlowRun,
  directInputPlan,
} from "./businessFlow.testFixtures";
import platformStyles from "../styles.css?inline";

vi.mock("../components/WorkspaceHeader", () => ({
  default: () => <header>STISP</header>,
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { id: 99, permissions: {} } }),
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({
    current: "3",
    projects: [{ id: 3, name: "核地院逻辑推理", code: "02" }],
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

const bootstrap: AgentBootstrap = {
  canAgent: true,
  canChat: true,
  canManage: false,
  workerOnline: true,
  thinkingEnabled: false,
  internetEnabled: false,
  allowAttachments: false,
  capabilities: [],
  defaultAgentModel: "qwen",
  defaultChatModel: "qwen",
  models: [
    {
      alias: "qwen",
      name: "Qwen3.8-27B",
      status: "online",
      allowAgent: true,
      supportsThinking: false,
      supportsVision: false,
      contextWindowTokens: 32768,
      checkedAt: "",
    },
  ],
};
const roleKeys = [
  "lithology",
  "faults",
  "calcite",
  "dolomite",
  "hematite",
  "hydromica",
  "chlorite",
] as const;
const names = [
  "岩性识别",
  "构造识别",
  "方解石化",
  "白云石化",
  "赤铁矿化",
  "水云母化",
  "绿泥石化",
];
const items: AgentWorkflowUpload[] = roleKeys.map((key, index) => ({
  id: `source-${index}`,
  batchId: "a".repeat(32),
  resourceId: 800 + index,
  source: "catalog",
  name: names[index]!,
  fileName: `五龙沟-海德乌拉_${names[index]}`,
  dataType: index < 2 ? "vector" : "raster",
  sizeBytes: 512,
  roleHint: key,
  workflowId: null,
  createdAt: "",
  profile: {
    kind: index < 2 ? "vector" : "raster",
    crs: "EPSG:4326",
    geometryTypes:
      index === 0 ? ["Polygon"] : index === 1 ? ["LineString"] : [],
    featureCount: 12,
    bounds: [97, 35, 98, 36],
    bandCount: index < 2 ? null : 1,
    width: index < 2 ? null : 100,
    height: index < 2 ? null : 100,
    warnings: [],
    fields: [
      { name: "class", type: "text", samples: ["岩性"], distinctCount: 1 },
    ],
  },
}));
const spec = {
  ...geologyDetail.version!.definition,
  inputRequirements: genericRoles.map((role) => ({
    key: role.key,
    label: role.label,
    description: "原始资料只读",
    dataTypes: [role.kind],
    required: role.key === "lithology",
    requiredFields: [],
  })),
  nodes: geologyDetail.version!.definition.nodes.map((node) => ({
    ...node,
    dataRoles: node.dataRoles.map((role) =>
      role === "structure"
        ? "faults"
        : role === "alteration"
          ? "calcite"
          : role,
    ),
  })),
};
const version = { ...geologyDetail.version!, definition: spec };
const detail = { ...geologyDetail, version, versions: [version] };
const intent = {
  definitionId: detail.flow.id,
  versionId: version.id,
  title: "逻辑推理",
  goal: "综合岩性、构造和蚀变资料开展逻辑推理。",
};
const roles = Object.fromEntries(
  items.map((item) => [item.roleHint!, item.resourceId]),
);
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(businessFlowsApi, "prepareInputs").mockImplementation(
    async (_id, request) => directInputPlan(request),
  );
  sessionStorage.clear();
  localStorage.clear();
  vi.spyOn(agentApi, "conversations").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "resources").mockResolvedValue({ items: [] });
  vi.spyOn(businessFlowsApi, "detail").mockResolvedValue(detail);
  vi.spyOn(agentApi, "restoreLogicConfiguration").mockResolvedValue({
    configuration: {
      resourceIds: items.map((item) => item.resourceId),
      roles,
      fieldMapping: {},
      prompt: "旧要求不覆盖本次目标",
      reasoningEffort: "medium",
    },
    items: structuredClone(items),
    unavailableResourceIds: [],
  });
});
afterEach(async () => {
  bootstrap.thinkingEnabled = false;
  bootstrap.models[0]!.supportsThinking = false;
  await page.viewport(1600, 900);
});
function showWorkspace() {
  return render(
    <>
      <style>{platformStyles}</style>
      <App>
        <MemoryRouter
          initialEntries={[
            {
              pathname: "/agent/workbench",
              state: { businessFlowLaunch: intent },
            },
          ]}
        >
          <AgentPage />
        </MemoryRouter>
      </App>
    </>,
  );
}

it.each([
  [1440, 1000],
  [390, 844],
])(
  "presents one preparation workspace with visible actions at %sx%s",
  async (width, height) => {
    await page.viewport(width, height);
    showWorkspace();
    await screen.findByText("五龙沟-海德乌拉_岩性识别");
    const start = await screen.findByRole("button", {
      name: "开始业务流",
      exact: true,
    });
    await waitFor(() => expect(start).toBeEnabled());
    const panel = screen.getByRole("region", { name: "业务流启动准备" });
    expect(panel.querySelectorAll(".flow-materials-row")).toHaveLength(7);
    expect(panel.querySelectorAll(".agent-demo-form")).toHaveLength(0);
    expect(
      screen.queryByRole("button", { name: "发送", exact: true }),
    ).not.toBeInTheDocument();
    expect(document.querySelector(".agent-messages")).not.toBeVisible();
    expect(screen.getByRole("textbox", { name: "本次任务目标" })).toHaveValue(
      intent.goal,
    );
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width + 1);
    const checkAction = () => {
      const bounds = start.getBoundingClientRect();
      expect(bounds.top).toBeGreaterThanOrEqual(0);
      expect(bounds.bottom).toBeLessThanOrEqual(height);
      expect(bounds.right).toBeLessThanOrEqual(width);
    };
    checkAction();
    const scroller = panel.querySelector<HTMLElement>(".flow-launch-scroll")!;
    await act(async () => {
      scroller.scrollTop = scroller.scrollHeight;
    });
    checkAction();
    scroller.scrollTop = 0;
    await page.screenshot({
      path: `../../test-results/business-flow-preparation-${width}.png`,
    });
    expect(agentApi.restoreLogicConfiguration).toHaveBeenCalledOnce();
    expect(agentApi.resources).not.toHaveBeenCalled();
  },
);

it.each(["restore", "suggest"])(
  "新版蚀变集合通过 %s 保留多份历史矿物资料并启动",
  async (mode) => {
    const newSpec = structuredClone(spec);
    const currentRoles = [
      "lithology",
      "faults",
      "coverage",
      "units",
      "alterations",
    ];
    newSpec.inputRequirements = newSpec.inputRequirements
      .filter((input) => currentRoles.includes(input.key))
      .map((input) =>
        input.key === "alterations"
          ? { ...input, multiple: true, semanticType: "class_mask_stack_v1" }
          : input,
      );
    newSpec.nodes = newSpec.nodes.map((node) => ({
      ...node,
      dataRoles: node.dataRoles.filter((key) => currentRoles.includes(key)),
    }));
    vi.mocked(businessFlowsApi.detail).mockResolvedValue({
      ...detail,
      version: { ...version, definition: newSpec },
      versions: [{ ...version, definition: newSpec }],
    });
    if (mode === "suggest")
      vi.mocked(agentApi.restoreLogicConfiguration).mockResolvedValue({
        configuration: null,
        items: structuredClone(items),
        unavailableResourceIds: [],
      });
    vi.spyOn(agentApi, "recognizeWorkflowRoles").mockResolvedValue({
      source: "model",
      questions: [],
      items: items.map((item) => ({
        uploadId: item.id,
        resourceId: item.resourceId,
        role: item.roleHint!,
        reason: "依据实际分类资料识别用途",
      })),
    });
    const start = vi
      .spyOn(businessFlowsApi, "start")
      .mockResolvedValue(businessFlowRun());
    render(
      <App>
        <BusinessFlowLaunch
          launch={intent}
          model="qwen"
          onStarted={vi.fn()}
          onCancel={vi.fn()}
        />
      </App>,
    );
    await screen.findByText(items[0]!.fileName);
    if (mode === "suggest")
      fireEvent.click(screen.getByRole("button", { name: "AI 识别资料用途" }));
    const action = screen.getByRole("button", {
      name: "开始业务流",
      exact: true,
    });
    await waitFor(() => expect(action).toBeEnabled());
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: items[2]!.fileName + "的资料角色" }),
    );
    await waitFor(() =>
      expect(
        screen.getByText("蚀变识别资料（不限矿物种类，可多份）", {
          selector: ".ant-select-item-option-content",
        }),
      ).toBeVisible(),
    );
    expect(
      screen.queryByText("方解石化识别结果", { exact: true }),
    ).not.toBeInTheDocument();
    fireEvent.keyDown(
      screen.getByRole("combobox", { name: items[2]!.fileName + "的资料角色" }),
      { key: "Escape" },
    );
    fireEvent.click(action);
    await waitFor(() => expect(start).toHaveBeenCalledOnce());
    expect(start.mock.calls[0]![1].inputs).toEqual({
      lithology: items[0]!.resourceId,
      faults: items[1]!.resourceId,
      ...Object.fromEntries(
        items
          .slice(2)
          .map((item) => [`alterations:${item.resourceId}`, item.resourceId]),
      ),
    });
  },
);

it("lets a fresh source receive one real role suggestion before starting the same flow", async () => {
  bootstrap.thinkingEnabled = true;
  bootstrap.models[0]!.supportsThinking = true;
  vi.mocked(agentApi.restoreLogicConfiguration).mockResolvedValue({
    configuration: null,
    items: [structuredClone(items[0]!)],
    unavailableResourceIds: [],
  });
  const recognize = vi
    .spyOn(agentApi, "recognizeWorkflowRoles")
    .mockResolvedValue({
      source: "model",
      questions: [],
      items: [
        {
          uploadId: items[0]!.id,
          resourceId: items[0]!.resourceId,
          role: "lithology",
          reason: "实际图层包含面要素及岩性字段",
        },
      ],
    });
  const start = vi.spyOn(businessFlowsApi, "start").mockResolvedValue(
    businessFlowRun({
      flowId: detail.flow.id,
      versionId: version.id,
      status: "queued",
    }),
  );
  render(
    <>
      <style>{platformStyles}</style>
      <App>
        <BusinessFlowLaunch
          launch={intent}
          model="qwen"
          onStarted={vi.fn()}
          onCancel={vi.fn()}
        />
      </App>
    </>,
  );
  const button = await screen.findByRole("button", {
    name: "开始业务流",
    exact: true,
  });
  expect(button).toBeDisabled();
  fireEvent.click(
    await screen.findByRole("button", { name: "AI 识别资料用途" }),
  );
  await waitFor(() => expect(button).toBeEnabled());
  expect(recognize).toHaveBeenCalledOnce();
  expect(recognize).toHaveBeenCalledWith(expect.any(String), "qwen", "medium");
  fireEvent.click(button);
  await waitFor(() => expect(start).toHaveBeenCalledOnce());
  expect(start.mock.calls[0]![1]).toMatchObject({
    versionId: version.id,
    inputs: { lithology: items[0]!.resourceId },
    model: "qwen",
  });
  expect(start.mock.calls[0]![1].parameters?.uploadBatchId).toBeTruthy();
});

it("keeps selections across remote searches and does not reread the restored sources", async () => {
  const catalog = vi
    .spyOn(agentApi, "workflowCatalogResources")
    .mockImplementation(async (query) => ({
      items: [
        {
          id: query ? 902 : 901,
          name: query ? "另一资料" : "新增资料",
          dataType: "vector",
          directoryId: null,
          directoryName: "地质资料",
          createdAt: "2026-11-10",
        },
      ],
      total: 1,
      page: 1,
      pageSize: 20,
      directories: [],
    }));
  const added = items.slice(0, 2).map((item, index) => ({
    ...item,
    id: `additional-${index}`,
    resourceId: 901 + index,
    fileName: index ? "另一资料" : "新增资料",
  }));
  const add = vi
    .spyOn(agentApi, "addWorkflowCatalogReferences")
    .mockResolvedValue({ items: added, errors: [] });
  showWorkspace();
  await screen.findByText("五龙沟-海德乌拉_岩性识别");
  fireEvent.click(
    screen.getByRole("button", { name: "选择系统数据", exact: true }),
  );
  fireEvent.click(await screen.findByText("新增资料", { exact: true }));
  fireEvent.change(screen.getByRole("searchbox", { name: "搜索任务资料" }), {
    target: { value: "另一" },
  });
  fireEvent.click(
    await screen.findByRole("checkbox", { name: "选择另一资料" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "加入本次任务" }));
  await waitFor(() => expect(add).toHaveBeenCalledOnce());
  expect(add.mock.calls[0]![1]).toEqual([901, 902]);
  expect(catalog).toHaveBeenCalledTimes(2);
  expect(agentApi.restoreLogicConfiguration).toHaveBeenCalledOnce();
});

it.each([
  [1461, 812, 7],
  [1461, 812, 40],
  [360, 800, 7],
  [360, 800, 40],
])(
  "新版准备页 %sx%s、%s 份资料时目标和启动操作保持可用",
  async (width, height, count) => {
    await page.viewport(width, height);
    const selected = Array.from({ length: count }, (_, index) => ({
      ...structuredClone(items[index % items.length]!),
      id: `restored-${index}`,
      resourceId: 900 + index,
      fileName: `第${index + 1}份地质调查资料及矿物识别结果`,
    }));
    vi.mocked(agentApi.restoreLogicConfiguration).mockResolvedValue({
      configuration: {
        resourceIds: selected.map((item) => item.resourceId),
        roles: Object.fromEntries(
          selected.map((item) => [item.roleHint!, item.resourceId]),
        ),
        fieldMapping: {},
        prompt: "旧要求",
        reasoningEffort: "low",
      },
      items: selected,
      unavailableResourceIds: [],
    });
    showWorkspace();
    await screen.findByText(selected[0]!.fileName);
    const panel = screen.getByRole("region", { name: "业务流启动准备" });
    expect(panel.querySelectorAll(".flow-materials-row")).toHaveLength(count);
    const goal = screen.getByRole("textbox", { name: "本次任务目标" });
    expect(goal).toHaveValue(intent.goal);
    expect(goal).toBeVisible();
    const start = screen.getByRole("button", {
      name: "开始业务流",
      exact: true,
    });
    await waitFor(() => expect(start).toBeEnabled());
    const check = () => {
      const bounds = start.getBoundingClientRect();
      expect(bounds.top).toBeGreaterThanOrEqual(0);
      expect(bounds.bottom).toBeLessThanOrEqual(height);
      expect(bounds.right).toBeLessThanOrEqual(width);
    };
    check();
    const scroll = panel.querySelector<HTMLElement>(".flow-launch-scroll")!;
    await act(async () => {
      scroll.scrollTop = scroll.scrollHeight;
    });
    check();
    expect(agentApi.restoreLogicConfiguration).toHaveBeenCalledOnce();
  },
);

it("复用来源通过业务流启动并冻结版本和本次目标", async () => {
  const start = vi
    .spyOn(businessFlowsApi, "start")
    .mockResolvedValue(businessFlowRun());
  const submit = vi.spyOn(agentApi, "submit");
  render(
    <App>
      <BusinessFlowLaunch
        launch={intent}
        model="qwen"
        onStarted={vi.fn()}
        onCancel={vi.fn()}
      />
    </App>,
  );
  await screen.findByText(items[0]!.fileName);
  const action = screen.getByRole("button", {
    name: "开始业务流",
    exact: true,
  });
  await waitFor(() => expect(action).toBeEnabled());
  fireEvent.click(action);
  await waitFor(() => expect(start).toHaveBeenCalledOnce());
  expect(start.mock.calls[0]![1]).toMatchObject({
    versionId: version.id,
    goal: intent.goal,
    inputs: roles,
    parameters: { uploadBatchId: expect.stringMatching(/^[a-f0-9]{32}$/) },
  });
  expect(submit).not.toHaveBeenCalled();
});

it("退出准备保留引用，重新打开仍可恢复，只有清空才解除引用", async () => {
  const remove = vi
    .spyOn(agentApi, "deleteWorkflowUpload")
    .mockResolvedValue(undefined);
  const view = showWorkspace();
  await screen.findByText(items[0]!.fileName);
  fireEvent.click(
    screen.getByRole("button", { name: "取消业务流准备", exact: true }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("region", { name: "业务流启动准备" }),
    ).not.toBeInTheDocument(),
  );
  expect(remove).not.toHaveBeenCalled();
  view.unmount();
  showWorkspace();
  await screen.findByText(items[0]!.fileName);
  fireEvent.click(screen.getByRole("button", { name: "清空", exact: true }));
  await waitFor(() => expect(remove).toHaveBeenCalledTimes(items.length));
  await waitFor(() =>
    expect(screen.queryByText(items[0]!.fileName)).not.toBeInTheDocument(),
  );
  expect(
    screen.getByRole("button", { name: "开始业务流", exact: true }),
  ).toBeDisabled();
});

it("ZIP 上传经业务流角色绑定后启动，不进入旧对话提交路径", async () => {
  vi.mocked(agentApi.restoreLogicConfiguration).mockResolvedValue({
    configuration: null,
    items: [],
    unavailableResourceIds: [],
  });
  const upload = {
    ...structuredClone(items[0]!),
    id: "zip-geology",
    source: "upload" as const,
  };
  vi.spyOn(agentApi, "uploadWorkflowBatch").mockResolvedValue({
    items: [upload],
    errors: [],
  });
  const start = vi
    .spyOn(businessFlowsApi, "start")
    .mockResolvedValue(businessFlowRun());
  const submit = vi.spyOn(agentApi, "submit");
  render(
    <App>
      <BusinessFlowLaunch
        launch={intent}
        model="qwen"
        onStarted={vi.fn()}
        onCancel={vi.fn()}
      />
    </App>,
  );
  await screen.findByRole("button", { name: "上传文件/ZIP", exact: true });
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
  fireEvent.change(input, {
    target: {
      files: [
        new File(["fixture"], "地质资料.zip", { type: "application/zip" }),
      ],
    },
  });
  await screen.findByText(upload.fileName);
  const role = screen.getByRole("combobox", {
    name: upload.fileName + "的资料角色",
  });
  fireEvent.mouseDown(role);
  fireEvent.click(await screen.findByText("岩性图（必需）", { exact: true }));
  const action = screen.getByRole("button", {
    name: "开始业务流",
    exact: true,
  });
  await waitFor(() => expect(action).toBeEnabled());
  fireEvent.click(action);
  await waitFor(() => expect(start).toHaveBeenCalledOnce());
  expect(start.mock.calls[0]![1]).toMatchObject({
    versionId: version.id,
    inputs: { lithology: upload.resourceId },
  });
  expect(start.mock.calls[0]![1].parameters?.uploadBatchId).toMatch(
    /^[a-f0-9]{32}$/,
  );
  expect(submit).not.toHaveBeenCalled();
});
