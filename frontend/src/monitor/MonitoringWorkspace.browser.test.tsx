import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { expect, it, vi } from "vitest";
import { App } from "antd";
import type {
  MonitoringProduct,
  ResourceListItem,
} from "../api/generated/types.gen";
import { requestJson } from "../api/client";
import { useMonitoringWorkspace } from "./useMonitoringWorkspace";
import MonitorRegionControls from "./MonitorRegionControls";
import MonitoringSourceControls from "./MonitoringSourceControls";
import MonitorTimeline from "./MonitorTimeline";
import { createMonitorMapMock } from "./test/monitorMapbox";
import { sourceCatalog, sourceTimes } from "./monitoringWorkspace.testFixtures";
vi.mock("../api/client", () => ({
  requestJson: vi.fn(async (url: string) =>
    url.includes("source-times")
      ? { ...sourceTimes, resourceId: 9000 }
      : sourceCatalog("wildfire", [
          {
            id: 9000,
            name: "新增年份资料",
            updatedAt: "2026-11-15",
          } as ResourceListItem,
        ]),
  ),
}));

it("draws a two-corner ROI and accepts the real source period beyond the old limit", async () => {
  const map = createMonitorMapMock({
    container: document.createElement("div"),
    style: { version: 8, sources: {}, layers: [] },
  });
  function Workspace() {
    const w = useMonitoringWorkspace("wildfire", 13);
    return (
      <App>
        <MonitoringSourceControls workspace={w} />
        <MonitorRegionControls map={map.value} workspace={w} />
        <output data-testid="selection">
          {JSON.stringify({
            inputs: w.inputs,
            time: w.time?.ordinal,
            region: w.region,
            ready: w.ready,
          })}
        </output>
      </App>
    );
  }
  const view = render(<Workspace />);
  await waitFor(() =>
    expect(screen.getByTestId("selection")).toHaveTextContent('"time":2000'),
  );
  expect(screen.getByTestId("selection")).toHaveTextContent('"ready":true');
  fireEvent.click(screen.getByRole("button", { name: "绘制研究区" }));
  map.emit("click", { lngLat: { lng: 120, lat: 30 } });
  map.emit("mousemove", { lngLat: { lng: 121, lat: 31 } });
  map.emit("click", { lngLat: { lng: 121, lat: 31 } });
  await waitFor(() =>
    expect(screen.getByTestId("selection")).toHaveTextContent('"ready":true'),
  );
  expect(screen.getByTestId("selection")).toHaveTextContent('"cube":9000');
  expect(map.layers.has("monitor-roi-line")).toBe(true);
  expect(map.api.doubleClickZoom.enable).toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "绘制研究区" }));
  map.api.remove();
  expect(() => view.unmount()).not.toThrow();
});

it("selects products by observation date and keeps unknown dates outside the dated sequence", async () => {
  const items = [
    {
      id: 2,
      name: "后期",
      observedStart: "2026-08-01",
      observedEnd: "2026-08-31",
    },
    {
      id: 1,
      name: "前期",
      observedStart: "2026-03-01",
      observedEnd: "2026-03-31",
    },
    { id: 3, name: "旧成果", observedStart: null, observedEnd: null },
  ] as MonitoringProduct[];
  const changed = vi.fn();
  function Timeline() {
    const [id, setId] = useState(1);
    return (
      <MonitorTimeline
        items={items}
        selected={items.find((row) => row.id === id)}
        onSelect={(value) => {
          changed(value);
          setId(value);
        }}
      />
    );
  }
  render(
    <App>
      <Timeline />
    </App>,
  );
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "下一期" }));
  expect(changed).toHaveBeenLastCalledWith(2);
  expect(
    screen.getByRole("combobox", { name: "切换观测日期" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("后期", { exact: true })).not.toBeInTheDocument();
});

it("shows a single RF interpretation period without playback controls", () => {
  const item = {
    id: 1,
    observedStart: "2025-03-01",
    observedEnd: "2025-12-31",
    extraction: { inputPeriods: ["2025-03", "2025-08", "2025-12"] },
  } as MonitoringProduct;
  render(
    <App>
      <MonitorTimeline
        items={[item, { ...item, id: 2 }]}
        selected={item}
        onSelect={vi.fn()}
      />
    </App>,
  );
  expect(screen.getByLabelText("成果观测时段")).toHaveTextContent("联合解译");
  expect(screen.getByLabelText("成果观测时段")).toHaveTextContent("2025.03–12");
  expect(
    screen.queryByRole("button", { name: "循环播放" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
});

it("loops playback from the last observation period back to the first", async () => {
  const items = [
    { id: 1, observedStart: "2020-01-01", observedEnd: "2020-01-08" },
    { id: 2, observedStart: "2020-01-09", observedEnd: "2020-01-16" },
  ] as MonitoringProduct[];
  const changed = vi.fn();
  function Timeline() {
    const [id, setId] = useState(2);
    return (
      <MonitorTimeline
        items={items}
        selected={items.find((row) => row.id === id)}
        onSelect={(value) => {
          changed(value);
          setId(value);
        }}
      />
    );
  }
  render(
    <App>
      <Timeline />
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: "循环播放" }));
  await waitFor(() => expect(changed).toHaveBeenCalledWith(1), {
    timeout: 4000,
  });
  await waitFor(() => expect(changed).toHaveBeenLastCalledWith(2), {
    timeout: 4000,
  });
  fireEvent.click(screen.getByRole("button", { name: "停止循环" }));
});

it("pages raw observations across years and switches the raw date without changing the selected result", async () => {
  const catalog = sourceCatalog("wildfire", [
    { id: 9000, name: "野火观测", updatedAt: "2026-11-15" } as ResourceListItem,
  ]);
  catalog.assets[0]!.years.unshift({
    year: 2025,
    count: 1,
    validProducts: ["gwis_ba"],
  });
  vi.mocked(requestJson).mockImplementation(async (url) => {
    if (!String(url).includes("source-times")) return catalog as never;
    return {
      resourceId: 9000,
      indexVersion: "real-source-v1",
      items: String(url).includes("after=")
        ? [{ ordinal: 2000, date: "2026-01-01", endDate: "2026-01-08" }]
        : [{ ordinal: 1999, date: "2025-12-27", endDate: "2025-12-31" }],
      nextOrdinal: String(url).includes("after=") ? null : 1999,
    } as never;
  });
  function Workspace() {
    const w = useMonitoringWorkspace("wildfire", 13);
    return (
      <App>
        <MonitorTimeline workspace={w} items={[]} onSelect={vi.fn()} />
        <output data-testid="raw-selection">
          {JSON.stringify({
            year: w.selectedYear,
            ordinal: w.time?.ordinal,
            ready: w.ready,
            raw: w.sourceVisible,
            result: w.resultVisible,
            count: w.allTimes.length,
          })}
        </output>
      </App>
    );
  }
  render(<Workspace />);
  await waitFor(() =>
    expect(screen.getByTestId("raw-selection")).toHaveTextContent('"count":2'),
  );
  const target = screen.getByRole("combobox", { name: "时间对象" });
  fireEvent.mouseDown(target);
  fireEvent.click(
    await screen.findByText("原图", {
      selector: ".ant-select-item-option-content",
    }),
  );
  await waitFor(() =>
    expect(screen.getByTestId("raw-selection")).toHaveTextContent('"raw":true'),
  );
  fireEvent.click(screen.getByRole("button", { name: "上一期" }));
  await waitFor(() =>
    expect(screen.getByTestId("raw-selection")).toHaveTextContent(
      '"year":2025',
    ),
  );
  expect(screen.getByTestId("raw-selection")).toHaveTextContent(
    '"ordinal":1999',
  );
  expect(screen.getByTestId("raw-selection")).toHaveTextContent(
    '"result":false',
  );
  fireEvent.click(screen.getByRole("button", { name: "下一期" }));
  await waitFor(() =>
    expect(screen.getByTestId("raw-selection")).toHaveTextContent(
      '"year":2026',
    ),
  );
});
