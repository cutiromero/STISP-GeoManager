import { App } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProjectManagementPage from "./ProjectManagementPage";

const mocks = vi.hoisted(() => ({
  users: vi.fn(),
  assignment: vi.fn(),
  assign: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({
    canAssign: true,
    canManage: false,
    refresh: mocks.refresh,
    assignableProjects: [
      { id: 1, name: "公开", code: "default", isDefault: true, isActive: true },
      {
        id: 2,
        name: "逻辑推理",
        code: "logic",
        isDefault: false,
        isActive: true,
      },
    ],
  }),
}));
vi.mock("../api/client", () => ({ api: { adminUsers: mocks.users } }));
vi.mock("../api/platform", () => ({
  platformApi: { assignment: mocks.assignment, assign: mocks.assign },
}));

beforeEach(() => {
  mocks.users.mockResolvedValue({
    items: [{ id: 42, username: "科研测试用户" }],
  });
  mocks.assignment.mockResolvedValue({
    userId: 42,
    projectIds: [2],
    allowPublicProject: false,
  });
  mocks.assign.mockResolvedValue({
    userId: 42,
    projectIds: [2],
    allowPublicProject: true,
  });
  mocks.refresh.mockResolvedValue(undefined);
});

describe("per-user public project access", () => {
  it("loads and saves the explicit public access policy with project assignment", async () => {
    render(
      <App>
        <ProjectManagementPage />
      </App>,
    );
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: "分配项目的用户" }),
    );
    fireEvent.click(
      await screen.findByText("科研测试用户", {
        selector: ".ant-select-item-option-content",
      }),
    );
    const toggle = await screen.findByRole("switch", {
      name: "允许访问公开项目",
    });
    await waitFor(() => expect(toggle).not.toBeChecked());
    expect(mocks.assignment).toHaveBeenCalledWith(42);
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("button", { name: "保存分配" }));
    await waitFor(() =>
      expect(mocks.assign).toHaveBeenCalledWith(42, [2], true),
    );
    expect(mocks.refresh).toHaveBeenCalled();
  });
});
