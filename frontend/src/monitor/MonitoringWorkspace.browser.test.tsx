import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { expect, it, vi } from "vitest";
import { App } from "antd";
import type {
  MonitoringProduct,
  ResourceListItem,
} from "../api/generated/types.gen";
import { useMonitoringWorkspace } from "./useMonitoringWorkspace";
import MonitorRegionControls from "./MonitorRegionControls";
import MonitoringSourceControls from "./MonitoringSourceControls";
import MonitorTimeline from "./MonitorTimeline";
import { createMonitorMapMock } from "./test/monitorMapbox";
import { sourceCatalog, sourceTimes } from "./monitoringWorkspace.testFixtures";
vi.mock("../api/client", () => ({
  requestJson: vi.fn(async (url: string) =>
    url.includes("source-times")
      ? sourceTimes
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
  expect(screen.getByTestId("selection")).toHaveTextContent('"ready":false');
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
  const range = screen.getByRole("slider", { name: "切换成果时期" });
  expect(range).toHaveAttribute("max", "1");
  fireEvent.change(range, { target: { value: "1" } });
  expect(changed).toHaveBeenLastCalledWith(2);
  await screen.findByText("2026-08-01 — 2026-08-31", { exact: true });
});
