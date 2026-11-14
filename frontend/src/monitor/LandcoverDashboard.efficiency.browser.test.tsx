import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type {
  MonitoringProductList,
  MonitoringProduct,
  ResourceListItem,
} from "../api/generated/types.gen";
import { api } from "../api/client";
import {
  monitorResourceProfile,
  clearMonitorResourceProfiles,
} from "./resourceProfiles";
import { businessFlowsApi } from "../api/businessFlows";
import {
  businessFlowRun,
  directInputPlan,
  researchDetail,
} from "../businessflows/businessFlow.testFixtures";
import { setActiveProject } from "../projects/session";
import { getMonitoringProducts } from "./productApi";
import LandcoverDashboard from "./LandcoverDashboard";

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
vi.mock("../utils/download", () => ({ downloadBlob: vi.fn() }));
vi.mock("./productApi", () => ({ getMonitoringProducts: vi.fn() }));
vi.mock("./LandcoverComparisonMap", () => ({
  default: ({
    mode,
    visibleCodes,
  }: {
    mode: string;
    visibleCodes: number[];
  }) => (
    <output data-testid="map-state">
      {JSON.stringify({ mode, visibleCodes })}
    </output>
  ),
}));

const config = {
  title: "中石油管道 · 地表覆盖解译",
  source: "remote_sensing_products" as const,
  scenes: ["landcover" as const],
  initialView: { center: [107, 36], zoom: 0.3, regionZoom: 10 },
};
const source = {
  id: 1455,
  projectTagId: 2,
  name: "样区01原始RGB",
  dataType: "raster",
  updatedAt: "2026-11-14T00:00:00Z",
} as ResourceListItem;
const product = {
  id: 10,
  name: "样区01完整解译",
  scene: "landcover",
  registeredAt: "2026-11-14T00:00:00Z",
  resourceId: 1500,
  metrics: [
    { key: "valid_area_km2", value: 1, label: "有效面积", unit: "km²" },
  ],
  sourceResourceIds: [1455],
  statistics: { valid_area_km2: 1 },
  model: { name: "UNet", variant: "完整六类", version: "1.0.0" },
  classification: {
    mode: "complete",
    priority: ["建筑", "水体", "耕地", "林地", "道路"],
    categories: [
      {
        code: 6,
        name: "建筑",
        color: "#FFB9B9",
        areaKm2: 1,
        percent: 100,
        pixelCount: 250000,
      },
    ],
    models: [],
  },
} as unknown as MonitoringProduct;
const list: MonitoringProductList = {
  projectId: 2,
  scene: "landcover",
  title: "地表覆盖",
  route: [],
  items: [product],
  nextBeforeId: null,
  inputResources: [source],
  businessFlow: {
    definitionId: 2,
    versionId: 21,
    title: "地表覆盖",
    goal: "解译所选样区",
  },
};
const current = (
  status: "queued" | "waiting_approval" | "succeeded" = "queued",
) => businessFlowRun({ projectId: 2, status, name: "样区01解译" });
function Location() {
  const value = useLocation();
  return <output aria-label="导航位置">{value.pathname + value.search}</output>;
}
function show() {
  return render(
    <App>
      <MemoryRouter>
        <LandcoverDashboard config={config} navigation={null} projectId={2} />
        <Location />
      </MemoryRouter>
    </App>,
  );
}

beforeEach(() => {
  clearMonitorResourceProfiles();
  vi.restoreAllMocks();
  sessionStorage.clear();
  setActiveProject("2");
  vi.mocked(getMonitoringProducts).mockReset().mockResolvedValue(list);
  vi.spyOn(businessFlowsApi, "runs").mockResolvedValue({ items: [] });
  vi.spyOn(businessFlowsApi, "detail").mockResolvedValue({
    ...researchDetail,
    versions: researchDetail.versions.map((version) => ({
      ...version,
      definition: {
        ...version.definition,
        inputRequirements: [
          {
            key: "image",
            label: "原始RGB影像",
            description: "原始影像",
            dataTypes: ["raster"],
            required: true,
            requiredFields: [],
            multiple: true,
          },
        ],
      },
    })),
  });
  vi.spyOn(businessFlowsApi, "prepareInputs").mockImplementation(
    async (_id, request) => directInputPlan(request),
  );
  vi.spyOn(businessFlowsApi, "start").mockResolvedValue(
    current("waiting_approval"),
  );
  vi.spyOn(businessFlowsApi, "run").mockResolvedValue(
    current("waiting_approval"),
  );
});
afterEach(() => {
  setActiveProject("1");
  sessionStorage.clear();
});

it("uses the six-card dashboard and submits the preselected source through the existing flow exactly once", async () => {
  const view = show();
  await screen.findByText("类型面积");
  expect(view.container.querySelectorAll(".monitor-panel")).toHaveLength(6);
  fireEvent.click(await screen.findByRole("checkbox", { name: "建筑" }));
  expect((await screen.findByTestId("map-state")).textContent).not.toContain(
    "6",
  );
  expect(businessFlowsApi.start).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "开始解译" }));
  await screen.findByRole("region", { name: "业务流启动准备" });
  expect(
    await within(
      screen.getByRole("region", { name: "业务流启动准备" }),
    ).findByText("样区01原始RGB"),
  ).toBeInTheDocument();
  const submit = await screen.findByRole("button", {
    name: "开始业务流",
  });
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);
  fireEvent.click(submit);
  await screen.findByRole("button", { name: "在智能体中打开" });
  expect(businessFlowsApi.start).toHaveBeenCalledOnce();
  expect(businessFlowsApi.start).toHaveBeenCalledWith(
    2,
    expect.objectContaining({
      inputs: { "image:1455": 1455 },
      parameters: { nodeParameters: { interpret: { classes: "all" } } },
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "在智能体中打开" }));
  expect(screen.getByLabelText("导航位置")).toHaveTextContent(
    "/agent/workbench?projectTagId=2&conversationId=31&runId=41",
  );
});

it("shares one task read between the card and drawer and refreshes products once on completion", async () => {
  sessionStorage.setItem("monitor-task:99:2:landcover", current().id);
  vi.mocked(businessFlowsApi.run)
    .mockResolvedValueOnce(current())
    .mockResolvedValue(current("succeeded"));
  show();
  await screen.findAllByRole("button", { name: "查看任务" });
  fireEvent.click(screen.getAllByRole("button", { name: "查看任务" })[0]!);
  await screen.findByRole("button", { name: "在智能体中打开" });
  expect(businessFlowsApi.run).toHaveBeenCalledOnce();
  await waitFor(() => expect(businessFlowsApi.run).toHaveBeenCalledTimes(2), {
    timeout: 4000,
  });
  await waitFor(() => expect(getMonitoringProducts).toHaveBeenCalledTimes(2));
  await new Promise((resolve) => setTimeout(resolve, 2300));
  expect(businessFlowsApi.run).toHaveBeenCalledTimes(2);
  expect(getMonitoringProducts).toHaveBeenCalledTimes(2);
});

it("shows RGB and disables classification for a region without a product", async () => {
  vi.mocked(getMonitoringProducts).mockResolvedValue({
    ...list,
    inputResources: [
      source,
      { ...source, id: 1460, name: "环江油田_RGB原始影像_06_综合地表" },
    ],
  });
  show();
  const region = await screen.findByRole("combobox", { name: "选择解译样区" });
  fireEvent.mouseDown(region);
  fireEvent.click(
    await screen.findByText("06_综合地表", {
      selector: ".ant-select-item-option-content",
    }),
  );
  await waitFor(() =>
    expect(screen.getByTestId("map-state")).toHaveTextContent(
      '"mode":"original"',
    ),
  );
  expect(
    screen.getByRole("radio", { name: "分类", exact: true }),
  ).toBeDisabled();
  expect(
    screen.getByRole("radio", { name: "叠加", exact: true }),
  ).toBeDisabled();
  expect(
    screen.getByRole("radio", { name: "卷帘", exact: true }),
  ).toBeDisabled();
  expect(businessFlowsApi.start).not.toHaveBeenCalled();
});

it("opens the current user's batch instead of another user's newer result", async () => {
  const own = {
    ...product,
    id: 20,
    provenance: {
      type: "system_interpretation" as const,
      batchId: "own-batch",
      taskId: "own-task",
      workflowId: null,
      creator: "本人",
      createdAt: product.registeredAt,
      owned: true,
    },
  };
  const foreign = {
    ...product,
    id: 30,
    sourceResourceIds: [1460],
    name: "另一人的最新成果",
    provenance: {
      ...own.provenance,
      batchId: "other-batch",
      taskId: "other-task",
      creator: "其他人",
      owned: false,
    },
  };
  vi.mocked(getMonitoringProducts).mockResolvedValue({
    ...list,
    items: [foreign, own],
    inputResources: [
      source,
      { ...source, id: 1460, name: "环江油田_RGB原始影像_06_综合地表" },
    ],
  });
  show();
  await screen.findByRole("checkbox", { name: "建筑" });
  expect(
    screen
      .getByRole("combobox", { name: "选择解译样区" })
      .closest(".ant-select"),
  ).toHaveTextContent("样区01原始RGB");
  expect(screen.queryByText("另一人的最新成果")).not.toBeInTheDocument();
  expect(
    screen.getByText("批次 own-batc", {
      selector: ".monitor-product-identity > span",
    }),
  ).toBeVisible();
});

it("exports the registered raster dataset and reuses the map metadata", async () => {
  const registered = { ...source, id: 1500, name: product.name };
  const ready = { ...product, resource: registered };
  vi.mocked(getMonitoringProducts).mockResolvedValue({
    ...list,
    items: [ready],
  });
  vi.spyOn(api, "resourceProfile").mockResolvedValue({
    resource: registered,
    raster: { id: 495 },
  } as Awaited<ReturnType<typeof api.resourceProfile>>);
  vi.spyOn(api, "exportLayers").mockResolvedValue({
    blob: new Blob(["result"]),
    filename: "classification.zip",
  });
  await monitorResourceProfile(registered);
  show();
  fireEvent.click(
    await screen.findByRole("button", { name: "下载成果", exact: true }),
  );
  await waitFor(() => expect(api.exportLayers).toHaveBeenCalledTimes(1));
  expect(api.exportLayers).toHaveBeenCalledWith({
    reproject: false,
    clip: false,
    items: [
      {
        layerType: "raster",
        datasetId: 495,
        resourceId: 1500,
        name: product.name,
      },
    ],
  });
  expect(api.resourceProfile).toHaveBeenCalledTimes(1);
});
