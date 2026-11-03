import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentFieldMappingReview,
  AgentWorkflow,
  AgentWorkflowUpload,
} from "../api/generated/types.gen";
import { resetProjectSession } from "../projects/session";
import FieldMappingReview from "./FieldMappingReview";
import WorkflowPanel from "./WorkflowPanel";

afterEach(() => resetProjectSession());

const upload: AgentWorkflowUpload = {
  id: "4f1c2a9e-7b3d-4c61-9a2e-1d5f6b7c8a90",
  batchId: "0".repeat(32),
  resourceId: 812,
  name: "八宝山幅地质图",
  fileName: "八宝山幅地质图.zip",
  dataType: "vector",
  sizeBytes: 2048,
  roleHint: "lithology",
  profile: {
    kind: "vector",
    crs: "EPSG:4326",
    geometryTypes: ["Polygon"],
    featureCount: 486,
    bounds: [96.8, 35.6, 97.4, 35.9],
    bandCount: null,
    width: null,
    height: null,
    fields: [
      {
        name: "DCMC",
        type: "text",
        samples: ["八宝山组二段"],
        distinctCount: 36,
      },
      { name: "DH", type: "text", samples: ["T3b2"], distinctCount: 34 },
    ],
    warnings: [],
  },
  workflowId: null,
  createdAt: "2026-11-03T09:30:00+08:00",
};

const review = (name: string | null): AgentFieldMappingReview => ({
  roles: [
    {
      role: "lithology",
      label: "地质图",
      resourceId: 812,
      fileName: "八宝山幅地质图.zip",
      fields: ["DCMC", "DH"],
      targets: [
        {
          key: "name",
          label: "地层或填图单元名称",
          required: true,
          field: name,
          reason: name ? "取值为组、段名称" : "未找到对应字段",
        },
        {
          key: "geo_sym",
          label: "代号",
          required: false,
          field: "DH",
          reason: "较短的地质代号",
        },
      ],
    },
  ],
  questions: name
    ? []
    : ["地质图中没有找到“地层或填图单元名称”，请指定对应字段"],
  modelMode: "real",
  confirmed: false,
});

const queued: AgentWorkflow = {
  id: "generic-task",
  projectId: 1,
  workflowType: "geology_generic",
  goal: "检查八宝山幅地质图",
  model: "configured-model",
  status: "queued",
  detail: "等待处理",
  currentStep: "",
  iteration: 0,
  operatorSteps: 0,
  maxIterations: 12,
  maxOperatorSteps: 12,
  executeOperators: false,
  resourceIds: [812],
  algorithmVersionId: null,
  parameters: {},
  resultIds: [],
  evidence: [],
  runtime: "durable_state_machine",
  steps: [],
  createdAt: "",
  updatedAt: "",
  planHash: "",
  importResults: true,
  resultResourceIds: [],
  plan: { inputs: {}, uploadInputs: { lithology: 812 } },
};

beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.setItem("workflow-session:77:1", "geology_generic");
  const item = {
    scenario: "geology_generic" as const,
    title: "通用地质推理（上传资料）",
    projectId: 1,
    projectName: "核地院逻辑推理",
    prompt: "检查上传资料",
    sampleNature: "user_upload" as const,
    available: true,
  };
  vi.spyOn(agentApi, "bootstrap").mockResolvedValue({
    knowledgeDomains: [],
  } as never);
  vi.spyOn(agentApi, "researchDemos").mockResolvedValue({ items: [item] });
  vi.spyOn(agentApi, "researchDemoSummaries").mockResolvedValue({
    items: [item],
  });
  vi.spyOn(agentApi, "resources").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "workflowHistory").mockResolvedValue({
    items: [],
    total: 0,
    offset: 0,
    limit: 30,
    hasMore: false,
  });
  vi.spyOn(agentApi, "workflowUploads").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "workflow").mockResolvedValue(queued);
  vi.spyOn(computeApi, "algorithms").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(computeApi, "inputs").mockResolvedValue({ items: [], total: 0 });
});

it("uploads a file, assigns the recommended role and creates the task with its batch", async () => {
  vi.spyOn(agentApi, "uploadWorkflowFile").mockResolvedValue(upload);
  const created = vi
    .spyOn(agentApi, "createWorkflow")
    .mockResolvedValue(queued);
  const { container } = render(
    <App>
      <MemoryRouter>
        <WorkflowPanel
          model="configured-model"
          resourceIds={[]}
          userId={77}
          embedded
        />
      </MemoryRouter>
    </App>,
  );
  const input = await waitFor(() => {
    const element =
      container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(element).not.toBeNull();
    return element!;
  });
  const button = screen.getByRole("button", { name: "生成执行计划" });
  expect(button).toBeDisabled();
  fireEvent.change(input, {
    target: { files: [new File(["{}"], "八宝山幅地质图.zip")] },
  });
  expect(await screen.findByText("八宝山幅地质图.zip")).toBeInTheDocument();
  const batchId = vi.mocked(agentApi.uploadWorkflowFile).mock.calls[0]![0];
  expect(batchId).toMatch(/^[0-9a-f]{32}$/);
  expect(screen.getByText(/486 个要素/)).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: "工作流目标" }), {
    target: { value: "检查八宝山幅地质图" },
  });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(created).toHaveBeenCalledOnce());
  expect(created.mock.calls[0]![0]).toMatchObject({
    workflowType: "geology_generic",
    uploadBatchId: batchId,
    inputs: { lithology: 812 },
    parameters: {},
  });
});

it("blocks confirmation until the required stratum field is chosen", async () => {
  const confirm = vi.fn();
  const view = render(
    <FieldMappingReview
      review={review(null)}
      busy={false}
      onConfirm={confirm}
    />,
  );
  expect(screen.getByText(/请指定对应字段/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "确认字段并继续" })).toBeDisabled();
  view.unmount();
  render(
    <FieldMappingReview
      review={review("DCMC")}
      busy={false}
      onConfirm={confirm}
    />,
  );
  expect(screen.getByText("取值为组、段名称")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "确认字段并继续" }));
  expect(confirm).toHaveBeenCalledWith({
    lithology: { name: "DCMC", geo_sym: "DH" },
  });
});
