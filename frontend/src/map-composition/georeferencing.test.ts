import { describe, expect, it } from "vitest";
import { boundsImagePlan } from "./mapImage";
import { scaleBarMetrics } from "./canvasScale";
import { createExportStyle } from "../map/mapExport";

describe("cartographic georeferencing", () => {
  it("ties the labelled distance to the map, independently of the scale box", () => {
    for (const width of [100, 200]) {
      const scale = scaleBarMetrics([0, -1, 4, 1], 1000, width);
      expect(
        scale.width * ((((4 * Math.PI) / 180) * 6378137) / 1000),
      ).toBeCloseTo(scale.distance, 8);
      expect(scale.width).toBeLessThanOrEqual(width);
    }
  });
  it.each([150, 300])(
    "keeps known Mercator control points registered at %i DPI",
    (dpi) => {
      for (const [mmW, mmH] of [
        [190, 240],
        [240, 190],
        [277, 380],
        [380, 277],
      ]) {
        const width = Math.round((mmW * dpi) / 25.4),
          height = Math.round((mmH * dpi) / 25.4);
        const plan = boundsImagePlan([100, 20, 101, 40], width, height);
        const [west, south, east, north] = plan.bounds;
        expect(west).toBeLessThan(100);
        expect(east).toBeGreaterThan(101);
        const merc = (lat: number) =>
          Math.asinh(Math.tan((lat * Math.PI) / 180));
        const lonPerPixel = (east - west) / width;
        const mercPerPixel = (merc(north) - merc(south)) / height;
        expect((lonPerPixel * Math.PI) / 180).toBeCloseTo(mercPerPixel, 10);
        // The requested centre falls at the same pixel in the image, grid and overview extent.
        expect(((100.5 - west) / (east - west)) * width).toBeCloseTo(
          width / 2,
          6,
        );
        const scale = scaleBarMetrics(plan.bounds, width, width / 5);
        const center = Math.atan(Math.sinh((merc(north) + merc(south)) / 2));
        expect(
          ((scale.width * lonPerPixel * Math.PI) / 180) *
            6378137 *
            Math.cos(center),
        ).toBeCloseTo(scale.distance, 6);
        expect(plan.outputWidth).toBe(width);
        expect(plan.outputHeight).toBe(height);
      }
    },
  );
  it("retains OSM and street basemaps instead of replacing them with satellite", () => {
    for (const [id, source, maxzoom] of [
      ["osm", "osm-raster", 19],
      ["mapbox-streets", "composite", 22],
    ] as const) {
      const style = createExportStyle({
        version: 8,
        sources: {
          [source]: {
            type: "raster",
            tiles: ["https://example.com/{z}/{x}/{y}.png"],
          },
        },
        layers: [],
      });
      expect(style.sources["map-export-platform-basemap"]).toMatchObject({
        maxzoom,
        tiles: [
          `/api/map/thumbnail-tiles/{z}/{x}/{y}.png?purpose=export&basemap=${id}`,
        ],
      });
    }
  });
});
