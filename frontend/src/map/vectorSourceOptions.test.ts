import { describe, expect, it } from "vitest";
import { cloneDefaultVectorSymbolization } from "../symbolization";
import type {
  GeoJsonFeatureCollection,
  LoadedVectorLayer,
  ResourceListItem,
} from "../types";
import {
  shouldClusterVectorLayer,
  vectorGeojsonSourceOptions,
  vectorSourceKey,
} from "./vectorSourceOptions";

describe("vectorGeojsonSourceOptions", () => {
  it("keeps dense point layers unclustered and disables point tile buffering", () => {
    const options = vectorGeojsonSourceOptions(
      makeLayer({
        geojson: pointFeatures(1000),
        geometryType: "Point",
      }),
    );

    expect(options.maxzoom).toBe(12);
    expect(options.buffer).toBe(0);
    expect(
      shouldClusterVectorLayer(makeLayer({ geojson: pointFeatures(1000) })),
    ).toBe(false);
    expect(options.cluster).toBeUndefined();
    expect(options.clusterMaxZoom).toBeUndefined();
    expect(options.clusterRadius).toBeUndefined();
  });

  it("clusters point layers only when symbolization enables clustering", () => {
    const layer = makeLayer({
      geojson: pointFeatures(1000),
      geometryType: "Point",
    });
    layer.symbolization.cluster = {
      enabled: true,
      maxZoom: 10,
      radius: 36,
    };

    const options = vectorGeojsonSourceOptions(layer);

    expect(shouldClusterVectorLayer(layer)).toBe(true);
    expect(options.cluster).toBe(true);
    expect(options.clusterMaxZoom).toBe(10);
    expect(options.clusterRadius).toBe(36);
  });

  it("does not cluster heatmap point layers", () => {
    const layer = makeLayer({
      geojson: pointFeatures(1000),
      geometryType: "Point",
    });
    layer.symbolization.pointMode = "heatmap";
    layer.symbolization.cluster.enabled = true;

    expect(shouldClusterVectorLayer(layer)).toBe(false);
    expect(vectorGeojsonSourceOptions(layer).cluster).toBeUndefined();
  });

  it("keeps small point layers unclustered while using zero source buffer", () => {
    const options = vectorGeojsonSourceOptions(
      makeLayer({
        geojson: pointFeatures(20),
        geometryType: "Point",
      }),
    );

    expect(options.maxzoom).toBe(12);
    expect(options.buffer).toBe(0);
    expect(options.cluster).toBeUndefined();
  });

  it("adds tolerance to large non-point layers", () => {
    const options = vectorGeojsonSourceOptions(
      makeLayer({
        geojson: polygonFeatures(2000),
        geometryType: "Polygon",
      }),
    );

    expect(options.maxzoom).toBe(16);
    expect(options.buffer).toBeUndefined();
    expect(options.cluster).toBeUndefined();
    expect(options.tolerance).toBe(0.75);
  });

  it("changes the source key when point clustering changes source options", () => {
    const circleLayer = makeLayer({
      geojson: pointFeatures(1000),
      geometryType: "Point",
    });
    const clusteredLayer = makeLayer({
      geojson: pointFeatures(1000),
      geometryType: "Point",
    });
    clusteredLayer.symbolization.cluster.enabled = true;

    expect(vectorSourceKey(circleLayer)).not.toBe(
      vectorSourceKey(clusteredLayer),
    );
  });
});

function makeLayer(
  overrides: Partial<LoadedVectorLayer> = {},
): LoadedVectorLayer {
  return {
    id: "vector-layer",
    name: "Vector layer",
    layerType: "vector",
    sourceResource: makeResource(),
    geojson: pointFeatures(1),
    geometryType: "Point",
    visible: true,
    summary: "",
    metadata: {},
    symbolization: cloneDefaultVectorSymbolization(),
    fields: [],
    ...overrides,
  };
}

function makeResource(): ResourceListItem {
  return {
    id: 1,
    name: "Vector resource",
    code: "vector-resource",
    dataType: "vector",
    category: null,
    source: "",
    provider: "",
    dataDate: null,
    spatialExtent: "",
    coordinateSystem: "EPSG:4326",
    fileFormat: "GeoJSON",
    description: "",
    qualityNote: "",
    status: "active",
    isQueryable: true,
    isRenderable: true,
    updatedAt: "2026-01-01",
  };
}

function pointFeatures(count: number): GeoJsonFeatureCollection {
  return {
    type: "FeatureCollection",
    features: Array.from({ length: count }, (_, index) => ({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [80 + index * 0.0001, 40],
      },
      properties: {},
    })),
  };
}

function polygonFeatures(count: number): GeoJsonFeatureCollection {
  return {
    type: "FeatureCollection",
    features: Array.from({ length: count }, (_, index) => {
      const offset = index * 0.0001;
      return {
        type: "Feature",
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [80 + offset, 40],
              [80.01 + offset, 40],
              [80.01 + offset, 40.01],
              [80 + offset, 40.01],
              [80 + offset, 40],
            ],
          ],
        },
        properties: {},
      };
    }),
  };
}
