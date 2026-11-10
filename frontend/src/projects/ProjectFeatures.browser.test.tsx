import { App } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { platformApi } from "../api/platform";
import { api } from "../api/client";
import type { ProjectTag, ProjectTagList } from "../api/generated/types.gen";
import ProjectManagementPage from "../pages/ProjectManagementPage";
import { ProjectProvider } from "./ProjectContext";
import { resetProjectSession } from "./session";

const state = vi.hoisted(() => ({
  global: false,
  enabled: false,
  admin: true,
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { id: 42 } }),
}));

function response(): ProjectTagList {
  const project: ProjectTag = {
    id: 1,
    name: "公开",
    code: "default",
    description: "",
    isDefault: true,
    isActive: true,
    sortOrder: 0,
    enabledFeatures: state.global || state.enabled ? ["ecology_monitor"] : [],
    configuredFeatures: state.enabled ? ["ecology_monitor"] : [],
    monitorConfig: null,
  };
  return {
    items: [project],
    canManage: state.admin,
    canAssign: state.admin,
    defaultProjectId: 1,
    assignableItems: state.admin ? [project] : [],
    featureCatalog: state.admin
      ? [{ key: "ecology_monitor", globallyEnabled: state.global }]
      : [],
  };
}

function show() {
  return render(
    <App>
      <MemoryRouter>
        <ProjectProvider>
          <ProjectManagementPage />
        </ProjectProvider>
      </MemoryRouter>
    </App>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  state.global = false;
  state.enabled = false;
  state.admin = true;
  sessionStorage.clear();
  resetProjectSession();
  vi.spyOn(api, "adminUsers").mockResolvedValue({ items: [] });
  vi.spyOn(platformApi, "projects").mockImplementation(async () => response());
  vi.spyOn(platformApi, "setProjectFeature").mockImplementation(
    async (_, __, body) => {
      state.enabled = body.enabled ?? state.enabled;
      return response().items[0]!;
    },
  );
  vi.spyOn(platformApi, "setGlobalProjectFeature").mockImplementation(
    async (key, enabled) => {
      state.global = enabled;
      return { key, globallyEnabled: enabled };
    },
  );
});

it("后台可开启关闭项目，支持全局覆盖并在全局关闭后恢复单项目状态", async () => {
  show();
  const projectSwitch = await screen.findByRole("switch", {
    name: "公开 ecology_monitor",
  });
  expect(projectSwitch).not.toBeChecked();
  fireEvent.click(projectSwitch);
  await waitFor(() => expect(projectSwitch).toBeChecked());
  await waitFor(() => expect(projectSwitch).toBeEnabled());
  expect(platformApi.setProjectFeature).toHaveBeenCalledWith(
    1,
    "ecology_monitor",
    { enabled: true },
  );
  fireEvent.click(projectSwitch);
  await waitFor(() => expect(projectSwitch).not.toBeChecked());
  await waitFor(() => expect(projectSwitch).toBeEnabled());
  const globalSwitch = screen.getByRole("switch", {
    name: "ecology_monitor 对所有项目开启",
  });
  fireEvent.click(globalSwitch);
  await waitFor(() => expect(globalSwitch).toBeChecked());
  expect(projectSwitch).toBeChecked();
  expect(projectSwitch).toBeDisabled();
  fireEvent.click(globalSwitch);
  await waitFor(() => expect(globalSwitch).not.toBeChecked());
  expect(projectSwitch).not.toBeChecked();
  await waitFor(() => expect(projectSwitch).toBeEnabled());
  expect(platformApi.setGlobalProjectFeature).toHaveBeenCalledWith(
    "ecology_monitor",
    false,
  );
});

it("非管理员不显示管理开关，也不发送写请求", async () => {
  state.admin = false;
  show();
  await screen.findByText("当前账号没有标签管理权限。");
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  expect(platformApi.setProjectFeature).not.toHaveBeenCalled();
  expect(platformApi.setGlobalProjectFeature).not.toHaveBeenCalled();
});

it("保存失败保留服务端旧状态并提示错误", async () => {
  vi.mocked(platformApi.setProjectFeature).mockRejectedValueOnce(
    new Error("保存失败测试"),
  );
  show();
  const projectSwitch = await screen.findByRole("switch", {
    name: "公开 ecology_monitor",
  });
  fireEvent.click(projectSwitch);
  await screen.findByText("Error: 保存失败测试");
  expect(projectSwitch).not.toBeChecked();
  await waitFor(() => expect(projectSwitch).toBeEnabled());
});
