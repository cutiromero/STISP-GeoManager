import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, expect, it, vi } from "vitest";
import { userEvent } from "vitest/browser";
import { AdminSystemLogsPanel } from "./AdminOperationLogsPage";

const mocks = vi.hoisted(() => ({ load: vi.fn() }));
vi.mock("../api/client", () => ({ api: { adminSystemLogs: mocks.load } }));

function log(content: string, lines = 500) {
  return {
    files: [{ name: "application.log", sizeBytes: 2048 }],
    selectedFile: "application.log",
    lines,
    content,
    generatedAt: "2026-11-17T12:00:00+08:00",
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

beforeEach(() => {
  mocks.load.mockReset();
});

it("loads the default file once and keeps a later selection when an older refresh arrives", async () => {
  mocks.load.mockResolvedValueOnce(log("初始日志"));
  render(
    <AntApp>
      <AdminSystemLogsPanel />
    </AntApp>,
  );
  expect(await screen.findByText("初始日志")).toBeInTheDocument();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: /刷新|Refresh/ }),
    ).not.toHaveClass("ant-btn-loading"),
  );
  expect(mocks.load).toHaveBeenCalledTimes(1);
  const old = deferred<ReturnType<typeof log>>();
  mocks.load.mockReturnValueOnce(old.promise);
  await userEvent.click(screen.getByRole("button", { name: /刷新|Refresh/ }));
  await waitFor(() => expect(mocks.load).toHaveBeenCalledTimes(2));
  mocks.load.mockResolvedValueOnce(log("最近200行", 200));
  fireEvent.mouseDown(screen.getAllByRole("combobox")[1]);
  await userEvent.click(await screen.findByText(/200 行|200 lines/));
  await waitFor(() => expect(mocks.load).toHaveBeenCalledTimes(3));
  expect(await screen.findByText("最近200行")).toBeInTheDocument();
  old.resolve(log("迟到的500行"));
  await waitFor(() =>
    expect(screen.queryByText("迟到的500行")).not.toBeInTheDocument(),
  );
  expect(screen.getByText("最近200行")).toBeInTheDocument();
  expect(mocks.load).toHaveBeenCalledTimes(3);
});

it("shows a retryable load failure instead of presenting stale logs as a successful read", async () => {
  mocks.load.mockResolvedValueOnce(log("旧日志"));
  render(
    <AntApp>
      <AdminSystemLogsPanel />
    </AntApp>,
  );
  expect(await screen.findByText("旧日志")).toBeInTheDocument();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: /刷新|Refresh/ }),
    ).not.toHaveClass("ant-btn-loading"),
  );
  mocks.load.mockRejectedValueOnce(new Error("日志读取失败，请重试"));
  await userEvent.click(screen.getByRole("button", { name: /刷新|Refresh/ }));
  await waitFor(() => expect(mocks.load).toHaveBeenCalledTimes(2));
  expect(await screen.findByText("日志读取失败，请重试")).toBeInTheDocument();
  expect(screen.queryByText("旧日志")).not.toBeInTheDocument();
  mocks.load.mockResolvedValueOnce(log("重试后的日志"));
  await userEvent.click(screen.getByRole("button", { name: /刷新|Refresh/ }));
  expect(await screen.findByText("重试后的日志")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
