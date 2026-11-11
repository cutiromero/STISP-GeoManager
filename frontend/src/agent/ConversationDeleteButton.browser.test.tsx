import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, expect, it, vi } from "vitest";
import ConversationDeleteButton from "./ConversationDeleteButton";

const api = vi.hoisted(() => ({ deletionPreview: vi.fn(), remove: vi.fn() }));
vi.mock("../api/agent", () => ({ agentApi: api }));
const conversation = { id: 17, projectId: 3, mode: "agent" as const, title: "待清理测试", archived: false, createdAt: "2026-11-11T04:00:00Z", updatedAt: "2026-11-11T04:00:00Z" };
const onDeleted = vi.fn();
const onError = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  api.deletionPreview.mockResolvedValue({ conversationId: 17, resourceCount: 2, outputCount: 5, retainedCount: 1, estimatedBytes: 2097152, confirmationToken: "current-scope-token" });
  api.remove.mockResolvedValue({ detail: "会话已删除" });
});

async function open() {
  render(<AntApp><ConversationDeleteButton conversation={conversation} onDeleted={onDeleted} onError={onError} /></AntApp>);
  fireEvent.click(screen.getByRole("button", { name: "删除", exact: true }));
  await screen.findByText(/可清理 2 项入库成果、5 份计算文件/);
  await waitFor(() => expect(screen.getByRole("dialog")).toBeVisible());
}

it("keeps generated data by default and deleting requires a separate confirm action", async () => {
  await open();
  expect(api.remove).not.toHaveBeenCalled();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(api.remove).toHaveBeenCalledWith(17, undefined));
  expect(onDeleted).toHaveBeenCalledOnce();
});

it("sends the preview scope only after the user opts in to data cleanup", async () => {
  api.remove.mockResolvedValue({ detail: "会话已删除", cleanup: { deletedResources: 2, deletedOutputs: 4, retainedResources: 1, retainedOutputs: 1, failedItems: 0 } });
  await open();
  expect(screen.getByText(/另有 1 项成果因引用或权限保留/)).toBeVisible();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(api.remove).toHaveBeenCalledWith(17, { deleteGeneratedData: true, confirmationToken: "current-scope-token" }));
  await screen.findByText(/清理 2 项入库成果、4 份计算文件；保留 2 项关联数据/);
});

it("allows conversation-only deletion when preview fails without enabling cleanup", async () => {
  api.deletionPreview.mockRejectedValue(new Error("offline"));
  render(<AntApp><ConversationDeleteButton conversation={conversation} onDeleted={onDeleted} onError={onError} /></AntApp>);
  fireEvent.click(screen.getByRole("button", { name: "删除", exact: true }));
  await screen.findByText(/关联数据检查失败/);
  expect(screen.getByRole("checkbox")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(api.remove).toHaveBeenCalledWith(17, undefined));
});

it("keeps the dialog open if deletion is rejected by the backend", async () => {
  api.remove.mockRejectedValue(new Error("范围已变化"));
  await open();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(onError).toHaveBeenCalledOnce());
  await waitFor(() => expect(screen.getByRole("dialog")).toBeVisible());
  expect(onDeleted).not.toHaveBeenCalled();
});
