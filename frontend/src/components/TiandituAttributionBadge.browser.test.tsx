import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { BasemapProvider } from "../map/basemapCatalog";
import TiandituAttributionBadge from "./TiandituAttributionBadge";

describe("TiandituAttributionBadge", () => {
  it("shows the official wordmark as a persistent Tianditu source link", () => {
    render(<TiandituAttributionBadge provider="tianditu" />);

    expect(
      screen.getByRole("complementary", { name: "天地图底图来源" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "访问天地图官网（新窗口打开）" }),
    ).toHaveAttribute("href", "https://www.tianditu.gov.cn/");
    expect(
      screen.getByRole("img", { name: "天地图 MAP WORLD" }),
    ).toHaveAttribute("src", expect.stringContaining("tianditu-map-world.svg"));
    expect(screen.getByText("天地图底图服务")).toBeVisible();
  });

  it.each<BasemapProvider>(["mapbox", "osm"])(
    "stays hidden for the %s provider",
    (provider) => {
      const { container } = render(
        <TiandituAttributionBadge provider={provider} />,
      );

      expect(container).toBeEmptyDOMElement();
    },
  );
});
