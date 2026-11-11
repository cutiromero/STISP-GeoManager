import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { api } from "../api/client";
import { createMockMonitorSource } from "../monitor/mockSource";
import { monitorPath } from "../monitor/project";
import { averageReadings } from "../monitor/state";
import { installMonitorMapboxMock } from "../monitor/test/monitorMapbox";
import type { MonitorDataSource, MonitorEvent } from "../monitor/types";
import type {
  ProjectTag,
  ProjectMonitorConfig,
} from "../api/generated/types.gen";
import EcologyMonitorPage, {
  EcologyMonitorDashboard,
} from "./EcologyMonitorPage";
import ResultsPage from "./ResultsPage";

const monitorConfig = vi.hoisted(
  () =>
    ({
      title: "塔里木河流域胡杨林生态监测",
      source: "tarim_poplar_mock",
      initialView: { center: [84, 39.9], zoom: 2.05, regionZoom: 5.15 },
    }) satisfies ProjectMonitorConfig,
);
const project = vi.hoisted(() => ({
  current: "6",
  projects: [] as ProjectTag[],
}));

function enabledProject(): ProjectTag {
  return {
    id: 6,
    code: "05",
    name: "塔大胡杨",
    description: "",
    isDefault: false,
    isActive: true,
    sortOrder: 1,
    enabledFeatures: ["ecology_monitor"],
    configuredFeatures: ["ecology_monitor"],
    monitorConfig,
  };
}
let mapState: ReturnType<typeof installMonitorMapboxMock> = {
  maps: [],
  points: [] as HTMLButtonElement[],
};
let reducedMotion = false;
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => project,
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({
    user: {
      permissions: {
        canViewMapCompositions: true,
        canViewResultArtifacts: true,
      },
    },
    bootstrap: { map: { mapboxAccessToken: "", defaultBasemap: "osm" } },
  }),
}));
vi.mock("../components/WorkspaceHeader", () => ({
  default: () => <header>STISP</header>,
}));
vi.mock("./ResearchDemoShowcase", () => ({ default: () => null }));
const originalMatchMedia = window.matchMedia.bind(window);
beforeEach(() => {
  vi.restoreAllMocks();
  mapState = installMonitorMapboxMock();
  reducedMotion = false;
  project.current = "6";
  project.projects = [enabledProject()];
  vi.spyOn(api, "mapCompositions").mockResolvedValue({
    items: [],
    availableAudienceGroups: [],
  });
  vi.spyOn(api, "resultArtifacts").mockResolvedValue({
    items: [],
    availableAccessGroups: [],
  });
  vi.spyOn(window, "matchMedia").mockImplementation((query) => {
    const media = originalMatchMedia(query);
    if (query === "(prefers-reduced-motion: reduce)")
      Object.defineProperty(media, "matches", { value: reducedMotion });
    return media;
  });
});
afterEach(() => {
  vi.useRealTimers();
});

function renderResults() {
  return render(resultsView());
}

function resultsView() {
  return (
    <ConfigProvider locale={zhCN}>
      <AntApp>
        <MemoryRouter initialEntries={["/results"]}>
          <Routes>
            <Route path="/results" element={<ResultsPage />} />
            <Route path={monitorPath} element={<EcologyMonitorPage />} />
          </Routes>
        </MemoryRouter>
      </AntApp>
    </ConfigProvider>
  );
}

async function controlledSource() {
  const initial = await createMockMonitorSource({
    now: () => Date.parse("2026-11-10T08:00:00Z"),
  }).getSnapshot();
  let listener: ((event: MonitorEvent) => void) | undefined;
  const unsubscribe = vi.fn();
  const source: MonitorDataSource = {
    getSnapshot: async () => initial,
    subscribe: (callback) => {
      listener = callback;
      return unsubscribe;
    },
  };
  const station = {
    ...initial.stations[9]!,
    risk: 88,
    readings: { ...initial.stations[9]!.readings, groundwater: 8.9 },
    recentEvent: "新模拟观测",
  };
  const event: MonitorEvent = {
    sequence: 1,
    occurredAt: "2026-11-10T08:00:04Z",
    station,
    sample: {
      id: "new",
      observedAt: "2026-11-10T08:00:04Z",
      readings: averageReadings(
        initial.stations.map((entry) =>
          entry.id === station.id ? station : entry,
        ),
      ),
    },
    alertChange: {
      kind: "raised",
      alert: {
        id: "test-alert",
        stationId: station.id,
        occurredAt: "2026-11-10T08:00:04Z",
        metric: "groundwater",
        level: "critical",
        message: "测试预警已汇入",
      },
    },
    assessment: { ...initial.assessment, summary: "模拟态势已更新" },
  };
  return { source, unsubscribe, event, emit: () => listener?.(event) };
}

it("入口依据后端功能清单而非项目代码，并可进入独立大屏", async () => {
  const view = renderResults();
  fireEvent.click(await screen.findByRole("button", { name: /进入监测大屏$/ }));
  await screen.findByRole("heading", { name: "塔里木河流域胡杨林生态监测" });
  expect(screen.queryByText("STISP")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /返回成果$/ }));
  await screen.findByRole("button", { name: /进入监测大屏$/ });
  view.unmount();
  for (const code of ["default", "03", "other"]) {
    project.projects = [{ ...enabledProject(), code, enabledFeatures: [] }];
    const other = renderResults();
    await screen.findByRole("heading", { name: "成果展示" });
    expect(
      screen.queryByRole("button", { name: /进入监测大屏$/ }),
    ).not.toBeInTheDocument();
    other.unmount();
  }
  project.projects = [{ ...enabledProject(), isActive: false }];
  const inactive = renderResults();
  expect(
    screen.queryByRole("button", { name: /进入监测大屏$/ }),
  ).not.toBeInTheDocument();
  inactive.unmount();
});

it("其他代码项目可开启，配置标题与初始视角生效，切换后不沿用旧内容", async () => {
  const config: ProjectMonitorConfig = {
    ...monitorConfig,
    title: "项目甲独立监测",
    initialView: { center: [102, 30], zoom: 3, regionZoom: 6 },
  };
  project.projects = [
    { ...enabledProject(), code: "independent", monitorConfig: config },
    {
      ...enabledProject(),
      id: 7,
      code: "unconfigured",
      name: "项目乙",
      monitorConfig: null,
    },
    {
      ...enabledProject(),
      id: 8,
      code: "disabled",
      name: "项目丙",
      enabledFeatures: [],
      monitorConfig: null,
    },
  ];
  const view = renderResults();
  fireEvent.click(await screen.findByRole("button", { name: /进入监测大屏$/ }));
  await screen.findByRole("heading", { name: config.title });
  await waitFor(() => expect(mapState.maps).toHaveLength(1));
  expect(mapState.maps[0]!.options.center).toEqual([102, 30]);
  expect(mapState.maps[0]!.options.zoom).toBeLessThanOrEqual(3);
  project.current = "7";
  view.rerender(resultsView());
  await screen.findByText("尚未配置监测内容");
  expect(
    screen.queryByRole("heading", { name: config.title }),
  ).not.toBeInTheDocument();
  expect(mapState.maps[0]!.api.remove).toHaveBeenCalledOnce();
  expect(mapState.maps).toHaveLength(1);
  project.current = "8";
  view.rerender(resultsView());
  await screen.findByText("当前项目尚未开启监测大屏");
  project.current = "6";
  view.rerender(resultsView());
  await screen.findByRole("heading", { name: config.title });
  await waitFor(() => expect(mapState.maps).toHaveLength(2));
  project.projects[0]!.enabledFeatures = [];
  view.rerender(resultsView());
  await screen.findByText("当前项目尚未开启监测大屏");
  expect(mapState.maps[1]!.api.remove).toHaveBeenCalledOnce();
});

it("已开启未配置项目显示入口和空状态，不创建地图或塔大胡杨数据源", async () => {
  project.projects[0]!.monitorConfig = null;
  const view = renderResults();
  fireEvent.click(await screen.findByRole("button", { name: /进入监测大屏$/ }));
  await screen.findByText("尚未配置监测内容");
  expect(
    screen.queryByText("塔里木河流域胡杨林生态监测"),
  ).not.toBeInTheDocument();
  expect(mapState.maps).toHaveLength(0);
  view.unmount();
});

it("未开启项目直接访问大屏明确提示并可返回成果页", async () => {
  project.projects[0]!.enabledFeatures = [];
  render(
    <AntApp>
      <MemoryRouter initialEntries={[monitorPath]}>
        <Routes>
          <Route path={monitorPath} element={<EcologyMonitorPage />} />
          <Route path="/results" element={<div>成果页占位</div>} />
        </Routes>
      </MemoryRouter>
    </AntApp>,
  );
  await screen.findByText("当前项目尚未开启监测大屏");
  expect(mapState.maps).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: /返回成果$/ }));
  await screen.findByText("成果页占位");
});

it("渲染全部窗口，事件更新数字、预警与研判，地图点位可点击且离开后释放资源", async () => {
  const control = await controlledSource();
  const view = render(
    <AntApp>
      <MemoryRouter>
        <EcologyMonitorDashboard
          source={control.source}
          config={monitorConfig}
        />
      </MemoryRouter>
    </AntApp>,
  );
  for (const name of [
    "区域综合风险指数",
    "关键生态指标",
    "生态指标动态趋势",
    "生态预警动态",
    "高风险区段排行",
    "智能体态势研判",
  ])
    expect(await screen.findByRole("region", { name })).toBeInTheDocument();
  await waitFor(() => expect(mapState.points).toHaveLength(13));
  expect(screen.queryByText(/底图暂不可用/)).not.toBeInTheDocument();
  expect(mapState.maps[0]!.api.setLanguage).toHaveBeenCalledWith("zh-Hans");
  expect(mapState.maps[0]!.options.projection).toBe("globe");
  const before = screen.getByTestId("metric-groundwater").textContent;
  act(control.emit);
  expect(screen.getByTestId("event-count")).toHaveTextContent("1");
  expect(screen.getByTestId("active-alert-count")).toHaveTextContent("5");
  expect(screen.getByTestId("metric-groundwater").textContent).not.toBe(before);
  expect(screen.getByText(/测试预警已汇入/)).toBeInTheDocument();
  expect(screen.getByText("模拟态势已更新")).toBeInTheDocument();
  fireEvent.click(
    within(screen.getByLabelText("塔里木河流域监测地球")).getByRole("button", { name: "英苏河段", exact: true }),
  );
  const details = screen.getByRole("complementary", { name: "点位详情" });
  expect(
    within(details).getByRole("heading", { name: "英苏河段" }),
  ).toBeInTheDocument();
  expect(details).toHaveTextContent("8.90");
  expect(details).toHaveTextContent("新模拟观测");
  fireEvent.click(screen.getByRole("button", { name: /生成报告$/ }));
  expect(await screen.findByText("功能建设中")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "关闭点位详情" }));
  view.unmount();
  expect(control.unsubscribe).toHaveBeenCalledOnce();
  expect(mapState.maps[0]!.api.remove).toHaveBeenCalledOnce();
  expect(mapState.points.every((point) => !point.isConnected)).toBe(true);
});

it("减少动态效果时不自转、不自动滚动，新事件仍正常更新", async () => {
  reducedMotion = true;
  const scroll = vi.spyOn(Element.prototype, "scrollTo");
  const control = await controlledSource();
  render(
    <AntApp>
      <MemoryRouter>
        <EcologyMonitorDashboard
          source={control.source}
          config={monitorConfig}
        />
      </MemoryRouter>
    </AntApp>,
  );
  const list = await screen.findByTestId("monitor-alert-list");
  await waitFor(() => expect(mapState.points).toHaveLength(13));
  expect(list).toHaveAttribute("data-auto-scroll", "false");
  act(control.emit);
  await new Promise((resolve) => setTimeout(resolve, 80));
  expect(scroll).not.toHaveBeenCalled();
  expect(mapState.maps[0]!.api.setCenter).not.toHaveBeenCalled();
  expect(mapState.maps[0]!.api.stop).toHaveBeenCalled();
  expect(screen.getByTestId("event-count")).toHaveTextContent("1");
  expect(screen.getByText("已遵循系统设置：减少动态效果")).toBeInTheDocument();
});

it("鼠标悬停地球暂停自转，背景继续运动，移开后恢复", async () => {
  const control = await controlledSource();
  const view = render(
    <AntApp>
      <MemoryRouter>
        <EcologyMonitorDashboard
          source={control.source}
          config={monitorConfig}
        />
      </MemoryRouter>
    </AntApp>,
  );
  await waitFor(() => expect(mapState.maps).toHaveLength(1));
  const map = mapState.maps[0]!.api;
  await waitFor(() => expect(map.setCenter).toHaveBeenCalled());
  const globe = screen.getByLabelText("塔里木河流域监测地球");
  const bounds = globe.getBoundingClientRect();
  fireEvent.pointerMove(globe, {
    clientX: bounds.left + bounds.width / 2,
    clientY: bounds.top + bounds.height / 2,
  });
  map.setCenter.mockClear();
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(map.setCenter).not.toHaveBeenCalled();
  expect(map.isPointOnSurface).toHaveBeenCalled();
  expect(
    getComputedStyle(
      document.querySelector(".monitor-space-background")!,
      "::before",
    ).animationPlayState,
  ).toBe("running");
  expect(
    getComputedStyle(document.querySelector(".monitor-space-stars")!)
      .animationPlayState,
  ).toBe("running");
  fireEvent.pointerLeave(globe);
  await waitFor(() => expect(map.setCenter).toHaveBeenCalled());
  view.unmount();
});

it("全球视角保留点位和连线，点击监测区可聚焦，头部保持紧凑", async () => {
  const control = await controlledSource();
  render(<AntApp><MemoryRouter><EcologyMonitorDashboard source={control.source} config={monitorConfig} /></MemoryRouter></AntApp>);
  const overview = await screen.findByRole("button", { name: "查看研究区监测点位" });
  expect(overview).toHaveTextContent("12 处");
  const point = mapState.points.find(point => point.classList.contains("monitor-map-point"))!;
  expect(getComputedStyle(point).display).not.toBe("none");
  const map = mapState.maps[0]!;
  act(() => map.emit("zoomend"));
  expect(map.api.setLayoutProperty).not.toHaveBeenCalledWith("monitor-links", "visibility", "none");
  expect(document.querySelector(".monitor-topbar")!.getBoundingClientRect().height).toBeLessThan(80);
  expect(screen.queryByRole("button", { name: "选择监测点位" })).toBeNull();
  const global = screen.getByRole("button", { name: "全球视角", exact: true });
  expect(global.textContent).toBe("");
  fireEvent.mouseOver(global);
  const tooltip = await screen.findByRole("tooltip", { name: "全球视角" });
  await waitFor(() => expect(tooltip).toBeVisible());
  fireEvent.click(overview);
  expect(map.api.flyTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: monitorConfig.initialView.regionZoom }));
});

it("地图外点击不会暂停地球，背景有位移与星光动态", async () => {
  const control = await controlledSource();
  render(<AntApp><MemoryRouter><EcologyMonitorDashboard source={control.source} config={monitorConfig} /></MemoryRouter></AntApp>);
  await waitFor(() => expect(mapState.maps[0]?.api.setCenter).toHaveBeenCalled());
  const map = mapState.maps[0]!.api;
  fireEvent.pointerUp(document.body);
  map.setCenter.mockClear();
  await waitFor(() => expect(map.setCenter).toHaveBeenCalled());
  expect(getComputedStyle(document.querySelector(".monitor-space-star")!).animationName).toBe("monitor-star-shimmer");
  fireEvent.click(screen.getByRole("button", { name: "暂停动效" }));
  expect(document.querySelector(".ecology-monitor")).toHaveAttribute("data-motion", "paused");
  fireEvent.click(screen.getByRole("button", { name: "启动动效" }));
  expect(document.querySelector(".ecology-monitor")).toHaveAttribute("data-motion", "running");
});

it("移出地球不会抢断切回全球视角的镜头动画，动画结束后恢复自转", async () => {
  const control = await controlledSource();
  render(<AntApp><MemoryRouter><EcologyMonitorDashboard source={control.source} config={monitorConfig} /></MemoryRouter></AntApp>);
  await waitFor(() => expect(mapState.maps[0]?.api.setCenter).toHaveBeenCalled());
  const map = mapState.maps[0]!.api;
  fireEvent.click(screen.getByRole("button", { name: /全球视角$/ }));
  fireEvent.pointerLeave(screen.getByLabelText("塔里木河流域监测地球"));
  map.setCenter.mockClear();
  await new Promise(resolve => setTimeout(resolve, 100));
  expect(map.setCenter).not.toHaveBeenCalled();
  await waitFor(() => expect(map.setCenter).toHaveBeenCalled(), { timeout: 2500 });
});

it("减少动态设置下可由用户明确启动演示动效", async () => {
  reducedMotion = true;
  const control = await controlledSource();
  render(<AntApp><MemoryRouter><EcologyMonitorDashboard source={control.source} config={monitorConfig} /></MemoryRouter></AntApp>);
  await screen.findByRole("button", { name: "启动动效" });
  fireEvent.click(screen.getByRole("button", { name: "启动动效" }));
  await waitFor(() => expect(mapState.maps[0]?.api.setCenter).toHaveBeenCalled());
});

it("列表悬停和键盘聚焦暂停滚动，页面隐藏停止模拟产出并在恢复后继续", async () => {
  const source = createMockMonitorSource({ intervalMs: 100 });
  const view = render(
    <AntApp>
      <MemoryRouter>
        <EcologyMonitorDashboard source={source} config={monitorConfig} />
      </MemoryRouter>
    </AntApp>,
  );
  const list = await screen.findByTestId("monitor-alert-list");
  fireEvent.mouseEnter(list);
  expect(list).toHaveAttribute("data-auto-scroll", "false");
  fireEvent.mouseLeave(list);
  expect(list).toHaveAttribute("data-auto-scroll", "true");
  fireEvent.focus(within(list).getAllByRole("button")[0]!);
  expect(list).toHaveAttribute("data-auto-scroll", "false");
  const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  const sequence = (await source.getSnapshot()).sequence;
  await new Promise((resolve) => setTimeout(resolve, 250));
  expect((await source.getSnapshot()).sequence).toBe(sequence);
  expect(screen.getByText("页面隐藏 · 数据流已暂停")).toBeInTheDocument();
  hidden.mockReturnValue(false);
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  await waitFor(async () =>
    expect((await source.getSnapshot()).sequence).toBeGreaterThan(sequence),
  );
  view.unmount();
});

it("目标分辨率和窄屏无横向溢出", async () => {
  const control = await controlledSource();
  render(
    <AntApp>
      <MemoryRouter>
        <EcologyMonitorDashboard
          source={control.source}
          config={monitorConfig}
        />
      </MemoryRouter>
    </AntApp>,
  );
  await screen.findByTestId("monitor-alert-list");
  for (const [width, height] of [
    [1920, 1080],
    [1710, 835],
    [1366, 768],
    [2560, 1440],
    [390, 844],
  ]) {
    await page.viewport(width!, height!);
    const root = document.querySelector<HTMLElement>(".ecology-monitor")!;
    expect(root.scrollWidth).toBeLessThanOrEqual(root.clientWidth + 1);
    for (const panel of root.querySelectorAll<HTMLElement>(".monitor-panel"))
      expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
    const map = root.querySelector<HTMLElement>(".monitor-map")!;
    expect(getComputedStyle(map).position).toBe("absolute");
    expect(map.clientHeight).toBeGreaterThan(250);
    const metrics = root.querySelector<HTMLElement>(".monitor-metrics")!;
    expect(metrics.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      metrics.closest(".monitor-panel")!.getBoundingClientRect().bottom,
    );
    for (const number of root.querySelectorAll<HTMLElement>(".monitor-number"))
      expect(number.getBoundingClientRect().height).toBeGreaterThanOrEqual(
        Number.parseFloat(getComputedStyle(number).fontSize),
      );
  }
  await page.viewport(1920, 1080);
  await page.screenshot({ path: "ecology-monitor-desktop.png" });
});
