import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { agentApi } from "../api/agent";
import { platformApi } from "../api/platform";
import type { AgentResearchDemoList } from "../api/generated/types.gen";
import { ProjectProvider, useProjectContext } from "../projects/ProjectContext";
import { getActiveProject, resetProjectSession } from "../projects/session";
import ResearchDemoShowcase from "./ResearchDemoShowcase";

vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { id: 99 } }),
}));
const items: AgentResearchDemoList["items"] = [
  {
    scenario: "ecology_investigation",
    projectId: 8,
    projectName: "干旱区生态风险评估分析决策",
    title: "从植被变化到调查建议",
    prompt: "使用本项目模拟两期影像和预设，解释植被变化并保存成果",
    sampleNature: "synthetic",
    available: true,
  },
  {
    scenario: "geology_correction",
    projectId: 3,
    projectName: "核地院逻辑推理",
    title: "从填图检查到纠偏复核",
    prompt: "检查本项目模拟填图，依据调查纠偏并保存地图，审核时向我提问",
    sampleNature: "synthetic",
    available: true,
  },
  {
    scenario: "geology_age_correction",
    projectId: 3,
    projectName: "核地院逻辑推理",
    title: "真实底图 · 地层时代录入纠偏",
    prompt:
      "使用真实图件副本检查标注的时代录入错误，检索辞书并实际计算、复查和保存地图",
    sampleNature: "real_map_with_demonstration_errors",
    available: true,
  },
];
function Destination() {
  const project = useProjectContext();
  const location = useLocation();
  return (
    <div>
      <output aria-label="入口项目">{project?.current}</output>
      <output aria-label="案例请求">{JSON.stringify(location.state)}</output>
    </div>
  );
}
function ProjectSwitch() {
  const project = useProjectContext();
  return (
    <button
      type="button"
      onClick={() => project?.choose("3", undefined, { confirm: false })}
    >
      切换到逻辑推理
    </button>
  );
}
function show() {
  return render(
    <AntApp>
      <MemoryRouter initialEntries={["/results"]}>
        <ProjectProvider>
          <ProjectSwitch />
          <Routes>
            <Route path="/results" element={<ResearchDemoShowcase />} />
            <Route path="/agent/workbench" element={<Destination />} />
          </Routes>
        </ProjectProvider>
      </MemoryRouter>
    </AntApp>,
  );
}
beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
  resetProjectSession();
  vi.spyOn(platformApi, "projects").mockResolvedValue({
    items: [
      { id: 1, name: "公开", isDefault: true, isActive: true },
      { id: 8, name: items[0].projectName, isDefault: false, isActive: true },
      { id: 3, name: items[1].projectName, isDefault: false, isActive: true },
    ],
    canManage: false,
    canAssign: false,
  });
  vi.spyOn(agentApi, "researchDemos").mockResolvedValue({ items });
});

it.each([0, 1, 2])(
  "launches case %i only from its current project without switching projects",
  async (index) => {
    const item = items[index];
    sessionStorage.setItem("project:99", String(item.projectId));
    show();
    const launch = await screen.findByRole("button", {
      name: `开始体验：${item.title}`,
    });
    expect(launch).not.toBeDisabled();
    fireEvent.click(launch);
    await waitFor(() =>
      expect(screen.getByLabelText("入口项目")).toHaveTextContent(
        String(item.projectId),
      ),
    );
    expect(getActiveProject()).toBe(String(item.projectId));
    expect(sessionStorage.getItem("project:99")).toBe(String(item.projectId));
    const data = JSON.parse(
      screen.getByLabelText("案例请求").textContent || "{}",
    );
    expect(data.researchDemo).toMatchObject(item);
    expect(data.researchDemo.token).toHaveLength(36);
    expect(data.query).toBeUndefined();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  },
);

it("shows geological demonstrations only in the current logic project", async () => {
  sessionStorage.setItem("project:99", "3");
  show();
  expect(
    await screen.findByText("真实底图 · 演示录入错误"),
  ).toBeInTheDocument();
  expect(screen.getAllByText("模拟资料 · 真实计算")).toHaveLength(1);
  expect(screen.getAllByRole("button", { name: /开始体验/ })).toHaveLength(2);
  expect(screen.queryByText(items[0].title)).not.toBeInTheDocument();
  expect(screen.getByText(/按辞书与适用条件修正时代录入/)).toBeInTheDocument();
  await page.screenshot({
    path: "../../test-results/research-demo-showcase-desktop.png",
  });
});

it("shows ecology only in the current arid-area project and updates on project change", async () => {
  sessionStorage.setItem("project:99", "8");
  show();
  expect(await screen.findByText(items[0].title)).toBeInTheDocument();
  expect(screen.queryByText(items[1].title)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "切换到逻辑推理" }));
  expect(await screen.findByText(items[1].title)).toBeInTheDocument();
  expect(screen.queryByText(items[0].title)).not.toBeInTheDocument();
  expect(getActiveProject()).toBe("3");
});

it("keeps unavailable entries disabled and hides entries belonging to inaccessible projects", async () => {
  sessionStorage.setItem("project:99", "8");
  vi.mocked(agentApi.researchDemos).mockResolvedValue({
    items: [
      { ...items[0], available: false },
      { ...items[1], projectId: 999 },
    ],
  });
  show();
  expect(await screen.findByRole("button", { name: /准备中/ })).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: /开始体验/ }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText(items[1].title)).not.toBeInTheDocument();
  expect(getActiveProject()).toBe("8");
});

it("hides all demonstrations in the public project even when other projects are accessible", async () => {
  show();
  await waitFor(() => expect(agentApi.researchDemos).toHaveBeenCalled());
  await waitFor(() => expect(platformApi.projects).toHaveBeenCalled());
  expect(screen.queryByLabelText("智能科研体验")).not.toBeInTheDocument();
  expect(screen.queryByText(items[0].projectName)).not.toBeInTheDocument();
  expect(screen.queryByText(items[1].projectName)).not.toBeInTheDocument();
  expect(getActiveProject()).toBe("1");
});

it("hides all demonstrations when the current project is no longer authorized", async () => {
  sessionStorage.setItem("project:99", "3");
  vi.mocked(platformApi.projects).mockResolvedValue({
    items: [{ id: 1, name: "公开", isDefault: true, isActive: true }],
    canManage: false,
    canAssign: false,
  });
  show();
  await waitFor(() => expect(getActiveProject()).toBe("1"));
  expect(screen.queryByLabelText("智能科研体验")).not.toBeInTheDocument();
});

it("does not show empty entries and remains readable on a phone", async () => {
  sessionStorage.setItem("project:99", "3");
  vi.mocked(agentApi.researchDemos).mockResolvedValue({ items: [] });
  const mounted = show();
  await waitFor(() => expect(agentApi.researchDemos).toHaveBeenCalled());
  expect(screen.queryByLabelText("智能科研体验")).not.toBeInTheDocument();
  mounted.unmount();
  vi.mocked(agentApi.researchDemos).mockResolvedValue({ items });
  await page.viewport(390, 844);
  show();
  const region = await screen.findByLabelText("智能科研体验");
  expect(region.scrollWidth).toBeLessThanOrEqual(region.clientWidth + 1);
  await page.screenshot({
    path: "../../test-results/research-demo-showcase-phone.png",
  });
  await page.viewport(1600, 900);
});
