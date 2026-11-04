import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { MemoryRouter, Navigate, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppContext } from "../contexts/AppContext";
import { platformApi } from "../api/platform";
import { applyPlatformDocumentTitle } from "../config/platformBrand";
import {
  RequireDataInventory,
  RequireDataUpload,
  RequireManageDataBackup,
  RequireManageProjects,
  RequireManageSystemSettings,
} from "../router";
import { appTheme } from "../theme";
import type {
  AdminDataResourceList,
  AdminSettings,
  Bootstrap,
  User,
} from "../types";

import AdminAuthPage from "./AdminAuthPage";
import AdminDataBackupPage from "./AdminDataBackupPage";
import AdminDashboardPage from "./AdminDashboardPage";
import AdminDataImportPage, {
  effectiveTableUploadMaxMb,
  effectiveVectorUploadMaxMb,
} from "./AdminDataImportPage";
import AdminDataInventoryPage from "./AdminDataInventoryPage";
import AdminLayout from "./AdminLayout";
import AdminOperationLogsPage from "./AdminOperationLogsPage";
import AdminProfilePage from "./AdminProfilePage";
import AdminSystemSettingsPage, {
  ADMIN_SETTING_RANGES,
  mergeSettingValues,
} from "./AdminSystemSettingsPage";
import AdminTopicCompositionManagementPage from "./AdminTopicCompositionManagementPage";
import AdminWorkspaceManagementPage from "./AdminWorkspaceManagementPage";
import ResourceLayout from "../resource/ResourceLayout";
import { fallbackTaxonomyTree } from "../utils/taxonomy";

const mockApi = vi.hoisted(() => ({
  bootstrap: vi.fn(),
  logout: vi.fn(),
  adminProfile: vi.fn(),
  updateAdminProfile: vi.fn(),
  updateAdminProfilePermissions: vi.fn(),
  updateAdminProfilePassword: vi.fn(),
  adminOperationLogs: vi.fn(),
  adminSystemLogs: vi.fn(),
  adminUsers: vi.fn(),
  roleApplications: vi.fn(),
  reviewRoleApplication: vi.fn(),
  createAdminUser: vi.fn(),
  updateAdminUserGroups: vi.fn(),
  updateAdminUser: vi.fn(),
  resetAdminUserPassword: vi.fn(),
  deleteAdminUser: vi.fn(),
  adminGroups: vi.fn(),
  createAdminGroup: vi.fn(),
  updateAdminGroup: vi.fn(),
  deleteAdminGroup: vi.fn(),
  adminSettings: vi.fn(),
  updateAdminSettings: vi.fn(),
  adminBackupOverview: vi.fn(),
  adminBackupSettings: vi.fn(),
  updateAdminBackupSettings: vi.fn(),
  testAdminBackupTarget: vi.fn(),
  adminBackupRuns: vi.fn(),
  createAdminBackupRun: vi.fn(),
  adminBackupRun: vi.fn(),
  downloadAdminBackupRun: vi.fn(),
  importPreview: vi.fn(),
  importValidate: vi.fn(),
  importCommit: vi.fn(),
  previewRasterImport: vi.fn(),
  importRaster: vi.fn(),
  rasterJob: vi.fn(),
  adminDataResources: vi.fn(),
  updateAdminDataResource: vi.fn(),
  createAdminDataResourceGroup: vi.fn(),
  updateAdminDataResourceGroup: vi.fn(),
  exportAdminDataResources: vi.fn(),
  dataSchemaSummary: vi.fn(),
  germplasmAccessions: vi.fn(),
  resources: vi.fn(),
  workspaces: vi.fn(),
  adminWorkspaces: vi.fn(),
  updateAdminWorkspace: vi.fn(),
  mapCompositions: vi.fn(),
  resultArtifacts: vi.fn(),
  downloadResultArtifact: vi.fn(),
  updateResultArtifact: vi.fn(),
  createResultArtifact: vi.fn(),
  adminDashboard: vi.fn(),
  adminDashboardServer: vi.fn(),
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
  ApiError: class ApiError extends Error {},
  api: mockApi,
}));

const bootstrap: Bootstrap = {
  systemName: "全球胡杨林生态系统保护数据共享平台",
  allowRegistration: false,
  map: {
    defaultCenter: [87.6, 41.7],
    defaultZoom: 6.5,
    defaultBasemap: "satellite",
    mapboxAccessToken: "",
    tiandituAccessToken: "",
  },
  limits: {
    uploadMaxMb: 64,
    queryResultLimit: 5000,
    maxRasterSidePixels: 12000,
  },
};

function inventoryResponseMeta({
  total,
  activeCount = total,
  inactiveCount = 0,
  restrictedCount = 0,
  sizeBytes = 0,
  itemCount = 0,
  categoryCode = "spatial",
  rootCategoryCode = "spatial",
}: {
  total: number;
  activeCount?: number;
  inactiveCount?: number;
  restrictedCount?: number;
  sizeBytes?: number;
  itemCount?: number;
  categoryCode?: string | null;
  rootCategoryCode?: string;
}): Pick<
  AdminDataResourceList,
  "summary" | "groupSummaries" | "inventoryGroups"
> {
  return {
    summary: {
      total,
      activeCount,
      inactiveCount,
      restrictedCount,
      sizeBytes,
      itemCount,
    },
    groupSummaries: [
      {
        key: "__all__",
        kind: "all",
        domainType: null,
        categoryCode: null,
        inventoryGroupId: null,
        resourceCount: total,
        activeCount,
        inactiveCount,
        sizeBytes,
        itemCount,
      },
      ...(categoryCode
        ? [
            {
              key: `__category__:${rootCategoryCode}`,
              kind: "category" as const,
              domainType: null,
              categoryCode: rootCategoryCode,
              inventoryGroupId: null,
              resourceCount: total,
              activeCount,
              inactiveCount,
              sizeBytes,
              itemCount,
            },
            {
              key: `__category__:${categoryCode}`,
              kind: "category" as const,
              domainType: null,
              categoryCode,
              inventoryGroupId: null,
              resourceCount: total,
              activeCount,
              inactiveCount,
              sizeBytes,
              itemCount,
            },
          ]
        : [
            {
              key: "__unclassified__",
              kind: "unclassified" as const,
              domainType: null,
              categoryCode: null,
              inventoryGroupId: null,
              resourceCount: total,
              activeCount,
              inactiveCount,
              sizeBytes,
              itemCount,
            },
          ]),
    ],
    inventoryGroups: [],
  };
}

const adminResourceClassification = {
  category: {
    id: 31,
    type: "data_category",
    code: "distribution_vector",
    name: "分布矢量",
    parentId: 3,
    selectable: true,
  },
  categoryPath: [
    { id: 3, code: "distribution", name: "胡杨空间分布信息" },
    { id: 31, code: "distribution_vector", name: "分布矢量" },
  ],
  classificationStatus: "classified" as const,
};

const adminUser: User = {
  id: 1,
  username: "admin",
  displayName: "系统管理员",
  email: "admin@example.local",
  avatarUrl: "",
  department: "平台运维组",
  isStaff: false,
  isSuperuser: false,
  roles: ["系统管理员"],
  groupIds: [1],
  isActive: true,
  operationLogGroupIds: [],
  permissions: {
    canAccessAdmin: true,
    canManageFeaturePermissions: true,
    canCreateUser: true,
    canViewOperationLogs: true,
    canViewAllOperationLogs: true,
    canViewOwnOperationLogs: true,
    canViewGroupOperationLogs: true,
    canViewSystemLogs: true,
    canManageSystemSettings: true,
    canManageDataBackup: true,
    canManageAuth: true,
    canViewDashboardResourceCard: true,
    canViewDashboardLayerCard: true,
    canViewDashboardRasterCard: true,
    canViewDashboardUserCard: true,
    canViewDashboardActiveUsersCard: true,
    canViewDashboardSystemCard: true,
    canViewDataOverview: true,
    canBrowseData: true,
    canQueryData: true,
    canUploadData: true,
    canViewDataResources: true,
    canCreateDataResources: true,
    canChangeDataResources: true,
    canDeleteDataResources: true,
    canLoadVectorLayer: true,
    canLoadRasterLayer: true,
    canUseCustomSymbolization: true,
    canExportData: true,
    canViewWorkspaces: true,
    canCreateWorkspaces: true,
    canChangeWorkspaces: true,
    canDeleteWorkspaces: true,
    canManageRasterData: true,
    canViewMapCompositions: true,
    canCreateMapCompositions: true,
    canChangeMapCompositions: true,
    canDeleteMapCompositions: true,
    canExportMapCompositions: true,
    canPublishMapCompositions: true,
    canRestoreMapCompositions: true,
    canViewResultArtifacts: true,
    canImportResultArtifacts: true,
    canDownloadResultArtifacts: true,
    canPublishResultArtifacts: true,
    canDeleteResultArtifacts: true,
  },
};

const availablePermissions = [
  {
    id: "core.manage_feature_permissions",
    label: "配置功能权限",
    group: "人员权限",
  },
  { id: "core.create_user", label: "新建用户", group: "人员权限" },
  { id: "core.view_operation_logs", label: "查看操作日志", group: "后台权限" },
  { id: "core.view_system_logs", label: "查看系统日志", group: "后台权限" },
  {
    id: "core.view_all_operation_logs",
    label: "查看所有用户日志",
    group: "日志权限",
  },
  {
    id: "core.view_own_operation_logs",
    label: "查看自己的日志",
    group: "日志权限",
  },
  {
    id: "core.view_group_operation_logs",
    label: "查看指定角色日志",
    group: "日志权限",
  },
  {
    id: "core.manage_system_settings",
    label: "修改系统设置",
    group: "后台权限",
  },
  {
    id: "core.manage_data_backup",
    label: "管理数据备份",
    group: "后台权限",
  },
  { id: "core.manage_auth", label: "修改认证授权", group: "人员权限" },
  {
    id: "core.view_dashboard_resource_card",
    label: "查看概览数据资源卡片",
    group: "概览权限",
  },
  {
    id: "core.view_dashboard_layer_card",
    label: "查看概览图层数卡片",
    group: "概览权限",
  },
  {
    id: "core.view_dashboard_raster_card",
    label: "查看概览栅格数量卡片",
    group: "概览权限",
  },
  {
    id: "core.view_dashboard_user_card",
    label: "查看概览用户数量卡片",
    group: "概览权限",
  },
  {
    id: "core.view_dashboard_active_users_card",
    label: "查看概览活跃用户卡片",
    group: "概览权限",
  },
  {
    id: "core.view_dashboard_system_card",
    label: "查看概览系统信息",
    group: "概览权限",
  },
  { id: "core.browse_data", label: "浏览数据目录", group: "数据权限" },
  { id: "core.query_data", label: "查询数据", group: "数据权限" },
  {
    id: "catalog.export_dataresource",
    label: "导出数据资源",
    group: "数据权限",
  },
];

const grantedPermissions = availablePermissions.map(
  (permission) => permission.id,
);

const adminGroup = {
  id: 1,
  name: "系统管理员",
  userCount: 1,
  permissions: grantedPermissions,
  isProtected: true,
  lockedPermissions: [],
};

const adminApiUser = {
  ...adminUser,
  groupIds: [adminGroup.id],
  isActive: true,
  directPermissions: [],
  effectivePermissions: grantedPermissions,
  operationLogGroupIds: [],
};

const adminSettings: AdminSettings = {
  systemName: bootstrap.systemName,
  allowRegistration: bootstrap.allowRegistration,
  map: bootstrap.map,
  limits: bootstrap.limits,
  raster: {
    symbolizerTimeoutSeconds: 120,
  },
  editable: true,
};

const backupRun = {
  id: 1,
  planType: "platform",
  targetType: "local",
  trigger: "manual",
  status: "success",
  progressPercent: 100,
  messages: ["本地备份已保存"],
  result: { fileCount: 2 },
  error: "",
  archiveName: "platform-backup-20260703030000.zip",
  sizeBytes: 2048,
  checksumSha256: "abc123",
  objectKey: "",
  localPath: "platform/platform-backup-20260703030000.zip",
  createdBy: "系统管理员",
  createdAt: "2026-07-03T03:00:00+08:00",
  startedAt: "2026-07-03T03:00:01+08:00",
  finishedAt: "2026-07-03T03:00:10+08:00",
} as const;

const backupSettings = {
  plans: {
    platform: {
      enabled: true,
      dailyAt: "03:00",
      target: "local",
      retentionCount: 3,
      includeLogs: false,
    },
    research: {
      enabled: false,
      dailyAt: "02:00",
      target: "object_storage",
      retentionCount: 7,
      includeLogs: false,
    },
  },
  local: {
    directory: "",
    configured: true,
  },
  objectStorage: {
    provider: "s3_compatible",
    endpoint: "https://s3.example.com",
    region: "cn-north-1",
    bucket: "geomanager-backups",
    prefix: "prod/",
    accessKeyId: "backup-service",
    secretConfigured: true,
    secretPreview: "******1234",
    configured: true,
  },
  updatedAt: "2026-07-03T10:20:00+08:00",
} as const;

const backupOverview = {
  settings: backupSettings,
  summaries: [
    {
      planType: "research",
      label: "科研数据",
      source: "科研数据根目录",
      available: true,
      fileCount: 12,
      sizeBytes: 4096,
    },
    {
      planType: "platform",
      label: "平台数据",
      source: "业务数据根目录",
      available: true,
      fileCount: 8,
      sizeBytes: 2048,
    },
  ],
  activeRuns: [],
  recentRuns: [backupRun],
  generatedAt: "2026-07-03T10:20:00+08:00",
} as const;

const emptySpatialSummary = {
  spatialResourceCount: 0,
  missingSpatialResourceCount: 0,
  totalBounds: [],
  resourceExtents: [],
  resourceExtentsTruncated: false,
  coverageRanking: [],
  heatmapCells: [],
};

function makeCategoryBreakdown(
  counts: Partial<
    Record<"baseGeo" | "habitat" | "distribution" | "thematic", number>
  > = {},
) {
  const category = (
    categoryCode: string,
    categoryName: string,
    count: number,
    childNames: Array<[string, string]>,
  ) => ({
    categoryCode,
    categoryName,
    count,
    sizeBytes: 0,
    itemCount: 0,
    children: childNames.map(([code, name], index) => ({
      categoryCode: code,
      categoryName: name,
      count: index === 0 ? count : 0,
      sizeBytes: 0,
      itemCount: 0,
    })),
  });
  return [
    category("base_geo", "基础地理信息数据", counts.baseGeo ?? 0, [
      ["base_geo_admin", "行政区划"],
      ["base_geo_elements", "基础地理要素"],
      ["base_geo_lucc", "LUCC"],
    ]),
    category("habitat", "胡杨生境数据", counts.habitat ?? 0, [
      ["habitat_water", "水"],
      ["habitat_soil", "土壤"],
      ["habitat_climate", "气候"],
      ["habitat_biotic", "生物环境"],
    ]),
    category("distribution", "胡杨空间分布信息", counts.distribution ?? 0, [
      ["distribution_vector", "分布矢量"],
      ["distribution_survey_image", "调查点图片"],
    ]),
    category("thematic", "胡杨专题数据", counts.thematic ?? 0, [
      ["thematic_gene_germplasm", "基因与种质"],
      ["thematic_individual", "个体"],
      ["thematic_population", "种群"],
      ["thematic_community", "群落"],
      ["thematic_ecosystem", "生态系统"],
      ["thematic_landscape_rs", "景观与遥感"],
    ]),
  ];
}

function hoverElement(element: Element) {
  fireEvent.pointerEnter(element);
  fireEvent.mouseOver(element);
  fireEvent.mouseEnter(element);
}

function renderAdminRoute(initialEntry: string, user: User = adminUser) {
  return render(
    <AdminTestProviders user={user}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/" element={<div>业务入口</div>} />
          <Route path="/resources" element={<ResourceLayout />}>
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route
              path="dashboard"
              element={<AdminDashboardPage scope="data" />}
            />
            <Route element={<RequireDataInventory />}>
              <Route
                path="data/inventory"
                element={<AdminDataInventoryPage />}
              />
              <Route
                path="manage/projects"
                element={<AdminWorkspaceManagementPage kind="project" />}
              />
              <Route
                path="manage/topics"
                element={<AdminTopicCompositionManagementPage />}
              />
            </Route>
            <Route element={<RequireDataUpload />}>
              <Route path="data/import" element={<AdminDataImportPage />} />
            </Route>
          </Route>
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route
              path="dashboard"
              element={<AdminDashboardPage scope="operations" />}
            />
            <Route path="profile" element={<AdminProfilePage />} />
            <Route element={<RequireManageProjects />}>
              <Route path="projects" element={<div>项目标签与成员分配</div>} />
            </Route>
            <Route path="logs" element={<AdminOperationLogsPage />} />
            <Route element={<RequireManageSystemSettings />}>
              <Route path="settings" element={<AdminSystemSettingsPage />} />
            </Route>
            <Route element={<RequireManageDataBackup />}>
              <Route path="backup" element={<AdminDataBackupPage />} />
            </Route>
            <Route path="auth" element={<Navigate to="users" replace />} />
            <Route path="auth/users" element={<AdminAuthPage />} />
            <Route path="auth/groups" element={<AdminAuthPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AdminTestProviders>,
  );
}

function renderWithProviders(
  children: React.ReactNode,
  user: User = adminUser,
) {
  return render(
    <AdminTestProviders user={user}>{children}</AdminTestProviders>,
  );
}

function AdminTestProviders({
  children,
  user = adminUser,
}: {
  children: React.ReactNode;
  user?: User;
}) {
  return (
    <ConfigProvider locale={zhCN} theme={appTheme}>
      <AntApp>
        <AppContext.Provider
          value={{
            bootstrap,
            user,
            setBootstrap: vi.fn(),
            setUser: vi.fn(),
          }}
        >
          {children}
        </AppContext.Provider>
      </AntApp>
    </ConfigProvider>
  );
}

describe("admin routes", () => {
  it.each(["zh-CN", "en-US"] as const)(
    "preserves the platform browser title in %s across layouts",
    async (locale) => {
      const title = applyPlatformDocumentTitle(undefined, locale);
      const admin = renderAdminRoute("/admin/profile");
      await waitFor(() => expect(mockApi.adminProfile).toHaveBeenCalled());
      expect(document.title).toBe(title);
      admin.unmount();
      renderAdminRoute("/resources/manage/projects");
      await waitFor(() => expect(mockApi.adminWorkspaces).toHaveBeenCalled());
      expect(document.title).toBe(title);
    },
  );

  it("places project management in the superadmin sidebar", async () => {
    renderAdminRoute("/admin/projects", { ...adminUser, isSuperuser: true });
    expect(await screen.findByText("项目标签与成员分配")).toBeVisible();
    expect(
      await screen.findByRole("link", { name: /项目管理/ }),
    ).toHaveAttribute("href", "/admin/projects");
  });

  it("hides and guards project management for an ordinary administrator", async () => {
    renderAdminRoute("/admin/projects");
    await waitFor(() => expect(mockApi.adminProfile).toHaveBeenCalled());
    expect(
      screen.queryByRole("link", { name: /项目管理/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("项目标签与成员分配")).not.toBeInTheDocument();
  });

  beforeEach(() => {
    for (const fn of Object.values(mockApi)) {
      fn.mockReset();
    }
    vi.mocked(platformApi.projects).mockReset().mockResolvedValue({
      items: [],
      canManage: false,
      canAssign: false,
      defaultProjectId: null,
    });
    window.localStorage.setItem(
      `huyang-system.workspace-tour.v1.${adminUser.id}.${adminUser.username}`,
      "completed",
    );
    mockApi.bootstrap.mockResolvedValue(bootstrap);
    mockApi.logout.mockResolvedValue({ detail: "已退出" });
    mockApi.resources.mockResolvedValue({ items: [] });
    mockApi.workspaces.mockResolvedValue({ items: [] });
    mockApi.adminProfile.mockResolvedValue({
      user: adminUser,
      avatarUrl: "",
      department: "平台运维组",
      grantedPermissions,
      disabledPermissions: [],
      effectivePermissions: grantedPermissions,
      availablePermissions,
    });
    mockApi.updateAdminProfilePermissions.mockImplementation((payload) =>
      Promise.resolve({
        user: adminUser,
        avatarUrl: "",
        department: "平台运维组",
        grantedPermissions,
        disabledPermissions: payload.disabledPermissions,
        effectivePermissions: grantedPermissions.filter(
          (permission) => !payload.disabledPermissions.includes(permission),
        ),
        availablePermissions,
      }),
    );
    mockApi.updateAdminProfilePassword.mockResolvedValue({
      detail: "密码已更新",
    });
    mockApi.adminUsers.mockResolvedValue({ items: [adminApiUser] });
    mockApi.roleApplications.mockResolvedValue({ items: [] });
    mockApi.updateAdminUser.mockImplementation((userId, payload) =>
      Promise.resolve({
        ...adminApiUser,
        id: userId,
        isActive: payload.isActive,
      }),
    );
    mockApi.resetAdminUserPassword.mockResolvedValue({
      ...adminApiUser,
      generatedPassword: "Abc123!@",
    });
    mockApi.deleteAdminUser.mockResolvedValue({ detail: "用户已删除" });
    mockApi.adminOperationLogs.mockResolvedValue({ items: [], total: 0 });
    mockApi.adminSystemLogs.mockResolvedValue({
      files: [],
      selectedFile: "",
      lines: 500,
      content: "",
      generatedAt: "2026-06-20T09:45:10+08:00",
    });
    mockApi.adminGroups.mockResolvedValue({
      items: [adminGroup],
      availablePermissions,
    });
    mockApi.reviewRoleApplication.mockImplementation((applicationId, payload) =>
      Promise.resolve({
        id: applicationId,
        userId: 8,
        requestedRole: "research",
        status: payload.action === "approve" ? "approved" : "rejected",
        reason: "需要上传长期监测数据",
        reviewNote: payload.reviewNote,
        createdAt: "2026-07-14T10:30:00+08:00",
        reviewedAt: "2026-07-14T11:00:00+08:00",
        user: {
          id: 8,
          username: "research_applicant",
          displayName: "张研究员",
          email: "research.applicant@example.com",
          department: "生态监测组",
        },
        reviewer: {
          id: 1,
          username: "admin",
          displayName: "系统管理员",
          email: "admin@example.local",
          department: "平台运维组",
        },
      }),
    );
    mockApi.adminSettings.mockResolvedValue(adminSettings);
    mockApi.updateAdminSettings.mockResolvedValue(adminSettings);
    mockApi.adminBackupOverview.mockResolvedValue(backupOverview);
    mockApi.adminBackupSettings.mockResolvedValue(backupSettings);
    mockApi.updateAdminBackupSettings.mockResolvedValue(backupSettings);
    mockApi.testAdminBackupTarget.mockResolvedValue({
      targetType: "local",
      status: "success",
      message: "备份目标连接测试成功",
      testedAt: "2026-07-03T10:20:00+08:00",
    });
    mockApi.adminBackupRuns.mockResolvedValue({ items: [backupRun], total: 1 });
    mockApi.createAdminBackupRun.mockResolvedValue({
      ...backupRun,
      id: 2,
      status: "queued",
      progressPercent: 0,
      messages: ["备份任务已创建"],
    });
    mockApi.adminBackupRun.mockResolvedValue(backupRun);
    mockApi.downloadAdminBackupRun.mockResolvedValue({
      blob: new Blob(["backup"]),
      filename: "platform-backup.zip",
    });
    mockApi.adminDashboard.mockResolvedValue({
      generatedAt: "2026-06-07T20:00:00+08:00",
      cards: {
        resources: { total: 2, active: 2 },
        layers: { total: 1, active: 1 },
        rasters: { resources: 1, datasets: 1, layers: 1 },
        dataOverview: {
          totalResources: 2,
          activeResources: 2,
          totalSizeBytes: 3072,
          totalItemCount: 12,
          typeBreakdown: [
            { dataType: "vector", count: 1, sizeBytes: 1024, itemCount: 8 },
            { dataType: "raster", count: 1, sizeBytes: 2048, itemCount: 4 },
          ],
          ownUploads: {
            totalResources: 1,
            activeResources: 1,
            totalSizeBytes: 1024,
            totalItemCount: 8,
            typeBreakdown: [
              { dataType: "vector", count: 1, sizeBytes: 1024, itemCount: 8 },
            ],
            categoryBreakdown: makeCategoryBreakdown({ distribution: 1 }),
            unclassifiedCount: 0,
            spatialSummary: emptySpatialSummary,
          },
          visibleResources: {
            totalResources: 2,
            activeResources: 2,
            totalSizeBytes: 3072,
            totalItemCount: 12,
            typeBreakdown: [
              { dataType: "vector", count: 1, sizeBytes: 1024, itemCount: 8 },
              { dataType: "raster", count: 1, sizeBytes: 2048, itemCount: 4 },
            ],
            categoryBreakdown: makeCategoryBreakdown({
              baseGeo: 1,
              distribution: 1,
            }),
            unclassifiedCount: 0,
            spatialSummary: emptySpatialSummary,
          },
        },
        users: {
          total: 2,
          active: 2,
          disabled: 0,
          groups: 3,
          vectorResources: 1,
          tableResources: 0,
        },
        activeUsers: {
          period: "day",
          rangeStart: "2026-06-07",
          rangeEnd: "2026-06-07",
          count: 1,
          loginCount: 2,
          series: Array.from({ length: 24 }, (_, hour) => ({
            key: String(hour),
            label: `${String(hour).padStart(2, "0")}:00`,
            count: hour === 9 ? 1 : 0,
          })),
          ranking: [
            {
              userId: 2,
              displayName: "活跃用户",
              username: "active-user",
              loginCount: 2,
            },
          ],
        },
      },
    });
    mockApi.adminDashboardServer.mockResolvedValue({
      generatedAt: "2026-06-07T20:00:00+08:00",
      hostname: "test-host",
      platform: "Darwin",
      cards: {
        cpu: {
          model: "Apple M",
          physicalCount: 8,
          logicalCount: 8,
          usagePercent: 32,
          loadAverage: [2.1, 1.8, 1.5],
        },
        memory: {
          model: "系统内存",
          slotCount: 1,
          totalBytes: 17179869184,
          usedBytes: 8589934592,
          availableBytes: 8589934592,
          usagePercent: 50,
        },
        disks: {
          count: 1,
          devices: [{ name: "disk0", model: "APPLE SSD", size: "512 GB" }],
          mount: "/Users/gx/Documents/Source/huyang_system",
          totalBytes: 512000000000,
          usedBytes: 256000000000,
          freeBytes: 256000000000,
          usagePercent: 50,
        },
      },
    });
    mockApi.dataSchemaSummary.mockResolvedValue({
      taxonomyVersion: "2026.07",
      catalogTree: fallbackTaxonomyTree,
      domains: [
        {
          code: "germplasm",
          name: "种质数据",
          spatialClass: "spatialized_table",
          description: "种质资源及样品来源管理。",
          recommendedResourceTypes: ["vector", "gene", "table"],
          coreEntities: ["GermplasmAccession", "BiologicalSample", "Site"],
        },
        {
          code: "genome",
          name: "基因组数据",
          spatialClass: "non_spatial",
          description: "测序、组装、变异和注释等非地理组学成果。",
          recommendedResourceTypes: ["gene", "table"],
          coreEntities: ["GenomeDataset", "GenomeSequenceFile"],
        },
        {
          code: "individual",
          name: "个体数据",
          spatialClass: "spatial",
          description: "单株个体位置、性别和健康状态。",
          recommendedResourceTypes: ["vector", "table"],
          coreEntities: ["IndividualOrganism", "TraitObservation"],
        },
        {
          code: "community",
          name: "群落数据",
          spatialClass: "spatialized_table",
          description: "样方、群落组成和多样性指标。",
          recommendedResourceTypes: ["vector", "table"],
          coreEntities: ["SamplePlot", "CommunitySurvey"],
        },
        {
          code: "population",
          name: "种群数据",
          spatialClass: "spatial",
          description: "种群范围、调查事件和种群指标。",
          recommendedResourceTypes: ["vector", "table"],
          coreEntities: ["PopulationUnit", "SamplePlot"],
        },
        {
          code: "field_survey",
          name: "野外调查数据",
          spatialClass: "spatialized_table",
          description: "调查任务、路线、样点和采集记录。",
          recommendedResourceTypes: ["vector", "table", "image"],
          coreEntities: ["SurveyEvent", "FieldObservation"],
        },
        {
          code: "remote_sensing",
          name: "遥感影像数据",
          spatialClass: "spatial",
          description: "遥感影像、指数产品和变化检测成果。",
          recommendedResourceTypes: ["raster", "vector"],
          coreEntities: ["RasterDataset", "RemoteSensingProduct"],
        },
        {
          code: "molecular",
          name: "分子数据",
          spatialClass: "non_spatial",
          description: "DNA/RNA 提取、PCR 和分子标记结果。",
          recommendedResourceTypes: ["gene", "table", "document"],
          coreEntities: ["MolecularSample", "MolecularAssay"],
        },
        {
          code: "other",
          name: "其他类型",
          spatialClass: "spatialized_table",
          description: "暂未归入专门专题的数据资源。",
          recommendedResourceTypes: ["vector", "table", "document", "image"],
          coreEntities: ["DataResource", "SourceDataset", "SourceSheet"],
        },
      ],
      layers: [
        {
          name: "平台管理元数据层",
          storage: "metadata.sqlite3",
          description: "保存资源、权限、目录和日志。",
        },
        {
          name: "生态业务语义层",
          storage: "Django 主库",
          description: "保存样方、个体、种质、样品等标准实体。",
        },
      ],
      entities: [
        {
          name: "GermplasmAccession",
          label: "种质资源",
          domainTypes: ["germplasm"],
          description: "连接样品、物种和采集地。",
          keyFields: ["accession_code", "sample_code", "source_site_id"],
        },
        {
          name: "SamplePlot",
          label: "样方/样点",
          domainTypes: ["community", "field_survey"],
          description: "群落调查和野外调查的空间锚点。",
          keyFields: ["plot_code", "longitude", "latitude"],
        },
        {
          name: "GenericImportedDataset",
          label: "其他导入数据",
          domainTypes: ["other"],
          description: "承接暂未归入专门业务专题的数据资源。",
          keyFields: ["data_resource_id", "source_file_name", "sheet_name"],
        },
      ],
      legacyCatalogTree: [
        {
          code: "geo",
          name: "地理数据",
          domainType: null,
          spatialClass: "spatial",
          children: [
            {
              code: "geo-field-survey",
              name: "野外调查数据",
              domainType: "field_survey",
              spatialClass: "spatialized_table",
              children: [],
            },
            {
              code: "geo-remote-sensing",
              name: "遥感影像数据",
              domainType: "remote_sensing",
              spatialClass: "spatial",
              children: [],
            },
            {
              code: "geo-other",
              name: "其他类型",
              domainType: "other",
              spatialClass: "spatialized_table",
              children: [],
            },
          ],
        },
        {
          code: "nongeo",
          name: "非地理数据",
          domainType: null,
          spatialClass: "non_spatial",
          children: [
            {
              code: "nongeo-molecular",
              name: "分子数据",
              domainType: "molecular",
              spatialClass: "non_spatial",
              children: [],
            },
            {
              code: "nongeo-genome",
              name: "基因组数据",
              domainType: "genome",
              spatialClass: "non_spatial",
              children: [],
            },
            {
              code: "nongeo-other",
              name: "其他类型",
              domainType: "other",
              spatialClass: "non_spatial",
              children: [],
            },
          ],
        },
      ],
    });
    mockApi.germplasmAccessions.mockResolvedValue({
      items: [],
      total: 0,
      current: 1,
      pageSize: 5,
    });
    mockApi.importPreview.mockResolvedValue({
      suggestedName: "样地调查点位",
      suggestedTableName: "sample_points",
      columns: ["plot_id", "longitude", "latitude", "height"],
      rowCount: 1,
      rows: [
        {
          plot_id: "P001",
          longitude: "87.6",
          latitude: "41.7",
          height: "3.2",
        },
      ],
      limitations: ["Excel 只读取第一张表；所有字段按文本读取。"],
      detected: {
        isGeographic: true,
        longitudeColumn: "longitude",
        latitudeColumn: "latitude",
        coordinateStats: null,
        validationIssues: [],
      },
      duplicateTarget: null,
    });
    mockApi.importValidate.mockResolvedValue({
      coordinateStats: {
        totalRows: 1,
        validRows: 1,
        missingRows: 0,
        quantizationErrorMeters: { min: 1.1, max: 1.1 },
      },
      validationIssues: [],
    });
    mockApi.importCommit.mockResolvedValue({
      resourceId: 1,
      resourceName: "样地调查点位",
      importedRows: 1,
      validationIssues: [],
    });
    mockApi.previewRasterImport.mockResolvedValue({
      primaryFileName: "raster.tif",
      sourceFormat: "GTiff",
      files: [{ name: "raster.tif", size: 1024, role: "primary" }],
      metadata: {
        size: [256, 128],
        driver: "GTiff",
        coordinateSystem: 32645,
        bands: [
          {
            band: 1,
            type: "Byte",
            description: "Band 1",
            colorInterpretation: "Gray",
            min: 0,
            max: 255,
            isInteger: true,
          },
        ],
      },
      bounds4326: [88, 40, 88.1, 40.1],
      defaultRules: { mode: "gray", bands: [1] },
      suggestedName: "raster",
      rasterKind: "continuous",
      resampling: "bilinear",
      warnings: [],
    });
    mockApi.importRaster.mockImplementation(
      (
        _files: File[],
        _payload: Record<string, unknown>,
        onUploadProgress?: (percent: number) => void,
      ) => {
        onUploadProgress?.(42);
        return Promise.resolve({
          id: "raster-job-1",
          kind: "import",
          status: "running",
          stage: "preprocessing",
          progressPercent: 35,
          messages: ["已上传栅格文件", "开始 gdalwarp 预处理"],
          result: null,
          error: "",
          startedAt: 1782100000,
          finishedAt: null,
        });
      },
    );
    mockApi.rasterJob.mockResolvedValue({
      id: "raster-job-1",
      kind: "import",
      status: "ready",
      progressPercent: 100,
      messages: ["已上传栅格文件", "gdalwarp 预处理完成", "导入完成"],
      result: null,
      error: "",
      startedAt: 1782100000,
      finishedAt: 1782100005,
    });
    mockApi.adminDataResources.mockResolvedValue({
      items: [
        {
          id: 1,
          name: "胡杨林样地点",
          code: "populus-plots",
          dataType: "vector",
          domainType: "field_survey",
          category: null,
          ...adminResourceClassification,
          source: "用户导入",
          provider: "平台组",
          dataDate: "2026-06-01",
          spatialExtent: "87.600000,41.700000,87.800000,41.900000",
          coordinateSystem: "EPSG:4326",
          fileFormat: "GPKG",
          storagePath: "populus_plots",
          description: "样地点数据",
          qualityNote: "",
          defaultVisualization: {},
          status: "active",
          accessGroups: [],
          canManageAccess: true,
          maintainer: "系统管理员",
          createdAt: "2026-06-01T10:00:00+08:00",
          updatedAt: "2026-06-01T10:00:00+08:00",
          defaultLayer: null,
        },
      ],
      total: 1,
      ...inventoryResponseMeta({ total: 1 }),
      availableAccessGroups: [
        { id: 2, name: "科研用户", isGuest: false, isSuperadmin: false },
        { id: 3, name: "游客", isGuest: true, isSuperadmin: false },
      ],
    });
    mockApi.updateAdminDataResource.mockImplementation((resourceId, payload) =>
      Promise.resolve({
        id: resourceId,
        name: payload.name ?? "胡杨林样地点",
        code: "populus-plots",
        dataType: "vector",
        domainType: "field_survey",
        category: null,
        ...adminResourceClassification,
        source: "用户导入",
        provider: "平台组",
        dataDate: "2026-06-01",
        spatialExtent: "87.600000,41.700000,87.800000,41.900000",
        coordinateSystem: "EPSG:4326",
        fileFormat: "GPKG",
        storagePath: "populus_plots",
        description: "样地点数据",
        qualityNote: "",
        defaultVisualization: payload.visualization ?? {},
        status: payload.status ?? "active",
        accessGroups: [],
        canManageAccess: true,
        maintainer: "系统管理员",
        createdAt: "2026-06-01T10:00:00+08:00",
        updatedAt: "2026-06-01T10:00:00+08:00",
        defaultLayer: null,
      }),
    );
    mockApi.createAdminDataResourceGroup.mockResolvedValue({
      id: 9,
      name: "植被调查",
      createdAt: "2026-06-01T10:00:00+08:00",
      updatedAt: "2026-06-01T10:00:00+08:00",
    });
    mockApi.updateAdminDataResourceGroup.mockImplementation(
      (groupId, payload) =>
        Promise.resolve(
          payload.action === "delete"
            ? { detail: "数据资料夹已删除" }
            : {
                id: groupId,
                name: payload.name ?? "样地调查",
                createdAt: "2026-06-01T10:00:00+08:00",
                updatedAt: "2026-06-01T10:00:00+08:00",
              },
        ),
    );
    mockApi.exportAdminDataResources.mockResolvedValue({
      blob: new Blob(["数据名称\n胡杨林样地点"], { type: "text/csv" }),
      filename: "data-inventory.csv",
    });
    mockApi.adminWorkspaces.mockImplementation((filters) => {
      const kind = filters?.kind ?? "project";
      return Promise.resolve({
        items: [
          {
            id: kind === "project" ? 1 : 2,
            kind,
            name: kind === "project" ? "塔里木河样地工程" : "胡杨退化专题",
            description:
              kind === "project" ? "样地点和遥感底图组合" : "退化样地专题",
            snapshot: { version: 1, groups: [] },
            owner: {
              id: 1,
              username: "admin",
              displayName: "系统管理员",
            },
            createdAt: "2026-06-01T10:00:00+08:00",
            updatedAt: "2026-06-01T10:00:00+08:00",
            status: "active",
            accessGroups: [],
            isOwner: true,
            canEdit: true,
            canDelete: true,
            canManageAccess: true,
          },
        ],
        total: 1,
        availableAccessGroups: [
          { id: 2, name: "科研用户", isGuest: false, isSuperadmin: false },
        ],
      });
    });
    mockApi.mapCompositions.mockResolvedValue({
      items: [
        {
          id: 2,
          projectId: 1,
          projectName: "塔里木河样地工程",
          name: "胡杨退化专题",
          description: "退化样地专题",
          status: "completed",
          layout: {},
          owner: {
            id: 1,
            username: "admin",
            displayName: "系统管理员",
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
          createdAt: "2026-06-01T10:00:00+08:00",
          updatedAt: "2026-06-01T10:00:00+08:00",
        },
      ],
      availableAudienceGroups: [],
    });
    mockApi.resultArtifacts.mockResolvedValue({
      items: [
        {
          id: 7,
          name: "胡杨监测年度报告",
          description: "直接导入的年度成果报告",
          sourceType: "direct_import",
          resultType: "report",
          status: "published",
          category: {
            id: 31,
            type: "data_category",
            code: "thematic_population",
            name: "种群",
            parentId: 3,
            selectable: true,
          },
          categoryPath: [
            { id: 3, code: "thematic", name: "胡杨专题数据" },
            { id: 31, code: "thematic_population", name: "种群" },
          ],
          provider: "塔里木大学",
          fileName: "annual-report.pdf",
          fileFormat: "pdf",
          sizeBytes: 2048,
          previewUrl: "/api/catalog/results/7/file/?variant=preview",
          downloadUrl: "/api/catalog/results/7/file/?variant=artifact",
          owner: {
            id: 1,
            username: "admin",
            displayName: "系统管理员",
          },
          accessGroups: [],
          canPreview: true,
          canDownload: true,
          canPublish: true,
          canUnpublish: true,
          canDelete: true,
          publishedAt: "2026-07-23T10:00:00+08:00",
          publishedBy: {
            id: 1,
            username: "admin",
            displayName: "系统管理员",
          },
          createdAt: "2026-07-23T10:00:00+08:00",
          updatedAt: "2026-07-23T10:00:00+08:00",
        },
      ],
      availableAccessGroups: [],
    });
    mockApi.updateAdminWorkspace.mockImplementation((workspaceId, payload) =>
      Promise.resolve({
        id: workspaceId,
        kind: payload.kind ?? "project",
        name: payload.name ?? "塔里木河样地工程",
        description: payload.description ?? "样地点和遥感底图组合",
        snapshot: { version: 1, groups: [] },
        owner: {
          id: 1,
          username: "admin",
          displayName: "系统管理员",
        },
        createdAt: "2026-06-01T10:00:00+08:00",
        updatedAt: "2026-06-01T10:00:00+08:00",
        status: payload.status ?? "active",
        accessGroups: [],
        isOwner: true,
        canEdit: true,
        canDelete: true,
        canManageAccess: true,
      }),
    );
  });

  it("redirects /admin to operational dashboard", async () => {
    renderAdminRoute("/admin");

    expect(await screen.findByRole("button", { name: /后台管理/ })).toHaveClass(
      "workspace-switch-card-active",
    );
    expect(await screen.findByText("用户信息")).toBeInTheDocument();
    expect(screen.getByText("账号活跃与登录")).toBeInTheDocument();
    expect(screen.getByText("服务器信息")).toBeInTheDocument();
    expect(screen.queryByText("图层数")).not.toBeInTheDocument();
  });

  it("renders data overview in data management", async () => {
    renderAdminRoute("/resources");

    expect(
      await screen.findByRole("button", { name: /^数据资源$/ }),
    ).toHaveClass("workspace-switch-card-active");
    expect(
      await screen.findByRole("tab", { name: "我可见的" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "我上传的" })).toBeInTheDocument();
    expect(screen.getByText("我可见的数据概览")).toBeInTheDocument();
    expect(screen.getAllByText("数据资源").length).toBeGreaterThan(0);
    expect(screen.getByText("数据大小")).toBeInTheDocument();
    expect(screen.getByText("数据条目")).toBeInTheDocument();
    expect(screen.getByText("数据格式类型")).toBeInTheDocument();
    expect(screen.getByText("业务分类分布")).toBeInTheDocument();
    expect(screen.getAllByText("基础地理信息数据").length).toBeGreaterThan(0);
    expect(screen.getByText("景观与遥感")).toBeInTheDocument();
    expect(
      screen.getByText("空间覆盖排行").closest(".admin-spatial-side-panel"),
    ).not.toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "我上传的" }));

    expect(await screen.findByText("我上传的数据概览")).toBeInTheDocument();
    expect(screen.queryByText("用户信息")).not.toBeInTheDocument();
    expect(screen.queryByText("服务器信息")).not.toBeInTheDocument();
  });

  it("shows own upload overview without data overview permission", async () => {
    const uploadOnlyUser = {
      ...adminUser,
      permissions: {
        ...adminUser.permissions,
        canViewDataOverview: false,
      },
    };
    mockApi.adminDashboard.mockResolvedValueOnce({
      generatedAt: "2026-06-23T09:00:00+08:00",
      cards: {
        resources: { total: 2, active: 2 },
        layers: { total: 1, active: 1 },
        rasters: { resources: 1, datasets: 1, layers: 1 },
        dataOverview: {
          ownUploads: {
            totalResources: 1,
            activeResources: 1,
            totalSizeBytes: 1024,
            totalItemCount: 8,
            typeBreakdown: [
              { dataType: "vector", count: 1, sizeBytes: 1024, itemCount: 8 },
            ],
            categoryBreakdown: makeCategoryBreakdown({ distribution: 1 }),
            unclassifiedCount: 0,
            spatialSummary: emptySpatialSummary,
          },
        },
      },
    });

    renderAdminRoute("/resources", uploadOnlyUser);

    expect(
      await screen.findByRole("tab", { name: "我上传的" }),
    ).toBeInTheDocument();
    expect(screen.getByText("我上传的数据概览")).toBeInTheDocument();
    expect(screen.getByText("数据大小")).toBeInTheDocument();
    expect(screen.getByText("数据条目")).toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "我可见的" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("我可见的数据概览")).not.toBeInTheDocument();
  });

  it("navigates directly from the data management header dropdown", async () => {
    renderAdminRoute("/admin");

    const dataManagementButton = await screen.findByRole("button", {
      name: /^数据资源$/,
    });
    hoverElement(dataManagementButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "存量数据" }));

    expect(await screen.findByText("胡杨林样地点")).toBeInTheDocument();
    expect(screen.getByText("数据组织方式")).toBeInTheDocument();
    expect(screen.getAllByText("地理数据").length).toBeGreaterThan(0);
    expect(screen.getAllByText("非地理数据").length).toBeGreaterThan(0);
    expect(screen.queryByText("胡杨生境数据")).not.toBeInTheDocument();
  });

  it("submits the password change form from user settings", async () => {
    renderWithProviders(<AdminProfilePage />);

    fireEvent.click(await screen.findByText("修改密码"));
    fireEvent.change(screen.getByLabelText("当前密码"), {
      target: { value: "OldPass123" },
    });
    fireEvent.change(screen.getByLabelText("新密码"), {
      target: { value: "NewPass123" },
    });
    fireEvent.change(screen.getByLabelText("确认新密码"), {
      target: { value: "NewPass123" },
    });
    fireEvent.click(screen.getByRole("button", { name: /更新密码/ }));

    await waitFor(() => {
      expect(mockApi.updateAdminProfilePassword).toHaveBeenCalledWith({
        currentPassword: "OldPass123",
        newPassword: "NewPass123",
        passwordConfirm: "NewPass123",
      });
    });
  });

  it("navigates from operation logs to system settings", async () => {
    renderAdminRoute("/admin/logs");

    const settingsLinks = await screen.findAllByRole("link", {
      name: /系统设置/,
    });
    fireEvent.click(settingsLinks[0] as HTMLElement);

    expect(await screen.findAllByText("基础配置")).not.toHaveLength(0);
    expect(screen.getAllByText(bootstrap.systemName).length).toBeGreaterThan(0);
  });

  it("keeps safe system-setting ranges and merges a one-field edit", () => {
    expect(ADMIN_SETTING_RANGES).toEqual({
      uploadMaxMb: { min: 1, max: 1024 },
      queryResultLimit: { min: 100, max: 10_000 },
      maxRasterSidePixels: { min: 1, max: 12_000 },
      symbolizerTimeoutSeconds: { min: 10, max: 600 },
    });

    expect(mergeSettingValues(adminSettings, { uploadMaxMb: 1024 })).toEqual({
      systemName: adminSettings.systemName,
      allowRegistration: adminSettings.allowRegistration,
      defaultCenterLon: adminSettings.map.defaultCenter[0],
      defaultCenterLat: adminSettings.map.defaultCenter[1],
      defaultZoom: adminSettings.map.defaultZoom,
      defaultBasemap: adminSettings.map.defaultBasemap,
      mapboxAccessToken: adminSettings.map.mapboxAccessToken,
      tiandituAccessToken: adminSettings.map.tiandituAccessToken,
      uploadMaxMb: 1024,
      queryResultLimit: adminSettings.limits.queryResultLimit,
      maxRasterSidePixels: adminSettings.limits.maxRasterSidePixels,
      symbolizerTimeoutSeconds: adminSettings.raster.symbolizerTimeoutSeconds,
    });
    expect(effectiveTableUploadMaxMb(1024)).toBe(16);
    expect(effectiveTableUploadMaxMb(8)).toBe(8);
    expect(effectiveVectorUploadMaxMb(1024)).toBe(120);
    expect(effectiveVectorUploadMaxMb(64)).toBe(64);
  });

  it("saves a one-field system limit edit with the complete current settings", async () => {
    renderWithProviders(<AdminSystemSettingsPage />);

    const label = await screen.findByText("上传上限 MB");
    const item = label.closest(".ant-descriptions-item");
    expect(item).not.toBeNull();

    fireEvent.click(within(item!).getByLabelText("edit"));
    const input = within(item!).getByRole("spinbutton");
    expect(input).toHaveAttribute("aria-valuemax", "1024");
    fireEvent.change(input, { target: { value: "1024" } });
    fireEvent.click(within(item!).getByLabelText("check"));

    await waitFor(() => {
      expect(mockApi.updateAdminSettings).toHaveBeenCalledWith({
        systemName: adminSettings.systemName,
        allowRegistration: adminSettings.allowRegistration,
        map: adminSettings.map,
        limits: {
          ...adminSettings.limits,
          uploadMaxMb: 1024,
        },
        raster: adminSettings.raster,
      });
    });
  });

  it("keeps operation log UI scoped and hides system logs without permission", async () => {
    const logOnlyUser: User = {
      ...adminUser,
      permissions: {
        ...adminUser.permissions,
        canViewSystemLogs: false,
        canManageSystemSettings: false,
        canManageDataBackup: false,
        canManageAuth: false,
      },
    };
    mockApi.adminOperationLogs.mockResolvedValue({
      items: [
        {
          id: 18,
          occurredAt: "2026-06-20 11:12:13",
          operator: "李数据管理员",
          module: "数据管理",
          action: "导入数据",
          result: "success",
          targetType: "data_resource",
          targetId: 9,
          targetCode: "visible-resource",
          targetName: "可见样地数据",
          ipAddress: "203.0.113.8",
          summary: "可见导入日志",
        },
      ],
      total: 1,
    });

    renderAdminRoute("/admin/logs", logOnlyUser);

    expect(await screen.findByText("日志列表")).toBeInTheDocument();
    expect(await screen.findByText("可见导入日志")).toBeInTheDocument();
    expect(screen.queryByText("系统日志")).not.toBeInTheDocument();
    expect(screen.queryByText("超级管理员")).not.toBeInTheDocument();
    expect(screen.queryByText("superadmin")).not.toBeInTheDocument();
    expect(mockApi.adminSystemLogs).not.toHaveBeenCalled();
  });

  it("gates data backup separately from system settings", async () => {
    const settingsOnlyUser: User = {
      ...adminUser,
      permissions: {
        ...adminUser.permissions,
        canManageDataBackup: false,
      },
    };

    renderAdminRoute("/admin/settings", settingsOnlyUser);

    expect(await screen.findAllByText("基础配置")).not.toHaveLength(0);
    const adminButton = await screen.findByRole("button", {
      name: /后台管理/,
    });
    hoverElement(adminButton);
    expect(
      screen.queryByRole("menuitem", { name: "数据备份" }),
    ).not.toBeInTheDocument();

    const { unmount } = renderAdminRoute("/admin/settings", settingsOnlyUser);
    unmount();

    renderAdminRoute("/admin/backup", settingsOnlyUser);

    expect(await screen.findByText("个人信息")).toBeInTheDocument();
    expect(screen.queryByText("数据备份功能暂未实现")).not.toBeInTheDocument();
  }, 30000);

  it("renders the superadmin backup workspace from typed API data", async () => {
    renderAdminRoute("/admin/backup", adminUser);

    expect((await screen.findAllByText("备份目标")).length).toBeGreaterThan(0);
    expect(screen.getByText("科研数据备份")).toBeInTheDocument();
    expect(screen.getByText("平台数据备份")).toBeInTheDocument();
    expect(screen.getByText("geomanager-backups")).toBeInTheDocument();
    expect(
      screen.getByText("platform-backup-20260703030000.zip"),
    ).toBeInTheDocument();
    expect(mockApi.adminBackupOverview).toHaveBeenCalledOnce();
    expect(mockApi.adminBackupRuns).toHaveBeenCalledWith(
      {
        current: 1,
        pageSize: 20,
      },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  }, 30000);

  it("disables both manual backup actions while a backup is active", async () => {
    const runningRun = {
      ...backupRun,
      id: 8,
      status: "running",
      progressPercent: 35,
      messages: ["正在归档平台数据"],
      finishedAt: null,
    } as const;
    mockApi.adminBackupOverview.mockResolvedValue({
      ...backupOverview,
      activeRuns: [runningRun],
      recentRuns: [runningRun],
    });
    mockApi.adminBackupRuns.mockResolvedValue({
      items: [runningRun],
      total: 1,
    });

    renderAdminRoute("/admin/backup", adminUser);

    const backupButtons = await screen.findAllByRole("button", {
      name: /立即备份/,
    });
    expect(backupButtons).toHaveLength(2);
    for (const button of backupButtons) {
      expect(button).toBeDisabled();
      fireEvent.click(button);
    }
    expect(mockApi.createAdminBackupRun).not.toHaveBeenCalled();
  });

  it("deduplicates rapid manual backup requests before React state updates", async () => {
    let resolveCreate!: (run: Record<string, unknown>) => void;
    mockApi.createAdminBackupRun.mockReturnValue(
      new Promise<Record<string, unknown>>((resolve) => {
        resolveCreate = resolve;
      }),
    );

    renderAdminRoute("/admin/backup", adminUser);

    const backupButtons = await screen.findAllByRole("button", {
      name: /立即备份/,
    });
    fireEvent.click(backupButtons[0]);
    fireEvent.click(backupButtons[0]);

    expect(mockApi.createAdminBackupRun).toHaveBeenCalledOnce();
    for (const button of screen.getAllByRole("button", { name: /立即备份/ })) {
      expect(button).toBeDisabled();
    }

    resolveCreate({ ...backupRun, id: 2 });
    await waitFor(() => {
      for (const button of screen.getAllByRole("button", {
        name: /立即备份/,
      })) {
        expect(button).toBeEnabled();
      }
    });
  });

  it("polls an existing backup and restores both actions at terminal state", async () => {
    const runningRun = {
      ...backupRun,
      id: 9,
      status: "running",
      progressPercent: 60,
      messages: ["正在上传归档"],
      finishedAt: null,
    } as const;
    const completedRun = {
      ...runningRun,
      status: "success",
      progressPercent: 100,
      messages: ["备份已完成"],
      finishedAt: "2026-07-03T03:00:10+08:00",
    } as const;
    mockApi.adminBackupOverview.mockResolvedValue({
      ...backupOverview,
      activeRuns: [runningRun],
      recentRuns: [runningRun],
    });
    mockApi.adminBackupRuns
      .mockResolvedValueOnce({ items: [runningRun], total: 1 })
      .mockResolvedValue({ items: [completedRun], total: 1 });
    mockApi.adminBackupRun.mockResolvedValue(completedRun);

    renderAdminRoute("/admin/backup", adminUser);

    const backupButtons = await screen.findAllByRole("button", {
      name: /立即备份/,
    });
    for (const button of backupButtons) {
      expect(button).toBeDisabled();
    }

    await waitFor(
      () => {
        expect(mockApi.adminBackupRun).toHaveBeenCalledWith(
          9,
          expect.objectContaining({ signal: expect.any(AbortSignal) }),
        );
        for (const button of screen.getAllByRole("button", {
          name: /立即备份/,
        })) {
          expect(button).toBeEnabled();
        }
      },
      { timeout: 6000 },
    );
  }, 10000);

  it("opens the user detail drawer from auth management", async () => {
    renderWithProviders(
      <MemoryRouter initialEntries={["/admin/auth/users"]}>
        <AdminAuthPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("用户列表")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /admin/ }));

    await waitFor(() => {
      expect(screen.getByText("用户详情")).toBeInTheDocument();
    });
    const drawer = screen.getByRole("dialog", { name: "用户详情" });
    expect(within(drawer).getByText("平台运维组")).toBeInTheDocument();
  }, 30000);

  it("shows and approves pending research role applications", async () => {
    mockApi.roleApplications.mockResolvedValue({
      items: [
        {
          id: 12,
          userId: 8,
          requestedRole: "research",
          status: "pending",
          reason: "需要上传长期监测数据",
          reviewNote: "",
          createdAt: "2026-07-14T10:30:00+08:00",
          reviewedAt: null,
          user: {
            id: 8,
            username: "research_applicant",
            displayName: "张研究员",
            email: "research.applicant@example.com",
            department: "生态监测组",
          },
          reviewer: null,
        },
      ],
    });

    renderWithProviders(
      <MemoryRouter initialEntries={["/admin/auth/users"]}>
        <AdminAuthPage />
      </MemoryRouter>,
      { ...adminUser, roles: ["超级管理员"] },
    );

    expect(await screen.findByText("科研用户申请")).toBeInTheDocument();
    expect(await screen.findByText("张研究员")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /通过/ }));
    const dialog = await screen.findByRole("dialog", {
      name: "确认通过科研用户申请？",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /通\s*过/ }));

    await waitFor(() => {
      expect(mockApi.reviewRoleApplication).toHaveBeenCalledWith(12, {
        action: "approve",
        reviewNote: "",
      });
    });
  }, 30000);

  it("puts current user first in auth management", async () => {
    const researcher = {
      ...adminApiUser,
      id: 2,
      username: "researcher",
      displayName: "科研用户",
      groupIds: [],
    };
    mockApi.adminUsers.mockResolvedValue({
      items: [researcher, adminApiUser],
    });
    mockApi.adminGroups.mockResolvedValue({
      items: [adminGroup],
      availablePermissions,
    });

    renderWithProviders(
      <MemoryRouter initialEntries={["/admin/auth/users"]}>
        <AdminAuthPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("用户列表")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        document.querySelectorAll(".admin-user-link")[0],
      ).toHaveTextContent("admin"),
    );

    fireEvent.click(screen.getAllByRole("button", { name: /操作/ })[0]);
    const ownPermissionItem = await screen.findByRole("menuitem", {
      name: /更改权限/,
    });
    expect(ownPermissionItem).toHaveAttribute("aria-disabled", "true");
    expect(
      within(ownPermissionItem).getByTitle("请到用户设置中修改自己的权限"),
    ).toBeInTheDocument();
  }, 30000);

  async function openUserCreation(superadmin = true) {
    const operator = superadmin
      ? { ...adminUser, roles: ["超级管理员"] }
      : adminUser;
    renderWithProviders(
      <MemoryRouter initialEntries={["/admin/auth/users"]}>
        <AdminAuthPage />
      </MemoryRouter>,
      operator,
    );
    await screen.findByText("用户列表");
    fireEvent.click(await screen.findByRole("button", { name: /新建用户/ }));
    return screen.findByRole("dialog", { name: /新建用户/ });
  }

  async function fillNewUser(dialog: HTMLElement) {
    fireEvent.change(within(dialog).getByLabelText("用户名"), {
      target: { value: "new_researcher" },
    });
    fireEvent.mouseDown(within(dialog).getByRole("combobox", { name: "角色" }));
    fireEvent.click(
      await screen.findByText("系统管理员", {
        selector: ".ant-select-item-option-content",
      }),
    );
    fireEvent.mouseDown(within(dialog).getByLabelText("用户名"));
  }

  function allowCreateProjects() {
    const common = { code: "demo", description: "", sortOrder: 0 };
    vi.mocked(platformApi.projects).mockResolvedValue({
      items: [],
      defaultProjectId: 1,
      canManage: true,
      canAssign: true,
      assignableItems: [
        { ...common, id: 1, name: "公开", isActive: true, isDefault: true },
        {
          ...common,
          id: 3,
          name: "逻辑推理",
          isActive: true,
          isDefault: false,
        },
        {
          ...common,
          id: 4,
          name: "已停用项目",
          isActive: false,
          isDefault: false,
        },
      ],
    });
    mockApi.createAdminUser.mockResolvedValue({
      ...adminApiUser,
      id: 20,
      username: "new_researcher",
      generatedPassword: "Generated123!",
    });
  }

  it("creates a user as superadmin without email and keeps default Public access", async () => {
    allowCreateProjects();
    const dialog = await openUserCreation();
    await fillNewUser(dialog);
    await waitFor(() =>
      expect(within(dialog).getByLabelText("邮箱（选填）")).toBeVisible(),
    );
    await waitFor(() =>
      expect(
        within(dialog).getByRole("switch", { name: "允许访问公开项目" }),
      ).toBeEnabled(),
    );
    expect(
      within(dialog).getByRole("switch", { name: "允许访问公开项目" }),
    ).toBeChecked();
    fireEvent.click(within(dialog).getByRole("button", { name: /确\s*定/ }));
    await waitFor(() =>
      expect(mockApi.createAdminUser).toHaveBeenCalledWith(
        expect.objectContaining({
          username: "new_researcher",
          email: "",
          projectIds: [],
          allowPublicProject: true,
        }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByText("Generated123!")).toBeVisible(),
    );
    expect(
      screen.getByText("Generated123!").querySelector(".ant-typography-copy"),
    ).not.toBeNull();
    expect(
      screen.queryByText("关闭公开项目后，请至少选择一个项目"),
    ).not.toBeInTheDocument();
  });

  it("requires a private project when disabling Public and resets scope after creation", async () => {
    allowCreateProjects();
    const dialog = await openUserCreation();
    await fillNewUser(dialog);
    const toggle = within(dialog).getByRole("switch", {
      name: "允许访问公开项目",
    });
    await waitFor(() => expect(toggle).toBeEnabled());
    fireEvent.click(toggle);
    fireEvent.click(within(dialog).getByRole("button", { name: /确\s*定/ }));
    expect(
      (await screen.findAllByText("关闭公开项目后，请至少选择一个项目")).length,
    ).toBeGreaterThan(0);
    expect(mockApi.createAdminUser).not.toHaveBeenCalled();
    fireEvent.mouseDown(
      within(dialog).getByRole("combobox", { name: "其他可见项目" }),
    );
    expect(screen.queryByText("已停用项目")).not.toBeInTheDocument();
    expect(
      screen.queryByText("公开", {
        selector: ".ant-select-item-option-content",
      }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      await screen.findByText("逻辑推理", {
        selector: ".ant-select-item-option-content",
      }),
    );
    fireEvent.mouseDown(within(dialog).getByLabelText("用户名"));
    fireEvent.click(within(dialog).getByRole("button", { name: /确\s*定/ }));
    await waitFor(() =>
      expect(mockApi.createAdminUser).toHaveBeenCalledWith(
        expect.objectContaining({ projectIds: [3], allowPublicProject: false }),
      ),
    );
    const success = await screen.findByRole("dialog", { name: "用户创建成功" });
    fireEvent.click(
      within(success).getByRole("button", { name: /知道了|确\s*定/ }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "用户创建成功" }),
      ).not.toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /新建用户/ }));
    const reopened = await screen.findByRole("dialog", { name: /新建用户/ });
    expect(
      within(reopened).getByRole("switch", { name: "允许访问公开项目" }),
    ).toBeChecked();
    expect(within(reopened).getByLabelText("用户名")).toHaveValue("");
    expect(
      within(reopened).queryByText("逻辑推理", {
        selector: ".ant-select-selection-item-content",
      }),
    ).not.toBeInTheDocument();
  });

  it("keeps email required and project assignment hidden for ordinary administrators", async () => {
    mockApi.createAdminUser.mockResolvedValue({
      ...adminApiUser,
      id: 20,
      username: "new_researcher",
    });
    const dialog = await openUserCreation(false);
    await fillNewUser(dialog);
    expect(
      within(dialog).queryByRole("switch", { name: "允许访问公开项目" }),
    ).not.toBeInTheDocument();
    expect(platformApi.projects).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: /确\s*定/ }));
    expect((await screen.findAllByText("请输入邮箱")).length).toBeGreaterThan(
      0,
    );
    expect(mockApi.createAdminUser).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText("邮箱"), {
      target: { value: "new@example.org" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /确\s*定/ }));
    await waitFor(() => expect(mockApi.createAdminUser).toHaveBeenCalledOnce());
    expect(mockApi.createAdminUser.mock.calls[0][0]).not.toHaveProperty(
      "projectIds",
    );
    expect(mockApi.createAdminUser.mock.calls[0][0]).not.toHaveProperty(
      "allowPublicProject",
    );
  });

  it("shows project loading and retries failures without clearing the current selection", async () => {
    allowCreateProjects();
    let finish: (
      value: Awaited<ReturnType<typeof platformApi.projects>>,
    ) => void = () => {};
    const valid = await platformApi.projects();
    vi.mocked(platformApi.projects)
      .mockClear()
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finish = resolve;
        }),
      );
    const dialog = await openUserCreation();
    expect(within(dialog).getByRole("status")).toHaveTextContent(
      "正在加载可分配项目",
    );
    expect(
      within(dialog).getByRole("button", { name: /确\s*定/ }),
    ).toBeDisabled();
    finish(valid);
    await waitFor(() =>
      expect(
        within(dialog).getByRole("combobox", { name: "其他可见项目" }),
      ).toBeEnabled(),
    );
    fireEvent.mouseDown(
      within(dialog).getByRole("combobox", { name: "其他可见项目" }),
    );
    fireEvent.click(
      await screen.findByText("逻辑推理", {
        selector: ".ant-select-item-option-content",
      }),
    );
    fireEvent.mouseDown(within(dialog).getByLabelText("用户名"));
    vi.mocked(platformApi.projects).mockRejectedValueOnce(
      new Error("项目网络失败"),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "刷新项目列表" }),
    );
    await waitFor(() =>
      expect(within(dialog).getByText("可见项目暂时无法加载")).toBeVisible(),
    );
    expect(
      within(dialog).getByText("逻辑推理", {
        selector: ".ant-select-selection-item-content",
      }),
    ).toBeVisible();
    expect(
      within(dialog).getByRole("button", { name: /确\s*定/ }),
    ).toBeDisabled();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "重试加载项目" }),
    );
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: /确\s*定/ }),
      ).toBeEnabled(),
    );
    expect(
      within(dialog).getByText("逻辑推理", {
        selector: ".ant-select-selection-item-content",
      }),
    ).toBeVisible();
    await fillNewUser(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: /确\s*定/ }));
    await waitFor(() =>
      expect(mockApi.createAdminUser).toHaveBeenCalledWith(
        expect.objectContaining({ projectIds: [3] }),
      ),
    );
  });

  async function openUsernameEdit(target: User, superadmin = true) {
    mockApi.adminUsers.mockResolvedValue({ items: [adminApiUser, target] });
    renderWithProviders(
      <MemoryRouter initialEntries={["/admin/auth/users"]}>
        <AdminAuthPage />
      </MemoryRouter>,
      superadmin ? { ...adminUser, roles: ["超级管理员"] } : adminUser,
    );
    const row = (
      await screen.findByRole("button", { name: target.username })
    ).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: /操作/ }));
    return row;
  }

  it("renames an allowed user with a username-only payload and keeps the display name", async () => {
    const target = {
      ...adminApiUser,
      id: 22,
      username: "old_geologist",
      displayName: "地质研究员",
      canRenameUsername: true,
    };
    mockApi.updateAdminUser.mockResolvedValue({
      ...target,
      username: "new_geologist",
    });
    await openUsernameEdit(target);
    fireEvent.click(
      await screen.findByRole("menuitem", { name: /修改用户名/ }),
    );
    const dialog = await screen.findByRole("dialog", { name: "修改用户名" });
    expect(
      within(dialog).getByText("显示名称：地质研究员"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("修改后请使用新用户名登录。"),
    ).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("用户名"), {
      target: { value: "new_geologist" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /确\s*定/ }));
    await waitFor(() =>
      expect(mockApi.updateAdminUser).toHaveBeenCalledWith(22, {
        username: "new_geologist",
      }),
    );
    expect(
      await screen.findByRole("button", { name: "new_geologist" }),
    ).toBeInTheDocument();
    expect(screen.getByText("地质研究员")).toBeInTheDocument();
  });

  it("keeps a duplicate username editable and saves the corrected name", async () => {
    const target = {
      ...adminApiUser,
      id: 22,
      username: "old_geologist",
      canRenameUsername: true,
    };
    mockApi.updateAdminUser
      .mockRejectedValueOnce(new Error("用户名已存在，请使用其他用户名"))
      .mockResolvedValueOnce({ ...target, username: "unique_geologist" });
    await openUsernameEdit(target);
    fireEvent.click(
      await screen.findByRole("menuitem", { name: /修改用户名/ }),
    );
    const dialog = await screen.findByRole("dialog", { name: "修改用户名" });
    fireEvent.change(within(dialog).getByLabelText("用户名"), {
      target: { value: "existing_name" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /确\s*定/ }));
    expect(
      await within(dialog).findByText("用户名已存在，请使用其他用户名"),
    ).toBeInTheDocument();
    expect(within(dialog).getByLabelText("用户名")).toHaveValue(
      "existing_name",
    );
    expect(
      screen.getByRole("button", { name: "old_geologist" }),
    ).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("用户名"), {
      target: { value: "unique_geologist" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /确\s*定/ }));
    expect(
      await screen.findByRole("button", { name: "unique_geologist" }),
    ).toBeInTheDocument();
  });

  it("hides username editing from ordinary administrators and sends only status changes", async () => {
    const target = {
      ...adminApiUser,
      id: 22,
      username: "regular_target",
      canRenameUsername: true,
    };
    mockApi.updateAdminUser.mockResolvedValue({ ...target, isActive: false });
    await openUsernameEdit(target, false);
    expect(
      screen.queryByRole("menuitem", { name: /修改用户名/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("menuitem", { name: /停用/ }));
    const dialog = await screen.findByRole("dialog", {
      name: "确认停用用户？",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /停\s*用/ }));
    await waitFor(() =>
      expect(mockApi.updateAdminUser).toHaveBeenCalledWith(22, {
        isActive: false,
      }),
    );
    expect(mockApi.updateAdminUser.mock.calls[0][1]).not.toHaveProperty(
      "username",
    );
  });

  it.each([
    {
      username: "configured_initial",
      roles: ["超级管理员"],
      canRenameUsername: false,
    },
    { username: "guest", roles: ["游客"], canRenameUsername: true },
  ])(
    "protects username editing for $username using server capability and guest rules",
    async (fields) => {
      await openUsernameEdit({ ...adminApiUser, id: 22, ...fields });
      const item = await screen.findByRole("menuitem", { name: /修改用户名/ });
      expect(item).toHaveAttribute("aria-disabled", "true");
      fireEvent.click(item);
      expect(
        screen.queryByRole("dialog", { name: "修改用户名" }),
      ).not.toBeInTheDocument();
      expect(mockApi.updateAdminUser).not.toHaveBeenCalled();
    },
  );

  it("keeps the built-in guest role unavailable when creating users", async () => {
    const guestGroup = {
      id: 3,
      name: "游客",
      userCount: 1,
      permissions: [],
      isProtected: true,
      lockedPermissions: [],
    };
    mockApi.adminGroups.mockResolvedValue({
      items: [adminGroup, guestGroup],
      availablePermissions,
    });

    renderWithProviders(
      <MemoryRouter initialEntries={["/admin/auth/users"]}>
        <AdminAuthPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("用户列表")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /新建用户/ }));
    const dialog = await screen.findByRole("dialog", { name: /新建用户/ });
    expect(
      within(dialog).getByText(
        "游客角色仅供系统 guest 账号使用，不能分配给其他账号。",
      ),
    ).toBeInTheDocument();

    fireEvent.mouseDown(within(dialog).getByRole("combobox", { name: "角色" }));
    const guestOptionLabel = await screen.findByText("游客（系统专用）");
    const guestOption = guestOptionLabel.closest(".ant-select-item-option");
    expect(guestOption).not.toBeNull();
    expect(guestOption).toHaveClass("ant-select-item-option-disabled");
  }, 30000);

  it("does not render hidden superadmin principals in auth management", async () => {
    const researchGroup = {
      id: 3,
      name: "科研用户",
      userCount: 1,
      permissions: ["core.view_operation_logs"],
      isProtected: false,
      lockedPermissions: [],
    };
    const dataGroup = {
      id: 4,
      name: "数据管理员",
      userCount: 1,
      permissions: ["core.manage_auth"],
      isProtected: false,
      lockedPermissions: [],
    };
    const visibleUser = {
      ...adminApiUser,
      id: 7,
      username: "data_admin_li",
      displayName: "李数据管理员",
      roles: ["数据管理员"],
      groupIds: [dataGroup.id],
      operationLogGroupIds: [researchGroup.id],
    };
    mockApi.adminUsers.mockResolvedValue({
      items: [visibleUser],
    });
    mockApi.adminGroups.mockResolvedValue({
      items: [researchGroup, dataGroup],
      availablePermissions,
    });

    renderWithProviders(
      <MemoryRouter initialEntries={["/admin/auth/users"]}>
        <AdminAuthPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("用户列表")).toBeInTheDocument();
    expect(await screen.findByText("data_admin_li")).toBeInTheDocument();
    expect(screen.queryByText("超级管理员")).not.toBeInTheDocument();
    expect(screen.queryByText("superadmin")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /操作/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /更改权限/ }));

    const drawer = await screen.findByRole("dialog", { name: "设置用户权限" });
    expect(within(drawer).getByText("科研用户")).toBeInTheDocument();
    expect(within(drawer).queryByText("超级管理员")).not.toBeInTheDocument();
  }, 30000);

  it("runs the admin data import step flow through preview and validation", async () => {
    renderAdminRoute("/resources/data/import");

    expect(await screen.findByText("选择或拖拽数据文件")).toBeInTheDocument();
    expect(screen.getByText("存量数据")).toBeInTheDocument();
    const input = document.querySelector(
      "input[type='file']",
    ) as HTMLInputElement;
    const file = new File(
      ["plot_id,longitude,latitude\nP001,87.6,41.7"],
      "sample-points.csv",
      {
        type: "text/csv",
      },
    );

    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByText("导入配置")).toBeInTheDocument();
    expect(screen.getByLabelText("存量数据中显示的资源名称")).toHaveValue(
      "样地调查点位",
    );
    const validateButton = screen.getByRole("button", {
      name: /数据校验并继续/,
    });
    expect(validateButton).toBeEnabled();
    expect(screen.queryByText("我自己可见")).not.toBeInTheDocument();
    expect(screen.queryByText("超级管理员可见")).not.toBeInTheDocument();
    expect(
      screen.queryByText("不选择角色时，仅上传者本人和超级管理员可见。"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /数据校验并继续/ }));

    await waitFor(() => {
      expect(mockApi.importValidate).toHaveBeenCalledWith(
        file,
        {
          name: "样地调查点位",
          importMode: "geographic",
          longitudeColumn: "longitude",
          latitudeColumn: "latitude",
          tableName: "sample_points",
        },
        1,
      );
    });
    const previewTitle = await screen.findByText("数据预览");
    const metadataTitle = screen.getByText("字段元数据");
    const submitButton = screen.getByRole("button", { name: /提交导入/ });
    expect(
      submitButton.compareDocumentPosition(previewTitle) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(previewTitle).toBeInTheDocument();
    expect(metadataTitle).toBeInTheDocument();
    expect(
      previewTitle.compareDocumentPosition(metadataTitle) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /提交导入/ }));

    await waitFor(() => {
      expect(mockApi.importCommit).toHaveBeenCalledWith(
        file,
        expect.objectContaining({
          name: "样地调查点位",
          domainType: "other",
          categoryCode: "spatial",
          importMode: "geographic",
          longitudeColumn: "longitude",
          latitudeColumn: "latitude",
          tableName: "sample_points",
          accessGroupIds: [],
        }),
        1,
      );
    });
  }, 30000);

  it("shows duplicate data names as a warning during import validation", async () => {
    mockApi.importValidate.mockResolvedValueOnce({
      coordinateStats: {
        totalRows: 1,
        validRows: 1,
        missingRows: 0,
        quantizationErrorMeters: { min: 1.1, max: 1.1 },
      },
      validationIssues: [],
      duplicateTarget: {
        targetName: "样地调查点位",
        message: "已存在同名数据资源",
      },
    });
    renderAdminRoute("/resources/data/import");

    const input = document.querySelector(
      "input[type='file']",
    ) as HTMLInputElement;
    const file = new File(
      ["plot_id,longitude,latitude\nP001,87.6,41.7"],
      "sample-points.csv",
      {
        type: "text/csv",
      },
    );

    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByText("导入配置")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /数据校验并继续/ }));

    await screen.findByText("确认重复数据名称");
    const duplicateAlerts = screen
      .getAllByText("数据名重复")
      .map((title) => title.closest(".ant-alert"));
    expect(duplicateAlerts.length).toBeGreaterThan(0);
    for (const duplicateAlert of duplicateAlerts) {
      expect(duplicateAlert).toHaveClass("ant-alert-warning");
      expect(duplicateAlert).not.toHaveClass("ant-alert-error");
    }
  }, 30000);

  it("warns before leaving an unfinished data import", async () => {
    renderAdminRoute("/resources/data/import");

    const input = document.querySelector(
      "input[type='file']",
    ) as HTMLInputElement;
    const file = new File(
      ["plot_id,longitude,latitude\nP001,87.6,41.7"],
      "sample-points.csv",
      {
        type: "text/csv",
      },
    );

    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByText("导入配置")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("link", { name: /存量数据/ }));
    expect(await screen.findByText("当前导入尚未完成")).toBeInTheDocument();
    expect(screen.getByText("导入配置")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认离开" }));
    expect(await screen.findByText("胡杨林样地点")).toBeInTheDocument();
  }, 30000);

  it("uploads a raster file and shows preprocessing progress", async () => {
    renderAdminRoute("/resources/data/import");

    expect(await screen.findByText("选择或拖拽数据文件")).toBeInTheDocument();
    const rasterInput = document.querySelector(
      "input[type='file']",
    ) as HTMLInputElement;
    const rasterFile = new File(["fake-raster"], "poplar-2026.tif", {
      type: "image/tiff",
    });

    fireEvent.change(rasterInput, { target: { files: [rasterFile] } });

    expect(await screen.findByText("栅格数据包预检通过")).toBeInTheDocument();
    expect(screen.getByLabelText("栅格数据名称")).toHaveValue("poplar-2026");
    let resolveRasterUpload: ((value: unknown) => void) | undefined;
    mockApi.importRaster.mockImplementationOnce(
      (
        _files: File[],
        _payload: Record<string, unknown>,
        onUploadProgress?: (percent: number) => void,
      ) => {
        onUploadProgress?.(42);
        return new Promise((resolve) => {
          resolveRasterUpload = resolve;
        });
      },
    );
    fireEvent.click(screen.getByRole("button", { name: /上传并预处理/ }));

    await waitFor(() => {
      expect(mockApi.importRaster).toHaveBeenCalledWith(
        [rasterFile],
        expect.objectContaining({
          name: "poplar-2026",
          categoryCode: "spatial",
        }),
        expect.any(Function),
        1,
      );
    });
    expect(await screen.findByText("正在上传")).toBeInTheDocument();
    expect(screen.getByText("已上传 42%")).toBeInTheDocument();
    resolveRasterUpload?.({
      id: "raster-job-1",
      kind: "import",
      status: "running",
      progressPercent: 35,
      messages: ["已上传栅格文件", "开始 gdalwarp 预处理"],
      result: null,
      error: "",
      startedAt: 1782100000,
      finishedAt: null,
    });
    expect(await screen.findByText("正在预处理")).toBeInTheDocument();
    expect(screen.getByText("上传进度")).toBeInTheDocument();
    expect(screen.getByText("GDAL 预处理进度")).toBeInTheDocument();

    await waitFor(
      () => {
        expect(mockApi.rasterJob).toHaveBeenCalledWith(
          "raster-job-1",
          expect.objectContaining({ signal: expect.any(AbortSignal) }),
        );
        expect(screen.getByText("栅格预处理完成")).toBeInTheDocument();
      },
      { timeout: 5000 },
    );
    expect(screen.getByText(/gdalwarp 预处理完成/)).toBeInTheDocument();
  }, 30000);

  it("rejects a raster file above the configured upload size before submitting", async () => {
    renderAdminRoute("/resources/data/import");

    const rasterInput = document.querySelector(
      "input[type='file']",
    ) as HTMLInputElement;
    const oversizedFile = new File(["x"], "too-large.tif", {
      type: "image/tiff",
    });
    Object.defineProperty(oversizedFile, "size", {
      value: bootstrap.limits.uploadMaxMb * 1024 * 1024 + 1,
    });

    fireEvent.change(rasterInput, { target: { files: [oversizedFile] } });

    expect(
      await screen.findByText(/栅格数据包总大小不能超过 64 MB/),
    ).toBeInTheDocument();
    expect(mockApi.previewRasterImport).not.toHaveBeenCalled();
    expect(mockApi.importRaster).not.toHaveBeenCalled();
  }, 30000);

  it("rejects a raster file above the pixel side limit before submitting", async () => {
    mockApi.previewRasterImport.mockRejectedValueOnce(
      new Error("栅格单边长度不能超过 10000 像素，当前为 10001 x 9000"),
    );
    renderAdminRoute("/resources/data/import");

    const rasterInput = document.querySelector(
      "input[type='file']",
    ) as HTMLInputElement;
    const rasterFile = new File(["fake-raster"], "too-wide.tif", {
      type: "image/tiff",
    });

    fireEvent.change(rasterInput, { target: { files: [rasterFile] } });

    expect(
      await screen.findByText(/栅格单边长度不能超过 10000 像素/),
    ).toBeInTheDocument();
    expect(mockApi.importRaster).not.toHaveBeenCalled();
  }, 30000);

  it("honors a lower platform cap for vector imports", async () => {
    renderAdminRoute("/resources/data/import");

    const vectorInput = document.querySelector(
      "input[type='file']",
    ) as HTMLInputElement;
    const oversizedFile = new File(["x"], "too-large.geojson", {
      type: "application/geo+json",
    });
    Object.defineProperty(oversizedFile, "size", {
      value: bootstrap.limits.uploadMaxMb * 1024 * 1024 + 1,
    });

    fireEvent.change(vectorInput, { target: { files: [oversizedFile] } });

    expect(
      await screen.findByText("矢量文件不能超过 64 MB（内存安全限制）"),
    ).toBeInTheDocument();
    expect(screen.getByText("尚未选择文件")).toBeInTheDocument();
  });

  it("rejects a table above its memory-safe parser limit before uploading", async () => {
    renderAdminRoute("/resources/data/import");

    const tableInput = document.querySelector(
      "input[type='file']",
    ) as HTMLInputElement;
    const oversizedFile = new File(["x"], "too-large.csv", {
      type: "text/csv",
    });
    Object.defineProperty(oversizedFile, "size", {
      value: 16 * 1024 * 1024 + 1,
    });

    fireEvent.change(tableInput, { target: { files: [oversizedFile] } });

    expect(
      await screen.findByText("表格文件不能超过 16 MB（内存安全限制）"),
    ).toBeInTheDocument();
    expect(screen.getByText("尚未选择文件")).toBeInTheDocument();
    expect(mockApi.importPreview).not.toHaveBeenCalled();
  });

  it("shows an unsupported state for files without an available import flow", async () => {
    renderAdminRoute("/resources/data/import");

    const input = document.querySelector(
      "input[type='file']",
    ) as HTMLInputElement;
    const file = new File(["plain"], "readme.txt", {
      type: "text/plain",
    });

    fireEvent.change(input, { target: { files: [file] } });

    expect(
      await screen.findByText("暂不支持自动导入该文件类型"),
    ).toBeInTheDocument();
    expect(screen.getByText(/readme\.txt/)).toBeInTheDocument();
    expect(mockApi.importPreview).not.toHaveBeenCalled();
    expect(mockApi.importRaster).not.toHaveBeenCalled();
  }, 30000);

  it("blocks browser unload while an import is unfinished", async () => {
    renderAdminRoute("/resources/data/import");

    const input = document.querySelector(
      "input[type='file']",
    ) as HTMLInputElement;
    const file = new File(
      ["plot_id,longitude,latitude\nP001,87.6,41.7"],
      "sample-points.csv",
      {
        type: "text/csv",
      },
    );

    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByText("导入配置")).toBeInTheDocument();

    const unloadEvent = new Event("beforeunload", {
      cancelable: true,
    }) as BeforeUnloadEvent;
    expect(window.dispatchEvent(unloadEvent)).toBe(false);
    expect(unloadEvent.defaultPrevented).toBe(true);
  }, 30000);

  it("warns before programmatic navigation leaves an unfinished data import", async () => {
    renderAdminRoute("/resources/data/import");

    const input = document.querySelector(
      "input[type='file']",
    ) as HTMLInputElement;
    const file = new File(
      ["plot_id,longitude,latitude\nP001,87.6,41.7"],
      "sample-points.csv",
      {
        type: "text/csv",
      },
    );

    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByText("导入配置")).toBeInTheDocument();

    window.history.pushState({}, "", "/resources/dashboard");

    expect(await screen.findByText("当前导入尚未完成")).toBeInTheDocument();
    expect(screen.getByText("导入配置")).toBeInTheDocument();
  }, 30000);

  it("loads the inventory data management page", async () => {
    renderAdminRoute("/resources/data/inventory");

    expect(await screen.findByText("胡杨林样地点")).toBeInTheDocument();
    expect(screen.getAllByText("全部数据").length).toBeGreaterThan(0);
    for (const groupName of [
      "地理数据",
      "非地理数据",
      "计算结果",
      "未分组（其他）",
    ]) {
      expect(
        screen.getByRole("button", { name: `删除系统分组${groupName}` }),
      ).toBeDisabled();
    }
    expect(
      document.querySelectorAll('button[aria-label^="删除系统分组"]'),
    ).toHaveLength(5);
    expect(
      screen.queryByRole("button", { name: "删除系统分组LUCC" }),
    ).not.toBeInTheDocument();
    const allDataRow = screen
      .getByRole("button", { name: "删除系统分组全部数据" })
      .closest("tr");
    expect(allDataRow).not.toBeNull();
    expect(allDataRow).toBe(
      allDataRow!.parentElement!.querySelector("tr.ant-table-row"),
    );
    expect(screen.getByText("CSV")).toBeInTheDocument();
    expect(screen.getByText("筛选结果总数")).toBeInTheDocument();
    expect(screen.getByText("启用数据")).toBeInTheDocument();
    expect(screen.queryByText("populus-plots")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "配置胡杨林样地点" }));

    expect(
      await screen.findByText(
        "访问范围由项目标签决定；仅对应项目成员和超管可见。公开项目所有人可读。",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("上传者本人可见")).not.toBeInTheDocument();
    expect(screen.queryByText("超级管理员可见")).not.toBeInTheDocument();
    expect(screen.queryByText("存储位置")).not.toBeInTheDocument();
    expect(screen.queryByText("populus_plots")).not.toBeInTheDocument();
  });

  it("keeps the coordinate and computation-result categories flat", async () => {
    renderAdminRoute("/resources/data/inventory");
    expect(await screen.findByText("胡杨林样地点")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "删除系统分组地理数据" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "删除系统分组非地理数据" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "删除系统分组计算结果" }),
    ).toBeDisabled();
    expect(
      document.querySelector(".inventory-category-child-table"),
    ).toBeNull();
    expect(
      document.querySelector(".inventory-group-resource-table"),
    ).not.toBeNull();
  });

  it("places pending resources in the unclassified inventory group", async () => {
    const pendingResource = {
      ...(await mockApi.adminDataResources()).items[0],
      category: null,
      categoryPath: [],
      classificationStatus: "pending" as const,
    };
    mockApi.adminDataResources.mockResolvedValueOnce({
      items: [pendingResource],
      total: 1,
      ...inventoryResponseMeta({ total: 1, categoryCode: null }),
      availableAccessGroups: [],
    });

    renderAdminRoute("/resources/data/inventory");

    expect(
      await screen.findByRole("checkbox", {
        name: "未分组（其他）资料夹状态",
      }),
    ).toBeChecked();
  });

  it("groups stored algorithm results separately and displays a friendly source", async () => {
    const result = {
      ...(await mockApi.adminDataResources()).items[0],
      name: "绿洲 NDVI 计算结果",
      category: {
        id: 3,
        type: "data_category",
        code: "compute_results",
        name: "计算结果",
        parentId: null,
        selectable: false,
      },
      categoryPath: [{ id: 3, code: "compute_results", name: "计算结果" }],
      source: "compute-output:internal-storage-key",
    };
    mockApi.adminDataResources.mockResolvedValueOnce({
      items: [result],
      total: 1,
      ...inventoryResponseMeta({
        total: 1,
        categoryCode: "compute_results",
        rootCategoryCode: "compute_results",
      }),
      availableAccessGroups: [],
    });
    renderAdminRoute("/resources/data/inventory");
    expect(await screen.findByText(result.name)).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "计算结果资料夹状态" }),
    ).toBeChecked();
    expect(screen.getByText("平台算法计算")).toBeInTheDocument();
    expect(screen.queryByText(result.source)).not.toBeInTheDocument();
  });

  it("switches the data import page to the independent result artifact workflow", async () => {
    renderAdminRoute("/resources/data/import");

    expect(
      await screen.findByRole("heading", { name: "选择导入目标" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "导入并发布成果" }));

    expect(
      await screen.findByRole("heading", { name: "导入并加载发布为成果" }),
    ).toBeInTheDocument();
    expect(screen.getByText("导入完成后直接发布")).toBeInTheDocument();
    expect(screen.queryByText("保存为草稿")).not.toBeInTheDocument();
    expect(
      screen.getByText(/历史草稿可在成果管理中发布或删除/),
    ).toBeInTheDocument();
  });

  it("renames an inventory data resource without changing its default layer name", async () => {
    renderAdminRoute("/resources/data/inventory");

    fireEvent.click(
      await screen.findByRole("button", { name: "配置胡杨林样地点" }),
    );
    const resourceNameInput = await screen.findByLabelText("数据资源名称");
    const layerNameInput = screen.getByLabelText("默认图层名称");
    expect(resourceNameInput).toHaveValue("胡杨林样地点");
    expect(layerNameInput).toHaveValue("胡杨林样地点");

    fireEvent.change(resourceNameInput, {
      target: { value: "胡杨林长期监测样地点" },
    });
    fireEvent.click(screen.getByRole("button", { name: /保存/ }));

    await waitFor(() => {
      expect(mockApi.updateAdminDataResource).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          action: "update",
          name: "胡杨林长期监测样地点",
          visualization: expect.objectContaining({
            layerName: "胡杨林样地点",
          }),
        }),
      );
    });
  });

  it("syncs data status from inventory group checkboxes", async () => {
    const groupedResource = {
      id: 7,
      name: "科研共享样地",
      code: "research-plots",
      dataType: "vector",
      domainType: "field_survey",
      category: null,
      ...adminResourceClassification,
      source: "用户导入",
      provider: "平台组",
      dataDate: "2026-06-01",
      spatialExtent: "87.600000,41.700000,87.800000,41.900000",
      coordinateSystem: "EPSG:4326",
      fileFormat: "GPKG",
      storagePath: "research_plots",
      description: "科研共享样地数据",
      qualityNote: "",
      defaultVisualization: {},
      sizeBytes: 2048,
      itemCount: 12,
      status: "active",
      accessGroups: [],
      canManageAccess: true,
      maintainer: "系统管理员",
      uploader: {
        id: 1,
        username: "admin",
        displayName: "系统管理员",
      },
      createdAt: "2026-06-01T10:00:00+08:00",
      updatedAt: "2026-06-01T10:00:00+08:00",
      defaultLayer: null,
    };
    mockApi.adminDataResources.mockResolvedValueOnce({
      items: [groupedResource],
      total: 1,
      ...inventoryResponseMeta({
        total: 1,
        sizeBytes: 2048,
        itemCount: 12,
      }),
      availableAccessGroups: [],
    });
    mockApi.updateAdminDataResource.mockResolvedValueOnce({
      ...groupedResource,
      status: "inactive",
    });

    renderAdminRoute("/resources/data/inventory");

    expect(await screen.findByText("全部数据")).toBeInTheDocument();
    const groupCheckbox = screen.getByRole("checkbox", {
      name: "全部数据资料夹状态",
    });
    expect(groupCheckbox).toBeChecked();

    fireEvent.click(groupCheckbox);

    await waitFor(() => {
      expect(mockApi.updateAdminDataResource).toHaveBeenCalledWith(7, {
        action: "setStatus",
        status: "inactive",
      });
    });
  });

  it("shows mixed enabled state for inventory groups", async () => {
    const activeResource = {
      id: 7,
      name: "科研共享样地",
      code: "research-plots",
      dataType: "vector",
      domainType: "field_survey",
      category: null,
      ...adminResourceClassification,
      source: "用户导入",
      provider: "平台组",
      dataDate: "2026-06-01",
      spatialExtent: "87.600000,41.700000,87.800000,41.900000",
      coordinateSystem: "EPSG:4326",
      fileFormat: "GPKG",
      storagePath: "research_plots",
      description: "科研共享样地数据",
      qualityNote: "",
      defaultVisualization: {},
      sizeBytes: 2048,
      itemCount: 12,
      status: "active",
      accessGroups: [],
      canManageAccess: true,
      maintainer: "系统管理员",
      uploader: {
        id: 1,
        username: "admin",
        displayName: "系统管理员",
      },
      createdAt: "2026-06-01T10:00:00+08:00",
      updatedAt: "2026-06-01T10:00:00+08:00",
      defaultLayer: null,
    };
    const inactiveResource = {
      ...activeResource,
      id: 8,
      name: "监测样线",
      code: "monitor-lines",
      status: "inactive",
    };
    mockApi.adminDataResources.mockResolvedValueOnce({
      items: [activeResource, inactiveResource],
      total: 2,
      ...inventoryResponseMeta({
        total: 2,
        activeCount: 1,
        inactiveCount: 1,
        sizeBytes: 4096,
        itemCount: 24,
      }),
      availableAccessGroups: [],
    });
    mockApi.updateAdminDataResource.mockResolvedValueOnce({
      ...inactiveResource,
      status: "active",
    });

    renderAdminRoute("/resources/data/inventory");

    const groupCheckbox = screen.getByRole("checkbox", {
      name: "全部数据资料夹状态",
    });
    await waitFor(() => {
      expect(groupCheckbox).toBePartiallyChecked();
      expect(screen.getAllByText("部分启用").length).toBeGreaterThan(0);
    });

    fireEvent.click(groupCheckbox);

    await waitFor(() => {
      expect(mockApi.updateAdminDataResource).toHaveBeenCalledWith(8, {
        action: "setStatus",
        status: "active",
      });
    });
  });

  it("creates renames and warns before deleting inventory groups", async () => {
    const baseInventory = await mockApi.adminDataResources();
    let persistedGroup:
      | {
          id: number;
          name: string;
          createdAt: string;
          updatedAt: string;
        }
      | undefined;
    mockApi.adminDataResources.mockImplementation(() =>
      Promise.resolve({
        ...baseInventory,
        inventoryGroups: persistedGroup ? [persistedGroup] : [],
      }),
    );
    mockApi.createAdminDataResourceGroup.mockImplementation(({ name }) => {
      persistedGroup = {
        id: 9,
        name,
        createdAt: "2026-06-01T10:00:00+08:00",
        updatedAt: "2026-06-01T10:00:00+08:00",
      };
      return Promise.resolve(persistedGroup);
    });
    mockApi.updateAdminDataResourceGroup.mockImplementation(
      (groupId, payload) => {
        if (payload.action === "delete") {
          persistedGroup = undefined;
          return Promise.resolve({ detail: "数据资料夹已删除" });
        }
        persistedGroup = {
          id: groupId,
          name: payload.name ?? persistedGroup?.name ?? "样地调查",
          createdAt: persistedGroup?.createdAt ?? "2026-06-01T10:00:00+08:00",
          updatedAt: "2026-06-01T10:00:00+08:00",
        };
        return Promise.resolve(persistedGroup);
      },
    );
    renderAdminRoute("/resources/data/inventory");

    expect(await screen.findByText("胡杨林样地点")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "新增资料夹（不控制访问权限）" }),
    );
    fireEvent.change(await screen.findByPlaceholderText("输入资料夹名称"), {
      target: { value: "植被调查" },
    });
    fireEvent.click(screen.getByRole("button", { name: "新建" }));

    expect(await screen.findByText("植被调查")).toBeInTheDocument();
    fireEvent.click(
      await screen.findByRole("button", { name: "编辑资料夹植被调查" }),
    );
    const groupNameInput = await screen.findByLabelText(
      "编辑资料夹名称植被调查",
    );
    fireEvent.change(groupNameInput, {
      target: { value: "样地调查" },
    });
    fireEvent.blur(groupNameInput);

    expect(await screen.findByText("样地调查")).toBeInTheDocument();

    fireEvent.click(
      await screen.findByRole("button", { name: "删除资料夹样地调查" }),
    );

    expect(
      await screen.findByText(
        "删除后仅移除自定义归档关系，数据仍保留在对应的数据分类中。",
      ),
    ).toBeInTheDocument();
  });

  it("does not render hidden superadmin uploader identity in data management", async () => {
    mockApi.adminDataResources.mockResolvedValueOnce({
      items: [
        {
          id: 1,
          name: "脱敏维护数据",
          code: "masked-maintainer-resource",
          dataType: "table",
          category: null,
          ...adminResourceClassification,
          source: "用户导入",
          provider: "平台组",
          dataDate: null,
          spatialExtent: "",
          coordinateSystem: "",
          fileFormat: "CSV",
          storagePath: "masked_maintainer_resource",
          description: "",
          qualityNote: "",
          defaultVisualization: {},
          status: "active",
          accessGroups: [
            {
              id: 3,
              name: "超级管理员",
              isGuest: false,
              isSuperadmin: true,
            },
          ],
          canManageAccess: true,
          maintainer: "",
          uploader: null,
          createdAt: "2026-06-01T10:00:00+08:00",
          updatedAt: "2026-06-01T10:00:00+08:00",
          defaultLayer: null,
        },
      ],
      total: 1,
      ...inventoryResponseMeta({ total: 1 }),
      availableAccessGroups: [
        { id: 2, name: "科研用户", isGuest: false, isSuperadmin: false },
      ],
    });

    renderAdminRoute("/resources/data/inventory");

    expect(await screen.findByText("脱敏维护数据")).toBeInTheDocument();
    expect(screen.getAllByText("未知").length).toBeGreaterThan(0);
    expect(screen.queryByText("超级管理员")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "配置脱敏维护数据" }));

    expect(
      await screen.findByText(
        "访问范围由项目标签决定；仅对应项目成员和超管可见。公开项目所有人可读。",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("超级管理员可见")).not.toBeInTheDocument();
    expect(screen.queryByTitle("3")).not.toBeInTheDocument();
  });

  it("uses usernames when uploader display names are empty in data management", async () => {
    mockApi.adminDataResources.mockResolvedValueOnce({
      items: [
        {
          id: 1,
          name: "无显示名上传数据",
          code: "unnamed-uploader-resource",
          dataType: "table",
          category: null,
          ...adminResourceClassification,
          source: "用户导入",
          provider: "平台组",
          dataDate: null,
          spatialExtent: "",
          coordinateSystem: "",
          fileFormat: "CSV",
          storagePath: "unnamed_uploader_resource",
          description: "",
          qualityNote: "",
          defaultVisualization: {},
          status: "active",
          accessGroups: [],
          isOwner: true,
          canEdit: true,
          canDelete: true,
          canManageAccess: true,
          maintainer: "",
          uploader: {
            id: 6,
            username: "data_operator",
            displayName: "",
          },
          createdAt: "2026-06-01T10:00:00+08:00",
          updatedAt: "2026-06-01T10:00:00+08:00",
          defaultLayer: null,
        },
      ],
      total: 1,
      ...inventoryResponseMeta({ total: 1 }),
      availableAccessGroups: [],
    });

    renderAdminRoute("/resources/data/inventory");

    expect(await screen.findByText("无显示名上传数据")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "配置无显示名上传数据" }),
    );

    await waitFor(() => {
      expect(screen.getAllByText("data_operator").length).toBeGreaterThan(1);
    });
  });

  it("loads the project and topic management pages", async () => {
    renderAdminRoute("/resources/manage/projects");

    expect(await screen.findByText("塔里木河样地工程")).toBeInTheDocument();
    expect(screen.getByText("当前工程")).toBeInTheDocument();

    renderAdminRoute("/resources/manage/topics");

    expect(await screen.findByText("胡杨退化专题")).toBeInTheDocument();
    expect(screen.getByText("全部成果")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "导入成果（1）" }));
    expect(await screen.findByText("胡杨监测年度报告")).toBeInTheDocument();
  });

  it("applies record-level workspace permissions for research users", async () => {
    const researchUser: User = {
      ...adminUser,
      id: 2,
      username: "researcher",
      displayName: "张研究员",
      roles: ["科研用户"],
      groupIds: [2],
      permissions: {
        ...adminUser.permissions,
        canAccessAdmin: false,
        canManageFeaturePermissions: false,
        canCreateUser: false,
        canManageAuth: false,
        canManageDataBackup: false,
        canManageSystemSettings: false,
        canChangeWorkspaces: true,
        canDeleteWorkspaces: true,
      },
    };
    window.localStorage.setItem(
      `huyang-system.workspace-tour.v1.${researchUser.id}.${researchUser.username}`,
      "completed",
    );
    mockApi.adminWorkspaces.mockResolvedValue({
      items: [
        {
          id: 21,
          kind: "project",
          name: "本人科研工程",
          description: "研究员本人保存的工程",
          snapshot: { version: 1, groups: [] },
          owner: {
            id: researchUser.id,
            username: researchUser.username,
            displayName: researchUser.displayName,
          },
          createdAt: "2026-07-28T10:00:00+08:00",
          updatedAt: "2026-07-29T10:00:00+08:00",
          status: "active",
          accessGroups: [],
          isOwner: true,
          canEdit: true,
          canDelete: true,
          canManageAccess: true,
        },
        {
          id: 22,
          kind: "project",
          name: "他人共享工程",
          description: "其他研究员共享的只读工程",
          snapshot: { version: 1, groups: [] },
          owner: {
            id: 9,
            username: "other_researcher",
            displayName: "其他研究员",
          },
          createdAt: "2026-07-27T10:00:00+08:00",
          updatedAt: "2026-07-29T09:00:00+08:00",
          status: "active",
          accessGroups: [
            { id: 2, name: "科研用户", isGuest: false, isSuperadmin: false },
          ],
          isOwner: false,
          canEdit: false,
          canDelete: false,
          canManageAccess: false,
        },
        {
          id: 23,
          kind: "project",
          name: "仅授权管理工程",
          description: "只能维护可见范围的共享工程",
          snapshot: { version: 1, groups: [] },
          owner: {
            id: 10,
            username: "workspace_owner",
            displayName: "工程负责人",
          },
          createdAt: "2026-07-26T10:00:00+08:00",
          updatedAt: "2026-07-29T08:00:00+08:00",
          status: "active",
          accessGroups: [],
          isOwner: false,
          canEdit: false,
          canDelete: false,
          canManageAccess: true,
        },
      ],
      total: 3,
      availableAccessGroups: [
        { id: 2, name: "科研用户", isGuest: false, isSuperadmin: false },
      ],
    });

    renderAdminRoute("/resources/manage/projects", researchUser);

    const ownProjectName = await screen.findByText("本人科研工程");
    const ownProjectRow = ownProjectName.closest("tr");
    expect(ownProjectRow).not.toBeNull();
    expect(
      within(ownProjectRow!).getByRole("button", {
        name: "配置本人科研工程",
      }),
    ).toBeEnabled();
    expect(
      within(ownProjectRow!).getByRole("button", {
        name: "删除本人科研工程",
      }),
    ).toBeEnabled();
    const ownStatusSwitch = within(ownProjectRow!).getByRole("switch");
    expect(ownStatusSwitch).toBeEnabled();

    const sharedProjectName = screen.getByText("他人共享工程");
    const sharedProjectRow = sharedProjectName.closest("tr");
    expect(sharedProjectRow).not.toBeNull();
    expect(
      within(sharedProjectRow!).getByRole("button", {
        name: "配置他人共享工程",
      }),
    ).toBeDisabled();
    expect(
      within(sharedProjectRow!).getByRole("button", {
        name: "删除他人共享工程",
      }),
    ).toBeDisabled();
    expect(within(sharedProjectRow!).getByRole("switch")).toBeDisabled();

    const accessProjectName = screen.getByText("仅授权管理工程");
    const accessProjectRow = accessProjectName.closest("tr");
    expect(accessProjectRow).not.toBeNull();
    const accessConfigButton = within(accessProjectRow!).getByRole("button", {
      name: "配置仅授权管理工程",
    });
    expect(accessConfigButton).toBeEnabled();
    expect(
      within(accessProjectRow!).getByRole("button", {
        name: "删除仅授权管理工程",
      }),
    ).toBeDisabled();
    expect(within(accessProjectRow!).getByRole("switch")).toBeDisabled();

    fireEvent.click(accessConfigButton);
    const accessDrawer = (await screen.findByText("工程配置")).closest(
      ".ant-drawer",
    );
    expect(accessDrawer).not.toBeNull();
    expect(within(accessDrawer!).getByLabelText("工程名称")).toBeDisabled();
    expect(
      within(accessDrawer!).queryByRole("combobox", {
        name: "允许访问的角色",
      }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      within(accessDrawer!).getByRole("button", { name: /保存/ }),
    );
    await waitFor(() => {
      expect(mockApi.updateAdminWorkspace).toHaveBeenCalledWith(23, {
        action: "updateAccess",
        expectedUpdatedAt: "2026-07-29T08:00:00+08:00",
        accessGroupIds: [],
      });
    });

    fireEvent.click(ownStatusSwitch);
    await waitFor(() => {
      expect(mockApi.updateAdminWorkspace).toHaveBeenCalledWith(21, {
        action: "setStatus",
        expectedUpdatedAt: "2026-07-29T10:00:00+08:00",
        status: "inactive",
      });
    });
  }, 30000);

  it("uses usernames when superadmin workspace owner display names are empty", async () => {
    mockApi.adminWorkspaces.mockResolvedValue({
      items: [
        {
          id: 1,
          kind: "project",
          name: "超级管理员保存工程",
          description: "无显示名账号保存",
          snapshot: { version: 1, groups: [] },
          owner: {
            id: 1,
            username: "superadmin",
            displayName: "",
          },
          createdAt: "2026-06-01T10:00:00+08:00",
          updatedAt: "2026-06-01T10:00:00+08:00",
          status: "active",
          accessGroups: [],
          canEdit: true,
          canDelete: true,
          canManageAccess: true,
        },
      ],
      total: 1,
      availableAccessGroups: [],
    });

    renderAdminRoute("/resources/manage/projects");

    expect(await screen.findByText("超级管理员保存工程")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "配置超级管理员保存工程" }),
    );

    await waitFor(() => {
      expect(screen.getAllByText("superadmin").length).toBeGreaterThan(1);
    });
  });
});
