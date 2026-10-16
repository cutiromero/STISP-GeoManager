import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ResourceListItem } from "../types";
import { fallbackTaxonomyTree } from "../utils/taxonomy";
import DataCatalogPage from "./DataCatalogPage";
import { page } from "vitest/browser";
import { resetProjectSession, setActiveProject } from "../projects/session";
import "../styles.css";

const mockApi = vi.hoisted(() => ({
  resources: vi.fn(),
  dataSchemaSummary: vi.fn(),
  deleteResources: vi.fn(),
  previewResourceDeletion: vi.fn(),
}));
const permissionState = vi.hoisted(() => ({ canDeleteDataResources: true }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  api: mockApi,
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({
    user: {
      permissions: {
        canBrowseData: true,
        canDeleteDataResources: permissionState.canDeleteDataResources,
      },
    },
  }),
}));
vi.mock("../components/WorkspaceHeader", () => ({ default: () => null }));

const result: ResourceListItem = {
  id: 8,
  projectTagId: 1,
  name: "绿洲 NDVI 计算结果",
  code: "compute-ndvi",
  dataType: "raster",
  spatialClass: "spatial",
  domainType: "other",
  category: {
    id: 3,
    type: "data_category",
    code: "compute_results",
    name: "计算结果",
    parentId: null,
    selectable: false,
  },
  categoryPath: [{ id: 3, code: "compute_results", name: "计算结果" }],
  classificationStatus: "classified",
  availableViews: ["map", "metadata"],
  defaultView: "map",
  source: "compute-output:internal-storage-key",
  provider: "",
  dataDate: null,
  spatialExtent: "",
  coordinateSystem: "EPSG:4326",
  fileFormat: "COG",
  description: "计算结果；任务 internal-task-id；SHA256 internal-checksum",
  qualityNote: "",
  sizeBytes: 256,
  itemCount: 1,
  status: "active",
  isQueryable: false,
  isRenderable: true,
  updatedAt: "2026-10-10T10:00:00+08:00",
};

function renderCatalog() {
  return render(
    <ConfigProvider locale={zhCN} theme={{ token: { motion: false } }}>
      <AntApp>
        <MemoryRouter initialEntries={["/data"]}>
          <Routes>
            <Route path="/data" element={<DataCatalogPage />} />
            <Route path="/map" element={<div>地理工作台入口</div>} />
          </Routes>
        </MemoryRouter>
      </AntApp>
    </ConfigProvider>,
  );
}

describe("data catalog computation results", () => {
  beforeEach(() => {
    resetProjectSession();
    permissionState.canDeleteDataResources = true;
    mockApi.deleteResources.mockReset();
    mockApi.previewResourceDeletion
      .mockReset()
      .mockImplementation(
        async ({ resourceIds }: { resourceIds: number[] }) => ({
          items: resourceIds.map((id) => ({
            resourceId: id,
            name: id === result.id ? result.name : "原始影像",
            status: "deletable",
            detail: "将删除资源记录及平台管理的文件。",
            historyReferenceCount: 0,
          })),
          confirmationToken: "reviewed-resource-snapshot",
        }),
      );
    mockApi.resources.mockReset().mockResolvedValue({ items: [result] });
    mockApi.dataSchemaSummary
      .mockReset()
      .mockResolvedValue({ catalogTree: fallbackTaxonomyTree });
  });

  it("filters stored computation results and hides internal provenance markers", async () => {
    renderCatalog();
    expect(await screen.findByText(result.name)).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("tree")).getByText("计算结果"));
    await waitFor(() => {
      expect(mockApi.resources).toHaveBeenLastCalledWith({
        categoryCode: "compute_results",
      });
    });
    expect(
      screen.getByText("已入库的算法输出，可查看结果或继续用于计算。"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /详情/ }));
    expect(await screen.findByText("平台算法计算")).toBeInTheDocument();
    expect(
      screen.queryByText(
        /internal-storage-key|internal-task-id|internal-checksum/,
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "用于计算" }),
    ).toBeInTheDocument();
  });

  it("keeps computation raster results linked to the map workspace", async () => {
    renderCatalog();
    fireEvent.click(await screen.findByRole("button", { name: "进入地图" }));
    expect(await screen.findByText("地理工作台入口")).toBeInTheDocument();
  });

  it("confirms selected names and removes only genuinely deleted resources", async () => {
    const retained = { ...result, id: 9, name: "原始影像" };
    mockApi.resources.mockResolvedValue({ items: [result, retained] });
    mockApi.deleteResources.mockResolvedValue({
      items: [
        {
          resourceId: 8,
          name: result.name,
          status: "deleted",
          detail: "已删除",
        },
        {
          resourceId: 9,
          name: retained.name,
          status: "blocked",
          detail: "被计算任务引用，请先处理相关任务",
        },
      ],
      deletedIds: [8],
      deletedCount: 1,
      failedCount: 1,
    });
    renderCatalog();
    await screen.findByText(result.name);
    fireEvent.click(screen.getByRole("button", { name: "文件管理" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "全选当前结果" }));
    expect(screen.getByText("已选择 2 项")).toBeInTheDocument();
    await page.screenshot({
      path: "../../test-results/catalog-file-management.png",
    });
    fireEvent.click(screen.getByRole("button", { name: "删除所选" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(result.name)).toBeInTheDocument();
    expect(within(dialog).getByText(retained.name)).toBeInTheDocument();
    expect(mockApi.deleteResources).not.toHaveBeenCalled();
    await page.screenshot({
      path: "../../test-results/catalog-file-delete-confirmation.png",
    });
    mockApi.resources.mockResolvedValue({ items: [retained] });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认删除" }));
    await waitFor(() =>
      expect(mockApi.deleteResources).toHaveBeenCalledWith(
        {
          resourceIds: [8, 9],
          confirmed: true,
          historyConfirmationToken: "reviewed-resource-snapshot",
        },
        "1",
      ),
    );
    expect(
      await screen.findByText("已删除 1 项，1 项未删除"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/被计算任务引用，请先处理相关任务/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("checkbox", { name: `选择文件 ${result.name}` }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: `选择文件 ${retained.name}` }),
    ).toBeChecked();
    expect(screen.getByText("已选择 1 项")).toBeInTheDocument();
  });

  it("keeps files and selection when the server rejects deletion", async () => {
    mockApi.deleteResources.mockRejectedValue(new Error("当前账号无删除权限"));
    renderCatalog();
    await screen.findByText(result.name);
    fireEvent.click(screen.getByRole("button", { name: "文件管理" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: `选择文件 ${result.name}` }),
    );
    fireEvent.click(screen.getByRole("button", { name: "删除所选" }));
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "确认删除",
      }),
    );
    expect(await screen.findByText("当前账号无删除权限")).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: `选择文件 ${result.name}` }),
    ).toBeChecked();
    expect(screen.getByText("已选择 1 项")).toBeInTheDocument();
  });

  it("shows retained shared storage and cleanup failures on deleted registrations", async () => {
    const detail =
      "已删除资源登记及关联图层、数据集；其他资源共用的存储已保留；部分隔离文件清理失败，请联系管理员";
    mockApi.deleteResources.mockResolvedValue({
      items: [
        { resourceId: result.id, name: result.name, status: "deleted", detail },
      ],
      deletedIds: [result.id],
      deletedCount: 1,
      failedCount: 0,
    });
    renderCatalog();
    await screen.findByText(result.name);
    fireEvent.click(screen.getByRole("button", { name: "文件管理" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: `选择文件 ${result.name}` }),
    );
    fireEvent.click(screen.getByRole("button", { name: "删除所选" }));
    mockApi.resources.mockResolvedValue({ items: [] });
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "确认删除",
      }),
    );
    const feedback = await screen.findByText(/部分隔离文件清理失败/);
    expect(feedback).toHaveTextContent("其他资源共用的存储已保留");
    expect(feedback.closest(".ant-alert")).toHaveClass("ant-alert-warning");
    expect(screen.getByText("已删除 1 项")).toBeInTheDocument();
  });

  it("does not delete after switching the project during confirmation", async () => {
    renderCatalog();
    await screen.findByText(result.name);
    fireEvent.click(screen.getByRole("button", { name: "文件管理" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: `选择文件 ${result.name}` }),
    );
    fireEvent.click(screen.getByRole("button", { name: "删除所选" }));
    const dialog = await screen.findByRole("dialog");
    setActiveProject("8");
    fireEvent.click(within(dialog).getByRole("button", { name: "确认删除" }));
    expect(
      await screen.findByText("项目已切换，请重新选择文件"),
    ).toBeInTheDocument();
    expect(mockApi.deleteResources).not.toHaveBeenCalled();
  });

  it("does not show file management without delete permission", async () => {
    permissionState.canDeleteDataResources = false;
    renderCatalog();
    await screen.findByText(result.name);
    expect(
      screen.queryByRole("button", { name: "文件管理" }),
    ).not.toBeInTheDocument();
  });

  it("previews historical workflow cleanup and submits only after user confirmation", async () => {
    mockApi.previewResourceDeletion.mockResolvedValue({
      items: [
        {
          resourceId: result.id,
          name: result.name,
          status: "confirmation_required",
          detail:
            "历史科研工作流引用该计算结果。删除后保留名称、来源及删除记录。",
          historyReferenceCount: 2,
        },
      ],
      confirmationToken: "history-snapshot",
    });
    mockApi.deleteResources.mockResolvedValue({
      items: [
        {
          resourceId: result.id,
          name: result.name,
          status: "deleted",
          detail: "已删除；保留历史任务及名称、来源和删除记录",
        },
      ],
      deletedIds: [result.id],
      deletedCount: 1,
      failedCount: 0,
    });
    renderCatalog();
    await screen.findByText(result.name);
    fireEvent.click(screen.getByRole("button", { name: "文件管理" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: `选择文件 ${result.name}` }),
    );
    fireEvent.click(screen.getByRole("button", { name: "删除所选" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText(/历史科研工作流引用/),
    ).toBeInTheDocument();
    expect(mockApi.deleteResources).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "确认删除" }));
    await waitFor(() =>
      expect(mockApi.deleteResources).toHaveBeenCalledWith(
        {
          resourceIds: [result.id],
          confirmed: true,
          historyConfirmationToken: "history-snapshot",
        },
        "1",
      ),
    );
  });

  it("keeps confirmation disabled for protected active dependencies", async () => {
    mockApi.previewResourceDeletion.mockResolvedValue({
      items: [
        {
          resourceId: result.id,
          name: result.name,
          status: "blocked",
          detail: "计算任务仍在使用该数据",
          historyReferenceCount: 0,
        },
      ],
      confirmationToken: "blocked-snapshot",
    });
    renderCatalog();
    await screen.findByText(result.name);
    fireEvent.click(screen.getByRole("button", { name: "文件管理" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: `选择文件 ${result.name}` }),
    );
    fireEvent.click(screen.getByRole("button", { name: "删除所选" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText("计算任务仍在使用该数据"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "确认删除" }),
    ).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: /取\s*消/ }));
    expect(mockApi.deleteResources).not.toHaveBeenCalled();
  });
  it("waits for the real preview and discards its reply after cancellation", async () => {
    let finishPreview:
      | ((value: { items: never[]; confirmationToken: string }) => void)
      | undefined;
    mockApi.previewResourceDeletion.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishPreview = resolve;
        }),
    );
    renderCatalog();
    await screen.findByText(result.name);
    fireEvent.click(screen.getByRole("button", { name: "文件管理" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: `选择文件 ${result.name}` }),
    );
    fireEvent.click(screen.getByRole("button", { name: "删除所选" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("button", { name: "确认删除" }),
    ).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: /取\s*消/ }));
    finishPreview?.({ items: [], confirmationToken: "obsolete" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(mockApi.deleteResources).not.toHaveBeenCalled();
  });
});
