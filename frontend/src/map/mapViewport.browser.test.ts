import type { Map as MapboxMap } from "mapbox-gl";
import { describe, expect, it } from "vitest";
import {
  fitBoundsOptions,
  rasterFitBoundsOptions,
  readMapViewState,
} from "./mapViewport";

describe("mapViewport", () => {
  it("reads bounds from the full map container state", () => {
    const map = createMap();

    const view = readMapViewState(map);

    expect(view.center).toEqual([88, 44]);
    expect(view.bounds).toEqual([80, 40, 96, 48]);
    expect(view.zoom).toBe(5);
  });

  it("uses fixed fitBounds padding", () => {
    expect(fitBoundsOptions(80).padding).toBe(80);
  });

  it("uses a top-down zoom limit for small raster extents", () => {
    expect(rasterFitBoundsOptions()).toMatchObject({
      padding: 80,
      maxZoom: 19,
      bearing: 0,
      pitch: 0,
    });
  });
});

function createMap() {
  return {
    getBounds: () => ({
      getSouthWest: () => ({ lng: 80, lat: 40 }),
      getNorthEast: () => ({ lng: 96, lat: 48 }),
    }),
    getCenter: () => ({ lng: 88, lat: 44 }),
    getZoom: () => 5,
    getBearing: () => 0,
    getPitch: () => 0,
  } as unknown as MapboxMap;
}
