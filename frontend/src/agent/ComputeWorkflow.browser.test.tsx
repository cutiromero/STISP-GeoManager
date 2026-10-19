import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentWorkflow,
  ComputeTask,
  ComputeVersion,
} from "../api/generated/types.gen";
import RunComputeTasks from "./RunComputeTasks";
import WorkflowPanel from "./WorkflowPanel";
import { workflowReport } from "./workflowReport.testFixtures";

const version: ComputeVersion = {
  id: 3,
  version: "1.0",
  status: "published",
  checksum: "abc",
  runtimeDigest: "abc",
  validated: true,
  createdAt: "2026-09-29",
  manifest: {
    schemaVersion: 1,
    identifier: "ndvi",
    name: "NDVI",
    version: "1.0",
    description: "NDVI",
    author: "测试",
    runtime: "python-geospatial-v1",
    timeoutSeconds: 60,
    deterministic: true,
    inputs: [],
    parameters: [],
    outputs: [],
  },
};
const task: ComputeTask = {
  id: "8f0ff08a-780a-4b0b-aeb4-b6fba8f3de00",
  name: "NDVI任务",
  projectTagId: 1,
  ownerName: "研究员",
  algorithmName: "NDVI",
  version,
  status: "queued",
  stage: "正在排队",
  progress: 0,
  error: "",
  parameters: {},
  inputs: [],
  outputs: [],
  createdAt: "2026-09-29",
  startedAt: null,
  finishedAt: null,
  trial: false,
  unread: false,
  retryOf: null,
  attemptCount: 0,
};
const workflow: AgentWorkflow = {
  id: "wf-1",
  projectId: 1,
  workflowType: "research_processing",
  goal: "计算NDVI",
  model: "mock",
  status: "waiting_approval",
  detail: "计划已校验",
  currentStep: "review_plan",
  iteration: 0,
  operatorSteps: 0,
  maxIterations: 5,
  maxOperatorSteps: 8,
  executeOperators: false,
  resourceIds: [12],
  algorithmVersionId: 3,
  parameters: {},
  resultIds: [],
  evidence: [],
  runtime: "durable",
  steps: [],
  createdAt: "2026-09-29",
  updatedAt: "2026-09-29",
  plan: {
    algorithm: "NDVI",
    inputNames: { image: "研究区影像" },
    parameters: { red: 3, nir: 4 },
  },
  planHash: "verified-plan",
  importResults: true,
  resultResourceIds: [],
};
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(agentApi, "prepareWorkflowReport").mockResolvedValue(
    workflowReport(),
  );
  vi.spyOn(agentApi, "bootstrap").mockResolvedValue({
    canChat: true,
    canAgent: true,
    canManage: false,
    internetEnabled: false,
    allowAttachments: false,
    workerOnline: true,
    models: [],
    defaultChatModel: "mock",
    defaultAgentModel: "mock",
    capabilities: [],
  });
  vi.spyOn(agentApi, "resources").mockResolvedValue({ items: [] });
  vi.spyOn(computeApi, "algorithms").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(computeApi, "inputs").mockResolvedValue({ items: [], total: 0 });
});

it("replaces queued evidence with live finished and imported task status", async () => {
  const poll = vi.spyOn(agentApi, "computeTasks").mockResolvedValueOnce({
    items: [
      {
        task,
        autoImport: true,
        trackingStatus: "waiting_compute",
        detail: "等待完成后入库",
      },
    ],
  });
  poll.mockResolvedValue({
    items: [
      {
        task: {
          ...task,
          status: "succeeded",
          stage: "执行完成",
          progress: 100,
          outputs: [
            {
              id: 8,
              key: "ndvi",
              label: "NDVI结果",
              kind: "raster",
              fileName: "ndvi.tif",
              sizeBytes: 24,
              checksum: "abc",
              metadata: {},
              expired: false,
              importStatus: "ready",
              resourceId: 42,
              resourceName: "研究区NDVI",
              resourceLocation: "公开 / 数据资源 / 研究区NDVI",
              importError: "",
              downloadUrl: "",
              previewUrl: "",
            },
          ],
        },
        autoImport: true,
        trackingStatus: "completed",
        detail: "1 项结果已入库",
      },
    ],
  });
  render(
    <AntApp>
      <MemoryRouter>
        <RunComputeTasks runId={7} refreshKey="1" />
      </MemoryRouter>
    </AntApp>,
  );
  await screen.findByText("排队中");
  await waitFor(
    () => expect(screen.getByText("计算完成")).toBeInTheDocument(),
    { timeout: 5000 },
  );
  expect(screen.getByText("已入库")).toBeInTheDocument();
  expect(screen.getByText("公开 / 数据资源 / 研究区NDVI")).toBeInTheDocument();
  expect(screen.queryByText("数据资源 #42")).not.toBeInTheDocument();
});

it("restores a saved plan and only executes after confirmation", async () => {
  vi.spyOn(agentApi, "workflows").mockResolvedValue({ items: [workflow] });
  const confirm = vi.spyOn(agentApi, "confirmWorkflow").mockResolvedValue({
    ...workflow,
    status: "succeeded",
    resultResourceIds: [42],
    detail: "1 项结果已入库",
  });
  const create = vi.spyOn(agentApi, "createWorkflow");
  render(
    <AntApp>
      <MemoryRouter>
        <WorkflowPanel model="mock" resourceIds={[12]} />
      </MemoryRouter>
    </AntApp>,
  );
  fireEvent.click(screen.getByText("MH-workflow / 计划、执行与入库"));
  await screen.findByText("研究区影像");
  expect(confirm).not.toHaveBeenCalled();
  expect(create).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认执行" }));
  await waitFor(() =>
    expect(confirm).toHaveBeenCalledWith("wf-1", "verified-plan"),
  );
  await screen.findByText("成果已保存到本项目的数据资源");
  expect(
    screen.getByRole("link", { name: "在地理工作台对比成果图层" }),
  ).toHaveAttribute("href", "/map?resources=42&projectTagId=1");
});

it("shows confirmation failure without claiming successful execution", async () => {
  vi.spyOn(agentApi, "workflows").mockResolvedValue({ items: [workflow] });
  vi.spyOn(agentApi, "confirmWorkflow").mockRejectedValue(
    new Error("输入数据已变化，请重新预览"),
  );
  render(
    <AntApp>
      <MemoryRouter>
        <WorkflowPanel model="mock" resourceIds={[12]} />
      </MemoryRouter>
    </AntApp>,
  );
  fireEvent.click(screen.getByText("MH-workflow / 计划、执行与入库"));
  fireEvent.click(await screen.findByRole("button", { name: "确认执行" }));
  await screen.findByText("输入数据已变化，请重新预览");
  expect(screen.queryByText("已完成", { exact: true })).not.toBeInTheDocument();
});
