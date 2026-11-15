import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import type { MonitoringProduct } from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import { businessFlowRun } from "../businessflows/businessFlow.testFixtures";
import {
  MonitorDataStatus,
  MonitorLayerStatusProvider,
} from "./MonitorLayerStatus";
import MonitorTimeline from "./MonitorTimeline";
import { useMonitorTask } from "./useMonitorTask";

vi.mock("../api/businessFlows", () => ({
  businessFlowsApi: { runs: vi.fn(), run: vi.fn() },
}));
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.mocked(businessFlowsApi.runs).mockResolvedValue({ items: [] });
});

it("waits for result layers before advancing playback and stops on a display failure", async () => {
  const changed = vi.fn();
  const items = [
    { id: 1, observedStart: "2020-01-01" },
    { id: 2, observedStart: "2020-01-09" },
  ] as MonitoringProduct[];
  function Timeline({
    busy,
    failed = false,
  }: {
    busy: boolean;
    failed?: boolean;
  }) {
    const [id, setId] = useState(1);
    return (
      <App>
        <MonitorLayerStatusProvider>
          <MonitorDataStatus
            title="观测图"
            loading={busy}
            error={failed ? "图层加载失败" : undefined}
          />
          <MonitorTimeline
            items={items}
            selected={items.find((row) => row.id === id)}
            onSelect={(value) => {
              changed(value);
              setId(value);
            }}
          />
        </MonitorLayerStatusProvider>
      </App>
    );
  }
  const view = render(<Timeline busy />);
  fireEvent.click(screen.getByRole("button", { name: "循环播放" }));
  expect(screen.getByRole("button", { name: "停止循环" })).toHaveTextContent(
    "缓冲",
  );
  await new Promise((resolve) => setTimeout(resolve, 2700));
  expect(changed).not.toHaveBeenCalled();
  view.rerender(<Timeline busy={false} />);
  await waitFor(() => expect(changed).toHaveBeenCalledWith(2), {
    timeout: 3500,
  });
  view.rerender(<Timeline busy={false} failed />);
  await screen.findByRole("button", { name: "循环播放" });
});

it("refreshes results once when a task completes directly after approval", async () => {
  const completed = vi.fn();
  const waiting = businessFlowRun({
    projectId: 13,
    flowId: 2,
    status: "waiting_approval",
  });
  function Task() {
    const task = useMonitorTask(13, 99, completed, 2, "wildfire");
    return (
      <>
        <button onClick={() => task.accept(waiting)}>waiting</button>
        <button
          onClick={() =>
            task.accept({
              ...waiting,
              status: "succeeded",
              revision: waiting.revision + 1,
            })
          }
        >
          complete
        </button>
      </>
    );
  }
  render(<Task />);
  fireEvent.click(screen.getByText("waiting"));
  expect(completed).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("complete"));
  fireEvent.click(screen.getByText("complete"));
  expect(completed).toHaveBeenCalledOnce();
});
