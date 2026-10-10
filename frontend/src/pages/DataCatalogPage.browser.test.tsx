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

const mockApi = vi.hoisted(() => ({
  resources: vi.fn(),
  dataSchemaSummary: vi.fn(),
}));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  api: mockApi,
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { permissions: { canBrowseData: true } } }),
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
    <ConfigProvider locale={zhCN}>
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
});
