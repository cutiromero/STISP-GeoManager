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
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentWorkflow,
  AgentWorkflowStep,
  ComputeCandidate,
} from "../api/generated/types.gen";
import WorkflowPanel from "./WorkflowPanel";
import RunComputeTasks from "./RunComputeTasks";
import { liveComputeTask } from "./computeFlow.testFixtures";
import "./agent.css";

const candidates: ComputeCandidate[] = [
  [101, "模拟前期影像", "raster"],
  [102, "模拟后期影像", "raster"],
  [103, "模拟有效像元掩膜", "raster"],
  [104, "模拟调查分区", "vector"],
  [105, "模拟生态背景初始版", "table"],
  [106, "模拟生态背景补充证据版", "table"],
].map(([id, name, kind]) => ({
  id: Number(id),
  name: String(name),
  kind: String(kind),
  projectTagId: 2,
  bands: kind === "raster" ? 2 : 0,
  fields: [],
  crs: "EPSG:32645",
  geometryTypes: [],
  sizeBytes: 100,
}));

function savedWorkflow(extra: Partial<AgentWorkflow> = {}): AgentWorkflow {
  return {
    id: "demo-workflow",
    projectId: 2,
    workflowType: "ecology_investigation",
    goal: "调查植被变化线索",
    model: "mock",
    status: "succeeded",
    detail: "完成分区调查排序",
    currentStep: "done",
    iteration: 3,
    operatorSteps: 4,
    maxIterations: 8,
    maxOperatorSteps: 12,
    executeOperators: true,
    resourceIds: [101, 102, 103, 104, 105],
    algorithmVersionId: null,
    parameters: {
      red: 1,
      nir: 2,
      early_date: "2024-07-01",
      late_date: "2025-07-01",
      min_coverage: 0.65,
    },
    resultIds: [],
    evidence: [],
    runtime: "durable",
    steps: [],
    createdAt: "2026-10-10",
    updatedAt: "2026-10-10",
    plan: {
      inputs: {
        early_image: 101,
        late_image: 102,
        valid_mask: 103,
        zones: 104,
        context: 105,
      },
      inputNames: { early_image: "模拟前期影像", late_image: "模拟后期影像" },
      knowledgeSelection: { mode: "manual", domains: ["arid_ecology"] },
      reviewOutputs: [],
      stages: [
        {
          outputs: [
            { kind: "raster", resourceId: 201 },
            { kind: "vector", resourceId: 202 },
          ],
        },
      ],
    },
    planHash: "verified-plan",
    importResults: true,
    resultResourceIds: [201, 202],
    ...extra,
  };
}

function decisionStep(): AgentWorkflowStep {
  return {
    id: 1,
    sequence: 1,
    kind: "demo_decision",
    status: "succeeded",
    message: "已形成当前判断",
    action: {},
    inputRefs: {},
    outputRefs: {},
    metrics: {},
    computeTaskId: "",
    errorCode: "",
    startedAt: "",
    finishedAt: "",
    decision: {
      problem: "哪些区域值得优先调查？",
      findings: ["西区平均变化为 -0.21，覆盖率 0.93"],
      judgement: "初步优先调查西区",
      uncertainties: ["需核对灌溉记录"],
      nextAction: "finish",
      algorithmReason: "共同有效像元足够，使用分区统计比较",
      resultSummary: "统计表已读取，共 4 个调查分区",
      evidenceRefs: [
        {
          kind: "knowledge",
          id: "hidden-knowledge-id",
          title: "同季节植被比较",
          revision: 3,
        },
        { kind: "output", id: "hidden-output-id", title: "statistics" },
      ],
      modelMode: "mock",
      modelName: "Mock",
    },
  };
}

function showWorkflow() {
  return render(
    <AntApp>
      <MemoryRouter>
        <WorkflowPanel model="mock" resourceIds={[]} embedded />
      </MemoryRouter>
    </AntApp>,
  );
}
function Location() {
  const location = useLocation();
  return (
    <output aria-label="当前位置">
      {location.pathname}
      {location.search}
    </output>
  );
}
async function select(label: string, option: string) {
  fireEvent.mouseDown(screen.getByRole("combobox", { name: label }));
  fireEvent.click(
    await screen.findByText(option, {
      selector: ".ant-select-item-option-content",
    }),
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(computeApi, "algorithms").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(computeApi, "inputs").mockResolvedValue({
    items: candidates,
    total: candidates.length,
  });
  vi.spyOn(agentApi, "workflows").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "resources").mockResolvedValue({
    items: candidates.map((entry) => ({
      id: entry.id,
      name: entry.name,
      dataType: entry.kind,
      description: "本条为可复现模拟资料，来源说明保留在资源中。",
    })),
  });
  vi.spyOn(agentApi, "bootstrap").mockResolvedValue({
    canChat: true,
    canAgent: true,
    canManage: false,
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
        supportsThinking: false,
        supportsVision: false,
        status: "online",
        checkedAt: "",
      },
    ],
    knowledgeDomains: [
      {
        id: "arid_ecology",
        label: "干旱区生态",
        count: 8,
        description: "生态调查知识",
      },
    ],
  });
});

it("binds ecological input roles, lets the user choose the evidence version, and submits actual parameters", async () => {
  const create = vi
    .spyOn(agentApi, "createWorkflow")
    .mockResolvedValue(savedWorkflow({ status: "queued" }));
  showWorkflow();
  await select("研究场景", "干旱区生态 · 变化与调查优先区");
  fireEvent.click(screen.getByRole("button", { name: "按名称匹配资料" }));
  expect(screen.getByRole("button", { name: "生成执行计划" })).toBeDisabled();
  await select("生态背景与观测记录", "模拟生态背景补充证据版");
  fireEvent.change(screen.getByLabelText("前期日期"), {
    target: { value: "2024-07-01" },
  });
  fireEvent.change(screen.getByLabelText("后期日期"), {
    target: { value: "2025-07-01" },
  });
  expect(
    within(screen.getByLabelText("已选资料说明")).getAllByText(
      "本条为可复现模拟资料，来源说明保留在资源中。",
    ),
  ).toHaveLength(5);
  fireEvent.click(screen.getByRole("button", { name: "生成执行计划" }));
  await waitFor(() => expect(create).toHaveBeenCalledOnce());
  expect(create).toHaveBeenCalledWith(
    expect.objectContaining({
      workflowType: "ecology_investigation",
      model: "mock",
      inputs: {
        early_image: 101,
        late_image: 102,
        valid_mask: 103,
        zones: 104,
        context: 106,
      },
      parameters: {
        red: 1,
        nir: 2,
        decline_threshold: -0.15,
        min_coverage: 0.65,
        early_date: "2024-07-01",
        late_date: "2025-07-01",
      },
      executeOperators: false,
      knowledgeSelection: { mode: "auto", domains: [] },
      importResults: true,
    }),
  );
});

it("restores a saved multi-stage judgement and scoped knowledge without creating or rerunning work", async () => {
  vi.spyOn(agentApi, "workflows").mockResolvedValue({
    items: [savedWorkflow({ steps: [decisionStep()] })],
  });
  const create = vi.spyOn(agentApi, "createWorkflow");
  const confirm = vi.spyOn(agentApi, "confirmWorkflow");
  showWorkflow();
  await screen.findByText("初步优先调查西区");
  expect(
    screen.getByText("西区平均变化为 -0.21，覆盖率 0.93"),
  ).toBeInTheDocument();
  expect(screen.getByText("同季节植被比较 · 版本 3")).toBeInTheDocument();
  expect(screen.getByText("查看分析结果与后续建议")).toBeInTheDocument();
  expect(screen.getByText("统计表")).toBeInTheDocument();
  expect(screen.queryByText("finish")).not.toBeInTheDocument();
  expect(screen.queryByText("hidden-output-id")).not.toBeInTheDocument();
  expect(screen.getAllByText("模拟模型").length).toBeGreaterThan(0);
  expect(screen.queryByText("hidden-knowledge-id")).not.toBeInTheDocument();
  expect(screen.getByLabelText("前期日期")).toHaveValue("2024-07-01");
  expect(
    screen.getByRole("combobox", { name: "工作流知识分区" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "在地理工作台对比成果图层" }),
  ).toHaveAttribute("href", "/map?resources=201,202&projectTagId=2");
  expect(create).not.toHaveBeenCalled();
  expect(confirm).not.toHaveBeenCalled();
});

it("keeps quality review visible and resumes only when the user approves the candidate results", async () => {
  const saved = savedWorkflow({
    status: "waiting_approval",
    detail: "几何修复影响较大，请核对候选结果",
    plan: {
      ...savedWorkflow().plan,
      reviewOutputs: [21],
      reviewReason: "needs_review",
    },
    steps: [decisionStep()],
  });
  vi.spyOn(agentApi, "workflows").mockResolvedValue({ items: [saved] });
  const confirm = vi
    .spyOn(agentApi, "confirmWorkflow")
    .mockResolvedValue({ ...saved, status: "running" });
  showWorkflow();
  await screen.findByText("几何修复影响较大，请核对候选结果");
  expect(confirm).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "审核并继续" }));
  await waitFor(() =>
    expect(confirm).toHaveBeenCalledWith("demo-workflow", "verified-plan"),
  );
});

it("uses a real model label for real decisions and clears previous evidence when access is revoked", async () => {
  const step = decisionStep();
  step.decision = {
    ...step.decision!,
    modelMode: "real",
    modelName: "Qwen 分析模型",
  };
  const first = savedWorkflow({ id: "first", steps: [step] });
  vi.spyOn(agentApi, "workflows").mockResolvedValue({
    items: [first, savedWorkflow({ id: "other", goal: "另一次调查" })],
  });
  vi.spyOn(agentApi, "workflow").mockRejectedValue(
    Object.assign(new Error("项目权限已撤销"), { status: 403 }),
  );
  showWorkflow();
  await screen.findByText("Qwen 分析模型");
  await select("历史工作流", "另一次调查");
  await screen.findByText("项目权限已撤销");
  expect(screen.queryByText("初步优先调查西区")).not.toBeInTheDocument();
  expect(screen.queryByText("同季节植被比较 · 版本 3")).not.toBeInTheDocument();
});

it("deduplicates workflow task IDs and opens an imported vector through the actual map URL", async () => {
  const task = liveComputeTask("succeeded");
  task.projectTagId = 2;
  task.outputs[0] = {
    ...task.outputs[0]!,
    kind: "vector",
    importStatus: "ready",
    resourceId: 203,
    resourceName: "调查优先区",
    resourceLocation: "生态项目 / 数据资源 / 调查优先区",
    mapUrl: "/map?resourceId=203&projectTagId=2",
  };
  const load = vi.spyOn(computeApi, "task").mockResolvedValue(task);
  const runPoll = vi.spyOn(agentApi, "computeTasks");
  render(
    <AntApp>
      <MemoryRouter>
        <RunComputeTasks taskIds={[task.id, task.id]} refreshKey="saved" />
        <Location />
      </MemoryRouter>
    </AntApp>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "在地理工作台查看" }),
  );
  expect(load).toHaveBeenCalledOnce();
  expect(runPoll).not.toHaveBeenCalled();
  expect(screen.getByRole("status", { name: "当前位置" })).toHaveTextContent(
    "/map?resourceId=203&projectTagId=2",
  );
  expect(screen.queryByText(task.id)).not.toBeInTheDocument();
});

it("does not route an unimported vector through the raster-only temporary preview", async () => {
  const task = liveComputeTask("succeeded");
  task.outputs[0] = { ...task.outputs[0]!, kind: "vector" };
  vi.spyOn(computeApi, "task").mockResolvedValue(task);
  render(
    <AntApp>
      <MemoryRouter>
        <RunComputeTasks taskIds={[task.id]} refreshKey="saved" />
      </MemoryRouter>
    </AntApp>,
  );
  await screen.findByText("计算完成，结果已保存。");
  expect(
    screen.queryByRole("button", { name: "在地理工作台查看" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "将结果入库" }),
  ).toBeInTheDocument();
});

it("keeps the same request key after a lost response and prevents duplicate preview clicks", async () => {
  vi.spyOn(agentApi, "workflows").mockResolvedValue({
    items: [savedWorkflow()],
  });
  const create = vi
    .spyOn(agentApi, "createWorkflow")
    .mockRejectedValueOnce(new Error("网络响应中断"))
    .mockResolvedValueOnce(savedWorkflow({ status: "waiting_approval" }));
  showWorkflow();
  await screen.findByText("成果已保存到本项目的数据资源");
  const preview = screen.getByRole("button", { name: "生成执行计划" });
  fireEvent.click(preview);
  fireEvent.click(preview);
  await screen.findByText("网络响应中断");
  expect(create).toHaveBeenCalledOnce();
  fireEvent.click(preview);
  await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
  expect(create.mock.calls[0]?.[0].idempotencyKey).toBe(
    create.mock.calls[1]?.[0].idempotencyKey,
  );
});

it("opens both the original geological map and the imported corrected layers for comparison", async () => {
  vi.spyOn(agentApi, "workflows").mockResolvedValue({
    items: [
      savedWorkflow({
        workflowType: "geology_correction",
        plan: {
          inputs: { initial_map: 301, surveys: 302, rules: 303 },
          stages: [
            {
              outputs: [
                { kind: "vector", resourceId: 304 },
                { kind: "table", resourceId: 305 },
              ],
            },
          ],
        },
        resultResourceIds: [304, 305],
      }),
    ],
  });
  showWorkflow();
  expect(
    await screen.findByRole("link", { name: "在地理工作台对比成果图层" }),
  ).toHaveAttribute("href", "/map?resources=301,304&projectTagId=2");
});

it("opens only spatial outputs and the retained change image when comparing an evidence update", async () => {
  vi.spyOn(agentApi, "workflows").mockResolvedValue({
    items: [
      savedWorkflow({
        resultResourceIds: [201, 202, 203],
        plan: {
          ...savedWorkflow().plan,
          previousChange: { resourceId: 199 },
          stages: [
            {
              outputs: [
                { kind: "raster", resourceId: 201 },
                { kind: "table", resourceId: 202 },
                { kind: "vector", resourceId: 203 },
              ],
            },
          ],
        },
      }),
    ],
  });
  showWorkflow();
  expect(
    await screen.findByRole("link", { name: "在地理工作台对比成果图层" }),
  ).toHaveAttribute("href", "/map?resources=199,201,203&projectTagId=2");
});

it("updates a completed ecological analysis by replacing only its observation evidence", async () => {
  const saved = savedWorkflow();
  vi.spyOn(agentApi, "workflows").mockResolvedValue({ items: [saved] });
  const create = vi
    .spyOn(agentApi, "createWorkflow")
    .mockResolvedValue(
      savedWorkflow({ id: "updated-analysis", status: "waiting_approval" }),
    );
  showWorkflow();
  fireEvent.click(
    await screen.findByRole("button", { name: "补充观测后更新判断" }),
  );
  expect(screen.getByRole("combobox", { name: "前期影像" })).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "后期影像" })).toBeDisabled();
  expect(
    screen.getByRole("combobox", { name: "共同有效像元掩膜" }),
  ).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "调查分区" })).toBeDisabled();
  expect(screen.getByLabelText("前期日期")).toBeDisabled();
  expect(screen.getByRole("spinbutton", { name: "红光波段" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "生成更新计划" })).toBeDisabled();
  expect(
    screen.getByRole("combobox", { name: "生态背景与观测记录" }),
  ).not.toBeDisabled();
  await select("生态背景与观测记录", "模拟生态背景补充证据版");
  fireEvent.click(screen.getByRole("button", { name: "生成更新计划" }));
  await waitFor(() => expect(create).toHaveBeenCalledOnce());
  expect(create).toHaveBeenCalledWith(
    expect.objectContaining({
      previousWorkflowId: saved.id,
      inputs: {
        ...(saved.plan.inputs as Record<string, number>),
        context: 106,
      },
      parameters: expect.objectContaining(saved.parameters),
    }),
  );
  expect(
    screen.queryByRole("button", { name: "生成更新计划" }),
  ).not.toBeInTheDocument();
});

it("restores the earlier judgement, new observation evidence and updated conclusion without rerunning", async () => {
  const updated = decisionStep();
  updated.decision = {
    ...updated.decision,
    judgement: "收获解释了西区下降，优先调查东区",
  };
  vi.spyOn(agentApi, "workflows").mockResolvedValue({
    items: [
      savedWorkflow({
        steps: [updated],
        plan: {
          ...savedWorkflow().plan,
          previousAnalysis: {
            workflowId: "hidden-previous-id",
            oldDecision: decisionStep().decision,
            oldContext: { title: "初始生态背景" },
            newContext: { title: "补充收获记录后的观测" },
            addedEvidence: [
              {
                date: "2025-06-25",
                event_type: "harvest",
                land_use: "cropland",
                source: "调查记录与农户访谈",
                confidence: "0.9",
                evidence_id: "hidden-evidence-id",
              },
            ],
          },
        },
      }),
    ],
  });
  const create = vi.spyOn(agentApi, "createWorkflow");
  showWorkflow();
  const comparison = await screen.findByLabelText("补充观测后的判断更新");
  expect(within(comparison).getByText("初步优先调查西区")).toBeInTheDocument();
  expect(
    within(comparison).getAllByText("统计表已读取，共 4 个调查分区"),
  ).toHaveLength(2);
  expect(
    within(comparison).getByText("收获解释了西区下降，优先调查东区"),
  ).toBeInTheDocument();
  expect(within(comparison).getByText("收获")).toBeInTheDocument();
  expect(within(comparison).getByText("农田")).toBeInTheDocument();
  expect(within(comparison).getByText("90%")).toBeInTheDocument();
  expect(
    within(comparison).getByText("调查记录与农户访谈"),
  ).toBeInTheDocument();
  expect(screen.queryByText("hidden-previous-id")).not.toBeInTheDocument();
  expect(screen.queryByText("hidden-evidence-id")).not.toBeInTheDocument();
  expect(create).not.toHaveBeenCalled();
});

it("expands saved knowledge statements, conditions and original citations using only safe links", async () => {
  vi.spyOn(agentApi, "workflows").mockResolvedValue({
    items: [
      savedWorkflow({
        evidence: [
          {
            id: 1,
            title: "有效像元比较依据",
            revision: 2,
            statement: "仅比较两期共同有效的像元。",
            conditions: ["同季节、同网格"],
            sources: [
              {
                title: "USGS质量说明",
                url: "https://www.usgs.gov/landsat-missions/quality",
                locator: "QA_PIXEL第2节",
                excerpt: "Cloud and cloud shadow flags",
              },
              {
                title: "本地调查说明",
                url: "javascript:alert(1)",
                locator: "观测表第3行",
              },
            ],
          },
        ],
      }),
    ],
  });
  showWorkflow();
  fireEvent.click(await screen.findByText("有效像元比较依据 · 版本 2"));
  const reference = await screen.findByLabelText("有效像元比较依据原文与出处");
  expect(
    within(reference).getByText("仅比较两期共同有效的像元。"),
  ).toBeInTheDocument();
  expect(within(reference).getByText("同季节、同网格")).toBeInTheDocument();
  expect(
    within(reference).getByText("原文位置：QA_PIXEL第2节"),
  ).toBeInTheDocument();
  expect(
    within(reference).getByText("Cloud and cloud shadow flags"),
  ).toBeInTheDocument();
  expect(
    within(reference).getByRole("link", { name: "USGS质量说明" }),
  ).toHaveAttribute("href", "https://www.usgs.gov/landsat-missions/quality");
  expect(
    within(reference).queryByRole("link", { name: "本地调查说明" }),
  ).not.toBeInTheDocument();
});
