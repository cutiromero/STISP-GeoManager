import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { businessFlowsApi } from "../api/businessFlows";
import type {
  BusinessFlowDetail,
  BusinessFlowList,
} from "../api/generated/types.gen";
import BusinessFlowsPage from "./BusinessFlowsPage";
import {
  researchDetail,
  researchFlow,
  researchVersion,
  summary,
} from "./businessFlow.testFixtures";

const session = vi.hoisted(() => ({ project: "3" }));
vi.mock("../components/WorkspaceHeader", () => ({
  default: () => <header>STISP</header>,
}));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({
    user: { id: 99, permissions: { canBrowseData: true } },
  }),
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({
    current: session.project,
    projects: [{ id: Number(session.project), name: "当前项目" }],
  }),
}));
vi.mock("../agent/useAgentBootstrap", () => ({
  useAgentBootstrapState: () => ({
    bootstrap: { canAgent: true },
    status: "ready",
    error: "",
    retry: vi.fn(),
  }),
}));

const detail = (id: number, project = 3): BusinessFlowDetail => {
  const flow = {
    ...researchFlow,
    id,
    projectId: project,
    name: `流程${String(id).padStart(2, "0")}`,
    code: `flow-${id}`,
    description: `资料${id}`,
    currentVersionId: 1000 + id,
  };
  const version = { ...researchVersion, id: 1000 + id, flowId: id };
  return { ...researchDetail, flow, version, versions: [version] };
};
const row = (id: number, project = 3) => {
  const value = detail(id, project);
  return summary(value.flow, value.version!);
};
const rows = Array.from({ length: 51 }, (_, index) => row(index + 1));
function deferred<T>() {
  let resolve!: (value: T) => void;
  return {
    promise: new Promise<T>((accept) => {
      resolve = accept;
    }),
    resolve: (value: T) => resolve(value),
  };
}
function Shell() {
  return (
    <App>
      <MemoryRouter>
        <BusinessFlowsPage />
      </MemoryRouter>
    </App>
  );
}
beforeEach(() => {
  session.project = "3";
  vi.spyOn(businessFlowsApi, "list").mockImplementation(
    async (options = {}) => {
      const q = (options.q ?? "").toLowerCase(),
        offset = options.offset ?? 0,
        limit = options.limit ?? 50;
      const values = rows.filter((item) =>
        `${item.name} ${item.description} ${item.code}`
          .toLowerCase()
          .includes(q),
      );
      return {
        items: values.slice(offset, offset + limit),
        canManage: false,
        ...(offset + limit < values.length
          ? { nextOffset: offset + limit }
          : {}),
      };
    },
  );
  vi.spyOn(businessFlowsApi, "detail").mockImplementation(async (id) =>
    detail(id, Number(session.project)),
  );
});
afterEach(() => vi.restoreAllMocks());

it("loads the 51st flow and deduplicates appended metadata without rereading selected detail", async () => {
  const original = vi.mocked(businessFlowsApi.list).getMockImplementation()!;
  vi.mocked(businessFlowsApi.list).mockImplementation(async (options = {}) =>
    options.offset === 50
      ? { items: [row(50), row(51)], canManage: false }
      : original(options),
  );
  render(<Shell />);
  await screen.findByRole("heading", { name: "流程01" });
  const catalog = screen.getByRole("complementary", { name: "业务流目录" });
  expect(
    within(catalog).queryByRole("button", { name: /流程51/ }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "加载更多业务流" }));
  expect(
    await within(catalog).findByRole("button", { name: /流程51/ }),
  ).toBeVisible();
  expect(
    within(catalog).getAllByRole("button", { name: /流程50/ }),
  ).toHaveLength(1);
  expect(businessFlowsApi.list).toHaveBeenCalledTimes(2);
  expect(businessFlowsApi.detail).toHaveBeenCalledOnce();
  fireEvent.click(within(catalog).getByRole("button", { name: /流程51/ }));
  await screen.findByRole("heading", { name: "流程51" });
  expect(businessFlowsApi.detail).toHaveBeenCalledTimes(2);
});

it("debounces remote code search beyond the first page and leaves current detail mounted", async () => {
  render(<Shell />);
  await screen.findByRole("heading", { name: "流程01" });
  const input = screen.getByRole("textbox", { name: "搜索业务流" });
  fireEvent.change(input, { target: { value: "flo" } });
  fireEvent.change(input, { target: { value: "flow-51" } });
  const catalog = screen.getByRole("complementary", { name: "业务流目录" });
  expect(
    await within(catalog).findByRole("button", { name: /流程51/ }),
  ).toBeVisible();
  await waitFor(() => expect(businessFlowsApi.list).toHaveBeenCalledTimes(2));
  expect(vi.mocked(businessFlowsApi.list).mock.calls[1]?.[0]?.q).toBe(
    "flow-51",
  );
  expect(screen.getByRole("heading", { name: "流程01" })).toBeVisible();
  fireEvent.change(input, { target: { value: " flow-51 " } });
  fireEvent.click(screen.getByRole("button", { name: /交付摘要，/ }));
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 360));
  });
  expect(businessFlowsApi.list).toHaveBeenCalledTimes(2);
  expect(businessFlowsApi.detail).toHaveBeenCalledOnce();
});

it("aborts old searches and ignores responses that arrive after the next query", async () => {
  const old = deferred<BusinessFlowList>(),
    next = deferred<BusinessFlowList>();
  const original = vi.mocked(businessFlowsApi.list).getMockImplementation()!;
  vi.mocked(businessFlowsApi.list).mockImplementation((options) =>
    options?.q === "old"
      ? old.promise
      : options?.q === "new"
        ? next.promise
        : original(options),
  );
  render(<Shell />);
  await screen.findByRole("heading", { name: "流程01" });
  const input = screen.getByRole("textbox", { name: "搜索业务流" });
  fireEvent.change(input, { target: { value: "old" } });
  await waitFor(() => expect(businessFlowsApi.list).toHaveBeenCalledTimes(2));
  const signal = vi.mocked(businessFlowsApi.list).mock.calls[1]?.[0]?.signal;
  fireEvent.change(input, { target: { value: "new" } });
  await waitFor(() => expect(businessFlowsApi.list).toHaveBeenCalledTimes(3));
  expect(signal?.aborted).toBe(true);
  await act(async () =>
    next.resolve({
      items: [{ ...row(51), code: "new-target" }],
      canManage: false,
    }),
  );
  await act(async () =>
    old.resolve({
      items: [{ ...row(2), code: "old-target" }],
      canManage: false,
    }),
  );
  const catalog = screen.getByRole("complementary", { name: "业务流目录" });
  expect(within(catalog).getByRole("button", { name: /流程51/ })).toBeVisible();
  expect(
    within(catalog).queryByRole("button", { name: /流程02/ }),
  ).not.toBeInTheDocument();
  expect(businessFlowsApi.detail).toHaveBeenCalledOnce();
});

it("clears project state and cancels the previous selection detail on a project change", async () => {
  const old = deferred<BusinessFlowDetail>();
  vi.mocked(businessFlowsApi.detail).mockImplementation(async (id) =>
    id === 1 ? old.promise : detail(id, 4),
  );
  vi.mocked(businessFlowsApi.list).mockImplementation(async () =>
    session.project === "3"
      ? { items: [row(1)], canManage: false }
      : { items: [row(66, 4)], canManage: false },
  );
  const view = render(<Shell />);
  await waitFor(() => expect(businessFlowsApi.detail).toHaveBeenCalledOnce());
  const signal = vi.mocked(businessFlowsApi.detail).mock.calls[0]?.[1]?.signal;
  session.project = "4";
  view.rerender(<Shell />);
  await screen.findByRole("heading", { name: "流程66" });
  expect(signal?.aborted).toBe(true);
  await act(async () => old.resolve(detail(1)));
  expect(screen.getByRole("heading", { name: "流程66" })).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /流程01/ }),
  ).not.toBeInTheDocument();
});

it("does not append an old load-more page after changing the search", async () => {
  const more = deferred<BusinessFlowList>();
  const original = vi.mocked(businessFlowsApi.list).getMockImplementation()!;
  vi.mocked(businessFlowsApi.list).mockImplementation((options) =>
    options?.offset === 50 ? more.promise : original(options),
  );
  render(<Shell />);
  await screen.findByRole("heading", { name: "流程01" });
  fireEvent.click(screen.getByRole("button", { name: "加载更多业务流" }));
  await waitFor(() => expect(businessFlowsApi.list).toHaveBeenCalledTimes(2));
  const signal = vi.mocked(businessFlowsApi.list).mock.calls[1]?.[0]?.signal;
  fireEvent.change(screen.getByRole("textbox", { name: "搜索业务流" }), {
    target: { value: "flow-51" },
  });
  await waitFor(() => expect(businessFlowsApi.list).toHaveBeenCalledTimes(3));
  expect(signal?.aborted).toBe(true);
  await act(async () => more.resolve({ items: [row(2)], canManage: false }));
  const catalog = screen.getByRole("complementary", { name: "业务流目录" });
  expect(
    await within(catalog).findByRole("button", { name: /流程51/ }),
  ).toBeVisible();
  expect(
    within(catalog).queryByRole("button", { name: /流程02/ }),
  ).not.toBeInTheDocument();
  expect(businessFlowsApi.detail).toHaveBeenCalledOnce();
});
