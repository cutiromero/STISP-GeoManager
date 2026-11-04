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
import type {
  AgentComputeTaskTracking,
  ComputeTask,
} from "../api/generated/types.gen";
import type { LiveActivity } from "./agentActivity";
import { liveComputeTask } from "./computeFlow.testFixtures";
import RunComputeTasks, { computeTasksActivity } from "./RunComputeTasks";
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
function show(onActivityChange?: (activity: LiveActivity) => void) {
  return render(
    <AntApp>
      <MemoryRouter>
        <RunComputeTasks
          runId={8}
          refreshKey="1"
          activityTaskId={liveComputeTask().id}
          onActivityChange={onActivityChange}
        />
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
  vi.spyOn(window, "open").mockReturnValue(null);
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
    screen.getByText("研究区影像 / 红光波段 第 3 波段 / 近红外波段 第 8 波段"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("259 × 260 / 1 波段 / EPSG:3857"),
  ).toBeInTheDocument();
  expect(screen.queryByText(task.id)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "在地理工作台查看" }));
  expect(window.open).toHaveBeenCalledWith(
    "/map?computeOutputId=30&projectTagId=1",
    "_blank",
    "noopener",
  );
  expect(screen.getByRole("status", { name: "当前位置" }).textContent).toBe(
    "/",
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
    resourceName: "研究区影像 / NDVI",
    resourceLocation: "公开 / 数据资源 / 研究区影像 / NDVI",
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
  await screen.findByText("公开 / 数据资源 / 研究区影像 / NDVI");
  expect(importOutput).toHaveBeenCalledOnce();
  expect(importOutput).toHaveBeenCalledWith(30, { name: task.name });
  expect(screen.queryByText("180", { exact: true })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "在地理工作台查看" }));
  expect(window.open).toHaveBeenCalledWith(
    "/map?resourceId=180&projectTagId=1",
    "_blank",
    "noopener",
  );
  expect(screen.getByRole("status", { name: "当前位置" }).textContent).toBe(
    "/",
  );
});

it("polls by interval and stops when the computation reaches a terminal state", async () => {
  const poll = vi
    .spyOn(agentApi, "computeTasks")
    .mockResolvedValue(result(liveComputeTask()));
  const activity = vi.fn<(activity: LiveActivity) => void>();
  const { unmount } = show(activity);
  await screen.findByText("排队中");
  expect(poll).toHaveBeenCalledOnce();
  expect(activity).toHaveBeenLastCalledWith(
    expect.objectContaining({ state: "working" }),
  );
  poll.mockResolvedValue(result(liveComputeTask("succeeded")));
  await waitFor(
    () => expect(screen.getByText("计算完成")).toBeInTheDocument(),
    { timeout: 5000 },
  );
  expect(poll).toHaveBeenCalledTimes(2);
  expect(activity).toHaveBeenLastCalledWith(
    expect.objectContaining({ state: "complete", label: "计算已完成" }),
  );
  vi.useFakeTimers();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(20000);
  });
  expect(poll).toHaveBeenCalledTimes(2);
  unmount();
});

it.each([401, 403])(
  "removes stale result cards after permission revocation (%s)",
  async (status) => {
    const poll = vi
      .spyOn(agentApi, "computeTasks")
      .mockResolvedValue(result(liveComputeTask()));
    const activity = vi.fn<(activity: LiveActivity) => void>();
    const { rerender } = show(activity);
    await screen.findByText("排队中");
    const denied = Object.assign(new Error("无权查看此任务"), { status });
    poll.mockRejectedValue(denied);
    rerender(
      <AntApp>
        <MemoryRouter>
          <RunComputeTasks
            runId={8}
            refreshKey="2"
            activityTaskId={liveComputeTask().id}
            onActivityChange={activity}
          />
          <Location />
        </MemoryRouter>
      </AntApp>,
    );
    await screen.findByText("无权查看此任务");
    expect(
      screen.queryByRole("region", { name: "研究区影像 / NDVI" }),
    ).not.toBeInTheDocument();
    expect(activity).toHaveBeenLastCalledWith(
      expect.objectContaining({ state: "stopped", label: "计算状态不可用" }),
    );
  },
);

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
  expect(window.open).toHaveBeenCalledWith(
    "/map?resourceId=180&projectTagId=1",
    "_blank",
    "noopener",
  );
  expect(screen.getByRole("status", { name: "当前位置" }).textContent).toBe(
    "/",
  );
});

it("maps only the bound task and treats optional import as completed computation", () => {
  const task = liveComputeTask("succeeded");
  const item = result(task).items[0]!;
  const other = result({ ...liveComputeTask("running"), id: "other" })
    .items[0]!;
  expect(computeTasksActivity([other, item], task.id)).toMatchObject({
    state: "complete",
    label: "计算已完成",
  });
  expect(computeTasksActivity([other], task.id)).toMatchObject({
    state: "working",
    label: "正在读取计算进度",
  });
  expect(
    computeTasksActivity([{ ...item, trackingStatus: "waiting_compute" }]),
  ).toMatchObject({ state: "complete" });
  expect(
    computeTasksActivity([{ ...item, trackingStatus: "waiting_import" }]),
  ).toMatchObject({ state: "complete" });
});

it("keeps actual calculations and requested imports active until their terminal state", () => {
  for (const status of [
    "queued",
    "validating",
    "running",
    "cancelling",
  ] as const)
    expect(
      computeTasksActivity(result(liveComputeTask(status)).items).state,
    ).toBe("working");
  const task = liveComputeTask("succeeded");
  const item = result(task).items[0]!;
  for (const trackingStatus of ["waiting_compute", "waiting_import"])
    expect(
      computeTasksActivity([{ ...item, autoImport: true, trackingStatus }]),
    ).toMatchObject({ state: "working", label: "正在保存计算成果" });
  for (const importStatus of ["queued", "running", "ready"] as const)
    expect(
      computeTasksActivity([
        {
          ...item,
          task: {
            ...task,
            outputs: [{ ...task.outputs[0]!, importStatus }],
          },
        },
      ]),
    ).toMatchObject({
      state: importStatus === "ready" ? "complete" : "working",
      label: importStatus === "ready" ? "计算与入库已完成" : "正在保存计算成果",
    });
  for (const trackingStatus of ["waiting_compute", "waiting_import"])
    expect(
      computeTasksActivity([
        {
          ...item,
          autoImport: true,
          trackingStatus,
          task: {
            ...task,
            outputs: [{ ...task.outputs[0]!, importStatus: "ready" }],
          },
        },
      ]),
    ).toMatchObject({ state: "complete", label: "计算与入库已完成" });
});

it("stops failed, cancelled, interrupted or blocked computation without masking it as success", () => {
  for (const status of ["failed", "cancelled", "interrupted"] as const)
    expect(
      computeTasksActivity(result(liveComputeTask(status)).items).state,
    ).toBe("stopped");
  const task = liveComputeTask("succeeded");
  const item = result(task).items[0]!;
  for (const trackingStatus of ["blocked", "failed"])
    expect(computeTasksActivity([{ ...item, trackingStatus }]).state).toBe(
      "stopped",
    );
  expect(
    computeTasksActivity([
      {
        ...item,
        task: {
          ...task,
          outputs: [{ ...task.outputs[0]!, importStatus: "failed" }],
        },
      },
    ]),
  ).toMatchObject({ state: "stopped", label: "计算完成，入库失败" });
});

it("does not restart polling when the parent passes a new activity callback", async () => {
  const poll = vi
    .spyOn(agentApi, "computeTasks")
    .mockResolvedValue(result(liveComputeTask()));
  const first = vi.fn<(activity: LiveActivity) => void>();
  const next = vi.fn<(activity: LiveActivity) => void>();
  const { rerender } = show(first);
  await screen.findByText("排队中");
  rerender(
    <AntApp>
      <MemoryRouter>
        <RunComputeTasks
          runId={8}
          refreshKey="1"
          activityTaskId={liveComputeTask().id}
          onActivityChange={next}
        />
        <Location />
      </MemoryRouter>
    </AntApp>,
  );
  expect(poll).toHaveBeenCalledOnce();
  poll.mockResolvedValue(result(liveComputeTask("succeeded")));
  await waitFor(
    () =>
      expect(next).toHaveBeenCalledWith(
        expect.objectContaining({ state: "complete" }),
      ),
    { timeout: 5000 },
  );
  expect(poll).toHaveBeenCalledTimes(2);
  expect(next).toHaveBeenLastCalledWith(
    expect.objectContaining({ state: "complete" }),
  );
});

it("rechecks transient read failures rather than reporting completion", async () => {
  vi.spyOn(agentApi, "computeTasks").mockRejectedValue(new Error("暂时离线"));
  const activity = vi.fn<(activity: LiveActivity) => void>();
  show(activity);
  await screen.findByText("暂时离线");
  expect(activity).toHaveBeenLastCalledWith(
    expect.objectContaining({
      state: "working",
      label: "正在重新核对计算状态",
    }),
  );
});

it("keeps the requested import active, then reports the imported result as complete", async () => {
  const task = liveComputeTask("succeeded");
  const output = task.outputs[0]!;
  const poll = vi
    .spyOn(agentApi, "computeTasks")
    .mockResolvedValue(
      result({ ...task, outputs: [{ ...output, importStatus: "running" }] }),
    );
  const activity = vi.fn<(activity: LiveActivity) => void>();
  show(activity);
  await screen.findByText("正在入库");
  expect(activity).toHaveBeenLastCalledWith(
    expect.objectContaining({ state: "working", label: "正在保存计算成果" }),
  );
  poll.mockResolvedValue(
    result({ ...task, outputs: [{ ...output, importStatus: "ready" }] }),
  );
  await waitFor(
    () =>
      expect(activity).toHaveBeenLastCalledWith(
        expect.objectContaining({
          state: "complete",
          label: "计算与入库已完成",
        }),
      ),
    { timeout: 5000 },
  );
  expect(poll).toHaveBeenCalledTimes(2);
});

it("rechecks an initially missing bound task without using a historical task status", async () => {
  const poll = vi
    .spyOn(agentApi, "computeTasks")
    .mockResolvedValue({ items: [] });
  const activity = vi.fn<(activity: LiveActivity) => void>();
  show(activity);
  await waitFor(() => expect(poll).toHaveBeenCalledOnce());
  expect(activity).toHaveBeenLastCalledWith(
    expect.objectContaining({ state: "working", label: "正在读取计算进度" }),
  );
  poll.mockResolvedValue(result(liveComputeTask("succeeded")));
  await waitFor(
    () =>
      expect(activity).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: "complete" }),
      ),
    { timeout: 5000 },
  );
  expect(poll).toHaveBeenCalledTimes(2);
});

it("ignores an in-flight response after unmount", async () => {
  let resolve!: (value: { items: AgentComputeTaskTracking[] }) => void;
  vi.spyOn(agentApi, "computeTasks").mockImplementation(
    () => new Promise((done) => (resolve = done)),
  );
  const activity = vi.fn<(activity: LiveActivity) => void>();
  const { unmount } = show(activity);
  expect(activity).toHaveBeenCalledOnce();
  unmount();
  await act(async () => resolve(result(liveComputeTask("succeeded"))));
  expect(activity).toHaveBeenCalledOnce();
});

it("ignores the previous run response after the task card changes", async () => {
  let resolve!: (value: { items: AgentComputeTaskTracking[] }) => void;
  vi.spyOn(agentApi, "computeTasks")
    .mockImplementationOnce(() => new Promise((done) => (resolve = done)))
    .mockResolvedValue(result(liveComputeTask()));
  const activity = vi.fn<(activity: LiveActivity) => void>();
  const { rerender } = show(activity);
  rerender(
    <AntApp>
      <MemoryRouter>
        <RunComputeTasks
          runId={9}
          refreshKey="1"
          activityTaskId={liveComputeTask().id}
          onActivityChange={activity}
        />
        <Location />
      </MemoryRouter>
    </AntApp>,
  );
  await screen.findByText("排队中");
  const calls = activity.mock.calls.length;
  await act(async () => resolve(result(liveComputeTask("succeeded"))));
  expect(activity).toHaveBeenCalledTimes(calls);
  expect(activity).toHaveBeenLastCalledWith(
    expect.objectContaining({ state: "working" }),
  );
});

it("groups real output files below collapsed completed calculations and previews the actual CSV", async () => {
  const task = liveComputeTask("succeeded");
  const output = {
    ...task.outputs[0]!,
    kind: "table",
    label: "分区统计表",
    fileName: "zone_statistics.csv",
    downloadUrl: "/api/compute/outputs/30/download/",
    metadata: { rows: 2 },
  };
  const load = vi
    .spyOn(agentApi, "computeTasks")
    .mockResolvedValue(result({ ...task, outputs: [output] }));
  const preview = vi.spyOn(computeApi, "preview").mockResolvedValue({
    kind: "table",
    metadata: { rows: 2 },
    columns: ["分区", "平均变化"],
    rows: [
      ["东区", -0.18],
      ["西区", -0.03],
    ],
  });
  render(
    <AntApp>
      <MemoryRouter>
        <RunComputeTasks runId={8} refreshKey="files" compact />
      </MemoryRouter>
    </AntApp>,
  );
  await screen.findByText("zone_statistics.csv");
  expect(screen.getByText("计算完成，结果已保存。")).not.toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "在线预览" }));
  await screen.findByText("东区");
  await waitFor(() => expect(screen.getByText("-0.18")).toBeVisible());
  expect(preview).toHaveBeenCalledWith(output.id);
  expect(load).toHaveBeenCalledOnce();
});

it("downloads a generated CSV with its real filename through the authenticated output link", async () => {
  const task = liveComputeTask("succeeded");
  task.outputs = [
    {
      ...task.outputs[0]!,
      kind: "table",
      fileName: "statistics.csv",
      downloadUrl: "/api/compute/outputs/30/download/",
    },
  ];
  vi.spyOn(agentApi, "computeTasks").mockResolvedValue(result(task));
  const fetchFile = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response("zone,mean\neast,-0.18", {
      headers: { "content-type": "text/csv" },
    }),
  );
  let filename = "";
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
    function (this: HTMLAnchorElement) {
      filename = this.download;
    },
  );
  show();
  fireEvent.click(await screen.findByRole("button", { name: "下载" }));
  await waitFor(() => expect(filename).toBe("statistics.csv"));
  expect(fetchFile).toHaveBeenCalledWith(
    "/api/compute/outputs/30/download/",
    expect.objectContaining({
      credentials: "include",
      headers: expect.objectContaining({ "X-Project-Id": expect.any(String) }),
    }),
  );
});

it("keeps final deliverables first and distinguishes earlier and later index files inside the folded intermediate list", async () => {
  const early = { ...liveComputeTask("succeeded"), id: "early-task" };
  const late = {
    ...liveComputeTask("succeeded"),
    id: "late-task",
    outputs: [{ ...early.outputs[0]!, id: 31 }],
  };
  const final = {
    ...liveComputeTask("succeeded"),
    id: "final-task",
    outputs: [
      {
        ...early.outputs[0]!,
        id: 32,
        kind: "table",
        label: "调查排序表",
        fileName: "priorities.csv",
      },
    ],
  };
  vi.spyOn(agentApi, "computeTasks").mockResolvedValue({
    items: [early, late, final].map((task) => result(task).items[0]!),
  });
  render(
    <AntApp>
      <MemoryRouter>
        <RunComputeTasks
          runId={8}
          refreshKey="roles"
          compact
          primaryTaskIds={[final.id]}
          taskDisplayNames={{
            [early.id]: "前期植被指数",
            [late.id]: "后期植被指数",
            [final.id]: "调查顺序分析",
          }}
        />
      </MemoryRouter>
    </AntApp>,
  );
  await screen.findByText("priorities.csv");
  expect(screen.queryByText("ndvi.tif")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("中间过程文件 / 2 个"));
  expect(
    await screen.findByText("前期植被指数", { selector: ".agent-file-source" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("后期植被指数", { selector: ".agent-file-source" }),
  ).toBeInTheDocument();
  expect(screen.getAllByText("ndvi.tif")).toHaveLength(2);
});
