import { fireEvent, render, screen, within } from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppContext } from "../contexts/AppContext";
import { setLocale } from "../i18n";
import { appTheme } from "../theme";
import type { Bootstrap } from "../types";
import AboutV2Page from "./AboutV2Page";

const bootstrap: Bootstrap = {
  systemName: "时空智能服务平台",
  allowRegistration: true,
  map: {
    defaultCenter: [116.4, 39.9],
    defaultZoom: 6,
    defaultBasemap: "osm",
    mapboxAccessToken: "",
  },
  limits: {
    uploadMaxMb: 512,
    queryResultLimit: 30000,
    maxRasterSidePixels: 10000,
  },
};

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

function renderAbout(path = "/about/team") {
  return render(
    <ConfigProvider theme={appTheme}>
      <AntApp>
        <AppContext.Provider
          value={{
            bootstrap,
            user: null,
            setBootstrap: vi.fn(),
            setUser: vi.fn(),
          }}
        >
          <MemoryRouter initialEntries={[path]}>
            <LocationProbe />
            <Routes>
              <Route
                path="/about/:section/:institutionId?"
                element={<AboutV2Page />}
              />
            </Routes>
          </MemoryRouter>
        </AppContext.Provider>
      </AntApp>
    </ConfigProvider>,
  );
}

describe("combined team introduction", () => {
  beforeEach(async () => {
    await setLocale("zh-CN");
  });

  it.each(["/about/members", "/about/team/tarim-university"])(
    "redirects the old entry %s to the unified team page",
    async (path) => {
      renderAbout(path);
      expect(
        await screen.findByRole("heading", { name: "团队介绍", level: 1 }),
      ).toBeVisible();
      expect(screen.getByTestId("location")).toHaveTextContent("/about/team");
      const sidebar = within(screen.getByRole("complementary"));
      expect(sidebar.getAllByRole("button")).toHaveLength(4);
      expect(
        sidebar.queryByRole("button", { name: /团队成员/ }),
      ).not.toBeInTheDocument();
      expect(sidebar.getByRole("button", { name: /团队介绍/ })).toHaveAttribute(
        "aria-current",
        "page",
      );
    },
  );

  it("shows all supplied members and expands their publications with clean DOI links", async () => {
    renderAbout();
    expect(screen.getAllByRole("img", { name: /照片$/ })).toHaveLength(11);
    const card = screen
      .getByRole("heading", { name: "李茂林" })
      .closest("article")!;
    expect(
      within(card).getByRole("link", { name: "limaolin26@mails.ucas.ac.cn" }),
    ).toHaveAttribute("href", "mailto:limaolin26@mails.ucas.ac.cn");
    fireEvent.click(
      within(card).getByRole("button", { name: /论文成果（8）/ }),
    );
    expect(await within(card).findAllByRole("listitem")).toHaveLength(8);
    expect(
      within(card).getByRole("link", { name: /Assessment, driving mechanism/ }),
    ).toHaveAttribute("href", "https://doi.org/10.1016/j.ecolind.2025.114340");
    expect(screen.queryByText(/塔里木大学/)).not.toBeInTheDocument();
  });

  it("keeps the English team, contact and help routes available", async () => {
    await setLocale("en-US");
    renderAbout();
    expect(screen.getByRole("button", { name: "Team News" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Official account QR code" })).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Spatiotemporal Intelligence Research Team",
      }),
    ).toBeVisible();
    expect(screen.getAllByRole("img", { name: /portrait$/ })).toHaveLength(11);
    fireEvent.click(
      within(screen.getByRole("complementary")).getByRole("button", {
        name: /Contact/,
      }),
    );
    expect(screen.getByRole("heading", { name: "Contact us" })).toBeVisible();
    expect(
      screen.getByRole("link", { name: "wanghaoyu@aircas.ac.cn" }),
    ).toHaveAttribute("href", "mailto:wanghaoyu@aircas.ac.cn");
    fireEvent.click(
      within(screen.getByRole("complementary")).getByRole("button", {
        name: /Help Center/,
      }),
    );
    expect(screen.getByTestId("location")).toHaveTextContent("/about/docs");
    expect(screen.queryByRole("heading", { name: /Backup|Administration|Permission audit/i })).not.toBeInTheDocument();
  });

  it("shows reader-facing help without administrator introductions or a full manual download", async () => {
    renderAbout("/about/docs");
    expect(await screen.findByRole("heading", { name: "帮助文档", level: 2 })).toBeVisible();
    expect(screen.queryByText("数据管理员")).not.toBeInTheDocument();
    expect(screen.queryByText("系统管理员")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "后台运行概览" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /PDF/ })).not.toBeInTheDocument();
  });
});
