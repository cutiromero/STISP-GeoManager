import { describe, expect, it } from "vitest";
import {
  applyViewportResult,
  exactViewportExportQuery,
  isLargeVectorResource,
  isViewportVectorLayer,
  viewportQueryPayload,
} from "./viewportVectorQuery";
import { createEmptyLayerGroup } from "../utils/layerFactory";
import { cloneDefaultVectorSymbolization } from "../symbolization";
import type { LoadedVectorLayer, ResourceQueryResult } from "../types";

export function largeLayer(): LoadedVectorLayer {
  return {
    id: "points",
    name: "灾害点",
    layerType: "vector",
    visible: true,
    geometryType: "Point",
    summary: "",
    metadata: {},
    fields: [],
    sourceResource: {
      ...createEmptyLayerGroup("test").sourceResource,
      id: 7,
      itemCount: 39953,
      sizeBytes: 10000000,
    },
    symbolization: cloneDefaultVectorSymbolization(),
    geojson: { type: "FeatureCollection", features: [] },
  };
}
describe("viewport vector display", () => {
  it("refetches original geometry for preview exports using the same extent and limit", () => {
    const layer = largeLayer();
    const body = viewportQueryPayload(
      [-180, -85, 180, 85],
      10000,
      "MultiLineString",
    );
    layer.metadata.视野查询键 = JSON.stringify([7, "revision", body]);
    const exact = exactViewportExportQuery(layer)!;
    expect(exact.limit).toBe(body.limit);
    expect(exact.spatialFilter).toEqual(body.spatialFilter);
    expect(exact.displayGeometry).toBeUndefined();
    expect(exact.lineSimplifyTolerance).toBeUndefined();
    expect(
      exactViewportExportQuery({
        ...layer,
        query: { attributeFilters: [], spatialFilter: body.spatialFilter },
      }),
    ).toBeNull();
  });
  it("bounds point requests to the view and preserves explicit-query budgets", () => {
    const q = viewportQueryPayload([85, 40, 90, 45], 10000, "Point");
    expect(q.limit).toBe(1500);
    expect(q.displayGeometry).toBe(true);
    expect(q.spatialFilter?.geometry.coordinates).toEqual([
      [
        [85, 40],
        [90, 40],
        [90, 45],
        [85, 45],
        [85, 40],
      ],
    ]);
    expect(
      viewportQueryPayload([85, 40, 90, 45], 10000, "MultiLineString").limit,
    ).toBe(10000);
    expect(viewportQueryPayload([85, 40, 90, 45], 200, "Point").limit).toBe(
      200,
    );
  });
  it("restores line detail when zooming in and keeps points and polygons unsimplified", () => {
    const world = viewportQueryPayload(
      [-180, -85, 180, 85],
      30000,
      "MultiLineString",
    );
    const region = viewportQueryPayload([85, 40, 90, 45], 30000, "LineString");
    const close = viewportQueryPayload(
      [85, 40, 85.001, 40.001],
      30000,
      "LineString",
    );
    expect(world.limit).toBe(10000);
    expect(world.lineSimplifyTolerance).toBe(0.05);
    expect(region.lineSimplifyTolerance).toBeLessThan(
      world.lineSimplifyTolerance!,
    );
    expect(close.lineSimplifyTolerance).toBeUndefined();
    expect(
      viewportQueryPayload([85, 40, 90, 45], 30000, "Point")
        .lineSimplifyTolerance,
    ).toBeUndefined();
    expect(
      viewportQueryPayload([85, 40, 90, 45], 30000, "Polygon")
        .lineSimplifyTolerance,
    ).toBeUndefined();
    expect(
      viewportQueryPayload([85, 40, 90, 45], 200, "LineString").limit,
    ).toBe(200);
  });
  it("splits dateline views without broadening them to the whole world", () => {
    const g = viewportQueryPayload([170, -10, 190, 10], 10000, "Point")
      .spatialFilter!.geometry;
    expect(g.type).toBe("MultiPolygon");
    expect(g.coordinates).toEqual([
      [
        [
          [170, -10],
          [180, -10],
          [180, 10],
          [170, 10],
          [170, -10],
        ],
      ],
      [
        [
          [-180, -10],
          [-170, -10],
          [-170, 10],
          [-180, 10],
          [-180, -10],
        ],
      ],
    ]);
    expect(() => viewportQueryPayload([NaN, 0, 90, 40], 1000)).toThrow();
  });
  it("upgrades old large source layers and leaves user queries and small layers intact", () => {
    const l = largeLayer();
    expect(isLargeVectorResource(l.sourceResource)).toBe(true);
    expect(isViewportVectorLayer(l)).toBe(true);
    expect(
      isViewportVectorLayer({
        ...l,
        query: {
          attributeFilters: [],
          spatialFilter: viewportQueryPayload([85, 40, 90, 45], 1000)
            .spatialFilter,
        },
      }),
    ).toBe(false);
    expect(
      isViewportVectorLayer({
        ...l,
        query: {
          attributeFilters: [
            { id: "a", field: "year", operator: "eq", value: "2000" },
          ],
          spatialFilter: null,
        },
      }),
    ).toBe(false);
    expect(
      isViewportVectorLayer({
        ...l,
        sourceResource: { ...l.sourceResource, itemCount: 10, sizeBytes: 100 },
      }),
    ).toBe(false);
  });
  it("clears old features on empty responses and marks capped results", () => {
    const l = largeLayer();
    l.geojson.features = [
      {
        type: "Feature",
        id: 1,
        properties: {},
        geometry: { type: "Point", coordinates: [85, 40] },
      },
    ];
    const result = {
      geojson: { type: "FeatureCollection", features: [] },
      fields: [],
      totalCount: 0,
      returnedCount: 0,
      limit: 1500,
      limitExceeded: false,
    } as ResourceQueryResult;
    expect(applyViewportResult(l, result).geojson.features).toEqual([]);
    expect(
      applyViewportResult(l, {
        ...result,
        totalCount: 2000,
        returnedCount: 1500,
        limitExceeded: true,
      }).summary,
    ).toContain("已达显示上限");
  });
});
