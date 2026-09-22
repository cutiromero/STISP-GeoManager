import { describe, expect, it } from "vitest";
import {
  buildThumbnail,
  isPlatformThumbnailTileUrl,
  thumbnailExtentBox,
  thumbnailFallbackTileUrl,
  thumbnailMapTileForBasemap,
  thumbnailFallbackUrlForFailedTile,
  thumbnailTiles,
  thumbnailUrlTemplateWithRetry,
  thumbnailViewportForMapView,
  thumbnailViewportForMapTile,
  formatRasterPixelCount,
  isRasterInsightSelection,
  nextEcoTabForSelectedFeature,
  rasterBandRangePosition,
} from "./RightSidePanel";
import type {
  DataResourceProfile,
  FeatureInfo,
  LoadedRasterLayer,
  MapViewState,
  ResourceListItem,
} from "../types";

const mapTile = {
  center: [82, 42] as [number, number],
  tileZoom: 6,
  scale: 0.44,
  tileUrlTemplate: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
};

describe("thumbnailTiles", () => {
  it("centers the thumbnail viewport on the configured 2D map tile", () => {
    const viewport = thumbnailViewportForMapTile(mapTile, 290, 174);
    const tiles = thumbnailTiles(
      mapTile.tileZoom,
      viewport,
      290,
      174,
      mapTile.tileUrlTemplate,
    );

    expect(viewport.scale).toBe(0.44);
    expect(tiles.length).toBeGreaterThan(0);
    expect(tiles[0]?.url).toContain("/6/");
  });

  it("requests thumbnail tiles from the platform server", () => {
    const viewport = thumbnailViewportForMapTile(mapTile, 290, 174);
    const tiles = thumbnailTiles(
      mapTile.tileZoom,
      viewport,
      290,
      174,
      "/api/map/thumbnail-tiles/{z}/{x}/{y}.png",
    );

    expect(tiles[0]?.url).toMatch(
      /^\/api\/map\/thumbnail-tiles\/6\/\d+\/\d+\.png$/,
    );
  });

  it("recognizes platform thumbnail tile URLs for automatic retries", () => {
    expect(
      isPlatformThumbnailTileUrl(
        "http://127.0.0.1:5173/api/map/thumbnail-tiles/3/5/2.png",
      ),
    ).toBe(true);
    expect(
      isPlatformThumbnailTileUrl("https://a.tile.openstreetmap.org/3/5/2.png"),
    ).toBe(false);
  });

  it("adds a retry query to platform thumbnail templates", () => {
    expect(
      thumbnailUrlTemplateWithRetry(
        "/api/map/thumbnail-tiles/{z}/{x}/{y}.png",
        42,
      ),
    ).toBe("/api/map/thumbnail-tiles/{z}/{x}/{y}.png?retry=42");
  });

  it("uses the configured scale as the thumbnail zoom ratio", () => {
    const viewport = thumbnailViewportForMapTile(mapTile, 290, 174);
    const visibleWorldWidth = 290 / viewport.scale;
    const visibleWorldHeight = 174 / viewport.scale;

    expect(visibleWorldWidth / visibleWorldHeight).toBeCloseTo(290 / 174, 6);
  });

  it("keeps the current view indicator visible when the view is outside the crop", () => {
    const viewport = thumbnailViewportForMapTile(mapTile, 290, 174);
    const extent = thumbnailExtentBox(
      [105, 25, 110, 30],
      6,
      viewport,
      290,
      174,
    );

    expect(extent.left).toBeGreaterThanOrEqual(0);
    expect(extent.top).toBeGreaterThanOrEqual(0);
    expect(extent.left + extent.width).toBeLessThanOrEqual(290);
    expect(extent.top + extent.height).toBeLessThanOrEqual(174);
    expect(extent.width).toBeGreaterThanOrEqual(10);
    expect(extent.height).toBeGreaterThanOrEqual(10);
  });

  it("overlaps adjacent tile edges to avoid visible seams", () => {
    const tiles = thumbnailTiles(
      6,
      { left: 4000.25, top: 2200.25, scale: 0.37 },
      360,
      180,
    );
    const rows = new Map<number, typeof tiles>();
    for (const tile of tiles) {
      rows.set(tile.top, [...(rows.get(tile.top) ?? []), tile]);
    }

    for (const row of rows.values()) {
      const sorted = [...row].sort((a, b) => a.left - b.left);
      for (let i = 1; i < sorted.length; i += 1) {
        const previous = sorted[i - 1];
        const current = sorted[i];
        expect(
          current.left - (previous.left + previous.width),
        ).toBeLessThanOrEqual(0);
      }
    }
  });

  it("provides a transparent fallback tile for failed thumbnail images", () => {
    expect(thumbnailFallbackTileUrl).toMatch(/^data:image\/gif;base64,/);
  });

  it("retries failed thumbnail tiles on another OSM subdomain before falling back", () => {
    const firstFallback = thumbnailFallbackUrlForFailedTile(
      "https://a.tile.openstreetmap.org/10/747/384.png",
      "",
    );
    const finalFallback = thumbnailFallbackUrlForFailedTile(
      "https://c.tile.openstreetmap.org/10/747/384.png",
      "a,b",
    );

    expect(firstFallback.url).toBe(
      "https://b.tile.openstreetmap.org/10/747/384.png",
    );
    expect(firstFallback.triedSubdomains).toBe("a");
    expect(finalFallback.url).toBe(thumbnailFallbackTileUrl);
  });

  it("uses the configured Mapbox basemap for satellite thumbnails", () => {
    const satelliteTile = thumbnailMapTileForBasemap({
      defaultCenter: [81, 41],
      defaultZoom: 4,
      defaultBasemap: "satellite",
      mapboxAccessToken: "pk.test token",
    });

    expect(satelliteTile.tileUrlTemplate).toBe(
      "/api/map/thumbnail-tiles/{z}/{x}/{y}.png",
    );
    expect(satelliteTile.tileUrlTemplate).not.toContain(
      "tile.openstreetmap.org",
    );
  });

  it("keeps OSM thumbnails when the configured basemap is OSM", () => {
    const osmTile = thumbnailMapTileForBasemap({
      defaultCenter: [81, 41],
      defaultZoom: 4,
      defaultBasemap: "osm",
      mapboxAccessToken: "pk.test-token",
    });

    expect(osmTile.tileUrlTemplate).toBe(
      "/api/map/thumbnail-tiles/{z}/{x}/{y}.png",
    );
  });
});

describe("thumbnailViewportForMapView", () => {
  const currentView: MapViewState = {
    center: [86, 40],
    bounds: [82, 37, 90, 43],
    zoom: 5.8,
    bearing: 0,
    pitch: 0,
  };

  it("centers the thumbnail on the current map viewport instead of a fixed crop", () => {
    const overview = thumbnailViewportForMapView(currentView, 290, 174);
    const thumbnail = buildThumbnail(currentView, 290, 174);

    expect(overview.zoom).toBe(3);
    expect(overview.viewport.scale).toBeGreaterThanOrEqual(0.12);
    expect(thumbnail.extent).not.toBeNull();
    expect(thumbnail.extent?.left).toBeGreaterThan(0);
    expect(thumbnail.extent?.top).toBeGreaterThan(0);
    expect(
      thumbnail.extent?.left + (thumbnail.extent?.width ?? 0),
    ).toBeLessThan(290);
    expect(
      thumbnail.extent?.top + (thumbnail.extent?.height ?? 0),
    ).toBeLessThan(174);
  });

  it("zooms the thumbnail out when the main map covers a wide region", () => {
    const wideView: MapViewState = {
      center: [88, 38],
      bounds: [45, 18, 131, 56],
      zoom: 3.4,
      bearing: 0,
      pitch: 0,
    };
    const overview = thumbnailViewportForMapView(wideView, 290, 174);
    const thumbnail = buildThumbnail(wideView, 290, 174);

    expect(overview.zoom).toBe(1);
    expect(thumbnail.extent).not.toBeNull();
    expect(thumbnail.extent?.left).toBeGreaterThanOrEqual(0);
    expect(thumbnail.extent?.top).toBeGreaterThanOrEqual(0);
    expect(
      thumbnail.extent?.left + (thumbnail.extent?.width ?? 0),
    ).toBeLessThanOrEqual(290);
    expect(
      thumbnail.extent?.top + (thumbnail.extent?.height ?? 0),
    ).toBeLessThanOrEqual(174);
  });

  it("keeps tiles covering the thumbnail height at low zoom", () => {
    const worldView: MapViewState = {
      center: [88, 18],
      bounds: [-180, -60, 180, 75],
      zoom: 2.1,
      bearing: 0,
      pitch: 0,
    };

    const thumbnail = buildThumbnail(worldView, 360, 180);
    const top = Math.min(...thumbnail.tiles.map((tile) => tile.top));
    const bottom = Math.max(
      ...thumbnail.tiles.map((tile) => tile.top + tile.height),
    );

    expect(top).toBeLessThanOrEqual(0);
    expect(bottom).toBeGreaterThanOrEqual(180);
  });

  it("caps thumbnail tile zoom when the main map is zoomed in deeply", () => {
    const closeView: MapViewState = {
      center: [82.84, 40.96],
      bounds: [82.82, 40.94, 82.86, 40.98],
      zoom: 17.2,
      bearing: 0,
      pitch: 0,
    };
    const overview = thumbnailViewportForMapView(closeView, 290, 174);
    const thumbnail = buildThumbnail(closeView, 290, 174);

    expect(overview.zoom).toBe(10);
    expect(thumbnail.tiles.every((tile) => tile.url.includes("/10/"))).toBe(
      true,
    );
  });
});

describe("nextEcoTabForSelectedFeature", () => {
  const feature: FeatureInfo = {
    layerId: "layer-1",
    layerName: "样地监测点",
    properties: { 编号: "GA344" },
  };

  it("switches the ecology panel to the feature tab when a map feature is selected", () => {
    expect(nextEcoTabForSelectedFeature("overview", feature)).toBe("feature");
    expect(nextEcoTabForSelectedFeature("monitor", feature)).toBe("feature");
  });

  it("switches the ecology panel to the feature tab when a layer is selected", () => {
    expect(nextEcoTabForSelectedFeature("overview", null, "layer-1")).toBe(
      "feature",
    );
    expect(nextEcoTabForSelectedFeature("monitor", null, "layer-1")).toBe(
      "feature",
    );
  });

  it("keeps the current tab when the selected feature is cleared", () => {
    expect(nextEcoTabForSelectedFeature("feature", null)).toBe("feature");
    expect(nextEcoTabForSelectedFeature("monitor", null)).toBe("monitor");
  });
});

describe("raster insight helpers", () => {
  it("identifies raster resources before they are loaded as map layers", () => {
    const resource = { dataType: "raster" } as ResourceListItem;
    const profile = { raster: { id: 7 } } as DataResourceProfile;
    const layer = { layerType: "raster" } as LoadedRasterLayer;

    expect(isRasterInsightSelection(resource, null, null)).toBe(true);
    expect(isRasterInsightSelection(null, profile, null)).toBe(true);
    expect(isRasterInsightSelection(null, null, layer)).toBe(true);
    expect(
      isRasterInsightSelection(
        { dataType: "vector" } as ResourceListItem,
        null,
        null,
      ),
    ).toBe(false);
  });

  it("positions every band against one shared value domain", () => {
    expect(rasterBandRangePosition(20, 60, 0, 100)).toEqual({
      left: 20,
      width: 40,
    });
    expect(rasterBandRangePosition(-10, 10, -20, 20)).toEqual({
      left: 25,
      width: 50,
    });
    expect(rasterBandRangePosition(20, 20, 0, 20)).toEqual({
      left: 98,
      width: 2,
    });
    expect(rasterBandRangePosition(null, 10, 0, 20)).toBeNull();
  });

  it("formats large raster cell counts without implying feature records", () => {
    expect(formatRasterPixelCount(226_000_000)).toBe("226 百万");
    expect(formatRasterPixelCount(12_500)).toBe("1.25 万");
    expect(formatRasterPixelCount(null)).toBe("-");
  });
});
