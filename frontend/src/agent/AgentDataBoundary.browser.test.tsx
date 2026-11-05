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
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentAlgorithmOption,
  AgentResource,
  ComputeAlgorithm,
  ComputeCandidate,
} from "../api/generated/types.gen";
import { resetProjectSession } from "../projects/session";
import { computeIntent, computeVersion } from "./computeFlow.testFixtures";
import { geologyRequiredFields } from "./geologyWorkflowInputs";
import GenericWorkflowUploads from "./GenericWorkflowUploads";
import DemoWorkflowForm from "./DemoWorkflowForm";
import WorkflowPanel from "./WorkflowPanel";

const business: ComputeCandidate = {
  ...computeIntent.inputCandidates[0]!,
  name: "demo Test 演示测试业务表",
  kind: "table",
  fields: ["business_field"],
  bands: 0,
};
const internal = { ...business, id: 11, name: "冻结规则工作副本" };
const version = {
  ...computeVersion,
  manifest: {
    ...computeVersion.manifest,
    agent: { enabled: true },
    inputs: [
      {
        key: "table",
        label: "输入表格",
        kind: "table" as const,
        required: true,
      },
    ],
    parameters: [
      {
        key: "field",
        label: "业务字段",
        type: "field" as const,
        input: "table",
        required: true,
      },
    ],
  },
};
const algorithm: ComputeAlgorithm = {
  id: 1,
  projectTagId: 1,
  identifier: "business-table",
  name: "业务统计",
  description: "",
  category: "",
  author: "平台",
  enabled: true,
  canManage: false,
  versions: [
    version,
    { ...version, id: 5, version: "draft", status: "draft" },
    {
      ...version,
      id: 6,
      version: "agent-disabled",
      manifest: { ...version.manifest, agent: { enabled: false } },
    },
    { ...version, id: 7, version: "archived", status: "archived" },
    { ...version, id: 8, version: "not-authorized" },
    {
      ...version,
      id: 10,
      version: "legacy-authorized",
      manifest: { ...version.manifest, agent: undefined },
    },
  ],
};
const options: AgentAlgorithmOption[] = [4, 5, 6, 7, 9, 10].map(
  (versionId) => ({
    versionId,
    algorithmId: 1,
    name: "业务统计",
    version: "1.0.0",
    description: "",
  }),
);
const resource = (candidate: ComputeCandidate): AgentResource => ({
  id: candidate.id,
  name: candidate.name,
  dataType: candidate.kind,
  description: "业务资料",
});

beforeEach(() => {
  vi.restoreAllMocks();
  resetProjectSession();
  vi.spyOn(agentApi, "bootstrap").mockResolvedValue({
    knowledgeDomains: [],
    algorithmOptions: options,
  } as never);
  vi.spyOn(agentApi, "resources").mockResolvedValue({
    items: [resource(business)],
  });
  vi.spyOn(agentApi, "researchDemoSummaries").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "researchDemos").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "activeWorkflow").mockResolvedValue({ item: null });
  vi.spyOn(agentApi, "workflowHistory").mockResolvedValue({
    items: [],
    total: 0,
    offset: 0,
    limit: 30,
    hasMore: false,
  });
  vi.spyOn(computeApi, "algorithms").mockResolvedValue({
    items: [
      algorithm,
      {
        ...algorithm,
        id: 2,
        name: "停用算法",
        enabled: false,
        versions: [{ ...version, id: 9 }],
      },
    ],
    total: 2,
  });
  vi.spyOn(computeApi, "inputs").mockResolvedValue({
    items: [business, internal],
    total: 2,
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  resetProjectSession();
});

function panel() {
  return render(
    <App>
      <MemoryRouter>
        <WorkflowPanel model="mock" resourceIds={[]} embedded />
      </MemoryRouter>
    </App>,
  );
}
async function openSelect(label: string) {
  const input = await screen.findByRole("combobox", { name: label });
  await waitFor(() => expect(input).toBeEnabled());
  fireEvent.mouseDown(input);
  return input;
}
async function choose(label: string, text: string) {
  await openSelect(label);
  fireEvent.click(
    await screen.findByText(text, {
      selector: ".ant-select-item-option-content",
    }),
  );
}

it("普通工作流只显示智能体白名单交集，保留业务演示名称", async () => {
  panel();
  await choose("研究场景", "通用科研计算");
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  await openSelect("指定算法");
  await waitFor(() =>
    expect(screen.getByText("业务统计 / 1.0.0")).toBeVisible(),
  );
  expect(screen.getByText("业务统计 / legacy-authorized")).toBeInTheDocument();
  for (const name of [
    "draft",
    "agent-disabled",
    "archived",
    "not-authorized",
    "停用算法",
  ])
    expect(
      screen.queryByText(new RegExp(name), {
        selector: ".ant-select-item-option-content",
      }),
    ).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("业务统计 / 1.0.0"));
  await openSelect("输入表格");
  expect(
    await screen.findByText(business.name, {
      selector: ".ant-select-item-option-content",
    }),
  ).toBeInTheDocument();
  expect(screen.queryByText(internal.name)).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByText(business.name, {
      selector: ".ant-select-item-option-content",
    }),
  );
  await openSelect("业务字段");
  expect(
    await screen.findByText("business_field", {
      selector: ".ant-select-item-option-content",
    }),
  ).toBeInTheDocument();
});

it.each(["resources", "algorithms"])(
  "%s 白名单为空时不回退通用计算目录",
  async (empty) => {
    if (empty === "resources")
      vi.mocked(agentApi.resources).mockResolvedValue({ items: [] });
    else
      vi.mocked(agentApi.bootstrap).mockResolvedValue({
        knowledgeDomains: [],
        algorithmOptions: [],
      } as never);
    panel();
    await choose("研究场景", "通用科研计算");
    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument(),
    );
    if (empty === "resources") {
      await choose("指定算法", "业务统计 / 1.0.0");
      await openSelect("输入表格");
      expect(screen.queryByText(business.name)).not.toBeInTheDocument();
      expect(screen.queryByText(internal.name)).not.toBeInTheDocument();
    } else {
      await openSelect("指定算法");
      expect(screen.queryByText("业务统计 / 1.0.0")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("combobox", { name: "输入表格" }),
      ).not.toBeInTheDocument();
    }
    expect(computeApi.inputs).toHaveBeenCalled();
    expect(computeApi.algorithms).toHaveBeenCalled();
  },
);

it("场景注册规则只用于对应规则控件，不扩大普通表格候选", async () => {
  const inputs = { initial_map: 101, coverage: 102, rules: 103 };
  const candidates = Object.entries(inputs).map(
    ([role, id]): ComputeCandidate => ({
      ...business,
      id,
      name: role === "rules" ? "场景专用注册规则" : role,
      kind: role === "rules" ? "table" : "vector",
      fields: geologyRequiredFields[role]!,
      crs: "EPSG:32646",
      geometryTypes: role === "rules" ? [] : ["Polygon"],
    }),
  );
  const scene = {
    scenario: "geology_map_review" as const,
    projectId: 1,
    projectName: "公开",
    title: "专用地质检查",
  };
  vi.mocked(agentApi.researchDemoSummaries).mockResolvedValue({
    items: [scene],
  });
  vi.mocked(agentApi.researchDemos).mockResolvedValue({
    items: [
      {
        ...scene,
        prompt: "检查",
        available: true,
        sampleNature: "demonstration_case",
        preset: { inputs, parameters: {} },
      },
    ],
  });
  vi.mocked(agentApi.resources).mockResolvedValue({
    items: [resource(business), ...candidates.slice(0, 2).map(resource)],
  });
  vi.mocked(computeApi.inputs).mockResolvedValue({
    items: [business, internal, ...candidates],
    total: 5,
  });
  panel();
  await choose("研究场景", "专用地质检查");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "预设" })).toBeEnabled(),
  );
  await openSelect("专家规则");
  expect(
    await screen.findByText("场景专用注册规则", {
      selector: ".ant-select-item-option-content",
    }),
  ).toBeInTheDocument();
  fireEvent.keyDown(screen.getByRole("combobox", { name: "专家规则" }), {
    key: "Escape",
  });
  await choose("研究场景", "通用科研计算");
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  await choose("指定算法", "业务统计 / 1.0.0");
  await openSelect("输入表格");
  expect(
    await screen.findByText(business.name, {
      selector: ".ant-select-item-option-content",
    }),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("场景专用注册规则", {
      selector: ".ant-select-item-option-content",
    }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText(internal.name)).not.toBeInTheDocument();
});

it("专用规则不进入同场景的其他表格角色", async () => {
  render(
    <App>
      <DemoWorkflowForm
        type="geology_correction"
        candidates={[business, internal]}
        resources={[resource(business)]}
        inputs={{}}
        parameters={{}}
        disabled={false}
        boundRulesId={internal.id}
        onInputsChange={vi.fn()}
        onParametersChange={vi.fn()}
      />
    </App>,
  );
  await openSelect("调查证据");
  expect(
    await screen.findByText(business.name, {
      selector: ".ant-select-item-option-content",
    }),
  ).toBeInTheDocument();
  expect(
    screen.queryByText(internal.name, {
      selector: ".ant-select-item-option-content",
    }),
  ).not.toBeInTheDocument();
  fireEvent.keyDown(screen.getByRole("combobox", { name: "调查证据" }), {
    key: "Escape",
  });
  await openSelect("结构化检查规则");
  expect(
    await screen.findByText(internal.name, {
      selector: ".ant-select-item-option-content",
    }),
  ).toBeInTheDocument();
});

it("系统资料目录保持真实空态，取消选择不加入引用也不借用历史上传", async () => {
  const add = vi.spyOn(agentApi, "addWorkflowCatalogReferences");
  vi.spyOn(agentApi, "restoreLogicConfiguration").mockResolvedValue({
    configuration: null,
    items: [
      {
        id: "restored-internal-upload",
        batchId: "b".repeat(32),
        resourceId: 11,
        source: "upload",
        name: internal.name,
        fileName: internal.name + ".csv",
        dataType: "table",
        sizeBytes: 20,
        roleHint: "units",
        workflowId: null,
        createdAt: "2026-11-06",
        profile: {
          kind: "table",
          crs: null,
          geometryTypes: [],
          featureCount: 1,
          bandCount: null,
          width: null,
          height: null,
          bounds: null,
          fields: [],
          warnings: [],
        },
      },
    ],
    unavailableResourceIds: [],
  });
  const catalog = vi
    .spyOn(agentApi, "workflowCatalogResources")
    .mockImplementation(async (_query, _options, page = 1, directoryId) => ({
      total: directoryId === 7 ? 0 : 1,
      page,
      pageSize: 20,
      directories: [
        { id: 4, name: "业务演示目录" },
        { id: 7, name: "筛选后空目录" },
      ],
      items:
        directoryId === 7
          ? []
          : [
              {
                id: 10,
                name: business.name,
                dataType: "table",
                description: "业务表",
                directoryId: 4,
                directoryName: "业务演示目录",
                createdAt: "2026-11-06",
                updatedAt: "2026-11-06",
              },
            ],
    }));
  render(
    <App>
      <GenericWorkflowUploads
        batchId={"b".repeat(32)}
        model="mock"
        inputs={{}}
        onInputsChange={vi.fn()}
        uploadOnly
      />
    </App>,
  );
  const button = screen.getByRole("button", { name: "选择系统数据" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  const dialog = await screen.findByRole("dialog");
  await waitFor(() =>
    expect(within(dialog).getByText(/最近更新优先，共 1 份/)).toBeVisible(),
  );
  await openSelect("选择系统数据资源");
  const selected = await screen.findByText(
    new RegExp(business.name + "（表格"),
  );
  fireEvent.click(selected);
  await waitFor(() =>
    expect(
      within(dialog).getByRole("button", { name: "加入本次任务" }),
    ).toBeEnabled(),
  );
  fireEvent.click(within(dialog).getByRole("button", { name: /取消|Cancel/ }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(add).not.toHaveBeenCalled();
  fireEvent.click(button);
  await screen.findByRole("dialog");
  await choose("按数据目录筛选", "筛选后空目录");
  await waitFor(() =>
    expect(catalog).toHaveBeenLastCalledWith("", expect.anything(), 1, 7),
  );
  await waitFor(() =>
    expect(screen.getByText(/最近更新优先，共 0 份/)).toBeVisible(),
  );
  await openSelect("选择系统数据资源");
  expect(
    screen.queryByText(new RegExp(business.name + "（表格")),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByText(internal.name, {
      selector: ".ant-select-item-option-content",
    }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(internal.name + ".csv")).toBeVisible();
  expect(agentApi.resources).not.toHaveBeenCalled();
  expect(computeApi.inputs).not.toHaveBeenCalled();
  expect(add).not.toHaveBeenCalled();
});
