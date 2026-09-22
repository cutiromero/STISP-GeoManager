import { describe, expect, it } from "vitest";
import {
  addJpegDpiMetadata,
  addPngDpiMetadata,
  createExportStyle,
  createMapRangeExportPlan,
  inferBasemapTileZoomRange,
} from "./mapExport";

const rectangleGeometry = {
  type: "Polygon",
  coordinates: [
    [
      [80, 40],
      [90, 40],
      [90, 45],
      [80, 45],
      [80, 40],
    ],
  ],
} as const;

describe("mapExport", () => {
  it("uses tile zoom and dpi to calculate the 2D export size", () => {
    const lowZoom = createMapRangeExportPlan(rectangleGeometry, {
      dpi: 96,
      tileZoom: 5,
    });
    const highZoom = createMapRangeExportPlan(rectangleGeometry, {
      dpi: 192,
      tileZoom: 6,
    });

    expect(highZoom.cssWidth).toBeGreaterThan(lowZoom.cssWidth);
    expect(highZoom.outputWidth).toBe(highZoom.cssWidth * 2);
    expect(highZoom.outputHeight).toBe(highZoom.cssHeight * 2);
    expect(highZoom.center[0]).toBeGreaterThan(80);
    expect(highZoom.center[0]).toBeLessThan(90);
  });

  it("expands the export viewport to the target map-frame aspect ratio", () => {
    const plan = createMapRangeExportPlan(rectangleGeometry, {
      dpi: 96,
      tileZoom: 7,
      targetAspect: 16 / 9,
    });

    expect(plan.cssWidth / plan.cssHeight).toBeCloseTo(16 / 9, 2);
    expect(plan.cssWidth).toBeGreaterThan(plan.cssHeight);
  });

  it("adds PNG pHYs metadata for the selected dpi", () => {
    const png = addPngDpiMetadata(minimalPng(), 300);
    const physOffset = findChunk(png, "pHYs");

    expect(physOffset).toBeGreaterThan(0);
    expect(readUint32(png, physOffset + 8)).toBe(11811);
    expect(readUint32(png, physOffset + 12)).toBe(11811);
    expect(png[physOffset + 16]).toBe(1);
  });

  it("adds JPG JFIF metadata for the selected dpi", () => {
    const jpg = addJpegDpiMetadata(minimalJpeg(), 300);
    const jfifOffset = findJpegSegment(jpg, 0xe0);

    expect(jfifOffset).toBe(2);
    expect(readUint32(jpg, jfifOffset + 4)).toBe(0x4a464946);
    expect(jpg[jfifOffset + 11]).toBe(1);
    expect(readUint16(jpg, jfifOffset + 12)).toBe(300);
    expect(readUint16(jpg, jfifOffset + 14)).toBe(300);
  });

  it("removes drawn range overlays while keeping loaded map layers", () => {
    const style = createExportStyle({
      version: 8,
      sources: {
        composite: { type: "vector", url: "mapbox://mapbox.mapbox-streets-v8" },
        satellite: { type: "raster", url: "mapbox://mapbox.satellite" },
        "query-spatial-filter": { type: "geojson", data: emptyFeatures() },
        "query-draw-preview": { type: "geojson", data: emptyFeatures() },
        "loaded-vector": { type: "geojson", data: emptyFeatures() },
        "loaded-raster": {
          type: "raster",
          tiles: ["/api/raster/tiles/1/hash/{z}/{x}/{y}.png"],
          tileSize: 256,
        },
      },
      layers: [
        { id: "background", type: "background" },
        { id: "satellite", type: "raster", source: "satellite" },
        { id: "road-label", type: "symbol", source: "composite" },
        {
          id: "query-spatial-filter-fill",
          type: "fill",
          source: "query-spatial-filter",
        },
        {
          id: "query-draw-preview-line",
          type: "line",
          source: "query-draw-preview",
        },
        { id: "loaded-vector-fill", type: "fill", source: "loaded-vector" },
        { id: "loaded-raster-raster", type: "raster", source: "loaded-raster" },
      ],
    });

    expect(style.sources).not.toHaveProperty("query-spatial-filter");
    expect(style.sources).not.toHaveProperty("query-draw-preview");
    expect(style.sources).not.toHaveProperty("composite");
    expect(style.sources).not.toHaveProperty("satellite");
    expect(style.sources).toHaveProperty("loaded-vector");
    expect(style.sources).toHaveProperty("loaded-raster");
    expect(style.sources).toHaveProperty("map-export-platform-basemap");
    expect(style.sources?.["map-export-platform-basemap"]).toMatchObject({
      type: "raster",
      tiles: [
        "/api/map/thumbnail-tiles/{z}/{x}/{y}.png?purpose=export&basemap=mapbox-satellite",
      ],
      tileSize: 256,
      maxzoom: 22,
    });
    expect(style.layers[1]).toMatchObject({
      id: "map-export-platform-basemap",
      paint: {
        "raster-fade-duration": 0,
        "raster-saturation": -0.55,
        "raster-contrast": -0.1,
      },
    });
    expect(style.layers.map((layer) => layer.id)).toEqual([
      "map-export-background",
      "map-export-platform-basemap",
      "loaded-vector-fill",
      "loaded-raster-raster",
    ]);
  });

  it("proxies Tianditu imagery and labels without changing provider", () => {
    const style = createExportStyle({
      version: 8,
      sources: {
        "basemap-tianditu-vector": {
          type: "raster",
          tiles: [
            "https://t0.tianditu.gov.cn/vec_w/wmts?TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=test-browser-key",
          ],
          tileSize: 256,
          maxzoom: 18,
        },
        "basemap-tianditu-labels": {
          type: "raster",
          tiles: [
            "https://t0.tianditu.gov.cn/cva_w/wmts?TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=test-browser-key",
          ],
          tileSize: 256,
          maxzoom: 18,
        },
        "loaded-vector": { type: "geojson", data: emptyFeatures() },
      },
      layers: [
        {
          id: "basemap-tianditu-vector",
          type: "raster",
          source: "basemap-tianditu-vector",
        },
        {
          id: "basemap-tianditu-labels",
          type: "raster",
          source: "basemap-tianditu-labels",
        },
        { id: "loaded-vector-fill", type: "fill", source: "loaded-vector" },
      ],
    });

    expect(style.sources).not.toHaveProperty("basemap-tianditu-vector");
    expect(style.sources).not.toHaveProperty("basemap-tianditu-labels");
    expect(style.sources).toHaveProperty("map-export-platform-basemap");
    expect(JSON.stringify(style)).not.toContain("test-browser-key");
    expect(style.layers.map((layer) => layer.id)).toEqual([
      "map-export-background",
      "map-export-platform-basemap",
      "map-export-platform-basemap-labels",
      "loaded-vector-fill",
    ]);
  });

  it("infers tile zoom options from basemap layers and excludes loaded data", () => {
    const range = inferBasemapTileZoomRange(
      {
        version: 8,
        sources: {
          "osm-raster": { type: "raster", tiles: [], tileSize: 256 },
          "loaded-vector": { type: "geojson", data: emptyFeatures() },
          "loaded-raster": {
            type: "raster",
            tiles: ["/api/raster/tiles/1/hash/{z}/{x}/{y}.png"],
            tileSize: 256,
          },
        },
        layers: [
          {
            id: "osm-raster",
            type: "raster",
            source: "osm-raster",
            minzoom: 0,
            maxzoom: 19,
          },
          {
            id: "loaded-vector-fill",
            type: "fill",
            source: "loaded-vector",
            maxzoom: 8,
          },
          {
            id: "loaded-raster-raster",
            type: "raster",
            source: "loaded-raster",
            maxzoom: 22,
          },
        ],
      },
      new Set(["loaded-vector", "loaded-raster"]),
    );

    expect(range).toEqual({ min: 0, max: 19 });
  });
});

function minimalPng() {
  const signature = new Uint8Array([
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
  ]);
  return concatBytes([
    signature,
    chunk("IHDR", new Uint8Array(13)),
    chunk("IEND"),
  ]);
}

function minimalJpeg() {
  return new Uint8Array([0xff, 0xd8, 0xff, 0xd9]);
}

function emptyFeatures() {
  return { type: "FeatureCollection", features: [] };
}

function chunk(type: string, data = new Uint8Array()) {
  const typeBytes = new TextEncoder().encode(type);
  const bytes = new Uint8Array(4 + typeBytes.length + data.length + 4);
  writeUint32(bytes, 0, data.length);
  bytes.set(typeBytes, 4);
  bytes.set(data, 8);
  return bytes;
}

function findChunk(bytes: Uint8Array, type: string) {
  let offset = 8;
  while (offset + 12 <= bytes.length) {
    const length = readUint32(bytes, offset);
    const chunkType = String.fromCharCode(
      bytes[offset + 4] ?? 0,
      bytes[offset + 5] ?? 0,
      bytes[offset + 6] ?? 0,
      bytes[offset + 7] ?? 0,
    );
    if (chunkType === type) {
      return offset;
    }
    offset += 12 + length;
  }
  return -1;
}

function findJpegSegment(bytes: Uint8Array, marker: number) {
  let offset = 2;
  while (offset + 4 <= bytes.length && bytes[offset] === 0xff) {
    const currentMarker = bytes[offset + 1];
    const length = readUint16(bytes, offset + 2);
    if (currentMarker === marker) {
      return offset;
    }
    if (length < 2) {
      break;
    }
    offset += 2 + length;
  }
  return -1;
}

function readUint32(bytes: Uint8Array, offset: number) {
  return (
    ((bytes[offset] ?? 0) * 0x1000000 +
      ((bytes[offset + 1] ?? 0) << 16) +
      ((bytes[offset + 2] ?? 0) << 8) +
      (bytes[offset + 3] ?? 0)) >>>
    0
  );
}

function readUint16(bytes: Uint8Array, offset: number) {
  return (((bytes[offset] ?? 0) << 8) + (bytes[offset + 1] ?? 0)) >>> 0;
}

function writeUint32(bytes: Uint8Array, offset: number, value: number) {
  bytes[offset] = (value >>> 24) & 0xff;
  bytes[offset + 1] = (value >>> 16) & 0xff;
  bytes[offset + 2] = (value >>> 8) & 0xff;
  bytes[offset + 3] = value & 0xff;
}

function concatBytes(parts: Uint8Array[]) {
  const output = new Uint8Array(
    parts.reduce((sum, part) => sum + part.length, 0),
  );
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}
