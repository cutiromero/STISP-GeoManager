import { sourceCatalog, sourceTimes } from "./monitoringWorkspace.testFixtures";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type {
  MonitoringProduct,
  MonitoringProductList,
  ResourceListItem,
  WildfireObservationCatalog,
} from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import {
  businessFlowRun,
  directInputPlan,
  researchDetail,
} from "../businessflows/businessFlow.testFixtures";
import { setActiveProject } from "../projects/session";
import { getMonitoringProducts } from "./productApi";
import WildfireDashboard from "./WildfireDashboard";

const state = vi.hoisted(() => ({
  catalog: undefined as WildfireObservationCatalog | undefined,
}));
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
  requestJson: vi.fn(async (url: string) =>
    url.includes("source-times")
      ? sourceTimes
      : sourceCatalog(
          "wildfire",
          state.catalog?.cube ? [state.catalog.cube] : [],
        ),
  ),
}));
vi.mock("./productApi", () => ({ getMonitoringProducts: vi.fn() }));
vi.mock("./ProductMap", () => ({
  default: ({ resource }: { resource?: ResourceListItem }) => (
    <output data-testid="observation-map">{resource?.id}</output>
  ),
}));
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
const cube = resource(1475, "SeasFire原始立方体");
const catalog: WildfireObservationCatalog = {
  cube,
  products: [
    { key: "gwis_ba", label: "GWIS火烧面积", unit: "ha", periodMode: "8day" },
    {
      key: "fcci_ba",
      label: "FCCI月度火烧面积",
      unit: "ha",
      periodMode: "monthly",
    },
  ],
  times: [
    {
      index: 872,
      date: "2019-12-19",
      endDate: "2019-12-26",
      validProducts: ["gwis_ba", "fcci_ba"],
    },
    {
      index: 873,
      date: "2019-12-27",
      endDate: "2019-12-31",
      validProducts: ["gwis_ba", "fcci_ba"],
    },
  ],
};
const product = {
  id: 1,
  schemaVersion: 1,
  code: "fire-obs",
  name: "本次GWIS观测",
  resourceId: 2010,
  resource: resource(2010, "观测原值"),
  scene: "wildfire",
  kind: "observation",
  quality: "passed",
  observedStart: "2019-12-27",
  observedEnd: "2019-12-31",
  sourceResourceIds: [1475],
  sourceLabel: "GWIS原始观测",
  limitations: ["0.25度格网"],
  interpretation: "研究区观测火烧面积180 ha。",
  statistics: { burned_area_ha: 180, valid_coverage_percent: 100 },
  statisticsMethod: "原始ha直接求和",
  model: null,
  threshold: null,
  timing: {
    inputThrough: "2019-12-31",
    validStart: null,
    validEnd: null,
    evidence: "原始时间轴",
  },
  registeredAt: "2026-11-14T00:00:00Z",
  metrics: [
    { key: "burned_area_ha", label: "观测烧毁面积", unit: "ha", value: 180 },
    {
      key: "valid_coverage_percent",
      label: "有效数据覆盖率",
      unit: "%",
      value: 100,
    },
  ],
  provenance: {
    type: "system_interpretation",
    owned: true,
    batchId: "own-fire",
    taskId: "11111111-1111-4111-8111-111111111111",
    workflowId: null,
    creator: "本人",
    createdAt: "2026-11-14T00:00:00Z",
  },
  observation: {
    product: "gwis_ba",
    unit: "ha",
    periodMode: "8day",
    activeCells: 6,
    validCells: 6,
    gridCells: 6,
    grid: {
      width: 3,
      height: 2,
      transform: [112, 0.25, 0, -10, 0, -0.25],
      crs: "EPSG:4326",
    },
    legend: [],
    series: [
      {
        observedStart: "2019-12-19",
        observedEnd: "2019-12-26",
        value: null,
        unit: "ha",
        validCells: 0,
        activeCells: 0,
      },
      {
        observedStart: "2019-12-27",
        observedEnd: "2019-12-31",
        value: 180,
        unit: "ha",
        validCells: 6,
        activeCells: 6,
      },
    ],
  },
  attachments: [
    { role: "classification", resource: resource(2011, "观测分级") },
  ],
} as MonitoringProduct;
const data: MonitoringProductList = {
  projectId: 13,
  scene: "wildfire",
  title: "野火观测",
  route: ["核对时期", "观测制图"],
  items: [product],
  nextBeforeId: null,
  inputResources: [cube],
  businessFlow: {
    definitionId: 2,
    versionId: 21,
    title: "野火历史观测制图",
    goal: "生成真实观测图",
  },
};
const config = {
  title: "野火监测",
  source: "remote_sensing_products" as const,
  scenes: ["wildfire" as const],
  initialView: {
    center: [130, -25] as [number, number],
    zoom: 0.3,
    regionZoom: 4,
  },
};
function show() {
  return render(
    <App>
      <MemoryRouter>
        <WildfireDashboard projectId={13} config={config} navigation={null} />
      </MemoryRouter>
    </App>,
  );
}
beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
  setActiveProject("13");
  state.catalog = structuredClone(catalog);
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
        inputRequirements: [
          {
            key: "cube",
            label: "原生立方体",
            description: "Zarr时空数据",
            dataTypes: ["raster" as const],
            required: true,
            requiredFields: [],
            multiple: false,
          },
        ],
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
  setActiveProject("1");
  sessionStorage.clear();
});

it("shows physical observation and a real dated series without synthetic risk", async () => {
  const view = show();
  await screen.findByText("180");
  expect(view.container.querySelectorAll(".monitor-panel")).toHaveLength(6);
  for (const name of [
    "时期与观测源",
    "火烧面积概况",
    "区域观测序列",
    "区域制图任务",
    "数据与模型资料",
    "成果说明",
  ])
    expect(screen.getByRole("region", { name })).toBeInTheDocument();
  expect(
    screen.getByRole("img", { name: "研究区观测序列" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("区域综合风险指数")).not.toBeInTheDocument();
  await waitFor(
    () =>
      expect(screen.getByTestId("observation-map")).toHaveTextContent("2011"),
    { timeout: 10000 },
  );
  fireEvent.click(screen.getByText("观测原值", { exact: true }));
  await waitFor(() =>
    expect(screen.getByTestId("observation-map")).toHaveTextContent("2010"),
  );
  expect(businessFlowsApi.start).not.toHaveBeenCalled();
});

it("launches one native cube run with the real source index and region", async () => {
  show();
  const start = await screen.findByRole("button", {
    name: "生成观测图",
    exact: true,
  });
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(screen.getByText("经纬度范围", { exact: true }));
  for (const [label, value] of [
    ["西界", 112],
    ["南界", -44],
    ["东界", 154],
    ["北界", -10],
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
      inputs: { cube: 1475 },
      goal: expect.stringContaining("所选时期：2026-12-27 — 2026-12-31"),
      parameters: {
        nodeParameters: {
          interpret: {
            product: "gwis_ba",
            time_index: 2000,
            history: 12,
            west: 112,
            south: -44,
            east: 154,
            north: -10,
          },
        },
      },
    }),
  );
});
