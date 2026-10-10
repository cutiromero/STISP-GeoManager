import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type {
  AgentComputeIntent,
  ComputeVersion,
} from "../api/generated/types.gen";
import ComputeIntentCard from "../agent/ComputeIntentCard";
import {
  computeIntent,
  computeRun,
  computeVersion,
  liveComputeTask,
} from "../agent/computeFlow.testFixtures";
import { setLocale } from "../i18n";
import ComputeTaskForm from "./ComputeTaskForm";
import "../agent/agent.css";

const table = {
  id: 22,
  name: "监测数据表",
  kind: "table",
  projectTagId: 1,
  fields: ["value", "date"],
  bands: 0,
  crs: "",
  geometryTypes: [],
  sizeBytes: 100,
};
const tableVersion: ComputeVersion = {
  ...computeVersion,
  manifest: {
    ...computeVersion.manifest,
    inputs: [
      { key: "table", label: "监测表格", kind: "table", required: true },
    ],
    parameters: [
      {
        key: "field",
        label: "分析字段",
        type: "field",
        input: "table",
        required: true,
        default: "value",
        help: "选择需要分析的数值字段",
      },
      {
        key: "factor",
        label: "缩放倍数",
        type: "number",
        required: true,
        default: 0,
        min: 0,
        max: 10,
      },
      {
        key: "keep",
        label: "保留原值",
        type: "boolean",
        required: true,
        default: false,
      },
      {
        key: "mode",
        label: "计算方式",
        type: "enum",
        choices: ["标准", "自定义"],
        required: true,
        default: "自定义",
      },
      {
        key: "offset",
        label: "偏移量",
        type: "integer",
        required: true,
        default: 3,
        when: { key: "mode", equals: "自定义" },
      },
    ],
    outputs: [
      {
        key: "result",
        label: "处理后表格",
        kind: "table",
        file: "result.csv",
        required: true,
      },
    ],
  },
};
const tableIntent: AgentComputeIntent = {
  ...computeIntent,
  algorithm: tableVersion,
  inputs: { table: table.id },
  parameters: {
    field: "value",
    factor: 0,
    keep: false,
    mode: "自定义",
    offset: 3,
  },
  inputCandidates: [table],
  missingParameters: [],
};

beforeEach(async () => {
  await setLocale("zh-CN");
  vi.restoreAllMocks();
  vi.spyOn(computeApi, "inputs").mockResolvedValue({
    items: computeIntent.inputCandidates,
    total: 2,
  });
  vi.spyOn(computeApi, "preflight").mockImplementation(async (body) => ({
    valid: true,
    parameters: body.parameters,
    detail: "检查通过",
  }));
  vi.spyOn(computeApi, "submit").mockResolvedValue(liveComputeTask());
  vi.spyOn(agentApi, "updateComputeIntent").mockResolvedValue(computeRun());
});

async function choose(label: string, option: string) {
  await page.getByRole("combobox", { name: label, exact: true }).click();
  fireEvent.click(
    await screen.findByText(option, {
      selector:
        ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content",
    }),
  );
}

function showCenter(version = computeVersion, resourceId?: number) {
  return render(
    <AntApp>
      <ComputeTaskForm
        version={version}
        resourceId={resourceId}
        onClose={() => {}}
        onSubmitted={() => {}}
      />
    </AntApp>,
  );
}
function showAgent(intent = computeIntent) {
  return render(
    <AntApp>
      <ComputeIntentCard runId={8} intent={intent} onChanged={() => {}} />
    </AntApp>,
  );
}

it("uses the same three sections and band names while preserving each entry's default policy", async () => {
  const center = showCenter(computeVersion, 10);
  await screen.findByText("研究区影像 · 8 波段");
  for (const title of ["输入数据", "算法参数", "结果概览"])
    expect(screen.getByRole("region", { name: title })).toBeInTheDocument();
  expect(
    screen.getByText("第 1 波段", { selector: ".ant-select-content" }),
  ).toBeInTheDocument();
  await choose("红光波段", "第 3 波段");
  expect(screen.getByText("NDVI指数栅格")).toBeInTheDocument();
  center.unmount();
  showAgent();
  await screen.findByText("研究区影像 · 8 波段");
  for (const title of ["输入数据", "算法参数", "结果概览"])
    expect(screen.getByRole("region", { name: title })).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "红光波段" })).toHaveValue("");
  await choose("红光波段", "第 3 波段");
  expect(screen.getByText("NDVI指数栅格")).toBeInTheDocument();
});

it("clears linked bands in the compute center when the image changes", async () => {
  showCenter(computeVersion, 10);
  await screen.findByText("研究区影像 · 8 波段");
  await choose("近红外波段", "第 8 波段");
  await choose("输入影像", "另一幅影像 · 4 波段");
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: "近红外波段" })).toHaveValue(
      "",
    ),
  );
  expect(screen.getByRole("combobox", { name: "红光波段" })).toHaveValue("");
  fireEvent.click(screen.getByRole("button", { name: "检查并提交" }));
  await screen.findAllByText("请补充此参数");
  expect(computeApi.submit).not.toHaveBeenCalled();
});

for (const entry of ["center", "agent"] as const) {
  it(`${entry} submits zero and false, hides conditional parameters, and shows help and ranges`, async () => {
    vi.mocked(computeApi.inputs).mockResolvedValue({
      items: [table],
      total: 1,
    });
    if (entry === "center") showCenter(tableVersion, table.id);
    else showAgent(tableIntent);
    await screen.findByText("监测数据表");
    expect(screen.getByText("选择需要分析的数值字段")).toBeInTheDocument();
    expect(screen.getByText("范围：0 – 10")).toBeInTheDocument();
    expect(screen.getByLabelText("缩放倍数")).toHaveValue("0");
    expect(screen.getByRole("switch", { name: "保留原值" })).not.toBeChecked();
    await choose("计算方式", "标准");
    await waitFor(() =>
      expect(screen.queryByLabelText("偏移量")).not.toBeInTheDocument(),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: entry === "center" ? "检查并提交" : "开始计算",
      }),
    );
    const submit =
      entry === "center" ? computeApi.submit : agentApi.updateComputeIntent;
    await waitFor(() => expect(submit).toHaveBeenCalledOnce());
    const body =
      entry === "center"
        ? vi.mocked(computeApi.submit).mock.calls[0][0]
        : vi.mocked(agentApi.updateComputeIntent).mock.calls[0][1];
    expect(body.parameters).toEqual({
      field: "value",
      factor: 0,
      keep: false,
      mode: "标准",
    });
  });
}

it("rejects a stale enum value instead of sending it to the agent", async () => {
  showAgent({
    ...tableIntent,
    parameters: { ...tableIntent.parameters, mode: "失效选项" },
  });
  fireEvent.click(screen.getByRole("button", { name: "开始计算" }));
  await screen.findByText("请从可用选项中选择");
  expect(agentApi.updateComputeIntent).not.toHaveBeenCalled();
});

for (const entry of ["center", "agent"] as const) {
  it(`${entry} clears fields linked to a changed table and retains independent parameters`, async () => {
    const otherTable = {
      ...table,
      id: 23,
      name: "另一张监测表",
      fields: ["district"],
    };
    vi.mocked(computeApi.inputs).mockResolvedValue({
      items: [table, otherTable],
      total: 2,
    });
    if (entry === "center") showCenter(tableVersion, table.id);
    else showAgent({ ...tableIntent, inputCandidates: [table, otherTable] });
    await screen.findByText("监测数据表");
    await choose("监测表格", "另一张监测表");
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "分析字段" })).toHaveValue(
        "",
      ),
    );
    expect(screen.getByLabelText("缩放倍数")).toHaveValue("0");
    expect(screen.getByRole("switch", { name: "保留原值" })).not.toBeChecked();
    await choose("分析字段", "district");
    expect(
      screen.getByText("district", { selector: ".ant-select-content" }),
    ).toBeInTheDocument();
  });
}

it("rejects an out-of-range numeric parameter before the agent request", async () => {
  showAgent({
    ...tableIntent,
    parameters: { ...tableIntent.parameters, factor: 11 },
  });
  fireEvent.click(screen.getByRole("button", { name: "开始计算" }));
  await screen.findByText("数值超出允许范围");
  expect(agentApi.updateComputeIntent).not.toHaveBeenCalled();
});

it("disables input-dependent fields until data is selected", async () => {
  const center = showCenter();
  expect(screen.getByRole("combobox", { name: "红光波段" })).toBeDisabled();
  center.unmount();
  showAgent({ ...computeIntent, inputs: {} });
  expect(screen.getByRole("combobox", { name: "红光波段" })).toBeDisabled();
});

it("uses English section and band labels", async () => {
  await setLocale("en");
  showAgent();
  await screen.findByText("研究区影像 · 8 bands");
  expect(
    screen.getByRole("region", { name: "Input data" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "Algorithm parameters" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "Result overview" }),
  ).toBeInTheDocument();
  await choose("Red band", "Band 3");
});

it("keeps both parameter layouts in a single column on narrow screens", async () => {
  await page.viewport(390, 844);
  const center = showCenter(computeVersion, 10);
  await screen.findByText("研究区影像 · 8 波段");
  const checkGrid = () => {
    const grid = document.querySelector(".compute-field-grid") as HTMLElement;
    expect(getComputedStyle(grid).gridTemplateColumns.split(" ")).toHaveLength(
      1,
    );
    expect(grid.getBoundingClientRect().right).toBeLessThanOrEqual(390);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390);
  };
  await waitFor(() =>
    expect(screen.getByRole("dialog").className).not.toContain("ant-zoom"),
  );
  checkGrid();
  await page.screenshot({
    path: "../../test-results/compute-fields-center-mobile.png",
  });
  center.unmount();
  const agent = showAgent();
  await screen.findByText("研究区影像 · 8 波段");
  checkGrid();
  await page.screenshot({
    path: "../../test-results/compute-fields-agent-mobile.png",
  });
  agent.unmount();
  await page.viewport(1600, 1000);
  showAgent(tableIntent);
  await page.screenshot({
    path: "../../test-results/compute-fields-agent-desktop.png",
  });
  await page.viewport(1600, 900);
});
