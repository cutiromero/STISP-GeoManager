import { App as AntApp } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import NonGeoPage from "./NonGeoPage";
import NonGeoScatter, { finiteValue, isMeasurement } from "./NonGeoScatter";
import { createNonGeoDemo } from "./nonGeoDemoData";
import "../styles.css";

vi.mock("../components/WorkspaceHeader", () => ({
  default: () => <header>STISP</header>,
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({
    user: { permissions: { canBrowseData: true, canQueryData: true } },
  }),
}));
const demo = createNonGeoDemo("zh-CN");
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "resources").mockResolvedValue({ items: [] });
  vi.spyOn(api, "dataSchemaSummary").mockRejectedValue(
    new Error("No schema in fixture"),
  );
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
