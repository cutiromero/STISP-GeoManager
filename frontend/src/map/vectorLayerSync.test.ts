import type { Map as MapboxMap } from "mapbox-gl";
import { describe, expect, it, vi } from "vitest";
import { cloneDefaultVectorSymbolization } from "../symbolization";
import type { LoadedVectorLayer } from "../types";
import {
  addLoadedStyleLayers,
  loadedStyleLayerIds,
  reorderLoadedStyleLayers,
  setLoadedLayerGroupVisibility,
} from "./vectorLayerSync";

function createVectorLayer(
  symbolization = cloneDefaultVectorSymbolization(),
): LoadedVectorLayer {
  return {
    id: "layer-1",
    name: "Test layer",
    layerType: "vector",
    sourceResource: {
      id: 1,
      name: "Resource",
    } as LoadedVectorLayer["sourceResource"],
    geojson: {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [75, 39] },
          properties: { region: "Kashgar" },
        },
      ],
    },
    geometryType: "Point",
    visible: true,
    summary: "",
    metadata: {},
    symbolization,
    fields: [],
  };
}

describe("setLoadedLayerGroupVisibility", () => {
  it("updates every supported vector and raster style layer", () => {
    const sourceId = "loaded-test";
    const layerIds = loadedStyleLayerIds(sourceId);
    const setLayoutProperty = vi.fn();
    const map = {
      style: {},
      getLayer: vi.fn((layerId: string) =>
        layerIds.includes(layerId) ? { id: layerId } : undefined,
      ),
      setLayoutProperty,
    } as unknown as MapboxMap;

    setLoadedLayerGroupVisibility(map, sourceId, false);
    expect(setLayoutProperty).toHaveBeenCalledTimes(layerIds.length);
    for (const layerId of layerIds) {
      expect(setLayoutProperty).toHaveBeenCalledWith(
        layerId,
        "visibility",
        "none",
      );
    }

    setLayoutProperty.mockClear();
    setLoadedLayerGroupVisibility(map, sourceId, true);
    expect(setLayoutProperty).toHaveBeenCalledTimes(layerIds.length);
    for (const layerId of layerIds) {
      expect(setLayoutProperty).toHaveBeenCalledWith(
        layerId,
        "visibility",
        "visible",
      );
    }
  });
});

describe("reorderLoadedStyleLayers", () => {
  it("keeps the first layer in the tree above later layers on the map", () => {
    const upper = { ...createVectorLayer(), id: "upper" };
    const lower = { ...createVectorLayer(), id: "lower" };
    const existingIds = new Set([
      "loaded-upper-fill",
      "loaded-upper-line",
      "loaded-lower-fill",
      "loaded-lower-line",
    ]);
    const moveLayer = vi.fn();
    const map = {
      style: {},
      getLayer: vi.fn((id: string) =>
        existingIds.has(id) ? { id } : undefined,
      ),
      moveLayer,
    } as unknown as MapboxMap;

    reorderLoadedStyleLayers(map, [upper, lower]);

    expect(moveLayer.mock.calls.map(([id]) => id)).toEqual([
      "loaded-lower-fill",
      "loaded-lower-line",
      "loaded-upper-fill",
      "loaded-upper-line",
    ]);
  });
});

describe("addLoadedStyleLayers", () => {
  it("uses unique-value class size as the symbol icon-size multiplier", () => {
    const addLayer = vi.fn();
    const style = cloneDefaultVectorSymbolization();
    style.pointMode = "symbol";
    style.symbol.iconImage = "custom-marker";
    style.symbol.iconSize = 1.5;
    style.renderer = {
      type: "uniqueValue",
      field: "region",
      updatedByUser: true,
      classes: [
        {
          id: "kashgar",
          label: "Kashgar",
          values: ["Kashgar"],
          color: "#e74c8c",
          iconImage: "custom-marker",
          size: 0.2,
          count: 1,
          visible: true,
        },
      ],
      defaultClass: {
        id: "other",
        label: "Other",
        values: [],
        color: "#888888",
        iconImage: "custom-marker",
        size: 1,
        count: 0,
        visible: true,
      },
    };
    const map = {
      style: {},
      getStyle: vi.fn(() => ({})),
      getLayer: vi.fn(() => undefined),
      addLayer,
      hasImage: vi.fn(() => false),
      addImage: vi.fn(),
      setFilter: vi.fn(),
      setLayoutProperty: vi.fn(),
      setPaintProperty: vi.fn(),
    } as unknown as MapboxMap;

    addLoadedStyleLayers(map, "loaded-test", createVectorLayer(style));

    const symbolLayer = addLayer.mock.calls.find(
      ([layer]) => layer.id === "loaded-test-symbol",
    )?.[0];
    expect(symbolLayer.layout["icon-size"]).toEqual([
      "match",
      ["to-string", ["get", "region"]],
      "Kashgar",
      0.30000000000000004,
      1.5,
    ]);
  });
});
