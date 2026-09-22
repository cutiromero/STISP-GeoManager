import type { Map as MapboxMap } from "mapbox-gl";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  cloneDefaultGroupSymbolization,
  cloneDefaultRasterSymbolization,
  cloneDefaultVectorSymbolization,
} from "../symbolization";
import type {
  LoadedLayerGroup,
  LoadedRasterLayer,
  LoadedVectorLayer,
  ResourceListItem,
} from "../types";
import { sourceIdFor } from "../utils/geometry";

const mocks = vi.hoisted(() => ({
  addLoadedStyleLayers: vi.fn(),
  addRasterLayer: vi.fn(),
  registerPlatformSymbolImages: vi.fn(),
  removeLoadedLayerGroup: vi.fn(),
  reorderLoadedStyleLayers: vi.fn(),
  setLoadedLayerGroupVisibility: vi.fn(),
  syncVectorInteractions: vi.fn(),
}));

vi.mock("./featureInteraction", () => ({
  syncVectorInteractions: mocks.syncVectorInteractions,
}));

vi.mock("./rasterLayerSync", () => ({
  addRasterLayer: mocks.addRasterLayer,
}));

vi.mock("./symbolImages", () => ({
  registerPlatformSymbolImages: mocks.registerPlatformSymbolImages,
}));

vi.mock("./vectorLayerSync", () => ({
  addLoadedStyleLayers: mocks.addLoadedStyleLayers,
  removeLoadedLayerGroup: mocks.removeLoadedLayerGroup,
  reorderLoadedStyleLayers: mocks.reorderLoadedStyleLayers,
  setLoadedLayerGroupVisibility: mocks.setLoadedLayerGroupVisibility,
}));

import { effectiveMapLayers } from "./effectiveMapLayers";
import { syncLoadedLayers } from "./loadedLayerSync";

describe("effectiveMapLayers", () => {
  it("combines group and child visibility for vector and raster layers", () => {
    const vector = makeVectorLayer("vector", true, 80);
    const raster = makeRasterLayer("raster", false, 60);
    const group = makeGroup(false, [vector, raster], 50);

    const layers = effectiveMapLayers([group]);

    expect(layers.map((layer) => layer.visible)).toEqual([false, false]);
    expect(layers.map((layer) => layer.symbolization.opacity)).toEqual([
      40, 30,
    ]);
    expect(vector.visible).toBe(true);
    expect(raster.visible).toBe(false);
  });
});

describe("syncLoadedLayers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.addRasterLayer.mockImplementation(
      (map: MapboxMap, sourceId: string) => {
        if (!map.getSource(sourceId)) {
          map.addSource(sourceId, { type: "raster", tiles: [] });
        }
      },
    );
  });

  it("keeps sources mounted while vector and raster visibility changes", () => {
    const map = createMap();
    const vector = makeVectorLayer("vector", true);
    const raster = makeRasterLayer("raster", true);
    const vectorSourceId = sourceIdFor(vector.id);
    const rasterSourceId = sourceIdFor(raster.id);

    syncLoadedLayers(map.value, [vector, raster]);
    expect(map.addSource).toHaveBeenCalledTimes(2);
    expect(mocks.setLoadedLayerGroupVisibility).toHaveBeenCalledWith(
      map.value,
      vectorSourceId,
      true,
    );
    expect(mocks.setLoadedLayerGroupVisibility).toHaveBeenCalledWith(
      map.value,
      rasterSourceId,
      true,
    );

    map.addSource.mockClear();
    mocks.removeLoadedLayerGroup.mockClear();
    mocks.setLoadedLayerGroupVisibility.mockClear();
    mocks.syncVectorInteractions.mockClear();

    syncLoadedLayers(map.value, [
      { ...vector, visible: false },
      { ...raster, visible: false },
    ]);

    expect(map.addSource).not.toHaveBeenCalled();
    expect(mocks.removeLoadedLayerGroup).not.toHaveBeenCalled();
    expect(mocks.setLoadedLayerGroupVisibility).toHaveBeenCalledWith(
      map.value,
      vectorSourceId,
      false,
    );
    expect(mocks.setLoadedLayerGroupVisibility).toHaveBeenCalledWith(
      map.value,
      rasterSourceId,
      false,
    );
    expect(mocks.syncVectorInteractions).toHaveBeenLastCalledWith(
      map.value,
      [],
      undefined,
    );

    mocks.setLoadedLayerGroupVisibility.mockClear();
    syncLoadedLayers(map.value, [vector, raster]);

    expect(map.addSource).not.toHaveBeenCalled();
    expect(mocks.removeLoadedLayerGroup).not.toHaveBeenCalled();
    expect(mocks.setLoadedLayerGroupVisibility).toHaveBeenCalledWith(
      map.value,
      vectorSourceId,
      true,
    );
    expect(mocks.setLoadedLayerGroupVisibility).toHaveBeenCalledWith(
      map.value,
      rasterSourceId,
      true,
    );
  });

  it("defers sources that have never been shown until they become visible", () => {
    const map = createMap();
    const vector = makeVectorLayer("vector", false);
    const raster = makeRasterLayer("raster", false);

    syncLoadedLayers(map.value, [vector, raster]);

    expect(map.addSource).not.toHaveBeenCalled();
    expect(mocks.addLoadedStyleLayers).not.toHaveBeenCalled();
    expect(mocks.addRasterLayer).not.toHaveBeenCalled();

    syncLoadedLayers(map.value, [
      { ...vector, visible: true },
      { ...raster, visible: true },
    ]);

    expect(map.addSource).toHaveBeenCalledTimes(2);
    expect(mocks.setLoadedLayerGroupVisibility).toHaveBeenCalledWith(
      map.value,
      sourceIdFor(vector.id),
      true,
    );
    expect(mocks.setLoadedLayerGroupVisibility).toHaveBeenCalledWith(
      map.value,
      sourceIdFor(raster.id),
      true,
    );
  });

  it("removes sources only when layers leave the workspace", () => {
    const map = createMap();
    const vector = makeVectorLayer("vector", true);
    const raster = makeRasterLayer("raster", true);

    syncLoadedLayers(map.value, [vector, raster]);
    mocks.removeLoadedLayerGroup.mockClear();

    syncLoadedLayers(map.value, []);

    expect(mocks.removeLoadedLayerGroup).toHaveBeenCalledTimes(2);
    expect(mocks.removeLoadedLayerGroup).toHaveBeenCalledWith(
      map.value,
      sourceIdFor(vector.id),
    );
    expect(mocks.removeLoadedLayerGroup).toHaveBeenCalledWith(
      map.value,
      sourceIdFor(raster.id),
    );
  });

  it("does not change the camera while restoring layers after a style switch", () => {
    const map = createMap();
    const vector = {
      ...makeVectorLayer("vector", true),
      geojson: {
        type: "FeatureCollection" as const,
        features: [
          {
            type: "Feature" as const,
            id: 1,
            properties: {},
            geometry: { type: "Point" as const, coordinates: [80, 41] },
          },
        ],
      },
    };

    syncLoadedLayers(map.value, [vector], undefined, {
      fitNewLayers: false,
    });

    expect(map.value.fitBounds).not.toHaveBeenCalled();
    expect(map.addSource).toHaveBeenCalledTimes(1);
  });
});

function createMap() {
  const sources = new Map<string, { setData: ReturnType<typeof vi.fn> }>();
  const addSource = vi.fn((sourceId: string) => {
    sources.set(sourceId, { setData: vi.fn() });
  });
  const value = {
    addSource,
    fitBounds: vi.fn(),
    getSource: vi.fn((sourceId: string) => sources.get(sourceId)),
  } as unknown as MapboxMap;
  return { value, addSource };
}

function makeGroup(
  visible: boolean,
  children: LoadedLayerGroup["children"],
  opacity = 100,
): LoadedLayerGroup {
  return {
    id: "group",
    name: "测试图层组",
    sourceResource: sourceResource(),
    visible,
    summary: "",
    createdAt: "2026-07-14T00:00:00.000Z",
    metadata: {},
    symbolization: { ...cloneDefaultGroupSymbolization(), opacity },
    children,
  };
}

function makeVectorLayer(
  id: string,
  visible: boolean,
  opacity = 100,
): LoadedVectorLayer {
  return {
    id,
    name: id,
    layerType: "vector",
    sourceResource: sourceResource(),
    geojson: { type: "FeatureCollection", features: [] },
    geometryType: "Point",
    visible,
    summary: "",
    metadata: {},
    symbolization: { ...cloneDefaultVectorSymbolization(), opacity },
    fields: [],
  };
}

function makeRasterLayer(
  id: string,
  visible: boolean,
  opacity = 100,
): LoadedRasterLayer {
  return {
    id,
    name: id,
    layerType: "raster",
    sourceResource: sourceResource() as LoadedRasterLayer["sourceResource"],
    tileUrl: `/api/raster/tiles/1/style/{z}/{x}/{y}.png`,
    geometryType: "Raster",
    visible,
    summary: "",
    metadata: {},
    symbolization: { ...cloneDefaultRasterSymbolization(), opacity },
    fields: [],
  };
}

function sourceResource(): ResourceListItem {
  return {
    id: 1,
    name: "测试资源",
    dataType: "vector",
  } as ResourceListItem;
}
