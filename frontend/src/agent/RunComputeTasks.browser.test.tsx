import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import type { ComputeTask } from "../api/generated/types.gen";
import { liveComputeTask } from "./computeFlow.testFixtures";
import RunComputeTasks from "./RunComputeTasks";
import "./agent.css";

function Location() {
  const location = useLocation();
  return (
    <output aria-label="当前位置">
      {location.pathname}
      {location.search}
    </output>
  );
}
function show() {
  return render(
    <AntApp>
      <MemoryRouter>
        <RunComputeTasks runId={8} refreshKey="1" />
        <Location />
      </MemoryRouter>
    </AntApp>,
  );
}
function result(task: ComputeTask) {
  return {
    items: [
      {
        task,
        autoImport: false,
        trackingStatus:
          task.status === "succeeded" ? "completed" : "waiting_compute",
        detail: "",
      },
    ],
  };
}
beforeEach(() => {
  vi.restoreAllMocks();
});
afterEach(() => {
  vi.useRealTimers();
});

it("offers map preview without first importing and avoids displaying task or resource identifiers", async () => {
  const task = liveComputeTask("succeeded");
  vi.spyOn(agentApi, "computeTasks").mockResolvedValue(result(task));
  const importOutput = vi.spyOn(computeApi, "importOutput");
  show();
  await screen.findByText("计算完成，结果已保存。");
  expect(
    screen.getByText("研究区影像 · 红光波段 第 3 波段 · 近红外波段 第 8 波段"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("259 × 260 · 1 波段 · EPSG:3857"),
  ).toBeInTheDocument();
  expect(screen.queryByText(task.id)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "在地理工作台查看" }));
  expect(screen.getByRole("status", { name: "当前位置" })).toHaveTextContent(
    "/map?computeOutputId=30&projectTagId=1",
  );
  expect(importOutput).not.toHaveBeenCalled();
});

it("imports once then follows the current state to the friendly database location", async () => {
  const task = liveComputeTask("succeeded");
  const output = task.outputs[0]!;
  const poll = vi
    .spyOn(agentApi, "computeTasks")
    .mockResolvedValueOnce(result(task));
  const imported = {
    ...output,
    importStatus: "ready" as const,
    resourceId: 180,
    resourceName: "研究区影像 · NDVI",
    resourceLocation: "公开 / 数据资源 / 研究区影像 · NDVI",
    mapUrl: "/map?resourceId=180&projectTagId=1",
  };
  poll.mockResolvedValue(result({ ...task, outputs: [imported] }));
  const importOutput = vi
    .spyOn(computeApi, "importOutput")
    .mockResolvedValue({ ...output, importStatus: "queued" });
  show();
  const button = await screen.findByRole("button", { name: "将结果入库" });
  fireEvent.click(button);
  fireEvent.click(button);
  await screen.findByText("公开 / 数据资源 / 研究区影像 · NDVI");
  expect(importOutput).toHaveBeenCalledOnce();
  expect(importOutput).toHaveBeenCalledWith(30, { name: task.name });
  expect(screen.queryByText("180", { exact: true })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "在地理工作台查看" }));
  expect(screen.getByRole("status", { name: "当前位置" })).toHaveTextContent(
    "/map?resourceId=180&projectTagId=1",
  );
});

it("polls by interval and stops when the computation reaches a terminal state", async () => {
  const poll = vi
    .spyOn(agentApi, "computeTasks")
    .mockResolvedValue(result(liveComputeTask()));
  const { unmount } = show();
  await screen.findByText("排队中");
  expect(poll).toHaveBeenCalledOnce();
  poll.mockResolvedValue(result(liveComputeTask("succeeded")));
  await waitFor(
    () => expect(screen.getByText("计算完成")).toBeInTheDocument(),
    { timeout: 5000 },
  );
  expect(poll).toHaveBeenCalledTimes(2);
  vi.useFakeTimers();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(20000);
  });
  expect(poll).toHaveBeenCalledTimes(2);
  unmount();
});

it("removes stale result cards after permission revocation", async () => {
  const poll = vi
    .spyOn(agentApi, "computeTasks")
    .mockResolvedValue(result(liveComputeTask()));
  const { rerender } = show();
  await screen.findByText("排队中");
  const denied = Object.assign(new Error("无权查看此任务"), { status: 403 });
  poll.mockRejectedValue(denied);
  rerender(
    <AntApp>
      <MemoryRouter>
        <RunComputeTasks runId={8} refreshKey="2" />
        <Location />
      </MemoryRouter>
    </AntApp>,
  );
  await screen.findByText("无权查看此任务");
  expect(
    screen.queryByRole("region", { name: "研究区影像 · NDVI" }),
  ).not.toBeInTheDocument();
});

it("opens the permanent resource even when its temporary output has expired", async () => {
  const task = liveComputeTask("succeeded");
  vi.spyOn(agentApi, "computeTasks").mockResolvedValue(
    result({
      ...task,
      outputs: [
        {
          ...task.outputs[0]!,
          expired: true,
          importStatus: "ready",
          resourceId: 180,
          resourceName: "研究区NDVI",
          resourceLocation: "公开 / 数据资源 / 研究区NDVI",
          mapUrl: "/map?resourceId=180&projectTagId=1",
        },
      ],
    }),
  );
  show();
  fireEvent.click(
    await screen.findByRole("button", { name: "在地理工作台查看" }),
  );
  expect(screen.getByRole("status", { name: "当前位置" })).toHaveTextContent(
    "/map?resourceId=180&projectTagId=1",
  );
});
