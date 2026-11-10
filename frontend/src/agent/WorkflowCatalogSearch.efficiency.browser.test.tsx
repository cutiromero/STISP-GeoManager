import { Profiler, type ProfilerOnRenderCallback } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { agentApi } from "../api/agent";
import type { AgentWorkflowCatalogPage } from "../api/generated/types.gen";
import GenericWorkflowUploads from "./GenericWorkflowUploads";

const page = (query = "", current = 1): AgentWorkflowCatalogPage => ({
  items: Array.from({ length: 20 }, (_, index) => ({
    id: (current - 1) * 20 + index + 1,
    name: `${query || "区域"}资料 ${(current - 1) * 20 + index + 1}`,
    dataType: "table",
    description: "区域地质观测",
    directoryId: null,
    directoryName: "",
    createdAt: "2026-11-10T12:00:00Z",
    updatedAt: "2026-11-10T12:00:00Z",
  })),
  total: 40,
  page: current,
  pageSize: 20,
  directories: [],
});

function show(
  onRender: ProfilerOnRenderCallback = vi.fn(),
  presentation: "default" | "business-flow" = "business-flow",
) {
  return render(
    <ConfigProvider locale={zhCN}>
      <App>
        <Profiler id="catalog" onRender={onRender}>
          <GenericWorkflowUploads
            batchId="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            model="mock"
            inputs={{}}
            onInputsChange={vi.fn()}
            presentation={presentation}
          />
        </Profiler>
      </App>
    </ConfigProvider>,
  );
}

beforeEach(() => {
  vi.spyOn(agentApi, "workflowUploads").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "workflowCatalogResources").mockImplementation(
    async (query, _options, current) => page(query, current),
  );
});
afterEach(() => vi.restoreAllMocks());

it("uses the same IME and visible-description behavior in the default picker", async () => {
  vi.mocked(agentApi.workflowCatalogResources).mockImplementation(
    async (query) => ({
      ...page(),
      items: query
        ? [
            {
              ...page().items[0]!,
              id: 99,
              name: "地质图",
              description: "…有233个采样点…",
            },
          ]
        : page().items,
    }),
  );
  show(vi.fn(), "default");
  fireEvent.click(screen.getByRole("button", { name: "选择系统数据" }));
  await waitFor(() =>
    expect(agentApi.workflowCatalogResources).toHaveBeenCalledOnce(),
  );
  const input = screen.getByRole("combobox", { name: "选择系统数据资源" });
  fireEvent.mouseDown(input);
  fireEvent.compositionStart(input);
  fireEvent.change(input, { target: { value: "23" } });
  await act(async () => new Promise((resolve) => setTimeout(resolve, 400)));
  expect(agentApi.workflowCatalogResources).toHaveBeenCalledOnce();
  fireEvent.change(input, { target: { value: "233" } });
  fireEvent.compositionEnd(input, { data: "233" });
  expect(await screen.findByText("233", { selector: "mark" })).toBeVisible();
  expect(screen.getByText(/说明：/)).toHaveTextContent("…有233个采样点…");
  expect(agentApi.workflowCatalogResources).toHaveBeenCalledTimes(2);
});

it("measures a rapid search burst and bounded result rendering without detail reads", async () => {
  const commits: number[] = [];
  show((_id: string, _phase: string, duration: number) =>
    commits.push(duration),
  );
  fireEvent.click(screen.getByRole("button", { name: "选择系统数据" }));
  await screen.findByRole("checkbox", { name: "选择区域资料 1" });
  commits.length = 0;
  const started = performance.now();
  const input = screen.getByRole("searchbox", { name: "搜索任务资料" });
  for (const value of ["2", "23", "233"]) {
    fireEvent.change(input, { target: { value } });
    await act(async () => new Promise((resolve) => setTimeout(resolve, 40)));
  }
  await screen.findByRole("checkbox", { name: "选择233资料 1" });
  expect(agentApi.workflowCatalogResources).toHaveBeenCalledTimes(2);
  expect(agentApi.workflowUploads).toHaveBeenCalledOnce();
  console.log(
    "CATALOG_FRONTEND_MEASUREMENTS=" +
      JSON.stringify({
        burstToResultMs: performance.now() - started,
        requestsIncludingOpen: vi.mocked(agentApi.workflowCatalogResources).mock
          .calls.length,
        commits: commits.length,
        renderTotalMs: commits.reduce((total, duration) => total + duration, 0),
        renderMaxMs: Math.max(...commits),
      }),
  );
});

it("does not search during IME composition, even after the debounce interval", async () => {
  show();
  fireEvent.click(screen.getByRole("button", { name: "选择系统数据" }));
  await screen.findByRole("checkbox", { name: "选择区域资料 1" });
  const input = screen.getByRole("searchbox", { name: "搜索任务资料" });
  fireEvent.compositionStart(input);
  fireEvent.change(input, { target: { value: "di" } });
  await act(async () => new Promise((resolve) => setTimeout(resolve, 400)));
  expect(agentApi.workflowCatalogResources).toHaveBeenCalledOnce();
  fireEvent.change(input, { target: { value: "地质" } });
  fireEvent.compositionEnd(input, { data: "地质" });
  await screen.findByRole("checkbox", { name: "选择地质资料 1" });
  expect(agentApi.workflowCatalogResources).toHaveBeenCalledTimes(2);
  expect(vi.mocked(agentApi.workflowCatalogResources).mock.calls[1]?.[0]).toBe(
    "地质",
  );
});

it("aborts old searches, ignores late responses and aborts on close", async () => {
  let resolveOld!: (result: AgentWorkflowCatalogPage) => void;
  vi.mocked(agentApi.workflowCatalogResources).mockImplementation(
    async (query) =>
      query === "旧"
        ? new Promise((resolve) => {
            resolveOld = resolve;
          })
        : page(query),
  );
  show();
  fireEvent.click(screen.getByRole("button", { name: "选择系统数据" }));
  await screen.findByRole("checkbox", { name: "选择区域资料 1" });
  const input = screen.getByRole("searchbox", { name: "搜索任务资料" });
  fireEvent.change(input, { target: { value: "旧" } });
  await waitFor(() =>
    expect(agentApi.workflowCatalogResources).toHaveBeenCalledTimes(2),
  );
  const oldSignal = vi.mocked(agentApi.workflowCatalogResources).mock
    .calls[1]?.[1]?.signal;
  fireEvent.change(input, { target: { value: "新" } });
  await screen.findByRole("checkbox", { name: "选择新资料 1" });
  expect(oldSignal?.aborted).toBe(true);
  await act(async () => resolveOld(page("旧")));
  expect(
    screen.queryByRole("checkbox", { name: "选择旧资料 1" }),
  ).not.toBeInTheDocument();
  const signal = vi.mocked(agentApi.workflowCatalogResources).mock.calls[2]?.[1]
    ?.signal;
  const dialog = screen.getByRole("dialog", { name: "选择系统数据" });
  fireEvent.click(within(dialog).getByRole("button", { name: /^取\s*消$/ }));
  await waitFor(() => expect(signal?.aborted).toBe(true));
});

it("shows highlighted description evidence, an explicit empty state and retained page selections", async () => {
  const add = vi
    .spyOn(agentApi, "addWorkflowCatalogReferences")
    .mockResolvedValue({ items: [] });
  vi.mocked(agentApi.workflowCatalogResources).mockImplementation(
    async (query, _options, current) => {
      if (query === "无结果") return { ...page(), items: [], total: 0 };
      const result = page(query, current);
      if (query === "233")
        result.items[0] = {
          ...result.items[0]!,
          name: "地质图",
          description: "…有233个采样点…",
        };
      return result;
    },
  );
  show();
  fireEvent.click(screen.getByRole("button", { name: "选择系统数据" }));
  fireEvent.click(
    await screen.findByRole("checkbox", { name: "选择区域资料 1" }),
  );
  fireEvent.click(screen.getByTitle("2"));
  await waitFor(() =>
    expect(agentApi.workflowCatalogResources).toHaveBeenCalledTimes(2),
  );
  await waitFor(() =>
    expect(
      vi.mocked(agentApi.workflowCatalogResources).mock.calls[1]?.[2],
    ).toBe(2),
  );
  fireEvent.click(
    await screen.findByRole("checkbox", { name: "选择区域资料 22" }),
  );
  const input = screen.getByRole("searchbox", { name: "搜索任务资料" });
  fireEvent.change(input, { target: { value: "233" } });
  await screen.findByRole("checkbox", { name: "选择地质图" });
  expect(screen.getAllByText("233", { selector: "mark" })).toHaveLength(20);
  expect(screen.getByRole("checkbox", { name: "选择地质图" })).toBeChecked();
  fireEvent.change(input, { target: { value: "无结果" } });
  await screen.findByText("没有匹配的资料，请调整关键词或数据目录");
  fireEvent.click(screen.getByRole("button", { name: "加入本次任务" }));
  await waitFor(() => expect(add).toHaveBeenCalledOnce());
  expect(add.mock.calls[0]?.[1]).toEqual([1, 22]);
});
