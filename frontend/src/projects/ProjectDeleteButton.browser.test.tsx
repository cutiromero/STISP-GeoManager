import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, expect, it, vi } from "vitest";
import ProjectDeleteButton from "./ProjectDeleteButton";

const api = vi.hoisted(() => ({ previewProjectDeletion: vi.fn(), deleteProject: vi.fn() }));
vi.mock("../api/platform", () => ({ platformApi: api }));
const project = { id: 13, name: "测试项目", code: "test", description: "", isDefault: false, isActive: true, sortOrder: 1 };
const onDeleted = vi.fn();
beforeEach(() => {
  vi.clearAllMocks();
  api.previewProjectDeletion.mockResolvedValue({ projectId: 13, name: "测试项目", resourceCount: 2, recordCount: 8, sharedResourceCount: 1, sharedFileCount: 1, estimatedBytes: 2048, confirmationToken: "confirmed-scope" });
  api.deleteProject.mockResolvedValue({ detail: "项目及独占数据已删除，共享数据已保留" });
});
function show(disabled = false) {
  return render(<App><ProjectDeleteButton project={project} disabled={disabled} onDeleted={onDeleted} /></App>);
}
it("requires the full project name and explicit data confirmation before deletion", async () => {
  show();
  fireEvent.click(screen.getByRole("button", { name: /删除$/ }));
  await screen.findByText(/保留 1 项通用资料/);
  const confirm = screen.getByRole("button", { name: "删除项目及独占数据" });
  expect(confirm).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox", { name: "输入完整项目名称" }), { target: { value: project.name } });
  expect(confirm).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(confirm);
  await waitFor(() => expect(api.deleteProject).toHaveBeenCalledWith(13, { confirmedName: project.name, deleteExclusiveData: true, confirmationToken: "confirmed-scope" }));
  expect(onDeleted).toHaveBeenCalledOnce();
});
it("does not enable confirmation when active tasks prevent preview", async () => {
  api.previewProjectDeletion.mockRejectedValue(new Error("项目仍有运行中任务"));
  show();
  fireEvent.click(screen.getByRole("button", { name: /删除$/ }));
  await screen.findByText(/项目仍有运行中任务/);
  expect(screen.getByRole("button", { name: "删除项目及独占数据" })).toBeDisabled();
  expect(api.deleteProject).not.toHaveBeenCalled();
});
it("keeps deletion disabled for a non-admin", () => {
  show(true);
  expect(screen.getByRole("button", { name: /删除$/ })).toBeDisabled();
});
