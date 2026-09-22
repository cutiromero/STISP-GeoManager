import { describe, expect, it } from "vitest";
import type { LoadedLayerGroup } from "../types";
import {
  boundsFromImageCoordinates,
  circleGeometry,
  clamp,
  combinedFeatureBounds,
  delay,
  ellipseGeometry,
  extractLayerToStandalone,
  extractCoordinates,
  geometryFromBoundsText,
  geometryFromPoints,
  moveLayerBetweenGroups,
  normalizeDisplayLngLat,
  polygonGeometry,
  rasterSourceKey,
  rectangleGeometry,
  reorderLayerGroups,
  sourceIdFor,
} from "./geometry";

describe("rectangleGeometry", () => {
  it("creates a closed polygon from two corners", () => {
    const geo = rectangleGeometry([10, 20], [30, 40]);
    expect(geo.type).toBe("Polygon");
    const coords = (geo as { coordinates: number[][][] }).coordinates[0];
    expect(coords).toHaveLength(5);
    expect(coords[0]).toEqual(coords[4]);
    expect(coords[0][0]).toBe(10);
    expect(coords[2][0]).toBe(30);
  });

  it("normalizes order when start > end", () => {
    const geo = rectangleGeometry([30, 40], [10, 20]);
    const coords = (geo as { coordinates: number[][][] }).coordinates[0];
    expect(coords[0][0]).toBe(10);
    expect(coords[2][0]).toBe(30);
  });
});

describe("geometryFromBoundsText", () => {
  it("creates a rectangle from comma separated bounds", () => {
    const geo = geometryFromBoundsText("80,40,85,45");
    expect(geo?.type).toBe("Polygon");
    const coords = (geo as { coordinates: number[][][] }).coordinates[0];
    expect(coords[0]).toEqual([80, 40]);
    expect(coords[2]).toEqual([85, 45]);
  });

  it("returns null for invalid bounds", () => {
    expect(geometryFromBoundsText("")).toBeNull();
    expect(geometryFromBoundsText("200,40,205,45")).toBeNull();
    expect(geometryFromBoundsText("80,40,80,45")).toBeNull();
  });
});

describe("circleGeometry", () => {
  it("creates a polygon with 73 points", () => {
    const geo = circleGeometry([0, 0], [1, 0]);
    const coords = (geo as { coordinates: number[][][] }).coordinates[0];
    expect(coords).toHaveLength(73);
    expect(coords[0][0]).toBeCloseTo(coords[72][0]);
    expect(coords[0][1]).toBeCloseTo(coords[72][1]);
  });
});

describe("ellipseGeometry", () => {
  it("creates a polygon", () => {
    const geo = ellipseGeometry([0, 0], [2, 1]);
    expect(geo.type).toBe("Polygon");
  });
});

describe("polygonGeometry", () => {
  it("closes the ring", () => {
    const geo = polygonGeometry([
      [0, 0],
      [1, 0],
      [1, 1],
    ]);
    const coords = (geo as { coordinates: number[][][] }).coordinates[0];
    expect(coords).toHaveLength(4);
    expect(coords[0]).toEqual(coords[3]);
  });

  it("handles empty points", () => {
    const geo = polygonGeometry([]);
    const coords = (geo as { coordinates: number[][][] }).coordinates[0];
    expect(coords).toHaveLength(0);
  });
});

describe("geometryFromPoints", () => {
  it("delegates to rectangleGeometry for rectangle mode", () => {
    const geo = geometryFromPoints("rectangle", [0, 0], [1, 1]);
    expect(geo.type).toBe("Polygon");
  });

  it("delegates to circleGeometry for circle mode", () => {
    const geo = geometryFromPoints("circle", [0, 0], [1, 0]);
    const coords = (geo as { coordinates: number[][][] }).coordinates[0];
    expect(coords).toHaveLength(73);
  });
});

describe("clamp", () => {
  it("clamps below min", () => expect(clamp(-5, 0, 10)).toBe(0));
  it("clamps above max", () => expect(clamp(15, 0, 10)).toBe(10));
  it("returns value in range", () => expect(clamp(5, 0, 10)).toBe(5));
});

describe("normalizeDisplayLngLat", () => {
  it("uses Mapbox wrap output before display formatting", () => {
    const normalized = normalizeDisplayLngLat({
      wrap: () => ({ lng: -179.87654, lat: 43.98765 }),
    });

    expect(normalized?.[0]).toBeCloseTo(-179.87654);
    expect(normalized?.[1]).toBeCloseTo(43.98765);
  });

  it("keeps display coordinates inside valid longitude and latitude ranges", () => {
    const normalized = normalizeDisplayLngLat({
      wrap: () => ({ lng: 181, lat: 91 }),
    });

    expect(normalized).toEqual([180, 90]);
  });

  it("returns null for invalid coordinates", () => {
    expect(
      normalizeDisplayLngLat({
        wrap: () => ({ lng: Number.NaN, lat: 43 }),
      }),
    ).toBeNull();
  });
});

describe("sourceIdFor", () => {
  it("prefixes with loaded-", () =>
    expect(sourceIdFor("abc")).toBe("loaded-abc"));
});

describe("rasterSourceKey", () => {
  it("returns JSON string", () => {
    const key = rasterSourceKey({ tileUrl: "a/{z}/{x}/{y}.png" });
    expect(() => JSON.parse(key)).not.toThrow();
  });

  it("differs for different urls", () => {
    const k1 = rasterSourceKey({ tileUrl: "a/{z}/{x}/{y}.png" });
    const k2 = rasterSourceKey({ tileUrl: "b/{z}/{x}/{y}.png" });
    expect(k1).not.toBe(k2);
  });

  it("differs for different raster bounds", () => {
    const k1 = rasterSourceKey({
      tileUrl: "a/{z}/{x}/{y}.png",
      imageCoordinates: [
        [80, 45],
        [85, 45],
        [85, 40],
        [80, 40],
      ],
    });
    const k2 = rasterSourceKey({
      tileUrl: "a/{z}/{x}/{y}.png",
      imageCoordinates: [
        [90, 45],
        [95, 45],
        [95, 40],
        [90, 40],
      ],
    });
    expect(k1).not.toBe(k2);
  });

  it("differs when the native tile zoom range changes", () => {
    const k1 = rasterSourceKey({
      tileUrl: "a/{z}/{x}/{y}.png",
      tileMinZoom: 0,
      tileMaxZoom: 15,
    });
    const k2 = rasterSourceKey({
      tileUrl: "a/{z}/{x}/{y}.png",
      tileMinZoom: 0,
      tileMaxZoom: 16,
    });
    expect(k1).not.toBe(k2);
  });
});

describe("delay", () => {
  it("resolves after specified ms", async () => {
    const start = Date.now();
    await delay(50);
    expect(Date.now() - start).toBeGreaterThanOrEqual(40);
  });
});

describe("reorderLayerGroups", () => {
  const groups = [
    { id: "a", name: "A" },
    { id: "b", name: "B" },
    { id: "c", name: "C" },
  ] as LoadedLayerGroup[];

  it("moves group before target", () => {
    const result = reorderLayerGroups(groups, "c", "a", "before");
    expect(result.map((g) => g.id)).toEqual(["c", "a", "b"]);
  });

  it("moves group after target", () => {
    const result = reorderLayerGroups(groups, "a", "c", "after");
    expect(result.map((g) => g.id)).toEqual(["b", "c", "a"]);
  });

  it("returns same array if source not found", () => {
    expect(reorderLayerGroups(groups, "x", "a", "before")).toBe(groups);
  });

  it("returns same array if target not found", () => {
    expect(reorderLayerGroups(groups, "a", "x", "before")).toBe(groups);
  });

  it("returns same array if source equals target", () => {
    expect(reorderLayerGroups(groups, "a", "a", "before")).toBe(groups);
  });
});

describe("moveLayerBetweenGroups", () => {
  it("reorders standalone loaded layers instead of nesting them", () => {
    const groups = [
      testGroup("first", [testLayer("layer-1")]),
      testGroup("second", [testLayer("layer-2")]),
    ];

    const result = moveLayerBetweenGroups(
      groups,
      "first",
      "layer-1",
      "second",
      "layer-2",
      "after",
    );

    expect(result.map((group) => group.id)).toEqual(["second", "first"]);
    expect(result.every((group) => group.children.length === 1)).toBe(true);
  });

  it("extracts a grouped layer back to the top level", () => {
    const groups = [
      { ...testGroup("manual", [testLayer("layer-1")]), isManual: true },
      testGroup("target", [testLayer("layer-2")]),
    ];

    const result = moveLayerBetweenGroups(
      groups,
      "manual",
      "layer-1",
      "target",
      "layer-2",
      "before",
    );

    expect(
      result.map((group) => group.children.map((layer) => layer.id)),
    ).toEqual([[], ["layer-1"], ["layer-2"]]);
    expect(result[0].id).toBe("manual");
    expect(result[0].isManual).toBe(true);
    expect(result[1].id).toMatch(/^ungrouped-layer-1-/);
    expect(result[2].id).toBe("target");
  });
});

describe("extractLayerToStandalone", () => {
  it("moves a grouped layer before a target top-level item", () => {
    const groups = [
      { ...testGroup("manual", [testLayer("layer-1")]), isManual: true },
      testGroup("target", [testLayer("layer-2")]),
    ];

    const result = extractLayerToStandalone(
      groups,
      "manual",
      "layer-1",
      "target",
      "before",
    );

    expect(
      result.map((group) => group.children.map((layer) => layer.id)),
    ).toEqual([[], ["layer-1"], ["layer-2"]]);
    expect(result[0].id).toBe("manual");
    expect(result[1].id).toMatch(/^ungrouped-layer-1-/);
    expect(result[2].id).toBe("target");
  });
});

describe("extractCoordinates", () => {
  it("extracts point coordinates", () => {
    const points: [number, number][] = [];
    extractCoordinates([10, 20], points);
    expect(points).toEqual([[10, 20]]);
  });

  it("recursively extracts nested coordinates", () => {
    const points: [number, number][] = [];
    extractCoordinates(
      [
        [
          [1, 2],
          [3, 4],
        ],
      ],
      points,
    );
    expect(points).toEqual([
      [1, 2],
      [3, 4],
    ]);
  });

  it("ignores non-array input", () => {
    const points: [number, number][] = [];
    extractCoordinates("not an array", points);
    expect(points).toEqual([]);
  });
});

function testGroup(
  id: string,
  children: LoadedLayerGroup["children"],
): LoadedLayerGroup {
  return {
    id,
    name: id,
    sourceResource: {
      id: 1,
      name: id,
      code: id,
      dataType: "vector",
      category: null,
      source: "",
      provider: "",
      dataDate: null,
      spatialExtent: "",
      coordinateSystem: "",
      fileFormat: "",
      description: "",
      qualityNote: "",
      sizeBytes: 0,
      itemCount: 0,
      status: "active",
      isQueryable: true,
      isRenderable: true,
      updatedAt: "2026-06-20T00:00:00.000Z",
    },
    visible: true,
    summary: id,
    createdAt: "2026-06-20T00:00:00.000Z",
    metadata: {},
    symbolization: {
      opacity: 1,
    },
    children,
  } as LoadedLayerGroup;
}

function testLayer(id: string): LoadedLayerGroup["children"][number] {
  return {
    id,
    name: id,
    layerType: "vector",
    sourceResource: testGroup("resource", []).sourceResource,
    geojson: { type: "FeatureCollection", features: [] },
    geometryType: "Point",
    visible: true,
    summary: id,
    metadata: {},
    symbolization: {
      opacity: 1,
    },
    fields: [],
  } as LoadedLayerGroup["children"][number];
}

describe("combinedFeatureBounds", () => {
  it("returns null for empty collections", () => {
    expect(combinedFeatureBounds([])).toBeNull();
  });

  it("returns bounds for features with coordinates", () => {
    const fc = {
      type: "FeatureCollection" as const,
      features: [
        {
          type: "Feature" as const,
          properties: {},
          geometry: { type: "Point", coordinates: [10, 20] },
        },
        {
          type: "Feature" as const,
          properties: {},
          geometry: { type: "Point", coordinates: [30, 40] },
        },
      ],
    };
    const bounds = combinedFeatureBounds([fc]);
    expect(bounds).not.toBeNull();
    expect(bounds?.getWest()).toBe(10);
    expect(bounds?.getEast()).toBe(30);
    expect(bounds?.getSouth()).toBe(20);
    expect(bounds?.getNorth()).toBe(40);
  });
});

describe("boundsFromImageCoordinates", () => {
  it("returns null for empty array", () => {
    expect(boundsFromImageCoordinates([])).toBeNull();
  });

  it("returns bounds from coordinates", () => {
    const bounds = boundsFromImageCoordinates([
      [10, 20],
      [30, 40],
    ]);
    expect(bounds).not.toBeNull();
    expect(bounds?.getWest()).toBe(10);
    expect(bounds?.getEast()).toBe(30);
  });
});
