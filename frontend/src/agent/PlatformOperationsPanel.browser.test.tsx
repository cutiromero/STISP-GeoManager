import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App } from "antd";
import { afterEach, expect, it, vi } from "vitest";
import PlatformOperationsPanel from "./PlatformOperationsPanel";
import { agentOperationsApi } from "../api/agentOperations";
import type { AgentOperation } from "../api/generated/types.gen";

const operation = (
  overrides: Partial<AgentOperation> = {},
): AgentOperation => ({
  id: "11111111-1111-4111-8111-111111111111",
  runId: 7,
  projectId: 3,
  kind: "publish",
  status: "pending",
  digest: "a".repeat(64),
  preview: {
    projectId: 3,
    title: "发布验收图件",
    target: "地质成果 V2",
    scope: "项目内具备查看权限的用户",
    effect: "发布指定版本，不授予原始资料权限",
    details: ["版本：2"],
  },
  result: {},
  expiresAt: new Date(Date.now() + 900000).toISOString(),
  createdAt: new Date().toISOString(),
  decidedAt: null,
  canConfirm: true,
  detail: "",
  ...overrides,
});

afterEach(() => vi.restoreAllMocks());

it("shows an unavailable state instead of asking to confirm a stopped run", async () => {
  vi.spyOn(agentOperationsApi, "list").mockResolvedValue({
    runId: 7,
    projectId: 3,
    items: [
      operation({
        canConfirm: false,
        detail: "本轮已停止，不能执行待确认操作",
      }),
    ],
  });
  const decide = vi.spyOn(agentOperationsApi, "decide");
  render(
    <App>
      <PlatformOperationsPanel projectId={3} accountId={1} runIds={[7]} />
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: /平台操作/ }));
  expect(await screen.findByText("当前不可执行")).toBeVisible();
  expect(screen.getByText("本轮已停止，不能执行待确认操作")).toBeVisible();
  expect(screen.queryByText("待您确认")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "确认执行此操作" }),
  ).not.toBeInTheDocument();
  expect(decide).not.toHaveBeenCalled();
});

it("loads on demand and confirms only the exact displayed preview", async () => {
  const item = operation();
  const list = vi
    .spyOn(agentOperationsApi, "list")
    .mockResolvedValue({ runId: 7, projectId: 3, items: [item] });
  const decide = vi.spyOn(agentOperationsApi, "decide").mockResolvedValue(
    operation({
      status: "confirmed",
      canConfirm: false,
      result: { objectId: 12, status: "published" },
    }),
  );
  const capabilities = vi
    .spyOn(agentOperationsApi, "capabilities")
    .mockResolvedValue({
      schemaVersion: 1,
      projectId: 3,
      scope: "current_user_current_project",
      items: [],
      limitations: "当前项目",
    });
  render(
    <App>
      <PlatformOperationsPanel projectId={3} accountId={1} runIds={[7]} />
    </App>,
  );
  expect(list).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /平台操作/ }));
  expect(await screen.findByText("地质成果 V2")).toBeVisible();
  expect(screen.getByText("项目内具备查看权限的用户")).toBeVisible();
  expect(decide).not.toHaveBeenCalled();
  expect(capabilities).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认执行此操作" }));
  await waitFor(() => expect(decide).toHaveBeenCalledTimes(1));
  expect(decide.mock.calls[0].slice(0, 3)).toEqual([item, "confirm", 3]);
  expect(await screen.findByText("已发布")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "确认执行此操作" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "可用能力" }));
  await waitFor(() => expect(capabilities).toHaveBeenCalledTimes(1));
});

it("does not offer confirmation for expired previews or mistake acceptance for completion", async () => {
  vi.spyOn(agentOperationsApi, "list").mockResolvedValue({
    runId: 7,
    projectId: 3,
    items: [
      operation({ expiresAt: new Date(Date.now() - 1000).toISOString() }),
    ],
  });
  const decide = vi.spyOn(agentOperationsApi, "decide");
  render(
    <App>
      <PlatformOperationsPanel projectId={3} accountId={1} runIds={[7]} />
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: /平台操作/ }));
  expect(await screen.findByText("已过期")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "确认执行此操作" }),
  ).not.toBeInTheDocument();
  expect(decide).not.toHaveBeenCalled();
});

it("clears an old account's in-flight decision and can reopen without stuck buttons", async () => {
  vi.spyOn(agentOperationsApi, "list").mockResolvedValue({
    runId: 7,
    projectId: 3,
    items: [operation()],
  });
  let resolve!: (value: AgentOperation) => void;
  vi.spyOn(agentOperationsApi, "decide").mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const view = render(
    <App>
      <PlatformOperationsPanel projectId={3} accountId={1} runIds={[7]} />
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: /平台操作/ }));
  fireEvent.click(
    await screen.findByRole("button", { name: "确认执行此操作" }),
  );
  await waitFor(() => expect(agentOperationsApi.decide).toHaveBeenCalled());
  view.rerender(
    <App>
      <PlatformOperationsPanel projectId={3} accountId={2} runIds={[7]} />
    </App>,
  );
  await act(async () =>
    resolve(operation({ status: "confirmed", canConfirm: false })),
  );
  expect(screen.queryByText("已发布")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /平台操作/ }));
  expect(
    await screen.findByRole("button", { name: "确认执行此操作" }),
  ).toBeEnabled();
});

it("shows real paged receipts and fetches the next page only on request", async () => {
  vi.spyOn(agentOperationsApi, "list").mockResolvedValue({
    runId: 7,
    projectId: 3,
    items: [],
  });
  const receipt = {
    id: "receipt-1",
    tool: "search_resources",
    contractVersion: "1.0.1",
    effect: "read",
    status: "succeeded" as const,
    requestHash: "a".repeat(64),
    argumentKeys: ["query"],
    resultRefs: {},
    error: {},
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  const calls = vi
    .spyOn(agentOperationsApi, "calls")
    .mockResolvedValueOnce({
      runId: 7,
      projectId: 3,
      total: 2,
      nextOffset: 1,
      items: [receipt],
    })
    .mockResolvedValueOnce({
      runId: 7,
      projectId: 3,
      total: 2,
      nextOffset: null,
      items: [{ ...receipt, id: "receipt-2", tool: "describe_resource" }],
    });
  render(
    <App>
      <PlatformOperationsPanel projectId={3} accountId={1} runIds={[7]} />
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: /平台操作/ }));
  fireEvent.click(await screen.findByRole("tab", { name: "调用回执" }));
  expect(await screen.findByText("search_resources")).toBeVisible();
  expect(calls).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "加载更多回执" }));
  expect(await screen.findByText("describe_resource")).toBeVisible();
  expect(calls.mock.calls[1].slice(0, 3)).toEqual([7, 3, 1]);
});
