import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Suspense, useEffect } from "react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApplicationErrorBoundary,
  isPageChunkError,
  lazyPage,
  retryFailedPageLoads,
  RouteRecovery,
} from "./pageRecovery";

beforeEach(() => {
  sessionStorage.removeItem("platform:last-page-error");
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  retryFailedPageLoads();
  vi.restoreAllMocks();
});

describe("page recovery", () => {
  it("can retry a rejected lazy page without retaining React.lazy's rejection", async () => {
    const load = vi
      .fn()
      .mockRejectedValueOnce(
        new TypeError("Failed to fetch dynamically imported module"),
      )
      .mockResolvedValueOnce({ default: () => <p>科研页面已恢复</p> });
    const Page = lazyPage(load);
    render(
      <MemoryRouter initialEntries={["/agent/workbench"]}>
        <RouteRecovery>
          <Suspense fallback={<p>正在加载</p>}>
            <Page />
          </Suspense>
        </RouteRecovery>
      </MemoryRouter>,
    );
    expect(await screen.findByText("页面资源加载失败")).toBeVisible();
    expect(screen.getByRole("link", { name: "快速对话" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "重试当前页面" }));
    expect(await screen.findByText("科研页面已恢复")).toBeVisible();
    expect(load).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps navigation usable after an effect throws and recovers on route changes", async () => {
    function BrokenPage() {
      useEffect(() => {
        throw new Error("planned page effect failure");
      }, []);
      return <p>载入中</p>;
    }
    render(
      <MemoryRouter initialEntries={["/agent/workbench"]}>
        <RouteRecovery>
          <Routes>
            <Route path="/agent/workbench" element={<BrokenPage />} />
            <Route path="/map" element={<p>地图页面可用</p>} />
          </Routes>
        </RouteRecovery>
      </MemoryRouter>,
    );
    expect(await screen.findByText("当前页面出现异常")).toBeVisible();
    const diagnostic = JSON.parse(
      sessionStorage.getItem("platform:last-page-error") ?? "null",
    );
    expect(diagnostic.path).toBe("/agent/workbench");
    expect(diagnostic.message).toBe("planned page effect failure");
    expect(diagnostic.componentStack).toContain("BrokenPage");
    fireEvent.click(screen.getByRole("link", { name: "地理工作台" }));
    expect(await screen.findByText("地图页面可用")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reloads a previously rejected page when leaving and returning to its route", async () => {
    const load = vi
      .fn()
      .mockRejectedValueOnce(new Error("Loading chunk 7 failed"))
      .mockResolvedValueOnce({ default: () => <p>科研智能体正常显示</p> });
    const Page = lazyPage(load);
    render(
      <MemoryRouter initialEntries={["/agent/workbench"]}>
        <RouteRecovery>
          <Suspense fallback={<p>正在加载</p>}>
            <Routes>
              <Route path="/agent/workbench" element={<Page />} />
              <Route
                path="/map"
                element={<Link to="/agent/workbench">返回科研智能体</Link>}
              />
            </Routes>
          </Suspense>
        </RouteRecovery>
      </MemoryRouter>,
    );
    expect(await screen.findByText("页面资源加载失败")).toBeVisible();
    fireEvent.click(screen.getByRole("link", { name: "地理工作台" }));
    fireEvent.click(
      await screen.findByRole("link", { name: "返回科研智能体" }),
    );
    expect(await screen.findByText("科研智能体正常显示")).toBeVisible();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("catches an application-level render failure without relying on providers", async () => {
    function BrokenProvider(): never {
      throw new TypeError("planned provider failure");
    }
    render(
      <ApplicationErrorBoundary>
        <BrokenProvider />
      </ApplicationErrorBoundary>,
    );
    expect(await screen.findByText("当前页面出现异常")).toBeVisible();
    expect(screen.getByRole("link", { name: "地理工作台" })).toHaveAttribute(
      "href",
      "/map",
    );
    expect(screen.getByRole("button", { name: "重新加载平台" })).toBeVisible();
    await waitFor(() => expect(console.error).toHaveBeenCalled());
  });

  it("retains recovery navigation when an older browser lacks AbortSignal.any", async () => {
    const descriptor = Object.getOwnPropertyDescriptor(AbortSignal, "any");
    Object.defineProperty(AbortSignal, "any", {
      configurable: true,
      value: undefined,
    });
    function UnsupportedEffect() {
      useEffect(() => {
        AbortSignal.any([new AbortController().signal]);
      }, []);
      return <p>载入工作流</p>;
    }
    try {
      render(
        <MemoryRouter initialEntries={["/agent/workbench"]}>
          <RouteRecovery>
            <Routes>
              <Route path="/agent/workbench" element={<UnsupportedEffect />} />
              <Route path="/map" element={<p>兼容模式下地图可用</p>} />
            </Routes>
          </RouteRecovery>
        </MemoryRouter>,
      );
      expect(await screen.findByText("当前页面出现异常")).toBeVisible();
      expect(sessionStorage.getItem("platform:last-page-error")).toContain(
        "AbortSignal.any",
      );
      fireEvent.click(screen.getByRole("link", { name: "地理工作台" }));
      expect(await screen.findByText("兼容模式下地图可用")).toBeVisible();
    } finally {
      if (descriptor) Object.defineProperty(AbortSignal, "any", descriptor);
      else Reflect.deleteProperty(AbortSignal, "any");
    }
  });

  it("recognizes chunk errors without classifying normal page errors as updates", () => {
    expect(
      isPageChunkError(
        new TypeError("error loading dynamically imported module"),
      ),
    ).toBe(true);
    expect(isPageChunkError(new Error("Loading CSS chunk 4 failed"))).toBe(
      true,
    );
    expect(
      isPageChunkError(new Error("Cannot read properties of undefined")),
    ).toBe(false);
  });
});
