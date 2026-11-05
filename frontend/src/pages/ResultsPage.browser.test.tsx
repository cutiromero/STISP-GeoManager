import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppContext } from "../contexts/AppContext";
import { appTheme } from "../theme";
import type { Bootstrap, MapComposition, ResultArtifact, User } from "../types";
import ResultsPage from "./ResultsPage";

const mockApi = vi.hoisted(() => ({
  resources: vi.fn(),
  workspaces: vi.fn(),
  mapCompositions: vi.fn(),
  resultArtifacts: vi.fn(),
  downloadMapCompositionVersion: vi.fn(),
  downloadResultArtifact: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("../api/platform", () => ({
  platformApi: {
    projects: vi
      .fn()
      .mockResolvedValue({ items: [], canManage: false, canAssign: false }),
  },
}));

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  api: mockApi,
  requestJson: vi.fn().mockResolvedValue({ canChat: false, canAgent: false }),
  requestForm: vi.fn(),
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

const viewer: User = {
  id: 8,
  username: "topic-viewer",
  displayName: "专题成果查看用户",
  email: "topic-viewer@example.local",
  avatarUrl: "",
  department: "生态监测组",
  isStaff: false,
  isSuperuser: false,
  roles: ["专题成果访问组"],
  groupIds: [18],
  isActive: true,
  operationLogGroupIds: [],
  permissions: {
    canAccessAdmin: true,
    canManageFeaturePermissions: false,
    canCreateUser: false,
    canViewOperationLogs: false,
    canViewAllOperationLogs: false,
    canViewOwnOperationLogs: false,
    canViewGroupOperationLogs: false,
    canViewSystemLogs: false,
    canManageSystemSettings: false,
    canManageDataBackup: false,
    canManageAuth: false,
    canViewDashboardResourceCard: false,
    canViewDashboardLayerCard: false,
    canViewDashboardRasterCard: false,
    canViewDashboardUserCard: false,
    canViewDashboardActiveUsersCard: false,
    canViewDashboardSystemCard: false,
    canViewDataOverview: false,
    canBrowseData: true,
    canQueryData: false,
    canUploadData: false,
    canViewDataResources: true,
    canCreateDataResources: false,
    canChangeDataResources: false,
    canDeleteDataResources: false,
    canLoadVectorLayer: false,
    canLoadRasterLayer: false,
    canUseCustomSymbolization: false,
    canUseAiInterpretation: false,
    canExportData: false,
    canViewWorkspaces: false,
    canCreateWorkspaces: false,
    canChangeWorkspaces: false,
    canDeleteWorkspaces: false,
    canViewMapCompositions: true,
    canCreateMapCompositions: false,
    canChangeMapCompositions: false,
    canDeleteMapCompositions: false,
    canExportMapCompositions: true,
    canPublishMapCompositions: false,
    canRestoreMapCompositions: false,
    canViewResultArtifacts: true,
    canImportResultArtifacts: false,
    canDownloadResultArtifacts: true,
    canPublishResultArtifacts: false,
    canDeleteResultArtifacts: false,
    canManageRasterData: false,
  },
};

const publishedVersion = {
  id: 103,
  compositionId: 27,
  versionNumber: 3,
  format: "pdf" as const,
  dpi: 300,
  widthPx: 3200,
  heightPx: 2400,
  note: "正式发布版",
  snapshotSchemaVersion: 2,
  snapshotChecksum: "a".repeat(64),
  previewUrl:
    "/api/catalog/map-compositions/27/versions/3/file/?variant=preview",
  downloadUrl:
    "/api/catalog/map-compositions/27/versions/3/file/?variant=artifact",
  createdAt: "2026-07-22T10:30:00+08:00",
};

const publishedComposition: MapComposition = {
  id: 27,
  projectId: 9,
  projectName: "塔里木河胡杨监测工程",
  name: "塔里木河胡杨分布专题图",
  description: "由地理工作台制作并发布的胡杨分布专题成果。",
  status: "published",
  layout: {},
  owner: {
    id: 2,
    username: "map-composer",
    displayName: "专题制图员",
  },
  audienceGroups: [
    {
      id: 18,
      name: "专题成果访问组",
      isGuest: false,
      isSuperadmin: false,
    },
  ],
  currentVersion: publishedVersion,
  publishedVersion,
  versions: [publishedVersion],
  isOwner: false,
  canPreview: true,
  canDownload: true,
  canEditLayout: false,
  canPublish: false,
  canUnpublish: false,
  canRestoreProject: false,
  canLoadSourceProject: false,
  canDelete: false,
  publishedAt: "2026-07-23T09:00:00+08:00",
  publishedBy: {
    id: 2,
    username: "map-composer",
    displayName: "专题制图员",
  },
  createdAt: "2026-07-21T09:00:00+08:00",
  updatedAt: "2026-07-23T09:00:00+08:00",
};

function RoutePosition() {
  const location = useLocation();
  return (
    <output aria-label="当前页面路径">
      {location.pathname + location.search}
    </output>
  );
}

function renderResultsPage() {
  const setBootstrap = vi.fn();
  const setUser = vi.fn();
  return render(
    <ConfigProvider locale={zhCN} theme={appTheme}>
      <AntApp>
        <AppContext.Provider
          value={{ bootstrap, user: viewer, setBootstrap, setUser }}
        >
          <MemoryRouter initialEntries={["/results"]}>
            <RoutePosition />
            <ResultsPage />
          </MemoryRouter>
        </AppContext.Provider>
      </AntApp>
    </ConfigProvider>,
  );
}

describe("ResultsPage published map compositions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.resources.mockResolvedValue({ items: [] });
    mockApi.workspaces.mockResolvedValue({ items: [] });
    mockApi.mapCompositions.mockResolvedValue({
      items: [publishedComposition],
      availableAudienceGroups: [],
    });
    mockApi.resultArtifacts.mockResolvedValue({
      items: [],
      availableAccessGroups: [],
    });
    mockApi.downloadMapCompositionVersion.mockResolvedValue({
      blob: new Blob(["published-map"], { type: "image/png" }),
      filename: "塔里木河胡杨分布专题图_V3.png",
    });
  });

  it("loads the published version from the workbench and exposes its preview and download", async () => {
    renderResultsPage();

    expect(
      await screen.findByText("塔里木河胡杨分布专题图"),
    ).toBeInTheDocument();
    expect(mockApi.mapCompositions).toHaveBeenCalledWith({
      status: "published",
    });
    expect(screen.getByText("V3")).toBeInTheDocument();
    expect(
      screen.getByText("来源工程：塔里木河胡杨监测工程"),
    ).toBeInTheDocument();
    expect(
      screen.getByAltText("塔里木河胡杨分布专题图成果预览"),
    ).toHaveAttribute("src", publishedVersion.previewUrl);

    fireEvent.click(screen.getByRole("button", { name: /查看详情/ }));

    expect(
      screen.getAllByAltText("塔里木河胡杨分布专题图成果预览"),
    ).toHaveLength(2);
    expect(
      screen.queryByTitle("塔里木河胡杨分布专题图 PDF 预览"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /下载成果/ }));

    await waitFor(() =>
      expect(mockApi.downloadMapCompositionVersion).toHaveBeenCalledWith(
        publishedComposition.id,
        publishedVersion.versionNumber,
      ),
    );
  });

  it.each([true, false])(
    "opens only the currently visible related data, linked=%s",
    async (linked) => {
      const artifact: ResultArtifact = {
        id: 57,
        projectTagId: 3,
        name: "布喀达坂峰幅人工精修岩性图",
        description: "师弟人工修改成果，与本次重算面积表关联。",
        sourceType: "direct_import",
        resultType: "map",
        status: "published",
        category: {
          id: 1,
          type: "data_category",
          code: "spatial",
          name: "地理数据",
        },
        categoryPath: [],
        provider: "地质解译组",
        fileName: "lithology.png",
        fileFormat: "png",
        sizeBytes: 1024,
        previewUrl:
          "/api/catalog/results/57/file/?variant=preview&projectTagId=3",
        downloadUrl:
          "/api/catalog/results/57/file/?variant=artifact&projectTagId=3",
        owner: publishedComposition.owner,
        accessGroups: [],
        relatedResources: linked
          ? [
              { id: 301, name: "人工精修对照图", dataType: "vector" },
              { id: 302, name: "当前面积统计", dataType: "table" },
            ]
          : [],
        canPreview: true,
        canDownload: true,
        canPublish: false,
        canUnpublish: false,
        canDelete: false,
        publishedAt: "2026-10-12T09:00:00+08:00",
        publishedBy: publishedComposition.owner,
        createdAt: "2026-10-12T09:00:00+08:00",
        updatedAt: "2026-10-12T09:00:00+08:00",
      };
      mockApi.mapCompositions.mockResolvedValue({
        items: [],
        availableAudienceGroups: [],
      });
      mockApi.resultArtifacts.mockResolvedValue({
        items: [artifact],
        availableAccessGroups: [],
      });
      renderResultsPage();
      fireEvent.click(await screen.findByRole("button", { name: /查看详情/ }));
      if (linked) {
        expect(await screen.findByText("关联数据")).toBeInTheDocument();
        expect(
          await screen.findByRole("link", { name: "人工精修对照图" }),
        ).toHaveAttribute("href", "/map?resources=301&projectTagId=3");
        expect(
          screen.getByRole("link", { name: "当前面积统计" }),
        ).toHaveAttribute(
          "href",
          `/resources/catalog?resourceId=302&q=${encodeURIComponent("当前面积统计")}`,
        );
        expect(
          fireEvent.click(screen.getByRole("link", { name: "人工精修对照图" })),
        ).toBe(false);
        expect(screen.getByLabelText("当前页面路径")).toHaveTextContent(
          "/map?resources=301&projectTagId=3",
        );
        expect(
          fireEvent.click(screen.getByRole("link", { name: "当前面积统计" })),
        ).toBe(false);
        expect(screen.getByLabelText("当前页面路径")).toHaveTextContent(
          `/resources/catalog?resourceId=302&q=${encodeURIComponent("当前面积统计")}`,
        );
      } else {
        expect(screen.queryByText("关联数据")).not.toBeInTheDocument();
        expect(
          screen.queryByRole("link", { name: "人工精修对照图" }),
        ).not.toBeInTheDocument();
      }
    },
  );
});
