import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "vitest/browser";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { registerForbiddenHandler } from "./api/client";
import { platformApi } from "./api/platform";
import { appTheme } from "./theme";
import platformStyles from "./styles.css?inline";
import type {
  Bootstrap,
  DataResourceProfile,
  NonGeoAnalytics,
  ResourceListItem,
  ResourceQueryResult,
  User,
} from "./types";

const { MockApiError, mockApi } = vi.hoisted(() => {
  class MockApiError extends Error {
    status: number;
    data: unknown;

    constructor(message: string, status: number, data?: unknown) {
      super(message);
      this.status = status;
      this.data = data;
    }
  }

  return {
    MockApiError,
    mockApi: {
      bootstrap: vi.fn(),
      loginOverview: vi.fn(),
      csrf: vi.fn(),
      me: vi.fn(),
      login: vi.fn(),
      guestLogin: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
      resources: vi.fn(),
      resourceProfile: vi.fn(),
      resourceVisualizationSummary: vi.fn(),
      nonGeoAnalysis: vi.fn(),
      nonGeoQuery: vi.fn(),
      queryResource: vi.fn(),
      workspaces: vi.fn(),
      scanCatalogSources: vi.fn(),
      scanRasterSources: vi.fn(),
      renderRasterAsync: vi.fn(),
      rasterJob: vi.fn(),
      adminOperationLogs: vi.fn(),
      adminSystemLogs: vi.fn(),
      adminDashboard: vi.fn(),
      adminDashboardServer: vi.fn(),
      dataSchemaSummary: vi.fn(),
    },
  };
});

vi.mock("./api/platform", () => ({
  platformApi: {
    projects: vi.fn().mockResolvedValue({
      items: [
        {
          id: 1,
          name: "公开",
          code: "default",
          isDefault: true,
          isActive: true,
          description: "",
          sortOrder: 0,
        },
      ],
      canManage: false,
      canAssign: false,
      assignableItems: [],
    }),
    articles: vi
      .fn()
      .mockResolvedValue({ items: [], total: 0, canEdit: false }),
  },
}));

vi.mock("./api/sharing", () => ({
  sharingApi: {
    list: vi.fn().mockResolvedValue({
      items: [],
      total: 0,
      unreadCount: 0,
      limit: 12,
      offset: 0,
    }),
  },
}));

vi.mock("./api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api/client")>()),
  ApiError: MockApiError,
  api: mockApi,
  registerForbiddenHandler: vi.fn(),
  unregisterForbiddenHandler: vi.fn(),
}));

vi.mock("./components/MapCanvas", () => ({
  default: ({
    loadedLayers = [],
  }: {
    loadedLayers?: Array<{ layerType?: string; tileUrl?: string }>;
  }) => (
    <div
      data-testid="map-canvas"
      style={{ width: "100%", height: "100%" }}
      data-raster-tile-url={
        loadedLayers.find((layer) => layer.layerType === "raster")?.tileUrl ??
        ""
      }
    />
  ),
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

const basePermissions = {
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

const normalUser: User = {
  id: 1,
  username: "researcher",
  displayName: "科研用户",
  email: "researcher@example.local",
  avatarUrl: "",
  department: "生态监测组",
  isStaff: false,
  isSuperuser: false,
  roles: ["科研用户"],
  operationLogGroupIds: [],
  permissions: basePermissions,
};

const adminUser: User = {
  ...normalUser,
  id: 2,
  username: "admin",
  displayName: "系统管理员",
  isStaff: false,
  isSuperuser: false,
  roles: ["系统管理员"],
  permissions: {
    ...basePermissions,
    canManageFeaturePermissions: true,
    canCreateUser: true,
    canManageRasterData: true,
  },
};

const tarimVectorResource: ResourceListItem = {
  id: 21,
  name: "塔里木河胡杨样地监测点",
  code: "tarim-poplar-monitoring-2026",
  dataType: "vector",
  spatialClass: "spatial",
  domainType: "field_survey",
  category: {
    id: 101,
    type: "data_category",
    code: "thematic_population",
    name: "种群",
    parentId: 100,
    selectable: true,
  },
  categoryPath: [
    { id: 100, code: "thematic", name: "胡杨专题数据" },
    { id: 101, code: "thematic_population", name: "种群" },
  ],
  classificationStatus: "classified",
  availableViews: ["map", "table", "metadata"],
  defaultView: "map",
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

const nonGeoTableResource: ResourceListItem = {
  id: 22,
  name: "2024 塔里木盆地植物调查基础数据",
  code: "tarim-plant-metadata-2024",
  dataType: "table",
  spatialClass: "non_spatial",
  domainType: "field_survey",
  category: null,
  categoryPath: [],
  classificationStatus: "pending",
  availableViews: ["metadata"],
  defaultView: "metadata",
  source: "用户导入",
  provider: "",
  dataDate: null,
  spatialExtent: "",
  coordinateSystem: "",
  fileFormat: "SQLITE",
  description: "不含经纬度的调查元数据",
  qualityNote: "",
  status: "active",
  isQueryable: false,
  isRenderable: false,
  updatedAt: "2026-07-14T10:00:00+08:00",
  sizeBytes: 1024,
  itemCount: 8,
};

const nonGeoAnalytics: NonGeoAnalytics = {
  resource: nonGeoTableResource,
  summary: {
    rowCount: 2,
    analyzedRowCount: 2,
    sampled: false,
    fieldCount: 3,
    numericFieldCount: 1,
    textFieldCount: 1,
    categoricalFieldCount: 1,
    completeness: 1,
    updatedAt: "2026-07-14T10:00:00+08:00",
    suggestedView: "species",
  },
  fields: [
    {
      name: "sample_id",
      type: "string",
      label: "sample_id",
      description: "样本编号",
      unit: "",
      role: "identifier",
      nullable: false,
      nonNullCount: 2,
      nullCount: 0,
      completeness: 1,
      uniqueCount: 2,
      sampleValues: ["S-1", "S-2"],
    },
    {
      name: "species",
      type: "string",
      label: "species",
      description: "物种",
      unit: "",
      role: "category",
      nullable: false,
      nonNullCount: 2,
      nullCount: 0,
      completeness: 1,
      uniqueCount: 2,
      sampleValues: ["胡杨", "柽柳"],
    },
    {
      name: "height",
      type: "float",
      label: "height",
      description: "高度",
      unit: "m",
      role: "measure",
      nullable: false,
      nonNullCount: 2,
      nullCount: 0,
      completeness: 1,
      uniqueCount: 2,
      sampleValues: [12.5, 5.2],
      min: 5.2,
      max: 12.5,
      mean: 8.85,
    },
  ],
  categoricalDistributions: [
    {
      field: "species",
      label: "species",
      total: 2,
      items: [
        { value: "胡杨", count: 1, ratio: 0.5 },
        { value: "柽柳", count: 1, ratio: 0.5 },
      ],
    },
  ],
  numericDistributions: [
    {
      field: "height",
      label: "height",
      min: 5.2,
      max: 12.5,
      mean: 8.85,
      median: 8.85,
      q1: 7.025,
      q3: 10.675,
      bins: [{ label: "5.2-12.5", min: 5.2, max: 12.5, count: 2, ratio: 1 }],
    },
  ],
  correlation: null,
  tablePreview: {
    resourceId: nonGeoTableResource.id,
    resourceName: nonGeoTableResource.name,
    totalCount: 2,
    returnedCount: 2,
    limit: 80,
    offset: 0,
    fields: [
      {
        name: "sample_id",
        type: "string",
        nullable: false,
        sampleValues: ["S-1", "S-2"],
        description: "样本编号",
      },
      {
        name: "species",
        type: "string",
        nullable: false,
        sampleValues: ["胡杨", "柽柳"],
        description: "物种",
      },
      {
        name: "height",
        type: "float",
        nullable: false,
        sampleValues: [12.5, 5.2],
        description: "高度",
      },
    ],
    rows: [
      { sample_id: "S-1", species: "胡杨", height: 12.5 },
      { sample_id: "S-2", species: "柽柳", height: 5.2 },
    ],
  },
  insights: ["资源包含 2 条真实记录和 3 个字段。"],
};

const tarimVectorProfile: DataResourceProfile = {
  resource: tarimVectorResource,
  fields: [
    {
      name: "sample_id",
      type: "str",
      nullable: false,
      sampleValues: ["TP-2026-001"],
      description: "样点编号",
    },
    {
      name: "dbh_cm",
      type: "float",
      nullable: false,
      sampleValues: [32.5],
      description: "胸径",
    },
  ],
  featureCount: 3,
  geometryType: "Point",
  bounds: [87.6, 43.7951, 87.6428, 43.81245],
};

const tarimRasterResource: ResourceListItem = {
  ...tarimVectorResource,
  id: 24,
  name: "塔里木河胡杨遥感影像",
  code: "tarim-poplar-raster-2026",
  dataType: "raster",
  domainType: "raster",
  availableViews: ["map", "metadata"],
  defaultView: "map",
  spatialExtent: "88.328434,40.079174,88.401642,40.160831",
  coordinateSystem: "EPSG:3857",
  fileFormat: "COG",
  isQueryable: false,
  isRenderable: true,
  itemCount: 1,
};

const tarimRasterRules = {
  mode: "gray",
  bands: [1],
  palette: "poplar",
  uniqueValues: [],
  alphaBand: "mask",
  nodata: { enabled: true },
  stretch: {
    enabled: true,
    type: "minmax",
    perBand: { "1": { min: 0, max: 255 } },
  },
};

const tarimRasterProfile: DataResourceProfile = {
  resource: tarimRasterResource,
  fields: [],
  featureCount: 0,
  geometryType: "Raster",
  bounds: [88.328434, 40.079174, 88.401642, 40.160831],
  raster: {
    id: 24,
    name: tarimRasterResource.name,
    code: tarimRasterResource.code,
    status: "ready",
    sourcePath: "tarim-poplar-raster.tif",
    processedPath: "tarim-poplar-raster.cog.tif",
    sourceMetadataPath: "source/tarim-poplar-raster.json",
    processedMetadataPath: "preprocessed/tarim-poplar-raster.json",
    dataResourceId: tarimRasterResource.id,
    mapLayerId: 24,
    bandCount: 1,
    bounds3857: [9832676.279, 4877454.34, 9840825.79, 4889341.335],
    bounds4326: [88.328434, 40.079174, 88.401642, 40.160831],
    imageCoordinates: [
      [88.328434, 40.160831],
      [88.401642, 40.160831],
      [88.401642, 40.079174],
      [88.328434, 40.079174],
    ],
    defaultRules: tarimRasterRules,
    sourceFileSize: 4464959,
    processedFileSize: 5861035,
    progressLog: "",
    errorMessage: "",
    importedAt: "2026-06-18T12:00:00+08:00",
    processedAt: "2026-06-18T12:10:00+08:00",
    metadata: {
      size: [12444, 18151],
      driver: "GTiff",
      coordinateSystem: 3857,
      bands: [
        {
          band: 1,
          type: "Byte",
          description: "遥感灰度",
          colorInterpretation: "Gray",
          min: 0,
          max: 255,
          isInteger: true,
        },
      ],
    },
  },
};

const tarimRasterRenderResult = {
  tileUrl: "/api/raster/tiles/24/tarim-default/{z}/{x}/{y}.png",
  styleHash: "tarim-default",
  minZoom: 0,
  maxZoom: 16,
  tileSampling: "linear",
  imageCoordinates: tarimRasterProfile.raster?.imageCoordinates ?? [],
  rules: tarimRasterRules,
};

const tarimQueryResult: ResourceQueryResult = {
  resourceId: 21,
  resourceName: "塔里木河胡杨样地监测点",
  totalCount: 3,
  returnedCount: 3,
  limit: 30000,
  fields: tarimVectorProfile.fields,
  geojson: {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: { type: "Point", coordinates: [87.6, 43.8] },
        properties: {
          sample_id: "TP-2026-001",
          health: "良好",
          dbh_cm: 32.5,
        },
      },
    ],
  },
  warnings: [],
};

const tarimVisualizationSummary = {
  resource: tarimVectorResource,
  domainType: "field_survey",
  generatedAt: "2026-06-18T12:00:00+08:00",
  source: "backend_aggregate",
  profile: {
    featureCount: 3,
    fieldCount: tarimVectorProfile.fields.length,
    geometryType: "Point",
    bounds: tarimVectorProfile.bounds,
  },
  categoryStats: [],
  numericStats: [],
  spatialSummary: {
    featureCount: 3,
    validGeometryCount: 3,
    nullGeometryCount: 0,
    coordinateCoverageRatio: 1,
    bounds: tarimVectorProfile.bounds,
    geometryTypes: [],
    centroid: [87.6214, 43.803775],
  },
  qualityIssues: [],
  recommendedCharts: [],
  recommendedSymbolizations: [],
  monitorPreview: {
    title: "资源质量监测",
    status: "ready",
    items: [],
  },
};

function renderApp(initialEntry: string) {
  return render(
    <ConfigProvider locale={zhCN} theme={appTheme}>
      <AntApp>
        <MemoryRouter initialEntries={[initialEntry]}>
          <App />
        </MemoryRouter>
      </AntApp>
    </ConfigProvider>,
  );
}

async function clickFirstResourceSelectButton() {
  let selectResourceButton: HTMLButtonElement | null = null;
  await waitFor(() => {
    selectResourceButton = document.querySelector<HTMLButtonElement>(
      ".resource-row button:not(.resource-quick-load-button)",
    );
    expect(selectResourceButton).not.toBeNull();
  });
  fireEvent.click(selectResourceButton!);
}

describe("application critical flows", () => {
  beforeEach(() => {
    window.localStorage.clear();
    for (const fn of Object.values(mockApi)) {
      fn.mockReset();
    }
    mockApi.bootstrap.mockResolvedValue(bootstrap);
    mockApi.loginOverview.mockRejectedValue(new Error("测试未配置登录概览"));
    mockApi.csrf.mockResolvedValue({ detail: "csrf cookie set" });
    mockApi.me.mockRejectedValue(new MockApiError("未登录", 401));
    mockApi.login.mockResolvedValue({ user: normalUser });
    mockApi.guestLogin.mockResolvedValue({
      user: {
        ...normalUser,
        id: 99,
        username: "guest",
        displayName: "游客",
        roles: ["游客"],
      },
    });
    mockApi.adminDashboard.mockResolvedValue({
      generatedAt: "2026-01-01T00:00:00+08:00",
      cards: {},
    });
    mockApi.adminDashboardServer.mockResolvedValue({ cards: {} });
    mockApi.dataSchemaSummary.mockResolvedValue({
      taxonomyVersion: "2026.07",
      domains: [],
      layers: [],
      entities: [],
      catalogTree: [],
    });
    mockApi.register.mockResolvedValue({
      user: normalUser,
      detail: "用户注册成功",
      roleApplication: null,
    });
    mockApi.logout.mockResolvedValue({ detail: "已退出" });
    mockApi.resources.mockResolvedValue({ items: [] });
    mockApi.resourceProfile.mockResolvedValue(tarimVectorProfile);
    mockApi.resourceVisualizationSummary.mockResolvedValue(
      tarimVisualizationSummary,
    );
    mockApi.nonGeoAnalysis.mockResolvedValue(nonGeoAnalytics);
    mockApi.nonGeoQuery.mockResolvedValue(nonGeoAnalytics.tablePreview);
    mockApi.queryResource.mockResolvedValue(tarimQueryResult);
    mockApi.workspaces.mockResolvedValue({
      items: [],
      availableAccessGroups: [],
    });
    mockApi.scanCatalogSources.mockResolvedValue({ detail: "ok" });
    mockApi.scanRasterSources.mockResolvedValue({
      id: "scan-job",
      status: "ready",
    });
    mockApi.renderRasterAsync.mockResolvedValue({
      id: "render-job",
      kind: "render",
      status: "ready",
      stage: "ready",
      progressPercent: 100,
      messages: ["默认栅格瓦片已就绪"],
      result: tarimRasterRenderResult,
      error: "",
      createdAt: "2026-08-11T10:00:00+08:00",
      updatedAt: "2026-08-11T10:00:01+08:00",
    });
    mockApi.rasterJob.mockResolvedValue({
      id: "scan-job",
      status: "ready",
      progressPercent: 100,
      messages: [],
    });
    mockApi.adminOperationLogs.mockResolvedValue({
      items: [],
      total: 0,
    });
    mockApi.adminSystemLogs.mockResolvedValue({
      files: [],
      selectedFile: "",
      lines: 500,
      content: "",
      generatedAt: "2026-06-20T09:45:10+08:00",
    });
  });

  it("exits directly to login while a project refresh and logout confirmation are pending", async () => {
    mockApi.me.mockResolvedValueOnce({ authenticated: true, user: normalUser });
    let finishLogout: (value: { detail: string }) => void = () => {};
    mockApi.logout.mockReturnValueOnce(
      new Promise((resolve) => {
        finishLogout = resolve;
      }),
    );
    renderApp("/map");
    expect(
      await screen.findByTestId("map-canvas", {}, { timeout: 10000 }),
    ).toBeVisible();
    let rejectRefresh: (error: unknown) => void = () => {};
    vi.mocked(platformApi.projects).mockReturnValueOnce(
      new Promise((_, reject) => {
        rejectRefresh = reject;
      }),
    );
    fireEvent(window, new Event("focus"));
    fireEvent.click(screen.getByRole("button", { name: "用户信息" }));
    fireEvent.click(await screen.findByRole("button", { name: /安全退出/ }));
    expect(
      await screen.findByLabelText("账号", {}, { timeout: 10000 }),
    ).toBeVisible();
    rejectRefresh(
      new DOMException("signal is aborted without reason", "AbortError"),
    );
    finishLogout({ detail: "已退出" });
    await waitFor(() => expect(mockApi.logout).toHaveBeenCalledOnce());
    expect(screen.queryByText("项目访问范围加载失败")).not.toBeInTheDocument();
    expect(
      screen.queryByText("signal is aborted without reason"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("登录状态已失效")).not.toBeInTheDocument();
    expect(sessionStorage.getItem("auth:expired-return")).toBeNull();
  });

  it("opens the public map directly at the root without a homepage", async () => {
    const stylesheet = document.createElement("style");
    stylesheet.textContent = platformStyles;
    document.head.append(stylesheet);
    try {
      renderApp("/");
      const canvas = await screen.findByTestId(
        "map-canvas",
        {},
        { timeout: 5000 },
      );
      expect(canvas).toBeInTheDocument();
      const wrapper = canvas.closest<HTMLElement>("main.map-stage");
      expect(wrapper).not.toBeNull();
      expect(wrapper!.getBoundingClientRect().height).toBeGreaterThan(300);
      expect(canvas.getBoundingClientRect().height).toBeGreaterThan(300);
      expect(canvas.getBoundingClientRect().width).toBeGreaterThan(300);
      expect(canvas).toBeVisible();
      expect(
        screen.queryByLabelText("地理工作台地质成果对比"),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /^首页$/ }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /^数据资源$/ }),
      ).toBeInTheDocument();
    } finally {
      stylesheet.remove();
    }
  });

  it("upgrades a legacy bootstrap name in the browser tab", async () => {
    mockApi.bootstrap.mockResolvedValueOnce({
      ...bootstrap,
      systemName: "中亚胡杨林生态系统保护数据共享平台",
    });

    renderApp("/login");

    await screen.findByRole("heading", { name: "用户登录" });
    expect(document.title).toBe("时空智能服务平台");
  });

  it("submits required email and a separate research role application", async () => {
    mockApi.bootstrap.mockResolvedValue({
      ...bootstrap,
      allowRegistration: true,
    });
    mockApi.register.mockResolvedValue({
      user: normalUser,
      detail: "用户注册成功，科研用户权限申请已提交",
      roleApplication: {
        id: 1,
        userId: normalUser.id,
        requestedRole: "research",
        status: "pending",
        reason: "需要上传长期监测数据",
        reviewNote: "",
        createdAt: "2026-07-14T10:30:00+08:00",
        reviewedAt: null,
      },
    });

    renderApp("/login");

    expect(
      await screen.findByRole("heading", { name: "用户登录" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /注册新账号/ }));
    expect(
      await screen.findByRole("heading", { name: "用户注册" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("首个注册用户自动成为系统管理员。"),
    ).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("请输入账号"), {
      target: { value: "research_applicant" },
    });
    fireEvent.change(screen.getByPlaceholderText("请输入邮箱"), {
      target: { value: "Applicant@Example.COM" },
    });
    await userEvent.click(screen.getByText("申请科研用户"));
    fireEvent.change(await screen.findByPlaceholderText("请输入真实姓名"), {
      target: { value: "张研究员" },
    });
    fireEvent.change(screen.getByPlaceholderText("请输入单位或部门"), {
      target: { value: "生态监测组" },
    });
    fireEvent.change(
      screen.getByPlaceholderText(
        "请简要说明需要上传、导出或科研分析权限的用途",
      ),
      { target: { value: "需要上传长期监测数据" } },
    );
    const passwordFields = screen.getAllByPlaceholderText(
      /请输入密码|请再次输入密码/,
    );
    fireEvent.change(passwordFields[0], {
      target: { value: "StrongPass12345" },
    });
    fireEvent.change(passwordFields[1], {
      target: { value: "StrongPass12345" },
    });
    fireEvent.click(screen.getByRole("button", { name: /注册并进入/ }));

    await waitFor(() => {
      expect(mockApi.register).toHaveBeenCalledWith({
        username: "research_applicant",
        email: "Applicant@Example.COM",
        accountPurpose: "research",
        displayName: "张研究员",
        department: "生态监测组",
        applicationReason: "需要上传长期监测数据",
        password: "StrongPass12345",
        passwordConfirm: "StrongPass12345",
      });
    });
  });

  it("retries app startup while the backend is still becoming ready", async () => {
    mockApi.bootstrap
      .mockRejectedValueOnce(new MockApiError("后端服务尚未就绪", 503))
      .mockResolvedValue(bootstrap);

    renderApp("/login");

    await waitFor(() => {
      expect(mockApi.bootstrap).toHaveBeenCalledTimes(1);
    });

    expect(
      await screen.findByRole("heading", { name: "用户登录" }),
    ).toBeInTheDocument();
    expect(mockApi.bootstrap).toHaveBeenCalledTimes(2);
    expect(mockApi.csrf).toHaveBeenCalledTimes(2);
  });

  it("allows visitors to enter the unified data catalog through guest login", async () => {
    mockApi.resources.mockResolvedValue({ items: [tarimVectorResource] });
    renderApp("/login");

    expect(
      await screen.findByRole("heading", { name: "用户登录" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /游客登录/ }));

    await waitFor(() => {
      expect(mockApi.guestLogin).toHaveBeenCalled();
    });
    expect(
      await screen.findByTestId("map-canvas", {}, { timeout: 10000 }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("塔里木河胡杨样地监测点", {}, { timeout: 10000 }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "加载", exact: true }));

    await waitFor(() => {
      expect(mockApi.queryResource).toHaveBeenCalledWith(tarimVectorResource, {
        attributeFilters: [],
        spatialFilter: null,
        limit: 30000,
      });
    });
    expect(screen.queryByText("请先登录")).not.toBeInTheDocument();
  });

  it("shows a retry action instead of an endless spinner after startup fails", async () => {
    mockApi.bootstrap.mockRejectedValue(
      new MockApiError("浏览器连接失败", 400),
    );
    renderApp("/login");
    expect(await screen.findByText("平台暂时未能加载")).toBeInTheDocument();
    expect(screen.getByText("浏览器连接失败")).toBeInTheDocument();
    mockApi.bootstrap.mockResolvedValue(bootstrap);
    fireEvent.click(screen.getByRole("button", { name: "重新连接" }));
    expect(
      await screen.findByRole("heading", { name: "用户登录" }),
    ).toBeInTheDocument();
  });

  it("redirects the old data URL to the resource module", async () => {
    mockApi.me.mockResolvedValue({ authenticated: true, user: normalUser });
    renderApp("/data");
    expect(
      await screen.findByRole("heading", { name: "数据资源目录" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^地理工作台$/ }));
    expect(
      await screen.findByTestId("map-canvas", {}, { timeout: 5000 }),
    ).toBeInTheDocument();
  });

  it("runs a representative vector query flow from resource selection to layer loading", async () => {
    mockApi.me.mockResolvedValue({ authenticated: true, user: normalUser });
    mockApi.resources.mockResolvedValue({ items: [tarimVectorResource] });

    renderApp("/map");

    expect(
      await screen.findByText("塔里木河胡杨样地监测点", {}, { timeout: 10000 }),
    ).toBeInTheDocument();
    await clickFirstResourceSelectButton();

    await waitFor(() => {
      expect(mockApi.resourceProfile).toHaveBeenCalledWith(tarimVectorResource);
    });
    expect(await screen.findByText("sample_id")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "查询并加载" }));

    await waitFor(() => {
      expect(mockApi.queryResource).toHaveBeenCalledWith(tarimVectorResource, {
        attributeFilters: [],
        spatialFilter: null,
        limit: 30000,
      });
    });
    fireEvent.click(screen.getByRole("tab", { name: /图层/ }));
    await waitFor(() => {
      const layerItems = screen.getAllByRole("treeitem");
      expect(
        layerItems.some((item) =>
          item.textContent?.includes("塔里木河胡杨样地监测点"),
        ),
      ).toBe(true);
    });
  });

  it("quick-loads a raster into the map without a manual symbolization click", async () => {
    const readyJob = {
      id: "render-job-raster-load",
      kind: "render",
      status: "ready",
      stage: "ready",
      progressPercent: 100,
      messages: ["默认栅格瓦片已就绪"],
      result: tarimRasterRenderResult,
      error: "",
      createdAt: "2026-08-11T10:00:00+08:00",
      updatedAt: "2026-08-11T10:00:01+08:00",
    };
    let resolveRender: (job: typeof readyJob) => void = () => undefined;
    mockApi.me.mockResolvedValue({ authenticated: true, user: normalUser });
    mockApi.resources.mockResolvedValue({ items: [tarimRasterResource] });
    mockApi.resourceProfile.mockResolvedValue(tarimRasterProfile);
    mockApi.renderRasterAsync.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveRender = resolve;
        }),
    );

    renderApp("/map");

    expect(
      await screen.findByText(tarimRasterResource.name, {}, { timeout: 10000 }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "加载", exact: true }));

    const progress = await screen.findByRole("status", {
      name: `${tarimRasterResource.name}加载进度`,
    });
    expect(progress).toHaveTextContent("正在准备栅格瓦片服务");
    expect(screen.getByTestId("map-canvas")).toHaveAttribute(
      "data-raster-tile-url",
      "",
    );

    resolveRender(readyJob);

    await waitFor(() => {
      expect(screen.getByTestId("map-canvas")).toHaveAttribute(
        "data-raster-tile-url",
        tarimRasterRenderResult.tileUrl,
      );
    });
    expect(
      screen.queryByRole("status", {
        name: `${tarimRasterResource.name}加载进度`,
      }),
    ).not.toBeInTheDocument();
    expect(mockApi.renderRasterAsync).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("tab", { name: /图层/ }));
    await waitFor(() => {
      const layerItems = screen.getAllByRole("treeitem");
      expect(
        layerItems.some((item) =>
          item.textContent?.includes(tarimRasterResource.name),
        ),
      ).toBe(true);
    });
  });

  it("shows the built-in poplar dataset and its details in the public project", async () => {
    window.localStorage.setItem(
      `huyang-system.workspace-tour.v1.${normalUser.id}.${normalUser.username}`,
      "completed",
    );
    mockApi.me.mockResolvedValue({ authenticated: true, user: normalUser });
    mockApi.resources.mockResolvedValue({
      items: [nonGeoTableResource, tarimVectorResource],
    });

    renderApp("/nongeo");

    expect(
      await screen.findByRole("heading", {
        name: "胡杨群落物种功能性状演示数据",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("内置示例，用于体验图表和明细查询。"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(nonGeoTableResource.name),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(tarimVectorResource.name),
    ).not.toBeInTheDocument();
    expect(await screen.findByText("记录总量")).toBeInTheDocument();
    expect(
      screen.getByText("2,411", { selector: "strong" }),
    ).toBeInTheDocument();
    expect(screen.getByText("数据说明与字段")).toBeInTheDocument();
    expect(mockApi.nonGeoAnalysis).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "查询明细" }));
    expect(await screen.findByRole("tab", { name: /明细/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      await screen.findByRole("columnheader", { name: "株高 (m)" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("cell", { name: "巴州地区" }).length,
    ).toBeGreaterThan(0);
    expect(mockApi.nonGeoQuery).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "刷新非地理数据资源" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the legacy analysis URL compatible while hiding the demo outside its project scope", async () => {
    const { platformApi } = await import("./api/platform");
    const projects = await platformApi.projects();
    const preferenceKey = `project:${normalUser.id}`;
    const previousProject = sessionStorage.getItem(preferenceKey);
    vi.mocked(platformApi.projects).mockResolvedValue({
      ...projects,
      items: [
        ...projects.items,
        {
          id: 7,
          name: "逻辑推理",
          code: "logic-reasoning",
          isDefault: false,
          isActive: true,
          description: "",
          sortOrder: 1,
        },
      ],
    });
    sessionStorage.setItem(preferenceKey, "7");
    mockApi.me.mockResolvedValue({ authenticated: true, user: normalUser });
    try {
      renderApp("/analysis");
      expect(
        await screen.findByRole("main", { name: "数据分析工作台" }),
      ).toBeInTheDocument();
      await waitFor(() =>
        expect(document.querySelector(".project-selector")).toHaveTextContent(
          "逻辑推理",
        ),
      );
      expect(screen.getByText("当前项目暂无演示数据")).toBeInTheDocument();
      expect(
        screen.queryByRole("heading", { name: "胡杨群落物种功能性状演示数据" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "查询明细" }),
      ).not.toBeInTheDocument();
      expect(mockApi.nonGeoAnalysis).not.toHaveBeenCalled();
      expect(mockApi.nonGeoQuery).not.toHaveBeenCalled();
    } finally {
      vi.mocked(platformApi.projects).mockResolvedValue(projects);
      if (previousProject === null) sessionStorage.removeItem(preferenceKey);
      else sessionStorage.setItem(preferenceKey, previousProject);
    }
  });

  it("keeps the shared guest account out of personal settings", async () => {
    const guestUser: User = {
      ...normalUser,
      id: 99,
      username: "guest",
      displayName: "游客",
      roles: ["游客"],
    };
    mockApi.me.mockResolvedValue({ authenticated: true, user: guestUser });

    renderApp("/admin/profile");

    await waitFor(() => {
      expect(mockApi.resources).toHaveBeenCalled();
    });
  });

  it("runs a long research user journey without privileged data exposure", async () => {
    const researchUser: User = {
      ...normalUser,
      id: 31,
      username: "secure_researcher",
      displayName: "安全科研用户",
      roles: ["科研用户"],
      permissions: {
        ...basePermissions,
        canViewOwnOperationLogs: true,
        canViewOperationLogs: false,
        canViewSystemLogs: false,
        canManageSystemSettings: false,
        canManageDataBackup: false,
        canManageAuth: false,
      },
    };
    window.localStorage.setItem(
      `huyang-system.workspace-tour.v1.${researchUser.id}.${researchUser.username}`,
      "completed",
    );
    mockApi.me.mockResolvedValue({ authenticated: true, user: researchUser });
    mockApi.resources.mockResolvedValue({ items: [tarimVectorResource] });
    mockApi.adminOperationLogs.mockResolvedValue({
      items: [
        {
          id: 42,
          occurredAt: "2026-06-20 10:30:00",
          operator: "安全科研用户",
          module: "数据查询",
          action: "查询数据资源",
          result: "success",
          targetType: "data_resource",
          targetId: tarimVectorResource.id,
          targetCode: tarimVectorResource.code,
          targetName: tarimVectorResource.name,
          ipAddress: "203.0.113.31",
          summary: "本人查询塔里木河样地数据",
        },
      ],
      total: 1,
    });

    renderApp("/map");

    expect(
      await screen.findByText("塔里木河胡杨样地监测点", {}, { timeout: 10000 }),
    ).toBeInTheDocument();
    expect(screen.queryByText("超级管理员")).not.toBeInTheDocument();
    expect(screen.queryByText("superadmin")).not.toBeInTheDocument();
    await clickFirstResourceSelectButton();
    expect(await screen.findByText("sample_id")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查询并加载" }));

    await waitFor(() => {
      expect(mockApi.queryResource).toHaveBeenCalledWith(tarimVectorResource, {
        attributeFilters: [],
        spatialFilter: null,
        limit: 30000,
      });
    });
    fireEvent.click(screen.getByRole("tab", { name: /图层/ }));
    await waitFor(() => {
      const rangeSwitches = screen
        .getAllByRole("switch")
        .filter((item) => item.getAttribute("aria-label")?.includes("范围"));
      expect(rangeSwitches.length).toBeGreaterThan(0);
    });

    const adminButton = screen.getByRole("button", { name: /后台管理/ });
    fireEvent.mouseEnter(adminButton);
    const logMenuItem = await screen.findByRole("menuitem", {
      name: "日志管理",
    });
    expect(logMenuItem).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: "用户管理" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: "角色权限" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: "系统设置" }),
    ).not.toBeInTheDocument();
    fireEvent.click(logMenuItem);

    expect(
      await screen.findByText("本人查询塔里木河样地数据"),
    ).toBeInTheDocument();
    expect(screen.queryByText("系统日志")).not.toBeInTheDocument();
    expect(screen.queryByText("超级管理员")).not.toBeInTheDocument();
    expect(screen.queryByText("superadmin")).not.toBeInTheDocument();
    expect(mockApi.adminSystemLogs).not.toHaveBeenCalled();
  }, 30000);

  it("keeps guest login from showing a spinner during account login", async () => {
    let resolveLogin: ((value: { user: User }) => void) | undefined;
    mockApi.login.mockReturnValue(
      new Promise((resolve) => {
        resolveLogin = resolve;
      }),
    );

    renderApp("/login");

    expect(
      await screen.findByRole("heading", { name: "用户登录" }),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("请输入账号"), {
      target: { value: "researcher" },
    });
    fireEvent.change(screen.getByPlaceholderText("请输入密码"), {
      target: { value: "pass12345" },
    });

    const loginButton = screen.getByRole("button", {
      name: /登录并进入数据平台$/,
    });
    const guestButton = screen.getByRole("button", { name: /游客登录/ });
    fireEvent.click(loginButton);

    await waitFor(() => {
      expect(mockApi.login).toHaveBeenCalled();
    });
    expect(guestButton).toBeDisabled();
    expect(guestButton).not.toHaveClass("ant-btn-loading");

    resolveLogin?.({ user: normalUser });
  });

  it("keeps account recovery on a loading state until the new identity is authorized", async () => {
    mockApi.me.mockResolvedValueOnce({ authenticated: true, user: normalUser });
    renderApp("/map");
    expect(
      await screen.findByTestId("map-canvas", {}, { timeout: 10000 }),
    ).toBeVisible();
    let complete!: (value: unknown) => void;
    mockApi.me.mockReturnValueOnce(
      new Promise((resolve) => {
        complete = resolve;
      }),
    );
    fireEvent(
      window,
      new CustomEvent("stisp:browser-session-ended", {
        detail: { reason: "account-changed" },
      }),
    );
    expect(
      await screen.findByRole("status", { name: "正在更新账号权限" }),
    ).toBeVisible();
    expect(screen.queryByTestId("map-canvas")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /账号登录/ }),
    ).not.toBeInTheDocument();
    complete({
      authenticated: true,
      user: { ...normalUser, id: 7, username: "next-account" },
    });
    expect(
      await screen.findByTestId("map-canvas", {}, { timeout: 10000 }),
    ).toBeVisible();
    expect(
      screen.queryByRole("status", { name: "正在更新账号权限" }),
    ).not.toBeInTheDocument();
  });

  it("allows authenticated users to enter the admin route", async () => {
    mockApi.me.mockResolvedValue({ authenticated: true, user: adminUser });

    renderApp("/admin");

    expect(
      await screen.findByTestId("pro-layout", {}, { timeout: 10000 }),
    ).toBeInTheDocument();
  });

  it.each([0, 503])(
    "retains verified login when a forbidden refresh fails with %s",
    async (status) => {
      mockApi.me.mockResolvedValueOnce({
        authenticated: true,
        user: normalUser,
      });
      renderApp("/map");
      expect(
        await screen.findByTestId("map-canvas", {}, { timeout: 10000 }),
      ).toBeVisible();
      mockApi.me.mockRejectedValueOnce(
        new MockApiError("临时连接失败", status),
      );
      const handler = vi
        .mocked(registerForbiddenHandler)
        .mock.calls.at(-1)?.[0];
      expect(handler).toBeDefined();
      await handler?.();
      fireEvent.click(screen.getByRole("button", { name: "用户信息" }));
      expect(document.querySelector(".user-button-name")).toHaveTextContent(
        "科研用户",
      );
      expect(
        screen.queryByRole("button", { name: "账号登录" }),
      ).not.toBeInTheDocument();
    },
  );

  it.each([401, 403])(
    "clears login after an explicit %s session refresh rejection",
    async (status) => {
      mockApi.me.mockResolvedValueOnce({
        authenticated: true,
        user: normalUser,
      });
      renderApp("/map");
      expect(
        await screen.findByTestId("map-canvas", {}, { timeout: 10000 }),
      ).toBeVisible();
      mockApi.me.mockRejectedValueOnce(new MockApiError("登录已失效", status));
      const handler = vi
        .mocked(registerForbiddenHandler)
        .mock.calls.at(-1)?.[0];
      await handler?.();
      await waitFor(() =>
        expect(document.querySelector(".user-button-name")).toHaveTextContent(
          "当前用户",
        ),
      );
    },
  );

  it("shows compact workspace navigation for privileged users", async () => {
    mockApi.me.mockResolvedValue({ authenticated: true, user: adminUser });

    renderApp("/");

    expect(
      await screen.findByTestId("map-canvas", {}, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^首页$/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^地理工作台$/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^数据分析$/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /后台管理/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /安全退出/ }),
    ).not.toBeInTheDocument();
  }, 30000);

  it("keeps first-time navigation unblocked and offers workspace guidance on demand", async () => {
    mockApi.me.mockResolvedValue({ authenticated: true, user: normalUser });

    renderApp("/map");

    expect(
      await screen.findByRole(
        "button",
        { name: /^数据资源$/ },
        { timeout: 10000 },
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^地理工作台$/ })).toBeEnabled();
    expect(screen.queryByText("🎉 欢迎 🎉")).not.toBeInTheDocument();
    expect(screen.queryByText("全局搜索")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "用户信息" }));
    fireEvent.click(await screen.findByRole("button", { name: /显示引导/ }));

    expect(
      await screen.findByText("🎉 欢迎 🎉", {}, { timeout: 10000 }),
    ).toBeInTheDocument();
  });
});
