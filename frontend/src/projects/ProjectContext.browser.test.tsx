import { App as AntApp } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ProjectProvider,
  ProjectSelector,
  useProjectContext,
} from "./ProjectContext";
import { getActiveProject, resetProjectSession } from "./session";

const mocks = vi.hoisted(() => ({ user: { id: 42 }, projects: vi.fn() }));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: mocks.user }),
}));
vi.mock("../api/platform", () => ({
  platformApi: { projects: mocks.projects },
}));

function CurrentProject() {
  const context = useProjectContext();
  return <output aria-label="实际项目范围">{context?.current}</output>;
}
function show() {
  return render(
    <AntApp>
      <ProjectProvider>
        <ProjectSelector />
        <CurrentProject />
      </ProjectProvider>
    </AntApp>,
  );
}
beforeEach(() => {
  resetProjectSession();
  sessionStorage.removeItem("project:42");
  mocks.projects.mockResolvedValue({
    items: [
      { id: 1, name: "公开", isActive: true, isDefault: true },
      { id: 2, name: "项目甲", isActive: true, isDefault: false },
    ],
    canManage: false,
    canAssign: false,
  });
});

describe("single-project navigation", () => {
  it("restores a legacy aggregate session to Public and only offers individual projects", async () => {
    sessionStorage.setItem("project:42", "all");
    show();
    await screen.findByText("公开");
    expect(getActiveProject()).toBe("1");
    expect(sessionStorage.getItem("project:42")).toBe("1");
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "当前项目标签" }));
    await screen.findByText("项目甲", {
      selector: ".ant-select-item-option-content",
    });
    expect(screen.queryByText("全部可访问")).not.toBeInTheDocument();
    expect(
      document.querySelectorAll(".ant-select-item-option-content"),
    ).toHaveLength(2);
  });

  it("switches and persists exactly one authorized project after confirmation", async () => {
    show();
    await screen.findByText("公开");
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "当前项目标签" }));
    fireEvent.click(
      await screen.findByText("项目甲", {
        selector: ".ant-select-item-option-content",
      }),
    );
    expect(getActiveProject()).toBe("1");
    fireEvent.click(await screen.findByRole("button", { name: "切换项目" }));
    await waitFor(() =>
      expect(screen.getByLabelText("实际项目范围")).toHaveTextContent("2"),
    );
    expect(getActiveProject()).toBe("2");
    expect(sessionStorage.getItem("project:42")).toBe("2");
  });

  it("returns a revoked stored project to Public", async () => {
    sessionStorage.setItem("project:42", "999");
    show();
    await waitFor(() =>
      expect(screen.getByLabelText("实际项目范围")).toHaveTextContent("1"),
    );
    expect(sessionStorage.getItem("project:42")).toBe("1");
    expect(getActiveProject()).toBe("1");
  });
});
