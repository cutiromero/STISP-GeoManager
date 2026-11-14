import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { App } from "antd";
import { beforeEach, expect, it, vi } from "vitest";
import type {
  ProjectTag,
  ProjectMonitorConfig,
} from "../api/generated/types.gen";
import EcologyMonitorPage from "../pages/EcologyMonitorPage";
import MonitorEntryCard from "./MonitorEntryCard";
import { createMonitorSource } from "./source";

const context = vi.hoisted(() => ({
  current: "2",
  projects: [] as ProjectTag[],
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { id: 1 } }),
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => context,
}));
vi.mock("./MonitorGlobe", () => ({ default: () => null }));
vi.mock("./useMonitor", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./useMonitor")>()),
  useMonitorActivity: () => ({
    visible: true,
    reducedMotion: false,
    animated: false,
  }),
}));
vi.mock("./source", () => ({
  createMonitorSource: vi.fn(() => ({
    getSnapshot: vi.fn(),
    subscribe: vi.fn(),
  })),
}));

const config: ProjectMonitorConfig = {
  title: "独立研究区监测",
  source: "tarim_poplar_mock",
  initialView: { center: [100, 30], zoom: 3, regionZoom: 7 },
};
const project: ProjectTag = {
  id: 2,
  code: "independent",
  name: "研究区甲",
  description: "",
  isDefault: false,
  isActive: true,
  sortOrder: 1,
  enabledFeatures: ["ecology_monitor"],
  monitorConfig: config,
};

function html(element: ReactNode) {
  return renderToStaticMarkup(
    <App>
      <MemoryRouter initialEntries={["/results/ecology-monitor"]}>
        {element}
      </MemoryRouter>
    </App>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  context.current = "2";
  context.projects = [{ ...project }];
});

it("任意项目代码仅由后端有效功能清单决定入口", () => {
  expect(html(<MonitorEntryCard />)).toContain("进入监测大屏");
  context.projects[0]!.enabledFeatures = [];
  context.projects[0]!.code = "05";
  expect(html(<MonitorEntryCard />)).not.toContain("进入监测大屏");
  expect(html(<EcologyMonitorPage />)).toContain("当前项目尚未开启监测大屏");
  expect(createMonitorSource).not.toHaveBeenCalled();
});

it("功能清单缺失、项目停用或当前项目不可访问时默认关闭", () => {
  delete context.projects[0]!.enabledFeatures;
  expect(html(<MonitorEntryCard />)).not.toContain("进入监测大屏");
  context.projects[0] = { ...project, isActive: false };
  expect(html(<EcologyMonitorPage />)).toContain("当前项目尚未开启监测大屏");
  context.current = "999";
  expect(html(<EcologyMonitorPage />)).toContain("返回成果");
  expect(createMonitorSource).not.toHaveBeenCalled();
});

it("开启但无配置显示空状态且不装配模拟数据源", () => {
  context.projects[0]!.monitorConfig = null;
  expect(html(<MonitorEntryCard />)).toContain("进入监测大屏");
  const result = html(<EcologyMonitorPage />);
  expect(result).toContain("尚未配置监测内容");
  expect(result).not.toContain("塔里木");
  expect(createMonitorSource).not.toHaveBeenCalled();
});

it("有配置时使用项目标题与显式数据源，切换项目不沿用配置", () => {
  expect(html(<EcologyMonitorPage />)).toContain(config.title);
  expect(createMonitorSource).toHaveBeenCalledWith({
    projectId: 2,
    locale: "zh-CN",
    config,
  });
  context.projects.push({
    ...project,
    id: 3,
    code: "other",
    monitorConfig: null,
  });
  context.current = "3";
  vi.clearAllMocks();
  const result = html(<EcologyMonitorPage />);
  expect(result).toContain("尚未配置监测内容");
  expect(result).not.toContain(config.title);
  expect(createMonitorSource).not.toHaveBeenCalled();
});
