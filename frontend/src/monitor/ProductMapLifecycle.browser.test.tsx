import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type {
  ProjectMonitorConfig,
  ResourceListItem,
} from "../api/generated/types.gen";
import { setActiveProject } from "../projects/session";
import ProductMap from "./ProductMap";
import { clearMonitorResourceProfiles } from "./resourceProfiles";
import { installMonitorMapboxMock } from "./test/monitorMapbox";

const context = vi.hoisted(() => ({
  bootstrap: { map: { mapboxAccessToken: "", defaultBasemap: "osm" } },
}));
vi.mock("../contexts/AppContext", () => ({ useAppContext: () => context }));
let maps: ReturnType<typeof installMonitorMapboxMock>;
const config = (center: [number, number]): ProjectMonitorConfig => ({
  title: "互花米草分布",
  source: "remote_sensing_products",
  scenes: ["spartina"],
  initialView: { center, zoom: 0.3, regionZoom: 11 },
});
const resource = {
  id: 901,
  name: "研究区分布",
  code: "distribution",
  dataType: "vector",
  updatedAt: "2026-11-15T00:00:00Z",
} as ResourceListItem;
const view = (center: [number, number], selected?: ResourceListItem) => (
  <App>
    <ProductMap
      config={config(center)}
      resource={selected}
      animated={false}
      focusProduct
    />
  </App>
);
beforeEach(() => {
  vi.restoreAllMocks();
  setActiveProject("13");
  clearMonitorResourceProfiles();
  context.bootstrap.map.defaultBasemap = "osm";
  maps = installMonitorMapboxMock();
  vi.spyOn(api, "resourceProfile").mockResolvedValue({
    resource,
    fields: [],
    featureCount: 3,
    geometryType: "MultiPolygon",
    bounds: [121.9, 31.2, 121.99, 31.29],
    raster: null,
    defaultVisualization: {},
    vectorTiles: {
      revision: "one",
      tileUrl: "/tiles/{z}/{x}/{y}.pbf",
      sourceLayer: "features",
      minZoom: 0,
      maxZoom: 16,
      bounds: [121.9, 31.2, 121.99, 31.29],
      clustered: false,
      featureCount: 3,
    },
  });
});

it("keeps the map alive while switching from a selected region to an empty result group and back", async () => {
  const screen = render(view([121.945, 31.245], resource));
  await waitFor(() => expect(maps.maps[0]?.sources.has("product")).toBe(true));
  screen.rerender(view([121.92, 31.24]));
  await waitFor(() => expect(maps.maps[0]?.sources.has("product")).toBe(false));
  expect(maps.maps).toHaveLength(1);
  expect(maps.maps[0]!.api.remove).not.toHaveBeenCalled();
  screen.rerender(view([121.945, 31.245], resource));
  await waitFor(() => expect(maps.maps[0]?.sources.has("product")).toBe(true));
  expect(maps.maps).toHaveLength(1);
  expect(api.resourceProfile).toHaveBeenCalledOnce();
  expect(maps.maps[0]!.api.fitBounds).toHaveBeenCalledTimes(2);
});

it("does not clean layers on a destroyed map when the basemap configuration changes", async () => {
  const screen = render(view([121.92, 31.24], resource));
  await waitFor(() => expect(maps.maps[0]?.sources.has("product")).toBe(true));
  context.bootstrap.map.defaultBasemap = "satellite";
  screen.rerender(view([121.92, 31.24]));
  await waitFor(() => expect(maps.maps[1]?.value.getStyle()).toBeTruthy());
  expect(maps.maps[0]!.api.remove).toHaveBeenCalledOnce();
  expect(maps.maps[0]!.value.getStyle()).toBeUndefined();
  screen.rerender(view([121.92, 31.24], resource));
  await waitFor(() => expect(maps.maps[1]?.sources.has("product")).toBe(true));
});

it("focuses the actual product extent rather than a shared project's default center", async () => {
  render(view([121.92, 31.24], resource));
  await waitFor(() => expect(maps.maps[0]?.api.fitBounds).toHaveBeenCalled());
  maps.maps[0]!.api.fitBounds.mockClear();
  fireEvent.click(
    screen.getByRole("button", { name: "聚焦研究区", exact: true }),
  );
  expect(maps.maps[0]!.api.fitBounds).toHaveBeenCalledOnce();
  expect(maps.maps[0]!.api.flyTo).not.toHaveBeenCalled();
});
