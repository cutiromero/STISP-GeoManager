import { App as AntApp } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useNavigate } from "react-router-dom";
import {
  ProjectProvider,
  ProjectSelector,
  useProjectContext,
} from "./ProjectContext";
import { getActiveProject, resetProjectSession } from "./session";

const mocks = vi.hoisted(() => ({
  user: { id: 42 } as { id: number } | null,
  projects: vi.fn(),
}));
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
function Logout() {
  const navigate = useNavigate();
  return (
    <button
      onClick={() => {
        mocks.user = null;
        resetProjectSession();
        navigate("/login");
      }}
    >
      退出测试
    </button>
  );
}
function show(path = "/map") {
  return render(
    <AntApp>
      <MemoryRouter initialEntries={[path]}>
        <Logout />
        <ProjectProvider>
          <ProjectSelector />
          <CurrentProject />
        </ProjectProvider>
      </MemoryRouter>
    </AntApp>,
  );
}
beforeEach(() => {
  mocks.user = { id: 42 };
  mocks.projects.mockReset();
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
  it("shows login immediately without loading project authorization", () => {
    mocks.user = null;
    mocks.projects.mockRejectedValue(new Error("项目不可用"));
    show("/login");
    expect(screen.getByLabelText("实际项目范围")).toBeVisible();
    expect(mocks.projects).not.toHaveBeenCalled();
    expect(screen.queryByText("项目访问范围加载失败")).not.toBeInTheDocument();
  });

  it("ignores a canceled refresh after logout and does not gate login", async () => {
    show();
    await screen.findByLabelText("实际项目范围");
    let rejectRefresh: (reason: unknown) => void = () => {};
    mocks.projects.mockReturnValueOnce(
      new Promise((_, reject) => {
        rejectRefresh = reject;
      }),
    );
    fireEvent(window, new Event("focus"));
    fireEvent.click(screen.getByRole("button", { name: "退出测试" }));
    rejectRefresh(
      new DOMException("signal is aborted without reason", "AbortError"),
    );
    await waitFor(() => expect(mocks.projects).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("实际项目范围")).toBeVisible();
    expect(screen.queryByText("项目访问范围加载失败")).not.toBeInTheDocument();
    expect(
      screen.queryByText("signal is aborted without reason"),
    ).not.toBeInTheDocument();
  });

  it("keeps a genuine initial project failure visible and retryable", async () => {
    mocks.projects.mockRejectedValueOnce(new Error("真实网络失败"));
    show();
    expect(await screen.findByText("项目访问范围加载失败")).toBeVisible();
    expect(screen.queryByLabelText("实际项目范围")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByLabelText("实际项目范围")).toBeVisible();
  });

  it("keeps the selected project and mounted page when an idle focus refresh fails, then retries", async () => {
    sessionStorage.setItem("project:42", "2");
    show();
    await screen.findByText("项目甲");
    const page = screen.getByLabelText("实际项目范围");
    mocks.projects.mockRejectedValueOnce(new Error("项目列表返回内容异常"));
    fireEvent(window, new Event("focus"));
    await screen.findByText("项目列表暂时无法更新，当前页面已保留");
    expect(screen.getByLabelText("实际项目范围")).toBe(page);
    expect(page).toHaveTextContent("2");
    expect(getActiveProject()).toBe("2");
    fireEvent.click(screen.getByRole("button", { name: "重试更新项目" }));
    await waitFor(() =>
      expect(
        screen.queryByText("项目列表暂时无法更新，当前页面已保留"),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByLabelText("实际项目范围")).toBe(page);
  });

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

  it("uses the authorized default when public access is disabled", async () => {
    sessionStorage.setItem("project:42", "1");
    mocks.projects.mockResolvedValue({
      items: [{ id: 2, name: "逻辑推理", isActive: true, isDefault: false }],
      defaultProjectId: 2,
      canManage: false,
      canAssign: false,
    });
    show();
    await waitFor(() =>
      expect(screen.getByLabelText("实际项目范围")).toHaveTextContent("2"),
    );
    expect(getActiveProject()).toBe("2");
    expect(sessionStorage.getItem("project:42")).toBe("2");
    expect(screen.queryByText("公开")).not.toBeInTheDocument();
  });

  it("waits for project authorization before mounting business pages", async () => {
    let resolve: (value: unknown) => void = () => {};
    mocks.projects.mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    show();
    expect(screen.queryByLabelText("实际项目范围")).not.toBeInTheDocument();
    resolve({
      items: [{ id: 2, name: "逻辑推理", isActive: true, isDefault: false }],
      defaultProjectId: 2,
      canManage: false,
      canAssign: false,
    });
    await waitFor(() =>
      expect(screen.getByLabelText("实际项目范围")).toHaveTextContent("2"),
    );
  });
});
