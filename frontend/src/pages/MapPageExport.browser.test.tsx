import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ExportOptions } from "../hooks/LayerContext";
import type { ExportLayerItem } from "../types";

const mockApi = vi.hoisted(() => ({
  exportLayersAsync: vi.fn(),
  rasterJob: vi.fn(),
  downloadExport: vi.fn(),
}));

const mockDownloadBlob = vi.hoisted(() => vi.fn());

vi.mock("../api/platform", () => ({
  platformApi: {
    projects: vi
      .fn()
      .mockResolvedValue({ items: [], canManage: false, canAssign: false }),
  },
}));

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  api: mockApi,
}));
vi.mock("../utils/download", () => ({ downloadBlob: mockDownloadBlob }));

import { useLayerExport } from "./MapPage";

const exportItem: ExportLayerItem = {
  layerType: "vector",
  name: "胡杨样地测试图层",
  resourceId: 1,
};

const exportOptions: ExportOptions = {
  epsg: 4326,
  reproject: false,
  clip: false,
  clipGeometry: null,
  format: "geojson",
};

const queuedJob = {
  id: "export-job-1",
  kind: "export",
  status: "running",
  progressPercent: 10,
  messages: ["导出任务已创建"],
  result: null,
  error: "",
  startedAt: 1,
  finishedAt: null,
};

const runningJob = {
  ...queuedJob,
  progressPercent: 40,
  messages: ["正在生成导出文件"],
};

const readyJob = {
  ...queuedJob,
  status: "ready",
  progressPercent: 100,
  messages: ["导出文件已生成"],
  finishedAt: 2,
};

const messageApi = {
  warning: vi.fn(),
  error: vi.fn(),
  success: vi.fn(),
};
const onProgress = vi.fn();
let latestExportPromise: Promise<void> | null = null;

function ExportHarness() {
  const exportLayers = useLayerExport({
    canExportData: true,
    permissionDeniedMessage: "当前角色无权限",
    message: messageApi,
  });

  return (
    <button
      type="button"
      onClick={() => {
        const promise = exportLayers([exportItem], exportOptions, onProgress);
        latestExportPromise = promise;
        void promise.catch(() => undefined);
      }}
    >
      开始测试导出
    </button>
  );
}

async function flushExportCreation() {
  fireEvent.click(screen.getByRole("button", { name: "开始测试导出" }));
  await act(async () => {
    await Promise.resolve();
  });
  expect(mockApi.exportLayersAsync).toHaveBeenCalledOnce();
  expect(latestExportPromise).not.toBeNull();
}

describe("MapPage asynchronous layer export polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-30T12:00:00+08:00"));
    for (const fn of Object.values(mockApi)) {
      fn.mockReset();
    }
    mockDownloadBlob.mockReset();
    messageApi.warning.mockReset();
    messageApi.error.mockReset();
    messageApi.success.mockReset();
    onProgress.mockReset();
    latestExportPromise = null;
    mockApi.exportLayersAsync.mockResolvedValue(queuedJob);
    mockApi.rasterJob.mockResolvedValue(runningJob);
    mockApi.downloadExport.mockResolvedValue({
      blob: new Blob(["export"]),
      filename: "layers.geojson",
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("stops a permanently running job at the maximum wait time", async () => {
    render(<ExportHarness />);
    await flushExportCreation();
    const promise = latestExportPromise!;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });

    await expect(promise).rejects.toThrow(
      "导出任务等待超时，请稍后重试或在任务中心查看状态",
    );
    expect(messageApi.error).toHaveBeenCalledWith(
      "导出任务等待超时，请稍后重试或在任务中心查看状态",
    );
    expect(mockApi.rasterJob.mock.calls.length).toBeGreaterThan(1);
    expect(mockApi.rasterJob.mock.calls.length).toBeLessThan(40);
    expect(mockApi.downloadExport).not.toHaveBeenCalled();

    const callsAtTimeout = mockApi.rasterJob.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(mockApi.rasterJob).toHaveBeenCalledTimes(callsAtTimeout);
  });

  it("backs off instead of polling every 900 milliseconds forever", async () => {
    render(<ExportHarness />);
    await flushExportCreation();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(899);
    });
    expect(mockApi.rasterJob).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(mockApi.rasterJob).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1349);
    });
    expect(mockApi.rasterJob).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(mockApi.rasterJob).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2024);
    });
    expect(mockApi.rasterJob).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(mockApi.rasterJob).toHaveBeenCalledTimes(3);
  });

  it("cancels a deferred poll when the page unmounts", async () => {
    let resolvePoll!: (job: typeof readyJob) => void;
    mockApi.rasterJob.mockReturnValue(
      new Promise<typeof readyJob>((resolve) => {
        resolvePoll = resolve;
      }),
    );
    const { unmount } = render(<ExportHarness />);
    await flushExportCreation();
    const promise = latestExportPromise!;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
    });
    expect(mockApi.rasterJob).toHaveBeenCalledOnce();

    unmount();
    resolvePoll(readyJob);
    await act(async () => {
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(10_000);
    });

    await expect(promise).resolves.toBeUndefined();
    expect(mockApi.rasterJob).toHaveBeenCalledOnce();
    expect(mockApi.downloadExport).not.toHaveBeenCalled();
    expect(mockDownloadBlob).not.toHaveBeenCalled();
    expect(messageApi.error).not.toHaveBeenCalled();
    expect(messageApi.success).not.toHaveBeenCalled();
    expect(onProgress).toHaveBeenCalledTimes(1);
  });

  it("downloads exactly once when the job becomes ready", async () => {
    mockApi.rasterJob.mockResolvedValue(readyJob);
    render(<ExportHarness />);
    await flushExportCreation();
    const promise = latestExportPromise!;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
      await promise;
    });

    expect(mockApi.rasterJob).toHaveBeenCalledOnce();
    expect(mockApi.downloadExport).toHaveBeenCalledOnce();
    expect(mockApi.downloadExport).toHaveBeenCalledWith("export-job-1");
    expect(mockDownloadBlob).toHaveBeenCalledOnce();
    expect(messageApi.success).toHaveBeenCalledWith("导出任务已完成");
    expect(messageApi.error).not.toHaveBeenCalled();
  });
});
