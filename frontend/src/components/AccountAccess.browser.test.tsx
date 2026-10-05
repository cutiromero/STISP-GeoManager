import { App as AntApp } from "antd";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { setLocale } from "../i18n";
const { request, setUser } = vi.hoisted(() => ({
  request: vi.fn(),
  setUser: vi.fn(),
}));
vi.mock("../api/client", () => ({ requestJson: request }));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({
    user: { id: 10, displayName: "测试用户", department: "研究组" },
    setUser,
  }),
}));
import { AccountAccessCard } from "./AccountAccess";
const access = {
  permissions: [
    { id: "compute.submit_task", label: "提交计算任务", group: "计算权限" },
  ],
  agentActions: ["读取有权访问的数据"],
  researchEligible: true,
  researchAdditionalPermissions: [
    { id: "catalog.add_dataresource", label: "上传数据", group: "数据权限" },
  ],
  application: null,
};
beforeEach(async () => {
  await setLocale("zh-CN");
  request.mockReset();
  setUser.mockReset();
  sessionStorage.clear();
  request.mockResolvedValue(access);
});
it("shows own capabilities and a separate application that confirms submission", async () => {
  const view = render(
    <AntApp>
      <AccountAccessCard />
    </AntApp>,
  );
  expect(await screen.findByText("提交计算任务")).toBeTruthy();
  expect(screen.queryByText("管理账号")).toBeNull();
  fireEvent.click(
    await screen.findByRole("button", { name: "申请成为科研用户" }),
  );
  fireEvent.change(await screen.findByLabelText("科研需求和申请说明"), {
    target: { value: "需要上传数据开展研究" },
  });
  request.mockResolvedValue({
    ...access,
    application: { id: 1, status: "pending", reviewNote: "" },
  });
  fireEvent.click(screen.getByRole("button", { name: "提交申请" }));
  await screen.findByText("已申请，等待超级管理员审核");
  expect(
    screen.getByRole("button", { name: "已申请" }).hasAttribute("disabled"),
  ).toBe(true);
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      "/api/auth/research-application/",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  view.unmount();
});
