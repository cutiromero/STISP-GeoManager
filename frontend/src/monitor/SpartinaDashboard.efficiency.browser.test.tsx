import { sourceCatalog } from "./monitoringWorkspace.testFixtures";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type {
  MonitoringProduct,
  MonitoringProductList,
  ResourceListItem,
} from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import {
  businessFlowRun,
  directInputPlan,
  researchDetail,
} from "../businessflows/businessFlow.testFixtures";
import { setActiveProject } from "../projects/session";
import { getMonitoringProducts } from "./productApi";
import SpartinaDashboard from "./SpartinaDashboard";

vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { id: 99 } }),
}));
vi.mock("../agent/useAgentBootstrap", () => ({
  useAgentBootstrapState: () => ({
    bootstrap: {
      canAgent: true,
      workerOnline: true,
      defaultAgentModel: "executor",
      models: [
        {
          alias: "executor",
          name: "执行模型",
          allowAgent: true,
          status: "online",
        },
      ],
    },
    status: "ready",
  }),
}));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  requestJson: vi.fn(async () =>
    sourceCatalog("spartina", data.inputResources ?? []),
  ),
}));
vi.mock("./productApi", () => ({ getMonitoringProducts: vi.fn() }));
vi.mock("./MonitorComparisonMap", () => ({
  default: (props: {
    product?: MonitoringProduct;
    displayResource?: ResourceListItem;
  }) => (
    <output data-testid="spartina-map-state">
      {JSON.stringify({
        product: props.product?.id,
        resource: props.displayResource?.id,
      })}
    </output>
  ),
}));
const config = {
  title: "互花米草分布解译",
  source: "remote_sensing_products" as const,
  scenes: ["spartina" as const],
  initialView: {
    center: [121.92, 31.24] as [number, number],
    zoom: 0.3,
    regionZoom: 11,
  },
};
const resource = (id: number, name: string) =>
  ({
    id,
    name,
    code: `source-${id}`,
    dataType: "raster",
    spatialClass: "spatial",
    status: "active",
    updatedAt: "2026-11-14T00:00:00Z",
    sizeBytes: 100,
    isQueryable: false,
    isRenderable: true,
    categoryPath: [],
    availableViews: ["map"],
    defaultView: "map",
  }) as ResourceListItem;
const result = {
  id: 1,
  schemaVersion: 1,
  code: "spartina-test",
  name: "当前研究区分布",
  resourceId: 2001,
  resource: resource(2001, "当前研究区分布"),
  scene: "spartina",
  kind: "model",
  quality: "passed",
  observedStart: null,
  observedEnd: null,
  sourceResourceIds: [1463, 1464, 1465],
  sourceLabel: "2025三季节",
  limitations: ["影像日期待补充"],
  interpretation: "本研究区分布面积12 ha。",
  statistics: {
    area_ha: 12,
    patch_count: 3,
    valid_area_km2: 0.5,
    coverage_percent: 24,
  },
  statisticsMethod: "原始WGS84网格椭球面积",
  model: {
    name: "互花米草随机森林",
    version: "1.0.0",
    variant: "三季节48特征",
    checkpointSha256: "a".repeat(64),
    forecastLeadDays: null,
  },
  threshold: null,
  timing: {
    inputThrough: null,
    validStart: null,
    validEnd: null,
    evidence: "交付月份",
  },
  registeredAt: "2026-11-14T00:00:00Z",
  metrics: [
    { key: "area_ha", label: "分布面积", unit: "ha", value: 12 },
    { key: "patch_count", label: "斑块数量", unit: "个", value: 3 },
  ],
  provenance: {
    type: "system_interpretation",
    owned: true,
    batchId: "owned-batch",
    taskId: "11111111-1111-4111-8111-111111111111",
    workflowId: null,
    createdAt: "2026-11-14T00:00:00Z",
    creator: "本人",
  },
  attachments: [
    { role: "probability", resource: resource(2002, "本次概率图") },
    { role: "original", resource: resource(2003, "08月真彩色预览") },
  ],
} as MonitoringProduct;
const data: MonitoringProductList = {
  projectId: 13,
  scene: "spartina",
  title: "互花米草",
  route: ["核对输入", "模型解译"],
  items: [result],
  nextBeforeId: null,
  inputResources: [
    resource(1463, "RF_202503"),
    resource(1464, "RF_202508"),
    resource(1465, "RF_202512"),
  ],
  businessFlow: {
    definitionId: 2,
    versionId: 21,
    title: "互花米草分布解译",
    goal: "解译研究区",
  },
};
function show() {
  return render(
    <App>
      <MemoryRouter>
        <SpartinaDashboard projectId={13} config={config} navigation={null} />
      </MemoryRouter>
    </App>,
  );
}
beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
  setActiveProject("13");
  vi.mocked(getMonitoringProducts)
    .mockReset()
    .mockResolvedValue(structuredClone(data));
  vi.spyOn(businessFlowsApi, "runs").mockResolvedValue({ items: [] });
  vi.spyOn(businessFlowsApi, "detail").mockResolvedValue({
    ...researchDetail,
    versions: researchDetail.versions.map((version) => ({
      ...version,
      definition: {
        ...version.definition,
        inputRequirements: ["march", "august", "december"].map((key) => ({
          key,
          label: key,
          description: "16波段原件",
          dataTypes: ["raster" as const],
          required: true,
          requiredFields: [],
          multiple: false,
        })),
      },
    })),
  });
  vi.spyOn(businessFlowsApi, "prepareInputs").mockImplementation(
    async (_id, request) => directInputPlan(request),
  );
  vi.spyOn(businessFlowsApi, "start").mockResolvedValue(
    businessFlowRun({ projectId: 13, flowId: 2, status: "waiting_approval" }),
  );
});
afterEach(() => {
  sessionStorage.clear();
  setActiveProject("1");
});

it("uses Spartina cards and maps only the probability belonging to the selected result", async () => {
  const view = show();
  await screen.findByText("12");
  expect(view.container.querySelectorAll(".monitor-panel")).toHaveLength(6);
  for (const name of [
    "研究区与成果",
    "解译任务",
    "分布统计",
    "分布与显示",
    "方法与输入",
    "成果说明",
  ])
    expect(screen.getByRole("region", { name })).toBeInTheDocument();
  expect(screen.queryByText("建筑")).not.toBeInTheDocument();
  await screen.findByTestId("spartina-map-state", {}, { timeout: 10000 });
  fireEvent.click(screen.getByText("概率", { exact: true }));
  await waitFor(() =>
    expect(screen.getByTestId("spartina-map-state")).toHaveTextContent("2002"),
  );
  expect(businessFlowsApi.start).not.toHaveBeenCalled();
});

it("submits three seasonal sources as one run with the selected geographic region", async () => {
  show();
  const start = await screen.findByRole("button", {
    name: "开始解译",
    exact: true,
  });
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(screen.getByText("经纬度范围", { exact: true }));
  for (const [label, value] of [
    ["西界", 121.9],
    ["南界", 31.2],
    ["东界", 121.99],
    ["北界", 31.29],
  ] as const)
    fireEvent.change(
      screen.getByRole("spinbutton", { name: `研究区${label}` }),
      { target: { value: String(value) } },
    );
  fireEvent.click(start);
  const submit = await screen.findByRole("button", { name: "开始业务流" });
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);
  fireEvent.click(submit);
  await screen.findByRole("button", { name: "在智能体中打开" });
  expect(businessFlowsApi.start).toHaveBeenCalledOnce();
  expect(businessFlowsApi.start).toHaveBeenCalledWith(
    2,
    expect.objectContaining({
      inputs: { march: 1463, august: 1464, december: 1465 },
      parameters: {
        nodeParameters: {
          interpret: { west: 121.9, south: 31.2, east: 121.99, north: 31.29 },
        },
      },
    }),
  );
});
