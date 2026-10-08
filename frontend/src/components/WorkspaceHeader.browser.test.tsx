import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { page, userEvent } from "vitest/browser";
import { AppContext } from "../contexts/AppContext";
import { appTheme } from "../theme";
import type {
  Bootstrap,
  MapComposition,
  ResourceListItem,
  User,
  WorkspaceScene,
} from "../types";
import WorkspaceHeader from "./WorkspaceHeader";
import headerStyles from "../styles.css?inline";

const { clearCachedLayerGroupsMock, mockApi } = vi.hoisted(() => ({
  clearCachedLayerGroupsMock: vi.fn(),
  mockApi: {
    logout: vi.fn(),
    resources: vi.fn(),
    workspaces: vi.fn(),
    mapCompositions: vi.fn(),
  },
}));

vi.mock("../api/platform", () => ({
  platformApi: {
    projects: vi
      .fn()
      .mockResolvedValue({ items: [], canManage: false, canAssign: false }),
  },
}));

vi.mock("../api/client", () => ({
  api: mockApi,
  requestJson: vi.fn().mockResolvedValue({ canChat: false, canAgent: false }),
  requestForm: vi.fn(),
}));

vi.mock("../utils/layerWorkspaceStorage", () => ({
  clearCachedLayerGroups: clearCachedLayerGroupsMock,
}));

const bootstrap: Bootstrap = {
  systemName: "全球胡杨林生态系统保护数据共享平台",
  allowRegistration: false,
  map: {
    defaultCenter: [87.6, 41.7],
    defaultZoom: 6.5,
    defaultBasemap: "osm",
    mapboxAccessToken: "",
  },
  limits: {
    uploadMaxMb: 512,
    queryResultLimit: 30000,
    maxRasterSidePixels: 10000,
  },
};

const permissions: User["permissions"] = {
  canAccessAdmin: true,
  canManageFeaturePermissions: false,
  canCreateUser: false,
  canViewOperationLogs: false,
  canViewAllOperationLogs: false,
  canViewOwnOperationLogs: false,
  canViewGroupOperationLogs: false,
  canViewSystemLogs: false,
  canManageSystemSettings: false,
  canManageAuth: false,
  canViewDashboardResourceCard: false,
  canViewDashboardLayerCard: false,
  canViewDashboardRasterCard: false,
  canViewDashboardUserCard: false,
  canViewDashboardActiveUsersCard: false,
  canViewDashboardSystemCard: false,
  canViewDataOverview: false,
  canBrowseData: true,
  canQueryData: true,
  canUploadData: false,
  canViewDataResources: false,
  canCreateDataResources: false,
  canChangeDataResources: false,
  canDeleteDataResources: false,
  canLoadVectorLayer: true,
  canLoadRasterLayer: true,
  canUseCustomSymbolization: false,
  canExportData: false,
  canViewWorkspaces: false,
  canCreateWorkspaces: false,
  canChangeWorkspaces: false,
  canDeleteWorkspaces: false,
  canManageRasterData: false,
};

const user: User = {
  id: 7,
  username: "researcher",
  displayName: "科研用户",
  email: "researcher@example.local",
  avatarUrl: "",
  department: "生态监测组",
  isStaff: false,
  isSuperuser: false,
  roles: ["科研用户"],
  operationLogGroupIds: [],
  permissions,
};

const resource: ResourceListItem = {
  id: 21,
  name: "塔里木河胡杨样地监测点",
  code: "tarim-poplar-monitoring-2026",
  dataType: "vector",
  category: { code: "monitoring", name: "长期监测" },
  source: "2026 塔里木河野外调查",
  provider: "生态监测组",
  dataDate: "2026-06-01",
  spatialExtent: "87.600000,43.795100,87.642800,43.812450",
  coordinateSystem: "EPSG:4326",
  fileFormat: "GeoPackage",
  description: "塔里木河胡杨样地监测点位",
  qualityNote: "",
  status: "active",
  isQueryable: true,
  isRenderable: false,
  updatedAt: "2026-06-18T12:00:00+08:00",
  sizeBytes: 245760,
  itemCount: 3,
};

function scene(
  id: number,
  kind: WorkspaceScene["kind"],
  name: string,
): WorkspaceScene {
  return {
    id,
    kind,
    name,
    description: "",
    snapshot: { groups: [] },
    owner: {
      id: user.id,
      username: user.username,
      displayName: user.displayName,
    },
    accessGroups: [],
    isOwner: true,
    canEdit: true,
    canDelete: true,
    canManageAccess: true,
    createdAt: "2026-06-18T12:00:00+08:00",
    updatedAt: "2026-06-18T12:00:00+08:00",
  };
}

const topicComposition: MapComposition = {
  id: 2,
  projectId: 1,
  projectName: "塔里木河监测工程",
  name: "胡杨退化专题",
  description: "退化样地专题成果",
  status: "completed",
  layout: {},
  owner: {
    id: user.id,
    username: user.username,
    displayName: user.displayName,
  },
  audienceGroups: [],
  currentVersion: null,
  publishedVersion: null,
  versions: [],
  isOwner: true,
  canPreview: true,
  canDownload: true,
  canEditLayout: true,
  canPublish: true,
  canUnpublish: false,
  canRestoreProject: true,
  canLoadSourceProject: true,
  canDelete: true,
  publishedAt: null,
  publishedBy: null,
  createdAt: "2026-06-18T12:00:00+08:00",
  updatedAt: "2026-06-18T12:00:00+08:00",
};

function renderHeader(
  props: Partial<React.ComponentProps<typeof WorkspaceHeader>> = {},
  contextUser: User = user,
  setUser: (user: User | null) => void = vi.fn(),
  initialPath = "/",
  withStyles = false,
) {
  return render(
    <ConfigProvider locale={zhCN} theme={appTheme}>
      <AntApp>
        {withStyles && <style>{headerStyles}</style>}
        <AppContext.Provider
          value={{
            bootstrap,
            user: contextUser,
            setBootstrap: vi.fn(),
            setUser,
          }}
        >
          <MemoryRouter initialEntries={[initialPath]}>
            <WorkspaceHeader
              activeTab="map"
              canBrowseData
              resources={[resource]}
              workspaceScenes={[scene(1, "project", "塔里木河监测工程")]}
              mapCompositions={[topicComposition]}
              {...props}
            />
            <CurrentPath />
          </MemoryRouter>
        </AppContext.Provider>
      </AntApp>
    </ConfigProvider>,
  );
}

function CurrentPath() {
  const location = useLocation();
  return <span data-testid="location-path">{location.pathname}</span>;
}

function sectionByTitle(title: string) {
  const section = screen.getByText(title).closest(".workspace-search-section");
  expect(section).not.toBeNull();
  return section as HTMLElement;
}

describe("WorkspaceHeader", () => {
  beforeEach(() => {
    for (const fn of Object.values(mockApi)) {
      fn.mockReset();
    }
    clearCachedLayerGroupsMock.mockReset();
    mockApi.logout.mockResolvedValue({ detail: "已退出" });
    mockApi.resources.mockResolvedValue({ items: [resource] });
    mockApi.workspaces.mockResolvedValue({
      items: [scene(1, "project", "塔里木河监测工程")],
    });
    mockApi.mapCompositions.mockResolvedValue({
      items: [topicComposition],
      availableAudienceGroups: [],
    });
    clearCachedLayerGroupsMock.mockResolvedValue(undefined);
  });

  it("separates projects and topics and loads them only from the load button", async () => {
    const onLoadWorkspaceScene = vi.fn();
    const onLoadMapComposition = vi.fn();
    const onQuickLoadResource = vi.fn();
    renderHeader({
      onLoadWorkspaceScene,
      onLoadMapComposition,
      onQuickLoadResource,
    });

    fireEvent.click(screen.getByPlaceholderText("搜索数据、工程、专题"));

    await waitFor(() => {
      expect(screen.getByText("塔里木河监测工程")).toBeInTheDocument();
    });

    const projectSection = sectionByTitle("工程");
    const topicSection = sectionByTitle("专题");
    expect(
      within(projectSection).getByText("塔里木河监测工程"),
    ).toBeInTheDocument();
    expect(
      within(projectSection).queryByText("胡杨退化专题"),
    ).not.toBeInTheDocument();
    expect(within(topicSection).getByText("胡杨退化专题")).toBeInTheDocument();
    expect(
      within(topicSection).queryByText("塔里木河监测工程"),
    ).not.toBeInTheDocument();

    fireEvent.click(within(projectSection).getByText("塔里木河监测工程"));
    fireEvent.click(within(topicSection).getByText("胡杨退化专题"));
    expect(onLoadWorkspaceScene).not.toHaveBeenCalled();
    expect(onLoadMapComposition).not.toHaveBeenCalled();
    expect(onQuickLoadResource).not.toHaveBeenCalled();

    fireEvent.click(
      within(projectSection).getByRole("button", { name: /加\s*载/ }),
    );
    expect(onLoadWorkspaceScene).toHaveBeenCalledWith(
      expect.objectContaining({ id: 1, kind: "project" }),
    );

    fireEvent.click(
      within(topicSection).getByRole("button", { name: /加\s*载/ }),
    );
    expect(onLoadMapComposition).toHaveBeenCalledWith(topicComposition);
  });

  it("opens the global search panel from the mobile trigger", async () => {
    renderHeader();

    fireEvent.click(screen.getByRole("button", { name: "打开全局搜索" }));

    expect(
      await screen.findByRole("region", { name: "全局搜索结果" }),
    ).toBeInTheDocument();
    expect(screen.getByText("专题")).toBeInTheDocument();
    expect(screen.getByText("胡杨退化专题")).toBeInTheDocument();
  });

  it("hides the standalone data import shortcut without upload permission", () => {
    renderHeader();

    expect(
      screen.queryByRole("button", { name: "数据导入" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("location-path")).toHaveTextContent("/");
  });

  it("hides data management and personal settings from guest sessions", async () => {
    const guestUser: User = {
      ...user,
      id: 99,
      username: "guest",
      displayName: "Guest",
      roles: ["游客"],
    };

    renderHeader({}, guestUser);

    expect(
      screen.queryByRole("button", { name: "数据资源" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "用户信息" }));
    expect(
      await screen.findByRole("button", { name: /安全退出/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "个人信息" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("location-path")).toHaveTextContent("/");
  });

  it("does not request workspaces without workspace view permission", async () => {
    renderHeader({ resources: undefined, workspaceScenes: undefined });

    await waitFor(() => {
      expect(mockApi.resources).toHaveBeenCalledOnce();
    });
    expect(mockApi.workspaces).not.toHaveBeenCalled();
  });

  it("loads workspace search without requiring data browse permission", async () => {
    const workspaceOnlyUser: User = {
      ...user,
      permissions: {
        ...permissions,
        canBrowseData: false,
        canViewWorkspaces: true,
      },
    };
    renderHeader(
      {
        canBrowseData: false,
        resources: undefined,
        workspaceScenes: undefined,
        mapCompositions: [],
      },
      workspaceOnlyUser,
    );

    await waitFor(() => {
      expect(mockApi.workspaces).toHaveBeenCalledOnce();
    });
    expect(mockApi.resources).not.toHaveBeenCalled();
    fireEvent.click(screen.getByPlaceholderText("搜索数据、工程、专题"));
    expect(await screen.findByText("塔里木河监测工程")).toBeInTheDocument();
  });

  it("keeps resource search available when workspace search fails", async () => {
    mockApi.workspaces.mockRejectedValue(new Error("工程搜索加载失败"));
    const workspaceUser: User = {
      ...user,
      permissions: {
        ...permissions,
        canViewWorkspaces: true,
      },
    };
    renderHeader(
      {
        resources: undefined,
        workspaceScenes: undefined,
        mapCompositions: [],
      },
      workspaceUser,
    );

    await waitFor(() => {
      expect(mockApi.resources).toHaveBeenCalledOnce();
      expect(mockApi.workspaces).toHaveBeenCalledOnce();
    });
    fireEvent.click(screen.getByPlaceholderText("搜索数据、工程、专题"));
    expect(await screen.findByText(resource.name)).toBeInTheDocument();
  });

  it("keeps workspace search available when resource search fails", async () => {
    mockApi.resources.mockRejectedValue(new Error("数据搜索加载失败"));
    const workspaceUser: User = {
      ...user,
      permissions: {
        ...permissions,
        canViewWorkspaces: true,
      },
    };
    renderHeader(
      {
        resources: undefined,
        workspaceScenes: undefined,
        mapCompositions: [],
      },
      workspaceUser,
    );

    await waitFor(() => {
      expect(mockApi.resources).toHaveBeenCalledOnce();
      expect(mockApi.workspaces).toHaveBeenCalledOnce();
    });
    fireEvent.click(screen.getByPlaceholderText("搜索数据、工程、专题"));
    expect(await screen.findByText("塔里木河监测工程")).toBeInTheDocument();
  });

  it("opens the data import page from the highlighted shortcut", () => {
    const uploadUser: User = {
      ...user,
      permissions: {
        ...permissions,
        canUploadData: true,
      },
    };
    renderHeader({}, uploadUser);

    fireEvent.click(screen.getByRole("button", { name: "数据导入" }));

    expect(screen.getByTestId("location-path")).toHaveTextContent(
      "/resources/data/import",
    );
  });

  it("returns to the geographic workspace when the platform logo is clicked", () => {
    renderHeader(
      { activeTab: "resources" },
      user,
      vi.fn(),
      "/resources/dashboard",
    );

    fireEvent.click(screen.getByRole("button", { name: "返回地理工作台" }));

    expect(screen.getByTestId("location-path")).toHaveTextContent("/map");
  });

  it("does not render the intelligent interpretation placeholder in navigation", () => {
    renderHeader();

    expect(
      screen.queryByRole("button", { name: "智能解译" }),
    ).not.toBeInTheDocument();
  });

  it("hides the agent entry when neither agent capability is granted", () => {
    renderHeader();

    expect(
      screen.queryByRole("button", { name: "智能体" }),
    ).not.toBeInTheDocument();
  });

  it("keeps first-entry map navigation available and opens guidance on demand", async () => {
    window.localStorage.clear();
    renderHeader();

    expect(screen.queryByText("🎉 欢迎 🎉")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "地理工作台" }));

    expect(screen.getByTestId("location-path")).toHaveTextContent("/map");

    fireEvent.click(screen.getByRole("button", { name: "用户信息" }));
    fireEvent.click(await screen.findByRole("button", { name: /显示引导/ }));

    expect(await screen.findByText("🎉 欢迎 🎉")).toBeInTheDocument();
  });

  it("clears cached layer state when the user logs out", async () => {
    const setUser = vi.fn();
    renderHeader({}, user, setUser);

    fireEvent.click(screen.getByRole("button", { name: "用户信息" }));
    fireEvent.click(await screen.findByRole("button", { name: /安全退出/ }));

    await waitFor(() => {
      expect(clearCachedLayerGroupsMock).toHaveBeenCalledOnce();
    });
    expect(mockApi.logout).toHaveBeenCalledOnce();
    expect(setUser).toHaveBeenCalledWith(null);
    await waitFor(() =>
      expect(screen.getByTestId("location-path")).toHaveTextContent("/login"),
    );
    expect(mockApi.logout.mock.invocationCallOrder[0]).toBeLessThan(
      clearCachedLayerGroupsMock.mock.invocationCallOrder[0],
    );
    expect(clearCachedLayerGroupsMock.mock.invocationCallOrder[0]).toBeLessThan(
      setUser.mock.invocationCallOrder[0],
    );
  });

  it.each([1500, 1280, 1024])(
    "keeps compressed navigation hit regions fixed at %s pixels",
    async (width) => {
      await page.viewport(width, 900);
      try {
        const { container } = renderHeader({}, user, vi.fn(), "/", true);
        const header =
          container.querySelector<HTMLElement>(".workspace-header")!;
        await waitFor(() =>
          expect(header).toHaveClass("workspace-header-nav-measured"),
        );
        const about = container.querySelector<HTMLButtonElement>(
          '.header-primary-actions button[title="关于我们"]',
        )!;
        const elements = [
          ...container.querySelectorAll<HTMLElement>(
            ".header-primary-actions button, .workspace-global-search",
          ),
        ];
        const rects = () =>
          elements.map((element) => {
            const box = element.getBoundingClientRect();
            return [box.x, box.y, box.width, box.height];
          });
        await userEvent.hover(
          screen.getByRole("button", { name: "返回地理工作台" }),
        );
        await new Promise((resolve) => setTimeout(resolve, 800));
        const active = container.querySelector<HTMLButtonElement>(
          ".workspace-switch-card-active",
        )!;
        for (const edge of ["left", "right", "activeBottom"] as const) {
          const target = edge === "activeBottom" ? active : about;
          const initial = rects();
          const bounds = target.getBoundingClientRect();
          await userEvent.hover(target, {
            position: {
              // Playwright positions are relative to the padding box, inside the border.
              x:
                edge === "activeBottom"
                  ? bounds.width / 2 - 1
                  : edge === "left"
                    ? 0
                    : bounds.width - 2,
              y:
                edge === "activeBottom"
                  ? bounds.height - 1.5
                  : bounds.height / 2 - 1,
            },
          });
          let maxDrift = 0;
          for (let sample = 0; sample < 18; sample++) {
            await new Promise((resolve) => setTimeout(resolve, 70));
            rects().forEach((box, index) =>
              box.forEach((value, coordinate) => {
                maxDrift = Math.max(
                  maxDrift,
                  Math.abs(value - initial[index]![coordinate]!),
                );
              }),
            );
          }
          expect(maxDrift).toBeLessThanOrEqual(0.6);
          expect(target.matches(":hover")).toBe(true);
          await userEvent.hover(
            screen.getByRole("button", { name: "返回地理工作台" }),
          );
          await new Promise((resolve) => setTimeout(resolve, 800));
        }
      } finally {
        await page.viewport(1600, 900);
      }
    },
  );

  it.each([
    ["地理工作台", "/map"],
    ["数据资源", "/resources/catalog"],
    ["数据分析", "/nongeo"],
    ["后台管理", "/admin/dashboard"],
    ["关于我们", "/about/system"],
  ])(
    "keeps the %s tooltip clear of its usable dropdown",
    async (title, path) => {
      await page.viewport(1024, 900);
      try {
        const { container } = renderHeader({}, user, vi.fn(), "/", true);
        const header =
          container.querySelector<HTMLElement>(".workspace-header")!;
        await waitFor(() =>
          expect(header).toHaveClass("workspace-header-nav-measured"),
        );
        await userEvent.hover(
          screen.getByRole("button", { name: "返回地理工作台" }),
        );
        await new Promise((resolve) => setTimeout(resolve, 800));
        const trigger = container.querySelector<HTMLButtonElement>(
          `.header-primary-actions button[title="${title}"]`,
        )!;
        await userEvent.hover(trigger);
        const tooltip = await screen.findByRole("tooltip");
        const menu = await screen.findByRole("menu");
        expect(tooltip).toHaveTextContent(title);
        const tooltipRoot = tooltip.closest<HTMLElement>(".ant-tooltip")!;
        const dropdownRoot = menu.closest<HTMLElement>(
          ".workspace-management-dropdown",
        )!;
        await new Promise((resolve) => setTimeout(resolve, 350));
        const labelBounds = tooltipRoot.getBoundingClientRect();
        const menuBounds = dropdownRoot.getBoundingClientRect();
        const overlapWidth = Math.max(
          0,
          Math.min(labelBounds.right, menuBounds.right) -
            Math.max(labelBounds.left, menuBounds.left),
        );
        const overlapHeight = Math.max(
          0,
          Math.min(labelBounds.bottom, menuBounds.bottom) -
            Math.max(labelBounds.top, menuBounds.top),
        );
        expect(overlapWidth * overlapHeight).toBe(0);
        expect(getComputedStyle(tooltipRoot).pointerEvents).toBe("none");
        await userEvent.click(within(menu).getAllByRole("menuitem")[0]!);
        await waitFor(() =>
          expect(screen.getByTestId("location-path")).toHaveTextContent(path),
        );
      } finally {
        await page.viewport(1600, 900);
      }
    },
  );

  it("shows a focus label without moving the navigation and supports keyboard activation", async () => {
    await page.viewport(1024, 900);
    try {
      const { container } = renderHeader({}, user, vi.fn(), "/", true);
      const header = container.querySelector<HTMLElement>(".workspace-header")!;
      await waitFor(() =>
        expect(header).toHaveClass("workspace-header-nav-measured"),
      );
      const compute = container.querySelector<HTMLButtonElement>(
        '[data-nav-key="compute"]',
      )!;
      const before = compute.getBoundingClientRect();
      compute.focus();
      expect(await screen.findByRole("tooltip")).toHaveTextContent(
        compute.title,
      );
      expect(compute).toHaveFocus();
      expect(compute.getBoundingClientRect().x).toBe(before.x);
      expect(compute.getBoundingClientRect().width).toBe(before.width);
      await userEvent.keyboard("{Enter}");
      await waitFor(() =>
        expect(screen.getByTestId("location-path")).toHaveTextContent(
          "/compute",
        ),
      );
    } finally {
      await page.viewport(1600, 900);
    }
  });

  it("preserves narrow-screen navigation and the mobile search entry", async () => {
    await page.viewport(390, 844);
    try {
      const { container } = renderHeader({}, user, vi.fn(), "/", true);
      const header = container.querySelector<HTMLElement>(".workspace-header")!;
      await waitFor(() =>
        expect(header).toHaveClass("workspace-header-nav-measured"),
      );
      expect(screen.queryByRole("button", { name: "智能体" })).toBeNull();
      expect(
        screen.getByRole("button", { name: "打开全局搜索" }),
      ).toBeVisible();
      expect(header.getBoundingClientRect().right).toBeLessThanOrEqual(
        window.innerWidth,
      );
      const about = container.querySelector<HTMLButtonElement>(
        '.header-primary-actions button[title="关于我们"]',
      )!;
      about.focus();
      expect(about).toHaveFocus();
      expect(await screen.findByRole("tooltip")).toHaveTextContent("关于我们");
      await userEvent.keyboard("{Enter}");
      await waitFor(() =>
        expect(screen.getByTestId("location-path")).toHaveTextContent(
          "/about/system",
        ),
      );
    } finally {
      await page.viewport(1600, 900);
    }
  });
});
