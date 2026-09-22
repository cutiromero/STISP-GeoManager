import { describe, expect, it } from "vitest";
import {
  cloneDefaultGroupSymbolization,
  cloneDefaultRasterSymbolization,
  cloneDefaultVectorSymbolization,
} from "../symbolization";
import type {
  DataResource,
  LoadedLayerGroup,
  LoadedRasterLayer,
  LoadedVectorLayer,
  SavedWorkspaceLayerGroup,
} from "../types";
import {
  isLoadedVectorLayer,
  toSavedWorkspaceLayer,
  workspaceSnapshot,
} from "./workspaceSnapshot";

function makeResource(overrides: Partial<DataResource> = {}): DataResource {
  return {
    id: 1,
    name: "测试资源",
    code: "test-resource",
    dataType: "vector",
    category: null,
    source: "测试来源",
    provider: "测试单位",
    dataDate: null,
    spatialExtent: "80,40,85,45",
    coordinateSystem: "EPSG:4326",
    fileFormat: "GPKG",
    description: "",
    qualityNote: "",
    status: "active",
    isQueryable: true,
    isRenderable: true,
    updatedAt: "2025-01-01",
    ...overrides,
  };
}

function makeVectorLayer(): LoadedVectorLayer {
  return {
    id: "layer-vector",
    name: "矢量图层",
    layerType: "vector",
    sourceResource: makeResource(),
    geojson: { type: "FeatureCollection", features: [] },
    geometryType: "Point",
    visible: true,
    summary: "0/0 条",
    metadata: { 图层类型: "矢量" },
    symbolization: cloneDefaultVectorSymbolization(),
    fields: [],
    query: {
      attributeFilters: [],
      spatialFilter: null,
    },
  };
}

function makeLayerGroup(child: LoadedVectorLayer): LoadedLayerGroup {
  return {
    id: "group-1",
    name: "测试图层组",
    sourceResource: child.sourceResource,
    visible: true,
    summary: "测试",
    createdAt: "2026-01-01T00:00:00.000Z",
    metadata: {},
    symbolization: cloneDefaultGroupSymbolization(),
    children: [child],
  };
}

describe("workspaceSnapshot", () => {
  it("stores lightweight vector layer snapshots without GeoJSON payloads", () => {
    const vectorLayer = makeVectorLayer();
    const snapshot = workspaceSnapshot(
      [makeLayerGroup(vectorLayer)],
      vectorLayer.id,
      null,
    );
    const groups = snapshot.groups as SavedWorkspaceLayerGroup[];
    const savedLayer = groups[0].children[0];

    expect(snapshot.version).toBe(2);
    expect(snapshot.selectedLayerId).toBe(vectorLayer.id);
    expect(savedLayer.layerType).toBe("vector");
    expect(savedLayer.query).toEqual({
      attributeFilters: [],
      spatialFilter: null,
    });
    expect(savedLayer).not.toHaveProperty("geojson");
  });

  it("stores raster render references but not transient job ids", () => {
    const rasterLayer: LoadedRasterLayer = {
      id: "layer-raster",
      name: "栅格图层",
      layerType: "raster",
      sourceResource: makeResource({ dataType: "raster" }),
      tileUrl: "/api/raster/tiles/7/hash/{z}/{x}/{y}.png",
      tileMinZoom: 0,
      tileMaxZoom: 16,
      tileSampling: "nearest",
      imageCoordinates: [
        [80, 45],
        [85, 45],
        [85, 40],
        [80, 40],
      ],
      rasterDatasetId: 7,
      rasterLayerId: 11,
      rasterMetadata: { size: [256, 256], bands: [] },
      renderJobId: "job-1",
      renderStatus: "ready",
      renderProgress: 100,
      renderMessages: ["完成"],
      geometryType: "Raster",
      visible: true,
      summary: "XYZ 瓦片已就绪",
      metadata: { 加载方式: "XYZ 瓦片" },
      symbolization: cloneDefaultRasterSymbolization(),
      fields: [],
    };

    const savedLayer = toSavedWorkspaceLayer(rasterLayer);

    expect(savedLayer.layerType).toBe("raster");
    expect(savedLayer.tileUrl).toBe(rasterLayer.tileUrl);
    expect(savedLayer.tileMaxZoom).toBe(16);
    expect(savedLayer.tileSampling).toBe("nearest");
    expect(savedLayer.rasterDatasetId).toBe(7);
    expect(savedLayer.renderStatus).toBe("ready");
    expect(savedLayer).not.toHaveProperty("renderJobId");
  });

  it("detects hydrated vector layers that already include GeoJSON", () => {
    const loadedLayer = makeVectorLayer();
    const savedLayer = toSavedWorkspaceLayer(loadedLayer);

    expect(isLoadedVectorLayer(loadedLayer)).toBe(true);
    expect(isLoadedVectorLayer(savedLayer)).toBe(false);
  });
});
