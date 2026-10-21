import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentWorkflow,
  ComputeCandidate,
} from "../api/generated/types.gen";
import WorkflowPanel from "./WorkflowPanel";
import DemoWorkflowForm, { demoGoals } from "./DemoWorkflowForm";
import { geologyRequiredFields } from "./geologyWorkflowInputs";

const names = {
  initial_map: "待检查地质图",
  coverage: "制图范围",
  rules: "专家规则",
};
const candidates: ComputeCandidate[] = Object.entries(names).map(
  ([role, name], index) => ({
    id: 101 + index,
    name,
    kind: role === "rules" ? "table" : "vector",
    projectTagId: 1,
    fields: geologyRequiredFields[role]!,
    bands: 0,
    crs: "EPSG:32646",
    geometryTypes: role === "rules" ? [] : ["Polygon"],
    sizeBytes: 100,
  }),
);
candidates.push({ ...candidates[0]!, id: 104, name: "新区域地质图" });
const preset = {
  inputs: { initial_map: 101, coverage: 102, rules: 103 },
  parameters: { working_epsg: 32646, max_changes: 2 },
};
const resources = candidates.map((item) => ({
  id: item.id,
  name: item.name,
  dataType: item.kind,
  description: "本次资料说明",
}));

const saved = (): AgentWorkflow => ({
  id: "current-plan",
  projectId: 1,
  workflowType: "geology_map_review",
  goal: demoGoals.geology_map_review,
  model: "configured-model",
  status: "waiting_approval",
  detail: "请核对计划",
  currentStep: "review_plan",
  iteration: 0,
  operatorSteps: 0,
  maxIterations: 8,
  maxOperatorSteps: 12,
  executeOperators: false,
  resourceIds: [101, 102, 103],
  algorithmVersionId: null,
  parameters: preset.parameters,
  resultIds: [],
  evidence: [],
  runtime: "durable",
  steps: [],
  createdAt: "",
  updatedAt: "",
  planHash: "current-hash",
  importResults: true,
  resultResourceIds: [],
  plan: {
    inputs: preset.inputs,
    inputNames: names,
    phase: "review_plan",
    knowledgeSelection: { mode: "auto", domains: [] },
  },
});

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(agentApi, "bootstrap").mockResolvedValue({
    knowledgeDomains: [],
  } as never);
  vi.spyOn(agentApi, "researchDemos").mockResolvedValue({
    items: [
      {
        scenario: "geology_map_review",
        title: "地质成果智能检查与修正",
        projectId: 1,
        projectName: "公开",
        prompt: "检查地图",
        sampleNature: "demonstration_case",
        available: true,
        preset,
      },
    ],
  });
  vi.spyOn(agentApi, "resources").mockResolvedValue({ items: resources });
  vi.spyOn(agentApi, "workflows").mockResolvedValue({ items: [] });
  vi.spyOn(computeApi, "algorithms").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(computeApi, "inputs").mockResolvedValue({
    items: candidates,
    total: candidates.length,
  });
});

function show() {
  return render(
    <App>
      <MemoryRouter>
        <WorkflowPanel model="configured-model" resourceIds={[]} embedded />
      </MemoryRouter>
    </App>,
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

it("restores the current active preset and really rematches an already selected custom map", async () => {
  const create = vi
    .spyOn(agentApi, "createWorkflow")
    .mockResolvedValue(saved());
  show();
  await select("研究场景", "地质成果智能检查与修正");
  await screen.findByText("待检查地质图 / 待检查地质图");
  await select("待检查地质图", "新区域地质图");
  expect(screen.getByText("待检查地质图 / 新区域地质图")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "按名称匹配资料" }));
  expect(
    await screen.findByText(/已重新匹配：待检查地质图、制图范围、专家规则/),
  ).toBeVisible();
  expect(screen.getByText("待检查地质图 / 待检查地质图")).toBeVisible();
  await select("待检查地质图", "新区域地质图");
  fireEvent.change(screen.getByRole("textbox", { name: "工作流目标" }), {
    target: { value: "用户改过的目标" },
  });
  fireEvent.click(screen.getByRole("button", { name: "预设" }));
  expect(screen.getByRole("textbox", { name: "工作流目标" })).toHaveValue(
    demoGoals.geology_map_review,
  );
  fireEvent.click(screen.getByRole("button", { name: "生成执行计划" }));
  await waitFor(() =>
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({
        inputs: preset.inputs,
        parameters: preset.parameters,
        knowledgeSelection: { mode: "auto", domains: [] },
      }),
    ),
  );
});

it("offers different compatible choices for the map, coverage and expert rules", async () => {
  show();
  await select("研究场景", "地质成果智能检查与修正");
  for (const [role, name] of Object.entries(names)) {
    fireEvent.mouseDown(screen.getByRole("combobox", { name }));
    const item = await screen.findByText(name, {
      selector: ".ant-select-item-option-content",
    });
    const dropdown = item.closest(".ant-select-dropdown") as HTMLElement;
    const options = within(dropdown)
      .getAllByText(/.+/, { selector: ".ant-select-item-option-content" })
      .map((option) => option.textContent);
    expect(options).toContain(name);
    for (const other of Object.entries(names)
      .filter(([key]) => key !== role)
      .map(([, value]) => value))
      expect(options).not.toContain(other);
    fireEvent.keyDown(screen.getByRole("combobox", { name }), {
      key: "Escape",
    });
  }
});

it("matches the actual catalog names and prefers the active name over a preserved old copy", () => {
  const onInputs = vi.fn();
  const actual = candidates.map((item) => ({
    ...item,
    name:
      item.id === 102
        ? "制图覆盖资料"
        : item.id === 103
          ? "专家知识检查规则"
          : item.name,
  }));
  actual.push({ ...candidates[0]!, id: 105, name: "待检查地质图（旧版）" });
  render(
    <App>
      <DemoWorkflowForm
        type="geology_map_review"
        candidates={actual}
        resources={[]}
        inputs={{ initial_map: 104, coverage: 102, rules: 103 }}
        parameters={{}}
        disabled={false}
        onInputsChange={onInputs}
        onParametersChange={vi.fn()}
      />
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: "按名称匹配资料" }));
  expect(onInputs).toHaveBeenCalledWith(preset.inputs);
  expect(
    screen.getByText(/已重新匹配：待检查地质图、制图范围、专家规则/),
  ).toBeVisible();
});

it("rejects incompatible historical selections with a specific missing-field explanation", () => {
  render(
    <App>
      <DemoWorkflowForm
        type="geology_map_review"
        candidates={candidates}
        resources={resources}
        inputs={{ initial_map: 103, coverage: 102, rules: 103 }}
        parameters={{}}
        disabled={false}
        onInputsChange={vi.fn()}
        onParametersChange={vi.fn()}
      />
    </App>,
  );
  expect(screen.getByText("当前资料不满足本场景要求")).toBeVisible();
  expect(
    screen.getByText(/待检查地质图：缺少必需字段：feature_id/),
  ).toBeVisible();
});

it("clears incompatible selections on an ambiguous match while preserving a compatible custom choice", () => {
  const onInputs = vi.fn();
  const ambiguous = candidates.map((item) => ({
    ...item,
    name:
      item.id === 101
        ? "待检查地质图甲"
        : item.id === 104
          ? "待检查地质图乙"
          : item.name,
  }));
  const view = render(
    <App>
      <DemoWorkflowForm
        type="geology_map_review"
        candidates={ambiguous}
        resources={[]}
        inputs={{ initial_map: 103, coverage: 102, rules: 103 }}
        parameters={{}}
        disabled={false}
        onInputsChange={onInputs}
        onParametersChange={vi.fn()}
      />
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: "按名称匹配资料" }));
  expect(onInputs).toHaveBeenLastCalledWith({ coverage: 102, rules: 103 });
  expect(screen.getByText(/原选择不兼容，已清空/)).toBeVisible();
  view.rerender(
    <App>
      <DemoWorkflowForm
        type="geology_map_review"
        candidates={ambiguous}
        resources={[]}
        inputs={{ initial_map: 104, coverage: 102, rules: 103 }}
        parameters={{}}
        disabled={false}
        onInputsChange={onInputs}
        onParametersChange={vi.fn()}
      />
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: "按名称匹配资料" }));
  expect(onInputs).toHaveBeenLastCalledWith({
    initial_map: 104,
    coverage: 102,
    rules: 103,
  });
  expect(screen.getByText(/已保留兼容的手动选择/)).toBeVisible();
});

it("requires a new plan after changing an input and cancels only the unexecuted old plan", async () => {
  vi.mocked(agentApi.workflows).mockResolvedValue({ items: [saved()] });
  const confirm = vi.spyOn(agentApi, "confirmWorkflow");
  const cancel = vi
    .spyOn(agentApi, "cancelWorkflow")
    .mockResolvedValue({ ...saved(), status: "cancelled" });
  const create = vi
    .spyOn(agentApi, "createWorkflow")
    .mockResolvedValue({ ...saved(), id: "new-plan", status: "queued" });
  show();
  await screen.findByRole("button", { name: "确认执行" });
  await select("待检查地质图", "新区域地质图");
  expect(await screen.findByText("资料或参数已改变")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "确认执行" }),
  ).not.toBeInTheDocument();
  expect(confirm).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "生成执行计划" }));
  await waitFor(() => expect(create).toHaveBeenCalledOnce());
  expect(cancel).toHaveBeenCalledWith("current-plan", {
    replacePlanHash: "current-hash",
  });
  expect(cancel.mock.invocationCallOrder[0]!).toBeLessThan(
    create.mock.invocationCallOrder[0]!,
  );
  expect(create).toHaveBeenCalledWith(
    expect.objectContaining({ inputs: { ...preset.inputs, initial_map: 104 } }),
  );
});

it.each(["conflict", "still-running"])(
  "does not create a replacement when conditional cancellation returns %s",
  async (mode) => {
    vi.mocked(agentApi.workflows).mockResolvedValue({ items: [saved()] });
    const cancel = vi.spyOn(agentApi, "cancelWorkflow");
    if (mode === "conflict")
      cancel.mockRejectedValue(
        Object.assign(new Error("计划已执行，不能作废"), { status: 409 }),
      );
    else cancel.mockResolvedValue({ ...saved(), status: "running" });
    const create = vi.spyOn(agentApi, "createWorkflow");
    show();
    await screen.findByRole("button", { name: "确认执行" });
    await select("待检查地质图", "新区域地质图");
    fireEvent.click(screen.getByRole("button", { name: "生成执行计划" }));
    expect(
      await screen.findByText(
        mode === "conflict"
          ? "计划已执行，不能作废"
          : "旧计划尚未停止，已保留当前任务。请刷新状态后再生成计划。",
      ),
    ).toBeVisible();
    expect(create).not.toHaveBeenCalled();
  },
);

it("loads later catalog pages so a preset beyond the first hundred remains selectable", async () => {
  vi.mocked(computeApi.inputs).mockImplementation(async (params) =>
    params?.page === 1
      ? { items: candidates.slice(0, 1), total: candidates.length }
      : { items: candidates.slice(1), total: candidates.length },
  );
  show();
  await select("研究场景", "地质成果智能检查与修正");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "预设" })).not.toBeDisabled(),
  );
  expect(computeApi.inputs).toHaveBeenCalledWith({ page: 2, pageSize: 100 });
});

it("uses the published geology parameter form and sends the user's revised threshold", async () => {
  vi.mocked(computeApi.algorithms).mockResolvedValue({
    total: 1,
    items: [
      {
        id: 1,
        projectTagId: 1,
        identifier: "geology-map-check",
        name: "地质成果智能检查",
        description: "检查",
        category: "地质",
        author: "STISP",
        enabled: true,
        canManage: false,
        versions: [
          {
            id: 37,
            version: "1.0.1",
            status: "published",
            checksum: "published-checksum",
            runtimeDigest: "sha256:runtime",
            validated: true,
            createdAt: "",
            manifest: {
              schemaVersion: 1,
              identifier: "geology-map-check",
              name: "地质成果智能检查",
              version: "1.0.1",
              description: "检查",
              author: "STISP",
              runtime: "geospatial",
              inputs: [],
              outputs: [],
              deterministic: true,
              timeoutSeconds: 300,
              parameters: [
                {
                  key: "max_changes",
                  label: "本轮修改数量上限",
                  type: "integer",
                  default: 2,
                  min: 1,
                  max: 10,
                },
              ],
            },
          },
        ],
      },
    ],
  });
  const create = vi
    .spyOn(agentApi, "createWorkflow")
    .mockResolvedValue(saved());
  show();
  await select("研究场景", "地质成果智能检查与修正");
  const field = await screen.findByRole("spinbutton", {
    name: "本轮修改数量上限",
  });
  expect(field).toHaveValue("2");
  fireEvent.change(field, { target: { value: "4" } });
  fireEvent.click(screen.getByRole("button", { name: "生成执行计划" }));
  await waitFor(() =>
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({
        parameters: { working_epsg: 32646, max_changes: 4 },
      }),
    ),
  );
});

it("does not replace or cancel a running computation through changed form fields", async () => {
  vi.mocked(agentApi.workflows).mockResolvedValue({
    items: [{ ...saved(), status: "running" }],
  });
  const cancel = vi.spyOn(agentApi, "cancelWorkflow");
  show();
  await screen.findByRole("combobox", { name: "待检查地质图" });
  expect(screen.getByRole("button", { name: "预设" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "生成执行计划" })).toBeDisabled();
  expect(screen.getByRole("textbox", { name: "工作流目标" })).toBeDisabled();
  expect(cancel).not.toHaveBeenCalled();
});
