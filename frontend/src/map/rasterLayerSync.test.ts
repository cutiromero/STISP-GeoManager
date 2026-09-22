import type { AnyLayer, Map as MapboxMap } from "mapbox-gl";
import { describe, expect, it, vi } from "vitest";
import { cloneDefaultRasterSymbolization } from "../symbolization";
import type { LoadedRasterLayer } from "../types";
import {
  addRasterLayer,
  rasterTileRendererVersion,
  versionedRasterTileUrl,
} from "./rasterLayerSync";

describe("addRasterLayer", () => {
  it("disables interpolation and zoom cross-fading for categorical rasters", () => {
    const { map, addedLayers, addedSources } = makeMap();
    const layer = makeRasterLayer("categorical", "unique");

    addRasterLayer(map, "lucc", layer);

    expect(addedLayers[0]?.paint).toMatchObject({
      "raster-resampling": "nearest",
      "raster-fade-duration": 0,
    });
    expect(addedSources[0]?.source).toMatchObject({
      tiles: [
        `/api/raster/tiles/1/hash/{z}/{x}/{y}.png?rv=${rasterTileRendererVersion}`,
      ],
      minzoom: 0,
      maxzoom: 16,
    });
  });

  it("honors explicit backend nearest sampling before raster metadata is available", () => {
    const { map, addedLayers } = makeMap();
    const layer = makeRasterLayer(undefined, "gray");
    layer.tileSampling = "nearest";

    addRasterLayer(map, "restored-lucc", layer);

    expect(addedLayers[0]?.paint).toMatchObject({
      "raster-resampling": "nearest",
      "raster-fade-duration": 0,
    });
  });

  it("replaces stale renderer versions without dropping existing queries", () => {
    expect(
      versionedRasterTileUrl(
        "/api/raster/tiles/1/hash/{z}/{x}/{y}.png?token=a&rv=1",
      ),
    ).toBe(
      `/api/raster/tiles/1/hash/{z}/{x}/{y}.png?token=a&rv=${rasterTileRendererVersion}`,
    );
  });

  it("keeps smooth sampling for continuous rasters", () => {
    const { map, addedLayers } = makeMap();
    const layer = makeRasterLayer("continuous", "gray");

    addRasterLayer(map, "dem", layer);

    expect(addedLayers[0]?.paint).toMatchObject({
      "raster-resampling": "linear",
      "raster-fade-duration": 300,
    });
  });

  it("recreates an unchanged raster source after a full style replacement", () => {
    const { map } = makeMap();
    const layer = makeRasterLayer("continuous", "gray");

    addRasterLayer(map, "dem", layer);
    map.removeSource("dem");
    addRasterLayer(map, "dem", layer);

    expect(map.addSource).toHaveBeenCalledTimes(2);
    expect(map.getSource("dem")).toBeDefined();
  });
});

function makeRasterLayer(
  rasterKind: LoadedRasterLayer["rasterKind"],
  mode: LoadedRasterLayer["symbolization"]["mode"],
): LoadedRasterLayer {
  const symbolization = cloneDefaultRasterSymbolization();
  symbolization.mode = mode;
  return {
    id: `raster-${rasterKind}`,
    name: "测试栅格",
    layerType: "raster",
    sourceResource: {} as LoadedRasterLayer["sourceResource"],
    tileUrl: "/api/raster/tiles/1/hash/{z}/{x}/{y}.png",
    tileMinZoom: rasterKind === "categorical" ? 0 : undefined,
    tileMaxZoom: rasterKind === "categorical" ? 16 : undefined,
    tileSampling: rasterKind === "categorical" ? "nearest" : undefined,
    rasterKind,
    geometryType: "Raster",
    visible: true,
    summary: "",
    metadata: {},
    symbolization,
    fields: [],
  };
}

function makeMap() {
  const sources = new Set<string>();
  const addedLayers: AnyLayer[] = [];
  const addedSources: Array<{ id: string; source: unknown }> = [];
  const map = {
    style: {},
    getStyle: vi.fn(() => ({})),
    getLayer: vi.fn(() => undefined),
    getSource: vi.fn((id: string) => (sources.has(id) ? {} : undefined)),
    addSource: vi.fn((id: string, source: unknown) => {
      sources.add(id);
      addedSources.push({ id, source });
    }),
    removeSource: vi.fn((id: string) => sources.delete(id)),
    addLayer: vi.fn((layer: AnyLayer) => addedLayers.push(layer)),
    removeLayer: vi.fn(),
    setFilter: vi.fn(),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
  } as unknown as MapboxMap;
  return { map, addedLayers, addedSources };
}
