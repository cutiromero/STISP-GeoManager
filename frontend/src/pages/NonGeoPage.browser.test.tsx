import { App as AntApp } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import NonGeoPage from "./NonGeoPage";
import NonGeoScatter, { finiteValue, isMeasurement } from "./NonGeoScatter";
import { createNonGeoDemo } from "./nonGeoDemoData";
import "../styles.css";

const permissionState = vi.hoisted(() => ({
  canQueryData: true,
  canBrowseData: true,
}));
vi.mock("../components/WorkspaceHeader", () => ({
  default: () => <header>STISP</header>,
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({
    user: {
      permissions: {
        canBrowseData: permissionState.canBrowseData,
        canQueryData: permissionState.canQueryData,
      },
    },
  }),
}));
const demo = createNonGeoDemo("zh-CN");
beforeEach(() => {
  permissionState.canQueryData = true;
  permissionState.canBrowseData = true;
  vi.restoreAllMocks();
  vi.spyOn(api, "resources").mockResolvedValue({ items: [] });
  vi.spyOn(api, "dataSchemaSummary").mockRejectedValue(
    new Error("No schema in fixture"),
  );
});
function show() {
  return render(
    <AntApp>
      <MemoryRouter
        initialEntries={["/nongeo?domainType=genome&categoryCode=test"]}
      >
        <NonGeoPage />
      </MemoryRouter>
    </AntApp>,
  );
}
it("shows only the poplar showcase without loading project or algorithm test data", async () => {
  vi.mocked(api.resources).mockResolvedValue({
    items: [
      {
        ...demo.resource,
        id: 7,
        name: "Algorithm test raster",
        dataType: "raster",
      },
    ],
  });
  const analyze = vi.spyOn(api, "nonGeoAnalysis");
  const { container } = show();
  expect(await screen.findByText("数值分布 · 株高")).toBeInTheDocument();
  expect(container.querySelectorAll(".nongeo-resource-row")).toHaveLength(1);
  expect(screen.queryByText("Algorithm test raster")).not.toBeInTheDocument();
  expect(api.resources).not.toHaveBeenCalled();
  expect(analyze).not.toHaveBeenCalled();
});
it("keeps generic category selection within the showcase", async () => {
  show();
  expect(await screen.findByText("结构占比 · 地区")).toBeInTheDocument();
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "分类维度" }));
  fireEvent.click(
    await screen.findByText("科名", {
      selector: ".ant-select-item-option-content",
    }),
  );
  expect(await screen.findByText("结构占比 · 科名")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /指标关系/ })).toBeInTheDocument();
});
it("allows the showcase without real-data query permission", async () => {
  permissionState.canQueryData = false;
  show();
  expect(await screen.findByText("数值分布 · 株高")).toBeInTheDocument();
});
it("respects the existing browse permission", () => {
  permissionState.canBrowseData = false;
  const { container } = show();
  expect(screen.getByText("当前用户暂无数据浏览权限")).toBeInTheDocument();
  expect(container.querySelectorAll(".nongeo-resource-row")).toHaveLength(0);
});
it("removes ornamental workspace entries and keeps histogram selection in sync", async () => {
  const { container } = show();
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
