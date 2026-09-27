import { App as AntApp } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import NonGeoPage from "./NonGeoPage";
import NonGeoScatter, { finiteValue, isMeasurement } from "./NonGeoScatter";
import { createNonGeoDemo } from "./nonGeoDemoData";
import "../styles.css";

const permissionState = vi.hoisted(() => ({ canQueryData: true }));
vi.mock("../components/WorkspaceHeader", () => ({
  default: () => <header>STISP</header>,
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({
    user: {
      permissions: {
        canBrowseData: true,
        canQueryData: permissionState.canQueryData,
      },
    },
  }),
}));
const demo = createNonGeoDemo("zh-CN");
beforeEach(() => {
  permissionState.canQueryData = true;
  vi.restoreAllMocks();
  vi.spyOn(api, "resources").mockResolvedValue({ items: [] });
  vi.spyOn(api, "dataSchemaSummary").mockRejectedValue(
    new Error("No schema in fixture"),
  );
});
it("keeps query permission boundaries and allows explicit examples", async () => {
  permissionState.canQueryData = false;
  vi.mocked(api.resources).mockResolvedValue({
    items: [{ ...demo.resource, id: 10, name: "观测数据" }],
  });
  const analyze = vi.spyOn(api, "nonGeoAnalysis");
  show();
  expect(await screen.findByText("当前角色无数据查询权限")).toBeInTheDocument();
  expect(analyze).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "查看胡杨数据示例" }));
  expect(await screen.findByText("数值分布 · 株高")).toBeInTheDocument();
});
it("filters spatial and non-spatial resources and updates the selected workflow", async () => {
  vi.mocked(api.resources).mockResolvedValue({
    items: [
      { ...demo.resource, id: 11, name: "区域影像", dataType: "raster" },
      { ...demo.resource, id: 12, name: "调查文档", dataType: "document" },
    ],
  });
  const { container } = show();
  await screen.findByText("选择分析方式");
  fireEvent.click(screen.getByRole("radio", { name: "非地理" }));
  await waitFor(() =>
    expect(container.querySelectorAll(".nongeo-resource-row")).toHaveLength(1),
  );
  expect(container.querySelector(".nongeo-resource-row")).toHaveTextContent(
    "调查文档",
  );
  expect(
    screen.queryByRole("button", { name: "在地理工作台查找" }),
  ).not.toBeInTheDocument();
});
function show() {
  return render(
    <AntApp>
      <MemoryRouter>
        <NonGeoPage />
      </MemoryRouter>
    </AntApp>,
  );
}
it("starts with a generic empty workspace and an explicit example entry", async () => {
  show();
  expect(
    await screen.findByRole("button", { name: "查看胡杨数据示例" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("数值分布 · 株高")).not.toBeInTheDocument();
  expect(screen.getByText("请选择左侧数据资源")).toBeInTheDocument();
});
it("routes spatial resources to their workflow without calling table analysis", async () => {
  vi.mocked(api.resources).mockResolvedValue({
    items: [{ ...demo.resource, id: 8, name: "区域影像", dataType: "raster" }],
  });
  const analyze = vi.spyOn(api, "nonGeoAnalysis");
  show();
  expect(await screen.findByText("选择分析方式")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "在地理工作台查找" }),
  ).toBeInTheDocument();
  expect(analyze).not.toHaveBeenCalled();
  expect(vi.mocked(api.resources)).toHaveBeenCalledWith({});
});
it("uses actual table fields for generic analysis and category selection", async () => {
  vi.mocked(api.resources).mockResolvedValue({
    items: [
      { ...demo.resource, id: 9, name: "城市观测记录", dataType: "table" },
    ],
  });
  const analytics = {
    ...demo.analytics,
    categoricalDistributions: [
      {
        ...demo.analytics.categoricalDistributions[0],
        field: "city",
        label: "城市",
      },
      {
        ...demo.analytics.categoricalDistributions[1],
        field: "period",
        label: "时段",
      },
    ],
  };
  vi.spyOn(api, "nonGeoAnalysis").mockResolvedValue(analytics);
  show();
  expect(await screen.findByText("结构占比 · 城市")).toBeInTheDocument();
  expect(api.nonGeoAnalysis).toHaveBeenCalledWith(9);
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "分类维度" }));
  fireEvent.click(
    await screen.findByText("时段", {
      selector: ".ant-select-item-option-content",
    }),
  );
  expect(await screen.findByText("结构占比 · 时段")).toBeInTheDocument();
});
it("removes ornamental workspace entries and keeps histogram selection in sync", async () => {
  const { container } = show();
  fireEvent.click(
    await screen.findByRole("button", { name: "查看胡杨数据示例" }),
  );
  await screen.findByText("数值分布 · 株高");
  for (const text of ["分析资产", "核心指标", "资源快照", "视图组合"])
    expect(screen.queryByText(text)).not.toBeInTheDocument();
  expect(container.querySelector(".nongeo-insight-panel")).toBeNull();
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "指标字段" }));
  expect(
    screen.queryByText("地点号", {
      selector: ".ant-select-item-option-content",
    }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    await screen.findByText("胸径", {
      selector: ".ant-select-item-option-content",
    }),
  );
  expect(await screen.findByText("数值分布 · 胸径")).toBeInTheDocument();
  const chart = screen.getByText("数值分布 · 胸径").closest("section")!;
  expect(chart.querySelector(".nongeo-histogram-axis")).toHaveTextContent(
    "96.4",
  );
});
it("uses meaningful scatter axes, small uniform points and accurate pair count", async () => {
  const { container } = render(
    <NonGeoScatter tableData={demo.table} fields={demo.analytics.fields} />,
  );
  expect(
    screen.getByRole("img", { name: "株高 (m) × 胸径 (cm)" }),
  ).toBeInTheDocument();
  const dots = [...container.querySelectorAll("circle")];
  expect(dots).toHaveLength(12);
  expect(
    dots.every(
      (dot) =>
        dot.getAttribute("r") === "3" &&
        dot.classList.contains("analysis-point"),
    ),
  ).toBe(true);
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "横轴指标" }));
  fireEvent.click(
    await screen.findByText("比叶面积 (cm²/g)", {
      selector: ".ant-select-item-option-content",
    }),
  );
  expect(
    await screen.findByRole("img", { name: "比叶面积 (cm²/g) × 胸径 (cm)" }),
  ).toBeInTheDocument();
  expect(screen.getByText(/12 条有效记录/)).toBeInTheDocument();
});
it("does not turn missing or nonnumeric values into zero, and identifies plot IDs", () => {
  for (const value of [null, undefined, "", "  ", true, Infinity, "missing"])
    expect(finiteValue(value)).toBeNull();
  expect(finiteValue(0)).toBe(0);
  expect(finiteValue("2.5")).toBe(2.5);
  expect(
    isMeasurement(
      demo.analytics.fields.find((field) => field.name === "plot_number")!,
    ),
  ).toBe(false);
});
it("keeps real-resource errors visible instead of silently substituting the demo", async () => {
  vi.mocked(api.resources).mockResolvedValue({
    items: [{ ...demo.resource, id: 7, name: "真实表格", isQueryable: true }],
  });
  vi.spyOn(api, "nonGeoAnalysis").mockRejectedValue(new Error("数据暂不可用"));
  show();
  expect(await screen.findByText("数据暂不可用")).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.queryByText("数值分布 · 株高")).not.toBeInTheDocument(),
  );
});
