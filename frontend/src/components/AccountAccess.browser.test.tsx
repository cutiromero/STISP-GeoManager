import { App as AntApp } from "antd";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { setLocale } from "../i18n";
import { page, userEvent } from "vitest/browser";
import accountStyles from "../styles.css?inline";
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

it.each([1200, 390])(
  "keeps available feature groups readable at %s pixels without changing grants",
  async (width) => {
    await page.viewport(width, 900);
    try {
      const { container } = render(
        <AntApp>
          <style>{accountStyles}</style>
          <AccountAccessCard />
        </AntApp>,
      );
      expect(
        await screen.findByRole("heading", { name: "计算权限" }),
      ).toBeVisible();
      expect(screen.getByRole("heading", { name: "智能体操作" })).toBeVisible();
      expect(screen.getByText("提交计算任务")).toBeVisible();
      expect(screen.getByText("读取有权访问的数据")).toBeVisible();
      expect(screen.queryByText("compute.submit_task")).toBeNull();
      expect(screen.queryByRole("switch")).toBeNull();
      for (const group of container.querySelectorAll<HTMLElement>(
        ".account-permission-group",
      )) {
        expect(group.scrollWidth).toBeLessThanOrEqual(group.clientWidth + 1);
        expect(group.getBoundingClientRect().right).toBeLessThanOrEqual(width);
      }
      await userEvent.click(screen.getByRole("button", { name: "刷新权限" }));
      await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
      expect(
        request.mock.calls.every(
          ([url, options]) => url === "/api/auth/access/" && !options,
        ),
      ).toBe(true);
    } finally {
      await page.viewport(1600, 900);
    }
  },
);
