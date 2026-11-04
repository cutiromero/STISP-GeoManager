import { fireEvent, render, screen } from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppContext } from "../contexts/AppContext";
import { localeStorageKey, setLocale } from "../i18n";
import { appTheme } from "../theme";
import type { Bootstrap } from "../types";
import LoginPage from "./LoginPage";
import { clearSessionExpired } from "../auth/sessionNotice";
import "../styles.css";
import { page } from "vitest/browser";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    loginOverview: vi.fn(),
    csrf: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    guestLogin: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({ api: mockApi }));

const bootstrap: Bootstrap = {
  systemName: "全球胡杨林生态系统保护数据共享平台",
  allowRegistration: true,
  map: {
    defaultCenter: [87.6, 41.7],
    defaultZoom: 6.5,
    defaultBasemap: "osm",
    mapboxAccessToken: "",
  },
  limits: {
    uploadMaxMb: 512,
    queryResultLimit: 30000,
    maxRasterSidePixels: 10000,
  },
};

function renderLoginPage() {
  return render(
    <ConfigProvider locale={zhCN} theme={appTheme}>
      <AntApp>
        <AppContext.Provider
          value={{
            bootstrap,
            user: null,
            setBootstrap: vi.fn(),
            setUser: vi.fn(),
          }}
        >
          <LoginPage />
        </AppContext.Provider>
      </AntApp>
    </ConfigProvider>,
  );
}

describe("LoginPage", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    clearSessionExpired();
    await setLocale("zh-CN");
    mockApi.loginOverview.mockRejectedValue(new Error("offline"));
  });

  it("shows the login form without an expired-session warning", () => {
    sessionStorage.setItem(
      "auth:expired-return",
      JSON.stringify({ path: "/agent/workbench", userId: 42 }),
    );
    renderLoginPage();
    expect(screen.getByLabelText("账号")).toBeVisible();
    expect(screen.queryByText("登录状态已失效")).not.toBeInTheDocument();
    expect(document.querySelector(".login-session-notice")).toBeNull();
    // Keep the same-account return path without a warning banner.
    expect(sessionStorage.getItem("auth:expired-return")).not.toBeNull();
  });

  it("does not offer remembered login and registers the current page after sign in", async () => {
    mockApi.csrf.mockResolvedValue({});
    mockApi.login.mockResolvedValue({ user: { id: 1 } });
    renderLoginPage();
    expect(screen.queryByText("记住登录状态")).toBeNull();
    fireEvent.change(screen.getByLabelText("账号"), {
      target: { value: "page-user" },
    });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "test-page-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: /登录并进入数据平台/ }));
    await vi.waitFor(() =>
      expect(mockApi.login).toHaveBeenCalledWith(
        "page-user",
        "test-page-password",
        false,
      ),
    );
  });

  it("switches to English immediately and persists the selected locale", async () => {
    renderLoginPage();

    fireEvent.click(screen.getByRole("button", { name: "切换平台语言" }));
    fireEvent.click(await screen.findByText("English"));

    expect(
      await screen.findByRole("heading", { name: "Sign in" }),
    ).toBeVisible();
    expect(screen.getByText("Unified authentication")).toBeVisible();
    expect(window.localStorage.getItem(localeStorageKey)).toBe("en-US");
  });

  it("clears credentials and validation state when switching modes", async () => {
    renderLoginPage();

    fireEvent.change(screen.getByLabelText("账号"), {
      target: { value: "existing-user" },
    });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "do-not-retain" },
    });
    fireEvent.click(screen.getByRole("button", { name: /注册新账号/ }));

    expect(screen.getByLabelText("账号")).toHaveValue("");
    expect(screen.getByLabelText("密码")).toHaveValue("");

    fireEvent.change(screen.getByLabelText("账号"), {
      target: { value: "new-user" },
    });
    fireEvent.change(screen.getByLabelText("邮箱"), {
      target: { value: "new@example.local" },
    });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "new-secret" },
    });
    fireEvent.change(screen.getByLabelText("确认密码"), {
      target: { value: "new-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "返回登录" }));

    expect(screen.getByLabelText("账号")).toHaveValue("");
    expect(screen.getByLabelText("密码")).toHaveValue("");
  });

  it("keeps the blue cover layout with animated backgrounds and no status polling", async () => {
    const { container } = renderLoginPage();
    expect(container.querySelectorAll(".login-background-slide")).toHaveLength(
      3,
    );
    expect(
      container.querySelectorAll(".login-background-slide.is-active"),
    ).toHaveLength(1);
    expect(container.querySelector(".login-stat-grid")).toBeNull();
    expect(container.querySelector(".login-ops-panel")).toBeNull();
    expect(container.querySelector(".login-capability-tags")).toBeNull();
    expect(mockApi.loginOverview).not.toHaveBeenCalled();
    expect(screen.getByText("空天观测，时空智能")).toBeVisible();
    expect(document.querySelector("vite-error-overlay")).toBeNull();
    await page.screenshot({
      path: "../../test-results/login-blue-cover-desktop.png",
    });
  });

  it("keeps login controls inside a smaller browser window", async () => {
    await page.viewport(1000, 650);
    try {
      const { container } = renderLoginPage();
      const card = container.querySelector(".login-card")!;
      const bounds = card.getBoundingClientRect();
      expect(bounds.left).toBeGreaterThanOrEqual(0);
      expect(bounds.right).toBeLessThanOrEqual(window.innerWidth);
      expect(
        screen.getByRole("button", { name: /登录并进入数据平台/ }),
      ).toBeVisible();
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
        window.innerWidth,
      );
      expect(document.querySelector("vite-error-overlay")).toBeNull();
      await page.screenshot({
        path: "../../test-results/login-blue-cover-window.png",
      });
    } finally {
      await page.viewport(1600, 900);
    }
  });
});
