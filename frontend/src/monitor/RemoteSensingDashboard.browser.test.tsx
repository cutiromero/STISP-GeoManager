import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import type {
  DataResource,
  MonitoringProduct,
  MonitoringProductList,
  ResourceProfileResponse,
} from "../api/generated/types.gen";
import { api } from "../api/client";
import EcologyMonitorPage from "../pages/EcologyMonitorPage";
import { getMonitoringProducts } from "./productApi";
import { createMonitorSource } from "./source";
import { installMonitorMapboxMock } from "./test/monitorMapbox";
import { setActiveProject } from "../projects/session";
import { cloneDefaultRasterSymbolization } from "../symbolization";

const context = vi.hoisted(() => ({
  current: "17",
  projects: [] as import("../api/generated/types.gen").ProjectTag[],
}));
const app = vi.hoisted(() => ({
  bootstrap: { map: { mapboxAccessToken: "", defaultBasemap: "osm" } },
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => context,
}));
vi.mock("../contexts/AppContext", () => ({ useAppContext: () => app }));
vi.mock("./productApi", () => ({ getMonitoringProducts: vi.fn() }));
vi.mock("./source", () => ({ createMonitorSource: vi.fn() }));

let maps: ReturnType<typeof installMonitorMapboxMock>;
beforeEach(() => {
  vi.restoreAllMocks();
  maps = installMonitorMapboxMock();
  context.current = "17";
  setActiveProject("17");
  context.projects = [
    {
      id: 17,
      code: "rs-test",
      name: "遥感项目",
      description: "",
      isDefault: false,
      isActive: true,
      sortOrder: 1,
      enabledFeatures: ["ecology_monitor"],
      monitorConfig: {
        title: "生态遥感监测",
        source: "remote_sensing_products",
        scenes: ["spartina", "wildfire"],
        initialView: { center: [112, 32], zoom: 2.3, regionZoom: 5 },
      },
    },
  ];
  vi.mocked(getMonitoringProducts)
    .mockReset()
    .mockImplementation(async (scene) => list(scene));
  vi.mocked(createMonitorSource).mockClear();
  vi.spyOn(api, "resourceProfile").mockImplementation(async (resource) =>
    profile(resource),
  );
});
afterEach(() => setActiveProject("1"));

function resource(id = 101): DataResource {
  return {
    id,
    projectTagId: 17,
    name: `地图成果${id}`,
    code: `map-${id}`,
    dataType: "vector",
    spatialClass: "spatial",
    domainType: null,
    category: null,
    categoryPath: [],
    classificationStatus: "pending",
    availableViews: ["map", "table", "metadata"],
    defaultView: "map",
    source: "用户资料",
    provider: "",
    dataDate: null,
    spatialExtent: "",
    coordinateSystem: "EPSG:4326",
    fileFormat: "gpkg",
    description: "",
    qualityNote: "",
    sizeBytes: 100,
    itemCount: 12881,
    status: "active",
    isQueryable: true,
    isRenderable: false,
    updatedAt: "2026-11-13T10:00:00Z",
  };
}

function product(id = 1): MonitoringProduct {
  const data = resource(100 + id);
  return {
    schemaVersion: 1,
    id,
    code: `extent-${id}`,
    name: `历史分布${id}`,
    resourceId: data.id,
    scene: "spartina",
    kind: "historical",
    quality: "unverified",
    observedStart: null,
    observedEnd: null,
    sourceResourceIds: [data.id],
    sourceLabel: "用户提供的历史分布面",
    limitations: ["观测时间未核实，未提供精度验证"],
    interpretation: "展示已有成果，不声明当前分布变化",
    statistics: { patch_count: 12881 },
    statisticsMethod: "原始要素计数；尚未计算面积",
    model: null,
    threshold: null,
    timing: {
      inputThrough: null,
      validStart: null,
      validEnd: null,
      evidence: "原始数据没有日期字段",
    },
    resource: data,
    registeredAt: "2026-11-13T10:00:00Z",
    metrics: [
      { key: "area_ha", label: "分布面积", unit: "ha", value: null },
      { key: "patch_count", label: "斑块数量", unit: "个", value: 12881 },
    ],
  };
}

function list(
  scene: MonitoringProductList["scene"],
  items: MonitoringProduct[] = [],
): MonitoringProductList {
  return {
    projectId: 17,
    scene,
    title: scene === "spartina" ? "互花米草监测" : "野火风险研判",
    route: [
      "选区与资料",
      "输入准备",
      "模型识别",
      "斑块统计",
      "变化核验",
      "成果发布",
    ],
    items,
    nextBeforeId: null,
  };
}

function profile(data: DataResource): ResourceProfileResponse {
  return {
    resource: data,
    fields: [],
    featureCount: 12881,
    geometryType: "MultiPolygon",
    bounds: [109, 21, 122, 39],
    raster: null,
    defaultVisualization: {},
    vectorTiles: {
      revision: "verified",
      tileUrl: `/api/catalog/resources/${data.id}/vector-tiles/verified/{z}/{x}/{y}.pbf`,
      sourceLayer: "features",
      minZoom: 0,
      maxZoom: 10,
      bounds: [109, 21, 122, 39],
      clustered: false,
      featureCount: 12881,
    },
  };
}

function view() {
  return (
    <AntApp>
      <MemoryRouter initialEntries={["/results/ecology-monitor"]}>
        <Routes>
          <Route
            path="/results/ecology-monitor"
            element={<EcologyMonitorPage />}
          />
          <Route path="/business-flows" element={<div>业务流目录占位</div>} />
        </Routes>
      </MemoryRouter>
    </AntApp>
  );
}

it("真实场景空状态不创建胡杨模拟源、站点或概率", async () => {
  render(view());
  await screen.findByText("暂无监测成果");
  expect(createMonitorSource).not.toHaveBeenCalled();
  expect(api.resourceProfile).not.toHaveBeenCalled();
  expect(screen.getByText("数据接入中")).toBeInTheDocument();
  expect(screen.queryByText("模拟事件流")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "野火", exact: true }));
  await screen.findByText("0.25° 网格 · 8 天周期");
  expect(getMonitoringProducts).toHaveBeenLastCalledWith(
    "wildfire",
    expect.any(AbortSignal),
  );
});

it("历史分布保留未知时间和空面积，选择后才加载同一地图资源", async () => {
  vi.mocked(getMonitoringProducts).mockResolvedValue(
    list("spartina", [product()]),
  );
  render(view());
  await screen.findByText("12,881");
  expect(screen.getAllByText("日期待补充").length).toBeGreaterThan(0);
  expect(screen.getByText("原始要素计数；尚未计算面积")).toBeInTheDocument();
  await waitFor(() => expect(api.resourceProfile).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(maps.maps[0]?.sources.has("product")).toBe(true));
  expect(maps.maps[0]?.api.addSource).toHaveBeenCalledWith(
    "product",
    expect.objectContaining({
      type: "vector",
      tiles: [expect.stringContaining("/101/vector-tiles/")],
    }),
  );
  expect(maps.maps[0]?.api.fitBounds).not.toHaveBeenCalled();
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
    window.innerWidth,
  );
  expect(
    document
      .querySelector(".remote-product-map-canvas")!
      .getBoundingClientRect().height,
  ).toBeGreaterThan(300);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "聚焦研究区" }),
    ).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "聚焦研究区" }));
  expect(maps.maps[0]?.api.flyTo).toHaveBeenCalledWith(
    expect.objectContaining({ center: [112, 32], zoom: 5 }),
  );
  fireEvent.click(screen.getByRole("button", { name: "全域" }));
  expect(maps.maps[0]?.api.fitBounds).toHaveBeenCalledTimes(1);
  expect(api.resourceProfile).toHaveBeenCalledTimes(1);
  expect(
    document.querySelector(".monitor-layout > .monitor-globe-panel"),
  ).not.toBeNull();
  expect(
    document.querySelectorAll(".monitor-information > .monitor-panel"),
  ).toHaveLength(6);
  expect(document.querySelector(".remote-monitor-layout")).toBeNull();
  expect(
    document.querySelector(".monitor-assessment")!.getBoundingClientRect()
      .height,
  ).toBeGreaterThanOrEqual(108);
});

it("刷新保留选中成果，等值视角配置不重建地图或重复读取文件", async () => {
  vi.mocked(getMonitoringProducts).mockImplementation(async () =>
    structuredClone(list("spartina", [product(), product(2)])),
  );
  const rendered = render(view());
  await waitFor(() => expect(api.resourceProfile).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: /历史分布2/ }));
  await waitFor(() => expect(api.resourceProfile).toHaveBeenCalledTimes(2));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "聚焦研究区" }),
    ).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "聚焦研究区" }));
  const config = context.projects[0]!.monitorConfig!;
  context.projects[0]!.monitorConfig = structuredClone(config);
  app.bootstrap.map = { defaultBasemap: "osm", mapboxAccessToken: "" };
  rendered.rerender(view());
  expect(maps.maps).toHaveLength(1);
  expect(maps.maps[0]!.api.remove).not.toHaveBeenCalled();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /刷新成果/ })).not.toHaveClass(
      "ant-btn-loading",
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: /刷新成果/ }));
  await waitFor(() => expect(getMonitoringProducts).toHaveBeenCalledTimes(2));
  expect(screen.getByRole("button", { name: /历史分布2/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(api.resourceProfile).toHaveBeenCalledTimes(2);
  expect(maps.maps).toHaveLength(1);
});

it("长面积和斑块数在不同窗口内完整显示，数值与相邻指标及图例不重叠", async () => {
  const item = product();
  item.metrics[0]!.value = 17615.30043001679;
  vi.mocked(getMonitoringProducts).mockResolvedValue(list("spartina", [item]));
  render(view());
  await screen.findByText("12,881");
  try {
    for (const [width, height] of [
      [1920, 1080],
      [1495, 883],
      [1280, 720],
      [390, 844],
    ]) {
      await page.viewport(width!, height!);
      await waitFor(() => {
        for (const metric of document.querySelectorAll(".monitor-metric")) {
          const container = metric.getBoundingClientRect();
          for (const element of metric.querySelectorAll(
            ".monitor-number, small",
          )) {
            const box = element.getBoundingClientRect();
            expect(box.left).toBeGreaterThanOrEqual(container.left - 1);
            expect(box.right).toBeLessThanOrEqual(container.right + 1);
            expect(element.scrollWidth).toBeLessThanOrEqual(
              element.clientWidth + 1,
            );
          }
        }
        const gauge = document
          .querySelector(".monitor-product-gauge")!
          .getBoundingClientRect();
        const number = document
          .querySelector(".monitor-gauge-value .monitor-number")!
          .getBoundingClientRect();
        expect(number.width).toBeLessThanOrEqual(gauge.width * 0.7);
        expect(number.right).toBeLessThan(
          document
            .querySelector(".monitor-product-overview")!
            .getBoundingClientRect().left,
        );
      });
    }
  } finally {
    await page.viewport(1920, 1080);
  }
  expect(
    screen.getByRole("button", { name: "刷新成果", exact: true }),
  ).toBeInTheDocument();
});

it("切换场景后取消旧请求并忽略迟到产品", async () => {
  let resolveOld: (value: MonitoringProductList) => void = () => {};
  let oldSignal: AbortSignal | undefined;
  vi.mocked(getMonitoringProducts).mockImplementation((scene, signal) =>
    scene === "spartina"
      ? new Promise((resolve) => {
          resolveOld = resolve;
          oldSignal = signal;
        })
      : Promise.resolve(list(scene)),
  );
  render(view());
  fireEvent.click(
    await screen.findByRole("button", { name: "野火", exact: true }),
  );
  await screen.findByText("暂无监测成果");
  expect(oldSignal?.aborted).toBe(true);
  await act(async () => resolveOld(list("spartina", [product()])));
  expect(screen.queryByText("历史分布1")).not.toBeInTheDocument();
  expect(api.resourceProfile).not.toHaveBeenCalled();
});

it("产品切换期间的迟到profile不能重新装回旧图层", async () => {
  vi.mocked(getMonitoringProducts).mockResolvedValue(
    list("spartina", [product(), product(2)]),
  );
  let resolveOld: (value: ResourceProfileResponse) => void = () => {};
  vi.mocked(api.resourceProfile).mockImplementation((data) =>
    data.id === 101
      ? new Promise((resolve) => {
          resolveOld = resolve;
        })
      : Promise.resolve(profile(data)),
  );
  render(view());
  await waitFor(() => expect(api.resourceProfile).toHaveBeenCalledTimes(1));
  const loading = await screen.findByText("正在准备成果图层");
  const loadingBox = loading.getBoundingClientRect();
  const mapBox = document
    .querySelector(".monitor-globe-panel")!
    .getBoundingClientRect();
  expect(loading).toHaveAttribute("role", "status");
  expect(loadingBox.left).toBeCloseTo(mapBox.left + 12, 0);
  expect(loadingBox.top).toBeCloseTo(mapBox.top + 12, 0);
  expect(loadingBox.width).toBeLessThan(320);
  expect(loadingBox.height).toBeLessThan(36);
  expect(
    screen.queryByRole("button", { name: /暂停动效|启动动效/ }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /历史分布2/ }));
  await waitFor(() => expect(maps.maps[0]?.sources.has("product")).toBe(true));
  await act(async () => resolveOld(profile(resource(101))));
  expect(maps.maps[0]?.api.addSource).toHaveBeenCalledTimes(1);
  expect(maps.maps[0]?.api.addSource).toHaveBeenLastCalledWith(
    "product",
    expect.objectContaining({
      tiles: [expect.stringContaining("/102/vector-tiles/")],
    }),
  );
});

it("刷新权限失败后清除旧成果与统计", async () => {
  vi.mocked(getMonitoringProducts)
    .mockResolvedValueOnce(list("spartina", [product()]))
    .mockRejectedValue(new Error("来源资源权限已撤回"));
  render(view());
  await screen.findByText("12,881");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /刷新成果/ })).not.toHaveClass(
      "ant-btn-loading",
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: /刷新成果/ }));
  await screen.findByText("来源资源权限已撤回");
  expect(screen.queryByText("12,881")).not.toBeInTheDocument();
  expect(screen.queryByText("历史分布1")).not.toBeInTheDocument();
});

it("业务路线按钮只进入目录，不自动创建任务", async () => {
  render(view());
  await screen.findByText("暂无监测成果");
  fireEvent.click(screen.getByRole("button", { name: "进入业务流" }));
  await screen.findByText("业务流目录占位");
  expect(createMonitorSource).not.toHaveBeenCalled();
});

it("分类栅格使用服务器瓦片、实际图例和nearest采样", async () => {
  const item = product();
  item.resource = { ...item.resource, dataType: "raster", isRenderable: true };
  vi.mocked(getMonitoringProducts).mockResolvedValue(list("spartina", [item]));
  const rules = {
    ...cloneDefaultRasterSymbolization(),
    mode: "unique" as const,
    uniqueValues: [{ value: 1, label: "模型分类目标", color: "#18ad72" }],
  };
  const coordinates: [number, number][] = [
    [109, 39],
    [122, 39],
    [122, 21],
    [109, 21],
  ];
  vi.mocked(api.resourceProfile).mockResolvedValue({
    ...profile(item.resource),
    vectorTiles: null,
    raster: {
      id: 17,
      mapLayerId: 17,
      bandCount: 1,
      rasterKind: "categorical",
      defaultRules: rules,
      imageCoordinates: coordinates,
      metadata: {
        size: [50, 50],
        bands: [],
        driver: "GTiff",
        coordinateSystem: "EPSG:4326",
      },
    } as ResourceProfileResponse["raster"],
  });
  vi.spyOn(api, "renderRasterAsync").mockResolvedValue({
    id: "render17",
    kind: "render",
    status: "ready",
    messages: [],
    result: {
      delivery: "xyz",
      datasetId: 17,
      layerId: 17,
      styleHash: "server-style",
      tileUrl: "/api/raster/tiles/17/server-style/{z}/{x}/{y}.png",
      minZoom: 0,
      maxZoom: 8,
      tileSampling: "nearest",
      status: "ready",
      bounds4326: [109, 21, 122, 39],
      bounds3857: [],
      imageCoordinates: coordinates,
      rules,
    },
  } as Awaited<ReturnType<typeof api.renderRasterAsync>>);
  render(view());
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "聚焦研究区" }),
    ).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "聚焦研究区" }));
  await screen.findByText("模型分类目标");
  expect(api.renderRasterAsync).toHaveBeenCalledWith(
    { datasetId: 17, rulesMode: "default" },
    { signal: expect.any(AbortSignal) },
  );
  expect(maps.maps[0]?.api.addSource).toHaveBeenCalledWith(
    "product",
    expect.objectContaining({
      type: "raster",
      tiles: [expect.stringContaining("projectTagId=17")],
    }),
  );
  expect(maps.maps[0]?.api.addLayer).toHaveBeenCalledWith(
    expect.objectContaining({
      id: "product-raster",
      paint: expect.objectContaining({
        "raster-opacity": 1,
        "raster-resampling": "nearest",
        "raster-fade-duration": 0,
      }),
    }),
  );
});
