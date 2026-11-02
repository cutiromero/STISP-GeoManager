import { describe, expect, it } from "vitest";
import {
  cloneDefaultRasterSymbolization,
  cloneDefaultVectorSymbolization,
} from "../symbolization";
import type { LoadedRasterLayer, LoadedVectorLayer } from "../types";
import { createEmptyLayerGroup } from "../utils/layerFactory";
import { workbenchLegends } from "./liveLegendData";
import { effectiveMapLayers } from "./effectiveMapLayers";

function raster(): LoadedRasterLayer {
  return {
    id: "raster",
    name: "土地覆盖",
    layerType: "raster",
    sourceResource: createEmptyLayerGroup().sourceResource,
    tileUrl: "/tiles/{z}/{x}/{y}.png",
    visible: true,
    geometryType: "raster",
    summary: "",
    metadata: {},
    fields: [],
    symbolization: cloneDefaultRasterSymbolization(),
  } as LoadedRasterLayer;
}
function vector(): LoadedVectorLayer {
  return {
    id: "vector",
    name: "地质图",
    layerType: "vector",
    sourceResource: createEmptyLayerGroup().sourceResource,
    visible: true,
    geometryType: "Polygon",
    geojson: { type: "FeatureCollection", features: [] },
    summary: "",
    metadata: {},
    fields: [],
    symbolization: cloneDefaultVectorSymbolization(),
  };
}

describe("live map legends", () => {
  it("uses actual returned raster classes without truncating or inventing categories", () => {
    const layer = raster();
    layer.symbolization.mode = "unique";
    layer.symbolization.uniqueValues = Array.from(
      { length: 45 },
      (_, index) => ({ value: index, label: `类别${index}`, color: "#345678" }),
    );
    expect(workbenchLegends([layer])[0]?.entries).toHaveLength(45);
    layer.symbolization.uniqueValues[0]!.color = "#abcdef";
    expect(workbenchLegends([layer])[0]?.entries[0]?.color).toBe("#abcdef");
  });

  it("reflects group/layer visibility and effective opacity", () => {
    const group = createEmptyLayerGroup();
    const layer = vector();
    layer.symbolization.opacity = 80;
    group.symbolization.opacity = 50;
    group.children = [layer];
    expect(workbenchLegends(effectiveMapLayers([group]))[0]?.opacity).toBe(0.4);
    group.visible = false;
    expect(workbenchLegends(effectiveMapLayers([group]))).toEqual([]);
  });

  it("shows real continuous ranges and honest automatic stretch endpoints", () => {
    const layer = raster();
    layer.symbolization.mode = "pseudocolor";
    layer.symbolization.bands = [1];
    layer.symbolization.stretch.perBand = {};
    expect(workbenchLegends([layer])[0]?.gradient).toMatchObject({
      low: "低",
      high: "高",
    });
    layer.symbolization.stretch.perBand = { "1": { min: -0.6, max: 0.9 } };
    expect(workbenchLegends([layer])[0]?.gradient).toMatchObject({
      low: "-0.6",
      high: "0.9",
    });
  });

  it("does not label RGB imagery as land-cover categories", () => {
    const layer = raster();
    layer.symbolization.mode = "rgb";
    layer.symbolization.bands = [3, 2, 1];
    const legend = workbenchLegends([layer])[0]!;
    expect(legend.entries).toEqual([]);
    expect(legend.gradient).toBeUndefined();
    expect(legend.note).toContain("R: 3  G: 2  B: 1");
  });

  it("shows vector classification colors and omits hidden classes", () => {
    const layer = vector();
    const defaultClass = {
      id: "other",
      label: "其他",
      values: [],
      color: "#777777",
      iconImage: "",
      size: 1,
      count: 0,
      visible: false,
    };
    layer.symbolization.renderer = {
      type: "uniqueValue",
      field: "class",
      defaultClass,
      classes: [
        {
          ...defaultClass,
          id: "forest",
          label: "森林",
          color: "#447733",
          visible: true,
        },
        { ...defaultClass, id: "water", label: "水体" },
      ],
    };
    expect(workbenchLegends([layer])[0]?.entries).toEqual([
      { id: "forest", label: "森林", color: "#447733", shape: "polygon" },
    ]);
  });
});
